
import os
import io
from datetime import date, timedelta
import requests
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Upstox 5-Min Reference Candle Backtester", layout="wide")

API_BASE = "https://api.upstox.com/v3/historical-candle"


# ------------------------------------------------------------
# UPSTOX DATA
# ------------------------------------------------------------
def get_candles(token, instrument_key, from_date, to_date):
    url = f"{API_BASE}/{instrument_key}/minutes/5/{to_date}/{from_date}"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }

    response = requests.get(url, headers=headers, timeout=45)

    if response.status_code != 200:
        raise RuntimeError(
            f"Upstox API {response.status_code}: {response.text[:500]}"
        )

    candles = response.json().get("data", {}).get("candles", [])

    rows = []
    for candle in candles:
        rows.append([
            candle[0],
            float(candle[1]),
            float(candle[2]),
            float(candle[3]),
            float(candle[4]),
            float(candle[5]) if len(candle) > 5 and candle[5] is not None else 0,
        ])

    return pd.DataFrame(
        rows,
        columns=["timestamp", "open", "high", "low", "close", "volume"]
    )


def download_history(token, instrument_key, start, end, progress=None, status=None):
    # Conservative 28-day chunks to stay below Upstox minute-data range limits.
    parts = []
    current = start
    total_days = max((end - start).days + 1, 1)
    completed_days = 0

    while current <= end:
        chunk_end = min(current + timedelta(days=27), end)

        message = f"Downloading {current} → {chunk_end}"

        if progress is not None:
            progress.progress(
                min(completed_days / total_days, 0.99),
                text=message
            )

        if status is not None:
            status.info(message)

        chunk = get_candles(
            token,
            instrument_key,
            current.isoformat(),
            chunk_end.isoformat()
        )

        if len(chunk) > 0:
            parts.append(chunk)

        completed_days += (chunk_end - current).days + 1
        current = chunk_end + timedelta(days=1)

    if not parts:
        return pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )

    data = pd.concat(parts, ignore_index=True)
    data = data.drop_duplicates(subset=["timestamp"])
    data["timestamp"] = pd.to_datetime(data["timestamp"])

    # Upstox timestamps are converted to IST.
    if getattr(data["timestamp"].dt, "tz", None) is not None:
        data["timestamp"] = (
            data["timestamp"]
            .dt.tz_convert("Asia/Kolkata")
            .dt.tz_localize(None)
        )

    data = data.sort_values("timestamp").reset_index(drop=True)

    if progress is not None:
        progress.progress(1.0, text="Download complete")

    return data


# ------------------------------------------------------------
# REFERENCE CANDLE
# ------------------------------------------------------------
def build_daily_reference_table(data, reference_start, reference_end):
    """
    IMPORTANT:
    For EVERY trading day, the selected 5-minute candle is found independently.

    Example:
      09:40-09:45 candle
      Reference High = THAT candle's High
      Reference Low  = THAT candle's Low

    The next day gets a completely new High/Low.
    """

    x = data.copy()
    x["Date"] = x["timestamp"].dt.date
    x["Time"] = x["timestamp"].dt.strftime("%H:%M")

    rows = []

    for trading_date, day in x.groupby("Date", sort=True):
        ref = day[day["Time"] == reference_start]

        if len(ref) == 0:
            continue

        candle = ref.iloc[0]

        rows.append({
            "Date": trading_date,
            "Reference Candle": f"{reference_start}-{reference_end}",
            "Reference Open": float(candle["open"]),
            "Reference High": float(candle["high"]),
            "Reference Low": float(candle["low"]),
            "Reference Close": float(candle["close"]),
            "Reference Timestamp": candle["timestamp"],
        })

    return pd.DataFrame(rows)


