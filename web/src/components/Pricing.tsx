const plans = [
  {
    name: "Free",
    price: "$0",
    period: "forever",
    description: "Explore strategies and paper trade",
    features: [
      "Strategy performance dashboard",
      "Paper trading mode",
      "Delayed signals (15min)",
      "Basic backtesting",
      "Community access",
    ],
    cta: "Get Started",
    ctaStyle:
      "border border-[var(--color-border)] bg-[var(--color-bg-card)] hover:bg-[var(--color-bg-card-hover)]",
    popular: false,
  },
  {
    name: "Pro",
    price: "$49",
    period: "/month",
    description: "Real-time signals and automation",
    features: [
      "Everything in Free",
      "Real-time signal alerts",
      "Telegram + webhook notifications",
      "Prediction market signals",
      "Advanced backtesting",
      "Priority support",
    ],
    cta: "Start Free Trial",
    ctaStyle:
      "bg-gradient-to-r from-blue-600 to-emerald-600 hover:from-blue-500 hover:to-emerald-500 shadow-lg shadow-blue-600/20",
    popular: true,
  },
  {
    name: "Institutional",
    price: "Custom",
    period: "",
    description: "Fully automated with custom strategies",
    features: [
      "Everything in Pro",
      "Automated execution (Hyperliquid)",
      "Custom strategy development",
      "API access",
      "Dedicated risk management",
      "White-glove onboarding",
    ],
    cta: "Contact Us",
    ctaStyle:
      "border border-[var(--color-border)] bg-[var(--color-bg-card)] hover:bg-[var(--color-bg-card-hover)]",
    popular: false,
  },
];

export default function Pricing() {
  return (
    <section id="pricing" className="py-24 bg-[var(--color-bg-card)]/30">
      <div className="mx-auto max-w-7xl px-6">
        <div className="text-center">
          <h2 className="text-3xl font-bold sm:text-4xl">
            Simple, <span className="text-gradient">transparent</span> pricing
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-[var(--color-text-muted)]">
            Start free, upgrade when you&#39;re ready. No hidden fees, no long-term
            commitments.
          </p>
        </div>

        <div className="mx-auto mt-16 grid max-w-5xl gap-6 lg:grid-cols-3">
          {plans.map((plan) => (
            <div
              key={plan.name}
              className={`relative rounded-xl border bg-[var(--color-bg-card)] p-6 ${
                plan.popular
                  ? "border-blue-500/50 shadow-lg shadow-blue-600/10"
                  : "border-[var(--color-border)]"
              }`}
            >
              {plan.popular && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-gradient-to-r from-blue-600 to-emerald-600 px-4 py-1 text-xs font-semibold text-white">
                  Most Popular
                </div>
              )}

              <div className="text-center">
                <h3 className="text-lg font-semibold">{plan.name}</h3>
                <div className="mt-4 flex items-baseline justify-center gap-1">
                  <span className="text-4xl font-extrabold">{plan.price}</span>
                  {plan.period && (
                    <span className="text-[var(--color-text-muted)]">
                      {plan.period}
                    </span>
                  )}
                </div>
                <p className="mt-2 text-sm text-[var(--color-text-muted)]">
                  {plan.description}
                </p>
              </div>

              <ul className="mt-8 space-y-3">
                {plan.features.map((f) => (
                  <li
                    key={f}
                    className="flex items-start gap-3 text-sm text-[var(--color-text-muted)]"
                  >
                    <svg
                      className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="3"
                    >
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                    {f}
                  </li>
                ))}
              </ul>

              <a
                href="#"
                className={`mt-8 block rounded-lg px-4 py-3 text-center text-sm font-semibold text-white transition-all ${plan.ctaStyle}`}
              >
                {plan.cta}
              </a>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
