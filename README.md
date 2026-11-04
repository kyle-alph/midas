# Midas

Autonomous BTC-USD trading agent. Deterministic strategies generate signals, Claude gates entries, and a hard risk layer sits between every signal and the exchange. Runs 24/7 under systemd on a DigitalOcean VPS against live Coinbase data.

**Status:** V1 has been paper trading since April 2026 (live prices, real alerts, no real orders). V2, a rebuild for live capital, is in design.

## Design principle

The LLM informs; deterministic code decides. Claude is called every 30 minutes, never per tick, and returns structured JSON. Its suggested threshold is clamped, it cannot size or place orders, and every assessment is logged next to the action taken.

## Architecture

```
Coinbase WebSocket ─► SharedPriceFeed
                         ├─► agent: conservative (Bollinger mean reversion)
                         └─► agent: aggressive   (momentum breakout)
each tick: pause → halt → signal → Claude gate (30 min) → RiskManager → broker → SQLite log
orchestrator.py: restart with backoff, circuit breaker, heartbeat checks
Telegram: hourly trades, end-of-day summary, halt alerts
```

Python · Coinbase Advanced Trade API · Anthropic SDK · pandas-ta · SQLite · systemd · Telegram

## Safety controls

- **Risk gate:** rejects an order if the agent is halted, the daily loss limit is reached, the daily cap would be exceeded, or the order exceeds max trade size. Sells are never blocked.
- **Daily loss halt:** stops the agent for the day and alerts immediately.
- **Supervision:** crashed agents restart with backoff (10s → 300s); 5 crashes in 120s trips a circuit breaker; a heartbeat older than 60s marks an agent as hung.
- **Pause switch:** `touch PAUSED` / `rm PAUSED`, no restart needed.
- **Paper isolation:** the only two order-placing calls sit behind a `PAPER_TRADING` branch.

Every loop iteration, holds included, is written to SQLite with price, signal, Claude's reasoning, risk verdict and order result. Parameter choices and rejected alternatives are in `DECISIONS.md`.

## Running

```bash
# .env: COINBASE_API_KEY, COINBASE_API_SECRET, ANTHROPIC_API_KEY,
#       TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PAPER_TRADING=true
pip install -r requirements.txt
python orchestrator.py --config agents.yaml
python cli.py status --all
```

Built agentically with Claude Code; `CLAUDE.md` holds the persistent project context.

## Known gaps in V1

- The Claude gate fails open: if the call errors, trading continues.
- Retried orders can be placed twice (`client_order_id` is regenerated per call).
- No reconciliation against exchange-reported positions.

## V2 (in design)

A clean rebuild for live capital, designed invariants-first: use cases → invariants → hazard table → state machine → code. Full log: [`docs/v2/DECISIONS.md`](docs/v2/DECISIONS.md).

| Area | Decision | ID |
|---|---|---|
| Source of truth | Coinbase; local DB is a rebuildable cache and audit log | D-003 |
| Orders | Limit buys (can't fill above signal), market sells (exits always fill) | D-004 |
| Daily cap | Cumulative spend, which bounds daily loss | D-006 |
| State at decision time | Fresh exchange read before every order | D-007 |
| Concurrency | One instance per strategy, one executor per process | D-013 |
| Divergence | Expected positions checked against exchange; halt in live | D-017 |
| Unknown order state | Intent persisted before send; deterministic `client_order_id`; query by ID on timeout | D-020 |
| Paper mode | Simulator behind the live interface, with fees and slippage | D-016 |

V1's gaps in V2: reconciliation is covered by D-003/D-007/D-017, order-state uncertainty by D-020, and the LLM moves out of the order path (D-002).
