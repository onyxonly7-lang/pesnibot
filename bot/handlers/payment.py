import json
import logging

from aiohttp import web
from aiogram import Bot

from bot import db
from bot.services.wayforpay import verify_webhook, build_webhook_response, build_payment_url
from bot.handlers.user import deliver_full_track

log = logging.getLogger(__name__)


async def wfp_webhook(request: web.Request) -> web.Response:
    bot: Bot = request.app["bot"]
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="bad json")

    if not verify_webhook(data):
        log.warning("WFP signature mismatch: %s", data)
        return web.Response(status=403, text="invalid signature")

    order_id: str = data.get("orderReference", "")
    tx_status: str = data.get("transactionStatus", "")

    if tx_status == "Approved":
        order = await db.get_order(order_id)
        if order and order["status"] != "paid":
            await deliver_full_track(bot, order_id)

    resp = build_webhook_response(order_id, status="accept")
    return web.Response(content_type="application/json", text=json.dumps(resp))


async def wfp_return(request: web.Request) -> web.Response:
    return web.Response(
        content_type="text/html",
        text="<h2>Дякуємо! Ваш платіж обробляється. Поверніться до Telegram.</h2>",
    )


async def test_payment(request: web.Request) -> web.Response:
    order_id = request.rel_url.query.get("order_id", "TEST-001")
    url = build_payment_url(order_id)
    return web.Response(content_type="text/plain", text=url)
