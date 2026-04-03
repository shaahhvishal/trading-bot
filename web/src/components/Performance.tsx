const trades = [
  { date: "Dec 05", side: "LONG", entry: "$97,989", exit: "$104,778", pnl: "+$1,797", pnlPct: "+6.93%", win: true, strategy: "Confluence" },
  { date: "Nov 28", side: "LONG", entry: "$99,444", exit: "$98,872", pnl: "-$164", pnlPct: "-0.57%", win: false, strategy: "Confluence" },
  { date: "Nov 21", side: "LONG", entry: "$92,427", exit: "$95,996", pnl: "+$448", pnlPct: "+3.86%", win: true, strategy: "Confluence" },
  { date: "Nov 05", side: "LONG", entry: "$75,136", exit: "$87,314", pnl: "+$1,674", pnlPct: "+16.21%", win: true, strategy: "Confluence" },
  { date: "Oct 24", side: "LONG", entry: "$67,492", exit: "$70,757", pnl: "+$474", pnlPct: "+4.84%", win: true, strategy: "Confluence" },
  { date: "Oct 11", side: "LONG", entry: "$62,843", exit: "$67,389", pnl: "+$804", pnlPct: "+7.23%", win: true, strategy: "Vol Breakout" },
  { date: "Sep 30", side: "LONG", entry: "$69,514", exit: "$95,041", pnl: "+$5,137", pnlPct: "+25.61%", win: true, strategy: "EMA Swing" },
  { date: "Sep 17", side: "LONG", entry: "$61,052", exit: "$65,392", pnl: "+$745", pnlPct: "+7.11%", win: true, strategy: "Vol Breakout" },
  { date: "Sep 09", side: "LONG", entry: "$88,940", exit: "$95,996", pnl: "+$1,989", pnlPct: "+7.93%", win: true, strategy: "Confluence" },
  { date: "Sep 04", side: "LONG", entry: "$97,794", exit: "$95,041", pnl: "-$779", pnlPct: "-2.81%", win: false, strategy: "Confluence" },
];

export default function Performance() {
  return (
    <section id="performance" className="py-24">
      <div className="mx-auto max-w-7xl px-6">
        <div className="text-center">
          <h2 className="text-3xl font-bold sm:text-4xl">
            <span className="text-gradient">Verified</span> trade history
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-[var(--color-text-muted)]">
            Real trades across all strategies on BTC/USDT.
            Out-of-sample period: September &mdash; December 2024.
          </p>
        </div>

        <div className="mx-auto mt-12 max-w-4xl overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)]">
          {/* Table header */}
          <div className="grid grid-cols-7 gap-4 border-b border-[var(--color-border)] bg-[var(--color-bg)] px-6 py-3 text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
            <div>Date</div>
            <div>Strategy</div>
            <div>Side</div>
            <div>Entry</div>
            <div>Exit</div>
            <div className="text-right">P&L</div>
            <div className="text-right">Return</div>
          </div>

          {/* Rows */}
          {trades.map((t, i) => (
            <div
              key={i}
              className="grid grid-cols-7 gap-4 border-b border-[var(--color-border)]/50 px-6 py-3 text-sm transition-colors hover:bg-[var(--color-bg-card-hover)]"
            >
              <div className="text-[var(--color-text-muted)]">{t.date}</div>
              <div className="text-xs text-[var(--color-text-muted)]">{t.strategy}</div>
              <div>
                <span
                  className={`rounded px-2 py-0.5 text-xs font-semibold ${
                    t.side === "LONG"
                      ? "bg-emerald-500/20 text-emerald-400"
                      : "bg-red-500/20 text-red-400"
                  }`}
                >
                  {t.side}
                </span>
              </div>
              <div className="font-mono text-xs">{t.entry}</div>
              <div className="font-mono text-xs">{t.exit}</div>
              <div
                className={`text-right font-mono text-xs font-semibold ${
                  t.win ? "text-emerald-400" : "text-red-400"
                }`}
              >
                {t.pnl}
              </div>
              <div
                className={`text-right font-mono text-xs ${
                  t.win ? "text-emerald-400" : "text-red-400"
                }`}
              >
                {t.pnlPct}
              </div>
            </div>
          ))}

          {/* Footer */}
          <div className="flex items-center justify-between bg-[var(--color-bg)]/50 px-6 py-4">
            <span className="text-sm text-[var(--color-text-muted)]">
              Showing recent trades across all strategies (91 total)
            </span>
            <a
              href="#"
              className="text-sm font-medium text-blue-400 hover:text-blue-300"
            >
              View full history &rarr;
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
