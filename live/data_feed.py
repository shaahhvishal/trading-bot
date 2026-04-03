"""
Real-time data feed from Binance WebSocket.

Subscribes to 1-minute kline (candlestick) streams for configured symbols,
then aggregates closed 1m candles into 1h candles for strategy consumption.

Features:
  - Auto-reconnect on disconnect with exponential backoff
  - Aggregates 1m candles into 1h candles in-memory
  - Calls a user-provided callback when a new 1h candle completes
  - Thread-safe candle buffer
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable

import websockets
from loguru import logger


# Binance WebSocket base URL for kline streams
BINANCE_WS_URL = "wss://stream.binance.us:9443/ws"

# How many 1m candles make a 1h candle
CANDLES_PER_HOUR = 60


class CandleAggregator:
    """Aggregates 1-minute candles into 1-hour candles."""

    def __init__(self) -> None:
        self._buffer: dict[str, list[dict]] = defaultdict(list)
        self._lock = threading.Lock()

    def add_candle(self, symbol: str, candle_1m: dict) -> dict | None:
        """Add a 1m candle. Returns a completed 1h candle if the hour is full.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            candle_1m: Dict with timestamp, open, high, low, close, volume.

        Returns:
            Aggregated 1h candle dict, or None if the hour isn't complete yet.
        """
        with self._lock:
            buf = self._buffer[symbol]
            buf.append(candle_1m)

            # Check if we've completed an hour boundary
            ts = candle_1m["timestamp"]
            if isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            else:
                dt = ts

            # A 1m candle at :59 means the hour is complete
            if dt.minute == 59 and len(buf) >= 1:
                return self._flush(symbol)

            # Also flush if buffer gets too large (catch-up / reconnect)
            if len(buf) >= CANDLES_PER_HOUR:
                return self._flush(symbol)

        return None

    def _flush(self, symbol: str) -> dict:
        """Aggregate buffered 1m candles into a single 1h candle."""
        buf = self._buffer[symbol]
        candle_1h = {
            "timestamp": buf[0]["timestamp"],
            "open": buf[0]["open"],
            "high": max(c["high"] for c in buf),
            "low": min(c["low"] for c in buf),
            "close": buf[-1]["close"],
            "volume": sum(c["volume"] for c in buf),
        }
        self._buffer[symbol] = []
        return candle_1h


class BinanceDataFeed:
    """Binance WebSocket data feed with auto-reconnect.

    Usage:
        feed = BinanceDataFeed(symbols=["BTC/USDT", "ETH/USDT"])
        feed.on_candle_1h = my_callback  # called when a 1h candle completes
        await feed.start()  # blocks, runs forever
    """

    def __init__(
        self,
        symbols: list[str],
        on_candle_1h: Callable[[str, dict], None] | None = None,
        on_candle_1m: Callable[[str, dict], None] | None = None,
    ) -> None:
        """Initialize data feed.

        Args:
            symbols: List of trading pairs (e.g. ["BTC/USDT"]).
            on_candle_1h: Callback(symbol, candle_dict) when 1h candle completes.
            on_candle_1m: Optional callback for every 1m candle.
        """
        self.symbols = symbols
        self.on_candle_1h = on_candle_1h
        self.on_candle_1m = on_candle_1m
        self._aggregator = CandleAggregator()
        self._running = False
        self._ws = None
        self._reconnect_delay = 1.0  # seconds, grows exponentially

    def _build_stream_url(self) -> str:
        """Build combined stream URL for all symbols."""
        streams = []
        for symbol in self.symbols:
            # Binance format: btcusdt@kline_1m
            pair = symbol.replace("/", "").lower()
            streams.append(f"{pair}@kline_1m")
        combined = "/".join(streams)
        return f"wss://stream.binance.us:9443/stream?streams={combined}"

    async def start(self) -> None:
        """Start the WebSocket feed. Blocks forever, auto-reconnects."""
        self._running = True
        while self._running:
            try:
                await self._connect()
            except asyncio.CancelledError:
                logger.info("Data feed cancelled")
                break
            except Exception as e:
                if not self._running:
                    break
                logger.error(f"WebSocket error: {e}. Reconnecting in {self._reconnect_delay:.0f}s...")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60.0)

    async def _connect(self) -> None:
        """Connect to Binance WebSocket and process messages."""
        url = self._build_stream_url()
        logger.info(f"Connecting to Binance WebSocket: {len(self.symbols)} symbols")

        async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
            self._ws = ws
            self._reconnect_delay = 1.0  # Reset backoff on successful connect
            logger.info("WebSocket connected")

            async for raw_msg in ws:
                if not self._running:
                    break
                try:
                    self._process_message(raw_msg)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")

    def _process_message(self, raw_msg: str) -> None:
        """Parse a Binance kline WebSocket message."""
        msg = json.loads(raw_msg)

        # Combined stream format: {"stream": "btcusdt@kline_1m", "data": {...}}
        data = msg.get("data", msg)
        if "k" not in data:
            return

        kline = data["k"]

        # Only process closed candles (kline.x == true)
        if not kline.get("x", False):
            return

        # Convert Binance symbol format to our format
        raw_symbol = kline["s"]  # e.g. "BTCUSDT"
        symbol = self._normalize_symbol(raw_symbol)

        candle_1m = {
            "timestamp": datetime.fromtimestamp(kline["t"] / 1000, tz=timezone.utc),
            "open": float(kline["o"]),
            "high": float(kline["h"]),
            "low": float(kline["l"]),
            "close": float(kline["c"]),
            "volume": float(kline["v"]),
        }

        # Fire 1m callback if registered
        if self.on_candle_1m:
            self.on_candle_1m(symbol, candle_1m)

        # Aggregate into 1h
        candle_1h = self._aggregator.add_candle(symbol, candle_1m)
        if candle_1h is not None and self.on_candle_1h:
            logger.debug(f"1h candle complete: {symbol} close={candle_1h['close']}")
            self.on_candle_1h(symbol, candle_1h)

    def _normalize_symbol(self, raw: str) -> str:
        """Convert 'BTCUSDT' → 'BTC/USDT'."""
        for sym in self.symbols:
            if sym.replace("/", "") == raw:
                return sym
        # Fallback: insert / before USDT
        if raw.endswith("USDT"):
            return raw[:-4] + "/USDT"
        return raw

    async def stop(self) -> None:
        """Gracefully stop the feed."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info("Data feed stopped")
