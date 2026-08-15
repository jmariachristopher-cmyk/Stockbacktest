# Upstox 5-Minute Breakout Backtester

Fixed version of the Streamlit 5-minute breakout backtester.

## Strategy
- Select a 5-minute reference candle.
- Long when a later 5-minute candle CLOSES above the reference high.
- Long SL = reference low; SL only on 5-minute CLOSE.
- Short when a later 5-minute candle CLOSES below the reference low.
- Short SL = reference high; SL only on 5-minute CLOSE.
- One trade per day; no re-entry.
- Open trade exits at 3:15 PM using the 15:10 candle close.
- Full Excel export.

## Run
pip install -r requirements.txt
streamlit run app.py
