import logging
from typing import Optional

from state.daily_state import DailyState

logger = logging.getLogger(__name__)


class AgentRiskManager:
    """
    Per-agent risk manager. Caps come from agents.yaml, not config.py constants.
    Same interface as RiskManager so agent_worker can swap them transparently.
    """

    def __init__(
        self,
        max_trade_usd: float,
        daily_cap_usd: float,
        daily_loss_halt_usd: float,
    ) -> None:
        self._max_trade = max_trade_usd
        self._daily_cap = daily_cap_usd
        self._loss_halt = daily_loss_halt_usd

    def can_buy(self, usd_amount: float, daily_state: DailyState) -> tuple[bool, str]:
        if daily_state.halted:
            return False, "halted"
        if daily_state.realized_loss_today >= self._loss_halt:
            return False, "daily loss limit"
        if daily_state.deployed_today + usd_amount > daily_state.daily_cap:
            return False, "daily cap exceeded"
        if usd_amount > self._max_trade:
            return False, "exceeds max trade size"
        return True, ""

    def can_sell(self, position: Optional[dict], daily_state: DailyState) -> tuple[bool, str]:
        if position is None:
            return False, "no open position"
        return True, ""
