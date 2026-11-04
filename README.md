# Midas

An autonomous BTC-USD trading agent. Deterministic strategies generate signals, Claude acts as a periodic market-assessment gate, and a hard risk layer that the model cannot override sits between every signal and the exchange. Runs 24/7 under systemd on a DigitalOcean VPS against live Coinbase market data.

**Status: Phase 1, paper trading.** Live prices, real exchange reads, real alerts, no real orders. The goal of this phase is a complete decision log to evaluate agent behavior against, not profit. Strategy parameters are deliberately provisional until that log is reviewed (see `DECISIONS.md`).

---

## Design principle

The LLM informs and deterministic code decides. Claude is consulted every 30 minutes, never per tick, and its output is treated as untrusted input:

- It returns structured JSON: `favorable_to_trade`, `suggested_dip_threshold_pct`, `reasoning`, `confidence`.
- Any threshold it suggests is clamped to a fixed range before use.
- It cannot size positions, place orders, or bypass any risk check.
- Every assessment and its reasoning is logged next to the action taken.

## Architecture

```
                 Coinbase WebSocket (live ticks)
                              │
                     SharedPriceFeed (1 connection)
                     ┌────────┴────────┐
              agent: conservative   agent: aggressive        ← separate processes
              Bollinger mean-rev.   momentum breakout
                     │                    │
   each tick:  pause check → halt check → strategy signal
               → Claude gate (every 30 min) → RiskManager → broker
               → SQLite decision log (every iteration, holds included)
                     │
              orchestrator.py: supervises workers, restart w/ backoff,
              circuit breaker, heartbeat staleness detection
                     │
              Telegram: hourly trade summary, end-of-day summary, immediate halt / circuit-break alerts
```

| Layer | Implementation |
|---|---|
| Exchange | Coinbase Advanced Trade API: REST for candles/accounts, WebSocket for live price |
| AI layer | Anthropic Claude Sonnet via the `anthropic` SDK |
| Indicators | `pandas`, `pandas-ta` |
| Storage | SQLite append-only decision log; per-agent JSON daily state |
| Runtime | systemd (`midas-orchestrator.service`), `Restart=always` |
| Alerting | Telegram Bot API |

## Multi-agent orchestrator

`agents.yaml` defines independent agents, each with its own strategy, risk caps, state file, and decision-log label:

| Agent | Strategy | Daily cap | Max trade | Daily loss halt |
|---|---|---|---|---|
| `conservative` | Bollinger mean reversion (20, 2.0σ) | $1,000 | $1,000 | $250 |
| `aggressive` | Momentum breakout (10, 1.5σ, volume filter) | $1,000 | $1,000 | $350 |

The orchestrator runs each agent as its own process over one shared price feed. Supervision:
- Crashed workers restart with exponential backoff (10s → 300s).
- 5 crashes inside 120s trips a circuit breaker: auto-restart stops and a Telegram alert fires.
- Each worker writes a heartbeat every 10s; a heartbeat older than 60s counts as a hung worker.

## Safety controls

| Control | Behavior |
|---|---|
| Risk gate | Last check before any order. Rejects if the agent is halted, the daily loss limit is reached, the order would exceed the daily deployed cap, or the order exceeds the max trade size. Sells are never blocked while a position is open. |
| Daily loss halt | Hitting the realized-loss limit halts that agent for the rest of the day and sends an immediate alert. |
| Frozen daily cap | The cap is set at the 9 AM reset; intraday profits do not raise it. |
| Pause switch | `touch PAUSED` pauses every agent without a restart; `rm PAUSED` resumes. |
| Paper isolation | The only two order-placing calls sit behind a `PAPER_TRADING` branch that returns before reaching them. Every other exchange call is read-only. |
| Persistent state | Daily counters and paper positions are persisted to disk and survive restarts. |

## Decision log

Every loop iteration writes a row to SQLite, including holds: price, signal, Claude assessment and reasoning, risk verdict, order result, and position snapshot. That table is the dataset Phase 1 exists to produce. Design and parameter decisions, with the alternatives rejected, are recorded append-only in `DECISIONS.md`.

## Running it

```bash
# .env: COINBASE_API_KEY, COINBASE_API_SECRET, ANTHROPIC_API_KEY,
#       TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PAPER_TRADING=true
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python orchestrator.py --config agents.yaml                # all agents
python orchestrator.py --config agents.yaml --agents conservative

python cli.py status --all       # daily state per agent
python cli.py logs --n 20        # recent decisions
```

Deploy: copy `midas-orchestrator.service` to `/etc/systemd/system/`, then `systemctl enable --now midas-orchestrator`.

## Development

Built agentically with Claude Code. `CLAUDE.md` holds persistent project context for agent sessions: which decisions are closed, which are open and must not be finalized without review, and which Phase 2 paths the agent should know about but not build.

---

## Known gaps

These are listed on purpose. Each is a prerequisite for real capital.

- **The Claude gate fails open.** If the assessment call errors, it returns `favorable_to_trade: True` so the loop never stalls. That is acceptable in paper trading but wrong with real money.
- **Order submission is not idempotent across retries.** `client_order_id` is generated fresh per call, so a retried request can create a second order.
- **No reconciliation.** The agent's believed position is never checked against what the exchange reports.

## Roadmap

**Phase 1.5: hardening before live capital (planned)**
- Make the Claude gate fail closed: on error or low confidence, no new entries; exits are unaffected.
- Generate one `client_order_id` per intended order and reuse it across retries. Handle partial fills and reconnect-then-reconcile after a dropped connection.
- Reconcile believed position against exchange-reported position on startup and on a fixed interval. Halt and alert on divergence; treat the exchange as the source of truth.
- Global kill switch with max-drawdown and anomalous-price circuit breakers, plus a manual override path.
- Handle exchange outages and rate limits with backoff, and halt cleanly when the market-data feed goes stale.
- Use a trade-only API key with no withdrawal permission.

**Phase 2: small live allocation (planned)**
- One agent goes live with a small fixed allocation and enforced loss limits; the other stays on paper as a control.
- Daily cap becomes `min(30% of account value, $500)`.

**Evaluation and observability (planned)**
- Score Claude's assessments against a labeled set of past decisions; compare against a no-LLM baseline.
- Track fill latency, slippage against expected price, reconciliation mismatches, LLM cost per decision, and error and retry rates.
- Failure injection: kill the feed, feed malformed data, force rate limits. Record the results.

**Strategy (open)**
- Pick final strategies from Phase 1 data. Candidates: a volume filter on dip confirmation, and regime switching on 1h price vs. 4h SMA.