# ------------------------------------------------------------
# BACKTEST
# ------------------------------------------------------------
def run_backtest(data, reference_start, reference_end, quantity):
    if len(data) == 0:
        return pd.DataFrame(), pd.DataFrame()

    x = data.copy()
    x["Date"] = x["timestamp"].dt.date
    x["Time"] = x["timestamp"].dt.strftime("%H:%M")

    reference_table = build_daily_reference_table(
        x,
        reference_start,
        reference_end
    )

    trades = []

    for _, reference in reference_table.iterrows():

        trading_date = reference["Date"]

        day = x[x["Date"] == trading_date].copy()

        # Normal NSE session.
        day = day[
            (day["Time"] >= "09:15") &
            (day["Time"] <= "15:15")
        ].sort_values("timestamp")

        reference_timestamp = reference["Reference Timestamp"]

        # CRITICAL:
        # Only candles AFTER the reference candle can trigger an entry.
        after_reference = day[
            day["timestamp"] > reference_timestamp
        ]

        reference_high = float(reference["Reference High"])
        reference_low = float(reference["Reference Low"])

        position = None
        entry = None
        exit_candle = None
        exit_reason = None

        for _, candle in after_reference.iterrows():

            candle_time = candle["timestamp"].strftime("%H:%M")
            close = float(candle["close"])

            # ------------------------------------------------
            # ENTRY
            # ------------------------------------------------
            # Entry is based ONLY on a 5-minute candle CLOSE.
            if position is None and candle_time <= "15:10":

                # BUY breakout
                if close > reference_high:
                    position = "LONG"
                    entry = candle
                    continue

                # SELL breakdown
                if close < reference_low:
                    position = "SHORT"
                    entry = candle
                    continue

            # ------------------------------------------------
            # STOP LOSS
            # ------------------------------------------------
            # SL is also evaluated ONLY on 5-minute candle CLOSE.
            if position == "LONG":
                if close <= reference_low:
                    exit_candle = candle
                    exit_reason = "STOP LOSS"
                    break

            if position == "SHORT":
                if close >= reference_high:
                    exit_candle = candle
                    exit_reason = "STOP LOSS"
                    break

        # ----------------------------------------------------
        # 3:15 PM EXIT
        # ----------------------------------------------------
        if position is not None and exit_candle is None:

            # The 15:10 candle is the 5-minute candle ending at 15:15.
            eod = day[day["Time"] == "15:10"]

            if len(eod) == 0:
                eod = day[day["Time"] <= "15:15"]

            if len(eod) > 0:
                exit_candle = eod.iloc[-1]
                exit_reason = "3:15 PM EXIT"

        if position is None or exit_candle is None:
            continue

        entry_price = float(entry["close"])
        exit_price = float(exit_candle["close"])

        if position == "LONG":
            pnl_points = exit_price - entry_price
        else:
            pnl_points = entry_price - exit_price

        trades.append({
            "Date": trading_date,

            # DAILY REFERENCE CANDLE
            "Reference Candle": reference["Reference Candle"],
            "Reference Open": reference["Reference Open"],
            "Reference High": reference_high,
            "Reference Low": reference_low,
            "Reference Close": reference["Reference Close"],

            # TRADE
            "Direction": position,
            "Entry Time": entry["timestamp"],
            "Entry Price": entry_price,

            # DAILY REFERENCE LEVEL USED AS SL
            "Stop Loss Price": (
                reference_low
                if position == "LONG"
                else reference_high
            ),

            "Exit Time": exit_candle["timestamp"],
            "Exit Price": exit_price,
            "Exit Reason": exit_reason,

            "P&L Points": pnl_points,
            "P&L ₹": pnl_points * quantity,

            "Result": (
                "PROFIT"
                if pnl_points > 0
                else ("LOSS" if pnl_points < 0 else "BREAKEVEN")
            ),
        })

    trades_df = pd.DataFrame(trades)

    if not trades_df.empty:
        trades_df["Cumulative P&L ₹"] = trades_df["P&L ₹"].cumsum()

    return trades_df, reference_table


# ------------------------------------------------------------
# SUMMARY
# ------------------------------------------------------------
def make_summary(trades, start, end, stock, reference_candle, quantity):

    if len(trades) == 0:
        return pd.DataFrame(columns=["Metric", "Value"])

    wins = int((trades["P&L Points"] > 0).sum())
    losses = int((trades["P&L Points"] < 0).sum())
    breakeven = int((trades["P&L Points"] == 0).sum())

    gross_profit = trades.loc[
        trades["P&L Points"] > 0,
        "P&L ₹"
    ].sum()

    gross_loss = trades.loc[
        trades["P&L Points"] < 0,
        "P&L ₹"
    ].sum()

    net_pnl = trades["P&L ₹"].sum()

    win_rate = wins / len(trades) * 100

    profit_factor = (
        gross_profit / abs(gross_loss)
        if float(gross_loss) != 0.0
        else float("inf")
    )

    return pd.DataFrame({
        "Metric": [
            "Stock",
            "Period",
            "Reference Candle",
            "Total Trades",
            "Winning Trades",
            "Losing Trades",
            "Breakeven Trades",
            "Win Rate %",
            "Gross Profit ₹",
            "Gross Loss ₹",
            "Net P&L ₹",
            "Profit Factor",
            "Quantity",
        ],
        "Value": [
            stock,
            f"{start} to {end}",
            reference_candle,
            len(trades),
            wins,
            losses,
            breakeven,
            round(win_rate, 2),
            round(gross_profit, 2),
            round(gross_loss, 2),
            round(net_pnl, 2),
            round(profit_factor, 3)
            if profit_factor != float("inf")
            else "INF",
            quantity,
        ]
    })


