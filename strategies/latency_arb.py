"""
Latency arbitrage strategy: Polymarket vs Hyperliquid.

Logic:
  This strategy exploits price discrepancies between prediction markets
  (Polymarket) and perps exchanges (Hyperliquid). When a significant event
  moves Polymarket prices faster than Hyperliquid adjusts, we trade the lag.

  Example: If a Polymarket contract for "BTC above $X by date Y" spikes from
  0.50 to 0.70 (implying bullish sentiment), but Hyperliquid BTC perp hasn't
  moved yet, we go long on Hyperliquid before the price catches up.

Why this works (market microstructure perspective):
  Prediction markets react to news/events almost instantly because traders
  are directly betting on outcomes. Perps exchanges are slower to adjust
  because liquidity providers use wider spreads during uncertainty. The
  latency window is typically 1-30 seconds — enough for automated execution.

Status:
  This strategy requires a live Polymarket data feed and cannot be backtested
  with standard OHLCV data. It will be fully implemented in Phase 3 when we
  build the live trading infrastructure. For now this is a skeleton that
  conforms to the Strategy interface.
"""

from __future__ import annotations

from typing import Any

from strategies.base import Signal, Strategy


class LatencyArbStrategy(Strategy):
    """Latency arbitrage between Polymarket and Hyperliquid.

    NOTE: This strategy requires live dual-feed data (Polymarket + Hyperliquid)
    and cannot be meaningfully backtested with single-source OHLCV candles.
    The on_candle method returns HOLD for backtesting; the real logic will
    live in on_tick() once live feeds are wired up in Phase 3.
    """

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)
        self.spread_threshold: float = self.params.get("spread_threshold", 0.005)
        self.max_hold_seconds: int = self.params.get("max_hold_seconds", 60)

    @property
    def name(self) -> str:
        return "latency_arb"

    @property
    def warmup_period(self) -> int:
        return 0

    def on_candle(self, candle: dict) -> Signal:
        """Placeholder — latency arb cannot run on historical candles.

        Args:
            candle: OHLCV dict (unused in this strategy).

        Returns:
            Always HOLD in backtest mode.
        """
        self._add_candle(candle)
        return Signal.HOLD
