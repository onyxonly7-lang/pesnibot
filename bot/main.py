import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import BOT_TOKEN, WEBHOOK_URL
from bot import db
from bot.handlers import user, admin
from bot.handlers.payment import wfp_webhook, wfp_return

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

    dp.include_router(admin.router)   # admin first so its FSM states take priority
    dp.include_router(user.router)

    # aiohttp app for WayForPay webhook
    app = web.Application()
    app["bot"] = bot
    app.router.add_post(WFP_PATH, wfp_webhook)
    app.router.add_get(WFP_RETURN_PATH, wfp_return)

    webhook_url = WEBHOOK_URL.rstrip("/") + WEBHOOK_PATH
    app.router.add_post(WEBHOOK_PATH, _make_tg_webhook_handler(bot, dp))

    await bot.set_webhook(webhook_url, drop_pending_updates=True)
    log.info("Webhook set to %s", webhook_url)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    log.info("HTTP server started on :8080")

    try:
        await asyncio.Event().wait()
    finally:
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
