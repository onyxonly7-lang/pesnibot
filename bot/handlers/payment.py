import html
import json
import logging
import time

from aiohttp import web
from aiogram import Bot

from bot import db
from bot.services.wayforpay import verify_webhook, build_webhook_response, build_payment_params
from bot.handlers.user import deliver_full_track

log = logging.getLogger(__name__)


async def pay_page(request: web.Request) -> web.Response:
    """Render an HTML page that auto-submits a POST form to WayForPay."""
    order_id = request.match_info["order_id"].upper()
    order = await db.get_order(order_id)
    if not order:
        return web.Response(status=404, text="Order not found")

    params = build_payment_params(order_id)

    fields_html = "\n".join(
        f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(str(v))}">'
        for k, v in params.items()
    )

    page = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Оплата</title>
  <style>
    body {{ font-family: sans-serif; display: flex; align-items: center;
           justify-content: center; height: 100vh; margin: 0; background: #f5f5f5; }}
    .box {{ text-align: center; color: #555; }}
    .spinner {{ width: 40px; height: 40px; border: 4px solid #ddd;
                border-top-color: #4a90e2; border-radius: 50%;
                animation: spin 0.8s linear infinite; margin: 0 auto 16px; }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    .btn {{ margin-top: 24px; padding: 14px 28px; background: #4a90e2; color: #fff;
            border: none; border-radius: 8px; font-size: 16px; cursor: pointer; }}
  </style>
</head>
<body>
  <div class="box">
    <div class="spinner"></div>
    <p>Переходимо до оплати...</p>
    <form id="wfp" method="POST" action="https://secure.wayforpay.com/pay">
      {fields_html}
      <noscript>
        <button class="btn" type="submit">Перейти до оплати</button>
      </noscript>
    </form>
    <button class="btn" id="btn" style="display:none" onclick="document.getElementById('wfp').submit()">
      Перейти до оплати
    </button>
  </div>
  <script>
    window.onload = function() {{
      try {{
        document.getElementById("wfp").submit();
      }} catch(e) {{
        document.getElementById("btn").style.display = "inline-block";
      }}
    }};
    setTimeout(function() {{
      document.getElementById("btn").style.display = "inline-block";
    }}, 1500);
  </script>
</body>
</html>"""
    return web.Response(content_type="text/html", text=page)


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
