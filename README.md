# Upstox 5-Minute Breakout Backtester

Streamlit app for a close-based 5-minute reference candle breakout strategy using Upstox Historical Candle V3 API.

## Rules
- Select a reference 5-minute candle.
- Long when a later 5-minute candle closes above reference high.
- Long SL is reference low, triggered only by 5-minute close.
- Short when a later 5-minute candle closes below reference low.
- Short SL is reference high, triggered only by 5-minute close.
- One trade per day; no re-entry.
- Open position exits at 3:15 PM using the 15:10 candle close.
- Download full Excel report.

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Cloud
Deploy the GitHub repository and enter the Upstox access token in the app. Prefer Streamlit secrets for production.
