# Trading Bot

Algorithmic crypto trading engine with 9 strategies, an event-driven backtesting engine, live paper trading via Binance WebSocket, risk management, Telegram alerts, and a Next.js dashboard.

Built for BTC/USDT and ETH/USDT on 1-minute to daily timeframes. Backtests on Binance historical data, paper trades in real-time, with Hyperliquid live execution planned.

## Project Structure

```
trading-bot/
├── strategies/       # 9 strategy implementations
├── backtest/         # Event-driven backtesting engine & metrics
├── data/             # Binance OHLCV download & Parquet storage
├── live/             # WebSocket feed, paper executor, risk manager
├── alerts/           # Telegram trade notifications
├── scripts/          # CLI entry points (backtest, live, analysis)
├── config/           # YAML configuration
├── tests/            # Unit & integration tests
├── web/              # Next.js + Tailwind dashboard
└── requirements.txt
```

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+ (for the web dashboard)

### Installation

```bash
# Clone the repo
git clone https://github.com/<your-username>/trading-bot.git
cd trading-bot

# Install Python dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your Telegram bot token & chat ID
```

### Download Data

```bash
# Download 1-year of 1-minute BTC/USDT candles from Binance
python scripts/run_backtest.py --strategy momentum --symbol BTC/USDT \
  --start 2024-01-01 --end 2025-01-01 --download
```

Data is stored as Parquet files in `data/parquet/` (~15 MB for 525k rows, loads in <1s).

### Run a Backtest

```bash
python scripts/run_backtest.py --strategy volatility_breakout --symbol BTC/USDT \
  --start 2024-01-01 --end 2025-01-01 --capital 10000 --fee 0.0005
```

Available strategies: `momentum`, `mean_reversion`, `volatility_breakout`, `orb`, `vwap_reversion`, `vwap_pullback`, `ema_swing`, `confluence`, `candle_predictor`.

### Start Paper Trading

```bash
python scripts/run_live.py --strategy volatility_breakout \
  --symbols BTC/USDT,ETH/USDT --capital 10000
```

Connects to Binance WebSocket for real-time 1m candles, aggregates to 1h, and executes trades in paper mode. Trade log saved to `data/paper_trades.json`.

### Web Dashboard

```bash
cd web
npm install
npm run dev  # http://localhost:3000
```

---

## Strategies

All strategies implement the same `Strategy` interface — `on_candle(candle) -> Signal` — and work identically in backtesting and live trading.

### 1. Momentum (EMA + RSI)

Trend-following baseline. Enters long when price is above EMA(30) and RSI > 50; short when below EMA(30) and RSI < 40.

| Parameter | Default |
|-----------|---------|
| `ema_period` | 30 |
| `rsi_period` | 14 |
| `rsi_long_threshold` | 50 |
| `rsi_short_threshold` | 40 |

### 2. Mean Reversion (Bollinger Bands + RSI)

Fades extremes. Enters long when price touches the lower Bollinger Band and RSI < 30; short at the upper band with RSI > 70. Works best in ranging markets.

| Parameter | Default |
|-----------|---------|
| `bb_period` | 20 |
| `bb_std` | 2.0 |
| `rsi_oversold` | 30 |
| `rsi_overbought` | 70 |

### 3. Volatility Breakout (Donchian + Volume) — Primary Strategy

Captures breakouts from consolidation. Enters long on a break above the 50-period high with above-average volume; short on a break below the low. Inspired by Turtle Trading.

Exit is signal-based (opposite breakout reverses the position) — MFE/MAE analysis showed that hard TP/SL targets cause re-entry churn and reduce returns.

| Parameter | Default |
|-----------|---------|
| `donchian_period` | 50 |
| `volume_ma_period` | 20 |
| `atr_period` | 14 |

**Backtest insight (BTC/USDT, 2024):** Winners average +10% MFE with a 58% capture ratio. Signal-only exits outperform fixed TP/SL.

### 4. Opening Range Breakout (ORB)

Intraday strategy operating on 8-hour sessions (UTC 00:00, 08:00, 16:00). Defines the opening range from the first 15 minutes, then enters on a breakout above/below with volume confirmation and VWAP bias.

Exits: initial stop at opposite side of the range, breakeven at +1R, take profit at +2R, trailing stop on 10-SMA, and a time stop if < 0.5R gain within 15 minutes. Skips sessions where the opening range exceeds 1.2x ATR.

| Parameter | Default |
|-----------|---------|
| `or_window_minutes` | 15 |
| `session_hours` | [0, 8, 16] |
| `atr_skip_mult` | 1.2 |
| `volume_mult` | 1.2 |
| `tp_r_multiple` | 2.0 |
| `trail_sma_period` | 10 |

### 5. VWAP Reversion (VWAP + RSI Divergence)

Mean-reversion around VWAP. Enters long when price drops 2 standard deviations below VWAP and RSI shows bullish divergence (price makes lower low, RSI makes higher low). Mirrors logic for shorts.

| Parameter | Default |
|-----------|---------|
| `vwap_std_mult` | 2.0 |
| `rsi_period` | 14 |
| `rsi_divergence_lookback` | 5 |

