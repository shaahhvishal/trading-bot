"""
Risk manager: enforces hard limits to prevent account blow-up.

Rules:
  1. Max position size: 5% of portfolio per trade
  2. Daily loss limit: -15% → halt trading for the day
  3. Total drawdown kill switch: -30% → stop everything, alert
  4. Max concurrent positions: 2
  5. Every risk check and limit breach is logged

The risk manager sits between the strategy and the executor. Before any
trade executes, it must pass all risk checks. If any check fails, the
trade is blocked and the reason is logged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from loguru import logger


@dataclass
class RiskLimits:
    """Configurable risk limits."""

    max_position_pct: float = 0.05       # 5% of portfolio per position
    daily_loss_limit: float = -0.15      # -15% daily loss → halt
    total_drawdown_limit: float = -0.30  # -30% total drawdown → kill switch
    max_open_positions: int = 2


@dataclass
class RiskEvent:
    """Record of a risk check or breach."""

    timestamp: datetime
    event_type: str   # "check_passed", "position_blocked", "daily_halt", "kill_switch"
    details: str
    data: dict = field(default_factory=dict)


class RiskManager:
    """Enforces risk limits and logs all risk events.

    Usage:
        rm = RiskManager(limits, initial_capital=10000)
        allowed, reason = rm.check_new_position(symbol, size, executor)
        if not allowed:
            # trade blocked
    """

    def __init__(
        self,
        limits: RiskLimits | None = None,
        initial_capital: float = 10_000.0,
        on_breach: Callable[[RiskEvent], None] | None = None,
    ) -> None:
        """Initialize risk manager.

        Args:
            limits: Risk limit configuration.
            initial_capital: Starting capital for drawdown calculation.
            on_breach: Optional callback when a limit is breached (e.g. send alert).
        """
        self.limits = limits or RiskLimits()
        self.initial_capital = initial_capital
        self.peak_capital = initial_capital
        self.on_breach = on_breach
        self.events: list[RiskEvent] = []
        self._daily_halt = False
        self._kill_switch = False
        self._halt_date: str | None = None

    @property
    def is_halted(self) -> bool:
        """True if trading is halted (daily or kill switch)."""
        return self._kill_switch or self._daily_halt

    @property
    def is_killed(self) -> bool:
        """True if the kill switch has been triggered."""
        return self._kill_switch

    def update_capital(self, current_capital: float) -> None:
        """Update peak capital tracking for drawdown calculation.

        Args:
            current_capital: Current total portfolio value.
        """
        if current_capital > self.peak_capital:
            self.peak_capital = current_capital

    def check_new_position(self, symbol: str, proposed_size: float,
                           current_capital: float,
                           open_position_count: int) -> tuple[bool, str]:
        """Check if a new position is allowed.

        Args:
            symbol: Trading pair.
            proposed_size: Size in USD of the new position.
            current_capital: Current available capital.
            open_position_count: Number of currently open positions.

        Returns:
            (allowed, reason) tuple. reason is empty string if allowed.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Reset daily halt if it's a new day
        if self._daily_halt and self._halt_date != today:
            self._daily_halt = False
            self._halt_date = None
            logger.info("Daily halt reset — new trading day")

        # Kill switch — permanent until manual reset
        if self._kill_switch:
            reason = "KILL SWITCH ACTIVE — trading permanently halted"
            self._log_event("position_blocked", reason, {"symbol": symbol})
            return False, reason

        # Daily halt
        if self._daily_halt:
            reason = f"DAILY HALT — trading paused for {today}"
            self._log_event("position_blocked", reason, {"symbol": symbol})
            return False, reason

        # Max concurrent positions
        if open_position_count >= self.limits.max_open_positions:
            reason = (
                f"MAX POSITIONS ({self.limits.max_open_positions}) reached — "
                f"currently {open_position_count} open"
            )
            self._log_event("position_blocked", reason, {"symbol": symbol})
            return False, reason

        # Max position size
        max_size = current_capital * self.limits.max_position_pct
        if proposed_size > max_size:
            reason = (
                f"POSITION TOO LARGE — ${proposed_size:,.2f} exceeds "
                f"{self.limits.max_position_pct*100:.0f}% limit (${max_size:,.2f})"
            )
            self._log_event("position_blocked", reason, {
                "symbol": symbol, "proposed": proposed_size, "max": max_size,
            })
            return False, reason

        self._log_event("check_passed", f"Position allowed: {symbol} ${proposed_size:,.2f}", {
            "symbol": symbol, "size": proposed_size,
        })
        return True, ""

    def check_daily_loss(self, daily_pnl: float) -> bool:
        """Check if daily loss limit is breached.

        Args:
            daily_pnl: Today's P&L in USD.

        Returns:
            True if trading should continue, False if halted.
        """
        if self._kill_switch:
            return False

        daily_pnl_pct = daily_pnl / self.initial_capital
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if daily_pnl_pct <= self.limits.daily_loss_limit:
            self._daily_halt = True
            self._halt_date = today
            event = self._log_event(
                "daily_halt",
                f"DAILY LOSS LIMIT HIT — P&L: ${daily_pnl:+,.2f} "
                f"({daily_pnl_pct*100:+.2f}%) exceeds {self.limits.daily_loss_limit*100:.0f}% limit",
                {"daily_pnl": daily_pnl, "daily_pnl_pct": daily_pnl_pct},
            )
            if self.on_breach:
                self.on_breach(event)
            return False

        return True

    def check_total_drawdown(self, current_capital: float) -> bool:
        """Check if total drawdown kill switch should trigger.

        Args:
            current_capital: Current total portfolio value.

        Returns:
            True if trading should continue, False if killed.
        """
        self.update_capital(current_capital)

        drawdown_pct = (current_capital - self.peak_capital) / self.peak_capital

        if drawdown_pct <= self.limits.total_drawdown_limit:
            self._kill_switch = True
            event = self._log_event(
                "kill_switch",
                f"KILL SWITCH TRIGGERED — Drawdown: {drawdown_pct*100:+.2f}% "
                f"(peak: ${self.peak_capital:,.2f} → current: ${current_capital:,.2f})",
                {
                    "current_capital": current_capital,
                    "peak_capital": self.peak_capital,
                    "drawdown_pct": drawdown_pct,
                },
            )
            if self.on_breach:
                self.on_breach(event)
            return False

        return True

    def calculate_position_size(self, current_capital: float) -> float:
        """Calculate the allowed position size based on risk limits.

        Args:
            current_capital: Current available capital.

        Returns:
            Maximum allowed position size in USD.
        """
        return current_capital * self.limits.max_position_pct

    def _log_event(self, event_type: str, details: str,
                   data: dict | None = None) -> RiskEvent:
        """Log a risk event."""
        event = RiskEvent(
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            details=details,
            data=data or {},
        )
        self.events.append(event)

        if event_type in ("daily_halt", "kill_switch"):
            logger.critical(details)
        elif event_type == "position_blocked":
            logger.warning(details)
        else:
            logger.debug(details)

        return event

    def reset_daily(self) -> None:
        """Manually reset the daily halt (for testing)."""
        self._daily_halt = False
        self._halt_date = None

    def reset_kill_switch(self) -> None:
        """Manually reset the kill switch (requires explicit action)."""
        self._kill_switch = False
        logger.warning("Kill switch manually reset")
