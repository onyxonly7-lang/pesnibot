import asyncio
import logging
from datetime import datetime, timezone, timedelta

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import ADMIN_CHAT_ID
from bot.services.stats import (
    daily_stats,
    monthly_stats,
    funnel_stats,
    format_daily,
    format_monthly,
    format_funnel,
)

log = logging.getLogger(__name__)
router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id == ADMIN_CHAT_ID


# ── /stats ────────────────────────────────────────────────────────────────

@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    s = await funnel_stats()
    await message.answer(format_funnel(s))


# ── /stats_orders (old order-status summary) ──────────────────────────────

@router.message(Command("stats_orders"))
async def cmd_stats_orders(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    s = await daily_stats()
    await message.answer(format_daily(s))


# ── /stats_month ──────────────────────────────────────────────────────────

@router.message(Command("stats_month"))
async def cmd_stats_month(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    s = await monthly_stats()
    await message.answer(format_monthly(s))


# ── Daily scheduler ───────────────────────────────────────────────────────

async def run_daily_stats(bot: Bot) -> None:
    """Background task: sends daily stats at 00:01 UTC every day."""
    while True:
        now = datetime.now(timezone.utc)
        # Next 00:01 UTC
        tomorrow = (now + timedelta(days=1)).replace(
            hour=0, minute=1, second=0, microsecond=0
        )
        wait_seconds = (tomorrow - now).total_seconds()
        log.info("Daily stats scheduled in %.0f seconds", wait_seconds)
        await asyncio.sleep(wait_seconds)

        # Stats for the day that just ended
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        try:
            s = await daily_stats(yesterday)
            await bot.send_message(ADMIN_CHAT_ID, format_daily(s))
        except Exception:
            log.exception("Failed to send daily stats")
