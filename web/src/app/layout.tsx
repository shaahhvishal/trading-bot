import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AlgoEdge — Algorithmic Crypto Trading",
  description:
    "Backtested trading strategies, real-time signals, and automated execution for crypto markets.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="antialiased">{children}</body>
    </html>
  );
}
