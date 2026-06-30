import json
import logging

from aiohttp import web
from aiogram import Bot

from bot import db
from bot.services.wayforpay import verify_webhook, build_webhook_response, create_invoice, create_invoice_debug
from bot.handlers.user import deliver_full_track

log = logging.getLogger(__name__)


async def wfp_webhook(request: web.Request) -> web.Response:
    bot: Bot = request.app["bot"]
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="bad json")

    order_id: str = data.get("orderReference", "")
    tx_status: str = data.get("transactionStatus", "")
    log.info("WFP webhook: order=%s status=%s", order_id, tx_status)

    if not verify_webhook(data):
        log.warning("WFP signature mismatch for order %s: %s", order_id, data)
        return web.Response(status=403, text="invalid signature")

    if tx_status == "Approved":
        order = await db.get_order(order_id)
        if order and order["status"] != "paid":
            await deliver_full_track(bot, order_id)

    resp = build_webhook_response(order_id, status="accept")
    return web.Response(content_type="application/json", text=json.dumps(resp))


async def wfp_return(request: web.Request) -> web.Response:
    # WayForPay returns the customer here via POST (sometimes GET).
    # No logic — delivery happens only in the webhook (/wfp).
    return web.Response(
        content_type="text/html",
        text=(
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Оплата успішна</title></head>"
            "<body style='font-family:sans-serif;text-align:center;padding:60px 20px'>"
            "<h2>✅ Оплата успішна!</h2>"
            "<p>Поверніться в Telegram — ваша пісня вже чекає на вас 🎵</p>"
            "</body></html>"
        ),
    )


async def test_payment(request: web.Request) -> web.Response:
    import time
    order_id = request.rel_url.query.get("order_id") or f"TEST-{int(time.time())}"
    try:
        info = await create_invoice_debug(order_id)
        return web.Response(
            content_type="application/json",
            text=json.dumps(info, ensure_ascii=False, indent=2),
        )
    except Exception as e:
        return web.Response(status=500, content_type="text/plain", text=str(e))