# ------------------------------------------------------------
# EXCEL
# ------------------------------------------------------------
def make_excel(trades, references, summary, raw, rules):

    """
    ONE Excel workbook.

    Tabs:
      Summary
      Reference Levels
      All Trades
      2022-08
      2022-09
      ...
      Rules
    """

    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:

        summary.to_excel(
            writer,
            index=False,
            sheet_name="Summary"
        )

        # This is important for verifying the daily High/Low.
        references.to_excel(
            writer,
            index=False,
            sheet_name="Reference Levels"
        )

        trades.to_excel(
            writer,
            index=False,
            sheet_name="All Trades"
        )

        monthly = trades.copy()

        monthly["_month"] = (
            pd.to_datetime(monthly["Date"])
            .dt.strftime("%Y-%m")
        )

        # Every month gets its OWN TAB in the SAME Excel file.
        for month, month_data in monthly.groupby(
            "_month",
            sort=True
        ):

            month_data = month_data.drop(
                columns=["_month"]
            )

            month_data.to_excel(
                writer,
                index=False,
                sheet_name=month
            )

        rules.to_excel(
            writer,
            index=False,
            sheet_name="Rules"
        )

        workbook = writer.book

        for worksheet in workbook.worksheets:

            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions

            for column_cells in worksheet.columns:

                column_letter = (
                    column_cells[0].column_letter
                )

                maximum = 0

                for cell in column_cells[:1000]:

                    value = (
                        ""
                        if cell.value is None
                        else str(cell.value)
                    )

                    maximum = max(
                        maximum,
                        len(value)
                    )

                worksheet.column_dimensions[
                    column_letter
                ].width = min(
                    max(maximum + 2, 10),
                    30
                )

    output.seek(0)

    return output.getvalue()


# ------------------------------------------------------------
# UI
# ------------------------------------------------------------
st.title("📊 Upstox 5-Minute Reference Candle Backtester")

st.caption(
    "Daily reference High/Low • exact selected 5-minute candle • "
    "close-based breakout & stop-loss • 3:15 PM exit • "
    "one Excel workbook with monthly tabs"
)

with st.sidebar:

    st.header("Backtest Settings")

    token = st.text_input(
        "Upstox Access Token",
        type="password",
        value=os.getenv(
            "UPSTOX_ACCESS_TOKEN",
            ""
        )
    )

    instrument = st.text_input(
        "Upstox Instrument Key",
        value="NSE_EQ|INE848E01016"
    )

    stock = st.text_input(
        "Stock Name",
        value="GODREJPROP"
    )

    start = st.date_input(
        "Start Date",
        value=date(2022, 8, 15)
    )

    end = st.date_input(
        "End Date",
        value=date(2026, 8, 14)
    )

    available_times = [
        f"{hour:02d}:{minute:02d}"
        for hour in range(9, 16)
        for minute in (
            0, 5, 10, 15, 20, 25,
            30, 35, 40, 45, 50, 55
        )
        if not (
            hour == 15 and minute > 10
        )
    ]

    reference_start = st.selectbox(
        "Reference Candle Start",
        available_times,
        index=available_times.index(
            "09:40"
        )
    )

    reference_end = (
        pd.Timestamp(reference_start)
        + pd.Timedelta(minutes=5)
    ).strftime("%H:%M")

    st.success(
        f"Reference Candle: "
        f"{reference_start} → {reference_end}"
    )

    quantity = st.number_input(
        "Quantity",
        min_value=1,
        value=1,
        step=1
    )

    run_backtest = st.button(
        "🚀 Run 4-Year Backtest",
        type="primary",
        use_container_width=True
    )


