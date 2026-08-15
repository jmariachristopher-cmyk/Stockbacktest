# Upstox 5-Minute Reference Candle Backtester V8

Genuine V8 code change.

For EVERY trading date, the selected 5-minute candle supplies that day's own Reference High and Reference Low. No hard-coded example price is ever used for another day.

LONG: later 5-minute close > that day's Reference High. Stop: later 5-minute close <= that day's Reference Low.

SHORT: later 5-minute close < that day's Reference Low. Stop: later 5-minute close >= that day's Reference High.

If still open, exit at the 15:10 candle close (3:15 PM). First trade only; no re-entry.

V8 also removes pandas namedtuple attribute access from the trade loop and uses explicit Series indexing.
