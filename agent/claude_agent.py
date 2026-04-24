import json
import logging
import time
from typing import Optional

import anthropic
import pandas as pd

import config

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a market assessment agent for a BTC-USD trading system.
Evaluate whether current conditions are favorable for dip-buying.

Respond ONLY in JSON, no preamble:
{
  "favorable_to_trade": true or false,
  "suggested_dip_threshold_pct": -0.002,
  "reasoning": "one sentence",
  "confidence": "high" or "medium" or "low"
}

Rules:
- 4h RSI > 70 and strong uptrend: loosen threshold to -0.003
- 4h RSI < 35: set favorable_to_trade to false
- 24h change worse than -5%: set favorable_to_trade to false
- Otherwise: favorable_to_trade true, threshold -0.002
- Never suggest threshold shallower than -0.001 or deeper than -0.005"""

_SAFE_DEFAULT = {
    "favorable_to_trade": True,
    "suggested_dip_threshold_pct": config.DIP_THRESHOLD_PCT,
    "reasoning": "Claude assessment failed — using safe default.",
    "confidence": "low",
}

_CANDLE_CACHE_TTL_SEC = 900   # 15 min


class ClaudeAgent:

    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self._candle_cache: dict = {}
        self._cache_ts: float = 0.0

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def assess_market(self, market_snapshot: dict) -> dict:
        """
        Returns:
        {"favorable_to_trade": bool, "suggested_dip_threshold_pct": float,
         "reasoning": str, "confidence": "high"|"medium"|"low"}
        On error: returns safe default with favorable_to_trade=True, confidence=low.
        Never lets a Claude failure halt the agent loop.
        """
        # STUB: real implementation wired below; swap comment to activate stub.
        # return self._stub_assessment()

        try:
            user_content = json.dumps(market_snapshot, indent=2)
            response = self._client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=256,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            text = response.content[0].text.strip()
            result = json.loads(text)

            # Clamp threshold to safe range
            threshold = result.get("suggested_dip_threshold_pct", config.DIP_THRESHOLD_PCT)
            result["suggested_dip_threshold_pct"] = max(-0.005, min(-0.001, threshold))
            return result

        except Exception as exc:
            logger.warning("ClaudeAgent.assess_market failed: %s — using safe default", exc)
            return dict(_SAFE_DEFAULT)

    def _build_market_snapshot(self, broker, current_price: float) -> dict:
        """
        Fetches 1h and 4h OHLCV via REST (not WebSocket).
        Computes via pandas-ta: RSI(14) on 1h, SMA(20) on 4h.
        Candle data cached for up to 15 min.
        """
        now = time.time()
        if now - self._cache_ts > _CANDLE_CACHE_TTL_SEC:
            self._candle_cache = self._fetch_candles(broker)
            self._cache_ts = now

        candles = self._candle_cache
        snapshot: dict = {"current_price": current_price}

        try:
            import pandas_ta as ta

            df_1h = candles.get("1h")
            df_4h = candles.get("4h")

            if df_1h is not None and not df_1h.empty:
                rsi_1h = ta.rsi(df_1h["close"], length=14)
                snapshot["rsi_1h"] = float(rsi_1h.iloc[-1]) if rsi_1h is not None else None

            if df_4h is not None and not df_4h.empty:
                rsi_4h = ta.rsi(df_4h["close"], length=14)
                sma_4h = ta.sma(df_4h["close"], length=20)
                snapshot["rsi_4h"] = float(rsi_4h.iloc[-1]) if rsi_4h is not None else None
                snapshot["sma_4h"] = float(sma_4h.iloc[-1]) if sma_4h is not None else None

                # 24h change from 4h candles (last 6 candles = 24h)
                if len(df_4h) >= 7:
                    price_24h_ago = float(df_4h["close"].iloc[-7])
                    snapshot["change_24h_pct"] = (current_price - price_24h_ago) / price_24h_ago

        except Exception as exc:
            logger.warning("_build_market_snapshot indicator computation failed: %s", exc)

        return snapshot

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _fetch_candles(self, broker) -> dict:
        """Fetch 1h and 4h OHLCV candles via REST. Returns {"1h": df, "4h": df}."""
        result = {}
        for granularity, key in [("ONE_HOUR", "1h"), ("FOUR_HOUR", "4h")]:
            try:
                resp = broker._client.get_candles(
                    product_id=config.SYMBOL,
                    start=str(int(time.time()) - 86400 * 2),   # 2 days back
                    end=str(int(time.time())),
                    granularity=granularity,
                )
                candles_raw = resp.get("candles", [])
                if candles_raw:
                    df = pd.DataFrame(candles_raw)
                    df["close"] = df["close"].astype(float)
                    df["open"] = df["open"].astype(float)
                    df["high"] = df["high"].astype(float)
                    df["low"] = df["low"].astype(float)
                    df["volume"] = df["volume"].astype(float)
                    df["start"] = pd.to_datetime(df["start"].astype(int), unit="s")
                    df = df.sort_values("start").reset_index(drop=True)
                    result[key] = df
            except Exception as exc:
                logger.warning("_fetch_candles(%s) failed: %s", granularity, exc)
        return result

    def _stub_assessment(self) -> dict:
        return {
            "favorable_to_trade": True,
            "suggested_dip_threshold_pct": -0.002,
            "reasoning": "STUB — not yet implemented",
            "confidence": "low",
        }
