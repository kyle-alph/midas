"""
Single agent worker process.

Standalone usage:
  python3 -m workers.agent_worker --agent-id conservative --config agents.yaml

When spawned by orchestrator, receives a multiprocessing.Queue for price ticks
instead of starting its own WebSocket feed.
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from multiprocessing import Queue as MPQueue
from typing import Optional

import yaml

import config as global_config
from agent.claude_agent import ClaudeAgent
from alerts.notifier import Notifier
from broker.coinbase_broker import CoinbaseBroker
from feed.websocket_feed import WebSocketFeed
from logger.decision_log import DecisionLog
from pause import is_paused
from risk.agent_risk_manager import AgentRiskManager
from state.daily_state import DailyState


def _setup_logging(agent_id: str) -> None:
    os.makedirs("logs", exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    fh = logging.FileHandler(f"logs/{agent_id}.log")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _get_strategy(strategy_name: str, params: dict):
    if strategy_name == "bollinger_mean_reversion":
        from strategy.bollinger_mean_reversion import BollingerMeanReversion
        return BollingerMeanReversion(params)
    if strategy_name == "momentum_breakout":
        from strategy.momentum_breakout import MomentumBreakout
        return MomentumBreakout(params)
    if strategy_name in ("dip_detector", "dip"):
        from strategy.dip_detector import DipDetector
        return DipDetector()
    raise ValueError(f"Unknown strategy: {strategy_name!r}")


def run_agent(agent_cfg: dict, price_queue: Optional[MPQueue] = None) -> None:
    """
    Entry point for a single agent process. Called by orchestrator (with price_queue)
    or directly via CLI (price_queue=None, spawns its own feed).
    """
    agent_id = agent_cfg["id"]
    _setup_logging(agent_id)
    logger = logging.getLogger(f"worker.{agent_id}")

    logger.info(
        "Agent %s starting — strategy=%s phase=%d dry_run=%s symbol=%s",
        agent_id,
        agent_cfg.get("strategy", "unknown"),
        agent_cfg.get("phase", global_config.PHASE),
        global_config.DRY_RUN,
        agent_cfg["symbol"],
    )

    symbol = agent_cfg["symbol"]
    params = agent_cfg.get("params", {})
    daily_cap_usd = float(agent_cfg["daily_cap_usd"])
    max_trade_usd = float(agent_cfg.get("max_trade_usd", daily_cap_usd))
    daily_loss_halt_usd = float(agent_cfg["daily_loss_halt_usd"])

    is_paper = agent_cfg.get("paper_trading", True)
    broker = CoinbaseBroker(
        paper_trading=is_paper,
        paper_position_file=f"paper_position_{agent_id}.json" if is_paper else None,
    )
    detector = _get_strategy(agent_cfg["strategy"], params)
    agent = ClaudeAgent()
    risk = AgentRiskManager(
        max_trade_usd=max_trade_usd,
        daily_cap_usd=daily_cap_usd,
        daily_loss_halt_usd=daily_loss_halt_usd,
    )
    log = DecisionLog()
    notifier = Notifier(agent_id=agent_id)
    daily_state = DailyState.load_or_create(
        broker.get_account_value(),
        state_file=f"state_{agent_id}.json",
        daily_cap_override=daily_cap_usd,
    )

    # Price source: shared queue (orchestrator) or own WebSocket feed (standalone).
    own_feed: Optional[WebSocketFeed] = None
    if price_queue is None:
        own_feed = WebSocketFeed(symbol=symbol)
        own_feed.start()

        def get_price() -> Optional[float]:
            return own_feed.get_latest_price()

        def get_ref_price() -> Optional[float]:
            return own_feed.get_reference_price()
    else:
        _last: dict = {"price": None}

        def get_price() -> Optional[float]:
            try:
                while True:
                    _last["price"] = price_queue.get_nowait()
            except Exception:
                pass
            return _last["price"]

        # TK: reference price (5-min candle close) requires feed-level tracking.
        # In queue mode we use the last received tick as a proxy for now.
        def get_ref_price() -> Optional[float]:
            return _last["price"]

    last_claude_call = 0.0
    claude_assessment = None
    last_hourly_alert = datetime.now().replace(minute=0, second=0, microsecond=0).timestamp()
    trades_this_hour: list = []
    eod_sent_today = datetime.now().hour >= global_config.EOD_SUMMARY_HOUR
    snapshot = None
    candles: list = []
    last_candle_fetch = 0.0
    _CANDLE_TTL_SEC = 300
    _heartbeat_file = f"logs/{agent_id}.heartbeat"
    _last_heartbeat = 0.0

    while True:
        if is_paused():
            logger.info("Agent %s paused (PAUSED file present)", agent_id)
            time.sleep(global_config.PAUSE_CHECK_INTERVAL_SEC)
            continue

        daily_state = daily_state.maybe_reset(broker.get_account_value(), daily_cap_override=daily_cap_usd)

        if daily_state.halted:
            time.sleep(global_config.PAUSE_CHECK_INTERVAL_SEC)
            continue

        current_price = get_price()
        if current_price is None:
            time.sleep(1)
            continue

        if time.time() - last_candle_fetch > _CANDLE_TTL_SEC:
            try:
                candles = broker.fetch_candles(symbol, granularity_sec=300, limit=25)
                last_candle_fetch = time.time()
            except Exception as exc:
                logger.warning("Candle fetch failed — using cached data: %s", exc)

        position = broker.get_open_position(symbol)

        if time.time() - last_claude_call > global_config.CLAUDE_ASSESSMENT_INTERVAL_SEC:
            snapshot = agent._build_market_snapshot(broker, current_price)
            claude_assessment = agent.assess_market(snapshot)
            last_claude_call = time.time()

        signal = "HOLD"
        if position:
            should_sell, reason = detector.should_sell(current_price, position)
            if should_sell:
                signal = f"SELL_{reason.upper()}"
        else:
            if claude_assessment and claude_assessment["favorable_to_trade"]:
                threshold = claude_assessment.get(
                    "suggested_dip_threshold_pct", global_config.DIP_THRESHOLD_PCT
                )
                reference_price = get_ref_price()
                if detector.should_buy(
                    current_price, reference_price, daily_state, position, threshold,
                    candles=candles,
                ):
                    signal = "BUY"

        risk_approved = False
        rejection_reason = None
        trade_executed = False
        order = None
        balance_before = broker.get_balance()

        if signal == "BUY":
            size = min(daily_cap_usd, daily_state.remaining_budget())
            risk_approved, rejection_reason = risk.can_buy(size, daily_state)
            if risk_approved:
                order = broker.place_market_buy(symbol, size)
                daily_state.record_buy(size)
                trade_executed = True
                trades_this_hour.append(order)

        elif signal.startswith("SELL_"):
            risk_approved, rejection_reason = risk.can_sell(position, daily_state)
            if risk_approved and position:
                order = broker.place_market_sell(symbol, position["btc_amount"])
                pnl = order["filled_value"] - position["cost_basis"]
                daily_state.record_sell(pnl)
                trade_executed = True
                trades_this_hour.append(order)

                if daily_state.realized_loss_today >= daily_loss_halt_usd:
                    daily_state.halted = True
                    notifier.send_halt_alert(
                        f"[{agent_id}] Daily loss limit reached", daily_state
                    )

        balance_after = broker.get_balance() if trade_executed else balance_before

        if time.time() - last_hourly_alert > 3600:
            notifier.send_hourly_summary(daily_state, trades_this_hour)
            trades_this_hour = []
            last_hourly_alert = time.time()

        now = datetime.now()
        if now.hour == global_config.EOD_SUMMARY_HOUR and not eod_sent_today:
            notifier.send_eod_summary(daily_state)
            eod_sent_today = True
        if now.hour == global_config.DAILY_RESET_HOUR:
            eod_sent_today = False

        log.write(
            agent_id=agent_id,
            current_price=current_price,
            market_snapshot=snapshot if claude_assessment else None,
            claude_assessment=claude_assessment,
            strategy_signal=signal,
            risk_approved=risk_approved,
            risk_rejection_reason=rejection_reason,
            trade_executed=trade_executed,
            order=order,
            position=position,
            daily_state=daily_state,
            balance_before=balance_before,
            balance_after=balance_after,
        )

        now_ts = time.time()
        if now_ts - _last_heartbeat >= 10:
            try:
                with open(_heartbeat_file, "w") as _hbf:
                    _hbf.write(str(now_ts))
                _last_heartbeat = now_ts
            except OSError:
                pass

        time.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent_worker")
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--config", default="agents.yaml")
    args = parser.parse_args()

    with open(args.config) as f:
        data = yaml.safe_load(f)

    agents_by_id = {a["id"]: a for a in data["agents"]}
    if args.agent_id not in agents_by_id:
        print(f"Unknown agent ID: {args.agent_id!r}. Available: {list(agents_by_id)}")
        sys.exit(1)

    run_agent(agents_by_id[args.agent_id])


if __name__ == "__main__":
    main()
