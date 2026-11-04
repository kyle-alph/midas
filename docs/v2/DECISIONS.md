# Midas V2 — Decision Log

Append-only. Supersede an entry with a new one that references its ID; never edit or delete.
Status: `Accepted` · `Proposed` · `Superseded by D-xxx` · `TK` (pending)

---

## D-001 — Rebuild from scratch
- **2026-11-02 · Accepted**
- Clean codebase instead of extending v1. v1 was built feature-first for paper-trading data; its safety properties (reconciliation, idempotent orders, fail-closed behavior) were never designed in. V2 traces every safeguard to a stated invariant.

## D-002 — Python
- **2026-11-02 · Accepted** · Rejected: Java
- The hard parts (state machine, idempotency, single writer) are language-agnostic. Python has the stronger AI SDK ecosystem for the P1 LLM strategy optimizer.
- Trade-off: Java is the stronger personal language for typing and concurrency.

## D-003 — Source of truth: Coinbase
- **2026-11-02 · Accepted** · Rejected: local DB
- Money moves on the exchange, so disagreements resolve in its favor. The local DB is a rebuildable cache plus the audit log.

## D-004 — Limit buys, market sells
- **2026-11-02 · Accepted** · Rejected: all limit, all market
- Limit buys can't fill above the signal price, which removes stale-price risk on entry.
- Market sells always fill. A limit stop can sit unfilled in a falling market, the worst-case loss (INV-04). TP/SL math assumes taker fees on exit.

## D-005 — SQLite
- **2026-11-02 · Accepted** · Rejected: Postgres
- Single writer, zero ops. A two-way door because of D-003, as long as all access goes through a repository layer.
- Revisit when multiple processes need concurrent writes.

## D-006 — Daily cap = cumulative spend
- **2026-11-02 · Accepted** · Rejected: max open exposure
- Max exposure lets closed losers free capacity, so daily loss is unbounded. Cumulative spend bounds it at roughly cap × (SL% + slippage + fees). Makes a separate daily-loss breaker (INV-07) redundant.

## D-007 — Read exchange state before each order
- **2026-11-02 · Accepted** · Rejected: WebSocket cache (silently stale on disconnect), DB + periodic reconcile (acts on stale state, INV-14)
- A REST read costs no fees and ~100–300 ms. Limit buys absorb the latency; for sells it beats a rejection for wrong size.
- Pivot to the WebSocket cache if latency causes missed entries or slow exits.

## D-008 — Partial fill at buy TTL
- **2026-11-02 · Accepted**
- Cancel the unfilled remainder; the filled part becomes a normal position. Prevents a late fill after the signal is stale (INV-03).

## D-009 — Day boundary: Pacific
- **2026-11-02 · Superseded by D-012**

## D-010 — Single live instance, single executor
- **2026-11-02 · Proposed (accepted with amendment in D-013)**
- Two processes mean duplicate orders and a doubled cap (INV-01/05/06/16); within one process, check-cap-then-send is a race.
- `flock` at startup; the live API key lives only on the VPS (local runs are paper); one executor consumes a queue and does cap check, exchange read and send one order at a time.

## D-011 — Invariant priority
- **2026-11-02 · Accepted**
- Invariants that directly risk money rank first; ones that don't (e.g. a lost log) rank below. See `INVARIANTS.md`.

## D-012 — Day boundary: UTC
- **2026-11-02 · Accepted · Supersedes D-009** · Rejected: Pacific (DST edges), rolling 24h window
- No DST edges, matches Coinbase and log timestamps. The reset lands mid-afternoon Pacific, so the boundary double-spend happens while Kyle can watch. Rolling window is the fallback if that becomes a concern.

## D-013 — Lock per strategy (amends D-010)
- **2026-11-02 · Accepted** · Rejected: cross-machine lease with fencing tokens
- One process per strategy, so the lock is `midas-<strategy_id>.lock`. `client_order_id` includes `strategy_id`. One executor per process.
- `flock` covers one machine only; the single-host live key covers the rest.

## D-014 — Sell sizing across strategies
- **2026-11-02 · Proposed**
- The exchange BTC balance is shared across strategies. Sell size = `min(strategy's expected position, exchange balance)`, using D-017's table.

## D-015 — Official Coinbase SDK
- **2026-11-02 · Accepted** · Rejected: raw `requests`
- Handles JWT auth and WebSocket. Its sync REST client and threaded WebSocket feed into D-019.

## D-016 — Paper mode: local simulator
- **2026-11-02 · Accepted (simulator, fees, slippage) · Proposed (fill rules, fault injection)**
- A forward test on live public prices, behind the same `ExchangeClient` interface as live, which makes INV-13 enforceable by type. Fees and slippage are mandatory; v1 showed fee-unaware paper trading misleads.
- Proposed fill rules: limit buys fill only when the market trades through the limit; market sells fill at best bid minus slippage; maker/taker fees at the account's tier.
- Proposed fault injection (timeouts, partial fills, dropped messages); without it, paper can only surface divergence Midas causes itself.

## D-017 — Expected-position table and divergence
- **2026-11-02 · Accepted (table, paging) · TK (halt scope)**
- Per-strategy expected positions built from order and fill records, compared with the exchange. Paper: page. Live: page and halt.
- Recommended halt scope: new entries only, exits keep running. Halting exits trades an accounting problem for an INV-04 loss.

## D-018 — Design before code
- **2026-11-02 · Accepted**
- Use cases → workflow → invariants → hazard table → state machine → code. No code before the hazard table and state machine are final.

## D-019 — Concurrency model
- **2026-11-02 · TK**
- Threads + `queue.Queue` (recommended): matches the sync SDK; shared state needs locks.
- `asyncio`: no locks, but every blocking call needs `to_thread`, and one miss stalls the exit monitor (INV-04).
- Either way, a priority queue puts sells ahead of buys.


## D-020 — Unknown order state after a timeout
- **2026-11-02 · Accepted** · Rejected: blind retry (double-buys), assume failure (orphans a live order)
- The most common real-world failure and how duplicates actually happen. Write the order intent to the DB before sending; use a deterministic `client_order_id`, which Coinbase dedupes; on a timeout, query by that ID before doing anything else.

---

## Open (TK)
- TK-01 Buy TTL · TK-02 Exit SLA · TK-03 TP%/SL% (must clear round-trip fees) · TK-04 Cap size · TK-05 Max price age (INV-09). Calibrate in paper.
- TK-06 Multi-process executor design (D-010)
- TK-07 Concurrency model (D-019)
- TK-08 Halt scope on live divergence (D-017)
- TK-09 Slippage model: order-book walk vs fixed bps (D-016)
- TK-10 Simulator fault injection (D-016)
- TK-11 Sell sizing rule (D-014)
