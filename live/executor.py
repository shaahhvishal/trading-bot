"""
Order executor with paper trading mode.

In paper mode: simulates order fills at current market price, tracks positions
and P&L in memory, and logs every trade to a JSON file.

In live mode (Phase 4): places real orders via Hyperliquid API using
hyperliquid-python SDK.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger


class Position:
    """Represents an open position."""

    def __init__(self, symbol: str, side: str, entry_price: float,
                 size: float, entry_time: datetime) -> None:
        self.symbol = symbol
        self.side = side          # "long" or "short"
        self.entry_price = entry_price
        self.size = size          # in quote currency (USD)
        self.entry_time = entry_time

    def unrealized_pnl(self, current_price: float) -> float:
        """Calculate unrealized P&L at a given price."""
        if self.side == "long":
            return self.size * (current_price - self.entry_price) / self.entry_price
        else:
            return self.size * (self.entry_price - current_price) / self.entry_price

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "entry_price": self.entry_price,
            "size": self.size,
            "entry_time": self.entry_time.isoformat(),
        }


class PaperExecutor:
    """Simulated order executor for paper trading.

    Fills orders instantly at the provided market price. Tracks positions,
    capital, and trade history. Logs every trade to a JSON file.
    """

    def __init__(
        self,
        initial_capital: float = 10_000.0,
        taker_fee: float = 0.0005,
        trade_log_path: str = "data/paper_trades.json",
    ) -> None:
        """Initialize paper executor.

        Args:
            initial_capital: Starting capital in USD.
            taker_fee: Fee per trade (0.0005 = 0.05%).
            trade_log_path: Path to write trade log JSON.
        """
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.taker_fee = taker_fee
        self.positions: dict[str, Position] = {}  # symbol → Position
        self.trade_log: list[dict] = []
        self._trade_log_path = Path(trade_log_path)
        self._trade_log_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing trade log if it exists and is non-empty
        if self._trade_log_path.exists() and self._trade_log_path.stat().st_size > 0:
            try:
                with open(self._trade_log_path) as f:
                    self.trade_log = json.load(f)
                logger.info(f"Loaded {len(self.trade_log)} existing paper trades")
            except json.JSONDecodeError:
                logger.warning("Corrupt trade log, starting fresh")
                self.trade_log = []

    @property
    def equity(self) -> float:
        """Total portfolio value (cash + unrealized positions)."""
        # Note: we'd need current prices to value positions accurately.
        # For now return capital (positions are tracked separately).
        return self.capital

    @property
    def open_position_count(self) -> int:
        """Number of currently open positions."""
        return len(self.positions)

    def get_position(self, symbol: str) -> Position | None:
        """Get the current position for a symbol, or None."""
        return self.positions.get(symbol)

    def open_position(self, symbol: str, side: str, price: float,
                      size: float) -> dict:
        """Open a new position (paper fill at given price).

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            side: "long" or "short".
            price: Current market price to fill at.
            size: Position size in USD.

        Returns:
            Trade record dict.
        """
        fee = size * self.taker_fee
        self.capital -= size + fee

        position = Position(
            symbol=symbol,
            side=side,
            entry_price=price,
            size=size,
            entry_time=datetime.now(timezone.utc),
        )
        self.positions[symbol] = position

        trade = {
            "action": "open",
            "symbol": symbol,
            "side": side,
            "price": price,
            "size": round(size, 2),
            "fee": round(fee, 4),
            "capital_after": round(self.capital, 2),
            "timestamp": position.entry_time.isoformat(),
        }
        self._record_trade(trade)

        logger.info(
            f"PAPER OPEN {side.upper()} {symbol} @ ${price:,.2f} "
            f"size=${size:,.2f} fee=${fee:.4f}"
        )
        return trade

    def close_position(self, symbol: str, price: float) -> dict | None:
        """Close an open position at the given price.

        Args:
            symbol: Trading pair.
            price: Current market price.

        Returns:
            Trade record dict, or None if no position exists.
        """
        position = self.positions.pop(symbol, None)
        if position is None:
            logger.warning(f"No open position to close for {symbol}")
            return None

        # Calculate P&L
        if position.side == "long":
            pnl_pct = (price - position.entry_price) / position.entry_price
        else:
            pnl_pct = (position.entry_price - price) / position.entry_price

        pnl = position.size * pnl_pct
        fee = position.size * self.taker_fee
        net_pnl = pnl - fee

        self.capital += position.size + net_pnl

        trade = {
            "action": "close",
            "symbol": symbol,
            "side": position.side,
            "entry_price": position.entry_price,
            "exit_price": price,
            "size": round(position.size, 2),
            "pnl": round(net_pnl, 4),
            "pnl_pct": round(pnl_pct * 100, 4),
            "fee": round(fee * 2, 4),  # entry + exit
            "capital_after": round(self.capital, 2),
            "entry_time": position.entry_time.isoformat(),
            "exit_time": datetime.now(timezone.utc).isoformat(),
            "hold_duration_min": round(
                (datetime.now(timezone.utc) - position.entry_time).total_seconds() / 60, 1
            ),
        }
        self._record_trade(trade)

        logger.info(
            f"PAPER CLOSE {position.side.upper()} {symbol} @ ${price:,.2f} "
            f"P&L=${net_pnl:+,.2f} ({pnl_pct*100:+.2f}%)"
        )
        return trade

    def _record_trade(self, trade: dict) -> None:
        """Append trade to in-memory log and persist to JSON file."""
        self.trade_log.append(trade)
        with open(self._trade_log_path, "w") as f:
            json.dump(self.trade_log, f, indent=2, default=str)

    def daily_pnl(self) -> float:
        """Calculate P&L for today (UTC)."""
        today = datetime.now(timezone.utc).date()
        daily = 0.0
        for trade in self.trade_log:
            if trade.get("action") == "close":
                ts = trade.get("exit_time", "")
                if ts and ts[:10] == str(today):
                    daily += trade.get("pnl", 0.0)
        return daily

    def total_pnl(self) -> float:
        """Total P&L since inception."""
        return self.capital - self.initial_capital + sum(
            pos.unrealized_pnl(pos.entry_price) for pos in self.positions.values()
        )

    def summary(self) -> dict[str, Any]:
        """Current state summary."""
        return {
            "capital": round(self.capital, 2),
            "initial_capital": self.initial_capital,
            "total_pnl": round(self.total_pnl(), 2),
            "daily_pnl": round(self.daily_pnl(), 2),
            "open_positions": {s: p.to_dict() for s, p in self.positions.items()},
            "total_trades": len([t for t in self.trade_log if t["action"] == "close"]),
        }
