"""Tests for live/risk_manager.py — prove that limits actually trigger."""

from __future__ import annotations

import pytest

from live.risk_manager import RiskEvent, RiskLimits, RiskManager


@pytest.fixture
def rm() -> RiskManager:
    """Risk manager with default limits and $10k capital."""
    return RiskManager(
        limits=RiskLimits(
            max_position_pct=0.05,
            daily_loss_limit=-0.15,
            total_drawdown_limit=-0.30,
            max_open_positions=2,
        ),
        initial_capital=10_000.0,
    )


class TestPositionSizeLimit:
    """Max 5% of portfolio per position."""

    def test_position_within_limit_allowed(self, rm):
        allowed, reason = rm.check_new_position("BTC/USDT", 400, 10_000, 0)
        assert allowed
        assert reason == ""

    def test_position_at_exact_limit_allowed(self, rm):
        allowed, _ = rm.check_new_position("BTC/USDT", 500, 10_000, 0)
        assert allowed

    def test_position_over_limit_blocked(self, rm):
        allowed, reason = rm.check_new_position("BTC/USDT", 600, 10_000, 0)
        assert not allowed
        assert "POSITION TOO LARGE" in reason

    def test_position_size_calculation(self, rm):
        size = rm.calculate_position_size(10_000)
        assert size == 500.0  # 5% of 10k


class TestMaxConcurrentPositions:
    """Max 2 concurrent open positions."""

    def test_first_position_allowed(self, rm):
        allowed, _ = rm.check_new_position("BTC/USDT", 500, 10_000, 0)
        assert allowed

    def test_second_position_allowed(self, rm):
        allowed, _ = rm.check_new_position("ETH/USDT", 500, 10_000, 1)
        assert allowed

    def test_third_position_blocked(self, rm):
        allowed, reason = rm.check_new_position("SOL/USDT", 500, 10_000, 2)
        assert not allowed
        assert "MAX POSITIONS" in reason


class TestDailyLossLimit:
    """Daily loss of -15% halts trading for the day."""

    def test_small_loss_continues(self, rm):
        result = rm.check_daily_loss(-1000)  # -10%
        assert result is True
        assert not rm.is_halted

    def test_15pct_loss_triggers_halt(self, rm):
        result = rm.check_daily_loss(-1500)  # exactly -15%
        assert result is False
        assert rm.is_halted
        assert rm._daily_halt

    def test_halt_blocks_new_positions(self, rm):
        rm.check_daily_loss(-1500)
        allowed, reason = rm.check_new_position("BTC/USDT", 500, 10_000, 0)
        assert not allowed
        assert "DAILY HALT" in reason

    def test_halt_is_not_kill_switch(self, rm):
        rm.check_daily_loss(-1500)
        assert rm.is_halted
        assert not rm.is_killed  # kill switch is separate


class TestKillSwitch:
    """Total drawdown of -30% triggers permanent kill switch."""

    def test_small_drawdown_continues(self, rm):
        rm.update_capital(10_000)
        result = rm.check_total_drawdown(8_000)  # -20%
        assert result is True
        assert not rm.is_killed

    def test_30pct_drawdown_triggers_kill(self, rm):
        rm.update_capital(10_000)
        result = rm.check_total_drawdown(7_000)  # -30%
        assert result is False
        assert rm.is_killed
        assert rm.is_halted

    def test_kill_switch_blocks_everything(self, rm):
        rm.update_capital(10_000)
        rm.check_total_drawdown(7_000)
        allowed, reason = rm.check_new_position("BTC/USDT", 100, 7_000, 0)
        assert not allowed
        assert "KILL SWITCH" in reason

    def test_kill_switch_survives_daily_reset(self, rm):
        rm.update_capital(10_000)
        rm.check_total_drawdown(7_000)
        rm.reset_daily()  # Should NOT reset kill switch
        assert rm.is_killed

    def test_kill_switch_uses_peak_capital(self, rm):
        """Drawdown is measured from peak, not initial capital."""
        rm.update_capital(15_000)  # Capital grew to 15k
        # Now drops to 10.5k → -30% from peak of 15k
        result = rm.check_total_drawdown(10_500)
        assert result is False
        assert rm.is_killed


class TestBreachCallback:
    """Risk breach callback fires on limit triggers."""

    def test_daily_halt_fires_callback(self, rm):
        events: list[RiskEvent] = []
        rm.on_breach = lambda e: events.append(e)

        rm.check_daily_loss(-2000)
        assert len(events) == 1
        assert events[0].event_type == "daily_halt"

    def test_kill_switch_fires_callback(self, rm):
        events: list[RiskEvent] = []
        rm.on_breach = lambda e: events.append(e)

        rm.check_total_drawdown(6_000)
        assert len(events) == 1
        assert events[0].event_type == "kill_switch"


class TestEventLogging:
    """All risk checks are logged."""

    def test_passed_checks_are_logged(self, rm):
        rm.check_new_position("BTC/USDT", 500, 10_000, 0)
        assert len(rm.events) == 1
        assert rm.events[0].event_type == "check_passed"

    def test_blocked_checks_are_logged(self, rm):
        rm.check_new_position("BTC/USDT", 600, 10_000, 0)
        assert len(rm.events) == 1
        assert rm.events[0].event_type == "position_blocked"
