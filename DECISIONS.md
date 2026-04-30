# Midas — Decision Log

## Strategy Parameter Justifications
*Logged April 2026 — Phase 1, Option 1 Dip-Buy*

### Buy Trigger: -0.2%
BTC average intraday volatility is 3-4%. At $65K BTC, 0.2% = ~$130 move.
- Too small (-0.1%): trading noise
- Too large (-0.5%): triggers rarely, defeats Phase 1 trade frequency goal
- **Verdict:** Starting point only. Revisit after Week 1 logs.

### Take Profit: +0.15%
Asymmetric to entry — profit without requiring full recovery.
- Phase 1 goal is data, not profit
- **Verdict:** Placeholder. TK — recalibrate after Week 1.

### Stop Loss: -0.8%
4x the entry trigger. Risks 0.8% to make 0.15% — win rate compensates.
- Too tight (-0.3%): stops out on normal BTC noise
- Too loose (-2.0%): too much capital at risk per trade
- **Verdict:** Placeholder. TK — validate against Week 1 data.

### 20-Candle Volume Average (Option 2 — TK)
On 5-min candles, 20 candles = 100 min of volume history.
Same rationale as 20-period Bollinger Bands default.
- **Verdict:** Standard starting point. Not magic.

### 1h Price vs 4h SMA for Regime Detection (Option 3 — TK)
1h = short-term signal. 4h SMA = trend anchor.
Comparing different timeframes reveals if short-term move is with or against trend.
- **Verdict:** Common retail algo pairing for BTC. TK until Option 3 implemented.

---

## Reference Price: last_candle
*Decided April 2026*

Dip is measured against the close of the most recent completed 5-min candle.
- `session_open`: drifts stale intraday; triggers too infrequently for Phase 1 data collection
- `last_claude`: 30-min staleness; no trades fire before first Claude call each session
- `last_candle`: reactive to short-term momentum reversals; triggers most frequently; aligns with Phase 1 goal of logging decisions, not profit
- **Verdict:** `last_candle`. Revisit if Week 1 logs show over-triggering in downtrends.

Falls back to latest tick price for the first 5 minutes after agent start (before first candle close).

---

## Open TK Decisions

- [x] Reference price for dip detection → `last_candle` (see entry below)
- [ ] Final strategy — Option 1 is placeholder only
- [ ] Claude assessment cadence — 30 min assumed, may change with final strategy
- [ ] Double-down logic — stubbed as False pending strategic decision

---
