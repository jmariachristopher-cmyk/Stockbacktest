
import os
import io
import traceback
from datetime import date, timedelta

import pandas as pd
import requests
import streamlit as st


st.set_page_config(
    page_title="Upstox 5-Minute Reference Candle Backtester — V8",
    layout="wide"
)

API_BASE = "https://api.upstox.com/v3/historical-candle"


# ============================================================
# UPSTOX DOWNLOAD
# ============================================================
def get_candles(token, instrument_key, from_date, to_date):
    url = f"{API_BASE}/{instrument_key}/minutes/5/{to_date}/{from_date}"

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=45
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Upstox API {response.status_code}: "
            f"{response.text[:1000]}"
        )

    payload = response.json()
    candles = payload.get("data", {}).get("candles", [])

    rows = []

    for candle in candles:
        if len(candle) < 5:
            continue

        rows.append({
            "timestamp": candle[0],
            "open": float(candle[1]),
            "high": float(candle[2]),
            "low": float(candle[3]),
            "close": float(candle[4]),
            "volume": (
                float(candle[5])
                if len(candle) > 5 and candle[5] is not None
                else 0.0
            ),
        })

    return pd.DataFrame(rows)


def download_history(
    token,
    instrument_key,
    start,
    end,
    progress_bar,
    status_box
):
    parts = []

    current = start
    total_days = max(
        (end - start).days + 1,
        1
    )

    processed_days = 0

    while current <= end:

        chunk_end = min(
            current + timedelta(days=27),
            end
        )

        status_box.info(
            f"Downloading {current} → {chunk_end}"
        )

        progress_bar.progress(
            min(processed_days / total_days, 0.99),
            text=f"Downloading {current} → {chunk_end}"
        )

        chunk = get_candles(
            token,
            instrument_key,
            current.isoformat(),
            chunk_end.isoformat()
        )

        if len(chunk.index) > 0:
            parts.append(chunk)

        processed_days += (
            chunk_end - current
        ).days + 1

        current = chunk_end + timedelta(days=1)

    if len(parts) == 0:
        return pd.DataFrame(
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]
        )

    data = pd.concat(
        parts,
        ignore_index=True
    )

    data = data.drop_duplicates(
        subset=["timestamp"]
    )

    # Explicit timestamp conversion.
    data["timestamp"] = pd.to_datetime(
        data["timestamp"],
        errors="coerce"
    )

    data = data.dropna(
        subset=["timestamp"]
    )

    # Convert to IST if timestamps are timezone-aware.
    try:
        if data["timestamp"].dt.tz is not None:
            data["timestamp"] = (
                data["timestamp"]
                .dt.tz_convert("Asia/Kolkata")
                .dt.tz_localize(None)
            )
    except Exception:
        # If Upstox already returned naive timestamps,
        # leave them unchanged.
        pass

    data = data.sort_values(
        "timestamp"
    ).reset_index(drop=True)

    progress_bar.progress(
        1.0,
        text="Download complete"
    )

    return data


