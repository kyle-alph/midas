import json
import logging
from dataclasses import dataclass, asdict, field
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
    state_file: str = field(default=STATE_FILE, compare=False)  # not persisted to JSON

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

    def maybe_reset(
        self,
        account_value: float,
        daily_cap_override: float | None = None,
    ) -> "DailyState":
        now = datetime.now()
        today_str = date.today().isoformat()

        if self.date != today_str and now.hour >= config.DAILY_RESET_HOUR:
            logger.info("Daily reset triggered (date=%s → %s)", self.date, today_str)
            new_cap = daily_cap_override if daily_cap_override is not None else _compute_daily_cap(account_value)

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
                state_file=self.state_file,
            )
            new_state._save()
            return new_state

        return self

    # ------------------------------------------------------------------ #
    # Persistence                                                          #
    # ------------------------------------------------------------------ #

    def _save(self) -> None:
        data = asdict(self)
        data.pop("state_file", None)  # not persisted; injected on load
        with open(self.state_file, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load_or_create(
        cls,
        account_value: float,
        state_file: str = STATE_FILE,
        daily_cap_override: float | None = None,
    ) -> "DailyState":
        today_str = date.today().isoformat()
        try:
            with open(state_file) as f:
                data = json.load(f)
            data["state_file"] = state_file  # inject before instantiation
            state = cls(**data)
            if daily_cap_override is not None:
                state.daily_cap = daily_cap_override
            return state.maybe_reset(account_value)
        except (FileNotFoundError, KeyError, TypeError):
            logger.info("No valid %s found — creating fresh DailyState.", state_file)
            cap = daily_cap_override if daily_cap_override is not None else _compute_daily_cap(account_value)
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
                state_file=state_file,
            )
            state._save()
            return state


def _compute_daily_cap(account_value: float) -> float:
    if config.PHASE == 1:
        return config.PHASE1_DAILY_DEPLOYED_LIMIT
    # Phase 2: min(30% account value, $500)
    return min(account_value * config.PHASE2_DAILY_CAP_PCT, config.PHASE2_DAILY_CAP_MAX)
