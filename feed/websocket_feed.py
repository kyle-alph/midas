import json
import logging
import threading
import time
from typing import Optional

from coinbase.websocket import WSClient

import config

logger = logging.getLogger(__name__)

_BACKOFF_MAX_SEC = 60


class WebSocketFeed:
    """
    Persistent WebSocket connection to Coinbase Advanced Trade ticker.
    Runs in a background daemon thread. Thread-safe price reads via Lock.
    """

    def __init__(self, symbol: str) -> None:
        self._symbol = symbol
        self._lock = threading.Lock()
        self._latest_price: Optional[float] = None
        self._last_candle_close: Optional[float] = None
        self._current_candle_bucket: Optional[int] = None  # floor(unix_ts / 300)
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._backoff = config.WEBSOCKET_RECONNECT_DELAY_SEC

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("WebSocketFeed started for %s", self._symbol)

    def stop(self) -> None:
        self._running = False

    def get_latest_price(self) -> Optional[float]:
        with self._lock:
            return self._latest_price

    def get_reference_price(self) -> Optional[float]:
        # last_candle: close of the most recent completed 5-min candle.
        # Falls back to latest tick if no candle has closed yet this session.
        with self._lock:
            return self._last_candle_close if self._last_candle_close is not None else self._latest_price

    # ------------------------------------------------------------------ #
    # Background loop                                                      #
    # ------------------------------------------------------------------ #

    def _run_loop(self) -> None:
        while self._running:
            try:
                self._connect_and_listen()
                # If we exit cleanly, reset backoff
                self._backoff = config.WEBSOCKET_RECONNECT_DELAY_SEC
            except Exception as exc:
                logger.warning(
                    "WebSocket disconnected: %s — reconnecting in %ds",
                    exc, self._backoff,
                )
                time.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, _BACKOFF_MAX_SEC)

    def _connect_and_listen(self) -> None:
        logger.info("Connecting WebSocket for %s", self._symbol)

        client = WSClient(
            api_key=config.COINBASE_API_KEY,
            api_secret=config.COINBASE_API_SECRET,
            on_message=self._on_message,
            on_open=self._on_open,
            on_close=self._on_close,
        )

        client.open()
        client.subscribe(product_ids=[self._symbol], channels=["ticker"])
        client.run_forever_with_exception_check()

    def _on_open(self) -> None:
        logger.info("WebSocket connection opened for %s", self._symbol)
        self._backoff = config.WEBSOCKET_RECONNECT_DELAY_SEC

    def _on_close(self) -> None:
        logger.warning("WebSocket connection closed for %s", self._symbol)

    def _on_message(self, msg: str) -> None:
        try:
            data = json.loads(msg)
            if data.get("channel") != "ticker":
                return
            for event in data.get("events", []):
                for tick in event.get("tickers", []):
                    price_str = tick.get("price")
                    if price_str:
                        price = float(price_str)
                        bucket = int(time.time()) // 300  # 5-min bucket
                        with self._lock:
                            if (self._current_candle_bucket is not None
                                    and bucket != self._current_candle_bucket):
                                # 5-min window just rolled — last price was the candle close
                                self._last_candle_close = self._latest_price
                            self._current_candle_bucket = bucket
                            self._latest_price = price
        except (json.JSONDecodeError, ValueError, KeyError):
            pass