# ============================================================
# DAILY REFERENCE CANDLE
# ============================================================
def create_reference_levels(
    data,
    reference_start,
    reference_end
):
    """
    THIS IS THE CORE REFERENCE-PRICE LOGIC.

    For each trading day:

        Reference High = High of that day's selected candle
        Reference Low  = Low of that day's selected candle

    The levels are recalculated every day.
    """

    x = data.copy()

    x["TradingDate"] = (
        x["timestamp"]
        .dt
        .date
    )

    x["Clock"] = (
        x["timestamp"]
        .dt
        .strftime("%H:%M")
    )

    # Select ONLY the exact requested 5-minute candle.
    refs = x.loc[
        x["Clock"] == reference_start,
        [
            "TradingDate",
            "timestamp",
            "open",
            "high",
            "low",
            "close"
        ]
    ].copy()

    if len(refs.index) == 0:
        return pd.DataFrame(
            columns=[
                "Date",
                "Reference Candle",
                "Reference Open",
                "Reference High",
                "Reference Low",
                "Reference Close",
                "Reference Timestamp"
            ]
        )

    refs = refs.drop_duplicates(
        subset=["TradingDate"],
        keep="first"
    )

    refs = refs.rename(
        columns={
            "TradingDate": "Date",
            "open": "Reference Open",
            "high": "Reference High",
            "low": "Reference Low",
            "close": "Reference Close",
            "timestamp": "Reference Timestamp",
        }
    )

    # These are the REAL prices from each day's selected candle.
    # No hard-coded reference price is used anywhere.
    for col in [
        "Reference Open",
        "Reference High",
        "Reference Low",
        "Reference Close",
    ]:
        refs[col] = pd.to_numeric(
            refs[col],
            errors="coerce"
        )

    refs.insert(
        1,
        "Reference Candle",
        f"{reference_start}-{reference_end}"
    )

    return refs.sort_values(
        "Date"
    ).reset_index(drop=True)


# ============================================================
# BACKTEST
# ============================================================
def backtest(
    data,
    reference_start,
    reference_end,
    quantity
):
    if len(data.index) == 0:
        return (
            pd.DataFrame(),
            pd.DataFrame()
        )

    x = data.copy()

    x["TradingDate"] = (
        x["timestamp"]
        .dt
        .date
    )

    x["Clock"] = (
        x["timestamp"]
        .dt
        .strftime("%H:%M")
    )

    references = create_reference_levels(
        x,
        reference_start,
        reference_end
    )

    trades = []

    # --------------------------------------------------------
    # Each reference row belongs to ONE day.
    #
    # IMPORTANT:
    # We deliberately use row["..."] instead of itertuples().
    # This prevents pandas from changing column names such as
    # "Reference Timestamp" into a namedtuple field.
    #
    # Most importantly, Reference High and Reference Low are
    # read from THAT DAY'S selected candle. They are never fixed
    # prices and are never carried forward to another day.
    # --------------------------------------------------------
    for _, reference_row in references.iterrows():

        trading_date = reference_row["Date"]

        reference_timestamp = pd.Timestamp(
            reference_row["Reference Timestamp"]
        )

        reference_high = float(
            reference_row["Reference High"]
        )

        reference_low = float(
            reference_row["Reference Low"]
        )

        day = x.loc[
            (x["TradingDate"] == trading_date)
            &
            (x["Clock"] >= "09:15")
            &
            (x["Clock"] <= "15:15")
        ].sort_values(
            "timestamp"
        )

        # Never use the reference candle itself for entry.
        after_reference = day.loc[
            day["timestamp"] > reference_timestamp
        ]

        direction = None
        entry_time = None
        entry_price = None
        exit_time = None
        exit_price = None
        exit_reason = None

        # ----------------------------------------------------
        # Look for first breakout.
        # ----------------------------------------------------
        for _, candle in after_reference.iterrows():

            candle_time = pd.Timestamp(candle["timestamp"]).strftime("%H:%M")

            close_price = float(candle["close"])

            if direction is None:

                # Long breakout.
                if (
                    candle_time <= "15:10"
                    and close_price > reference_high
                ):
                    direction = "LONG"
                    entry_time = candle["timestamp"]
                    entry_price = close_price
                    continue

                # Short breakdown.
                if (
                    candle_time <= "15:10"
                    and close_price < reference_low
                ):
                    direction = "SHORT"
                    entry_time = candle["timestamp"]
                    entry_price = close_price
                    continue

            # ------------------------------------------------
            # Long stop loss.
            # ------------------------------------------------
            if direction == "LONG":

                if close_price <= reference_low:
                    exit_time = candle["timestamp"]
                    exit_price = close_price
                    exit_reason = "STOP LOSS"
                    break

            # ------------------------------------------------
            # Short stop loss.
            # ------------------------------------------------
            if direction == "SHORT":

                if close_price >= reference_high:
                    exit_time = candle["timestamp"]
                    exit_price = close_price
                    exit_reason = "STOP LOSS"
                    break

        # ----------------------------------------------------
        # 3:15 PM exit.
        #
        # NSE 5-minute candle 15:10 represents the candle
        # ending at 15:15.
        # ----------------------------------------------------
        if (
            direction is not None
            and exit_time is None
        ):

            eod = day.loc[
                day["Clock"] == "15:10"
            ]

            if len(eod.index) > 0:

                last = eod.iloc[-1]

                exit_time = last["timestamp"]
                exit_price = float(
                    last["close"]
                )
                exit_reason = "3:15 PM EXIT"

        if (
            direction is None
            or exit_time is None
        ):
            continue

        if direction == "LONG":
            pnl_points = (
                exit_price - entry_price
            )
            stop_price = reference_low
        else:
            pnl_points = (
                entry_price - exit_price
            )
            stop_price = reference_high

        trades.append({
            "Date": trading_date,
            "Reference Candle": (
                f"{reference_start}-{reference_end}"
            ),
            "Reference Open": float(
                reference_row["Reference Open"]
            ),
            "Reference High": reference_high,
            "Reference Low": reference_low,
            "Reference Close": float(
                reference_row["Reference Close"]
            ),
            "Direction": direction,
            "Entry Time": entry_time,
            "Entry Price": entry_price,
            "Stop Loss Price": stop_price,
            "Exit Time": exit_time,
            "Exit Price": exit_price,
            "Exit Reason": exit_reason,
            "P&L Points": pnl_points,
            "P&L ₹": pnl_points * int(quantity),
            "Result": (
                "PROFIT"
                if pnl_points > 0
                else (
                    "LOSS"
                    if pnl_points < 0
                    else "BREAKEVEN"
                )
            )
        })

    trades_df = pd.DataFrame(trades)

    if len(trades_df.index) > 0:
        trades_df["Cumulative P&L ₹"] = (
            trades_df["P&L ₹"].cumsum()
        )

    return trades_df, references


