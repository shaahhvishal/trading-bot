const strategies = [
  {
    name: "Confluence",
    badge: "PRIMARY",
    badgeColor: "bg-emerald-500/20 text-emerald-400",
    timeframe: "1H / Multi-TF",
    description:
      "Multi-indicator scoring system that only enters when 6 independent technical signals align. Combines EMA trend, Fibonacci, trendlines, RSI divergence, support/resistance, and higher-timeframe confirmation.",
    stats: [
      { label: "Full Year", value: "+173%" },
      { label: "OOS Return", value: "+42.1%" },
      { label: "Sharpe", value: "25.90" },
      { label: "Max DD", value: "-9.8%" },
      { label: "Profit Factor", value: "3.16" },
      { label: "Win/Loss", value: "5.55x" },
    ],
    details: [
      "6 indicators scored 0-2 (max 12 points)",
      "Entry when score >= 7 (strong consensus)",
      "Exit when score drops to <= 3",
      "1H + 4H + Daily timeframe alignment",
      "Validated on BTC + Mag 7 stocks",
    ],
  },
  {
    name: "Volatility Breakout",
    badge: "CORE",
    badgeColor: "bg-blue-500/20 text-blue-400",
    timeframe: "1H",
    description:
      "Donchian Channel breakout with volume confirmation. Captures momentum cascades when BTC escapes consolidation ranges.",
    stats: [
      { label: "Full Year", value: "+107%" },
      { label: "OOS Return", value: "+61.6%" },
      { label: "Sharpe", value: "26.07" },
      { label: "Max DD", value: "-12.0%" },
      { label: "Profit Factor", value: "3.15" },
      { label: "Trades (4mo)", value: "22" },
    ],
    details: [
      "50-period Donchian channel (2-day lookback)",
      "Volume > 20-period MA for confirmation",
      "Signal-based exits (opposite breakout)",
      "MFE/MAE validated: exits confirmed optimal",
    ],
  },
  {
    name: "EMA Swing",
    badge: "SWING",
    badgeColor: "bg-purple-500/20 text-purple-400",
    timeframe: "1H + 4H",
    description:
      "Multi-timeframe 200 EMA trend filter. Goes long when both 1H and 4H candles close above their 200 EMA — captures major trend legs with minimal drawdown.",
    stats: [
      { label: "Full Year", value: "+107%" },
      { label: "OOS Return", value: "+32.1%" },
      { label: "Sharpe", value: "20.08" },
      { label: "Max DD", value: "-8.9%" },
      { label: "Profit Factor", value: "2.86" },
      { label: "Win/Loss", value: "11.1x" },
    ],
    details: [
      "200 EMA on both 1H and 4H timeframes",
      "Long-only — no short positions",
      "4H resampled and forward-filled to 1H",
      "Best win/loss ratio of all strategies",
    ],
  },
  {
    name: "Candle Predictor",
    badge: "PREDICTION MARKET",
    badgeColor: "bg-yellow-500/20 text-yellow-400",
    timeframe: "15M",
    description:
      "Predicts next-candle color using mean reversion signals. Designed for binary prediction markets with 1.90x+ payouts.",
    stats: [
      { label: "Accuracy", value: "55.6%" },
      { label: "ROI @1.95x", value: "+8.3%" },
      { label: "Signals/Day", value: "~3" },
      { label: "Sample Size", value: "335" },
      { label: "Direction", value: "GREEN only" },
      { label: "Best Edge", value: "+4.2%" },
    ],
    details: [
      "RSI oversold (<30) mean reversion",
      "5-candle negative momentum bounce",
      "Bollinger Band < -2\u03c3 reversal",
      "High volume (1.5-2.5x) confirmation",
    ],
  },
];

export default function Strategies() {
  return (
    <section id="strategies" className="py-24 bg-[var(--color-bg-card)]/30">
      <div className="mx-auto max-w-7xl px-6">
        <div className="text-center">
          <h2 className="text-3xl font-bold sm:text-4xl">
            Strategies built on <span className="text-gradient">real edge</span>
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-[var(--color-text-muted)]">
            Every strategy is backtested on full-year data, walk-forward
            optimized, and validated out-of-sample. No overfitting, no
            hypothetical returns.
          </p>
        </div>

        <div className="mt-16 space-y-8">
          {strategies.map((s) => (
            <div
              key={s.name}
              className="card-glow overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)]"
            >
              <div className="p-6 lg:p-8">
                <div className="flex flex-wrap items-center gap-3">
                  <h3 className="text-xl font-bold">{s.name}</h3>
                  <span
                    className={`rounded-full px-3 py-0.5 text-xs font-semibold ${s.badgeColor}`}
                  >
                    {s.badge}
                  </span>
                  <span className="rounded-full border border-[var(--color-border)] px-3 py-0.5 text-xs text-[var(--color-text-muted)]">
                    {s.timeframe}
                  </span>
                </div>
                <p className="mt-3 max-w-3xl text-[var(--color-text-muted)]">
                  {s.description}
                </p>

                {/* Stats grid */}
                <div className="mt-6 grid grid-cols-3 gap-3 sm:grid-cols-6">
                  {s.stats.map((stat) => (
                    <div
                      key={stat.label}
                      className="rounded-lg bg-[var(--color-bg)]/50 p-3 text-center"
                    >
                      <div className="text-lg font-bold">{stat.value}</div>
                      <div className="mt-0.5 text-xs text-[var(--color-text-muted)]">
                        {stat.label}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Details */}
                <div className="mt-6 flex flex-wrap gap-2">
                  {s.details.map((d) => (
                    <span
                      key={d}
                      className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-1 text-xs text-[var(--color-text-muted)]"
                    >
                      {d}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
