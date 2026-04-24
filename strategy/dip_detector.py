import logging
from typing import Optional

import config
from state.daily_state import DailyState

logger = logging.getLogger(__name__)

# PHASE 1 PLACEHOLDER STRATEGY — NOT FINAL.
# All threshold values come from config, never hardcoded here.
# Recalibrate all values after Week 1 log review.
#
# TK Option 2: volume filter on dip confirmation
#   - Require current 5-min volume > 20-candle average before triggering buy.
#   - Rationale: filters false dips driven by low-liquidity noise.
#
# TK Option 3: regime detection (trending vs ranging)
#   - Use 1h price vs 4h SMA to detect regime; switch signal logic accordingly.
#   - Rationale: dip-buying in a strong downtrend is a losing strategy.


class DipDetector:

    def should_buy(
        self,
        current_price: float,
        reference_price: float,    # TK: source is a pending decision (see DECISIONS.md)
        daily_state: DailyState,
        position: Optional[dict],
        dip_threshold_pct: float = config.DIP_THRESHOLD_PCT,  # PLACEHOLDER
    ) -> bool:
        """
        Returns True if ALL:
        - No open position (one BTC symbol position at a time)
        - Price dropped >= dip_threshold_pct from reference_price
        - daily_state.remaining_budget() >= get_trade_size(daily_state)
        - daily_state.halted is False
        Additional buys into existing position handled by should_double_down().
        """
        if daily_state.halted:
            return False

        if position is not None:
            return False

        if reference_price is None or reference_price <= 0:
            logger.warning("should_buy: reference_price unavailable, skipping")
            return False

        pct_change = (current_price - reference_price) / reference_price
        if pct_change > dip_threshold_pct:   # PLACEHOLDER threshold
            return False

        trade_size = self.get_trade_size(daily_state)
        if daily_state.remaining_budget() < trade_size:
            return False

        return True

    def should_sell(
        self, current_price: float, position: dict
    ) -> tuple[bool, str]:
        """
        (True, 'take_profit') if price >= avg_entry * (1 + TAKE_PROFIT_PCT)
        (True, 'stop_loss')   if price <= avg_entry * (1 + STOP_LOSS_PCT)
        (False, '')           otherwise
        Uses position["avg_entry_price"] — average cost basis, not per-lot.
        """
        avg_entry = position["avg_entry_price"]

        take_profit_price = avg_entry * (1 + config.TAKE_PROFIT_PCT)   # PLACEHOLDER
        stop_loss_price   = avg_entry * (1 + config.STOP_LOSS_PCT)     # PLACEHOLDER

        if current_price >= take_profit_price:
            return True, "take_profit"
        if current_price <= stop_loss_price:
            return True, "stop_loss"
        return False, ""

    def should_double_down(
        self,
        current_price: float,
        position: dict,
        daily_state: DailyState,
    ) -> bool:
        """
        TK — double-down logic is a pending strategic decision. Stub: always False.
        When implemented:
        - Additional buy into existing position when price drops further.
        - Must remain within remaining daily budget.
        - Requires justification logged to decision_log (why add vs exit and re-enter).
        """
        return False

    def get_trade_size(self, daily_state: DailyState) -> float:
        """
        Phase 1: min(PHASE1_MAX_TRADE_USD, remaining_budget)
        Phase 2: TK — per-position cap to be defined with Phase 2 strategy.
        """
        if config.PHASE == 1:
            return min(config.PHASE1_MAX_TRADE_USD, daily_state.remaining_budget())
        # Phase 2 per-trade size TK
        return min(config.PHASE1_MAX_TRADE_USD, daily_state.remaining_budget())
