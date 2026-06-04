import logging
from typing import Optional

import pandas as pd

import config
from state.daily_state import DailyState

logger = logging.getLogger(__name__)

# TK: Momentum breakout strategy — scaffold stub.
# Buy signal: price breaks above recent high with volume confirmation (if volume_filter=true).
# Sell signal: price falls below entry by stop_loss_pct or rises above take_profit_pct.
# Requires real candle history and optional volume data — not yet wired.


class MomentumBreakout:

    def __init__(self, params: dict) -> None:
        self._bb_period = params.get("bb_period", 10)
        self._bb_std = params.get("bb_std", 1.5)
        self._take_profit_pct = params.get("take_profit_pct", 0.003)
        self._stop_loss_pct = params.get("stop_loss_pct", -0.005)
        self._volume_filter = params.get("volume_filter", True)

    def should_buy(
        self,
        current_price: float,
        reference_price: Optional[float],
        daily_state: DailyState,
        position: Optional[dict],
        dip_threshold_pct: float = config.DIP_THRESHOLD_PCT,
        candles: Optional[list] = None,
    ) -> bool:
        if daily_state.halted or position is not None:
            return False
        if not candles or len(candles) < self._bb_period:
            logger.debug("MomentumBreakout.should_buy — insufficient candles (%d)", len(candles) if candles else 0)
            return False
        recent = candles[-self._bb_period:]
        closes = pd.Series([c["close"] for c in recent])
        upper_band = closes.mean() + self._bb_std * closes.std()
        if current_price <= upper_band:
            return False
        if self._volume_filter and len(recent) >= 2:
            avg_vol = sum(c["volume"] for c in recent[:-1]) / (len(recent) - 1)
            if recent[-1]["volume"] <= avg_vol:
                return False
        return True

    def should_sell(self, current_price: float, position: dict) -> tuple[bool, str]:
        avg_entry = position["avg_entry_price"]
        if current_price >= avg_entry * (1 + self._take_profit_pct):
            return True, "take_profit"
        if current_price <= avg_entry * (1 + self._stop_loss_pct):
            return True, "stop_loss"
        return False, ""

    def should_double_down(
        self,
        current_price: float,
        position: dict,
        daily_state: DailyState,
    ) -> bool:
        return False

    def get_trade_size(self, daily_state: DailyState) -> float:
        return min(config.PHASE1_MAX_TRADE_USD, daily_state.remaining_budget())