# ============================================================
# SUMMARY
# ============================================================
def create_summary(
    trades,
    start,
    end,
    stock,
    reference_candle,
    quantity
):
    if len(trades.index) == 0:
        return pd.DataFrame(
            columns=["Metric", "Value"]
        )

    wins = int(
        (
            trades["P&L Points"] > 0
        ).sum()
    )

    losses = int(
        (
            trades["P&L Points"] < 0
        ).sum()
    )

    breakeven = int(
        (
            trades["P&L Points"] == 0
        ).sum()
    )

    gross_profit = float(
        trades.loc[
            trades["P&L Points"] > 0,
            "P&L ₹"
        ].sum()
    )

    gross_loss = float(
        trades.loc[
            trades["P&L Points"] < 0,
            "P&L ₹"
        ].sum()
    )

    net_pnl = float(
        trades["P&L ₹"].sum()
    )

    win_rate = (
        wins / len(trades.index) * 100
    )

    if gross_loss != 0:
        profit_factor = (
            gross_profit / abs(gross_loss)
        )
    else:
        profit_factor = float("inf")

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
            "Quantity"
        ],
        "Value": [
            stock,
            f"{start} to {end}",
            reference_candle,
            len(trades.index),
            wins,
            losses,
            breakeven,
            round(win_rate, 2),
            round(gross_profit, 2),
            round(gross_loss, 2),
            round(net_pnl, 2),
            (
                "INF"
                if profit_factor == float("inf")
                else round(profit_factor, 3)
            ),
            quantity
        ]
    })


