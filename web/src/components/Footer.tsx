export default function Footer() {
  return (
    <footer className="border-t border-[var(--color-border)] py-12">
      <div className="mx-auto max-w-7xl px-6">
        <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
          {/* Brand */}
          <div>
            <div className="flex items-center gap-2 text-lg font-bold">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-blue-500 to-emerald-500">
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="white"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <polyline points="22 7 13.5 15.5 8.5 10.5 2 17" />
                  <polyline points="16 7 22 7 22 13" />
                </svg>
              </div>
              Algo<span className="text-gradient">Edge</span>
            </div>
            <p className="mt-3 text-sm text-[var(--color-text-muted)]">
              Data-driven crypto trading strategies. Backtested, validated, and
              ready to deploy.
            </p>
          </div>

          {/* Product */}
          <div>
            <h4 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
              Product
            </h4>
            <ul className="mt-4 space-y-2 text-sm text-[var(--color-text-muted)]">
              <li><a href="#features" className="hover:text-white">Features</a></li>
              <li><a href="#strategies" className="hover:text-white">Strategies</a></li>
              <li><a href="#performance" className="hover:text-white">Performance</a></li>
              <li><a href="#pricing" className="hover:text-white">Pricing</a></li>
            </ul>
          </div>

          {/* Resources */}
          <div>
            <h4 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
              Resources
            </h4>
            <ul className="mt-4 space-y-2 text-sm text-[var(--color-text-muted)]">
              <li><a href="#" className="hover:text-white">Documentation</a></li>
              <li><a href="#" className="hover:text-white">Blog</a></li>
              <li><a href="#" className="hover:text-white">API Reference</a></li>
              <li><a href="#" className="hover:text-white">Status</a></li>
            </ul>
          </div>

          {/* Legal */}
          <div>
            <h4 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
              Legal
            </h4>
            <ul className="mt-4 space-y-2 text-sm text-[var(--color-text-muted)]">
              <li><a href="#" className="hover:text-white">Privacy Policy</a></li>
              <li><a href="#" className="hover:text-white">Terms of Service</a></li>
              <li><a href="#" className="hover:text-white">Risk Disclaimer</a></li>
            </ul>
          </div>
        </div>

        <div className="mt-12 border-t border-[var(--color-border)] pt-8">
          <div className="flex flex-col items-center justify-between gap-4 sm:flex-row">
            <p className="text-xs text-[var(--color-text-muted)]">
              &copy; 2024 AlgoEdge. All rights reserved.
            </p>
            <p className="text-xs text-[var(--color-text-muted)]">
              Trading involves risk. Past performance does not guarantee future
              results.
            </p>
          </div>
        </div>
      </div>
    </footer>
  );
}
