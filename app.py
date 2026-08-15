
import os
import io
from datetime import date, timedelta
import requests
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Upstox 5-Min Breakout Backtester", layout="wide")

API_BASE = "https://api.upstox.com/v3/historical-candle"

def get_candles(token, instrument_key, from_date, to_date):
    url = f"{API_BASE}/{instrument_key}/minutes/5/{to_date}/{from_date}"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=headers, timeout=45)
    if r.status_code != 200:
        raise RuntimeError(f"Upstox API {r.status_code}: {r.text[:500]}")
    candles = r.json().get("data", {}).get("candles", [])
    rows = []
    for c in candles:
        rows.append([
            c[0], float(c[1]), float(c[2]), float(c[3]), float(c[4]),
            float(c[5]) if len(c) > 5 and c[5] is not None else 0
        ])
    return pd.DataFrame(
        rows, columns=["timestamp", "open", "high", "low", "close", "volume"]
    )

def download_history(token, instrument_key, start, end, progress_bar=None, status_box=None):
    parts = []
    cur = start
    total_days = max((end - start).days + 1, 1)
    done = 0

    while cur <= end:
        chunk_end = min(cur + timedelta(days=30), end)

        fraction = min(done / total_days, 0.99)
        message = f"Downloading {cur} → {chunk_end}"
        if progress_bar is not None:
            progress_bar.progress(fraction, text=message)
        if status_box is not None:
            status_box.info(message)

        df = get_candles(
            token, instrument_key, cur.isoformat(), chunk_end.isoformat()
        )
        if not df.empty:
            parts.append(df)

        done += (chunk_end - cur).days + 1
        cur = chunk_end + timedelta(days=1)

    if not parts:
        return pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )

    df = pd.concat(parts, ignore_index=True).drop_duplicates("timestamp")
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    if getattr(df["timestamp"].dt, "tz", None) is not None:
        df["timestamp"] = (
            df["timestamp"]
            .dt.tz_convert("Asia/Kolkata")
            .dt.tz_localize(None)
        )

    df = df.sort_values("timestamp").reset_index(drop=True)

    if progress_bar is not None:
        progress_bar.progress(1.0, text="Download complete")

    return df

def backtest(df, ref_start, ref_end, qty):
    if df.empty:
        return pd.DataFrame()

    x = df.copy()
    x["date"] = x["timestamp"].dt.date
    x["clock"] = x["timestamp"].dt.strftime("%H:%M")
    trades = []

    for d, day in x.groupby("date", sort=True):
        day = day[
            (day["clock"] >= "09:15") & (day["clock"] <= "15:15")
        ].sort_values("timestamp").reset_index(drop=True)

        # The candle beginning at ref_start is the reference candle.
        ref = day[day["clock"] == ref_start]
        if ref.empty:
            continue

        ref = ref.iloc[0]
        rh = float(ref["high"])
        rl = float(ref["low"])

        position = None
        entry = None
        exit_row = None
        reason = None

        for _, row in day[day["timestamp"] > ref["timestamp"]].iterrows():
            clock = row["timestamp"].strftime("%H:%M")
            close = float(row["close"])

            # Entry only from the close of a later 5-minute candle.
            if position is None and clock <= "15:10":
                if close > rh:
                    position, entry = "LONG", row
                    continue

                if close < rl:
                    position, entry = "SHORT", row
                    continue

            # Stop-loss only on 5-minute CLOSE.
            if position == "LONG" and close <= rl:
                exit_row, reason = row, "STOP LOSS"
                break

            if position == "SHORT" and close >= rh:
                exit_row, reason = row, "STOP LOSS"
                break

        # If SL was not hit, exit at the close of the 15:10 candle,
        # which is the 5-minute candle ending at 15:15.
        if position and exit_row is None:
            eod = day[day["clock"] == "15:10"]
            if eod.empty:
                eod = day[day["clock"] <= "15:15"]

            if not eod.empty:
                exit_row = eod.iloc[-1]
                reason = "3:15 PM EXIT"

        if position and exit_row is not None:
            entry_price = float(entry["close"])
            exit_price = float(exit_row["close"])

            pnl = (
                exit_price - entry_price
                if position == "LONG"
                else entry_price - exit_price
            )

            trades.append({
                "Date": d,
                "Reference Candle": f"{ref_start}-{ref_end}",
                "Reference High": rh,
                "Reference Low": rl,
                "Direction": position,
                "Entry Time": entry["timestamp"],
                "Entry Price": entry_price,
                "Stop Loss Price": rl if position == "LONG" else rh,
                "Exit Time": exit_row["timestamp"],
                "Exit Price": exit_price,
                "Exit Reason": reason,
                "P&L Points": pnl,
                "P&L ₹": pnl * qty,
                "Result": (
                    "PROFIT" if pnl > 0
                    else ("LOSS" if pnl < 0 else "BREAKEVEN")
                )
            })

    out = pd.DataFrame(trades)

    if not out.empty:
        out["Cumulative P&L ₹"] = out["P&L ₹"].cumsum()

    return out

