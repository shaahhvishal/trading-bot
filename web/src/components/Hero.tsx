export default function Hero() {
  return (
    <section className="bg-grid relative overflow-hidden pt-32 pb-20">
      {/* Gradient orbs */}
      <div className="pointer-events-none absolute -top-40 left-1/4 h-[500px] w-[500px] rounded-full bg-blue-600/10 blur-[120px]" />
      <div className="pointer-events-none absolute -top-20 right-1/4 h-[400px] w-[400px] rounded-full bg-emerald-600/10 blur-[120px]" />

      <div className="relative mx-auto max-w-7xl px-6 text-center">
        {/* Badge */}
        <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-card)] px-4 py-1.5 text-sm text-[var(--color-text-muted)]">
          <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
          Live signals running 24/7
        </div>

        <h1 className="mx-auto max-w-4xl text-5xl leading-tight font-extrabold tracking-tight sm:text-6xl lg:text-7xl">
          Trade crypto with{" "}
          <span className="text-gradient">data-driven</span> strategies
        </h1>

        <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-[var(--color-text-muted)]">
          Backtested algorithms that actually work. Real-time signals, automated
          execution, and transparent performance — no black boxes.
        </p>

        <div className="mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row">
          <a
            href="#pricing"
            className="rounded-xl bg-gradient-to-r from-blue-600 to-emerald-600 px-8 py-3.5 text-base font-semibold text-white shadow-lg shadow-blue-600/20 transition-all hover:from-blue-500 hover:to-emerald-500 hover:shadow-blue-500/30"
          >
            Start Free Trial
          </a>
          <a
            href="#strategies"
            className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] px-8 py-3.5 text-base font-semibold text-white transition-all hover:bg-[var(--color-bg-card-hover)]"
          >
            View Strategies
          </a>
        </div>

        {/* Stats row */}
        <div className="mx-auto mt-16 grid max-w-3xl grid-cols-2 gap-6 sm:grid-cols-4">
          {[
            { value: "+173%", label: "Best Strategy" },
            { value: "25.90", label: "Sharpe Ratio" },
            { value: "-9.8%", label: "Max Drawdown" },
            { value: "24/7", label: "Live Signals" },
          ].map((stat) => (
            <div key={stat.label} className="text-center">
              <div className="text-2xl font-bold text-white sm:text-3xl">
                {stat.value}
              </div>
              <div className="mt-1 text-sm text-[var(--color-text-muted)]">
                {stat.label}
              </div>
            </div>
          ))}
        </div>

        {/* Dashboard preview */}
        <div className="mx-auto mt-16 max-w-5xl">
          <div className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] shadow-2xl shadow-black/40">
            {/* Mock terminal/dashboard header */}
            <div className="flex items-center gap-2 border-b border-[var(--color-border)] px-4 py-3">
              <div className="h-3 w-3 rounded-full bg-red-500/80" />
              <div className="h-3 w-3 rounded-full bg-yellow-500/80" />
              <div className="h-3 w-3 rounded-full bg-green-500/80" />
              <span className="ml-4 text-xs text-[var(--color-text-muted)]">
                AlgoEdge Dashboard — BTC/USDT Confluence Strategy
              </span>
            </div>
            {/* Mock content */}
            <div className="p-6">
              <div className="grid grid-cols-4 gap-4">
                <DashStat label="Portfolio" value="$27,303" change="+173%" />
                <DashStat label="Confluence" value="7/12" change="BUY active" />
                <DashStat label="Profit Factor" value="3.16" change="Strong edge" />
                <DashStat label="Max Drawdown" value="-9.8%" change="Controlled" />
              </div>
              {/* Mock chart area */}
              <div className="mt-6 flex h-48 items-end gap-1 rounded-lg bg-[var(--color-bg)]/50 p-4">
                {mockEquityCurve.map((v, i) => (
                  <div
                    key={i}
                    className="flex-1 rounded-t bg-gradient-to-t from-blue-600/60 to-emerald-500/60"
                    style={{ height: `${v}%` }}
                  />
                ))}
              </div>
              <div className="mt-2 flex justify-between text-xs text-[var(--color-text-muted)]">
                <span>Sep 2024</span>
                <span>Oct</span>
                <span>Nov</span>
                <span>Dec 2024</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function DashStat({
  label,
  value,
  change,
}: {
  label: string;
  value: string;
  change: string;
}) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)]/50 p-3">
      <div className="text-xs text-[var(--color-text-muted)]">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
      <div className="mt-0.5 text-xs text-emerald-400">{change}</div>
    </div>
  );
}

// Simulated equity curve bars (% height)
const mockEquityCurve = [
  20, 22, 18, 25, 28, 24, 30, 35, 32, 38, 42, 40, 45, 43, 50, 48, 55, 52,
  58, 62, 60, 65, 63, 68, 72, 70, 75, 78, 80, 82, 85, 88, 86, 90, 92, 88,
  91, 95, 93, 96, 98, 95, 100,
];
