import logging
from typing import Optional

import pandas as pd

import config
from state.daily_state import DailyState

logger = logging.getLogger(__name__)

# TK: Bollinger Band mean reversion strategy — scaffold stub.
# Buy signal: price touches lower band (mean - bb_std * stddev).
# Sell signal: price reverts to upper band or hits stop loss.
# Requires real candle history for band computation — not yet wired.


class BollingerMeanReversion:

    def __init__(self, params: dict) -> None:
        self._bb_period = params.get("bb_period", 20)
        self._bb_std = params.get("bb_std", 2.0)
        self._take_profit_pct = params.get("take_profit_pct", 0.006)
        self._stop_loss_pct = params.get("stop_loss_pct", -0.008)
        self._volume_filter = params.get("volume_filter", False)

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
            logger.debug("BollingerMeanReversion.should_buy — insufficient candles (%d)", len(candles) if candles else 0)
            return False
        closes = pd.Series([c["close"] for c in candles[-self._bb_period:]])
        lower_band = closes.mean() - self._bb_std * closes.std()
        return current_price < lower_band

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