def make_summary(trades, start, end, stock, ref, qty):
    if trades.empty:
        return pd.DataFrame({"Metric": [], "Value": []})

    wins = int((trades["P&L Points"] > 0).sum())
    losses = int((trades["P&L Points"] < 0).sum())
    breakeven = int((trades["P&L Points"] == 0).sum())

    gross_profit = trades.loc[
        trades["P&L Points"] > 0, "P&L ₹"
    ].sum()

    gross_loss = trades.loc[
        trades["P&L Points"] < 0, "P&L ₹"
    ].sum()

    net = trades["P&L ₹"].sum()
    win_rate = wins / len(trades) * 100
    pf = gross_profit / abs(gross_loss) if gross_loss else float("inf")

    return pd.DataFrame({
        "Metric": [
            "Stock", "Period", "Reference Candle", "Total Trades",
            "Winning Trades", "Losing Trades", "Breakeven Trades",
            "Win Rate %", "Gross Profit ₹", "Gross Loss ₹",
            "Net P&L ₹", "Profit Factor", "Quantity"
        ],
        "Value": [
            stock, f"{start} to {end}", ref, len(trades),
            wins, losses, breakeven, round(win_rate, 2),
            round(gross_profit, 2), round(gross_loss, 2),
            round(net, 2),
            round(pf, 3) if pf != float("inf") else "INF",
            qty
        ]
    })

def make_excel(trades, summary, raw, rules):
    b = io.BytesIO()

    with pd.ExcelWriter(b, engine="openpyxl") as writer:
        summary.to_excel(writer, index=False, sheet_name="Summary")
        trades.to_excel(writer, index=False, sheet_name="Trades")
        rules.to_excel(writer, index=False, sheet_name="Rules")
        raw.to_excel(writer, index=False, sheet_name="5Min Data")

    b.seek(0)
    return b.getvalue()

st.title("📊 Upstox 5-Minute Breakout Backtester")
st.caption(
    "Historical 5-minute OHLC • reference-candle breakout • "
    "close-based stop-loss • 3:15 PM exit"
)

