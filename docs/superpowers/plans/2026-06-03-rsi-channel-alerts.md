# RSI Channel Alerts & Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Pine Script v6 indicator + matching strategy that plot a hand-anchored descending parallel channel on the RSI pane, emit four breach alerts (breakoutBuy, upperRejection, supportTouch, supportBreakdown), and backtest entries on either bullish signal with exits on either bearish signal.

**Architecture:** Two paired Pine v6 files in `pinescripts/` (matching the existing `orb_donchian_combo.pine` + `..._strategy.pine` pattern). Both share identical channel-construction logic — upper line defined by two user-clicked anchors, lower line is a parallel offset. Indicator emits `alertcondition()` + `plotshape()`; strategy uses the same conditions to drive `strategy.entry`/`strategy.close`.

**Tech Stack:** Pine Script v6, TradingView Pine Editor, TradingView Strategy Tester.

**Verification model:** Pine Script has no automated test framework. Each task is verified by loading the script in TradingView's Pine Editor, confirming it compiles, and visually inspecting outputs against criteria. Where applicable, TradingView's bar Replay tool steps through history to verify signals fire on the expected bars.

**Reference chart for verification:** MSTR daily (NASDAQ), date range Jul 2021 – present. This is the chart the user has the hand-drawn channel on.

---

## File Structure

| File | Responsibility |
|---|---|
| `pinescripts/rsi_channel_alerts.pine` | Indicator pane: RSI + projected channel + 4 plotshapes + 4 alertconditions |
| `pinescripts/rsi_channel_strategy.pine` | Strategy pane: same channel logic + strategy.entry/strategy.close on the 4 signals |

