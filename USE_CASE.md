# Midas — Use Cases

## Initial Deployment

**Goal:** Paper trade against live Coinbase data for a few days. Log every decision, fire real Telegram alerts, execute no real orders.

### E2E Walkthrough

**Startup**

`CoinbaseBroker.__init__` creates a `RESTClient` with real credentials and sets `_paper_position = None`. `DailyState.load_or_create` calls `broker.get_account_value()` — hits real Coinbase REST to read USD balance — uses it only to compute `daily_cap = $500` (Phase 1 hardcoded). WebSocket connects and starts streaming live ticks.

---

**Every tick — no dip**

`feed.get_latest_price()` → real price from WebSocket. `broker.get_open_position()` → paper trading branch → `_paper_position is None` → returns `None`. `detector.should_buy()` checks dip threshold — price hasn't moved enough → `signal = "hold"`. `log.write()` fires every iteration, writing `paper_trading=1`, `signal="hold"`, `trade_executed=0` to SQLite. No Coinbase order calls touched.

---

**Buy tick — price dips ≥ 0.2% from candle close**

`detector.should_buy()` returns True. `risk.can_buy($200, daily_state)` checks halted / loss limit / cap / max trade — all pass. Then:

```python
order = broker.place_market_buy("BTC-USD", 200)
```

Inside `place_market_buy`, `if config.PAPER_TRADING:` → enters paper branch. Calls `get_current_price()` (read-only REST) for a realistic fill price. Updates `_paper_position` in memory. Returns a fake `order_id = "dry-<uuid>"`. **`market_order_buy()` is never reached. No real order placed.**

`daily_state.record_buy($200)` → `deployed_today = $200`, persisted to `state.json`. Logged to SQLite with `trade_executed=1`, `order_id="dry-..."`, real fill price, real position snapshot.

---

**Sell tick — price hits take-profit**

`broker.get_open_position()` → paper branch → `_paper_position` has data → calls `get_current_price()` (read-only) → returns paper position with live unrealized PnL. `detector.should_sell()` fires. Then:

```python
order = broker.place_market_sell("BTC-USD", position["btc_amount"])
```

`if config.PAPER_TRADING:` → paper branch. Gets current price (read-only), clears `_paper_position = None`, returns fake order dict. **`market_order_sell()` is never reached. No real sell.**

`pnl = order["filled_value"] - position["cost_basis"]` — real PnL math against paper entry. `daily_state.record_sell(pnl)` persisted. Logged to SQLite.

---

**Alerts**

Telegram fires unconditionally (no DRY_RUN suppression):
- Hourly summary: only if `trades_this_hour` is non-empty
- EoD at 8AM
- Halt alert if daily loss limit hit

---

**Daily reset at 9AM**

`daily_state.maybe_reset()` creates fresh DailyState with `daily_cap=$500`, zeroes all counters, persists to `state.json`. `_paper_position` in the broker is unaffected — any open paper position carries over.

---

**Paper safety — the only two real order methods**

```python
# broker/coinbase_broker.py
order = self._client.market_order_buy(...)   # only if not PAPER_TRADING
order = self._client.market_order_sell(...)  # only if not PAPER_TRADING
```

Both are behind `if config.PAPER_TRADING:` blocks that `return` before reaching them. All other Coinbase calls (`get_accounts`, `get_best_bid_ask`, `get_candles`) are read-only.

---

**Known limitation**

`_paper_position` is in-memory only. A restart wipes it — the agent will think there's no open position and may open a new paper buy. `deployed_today` in `state.json` survives correctly, so daily cap enforcement is unaffected. Acceptable for paper trading.
