import json
import logging
import threading
import time
from multiprocessing import Queue
from typing import Optional

from coinbase.websocket import WSClient

import config

logger = logging.getLogger(__name__)

_BACKOFF_MAX_SEC = 60


class SharedPriceFeed:
    """
    Single WebSocket connection to Coinbase. Distributes price ticks to all
    registered agent queues (multiprocessing.Queue, one per worker process).
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._queues: list[Queue] = []
        self._latest_price: float = 0.0
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._backoff = config.WEBSOCKET_RECONNECT_DELAY_SEC

    def register_queue(self) -> Queue:
        """Call once per agent before start(). Returns a multiprocessing.Queue."""
        q: Queue = Queue(maxsize=500)
        with self._lock:
            self._queues.append(q)
        return q

    def get_latest_price(self) -> float:
        with self._lock:
            return self._latest_price

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("SharedPriceFeed started for %s", self.symbol)

    def stop(self) -> None:
        self._running = False

    def _on_tick(self, price: float) -> None:
        with self._lock:
            self._latest_price = price
            for q in self._queues:
                try:
                    q.put_nowait(price)
                except Exception:
                    pass  # drop tick if queue is full; agent will use prior price

    def _run_loop(self) -> None:
        while self._running:
            try:
                self._connect_and_listen()
                self._backoff = config.WEBSOCKET_RECONNECT_DELAY_SEC
            except Exception as exc:
                logger.warning(
                    "SharedPriceFeed disconnected: %s — reconnecting in %ds",
                    exc, self._backoff,
                )
                time.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, _BACKOFF_MAX_SEC)

    def _connect_and_listen(self) -> None:
        def on_message(msg: str) -> None:
            try:
                data = json.loads(msg)
                if data.get("channel") != "ticker":
                    return
                for event in data.get("events", []):
                    for tick in event.get("tickers", []):
                        price_str = tick.get("price")
                        if price_str:
                            self._on_tick(float(price_str))
            except (json.JSONDecodeError, ValueError, KeyError):
                pass

        client = WSClient(
            api_key=config.COINBASE_API_KEY,
            api_secret=config.COINBASE_API_SECRET,
            on_message=on_message,
            on_open=lambda: logger.info("SharedPriceFeed WebSocket opened for %s", self.symbol),
            on_close=lambda: logger.warning("SharedPriceFeed WebSocket closed for %s", self.symbol),
        )
        client.open()
        client.subscribe(product_ids=[self.symbol], channels=["ticker"])
        client.run_forever_with_exception_check()