# ============================================================
# EXCEL
# ============================================================
def create_excel(
    trades,
    references,
    summary,
    raw,
    rules
):
    output = io.BytesIO()

    with pd.ExcelWriter(
        output,
        engine="openpyxl"
    ) as writer:

        summary.to_excel(
            writer,
            index=False,
            sheet_name="Summary"
        )

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

        if len(trades.index) > 0:

            temp = trades.copy()

            temp["_Month"] = (
                pd.to_datetime(
                    temp["Date"]
                )
                .dt
                .strftime("%Y-%m")
            )

            for month, monthly in temp.groupby(
                "_Month",
                sort=True
            ):

                monthly = monthly.drop(
                    columns=["_Month"]
                )

                monthly.to_excel(
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

            if worksheet.max_row > 1:
                worksheet.auto_filter.ref = (
                    worksheet.dimensions
                )

            for column in worksheet.columns:

                letter = (
                    column[0].column_letter
                )

                longest = 0

                for cell in column[:1000]:

                    value = (
                        ""
                        if cell.value is None
                        else str(cell.value)
                    )

                    longest = max(
                        longest,
                        len(value)
                    )

                worksheet.column_dimensions[
                    letter
                ].width = min(
                    max(longest + 2, 10),
                    30
                )

    output.seek(0)
    return output.getvalue()


# ============================================================
# STREAMLIT UI
# ============================================================
st.title(
    "📊 Upstox 5-Minute Reference Candle Backtester — V8"
)

st.caption(
    "Exact daily reference candle High/Low • "
    "5-minute close breakout • close-based stop loss • "
    "3:15 PM exit • one Excel workbook with monthly tabs"
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

    reference_times = [
        f"{hour:02d}:{minute:02d}"
        for hour in range(9, 16)
        for minute in (
            0, 5, 10, 15, 20, 25,
            30, 35, 40, 45, 50, 55
        )
        if not (
            hour == 15
            and minute > 10
        )
    ]

    reference_start = st.selectbox(
        "Reference Candle Start",
        reference_times,
        index=reference_times.index(
            "09:35"
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

    run = st.button(
        "🚀 Run 4-Year Backtest",
        type="primary",
        use_container_width=True
    )


if run:

    if token.strip() == "":
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

    progress_bar = st.progress(
        0,
        text="Starting..."
    )

    status_box = st.empty()

    try:

        # ====================================================
        # STEP 1: DOWNLOAD
        # ====================================================
        raw = download_history(
            token,
            instrument,
            start,
            end,
            progress_bar,
            status_box
        )

        if len(raw.index) == 0:
            st.error(
                "Upstox returned no candles."
            )
            st.stop()

        status_box.success(
            f"Downloaded {len(raw.index):,} "
            "5-minute candles."
        )

        # ====================================================
        # STEP 2: REFERENCE LEVELS
        # ====================================================
        try:

            references = create_reference_levels(
                raw,
                reference_start,
                reference_end
            )

        except Exception as error:

            st.error(
                "Reference candle calculation failed."
            )

            st.code(
                traceback.format_exc(),
                language="text"
            )

            st.stop()

        if len(references.index) == 0:

            st.warning(
                f"No {reference_start} candles were found "
                "in the downloaded data."
            )

            st.stop()

        st.subheader(
            "🔴 Daily Reference Levels"
        )

        st.info(
            "These are the ACTUAL High and Low of the "
            "selected 5-minute candle for EACH individual day. "
            "The levels change every day. No example/fixed price "
            "is used for the backtest."
        )

        st.dataframe(
            references[
                [
                    "Date",
                    "Reference Candle",
                    "Reference Open",
                    "Reference High",
                    "Reference Low",
                    "Reference Close"
                ]
            ],
            use_container_width=True,
            hide_index=True
        )

        # ====================================================
        # STEP 3: BACKTEST
        # ====================================================
        try:

            required_reference_cols = [
                "Date", "Reference Timestamp", "Reference High",
                "Reference Low", "Reference Open", "Reference Close"
            ]
            missing_reference_cols = [
                c for c in required_reference_cols
                if c not in references.columns
            ]
            if missing_reference_cols:
                raise ValueError(
                    "Reference table is missing: "
                    + ", ".join(missing_reference_cols)
                )

            if references[["Reference High", "Reference Low"]].isna().any().any():
                raise ValueError(
                    "Missing daily Reference High/Low. "
                    "No fixed/reference example price will be substituted."
                )

            trades, references = backtest(
                raw,
                reference_start,
                reference_end,
                quantity
            )

        except Exception:

            st.error(
                "Trade calculation failed. "
                "The exact Python traceback is shown below "
                "so we can identify the remaining issue."
            )

            st.code(
                traceback.format_exc(),
                language="text"
            )

            st.stop()

        if len(trades.index) == 0:

            st.warning(
                "Reference levels were found, "
                "but no breakout trade occurred."
            )

            st.stop()

        # ====================================================
        # SUMMARY
        # ====================================================
        summary = create_summary(
            trades,
            start,
            end,
            stock,
            f"{reference_start}-{reference_end}",
            quantity
        )

        wins = int(
            (
                trades["P&L Points"] > 0
            ).sum()
        )

        losses = int(
            (
                trades["P&L Points"] < 0
            ).sum()
        )

        total = len(trades.index)

        gross_profit = float(
            trades.loc[
                trades["P&L Points"] > 0,
                "P&L ₹"
            ].sum()
        )

        gross_loss = float(
            trades.loc[
                trades["P&L Points"] < 0,
                "P&L ₹"
            ].sum()
        )

        c1, c2, c3, c4, c5, c6 = st.columns(6)

        c1.metric(
            "Trades",
            total
        )

        c2.metric(
            "Win Rate",
            f"{wins / total * 100:.2f}%"
        )

        c3.metric(
            "Net P&L",
            f"₹{float(trades['P&L ₹'].sum()):,.2f}"
        )

        c4.metric(
            "Profit Factor",
            (
                f"{gross_profit / abs(gross_loss):.2f}"
                if gross_loss != 0
                else "INF"
            )
        )

        c5.metric(
            "Wins",
            wins
        )

        c6.metric(
            "Losses",
            losses
        )

        st.subheader(
            "📈 Equity Curve"
        )

        st.line_chart(
            trades.set_index(
                "Date"
            )["Cumulative P&L ₹"]
        )

        st.subheader(
            "Trade Results"
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
                "3:15 PM Exit",
                "Re-entry"
            ],
            "Definition": [
                f"{reference_start}-{reference_end}",
                "Actual HIGH of that day's selected 5-minute candle; recalculated every trading day",
                "Actual LOW of that day's selected 5-minute candle; recalculated every trading day",
                "Later 5-minute candle CLOSE > that day's Reference High",
                "Later 5-minute candle CLOSE <= that day's Reference Low",
                "Later 5-minute candle CLOSE < that day's Reference Low",
                "Later 5-minute candle CLOSE >= that day's Reference High",
                "Open trade exits using the 15:10 candle CLOSE",
                "No re-entry after the first trade of the day"
            ]
        })

        # ====================================================
        # EXCEL
        # ====================================================
        excel = create_excel(
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
            .dt
            .strftime("%Y-%m")
            .nunique()
        )

        st.success(
            f"ONE Excel workbook created with "
            f"{month_count} monthly tabs."
        )

        st.download_button(
            "⬇️ Download ONE Excel — Monthly Tabs",
            data=excel,
            file_name=(
                f"{stock}_"
                f"{reference_start.replace(':', '')}_"
                f"4year_backtest.xlsx"
            ),
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            use_container_width=True
        )

    except Exception:

        st.error(
            "Backtest error. "
            "The exact traceback is shown below."
        )

        st.code(
            traceback.format_exc(),
            language="text"
        )


st.divider()

st.info(
    "Security: never commit your Upstox access token to GitHub. "
    "Use Streamlit Secrets for deployment."
)