with st.sidebar:
    st.header("Backtest Settings")

    token = st.text_input(
        "Upstox Access Token",
        type="password",
        value=os.getenv("UPSTOX_ACCESS_TOKEN", "")
    )

    instrument = st.text_input(
        "Upstox Instrument Key",
        value="NSE_EQ|INE848E01016"
    )

    stock = st.text_input("Stock Name", value="GODREJPROP")

    start = st.date_input(
        "Start Date",
        value=date(2022, 8, 15)
    )

    end = st.date_input(
        "End Date",
        value=date(2026, 8, 14)
    )

    times = [
        f"{h:02d}:{m:02d}"
        for h in range(9, 16)
        for m in (0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55)
        if not (h == 15 and m > 10)
    ]

    ref_start = st.selectbox(
        "Reference Candle Start",
        times,
        index=times.index("09:35")
    )

    ref_end = (
        pd.Timestamp(ref_start) + pd.Timedelta(minutes=5)
    ).strftime("%H:%M")

    st.caption(f"Reference candle: {ref_start} → {ref_end}")

    qty = st.number_input(
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
    if not token or "|" not in instrument:
        st.error("Enter a valid Upstox access token and instrument key.")
        st.stop()

    if start >= end:
        st.error("Start date must be before end date.")
        st.stop()

    progress_bar = st.progress(0, text="Starting download...")
    status_box = st.empty()

    try:
        raw = download_history(
            token,
            instrument,
            start,
            end,
            progress_bar,
            status_box
        )

        if raw.empty:
            st.error(
                "Upstox returned no 5-minute candles. "
                "Check the instrument key, access token and date range."
            )
            st.stop()

        status_box.success(
            f"Downloaded {len(raw):,} five-minute candles."
        )

        trades = backtest(raw, ref_start, ref_end, qty)

        if trades.empty:
            st.warning(
                "No trades were generated. Check the reference candle, "
                "instrument key and date range."
            )
            st.stop()

        summ = make_summary(
            trades,
            start,
            end,
            stock,
            f"{ref_start}-{ref_end}",
            qty
        )

        col = st.columns(6)

        col[0].metric("Trades", len(trades))
        col[1].metric(
            "Win Rate",
            f"{(trades['P&L Points'] > 0).mean() * 100:.2f}%"
        )
        col[2].metric(
            "Net P&L",
            f"₹{trades['P&L ₹'].sum():,.2f}"
        )

        gross_profit = trades.loc[
            trades["P&L Points"] > 0, "P&L ₹"
        ].sum()

        gross_loss = trades.loc[
            trades["P&L Points"] < 0, "P&L ₹"
        ].sum()

        col[3].metric(
            "Profit Factor",
            f"{gross_profit / abs(gross_loss):.2f}"
            if gross_loss else "INF"
        )

        col[4].metric(
            "Wins",
            int((trades["P&L Points"] > 0).sum())
        )

        col[5].metric(
            "Losses",
            int((trades["P&L Points"] < 0).sum())
        )

        st.subheader("Equity Curve")
        st.line_chart(
            trades.set_index("Date")["Cumulative P&L ₹"]
        )

        left, right = st.columns(2)

        with left:
            st.subheader("Monthly P&L")
            monthly = trades.copy()
            monthly["Month"] = (
                pd.to_datetime(monthly["Date"])
                .dt.to_period("M")
                .astype(str)
            )
            st.bar_chart(
                monthly.groupby("Month")["P&L ₹"].sum()
            )

        with right:
            st.subheader("Trade Results")
            st.bar_chart(
                trades["Result"].value_counts()
            )

        st.subheader("Trade-by-Trade Results")
        st.dataframe(
            trades,
            use_container_width=True,
            hide_index=True
        )

        rules = pd.DataFrame({
            "Rule": [
                "Reference candle",
                "Long entry",
                "Long stop loss",
                "Short entry",
                "Short stop loss",
                "Exit",
                "Re-entry"
            ],
            "Definition": [
                f"{ref_start}-{ref_end}",
                "First later 5-minute CLOSE above reference HIGH",
                "Reference LOW; exit only on 5-minute CLOSE <= LOW",
                "First later 5-minute CLOSE below reference LOW",
                "Reference HIGH; exit only on 5-minute CLOSE >= HIGH",
                "Close at 3:15 PM using the 15:10 candle close",
                "No re-entry after the first trade of the day"
            ]
        })

        excel = make_excel(
            trades,
            summ,
            raw,
            rules
        )

        st.download_button(
            "⬇️ Download Complete Excel Report",
            data=excel,
            file_name=(
                f"{stock}_{ref_start.replace(':','')}_"
                f"4year_backtest.xlsx"
            ),
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            use_container_width=True
        )

    except requests.RequestException as e:
        st.error(f"Network/API connection error: {e}")

    except Exception as e:
        st.error(f"Backtest error: {e}")

st.divider()

st.info(
    "Security: never commit your Upstox access token to GitHub. "
    "For Streamlit Cloud, use Streamlit Secrets."
)
