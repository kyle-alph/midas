import logging
from typing import Optional

import config
from state.daily_state import DailyState

logger = logging.getLogger(__name__)


class RiskManager:
    """
    Last line of defense. Hard enforcement only — no reasoning, no LLM calls.
    Every trade passes through here regardless of what strategy or Claude says.
    """

    def can_buy(self, usd_amount: float, daily_state: DailyState) -> tuple[bool, str]:
        """
        Checks in order:
        1. daily_state.halted              → reject "halted"
        2. realized_loss_today >= limit    → reject "daily loss limit"
        3. deployed_today + amount > cap   → reject "daily cap exceeded"
        4. amount > max single trade size  → reject "exceeds max trade size"
        Returns (True, '') if all pass.
        """
        if daily_state.halted:
            return False, "halted"

        loss_limit = (
            config.PHASE1_DAILY_LOSS_HALT
            if config.PHASE == 1
            else config.PHASE2_DAILY_LOSS_HALT
        )
        if daily_state.realized_loss_today >= loss_limit:
            return False, "daily loss limit"

        if daily_state.deployed_today + usd_amount > daily_state.daily_cap:
            return False, "daily cap exceeded"

        max_trade = (
            config.PHASE1_MAX_TRADE_USD
            if config.PHASE == 1
            else config.PHASE2_DAILY_CAP_MAX  # Phase 2 per-trade cap TK
        )
        if usd_amount > max_trade:
            return False, "exceeds max trade size"

        return True, ""

    def can_sell(self, position: Optional[dict], daily_state: DailyState) -> tuple[bool, str]:
        """Sells never blocked if a position exists."""
        if position is None:
            return False, "no open position"
        return True, ""

    def get_daily_cap(self, account_value: float) -> float:
        """
        Phase 1: PHASE1_DAILY_DEPLOYED_LIMIT
        Phase 2: min(account_value * PHASE2_DAILY_CAP_PCT, PHASE2_DAILY_CAP_MAX)
        """
        if config.PHASE == 1:
            return config.PHASE1_DAILY_DEPLOYED_LIMIT
        return min(account_value * config.PHASE2_DAILY_CAP_PCT, config.PHASE2_DAILY_CAP_MAX)
