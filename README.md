# Upstox 5-Minute Reference Candle Backtester V4

This version fixes the reference-price definition.

For EVERY trading day:
1. Find the exact selected 5-minute candle.
2. Reference High = that candle's actual High.
3. Reference Low = that candle's actual Low.
4. Those two levels are used only for that trading day.
5. The next trading day gets a completely new pair of levels.

The app displays a `Reference Levels` table before/alongside the trade results so
the values can be checked against TradingView.

Excel output is ONE workbook containing:
- Summary
- Reference Levels
- All Trades
- One tab per month (YYYY-MM)
- Rules

The historical downloader uses conservative 28-day chunks for Upstox minute data.
