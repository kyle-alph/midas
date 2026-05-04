import logging
import time
from datetime import datetime

import config
from agent.claude_agent import ClaudeAgent
from alerts.notifier import Notifier
from broker.coinbase_broker import CoinbaseBroker
from feed.websocket_feed import WebSocketFeed
from logger.decision_log import DecisionLog
from pause import is_paused
from risk.risk_manager import RiskManager
from state.daily_state import DailyState
from strategy.dip_detector import DipDetector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info(
        "Midas starting — phase=%d dry_run=%s paper_trading=%s symbol=%s",
        config.PHASE, config.DRY_RUN, config.PAPER_TRADING, config.SYMBOL,
    )

    broker      = CoinbaseBroker()
    feed        = WebSocketFeed(symbol=config.SYMBOL)
    detector    = DipDetector()
    agent       = ClaudeAgent()
    risk        = RiskManager()
    log         = DecisionLog()
    notifier    = Notifier()
    daily_state = DailyState.load_or_create(broker.get_account_value())

    feed.start()

    last_claude_call  = 0.0
    claude_assessment = None
    last_hourly_alert = datetime.now().replace(minute=0, second=0, microsecond=0).timestamp()
    trades_this_hour: list = []
    eod_sent_today    = datetime.now().hour >= config.EOD_SUMMARY_HOUR
    snapshot          = None

    while True:

        # 1. Pause check
        if is_paused():
            logger.info("Agent paused (PAUSED file present)")
            time.sleep(config.PAUSE_CHECK_INTERVAL_SEC)
            continue

        # 2. Daily reset (9AM)
        daily_state = daily_state.maybe_reset(broker.get_account_value())

        # 3. Halt check
        if daily_state.halted:
            time.sleep(config.PAUSE_CHECK_INTERVAL_SEC)
            continue

        # 4. Market state
        current_price = feed.get_latest_price()
        if current_price is None:
            time.sleep(1)
            continue

        position = broker.get_open_position(config.SYMBOL)

        # 5. Claude assessment (every CLAUDE_ASSESSMENT_INTERVAL_SEC)
        #    TK: cadence may change when final strategy is defined
        if time.time() - last_claude_call > config.CLAUDE_ASSESSMENT_INTERVAL_SEC:
            snapshot          = agent._build_market_snapshot(broker, current_price)
            claude_assessment = agent.assess_market(snapshot)
            last_claude_call  = time.time()

        # 6. Strategy signal
        #    TK: reference price source is a pending decision (see DECISIONS.md)
        signal = "HOLD"
        if position:
            should_sell, reason = detector.should_sell(current_price, position)
            if should_sell:
                signal = f"SELL_{reason.upper()}"
        else:
            if claude_assessment and claude_assessment["favorable_to_trade"]:
                threshold       = claude_assessment.get(
                    "suggested_dip_threshold_pct", config.DIP_THRESHOLD_PCT
                )
                reference_price = feed.get_reference_price()   # TK stub
                if detector.should_buy(
                    current_price, reference_price, daily_state, position, threshold
                ):
                    signal = "BUY"

        # 7. Risk check → execute
        risk_approved    = False
        rejection_reason = None
        trade_executed   = False
        order            = None
        balance_before   = broker.get_balance()

        if signal == "BUY":
            size = detector.get_trade_size(daily_state)
            risk_approved, rejection_reason = risk.can_buy(size, daily_state)
            if risk_approved:
                order = broker.place_market_buy(config.SYMBOL, size)
                daily_state.record_buy(size)
                trade_executed = True
                trades_this_hour.append(order)

        elif signal.startswith("SELL_"):
            risk_approved, rejection_reason = risk.can_sell(position, daily_state)
            if risk_approved and position:
                order = broker.place_market_sell(config.SYMBOL, position["btc_amount"])
                pnl   = order["filled_value"] - position["cost_basis"]
                daily_state.record_sell(pnl)
                trade_executed = True
                trades_this_hour.append(order)

                loss_limit = (
                    config.PHASE1_DAILY_LOSS_HALT
                    if config.PHASE == 1
                    else config.PHASE2_DAILY_LOSS_HALT
                )
                if daily_state.realized_loss_today >= loss_limit:
                    daily_state.halted = True
                    notifier.send_halt_alert("Daily loss limit reached", daily_state)

        balance_after = broker.get_balance() if trade_executed else balance_before

        # 8. Hourly summary
        if time.time() - last_hourly_alert > 3600:
            notifier.send_hourly_summary(daily_state, trades_this_hour)
            trades_this_hour  = []
            last_hourly_alert = time.time()

        # 9. EoD summary (8AM, once per day)
        now = datetime.now()
        if now.hour == config.EOD_SUMMARY_HOUR and not eod_sent_today:
            notifier.send_eod_summary(daily_state)
            eod_sent_today = True
        if now.hour == config.DAILY_RESET_HOUR:
            eod_sent_today = False

        # 10. Log everything — every iteration, including holds
        log.write(
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

        time.sleep(1)


if __name__ == "__main__":
    main()
