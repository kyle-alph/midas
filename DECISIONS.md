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

## Open TK Decisions

- [ ] Reference price for dip detection (session open? last 5-min candle? last Claude price?)
- [ ] Final strategy — Option 1 is placeholder only
- [ ] Claude assessment cadence — 30 min assumed, may change with final strategy
- [ ] Double-down logic — stubbed as False pending strategic decision

---
