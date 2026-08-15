
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
        rows.append([c[0], float(c[1]), float(c[2]), float(c[3]), float(c[4]),
                     float(c[5]) if len(c) > 5 and c[5] is not None else 0])
    return pd.DataFrame(rows, columns=["timestamp","open","high","low","close","volume"])

def download_history(token, instrument_key, start, end, progress=None):
    parts = []
    cur = start
    total_days = max((end-start).days + 1, 1)
    done = 0
    while cur <= end:
        chunk_end = min(cur + timedelta(days=30), end)
        if progress:
            progress(min(done / total_days, 0.99), f"Downloading {cur} → {chunk_end}")
        df = get_candles(token, instrument_key, cur.isoformat(), chunk_end.isoformat())
        if not df.empty:
            parts.append(df)
        done += (chunk_end-cur).days + 1
        cur = chunk_end + timedelta(days=1)
    if not parts:
        return pd.DataFrame(columns=["timestamp","open","high","low","close","volume"])
    df = pd.concat(parts, ignore_index=True).drop_duplicates("timestamp")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    if getattr(df["timestamp"].dt, "tz", None) is not None:
        df["timestamp"] = df["timestamp"].dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    return df.sort_values("timestamp").reset_index(drop=True)

def backtest(df, ref_start, ref_end, qty):
    if df.empty:
        return pd.DataFrame()
    x = df.copy()
    x["date"] = x.timestamp.dt.date
    x["clock"] = x.timestamp.dt.strftime("%H:%M")
    trades = []

    for d, day in x.groupby("date", sort=True):
        day = day[(day.clock >= "09:15") & (day.clock <= "15:15")].sort_values("timestamp").reset_index(drop=True)
        ref = day[day.clock == ref_start]
        if ref.empty:
            continue
        ref = ref.iloc[0]
        rh, rl = float(ref.high), float(ref.low)
        position = None
        entry = None
        exit_row = None
        reason = None

        for _, row in day[day.timestamp > ref.timestamp].iterrows():
            clock = row.timestamp.strftime("%H:%M")
            close = float(row.close)

            if position is None and clock <= "15:10":
                if close > rh:
                    position, entry = "LONG", row
                    continue
                if close < rl:
                    position, entry = "SHORT", row
                    continue

            if position == "LONG" and close <= rl:
                exit_row, reason = row, "STOP LOSS"
                break
            if position == "SHORT" and close >= rh:
                exit_row, reason = row, "STOP LOSS"
                break

        if position and exit_row is None:
            eod = day[day.clock == "15:10"]
            if eod.empty:
                eod = day[day.clock <= "15:15"]
            if not eod.empty:
                exit_row, reason = eod.iloc[-1], "3:15 PM EXIT"

        if position and exit_row is not None:
            ep, xp = float(entry.close), float(exit_row.close)
            pnl = xp-ep if position == "LONG" else ep-xp
            trades.append({
                "Date": d, "Reference Candle": f"{ref_start}-{ref_end}",
                "Reference High": rh, "Reference Low": rl,
                "Direction": position, "Entry Time": entry.timestamp,
                "Entry Price": ep, "Stop Loss Price": rl if position=="LONG" else rh,
                "Exit Time": exit_row.timestamp, "Exit Price": xp,
                "Exit Reason": reason, "P&L Points": pnl,
                "P&L ₹": pnl*qty,
                "Result": "PROFIT" if pnl > 0 else ("LOSS" if pnl < 0 else "BREAKEVEN")
            })
    out = pd.DataFrame(trades)
    if not out.empty:
        out["Cumulative P&L ₹"] = out["P&L ₹"].cumsum()
    return out

def summary(trades, start, end, stock, ref, qty):
    if trades.empty:
        return pd.DataFrame({"Metric":[],"Value":[]})
    wins = (trades["P&L Points"] > 0).sum()
    losses = (trades["P&L Points"] < 0).sum()
    gp = trades.loc[trades["P&L Points"] > 0, "P&L ₹"].sum()
    gl = trades.loc[trades["P&L Points"] < 0, "P&L ₹"].sum()
    return pd.DataFrame({
        "Metric": ["Stock","Period","Reference Candle","Trades","Wins","Losses","Win Rate %",
                   "Gross Profit ₹","Gross Loss ₹","Net P&L ₹","Profit Factor","Quantity"],
        "Value": [stock,f"{start} to {end}",ref,len(trades),wins,losses,
                  round(wins/len(trades)*100,2),round(gp,2),round(gl,2),
                  round(trades["P&L ₹"].sum(),2),
                  round(gp/abs(gl),3) if gl else "INF",qty]
    })

