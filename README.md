# Upstox 5-Minute Reference Candle Backtester V5

V5 fixes the Streamlit runtime issue (`'bool' object is not callable`) by using
explicit DataFrame length checks and explicit numeric checks.

Reference-price logic:
- The selected 5-minute candle is found separately for every trading day.
- Reference High = that day's selected candle High.
- Reference Low = that day's selected candle Low.
- Levels are not carried to another day.
- Long entry = later 5-minute close above that day's Reference High.
- Long SL = later 5-minute close at/below that day's Reference Low.
- Short entry = later 5-minute close below that day's Reference Low.
- Short SL = later 5-minute close at/above that day's Reference High.
- Open position exits at 3:15 PM using the 15:10 candle close.
- No re-entry after the first trade of a day.

Excel:
- Summary
- Reference Levels
- All Trades
- one YYYY-MM tab for every month
- Rules
