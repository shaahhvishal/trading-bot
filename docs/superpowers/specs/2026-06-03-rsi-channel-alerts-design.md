# RSI Channel Breach Alerts & Backtest

## Purpose

Generate trading signals when RSI breaches a hand-defined descending parallel channel — like the macro RSI channel currently drawn on the MSTR daily chart. The system must:

1. Plot the channel directly on the RSI pane so the user can visually confirm the script's lines match the manually drawn ones.
2. Emit alerts (TradingView `alertcondition`) on breach events for live trading.
3. Provide a backtestable `strategy()` version so the user can measure historical performance in TradingView's Strategy Tester.

## Context

- Project: `trading-bot`, Pine Script indicators live in `pinescripts/`.
- Existing pattern: `volatility_breakout.pine` (indicator) + `orb_donchian_combo.pine` / `orb_donchian_combo_strategy.pine` (indicator + strategy pair). The new work follows the same pair pattern.
- Pine Script version: v6.
- User's chart shows a descending parallel channel drawn on RSI(14) of MSTR daily, with two annotated events: "Close on support" (touch of lower line) and "Buy majority of Leaps on this buy signal" (cross above upper line).

## Deliverables

Two new files in `pinescripts/`:

| File | Type | Purpose |
|---|---|---|
| `rsi_channel_alerts.pine` | `indicator()` | Live alerts, visual tuning of channel anchors |
| `rsi_channel_strategy.pine` | `strategy()` | TradingView Strategy Tester backtest |

Both share the same channel-construction logic; the strategy file is the indicator file with `strategy.entry` / `strategy.close` calls in place of `alertcondition`.

## Channel construction

The upper line is defined by **two user-picked anchor points** on the RSI series. The lower line is a configurable parallel offset below the upper line.

### Inputs

| Input | Type | Default | Purpose |
|---|---|---|---|
| `rsiLength` | int | 14 | RSI period |
| `point1Time` | time | (user picks) | First anchor: bar timestamp |
| `point1RSI` | float | (user picks) | First anchor: RSI value at that bar |
| `point2Time` | time | (user picks) | Second anchor: bar timestamp |
| `point2RSI` | float | (user picks) | Second anchor: RSI value at that bar |
| `channelWidth` | float | 30.0 | Vertical distance (in RSI points) from upper to lower line |
| `touchTolerance` | float | 1.5 | How close RSI must get to lower line to count as a "touch" |

All four anchor inputs use Pine v6's `input.time(..., confirm=true)` and `input.price(..., confirm=true)`. When the user first adds the indicator, TradingView prompts them to click two points on the chart — no manual typing of dates or RSI values. After that, draggable anchor markers appear on the chart for fine-tuning.

### Computed each bar

```
slope     = (point2RSI - point1RSI) / (point2Time - point1Time)   // RSI units per ms
upperLine = point1RSI + slope * (time - point1Time)               // projects across all bars
lowerLine = upperLine - channelWidth
rsi       = ta.rsi(close, rsiLength)
```

## Visual verification

The indicator pane plots:

- `rsi` (yellow, linewidth 2) — the actual RSI series
- `upperLine` (white, linewidth 1) — projected upper channel line
- `lowerLine` (white, linewidth 1) — projected lower channel line
- Channel fill (subtle white, 90% transparency) between upper and lower
- Static reference lines at RSI 70, 50, 30 (dashed, gray)

Verification workflow:

1. User adds indicator → clicks two points on the chart at known intersections of their drawn line and RSI.
2. The plotted `upperLine` appears immediately. User compares against their hand-drawn line.
3. If off, drag the anchor markers (TradingView native) until aligned.
4. Adjust `channelWidth` until the plotted `lowerLine` matches the hand-drawn lower line.

## Alert / signal definitions

| Signal | Pine condition | Meaning |
|---|---|---|
| `breakoutBuy` | `ta.crossover(rsi, upperLine)` | Bullish: RSI broke above descending resistance |
| `upperRejection` | `ta.crossunder(rsi, upperLine)` | Bearish exit: RSI failed at resistance |
| `supportTouch` | `rsi <= lowerLine + touchTolerance and rsi[1] > lowerLine[1] + touchTolerance` | Bullish dip-buy: RSI entered support zone from above |
| `supportBreakdown` | `ta.crossunder(rsi, lowerLine)` | Bearish: channel broke down |

`supportTouch` fires once when RSI enters the tolerance zone (not every bar it stays there) — this avoids alert spam during extended support tests.

### Indicator file — outputs per signal

For each of the four signals:

- `plotshape()` on the RSI pane: up-triangle (green) for bullish, down-triangle (red) for bearish, placed at the RSI value
- `bgcolor()` tint on the price pane (subtle, low alpha): green for bullish, red for bearish
- `alertcondition()` with a descriptive message (matches the format in `volatility_breakout.pine`)

## Strategy file — entries and exits

Defaults (all toggleable via `input.bool`):

- **Long entry on `breakoutBuy`:** enabled
- **Long entry on `supportTouch`:** enabled
- **Long exit on `upperRejection`:** enabled (close any open long)
- **Long exit on `supportBreakdown`:** enabled (stop-out)

Rules:

- Only one long position open at a time (`strategy.position_size > 0` check before entering).
- No short entries (matches the user's options-buying use case — they buy LEAPS on bullish signals).
- Position size: `input.float(100, "Position size %")` (% of equity per trade — TradingView default).
- Date filter inputs: `startDate`, `endDate` for limiting backtest range.
- Commission input: `input.float(0.0, "Commission %")`.

The Strategy Tester then provides net profit, # trades, win rate, profit factor, max drawdown, equity curve — standard TradingView strategy output.

## Out of scope

- Auto-detecting the channel from pivots or linear regression (the user explicitly chose manual anchors).
- Short entries (covered by user's "buy LEAPS" use case).
- Integration with the project's Python backtester (`scripts/backtest_orb_vs_vol.py`) — that would require porting `ta.rsi` and time-based line projection to Python. If desired later, the Strategy Tester can export trades as CSV for comparison.
- Multi-timeframe RSI (channel uses the chart's native timeframe only).
- Auto-re-anchoring when the channel breaks — user manually re-picks points after a structural break.

## Success criteria

1. Adding `rsi_channel_alerts.pine` to an MSTR daily chart and clicking two points on the visible RSI channel produces plotted upper/lower lines that visibly match the user's hand-drawn channel.
2. The four `alertcondition` entries appear in TradingView's "Create Alert" dialog and fire correctly when their conditions are met (verifiable by stepping through historical bars with the Replay tool).
3. `rsi_channel_strategy.pine` runs in Strategy Tester without errors on MSTR daily over the 2021-2026 range visible in the chart, producing a non-zero number of trades and a populated equity curve.
