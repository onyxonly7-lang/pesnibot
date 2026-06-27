import asyncio
import logging
import os

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import BOT_TOKEN, WEBHOOK_URL
from bot import db
from bot.handlers import user, admin
from bot.handlers.payment import wfp_webhook, wfp_return
from bot.handlers.stats import router as stats_router, run_daily_stats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

WFP_PATH = "/wfp"
WFP_RETURN_PATH = "/wfp/return"
WEBHOOK_PATH = "/webhook"


async def main() -> None:
    await db.init_db()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(stats_router)
    dp.include_router(admin.router)
    dp.include_router(user.router)

    app = web.Application()
    app["bot"] = bot
    app.router.add_post(WFP_PATH, wfp_webhook)
    app.router.add_get(WFP_RETURN_PATH, wfp_return)
    app.router.add_post(WEBHOOK_PATH, _make_tg_webhook_handler(bot, dp))

    webhook_url = WEBHOOK_URL.rstrip("/") + WEBHOOK_PATH
    await bot.set_webhook(webhook_url, drop_pending_updates=False)
    log.info("Webhook set to %s", webhook_url)

    # Railway задаёт PORT через переменную окружения
    port = int(os.getenv("PORT", "8080"))

    stats_task = asyncio.create_task(run_daily_stats(bot))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("HTTP server started on :%d", port)

    try:
        await asyncio.Event().wait()
    finally:
        stats_task.cancel()
        await runner.cleanup()
        await bot.session.close()


def _make_tg_webhook_handler(bot: Bot, dp: Dispatcher):
    from aiogram.types import Update

    async def handler(request: web.Request) -> web.Response:
        data = await request.json()
        update = Update.model_validate(data)
        await dp.feed_update(bot, update)
        return web.Response(text="ok")

    return handler


if __name__ == "__main__":
    asyncio.run(main())
