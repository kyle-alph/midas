import logging

import requests

import config

logger = logging.getLogger(__name__)

_TELEGRAM_URL = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"


class Notifier:

    def send_halt_alert(self, reason: str, daily_state) -> None:
        msg = (
            f"🛑 MIDAS HALTED\n"
            f"Reason: {reason}\n"
            f"Loss today: ${daily_state.realized_loss_today:.2f}\n"
            f"Cap: ${daily_state.daily_cap:.2f}\n"
            f"Trades: {daily_state.trade_count_today}"
        )
        self._send(msg)

    def send_hourly_summary(self, daily_state, trades_this_hour: list) -> None:
        if not trades_this_hour:
            return
        msg = (
            f"📊 MIDAS HOURLY\n"
            f"Trades this hour: {len(trades_this_hour)}\n"
            f"PnL today: ${daily_state.net_pnl_today():.2f}\n"
            f"Deployed: ${daily_state.deployed_today:.2f} / ${daily_state.daily_cap:.2f}\n"
            f"Halted: {'Yes' if daily_state.halted else 'No'}"
        )
        self._send(msg)

    def send_eod_summary(self, daily_state) -> None:
        msg = (
            f"🌙 MIDAS END OF DAY\n"
            f"Trades: {daily_state.trade_count_today}\n"
            f"PnL: ${daily_state.net_pnl_today():.2f}\n"
            f"Deployed: ${daily_state.deployed_today:.2f}\n"
            f"Halted today: {'Yes' if daily_state.halted else 'No'}"
        )
        self._send(msg)

    def send_test(self) -> None:
        self._send("✅ Midas is alive — Telegram alerts working")

    def _send(self, message: str) -> None:
        if config.DRY_RUN:
            logger.info("[DRY_RUN] Telegram suppressed: %s", message)
            return
        try:
            resp = requests.post(
                _TELEGRAM_URL,
                json={"chat_id": config.TELEGRAM_CHAT_ID, "text": message},
                timeout=10,
            )
            if not resp.ok:
                logger.error("[Notifier] Telegram error %d: %s", resp.status_code, resp.text)
        except requests.RequestException as exc:
            logger.error("[Notifier] Telegram request failed: %s", exc)
