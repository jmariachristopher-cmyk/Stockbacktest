# Upstox 5-Minute Reference Candle Backtester V7

## Daily reference price — the key rule

For EVERY trading day, the app finds the exact selected 5-minute candle.

Example: selecting 09:35 means the 09:35–09:40 candle.

For each date:
- Reference High = HIGH of that date's 09:35–09:40 candle
- Reference Low = LOW of that date's 09:35–09:40 candle

The prices are recalculated independently every day.

A price such as 2006.40 / 2001.70 from a TradingView example is NEVER
hard-coded and is NEVER reused for another date.

## Trading rules

After the reference candle:

LONG:
- a later 5-minute candle CLOSES above that day's Reference High
- entry at that closing price
- stop loss is that day's Reference Low
- stop triggers only when a later 5-minute candle CLOSES at/below the
  Reference Low

SHORT:
- a later 5-minute candle CLOSES below that day's Reference Low
- entry at that closing price
- stop loss is that day's Reference High
- stop triggers only when a later 5-minute candle CLOSES at/above the
  Reference High

Only the first trade of the day is taken. No re-entry.

If still open, exit at the 15:10 candle close, which represents the
3:10–3:15 candle and therefore the 3:15 PM close.

## Excel workbook

One workbook contains:
- Summary
- Reference Levels
- All Trades
- YYYY-MM monthly tabs
- Rules

The Reference Levels tab is the audit trail for the daily High/Low values.