if run_backtest:

    if not token:
        st.error(
            "Enter your Upstox Access Token."
        )
        st.stop()

    if "|" not in instrument:
        st.error(
            "Enter a valid Upstox Instrument Key."
        )
        st.stop()

    if start >= end:
        st.error(
            "Start Date must be before End Date."
        )
        st.stop()

    progress = st.progress(
        0,
        text="Starting..."
    )

    status = st.empty()

    try:

        raw = download_history(
            token,
            instrument,
            start,
            end,
            progress,
            status
        )

        if raw.empty:
            st.error(
                "No data returned by Upstox. "
                "Check the instrument key, token and dates."
            )
            st.stop()

        status.success(
            f"Downloaded {len(raw):,} 5-minute candles."
        )

        trades, references = run_backtest(
            raw,
            reference_start,
            reference_end,
            quantity
        )

        if len(references) == 0:
            st.warning(
                "No reference candles were found."
            )
            st.stop()

        # ----------------------------------------------------
        # SHOW DAILY REFERENCE LEVELS
        # ----------------------------------------------------
        st.subheader(
            "🔴 Daily Reference Levels"
        )

        st.caption(
            "CHECK THIS TABLE against TradingView. "
            "Reference High/Low are the actual High/Low of the selected "
            "5-minute candle for each individual trading day."
        )

        st.info(
            "Reference High and Reference Low are recalculated "
            "from the selected candle independently for EVERY "
            "trading day."
        )

        st.dataframe(
            references[
                [
                    "Date",
                    "Reference Candle",
                    "Reference Open",
                    "Reference High",
                    "Reference Low",
                    "Reference Close",
                ]
            ],
            use_container_width=True,
            hide_index=True
        )

        if len(trades) == 0:
            st.warning(
                "Reference candles were found, but no breakout "
                "trades were generated."
            )
            st.stop()

        summary = make_summary(
            trades,
            start,
            end,
            stock,
            f"{reference_start}-{reference_end}",
            quantity
        )

        columns = st.columns(6)

        columns[0].metric(
            "Trades",
            len(trades)
        )

        columns[1].metric(
            "Win Rate",
            f"{(trades['P&L Points'] > 0).mean() * 100:.2f}%"
        )

        columns[2].metric(
            "Net P&L",
            f"₹{trades['P&L ₹'].sum():,.2f}"
        )

        gross_profit = trades.loc[
            trades["P&L Points"] > 0,
            "P&L ₹"
        ].sum()

        gross_loss = trades.loc[
            trades["P&L Points"] < 0,
            "P&L ₹"
        ].sum()

        columns[3].metric(
            "Profit Factor",
            (
                f"{gross_profit / abs(gross_loss):.2f}"
                if float(gross_loss) != 0.0
                else "INF"
            )
        )

        columns[4].metric(
            "Wins",
            int(
                (
                    trades["P&L Points"] > 0
                ).sum()
            )
        )

        columns[5].metric(
            "Losses",
            int(
                (
                    trades["P&L Points"] < 0
                ).sum()
            )
        )

        st.subheader(
            "📈 Equity Curve"
        )

        st.line_chart(
            trades.set_index(
                "Date"
            )["Cumulative P&L ₹"]
        )

        left, right = st.columns(2)

        with left:

            st.subheader(
                "Monthly P&L"
            )

            monthly_chart = trades.copy()

            monthly_chart["Month"] = (
                pd.to_datetime(
                    monthly_chart["Date"]
                )
                .dt.to_period("M")
                .astype(str)
            )

            st.bar_chart(
                monthly_chart
                .groupby("Month")["P&L ₹"]
                .sum()
            )

        with right:

            st.subheader(
                "Trade Results"
            )

            st.bar_chart(
                trades["Result"]
                .value_counts()
            )

        st.subheader(
            "Trade-by-Trade Results"
        )

        st.dataframe(
            trades,
            use_container_width=True,
            hide_index=True
        )

        rules = pd.DataFrame({
            "Rule": [
                "Reference Candle",
                "Reference High",
                "Reference Low",
                "Long Entry",
                "Long Stop Loss",
                "Short Entry",
                "Short Stop Loss",
                "Exit",
                "Re-entry",
            ],
            "Definition": [
                f"{reference_start}-{reference_end}",
                "High of THAT day's selected 5-minute reference candle",
                "Low of THAT day's selected 5-minute reference candle",
                "Later 5-minute candle CLOSES above that day's Reference High",
                "Later 5-minute candle CLOSES at/below that day's Reference Low",
                "Later 5-minute candle CLOSES below that day's Reference Low",
                "Later 5-minute candle CLOSES at/above that day's Reference High",
                "Open trade closes at 3:15 PM using the 15:10 candle close",
                "No re-entry after the first trade of the day",
            ]
        })

        excel_file = make_excel(
            trades,
            references,
            summary,
            raw,
            rules
        )

        month_count = (
            pd.to_datetime(
                trades["Date"]
            )
            .dt.strftime("%Y-%m")
            .nunique()
        )

        st.success(
            f"ONE Excel workbook created with "
            f"{month_count} monthly tabs."
        )

        st.download_button(
            "⬇️ Download ONE Excel — Monthly Tabs",
            data=excel_file,
            file_name=(
                f"{stock}_"
                f"{reference_start.replace(':','')}_"
                f"4year_backtest.xlsx"
            ),
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            use_container_width=True
        )

    except requests.RequestException as error:
        st.error(
            f"Network/API error: {error}"
        )

    except Exception as error:
        st.error(
            f"Backtest error: {error}"
        )


st.divider()

st.info(
    "Security: never commit your Upstox access token to GitHub. "
    "Use Streamlit Secrets for deployment."
)
