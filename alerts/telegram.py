"""
Telegram alerting for the trading bot.

Sends messages via the Telegram Bot API for:
  - Every trade entry/exit
  - Daily P&L summary at midnight UTC
  - Risk limit breaches
  - Errors and crashes

Bot token and chat ID come from environment variables (.env file).
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from loguru import logger


class TelegramAlerter:
    """Send alerts via Telegram bot."""

    def __init__(self, bot_token: str, chat_id: str) -> None:
        """Initialize Telegram alerter.

        Args:
            bot_token: Telegram bot API token (from @BotFather).
            chat_id: Telegram chat/group ID to send messages to.
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._base_url = f"https://api.telegram.org/bot{bot_token}"
        self._enabled = bool(bot_token and chat_id)

        if not self._enabled:
            logger.warning("Telegram alerts disabled — missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")

    @classmethod
    def from_env(cls) -> TelegramAlerter:
        """Create a TelegramAlerter from environment variables.

        Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from os.environ
        (populated by python-dotenv from .env file).
        """
        from dotenv import load_dotenv
        load_dotenv()

        return cls(
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        )

    async def send(self, message: str) -> bool:
        """Send a message to the configured Telegram chat.

        Args:
            message: Text message to send.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not self._enabled:
            logger.debug(f"Telegram (disabled): {message[:80]}...")
            return False

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self._base_url}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": message,
                        "parse_mode": "HTML",
                    },
                )
                if response.status_code == 200:
                    return True
                else:
                    logger.warning(
                        f"Telegram API error {response.status_code}: {response.text}"
                    )
                    return False
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    async def send_trade(self, trade: dict) -> bool:
        """Send a formatted trade alert.

        Args:
            trade: Trade record dict from the executor.
        """
        if trade.get("action") == "open":
            msg = (
                f"📈 <b>OPEN {trade['side'].upper()}</b> {trade['symbol']}\n"
                f"Price: ${trade['price']:,.2f}\n"
                f"Size: ${trade['size']:,.2f}"
            )
        else:
            emoji = "✅" if trade.get("pnl", 0) >= 0 else "❌"
            msg = (
                f"{emoji} <b>CLOSE {trade['side'].upper()}</b> {trade['symbol']}\n"
                f"Entry: ${trade['entry_price']:,.2f} → Exit: ${trade['exit_price']:,.2f}\n"
                f"P&L: ${trade['pnl']:+,.2f} ({trade['pnl_pct']:+.2f}%)"
            )
        return await self.send(msg)

    async def send_risk_breach(self, details: str) -> bool:
        """Send a risk breach alert.

        Args:
            details: Description of the risk breach.
        """
        return await self.send(f"🚨 <b>RISK ALERT</b>\n{details}")

    async def send_error(self, error: str) -> bool:
        """Send an error alert.

        Args:
            error: Error description.
        """
        return await self.send(f"⚠️ <b>ERROR</b>\n{error}")

    async def send_daily_summary(self, summary: dict) -> bool:
        """Send a daily P&L summary.

        Args:
            summary: Summary dict from executor.summary().
        """
        msg = (
            f"📊 <b>DAILY SUMMARY</b>\n"
            f"──────────────\n"
            f"Capital: ${summary['capital']:,.2f}\n"
            f"Daily P&L: ${summary['daily_pnl']:+,.2f}\n"
            f"Total P&L: ${summary['total_pnl']:+,.2f}\n"
            f"Total Trades: {summary['total_trades']}\n"
            f"Open Positions: {len(summary['open_positions'])}"
        )
        return await self.send(msg)