def excel_bytes(trades, summ, raw, rules):
    b = io.BytesIO()
    with pd.ExcelWriter(b, engine="openpyxl") as writer:
        summ.to_excel(writer, index=False, sheet_name="Summary")
        trades.to_excel(writer, index=False, sheet_name="Trades")
        rules.to_excel(writer, index=False, sheet_name="Rules")
        raw.to_excel(writer, index=False, sheet_name="5Min Data")
    b.seek(0)
    return b.getvalue()

st.title("📊 Upstox 5-Minute Breakout Backtester")
st.caption("Historical 5-minute OHLC • reference-candle breakout • close-based stop-loss • 3:15 PM exit")

with st.sidebar:
    st.header("Backtest Settings")
    token = st.text_input("Upstox Access Token", type="password", value=os.getenv("UPSTOX_ACCESS_TOKEN",""))
    instrument = st.text_input("Upstox Instrument Key", value="NSE_EQ|INE848E01016")
    stock = st.text_input("Stock Name", value="STOCK")
    start = st.date_input("Start Date", value=date(2022,8,15))
    end = st.date_input("End Date", value=date(2026,8,14))
    times = [f"{h:02d}:{m:02d}" for h in range(9,16) for m in (0,5,10,15,20,25,30,35,40,45,50,55) if not (h==15 and m>10)]
    ref_start = st.selectbox("Reference Candle Start", times, index=times.index("09:35"))
    ref_end = f"{(pd.Timestamp(ref_start)+pd.Timedelta(minutes=5)).strftime('%H:%M')}"
    qty = st.number_input("Quantity", min_value=1, value=1, step=1)
    run = st.button("🚀 Run 4-Year Backtest", type="primary", use_container_width=True)

if run:
    if not token or "|" not in instrument:
        st.error("Enter a valid Upstox access token and instrument key.")
        st.stop()
    if start >= end:
        st.error("Start date must be before end date.")
        st.stop()

    bar = st.progress(0)
    status = st.empty()
    try:
        raw = download_history(token, instrument, start, end, bar)
        bar.progress(1.0)
        status.success(f"Downloaded {len(raw):,} five-minute candles.")
        trades = backtest(raw, ref_start, ref_end, qty)
        summ = summary(trades, start, end, stock, f"{ref_start}-{ref_end}", qty)

        if trades.empty:
            st.warning("No trades found. Check the instrument key, dates and reference candle.")
            st.stop()

        c = st.columns(6)
        c[0].metric("Trades", len(trades))
        c[1].metric("Win Rate", f"{(trades['P&L Points']>0).mean()*100:.2f}%")
        c[2].metric("Net P&L", f"₹{trades['P&L ₹'].sum():,.2f}")
        gp = trades.loc[trades["P&L Points"]>0,"P&L ₹"].sum()
        gl = trades.loc[trades["P&L Points"]<0,"P&L ₹"].sum()
        c[3].metric("Profit Factor", f"{gp/abs(gl):.2f}" if gl else "INF")
        c[4].metric("Wins", int((trades["P&L Points"]>0).sum()))
        c[5].metric("Losses", int((trades["P&L Points"]<0).sum()))

        st.subheader("Equity Curve")
        st.line_chart(trades.set_index("Date")["Cumulative P&L ₹"])

        left, right = st.columns(2)
        with left:
            st.subheader("Monthly P&L")
            monthly = trades.copy()
            monthly["Month"] = pd.to_datetime(monthly["Date"]).dt.to_period("M").astype(str)
            st.bar_chart(monthly.groupby("Month")["P&L ₹"].sum())
        with right:
            st.subheader("Trade Results")
            st.bar_chart(trades["Result"].value_counts())

        st.subheader("Trade-by-Trade Results")
        st.dataframe(trades, use_container_width=True, hide_index=True)

        rules = pd.DataFrame({
            "Rule": ["Reference candle","Long entry","Long SL","Short entry","Short SL","Exit","Re-entry"],
            "Definition": [
                f"{ref_start}-{ref_end}",
                "First later 5-minute CLOSE above reference HIGH",
                "Reference LOW; exit only on 5-minute CLOSE <= LOW",
                "First later 5-minute CLOSE below reference LOW",
                "Reference HIGH; exit only on 5-minute CLOSE >= HIGH",
                "Open trade closes at 3:15 PM (15:10 candle close)",
                "No re-entry after the first trade of the day"
            ]
        })
        data = excel_bytes(trades, summ, raw, rules)
        st.download_button("⬇️ Download Complete Excel Report", data=data,
                           file_name=f"{stock}_{ref_start.replace(':','')}_4year_backtest.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)
    except Exception as e:
        st.error(str(e))

st.divider()
st.info("Security: for Streamlit Cloud, use st.secrets instead of hard-coding your Upstox token. Never commit tokens to GitHub.")
