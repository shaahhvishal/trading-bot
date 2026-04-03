"""
Real-time 15m candle predictor for prediction markets.

Connects to Binance WebSocket, aggregates 1m→15m candles,
runs CandlePredictorStrategy, and outputs predictions via
console + optional Telegram alerts.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable

import websockets
from loguru import logger

BINANCE_WS_URL = "wss://stream.binance.us:9443/ws"
CANDLES_PER_15M = 15


class CandleAggregator15m:
    """Aggregates 1-minute candles into 15-minute candles."""

    def __init__(self) -> None:
        self._buffer: dict[str, list[dict]] = defaultdict(list)
        self._lock = threading.Lock()

    def add_candle(self, symbol: str, candle_1m: dict) -> dict | None:
        """Add a 1m candle. Returns completed 15m candle if ready."""
        with self._lock:
            buf = self._buffer[symbol]
            buf.append(candle_1m)

            ts = candle_1m["timestamp"]
            if hasattr(ts, "minute"):
                minute = ts.minute
            else:
                minute = datetime.fromisoformat(str(ts)).minute

            # 15m boundaries: minute 0, 15, 30, 45
            at_boundary = minute % 15 == 14  # last minute of the 15m block

            if at_boundary and len(buf) >= 1:
                candle_15m = self._aggregate(buf)
                buf.clear()
                return candle_15m

            # If buffer gets too large (missed boundary), flush
            if len(buf) > CANDLES_PER_15M + 2:
                candle_15m = self._aggregate(buf)
                buf.clear()
                return candle_15m

            return None

    def _aggregate(self, candles: list[dict]) -> dict:
        return {
            "timestamp": candles[0]["timestamp"],
            "open": candles[0]["open"],
            "high": max(c["high"] for c in candles),
            "low": min(c["low"] for c in candles),
            "close": candles[-1]["close"],
            "volume": sum(c["volume"] for c in candles),
        }


class PredictionFeed:
    """WebSocket feed that produces 15m predictions."""

    def __init__(
        self,
        symbol: str = "BTC/USDT",
        on_prediction: Callable | None = None,
    ) -> None:
        self.symbol = symbol
        self.on_prediction = on_prediction
        self._aggregator = CandleAggregator15m()
        self._running = False
        self._reconnect_delay = 1.0

    def _ws_symbol(self) -> str:
        """Convert BTC/USDT → btcusdt."""
        return self.symbol.replace("/", "").lower()

    async def _connect(self) -> None:
        stream = f"{self._ws_symbol()}@kline_1m"
        url = f"{BINANCE_WS_URL}/{stream}"

        while self._running:
            try:
                logger.info(f"Connecting to {url}...")
                async with websockets.connect(url, ping_interval=20) as ws:
                    logger.info(f"Connected — streaming {self.symbol} 1m candles")
                    self._reconnect_delay = 1.0

                    async for msg in ws:
                        if not self._running:
                            break
                        await self._handle_message(msg)

            except (websockets.ConnectionClosed, ConnectionError, OSError) as e:
                if not self._running:
                    break
                logger.warning(f"Disconnected: {e}. Reconnecting in {self._reconnect_delay:.0f}s...")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60.0)

    async def _handle_message(self, raw: str) -> None:
        data = json.loads(raw)
        kline = data.get("k")
        if not kline or not kline.get("x"):  # x = is_closed
            return

        candle_1m = {
            "timestamp": datetime.fromtimestamp(kline["t"] / 1000, tz=timezone.utc),
            "open": float(kline["o"]),
            "high": float(kline["h"]),
            "low": float(kline["l"]),
            "close": float(kline["c"]),
            "volume": float(kline["v"]),
        }

        candle_15m = self._aggregator.add_candle(self.symbol, candle_1m)
        if candle_15m is not None and self.on_prediction:
            await self.on_prediction(candle_15m)

    async def start(self) -> None:
        self._running = True
        await self._connect()

    def stop(self) -> None:
        self._running = False
