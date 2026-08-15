# Upstox 5-Minute Breakout Backtester V3

The app creates ONE Excel workbook. Every month is a separate tab inside that same workbook.

Example tabs:
- Summary
- All Trades
- 2022-08
- 2022-09
- 2022-10
- ...
- 2026-08
- Rules

Every daily reference candle is recalculated independently. The selected candle's
Open, High, Low and Close are included in the monthly tabs.

The previous Upstox date-range issue is avoided with conservative 28-day API chunks.
