# Upstox 5-Minute Reference Candle Backtester V6

## Important

The previous versions were hiding the exact Python line that produced the
`'bool' object is not callable` error.

V6 separates the process into:
1. Download
2. Daily reference-level calculation
3. Trade calculation
4. Excel creation

If any step fails, V6 displays the full Python traceback in Streamlit.

## Reference price

For every trading day, the selected exact 5-minute candle is used:

Reference High = that candle's High
Reference Low = that candle's Low

The levels are recalculated independently every day.

## Trade rules

Long:
- later 5-minute CLOSE > reference High
- stop when later 5-minute CLOSE <= reference Low

Short:
- later 5-minute CLOSE < reference Low
- stop when later 5-minute CLOSE >= reference High

Open trade:
- exits at 3:15 PM using the 15:10 candle close

One trade maximum per day.

## Excel

One workbook:
- Summary
- Reference Levels
- All Trades
- one YYYY-MM tab per month
- Rules
