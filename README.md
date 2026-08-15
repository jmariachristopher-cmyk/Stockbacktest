# Upstox 5-Minute Breakout Backtester — V2

This version fixes Upstox `UDAPI1148 Invalid date range`.

## Why the error happened

Upstox V3 documents a maximum retrieval window of 1 month for minute intervals from 1 to 15 minutes. The previous app requested a 31-day range in one call in some cases. This V2 deliberately uses **28-day chunks**, which stays safely inside the limit.

## Strategy

- Select a 5-minute reference candle.
- Long when a later 5-minute candle CLOSES above reference HIGH.
- Long SL = reference LOW; stop only on 5-minute CLOSE.
- Short when a later 5-minute candle CLOSES below reference LOW.
- Short SL = reference HIGH; stop only on 5-minute CLOSE.
- One trade per day; no re-entry.
- Open position exits at 3:15 PM using the 15:10 candle close.
- Full Excel export.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Cloud

Deploy `app.py` from GitHub. Never commit the Upstox access token to GitHub.
