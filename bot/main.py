import asyncio
import logging
import os

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import BOT_TOKEN, WEBHOOK_URL
from bot import db
from bot.handlers import user, admin
from bot.handlers.payment import wfp_webhook, wfp_return, test_payment
from bot.handlers.stats import router as stats_router, run_daily_stats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

WFP_PATH = "/wfp"
WFP_RETURN_PATH = "/wfp/return"
WEBHOOK_PATH = "/webhook"


def _build_app(bot: Bot, dp: Dispatcher) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_post(WFP_PATH, wfp_webhook)
    app.router.add_get(WFP_RETURN_PATH, wfp_return)
    app.router.add_get("/test_payment", test_payment)
    if WEBHOOK_URL:
        app.router.add_post(WEBHOOK_PATH, _make_tg_webhook_handler(bot, dp))
    return app


async def _run_http(app: web.Application) -> None:
    port = int(os.getenv("PORT", "8080"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("HTTP server listening on :%d", port)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


async def _run_polling(bot: Bot, dp: Dispatcher) -> None:
    log.info("Starting aiogram polling (no WEBHOOK_URL set)")
    await dp.start_polling(bot, drop_pending_updates=False)


async def main() -> None:
    await db.init_db()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(stats_router)
    dp.include_router(admin.router)
    dp.include_router(user.router)

    app = _build_app(bot, dp)

    stats_task = asyncio.create_task(run_daily_stats(bot))

    try:
        if WEBHOOK_URL:
            webhook_url = WEBHOOK_URL.rstrip("/") + WEBHOOK_PATH
            await bot.set_webhook(webhook_url, drop_pending_updates=False)
            log.info("Webhook set to %s", webhook_url)
            await _run_http(app)
        else:
            # No webhook configured: run HTTP server and polling side-by-side
            await asyncio.gather(
                _run_http(app),
                _run_polling(bot, dp),
            )
    finally:
        stats_task.cancel()
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
