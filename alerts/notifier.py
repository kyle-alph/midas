import logging

from twilio.rest import Client

import config
from state.daily_state import DailyState

logger = logging.getLogger(__name__)


class Notifier:

    def __init__(self) -> None:
        self._client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)

    def send_halt_alert(self, reason: str, daily_state: DailyState) -> None:
        """Immediate SMS on halt condition."""
        body = (
            f"[HALT] {reason} | "
            f"Loss: ${daily_state.realized_loss_today:.2f} | "
            f"Cap: ${daily_state.daily_cap:.2f} | "
            f"Trades: {daily_state.trade_count_today}"
        )
        self._send(body)

    def send_hourly_summary(self, daily_state: DailyState, trades_this_hour: list) -> None:
        """Send only if trades occurred this hour."""
        if not trades_this_hour:
            return
        body = (
            f"[HOURLY] {len(trades_this_hour)} trade(s) | "
            f"PnL: ${daily_state.net_pnl_today():+.2f} | "
            f"Deployed: ${daily_state.deployed_today:.2f}/${daily_state.daily_cap:.2f} | "
            f"Halted: {'Y' if daily_state.halted else 'N'}"
        )
        self._send(body)

    def send_eod_summary(self, daily_state: DailyState) -> None:
        """Sent at EOD_SUMMARY_HOUR (8AM) before 9AM reset."""
        body = (
            f"[EOD] {daily_state.date} | "
            f"Trades: {daily_state.trade_count_today} | "
            f"PnL: ${daily_state.net_pnl_today():+.2f} | "
            f"Profit: ${daily_state.realized_profit_today:.2f} | "
            f"Loss: ${daily_state.realized_loss_today:.2f} | "
            f"Deployed: ${daily_state.deployed_today:.2f}"
        )
        self._send(body)

    def _send(self, body: str) -> None:
        if config.DRY_RUN:
            logger.info("[DRY_RUN] SMS suppressed: %s", body)
            return
        try:
            msg = self._client.messages.create(
                body=body,
                from_=config.TWILIO_FROM_NUMBER,
                to=config.TWILIO_TO_NUMBER,
            )
            logger.info("SMS sent: sid=%s", msg.sid)
        except Exception as exc:
            logger.error("SMS send failed: %s", exc)
