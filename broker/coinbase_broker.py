import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from coinbase.rest import RESTClient

import config

_GRANULARITY_MAP = {
    60:    "ONE_MINUTE",
    300:   "FIVE_MINUTE",
    900:   "FIFTEEN_MINUTE",
    3600:  "ONE_HOUR",
    14400: "FOUR_HOUR",
    86400: "ONE_DAY",
}

logger = logging.getLogger(__name__)


class CoinbaseBroker:

    def __init__(
        self,
        paper_trading: bool | None = None,
        paper_position_file: Optional[str] = None,
    ) -> None:
        self._client = RESTClient(
            api_key=config.COINBASE_API_KEY,
            api_secret=config.COINBASE_API_SECRET,
        )
        self._paper_trading = config.PAPER_TRADING if paper_trading is None else paper_trading
        self._paper_position_file = paper_position_file
        self._paper_position: Optional[dict] = self._load_paper_position()

    # ------------------------------------------------------------------ #
    # Account                                                              #
    # ------------------------------------------------------------------ #

    def get_balance(self) -> float:
        """Total USD cash balance available."""
        accounts = self._client.get_accounts()
        for acct in accounts["accounts"]:
            if acct["currency"] == "USD":
                return float(acct["available_balance"]["value"])
        return 0.0

    def get_account_value(self) -> float:
        """Total account value = cash + open BTC position value at current price."""
        usd_balance = self.get_balance()
        position = self.get_open_position(config.SYMBOL)
        if position:
            return usd_balance + position["current_value_usd"]
        return usd_balance

    def get_current_price(self, symbol: str) -> float:
        """Current mid price for symbol."""
        product = self._client.get_best_bid_ask(product_ids=[symbol])
        pricebook = product["pricebooks"][0]
        best_bid = float(pricebook["bids"][0]["price"])
        best_ask = float(pricebook["asks"][0]["price"])
        return (best_bid + best_ask) / 2.0

    # ------------------------------------------------------------------ #
    # Orders                                                               #
    # ------------------------------------------------------------------ #

    def place_market_buy(self, symbol: str, usd_amount: float) -> dict:
        """
        Place market buy for usd_amount USD.
        PAPER_TRADING: log and return a fake filled dict, never raise.
        Returns: {"order_id", "filled_size", "avg_filled_price", "usd_spent", "status"}
        """
        if self._paper_trading:
            fake_price = self.get_current_price(symbol)
            filled_size = usd_amount / fake_price
            logger.info(
                "[PAPER] BUY %s | $%.2f | ~%.8f BTC @ $%.2f",
                symbol, usd_amount, filled_size, fake_price,
            )
            if self._paper_position is None:
                self._paper_position = {
                    "btc_amount": filled_size,
                    "avg_entry_price": fake_price,
                    "cost_basis": usd_amount,
                }
            else:
                new_btc = self._paper_position["btc_amount"] + filled_size
                new_cost = self._paper_position["cost_basis"] + usd_amount
                self._paper_position = {
                    "btc_amount": new_btc,
                    "avg_entry_price": new_cost / new_btc,
                    "cost_basis": new_cost,
                }
            self._save_paper_position()
            return {
                "order_id": f"dry-{uuid.uuid4()}",
                "filled_size": filled_size,
                "avg_filled_price": fake_price,
                "usd_spent": usd_amount,
                "status": "FILLED",
            }

        order = self._client.market_order_buy(
            client_order_id=str(uuid.uuid4()),
            product_id=symbol,
            quote_size=str(round(usd_amount, 2)),
        )
        return self._parse_order_response(order)

    def place_market_sell(self, symbol: str, btc_amount: float) -> dict:
        """
        Place market sell for btc_amount BTC.
        PAPER_TRADING: log and return a fake filled dict, never raise.
        Returns: {"order_id", "filled_value", "avg_filled_price", "btc_sold", "status"}
        """
        if self._paper_trading:
            fake_price = self.get_current_price(symbol)
            filled_value = btc_amount * fake_price
            logger.info(
                "[PAPER] SELL %s | %.8f BTC @ $%.2f | ~$%.2f",
                symbol, btc_amount, fake_price, filled_value,
            )
            self._paper_position = None
            self._save_paper_position()
            return {
                "order_id": f"dry-{uuid.uuid4()}",
                "filled_value": filled_value,
                "avg_filled_price": fake_price,
                "btc_sold": btc_amount,
                "status": "FILLED",
            }

        order = self._client.market_order_sell(
            client_order_id=str(uuid.uuid4()),
            product_id=symbol,
            base_size=str(round(btc_amount, 8)),
        )
        return self._parse_sell_response(order)

    # ------------------------------------------------------------------ #
    # Position                                                             #
    # ------------------------------------------------------------------ #

    def get_open_position(self, symbol: str) -> Optional[dict]:
        """
        # DERIVED — not a native SDK call
        Computes open position from filled orders that have not been closed.
        Returns None if no open position.
        Returns: {"btc_amount", "avg_entry_price", "cost_basis",
                  "current_value_usd", "unrealized_pnl"}
        Uses average cost basis across all fills for current open position.
        """
        if self._paper_trading:
            if self._paper_position is None:
                return None
            pos = self._paper_position
            current_price = self.get_current_price(symbol)
            current_value = pos["btc_amount"] * current_price
            return {
                "btc_amount": pos["btc_amount"],
                "avg_entry_price": pos["avg_entry_price"],
                "cost_basis": pos["cost_basis"],
                "current_value_usd": current_value,
                "unrealized_pnl": current_value - pos["cost_basis"],
            }

        # Fetch recent filled buy orders for the symbol, scoped to last 24h
        # to exclude prior account history outside this agent's trading window
        start_date = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        orders = self._client.list_orders(
            product_id=symbol,
            order_status=["FILLED"],
            order_side="BUY",
            start_date=start_date,
        )

        total_btc = 0.0
        total_cost = 0.0

        for order in orders.get("orders", []):
            filled_size = float(order.get("filled_size", 0))
            avg_price = float(order.get("average_filled_price", 0))
            if filled_size > 0 and avg_price > 0:
                total_btc += filled_size
                total_cost += filled_size * avg_price

        # Subtract fills from sell orders to find net position
        sell_orders = self._client.list_orders(
            product_id=symbol,
            order_status=["FILLED"],
            order_side="SELL",
            start_date=start_date,
        )
        for order in sell_orders.get("orders", []):
            filled_size = float(order.get("filled_size", 0))
            if filled_size > 0:
                total_btc -= filled_size

        total_btc = round(total_btc, 8)
        if total_btc <= 0.000001:
            return None

        avg_entry = total_cost / (total_btc + sum(
            float(o.get("filled_size", 0))
            for o in sell_orders.get("orders", [])
        )) if total_cost > 0 else 0.0

        current_price = self.get_current_price(symbol)
        current_value = total_btc * current_price
        cost_basis = total_btc * avg_entry

        return {
            "btc_amount": total_btc,
            "avg_entry_price": avg_entry,
            "cost_basis": cost_basis,
            "current_value_usd": current_value,
            "unrealized_pnl": current_value - cost_basis,
        }

    # ------------------------------------------------------------------ #
    # Market data                                                          #
    # ------------------------------------------------------------------ #

    def fetch_candles(self, symbol: str, granularity_sec: int, limit: int) -> list[dict]:
        """
        Returns up to `limit` most recent completed candles, oldest-first.
        Each dict: {start (unix int), open, high, low, close, volume (floats)}.
        """
        granularity = _GRANULARITY_MAP.get(granularity_sec)
        if not granularity:
            raise ValueError(f"Unsupported granularity: {granularity_sec}s")
        end = int(time.time())
        start = end - granularity_sec * (limit + 2)
        resp = self._client.get_candles(
            product_id=symbol,
            start=str(start),
            end=str(end),
            granularity=granularity,
        )
        candles_raw = resp.candles if hasattr(resp, "candles") else resp.get("candles", [])
        result = [
            {
                "start":  int(c.start if hasattr(c, "start") else c["start"]),
                "open":   float(c.open if hasattr(c, "open") else c["open"]),
                "high":   float(c.high if hasattr(c, "high") else c["high"]),
                "low":    float(c.low if hasattr(c, "low") else c["low"]),
                "close":  float(c.close if hasattr(c, "close") else c["close"]),
                "volume": float(c.volume if hasattr(c, "volume") else c["volume"]),
            }
            for c in candles_raw
        ]
        result.sort(key=lambda c: c["start"])
        return result[-limit:]

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _load_paper_position(self) -> Optional[dict]:
        if not self._paper_trading or not self._paper_position_file:
            return None
        try:
            import json as _json
            with open(self._paper_position_file) as f:
                return _json.load(f)
        except (FileNotFoundError, ValueError):
            return None

    def _save_paper_position(self) -> None:
        if not self._paper_position_file:
            return
        import json as _json
        with open(self._paper_position_file, "w") as f:
            _json.dump(self._paper_position, f)



    def _parse_order_response(self, order: dict) -> dict:
        """Parse buy order response into standard dict."""
        success_resp = order.get("success_response", {})
        order_id = success_resp.get("order_id", "")
        # Full fill details require a follow-up get_order call
        details = self._client.get_order(order_id)
        o = details.get("order", {})
        filled_size = float(o.get("filled_size", 0))
        avg_price = float(o.get("average_filled_price", 0))
        return {
            "order_id": order_id,
            "filled_size": filled_size,
            "avg_filled_price": avg_price,
            "usd_spent": filled_size * avg_price,
            "status": o.get("status", "UNKNOWN"),
        }

    def _parse_sell_response(self, order: dict) -> dict:
        """Parse sell order response into standard dict."""
        success_resp = order.get("success_response", {})
        order_id = success_resp.get("order_id", "")
        details = self._client.get_order(order_id)
        o = details.get("order", {})
        filled_size = float(o.get("filled_size", 0))
        avg_price = float(o.get("average_filled_price", 0))
        return {
            "order_id": order_id,
            "filled_value": filled_size * avg_price,
            "avg_filled_price": avg_price,
            "btc_sold": filled_size,
            "status": o.get("status", "UNKNOWN"),
        }
