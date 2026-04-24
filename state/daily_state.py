import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, date

import config

logger = logging.getLogger(__name__)

STATE_FILE = "state.json"


@dataclass
class DailyState:
    date: str                   # YYYY-MM-DD
    daily_cap: float            # Frozen at 9AM reset, never changes intraday
    deployed_today: float       # Total USD in buys today
    realized_loss_today: float  # Total losses (positive = loss)
    realized_profit_today: float
    trade_count_today: int      # Completed round-trip trades
    buy_count_today: int        # Individual buy executions
    halted: bool
    last_reset_date: str

    # ------------------------------------------------------------------ #
    # Computed helpers                                                     #
    # ------------------------------------------------------------------ #

    def remaining_budget(self) -> float:
        return max(0.0, self.daily_cap - self.deployed_today)

    def net_pnl_today(self) -> float:
        return self.realized_profit_today - self.realized_loss_today

    # ------------------------------------------------------------------ #
    # Mutators                                                             #
    # ------------------------------------------------------------------ #

    def record_buy(self, usd_amount: float) -> None:
        self.deployed_today += usd_amount
        self.buy_count_today += 1
        self._save()

    def record_sell(self, pnl: float) -> None:
        if pnl >= 0:
            self.realized_profit_today += pnl
        else:
            self.realized_loss_today += abs(pnl)
        self.trade_count_today += 1
        self._save()

    # ------------------------------------------------------------------ #
    # Reset logic                                                          #
    # ------------------------------------------------------------------ #

    def maybe_reset(self, account_value: float) -> "DailyState":
        now = datetime.now()
        today_str = date.today().isoformat()

        if self.date != today_str and now.hour >= config.DAILY_RESET_HOUR:
            logger.info("Daily reset triggered (date=%s → %s)", self.date, today_str)
            new_cap = _compute_daily_cap(account_value)

            # Carry-over: if open position value >= new cap, no remaining budget.
            # The caller is responsible for passing position value if needed;
            # here we conservatively set deployed_today = 0 and let remaining_budget
            # reflect the full cap. Callers in main.py handle position carry-over
            # by comparing position value against remaining_budget before trading.
            new_state = DailyState(
                date=today_str,
                daily_cap=new_cap,
                deployed_today=0.0,
                realized_loss_today=0.0,
                realized_profit_today=0.0,
                trade_count_today=0,
                buy_count_today=0,
                halted=False,
                last_reset_date=self.date,
            )
            new_state._save()
            return new_state

        return self

    # ------------------------------------------------------------------ #
    # Persistence                                                          #
    # ------------------------------------------------------------------ #

    def _save(self) -> None:
        with open(STATE_FILE, "w") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load_or_create(cls, account_value: float) -> "DailyState":
        today_str = date.today().isoformat()
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            state = cls(**data)
            # If file is from a previous day and reset hour has passed, reset now.
            return state.maybe_reset(account_value)
        except (FileNotFoundError, KeyError, TypeError):
            logger.info("No valid state.json found — creating fresh DailyState.")
            cap = _compute_daily_cap(account_value)
            state = cls(
                date=today_str,
                daily_cap=cap,
                deployed_today=0.0,
                realized_loss_today=0.0,
                realized_profit_today=0.0,
                trade_count_today=0,
                buy_count_today=0,
                halted=False,
                last_reset_date=today_str,
            )
            state._save()
            return state


def _compute_daily_cap(account_value: float) -> float:
    if config.PHASE == 1:
        return config.PHASE1_DAILY_DEPLOYED_LIMIT
    # Phase 2: min(30% account value, $500)
    return min(account_value * config.PHASE2_DAILY_CAP_PCT, config.PHASE2_DAILY_CAP_MAX)
