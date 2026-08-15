# V9 — Upstox / TradingView Reference Candle Alignment

The user's TradingView screenshot established the required mapping.

When the UI says **09:35-09:40**, the reference candle is the candle
displayed by TradingView at **09:40**.

For Upstox historical 5-minute data, the corresponding row is selected
using the **reference end time (09:40)**.

Verified user example for 2026-08-14:
TradingView reference candle:
Open 2002.7
High 2006.4
Low 2001.7
Close 2001.7

The prior version incorrectly used the 09:35 row:
Open 1999.1
High 2005.0
Low 1998.0
Close 2002.7

V9 uses 09:40 for the selected 09:35-09:40 reference.

Daily:
- Reference High = that day's selected candle High
- Reference Low = that day's selected candle Low
- LONG = subsequent 5-minute CLOSE > that day's High
- LONG SL = subsequent 5-minute CLOSE <= that day's Low
- SHORT = subsequent 5-minute CLOSE < that day's Low
- SHORT SL = subsequent 5-minute CLOSE >= that day's High
- First trade only; no re-entry
- Open trade exits on 15:10 candle close (3:15 PM)

Excel includes monthly tabs and an audit column for the Upstox candle timestamp.