Both files are self-contained — no shared imports (Pine Script doesn't support cross-file imports in the standard editor workflow).

---

## Task 1: Indicator skeleton — RSI + reference lines

**Files:**
- Create: `pinescripts/rsi_channel_alerts.pine`

- [ ] **Step 1: Create the file with the indicator declaration and RSI plot**

```pine
// This Pine Script™ source code is subject to the terms of the Mozilla Public License 2.0
// https://mozilla.org/MPL/2.0/

//@version=6
indicator("RSI Channel Alerts", overlay=false, precision=2)

// === INPUTS: RSI ===
grpRSI     = "RSI"
rsiLength  = input.int(14, "RSI Length", minval=2, maxval=100, group=grpRSI)
rsiSource  = input.source(close, "RSI Source", group=grpRSI)

// === RSI ===
rsi = ta.rsi(rsiSource, rsiLength)

// === PLOTS: RSI + reference lines ===
plot(rsi, "RSI", color=color.new(color.yellow, 0), linewidth=2)
hline(70, "Overbought", color=color.new(color.gray, 50), linestyle=hline.style_dashed)
hline(50, "Mid",        color=color.new(color.gray, 70), linestyle=hline.style_dotted)
hline(30, "Oversold",   color=color.new(color.gray, 50), linestyle=hline.style_dashed)
```

- [ ] **Step 2: Verify the file compiles in TradingView**

1. Open TradingView, load MSTR daily chart.
2. Open Pine Editor (bottom panel).
3. Paste the file contents, click "Save" then "Add to chart".
4. Expected: a new pane appears below the price chart showing a yellow RSI line oscillating roughly between 20 and 85, with dashed gray lines at 70/30 and a dotted line at 50. No compile errors in the Pine Editor console.

If it fails to compile, fix the error before proceeding.

- [ ] **Step 3: Commit**

```bash
git add pinescripts/rsi_channel_alerts.pine
git commit -m "feat(pine): RSI channel alerts skeleton with reference lines"
```

---

## Task 2: Upper line with two-point interactive anchors

**Files:**
- Modify: `pinescripts/rsi_channel_alerts.pine`

- [ ] **Step 1: Add anchor inputs and upper line computation**

Insert after the `rsiSource` input, inside a new group, and add the upper line plot after the existing RSI plot:

```pine
// === INPUTS: Channel anchors (upper line) ===
grpAnchor   = "Channel Anchors"
point1Time  = input.time(timestamp("2022-01-01T00:00"), "Point 1 Time",  group=grpAnchor, confirm=true)
point1RSI   = input.price(70.0,                         "Point 1 RSI",   group=grpAnchor, confirm=true)
point2Time  = input.time(timestamp("2024-01-01T00:00"), "Point 2 Time",  group=grpAnchor, confirm=true)
point2RSI   = input.price(60.0,                         "Point 2 RSI",   group=grpAnchor, confirm=true)
```

And add the line computation after `rsi = ta.rsi(...)`:

```pine
// === UPPER CHANNEL LINE (projected from two anchor points) ===
// slope in RSI units per millisecond of time
slope     = (point2RSI - point1RSI) / (point2Time - point1Time)
upperLine = point1RSI + slope * (time - point1Time)
```

And add this plot after the RSI plot:

```pine
plot(upperLine, "Upper Channel", color=color.new(color.white, 20), linewidth=1)
```

- [ ] **Step 2: Verify interactive anchor picking works**

1. In Pine Editor: Save → "Add to chart" (or remove old instance first and re-add).
2. Expected: TradingView prompts you to click TWO points on the chart, in order. The first click sets Point 1 (time + RSI), the second sets Point 2.
3. Click two points on the RSI pane that visually lie on your hand-drawn upper channel line (e.g., one peak in early 2022 around RSI 75, another peak in mid-2024 around RSI 65).
4. Expected: A white line appears that passes through both clicked points and extrapolates across the full visible range.
5. Verify the line visually aligns with your hand-drawn upper channel line. If not, open the indicator's settings (gear icon) → Inputs tab → adjust Point 1/Point 2 values, OR remove and re-add to re-pick interactively.

If `input.price(..., confirm=true)` does NOT produce the click-to-pick prompt for RSI values (this can vary — `input.price` is documented to capture y-axis values in the active pane), replace it with `input.float(70.0, "Point 1 RSI", group=grpAnchor)` and have the user type RSI values manually. Document the fallback in a comment.

- [ ] **Step 3: Commit**

```bash
git add pinescripts/rsi_channel_alerts.pine
git commit -m "feat(pine): upper channel line from two interactive anchor points"
```

---

## Task 3: Lower line as parallel offset

**Files:**
- Modify: `pinescripts/rsi_channel_alerts.pine`

- [ ] **Step 1: Add channelWidth input and lower line computation**

Add to the `grpAnchor` group (after `point2RSI`):

```pine
channelWidth = input.float(30.0, "Channel Width (RSI points)", minval=1.0, step=0.5, group=grpAnchor, tooltip="Vertical distance from upper to lower line.")
```

Add after the `upperLine` computation:

```pine
lowerLine = upperLine - channelWidth
```

Replace the existing single upper-line plot with a paired plot + channel fill:

```pine
pUpper = plot(upperLine, "Upper Channel", color=color.new(color.white, 20), linewidth=1)
pLower = plot(lowerLine, "Lower Channel", color=color.new(color.white, 20), linewidth=1)
fill(pUpper, pLower, color=color.new(color.white, 92), title="Channel Fill")
```

- [ ] **Step 2: Verify the lower line is parallel and the fill renders**

1. Save → re-add to chart (re-pick anchors if needed).
2. Expected: a second white line appears 30 RSI points below the upper line, with a faint white fill between them.
3. Adjust `channelWidth` in settings until the lower line visually matches your hand-drawn lower channel line.
4. Both lines should be perfectly parallel (same slope) since `lowerLine = upperLine - channelWidth`.

- [ ] **Step 3: Commit**

```bash
git add pinescripts/rsi_channel_alerts.pine
git commit -m "feat(pine): parallel lower channel line with configurable width"
```

---

## Task 4: Compute signals and plot shape markers

**Files:**
- Modify: `pinescripts/rsi_channel_alerts.pine`

- [ ] **Step 1: Add touch tolerance input and signal computations**

Add to `grpAnchor`:

```pine
touchTolerance = input.float(1.5, "Support Touch Tolerance (RSI points)", minval=0.1, step=0.1, group=grpAnchor, tooltip="How close RSI must get to lower line to count as a touch.")
```

Add after the `lowerLine` computation:

```pine
// === SIGNALS ===
breakoutBuy      = ta.crossover(rsi, upperLine)
upperRejection   = ta.crossunder(rsi, upperLine)
supportTouch     = rsi <= lowerLine + touchTolerance and rsi[1] > lowerLine[1] + touchTolerance
supportBreakdown = ta.crossunder(rsi, lowerLine)
```

Add after the channel fill plot:

```pine
// === SIGNAL MARKERS ===
plotshape(breakoutBuy,      title="Breakout BUY",      style=shape.triangleup,   location=location.absolute, color=color.new(color.green, 0),  size=size.small, text="BUY")
plotshape(upperRejection,   title="Upper Rejection",   style=shape.triangledown, location=location.absolute, color=color.new(color.red, 0),    size=size.small, text="REJ")
plotshape(supportTouch,     title="Support Touch",     style=shape.triangleup,   location=location.absolute, color=color.new(color.lime, 0),   size=size.small, text="DIP")
plotshape(supportBreakdown, title="Support Breakdown", style=shape.triangledown, location=location.absolute, color=color.new(color.orange, 0), size=size.small, text="BRK")
```

Note: `location.absolute` places the marker at the RSI value (the script's plotted series). `location.belowbar`/`abovebar` don't apply in indicator panes — they reference price bars.

**Spec deviation:** the design spec mentions `bgcolor()` tints on the price pane. This is not implementable from a non-overlay indicator — `bgcolor()` only tints the pane the indicator runs in. The `plotshape()` markers above already make signals visually obvious, so the price-pane tint is dropped. If desired later, a separate overlay-style "marker-only" indicator could be created that mirrors the signals onto the price pane.

- [ ] **Step 2: Verify markers appear on historical signal bars**

1. Save → re-add (re-pick anchors).
2. Expected: green/lime up-triangles appear where RSI crossed above the upper line or touched the lower line; red/orange down-triangles appear at the inverse events.
3. Spot-check the user's annotated event: the green arrow on the chart ("+3,600% / 473 days") should sit on or very near a `breakoutBuy` marker. If not, the anchors may need fine-tuning.
4. Use TradingView's bar Replay tool (top toolbar, "Replay" button → click a starting bar) to step forward and watch a marker appear in real-time when the condition fires.

- [ ] **Step 3: Commit**

```bash
git add pinescripts/rsi_channel_alerts.pine
git commit -m "feat(pine): four channel-breach signals with shape markers"
```

---

## Task 5: Wire up alertcondition() for each signal

**Files:**
- Modify: `pinescripts/rsi_channel_alerts.pine`

- [ ] **Step 1: Append alertcondition calls**

Add at the bottom of the file:

```pine
// === ALERTS ===
alertcondition(breakoutBuy,      title="RSI Channel: Breakout BUY",         message="RSI Channel BUY — RSI crossed above descending upper resistance. Consider opening longs / LEAPS.")
alertcondition(upperRejection,   title="RSI Channel: Upper Rejection",      message="RSI Channel REJECTION — RSI crossed back below upper resistance. Consider closing longs.")
alertcondition(supportTouch,     title="RSI Channel: Support Touch (DIP)",  message="RSI Channel DIP — RSI touched lower support line. Consider dip buy.")
alertcondition(supportBreakdown, title="RSI Channel: Support Breakdown",    message="RSI Channel BREAKDOWN — RSI broke below lower support line. Channel structure broken.")
```

- [ ] **Step 2: Verify all four alerts appear in the Alert dialog**

1. Save → re-add.
2. Right-click the chart → "Add alert" (or click the clock icon in the toolbar).
3. In the "Condition" dropdown, select "RSI Channel Alerts".
4. In the second dropdown, expected: all four titles appear — "RSI Channel: Breakout BUY", "RSI Channel: Upper Rejection", "RSI Channel: Support Touch (DIP)", "RSI Channel: Support Breakdown".
5. Cancel the alert dialog without creating one (this task only verifies they appear; creating live alerts is a user step).

- [ ] **Step 3: Commit**

```bash
git add pinescripts/rsi_channel_alerts.pine
git commit -m "feat(pine): alertcondition entries for all four channel signals"
```

---

## Task 6: Strategy file — channel logic and skeleton

**Files:**
- Create: `pinescripts/rsi_channel_strategy.pine`

- [ ] **Step 1: Create the strategy file by copying the channel logic from the indicator**

```pine
// This Pine Script™ source code is subject to the terms of the Mozilla Public License 2.0
// https://mozilla.org/MPL/2.0/

//@version=6
strategy("RSI Channel Strategy", overlay=false, precision=2, default_qty_type=strategy.percent_of_equity, default_qty_value=100, initial_capital=10000, commission_type=strategy.commission.percent, commission_value=0.0)

// === INPUTS: RSI ===
grpRSI     = "RSI"
rsiLength  = input.int(14, "RSI Length", minval=2, maxval=100, group=grpRSI)
rsiSource  = input.source(close, "RSI Source", group=grpRSI)

// === INPUTS: Channel anchors ===
grpAnchor      = "Channel Anchors"
point1Time     = input.time(timestamp("2022-01-01T00:00"), "Point 1 Time",  group=grpAnchor, confirm=true)
point1RSI      = input.price(70.0,                         "Point 1 RSI",   group=grpAnchor, confirm=true)
point2Time     = input.time(timestamp("2024-01-01T00:00"), "Point 2 Time",  group=grpAnchor, confirm=true)
point2RSI      = input.price(60.0,                         "Point 2 RSI",   group=grpAnchor, confirm=true)
channelWidth   = input.float(30.0, "Channel Width (RSI points)", minval=1.0, step=0.5, group=grpAnchor)
touchTolerance = input.float(1.5,  "Support Touch Tolerance (RSI points)", minval=0.1, step=0.1, group=grpAnchor)

// === INPUTS: Backtest range ===
grpRange  = "Backtest Range"
startDate = input.time(timestamp("2021-01-01T00:00"), "Start Date", group=grpRange)
endDate   = input.time(timestamp("2030-01-01T00:00"), "End Date",   group=grpRange)
inRange   = time >= startDate and time <= endDate

// === RSI + CHANNEL ===
rsi       = ta.rsi(rsiSource, rsiLength)
slope     = (point2RSI - point1RSI) / (point2Time - point1Time)
upperLine = point1RSI + slope * (time - point1Time)
lowerLine = upperLine - channelWidth

// === SIGNALS ===
breakoutBuy      = ta.crossover(rsi, upperLine)
upperRejection   = ta.crossunder(rsi, upperLine)
supportTouch     = rsi <= lowerLine + touchTolerance and rsi[1] > lowerLine[1] + touchTolerance
supportBreakdown = ta.crossunder(rsi, lowerLine)

// === PLOTS (for visual verification during backtest) ===
plot(rsi, "RSI", color=color.new(color.yellow, 0), linewidth=2)
pUpper = plot(upperLine, "Upper Channel", color=color.new(color.white, 20), linewidth=1)
pLower = plot(lowerLine, "Lower Channel", color=color.new(color.white, 20), linewidth=1)
fill(pUpper, pLower, color=color.new(color.white, 92), title="Channel Fill")
hline(70, "Overbought", color=color.new(color.gray, 50), linestyle=hline.style_dashed)
hline(50, "Mid",        color=color.new(color.gray, 70), linestyle=hline.style_dotted)
hline(30, "Oversold",   color=color.new(color.gray, 50), linestyle=hline.style_dashed)
```

- [ ] **Step 2: Verify the strategy file compiles and renders the channel**

1. Open Pine Editor → paste file contents → Save → "Add to chart".
2. Pick the same two anchor points used in the indicator.
3. Expected: a new pane appears showing the RSI + projected channel, identical visual to the indicator. Strategy Tester tab opens at the bottom showing "Net Profit: 0.00 USD, Total Closed Trades: 0" (no entries yet — that's Task 7).
4. No compile errors.

- [ ] **Step 3: Commit**

```bash
git add pinescripts/rsi_channel_strategy.pine
git commit -m "feat(pine): RSI channel strategy skeleton with backtest range inputs"
```

---

## Task 7: Strategy entries and exits

**Files:**
- Modify: `pinescripts/rsi_channel_strategy.pine`

- [ ] **Step 1: Add entry/exit toggle inputs**

Add a new group above the `// === RSI + CHANNEL ===` section:

```pine
// === INPUTS: Strategy rules ===
grpRules        = "Strategy Rules"
enableBreakout  = input.bool(true, "Long Entry on Breakout (cross above upper)",      group=grpRules)
enableDipBuy    = input.bool(true, "Long Entry on Support Touch (dip buy)",           group=grpRules)
enableRejExit   = input.bool(true, "Exit Long on Upper Rejection (cross below upper)", group=grpRules)
enableBreakExit = input.bool(true, "Exit Long on Support Breakdown",                   group=grpRules)
```

- [ ] **Step 2: Add strategy.entry / strategy.close logic**

Append at the bottom of the file (after the existing plots/hlines):

```pine
// === STRATEGY ENTRIES (long-only) ===
flat = strategy.position_size == 0

if inRange and flat and enableBreakout and breakoutBuy
    strategy.entry("Breakout", strategy.long, comment="Breakout")

if inRange and flat and enableDipBuy and supportTouch
    strategy.entry("DipBuy", strategy.long, comment="DipBuy")

// === STRATEGY EXITS ===
if strategy.position_size > 0 and enableRejExit and upperRejection
    strategy.close_all(comment="Rejection")

if strategy.position_size > 0 and enableBreakExit and supportBreakdown
    strategy.close_all(comment="Breakdown")

// === SIGNAL MARKERS (visual reference on strategy chart) ===
plotshape(breakoutBuy,      title="Breakout BUY",      style=shape.triangleup,   location=location.absolute, color=color.new(color.green, 0),  size=size.small, text="BUY")
plotshape(upperRejection,   title="Upper Rejection",   style=shape.triangledown, location=location.absolute, color=color.new(color.red, 0),    size=size.small, text="REJ")
plotshape(supportTouch,     title="Support Touch",     style=shape.triangleup,   location=location.absolute, color=color.new(color.lime, 0),   size=size.small, text="DIP")
plotshape(supportBreakdown, title="Support Breakdown", style=shape.triangledown, location=location.absolute, color=color.new(color.orange, 0), size=size.small, text="BRK")
```

Note: the `flat` guard prevents stacking multiple long entries when both breakout and dip-buy fire close together. First signal wins until exit.

- [ ] **Step 3: Verify the Strategy Tester populates with trades**

1. Save → re-add to chart with same anchor points as the indicator.
2. Open the Strategy Tester panel (bottom of TradingView).
3. **Overview tab** expected: Net Profit, Total Closed Trades > 0, Percent Profitable, Profit Factor, Max Drawdown all populated. Equity curve chart renders.
4. **List of Trades tab** expected: rows of entries with comment "Breakout" or "DipBuy" and exits with comment "Rejection" or "Breakdown".
5. **Performance Summary tab** expected: detailed long-side statistics.
6. Spot-check: on the chart, every entry arrow should align with a green/lime up-triangle marker; every exit should align with a red/orange down-triangle.

If "Total Closed Trades" is 0: the anchors are likely off the visible RSI range, so no crossovers ever fire. Re-pick anchors closer to actual RSI peaks/troughs.

- [ ] **Step 4: Toggle test — verify each rule input actually disables its signal**

1. In strategy settings, uncheck "Long Entry on Breakout".
2. Expected: trade count drops; only "DipBuy"-commented entries remain in the trade list.
3. Re-check Breakout, uncheck "Long Entry on Support Touch".
4. Expected: only "Breakout"-commented entries remain.
5. Re-check both entries; uncheck both exits.
6. Expected: positions never close until the next entry opportunity (they'll be stuck open at end of backtest, visible in trade list as "Open" status).
7. Restore all four toggles to checked.

- [ ] **Step 5: Commit**

```bash
git add pinescripts/rsi_channel_strategy.pine
git commit -m "feat(pine): RSI channel strategy entries and exits with toggles"
```

---

## Final verification checklist

After all tasks complete, run this end-to-end on a fresh MSTR daily chart:

- [ ] Both `.pine` files compile without errors in Pine Editor
- [ ] Indicator: clicking two anchor points produces a channel that visually matches the user's hand-drawn channel
- [ ] Indicator: all four `plotshape()` markers appear at correct historical points
- [ ] Indicator: all four `alertcondition()` entries appear in TradingView's "Add alert" dialog
- [ ] Strategy: Strategy Tester reports populate with non-zero trades and an equity curve
- [ ] Strategy: each rule toggle correctly disables/enables its corresponding entry or exit
- [ ] No spec requirement is unimplemented (cross-reference against `docs/superpowers/specs/2026-06-03-rsi-channel-alerts-design.md`)