### 6. VWAP Pullback (Trend Continuation)

Buys pullbacks to VWAP in an uptrend. Waits for price to retrace to within 0.4x ATR of session VWAP, then enters when the candle reclaims VWAP. Stop below VWAP - 0.5x ATR, TP at 2R, trailing under 9 EMA.

| Parameter | Default |
|-----------|---------|
| `pullback_atr_mult` | 0.4 |
| `stop_atr_mult` | 0.5 |
| `tp_r_multiple` | 2.0 |
| `trail_ema_period` | 9 |

### 7. EMA Swing (Multi-Timeframe Trend)

Long-only. Enters when both the 1H and 4H close are above their 200 EMA; exits when either breaks below. Simple but effective for catching sustained trends.

### 8. Confluence (Multi-Indicator Scoring)

Long-only scoring system (max 12 points). Enters at >= 7, exits at <= 3. Scores across:
- EMA trend (50 & 200)
- Fibonacci retracement levels
- Trendline proximity
- RSI divergence
- Support/resistance retests
- Higher-timeframe alignment (4H, Daily)

Reduces false signals by requiring agreement across independent indicators.

### 9. Candle Predictor (Prediction Markets)

Not a trading strategy — predicts whether the next 15m BTC candle will be green or red, for use on betting/prediction platforms.

**Historical performance:** 55.5% accuracy at confidence >= 4.0 over 335 bets (Sep-Dec 2024). Only predicts green (red showed no edge).

---

## Backtesting Engine

Event-driven engine in `backtest/engine.py`. Candles are processed one at a time with no lookahead bias — the same `on_candle()` method used in live trading.

**Metrics reported:**
- Total return, number of trades, win rate
- Profit factor, Sharpe ratio (annualized)
- Max drawdown
- Average win/loss, reward-to-risk ratio
- Full equity curve and trade log

**Fees & slippage** are applied per-trade (default: 0.05% taker fee, 0.01% slippage).

---

## Live Trading Architecture

```
Binance WebSocket (1m candles)
    |
CandleAggregator (1m -> 1h)
    |
Strategy.on_candle() -> BUY / SELL / HOLD
    |
RiskManager.check() -> allowed?
    |
PaperExecutor.execute() -> simulated fill
    |
TelegramAlerter.send() -> notification
```

### Risk Management

| Limit | Default |
|-------|---------|
| Max position size | 5% of portfolio |
| Daily loss limit | -15% (halt trading) |
| Total drawdown kill switch | -30% (stop everything) |
| Max concurrent positions | 3 |

Breaches trigger Telegram alerts.

### Alerts

Telegram notifications for every trade entry/exit, daily P&L summaries, risk limit breaches, and errors.

---

## Configuration

All parameters are in `config/settings.yaml`:

```yaml
symbol: "BTC/USDT"
timeframe: "1m"

backtest:
  initial_capital: 10000.0
  taker_fee: 0.0005
  maker_fee: 0.0002
  slippage: 0.0001
  position_size: 1.0

strategies:
  volatility_breakout:
    donchian_period: 50
    volume_ma_period: 20
    atr_period: 14
  # ... other strategies ...

risk:
  max_position_pct: 0.05
  daily_loss_limit: -0.15
  total_drawdown_limit: -0.30
  max_open_positions: 3

live:
  symbols: ["BTC/USDT", "ETH/USDT"]
  strategy: "volatility_breakout"
  mode: "paper"
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in:

```
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

Optional (for future Hyperliquid live execution):
```
HYPERLIQUID_PRIVATE_KEY=...
HYPERLIQUID_WALLET_ADDRESS=...
```

---

## Analysis Scripts

```bash
# MFE/MAE analysis (validate exit logic)
python scripts/analyze_mfe_mae.py

# Candle predictor accuracy
python scripts/analyze_candle_color.py

# Compare TP/SL vs signal-only exits
python scripts/backtest_vol_tpsl.py

# Parameter optimization (grid search)
python scripts/optimize.py

# Multi-timeframe comparison
python scripts/compare_timeframes.py
```

---

## Tests

```bash
pytest tests/
```

Covers strategy signals, backtest engine, metrics calculations, risk manager, data storage, and full bot integration.

---

## Adding a New Strategy

1. Create `strategies/my_strategy.py` inheriting from `Strategy`
2. Implement `prepare()`, `on_candle()`, and `warmup_period`
3. Register it in `scripts/run_backtest.py`
4. Add tests in `tests/test_strategies.py`
5. Backtest: `python scripts/run_backtest.py --strategy my_strategy`

---

## Roadmap

- [x] Phase 1 — Data pipeline (Binance download, Parquet storage)
- [x] Phase 2 — Backtesting engine & 9 strategies
- [x] Phase 3 — Paper trading, WebSocket feed, risk management, Telegram alerts
- [ ] Phase 4 — Hyperliquid live execution
- [ ] Phase 5 — Dashboard refinement, ML signals, advanced analytics

---

## Disclaimer

This is for educational and paper trading purposes. Algorithmic trading is inherently risky. Use paper trading first, enable all risk limits, and never risk more than you can afford to lose.
