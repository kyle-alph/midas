import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Optional

import config
from state.daily_state import DailyState

logger = logging.getLogger(__name__)

DB_FILE = "decisions.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS decisions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                    TEXT NOT NULL,
    phase                 INTEGER NOT NULL,
    paper_trading         INTEGER NOT NULL,
    current_price         REAL,
    market_snapshot       TEXT,
    claude_assessment     TEXT,
    claude_reasoning      TEXT,
    strategy_signal       TEXT,
    risk_approved         INTEGER,
    risk_rejection_reason TEXT,
    trade_executed        INTEGER,
    trade_usd_amount      REAL,
    order_id              TEXT,
    fill_price            REAL,
    position_avg_entry    REAL,
    position_btc_amount   REAL,
    balance_before        REAL,
    balance_after         REAL,
    deployed_today        REAL,
    realized_loss_today   REAL,
    realized_profit_today REAL,
    daily_cap             REAL,
    trade_count_today     INTEGER,
    halted                INTEGER
);
"""


class DecisionLog:

    def __init__(self, db_file: str = DB_FILE) -> None:
        self._db_file = db_file
        with self._conn() as conn:
            conn.execute(_CREATE_TABLE)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_file)

    def write(
        self,
        current_price: Optional[float],
        market_snapshot: Optional[dict],
        claude_assessment: Optional[dict],
        strategy_signal: str,
        risk_approved: bool,
        risk_rejection_reason: Optional[str],
        trade_executed: bool,
        order: Optional[dict],
        position: Optional[dict],
        daily_state: DailyState,
        balance_before: Optional[float] = None,
        balance_after: Optional[float] = None,
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat()

        trade_usd = None
        order_id = None
        fill_price = None
        if order:
            order_id = order.get("order_id")
            fill_price = order.get("avg_filled_price")
            trade_usd = order.get("usd_spent") or order.get("filled_value")

        pos_avg_entry = position["avg_entry_price"] if position else None
        pos_btc = position["btc_amount"] if position else None

        claude_reasoning = None
        if claude_assessment:
            claude_reasoning = claude_assessment.get("reasoning")

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO decisions (
                    ts, phase, paper_trading, current_price,
                    market_snapshot, claude_assessment, claude_reasoning,
                    strategy_signal, risk_approved, risk_rejection_reason,
                    trade_executed, trade_usd_amount, order_id, fill_price,
                    position_avg_entry, position_btc_amount,
                    balance_before, balance_after,
                    deployed_today, realized_loss_today, realized_profit_today,
                    daily_cap, trade_count_today, halted
                ) VALUES (
                    ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                )
                """,
                (
                    ts,
                    config.PHASE,
                    int(config.PAPER_TRADING),
                    current_price,
                    json.dumps(market_snapshot) if market_snapshot else None,
                    json.dumps(claude_assessment) if claude_assessment else None,
                    claude_reasoning,
                    strategy_signal,
                    int(risk_approved),
                    risk_rejection_reason,
                    int(trade_executed),
                    trade_usd,
                    order_id,
                    fill_price,
                    pos_avg_entry,
                    pos_btc,
                    balance_before,
                    balance_after,
                    daily_state.deployed_today,
                    daily_state.realized_loss_today,
                    daily_state.realized_profit_today,
                    daily_state.daily_cap,
                    daily_state.trade_count_today,
                    int(daily_state.halted),
                ),
            )

    def print_recent(self, n: int = 20) -> None:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM decisions ORDER BY id DESC LIMIT ?", (n,)
            ).fetchall()
            cols = [d[0] for d in conn.execute("SELECT * FROM decisions LIMIT 0").description]

        rows.reverse()
        for row in rows:
            record = dict(zip(cols, row))
            signal = record.get("strategy_signal", "?")
            price = record.get("current_price")
            executed = bool(record.get("trade_executed"))
            approved = bool(record.get("risk_approved"))
            rejection = record.get("risk_rejection_reason") or ""
            ts = record.get("ts", "")[:19]

            trade_marker = " [TRADE]" if executed else ""
            risk_marker = f" [REJECTED: {rejection}]" if not approved and rejection else ""
            price_str = f"${price:,.2f}" if price else "N/A"

            print(
                f"{ts}  {signal:<20} {price_str:<14}"
                f"{trade_marker}{risk_marker}"
            )
