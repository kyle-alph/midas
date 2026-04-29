# Midas — Claude Code Context

## What This Is

Autonomous BTC-USD trading agent running 24/7 on a DigitalOcean VPS.
Uses Coinbase Advanced Trade API for execution and Claude Sonnet as a periodic
market assessment layer (not per-tick). Real-time price feed via WebSocket.
Systemd daemon keeps it alive.

**This is a Phase 1 learning build.** Primary goal is generating decision logs
and validating agent behavior — not profit. Several parameters and architectural
decisions are explicitly placeholder and must not be finalized without review.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Exchange | Coinbase Advanced Trade (`coinbase-advanced-py`) |
| AI Layer | Anthropic Claude Sonnet (`anthropic` SDK) |
| Indicators | `pandas` + `pandas-ta` (RSI, SMA) |
| Database | SQLite (stdlib) — `decisions.db` in project root |
| Deployment | DigitalOcean Ubuntu 22.04, systemd (`midas.service`) |
| Alerting | Twilio SMS |

---

## Repository Layout

```
Midas/
├── main.py                 # Orchestration loop
├── config.py               # All constants and env var loading
├── DECISIONS.md            # Append-only parameter justification log
├── pause.py                # PAUSED file checker
├── cli.py                  # Log viewer and status CLI
├── broker/coinbase_broker.py
├── feed/websocket_feed.py  # Background WebSocket thread; auto-reconnects
├── strategy/dip_detector.py
├── agent/claude_agent.py   # Periodic Claude assessment (every 30 min)
├── risk/risk_manager.py    # Hard enforcement — last gate before any order
├── logger/decision_log.py  # SQLite append-only; writes every loop iteration
├── alerts/notifier.py      # Twilio SMS
├── state/daily_state.py    # Intraday tracking; resets at 9AM; persists to state.json
└── midas.service           # systemd unit file
```

---

## Main Loop (main.py)

Each iteration (1-second tick):
1. Pause check (PAUSED file)
2. Daily reset (9AM)
3. Halt check
4. Get current price from WebSocket feed
5. Claude assessment every `CLAUDE_ASSESSMENT_INTERVAL_SEC` (30 min) — returns `favorable_to_trade` + suggested dip threshold
6. Strategy signal: sell check if position open; buy check if Claude is favorable
7. Risk gate (`RiskManager`) — hard caps, never bypassed
8. Execute order via `CoinbaseBroker`
9. Hourly SMS summary (only if trades occurred)
10. EoD SMS summary (8AM, before 9AM reset)
11. Log everything to SQLite — including holds

---

## Phase 1 Caps (config.py)

| Constant | Value | Meaning |
|---|---|---|
| `PHASE1_MAX_TRADE_USD` | $200 | Max single trade |
| `PHASE1_DAILY_DEPLOYED_LIMIT` | $200 | Max deployed per day |
| `PHASE1_DAILY_LOSS_HALT` | $100 | Auto-halt threshold |
| `DIP_THRESHOLD_PCT` | -0.2% | Buy trigger — **PLACEHOLDER** |
| `TAKE_PROFIT_PCT` | +0.15% | TP trigger — **PLACEHOLDER** |
| `STOP_LOSS_PCT` | -0.8% | SL trigger — **PLACEHOLDER** |

All strategy thresholds are placeholders. Do not treat as final. Recalibrate after Week 1 log review.

---

## Open TK Decisions — Do Not Finalize Without Kyle

These are explicitly unresolved. Scaffold stubs exist; do not implement a real approach without a decision logged to DECISIONS.md.

- **Reference price source** (`REFERENCE_PRICE_MODE`) — options: session open, last 5-min candle close, last Claude assessment price. Currently stubbed: `get_reference_price()` returns latest price.
- **Claude assessment cadence** — 30 min is a configurable assumption, not final.
- **Double-down logic** — `should_double_down()` stubs `False`. Pending strategic decision.
- **Final strategy** — Option 1 (dip-buy) is Phase 1 learning vehicle only.
  - Option 2 TK: volume filter on dip confirmation (require volume > 20-candle avg)
  - Option 3 TK: regime detection (1h price vs 4h SMA), switch signal logic
- **Strategy thresholds** — all values marked `# PLACEHOLDER` in config.py and strategy/

---

## Decided — Do Not Revisit

- REST for candle history, WebSocket for live price
- One BTC position at a time; additional buys into same position allowed within daily cap (double-down, when implemented)
- Claude called periodically for assessment — never per tick
- Average cost basis across double-down buys
- Double-down requires justification logged to decision_log
- Domain-driven repo structure
- SQLite for Phase 1 (Postgres migration path is low overhead when needed)
- Daily cap frozen at 9AM — intraday profits do not increase it
- Twilio SMS: hourly (if trades), EoD at 8AM, halt-only immediate
- DECISIONS.md is append-only — never overwrite

---

## DRY_RUN Mode

`DRY_RUN=true` (default). In dry-run, `CoinbaseBroker` logs order intent and returns a fake filled dict without hitting the API. Never raises. Safe to run locally.

---

## Running Locally

```bash
cp .env.example .env   # fill in credentials
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py         # DRY_RUN=true by default
```

CLI:
```bash
python cli.py status
python cli.py logs --n 20
```

Pause/resume without restarting:
```bash
touch PAUSED    # pause
rm PAUSED       # resume
```

---

## VPS Deployment

```bash
sudo cp midas.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable midas
sudo systemctl start midas
journalctl -u midas -f
```

---

## Claude Agent (agent/claude_agent.py)

- System prompt is fixed — do not modify without appending rationale to DECISIONS.md.
- Returns `{"favorable_to_trade": bool, "suggested_dip_threshold_pct": float, "reasoning": str, "confidence": str}`.
- On any exception: returns safe default (`favorable_to_trade: True`, `confidence: low`) — Claude failure must never halt the loop.
- Threshold clamped to [-0.005, -0.001] regardless of Claude output.
- Candle data cached 15 min (`_CANDLE_CACHE_TTL_SEC = 900`).
- Stub available: uncomment `return self._stub_assessment()` in `assess_market()`.

---

## Risk Manager (risk/risk_manager.py)

Last line of defense. Checks in order:
1. `daily_state.halted` → reject
2. `realized_loss_today >= limit` → reject
3. `deployed_today + amount > cap` → reject
4. `amount > PHASE1_MAX_TRADE_USD` → reject

Sells are never blocked if a position exists.

---

## State Persistence

`state/daily_state.py` writes to `state.json` in project root. Survives restarts within the same trading day. Resets at 9AM (`DAILY_RESET_HOUR`). Daily cap is frozen at reset time — intraday profits do not increase it.

---

## Phase 2 Upgrade Paths — Aware But Do Not Build

- Daily cap: `min(30% account_value, $500)`
- Strategy Option 2: volume filter
- Strategy Option 3: regime detection
- Multi-symbol support (broker/feed already use `config.SYMBOL` throughout)
