import hashlib
import hmac
import logging
import time
from typing import Any

import aiohttp

from bot.config import WFP_MERCHANT_ACCOUNT, WFP_MERCHANT_SECRET, PRICE_UAH

log = logging.getLogger(__name__)

_API_URL = "https://api.wayforpay.com/api"

_BASE_URL = "https://worker-production-2e5c.up.railway.app"
_SERVICE_URL = _BASE_URL + "/wfp"
_RETURN_URL = _BASE_URL + "/wfp/return"
_DOMAIN = "worker-production-2e5c.up.railway.app"


def _sign(params: list) -> str:
    msg = ";".join(str(p) for p in params)
    log.debug("WFP sign string: %s", msg)
    return hmac.new(
        WFP_MERCHANT_SECRET.encode(),
        msg.encode(),
        hashlib.md5,
    ).hexdigest()


async def create_invoice(order_id: str) -> str:
    """Call WayForPay CREATE_INVOICE and return invoiceUrl."""
    order_date = int(time.time())
    product_name = f"Персональна пісня {order_id}"
    product_count = 1
    product_price = PRICE_UAH

    signature = _sign([
        WFP_MERCHANT_ACCOUNT,
        _DOMAIN,
        order_id,
        order_date,
        product_price,
        "UAH",
        product_name,
        product_count,
        product_price,
    ])

    payload = {
        "transactionType": "CREATE_INVOICE",
        "merchantAccount": WFP_MERCHANT_ACCOUNT,
        "merchantDomainName": _DOMAIN,
        "merchantSignature": signature,
        "apiVersion": 1,
        "orderReference": order_id,
        "orderDate": order_date,
        "amount": product_price,
        "currency": "UAH",
        "productName": [product_name],
        "productCount": [product_count],
        "productPrice": [product_price],
        "returnUrl": _RETURN_URL,
        "serviceUrl": _SERVICE_URL,
        "language": "UA",
        "paymentSystems": "card;googlePay;applePay",
        "productLogoUrl": "https://i.imgur.com/YVeJq9p.jpeg",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(_API_URL, json=payload) as resp:
            data = await resp.json(content_type=None)

    log.info("WFP CREATE_INVOICE response for %s: %s", order_id, data)

    reason = data.get("reasonCode") or data.get("reason", "")
    invoice_url = data.get("invoiceUrl", "")

    if reason != "Ok" or not invoice_url:
        raise RuntimeError(
            f"WayForPay CREATE_INVOICE failed for {order_id}: reason={reason!r}, data={data}"
        )

    return invoice_url


def verify_webhook(data: dict[str, Any]) -> bool:
    """Verify HMAC-MD5 signature from WayForPay webhook."""
    sign_params = [
        data.get("merchantAccount", ""),
        data.get("orderReference", ""),
        data.get("amount", ""),
        data.get("currency", ""),
        data.get("authCode", ""),
        data.get("cardPan", ""),
        data.get("transactionStatus", ""),
        data.get("reasonCode", ""),
    ]
    expected = _sign(sign_params)
    received = data.get("merchantSignature", "")
    return hmac.compare_digest(expected, received)


def build_webhook_response(order_id: str, status: str = "accept") -> dict:
    """Build the response WayForPay expects after webhook processing."""
    now = int(time.time())
    sign = _sign([order_id, status, now])
    return {
        "orderReference": order_id,
        "status": status,
        "time": now,
        "signature": sign,
    }
