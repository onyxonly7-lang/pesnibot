import hashlib
import hmac
import time
import urllib.parse
from typing import Any

from bot.config import WFP_MERCHANT_ACCOUNT, WFP_MERCHANT_SECRET, WEBHOOK_URL, PRICE_UAH

_WFP_PAY_URL = "https://secure.wayforpay.com/pay"

# Фиксированные URL согласно договорённости
_BASE_URL = "https://worker-production-2e5c.up.railway.app"
_SERVICE_URL = _BASE_URL + "/wfp"
_RETURN_URL = _BASE_URL + "/wfp/return"
_DOMAIN = "worker-production-2e5c.up.railway.app"


def _sign(params: list) -> str:
    msg = ";".join(str(p) for p in params)
    return hmac.new(
        WFP_MERCHANT_SECRET.encode(),
        msg.encode(),
        hashlib.md5,
    ).hexdigest()


def build_payment_url(order_id: str, user_id: int) -> str:
    order_date = int(time.time())
    product_name = f"Персональная песня {order_id}"
    product_count = 1
    product_price = PRICE_UAH

    # Порядок полей подписи строго по документации WayForPay
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

    params = {
        "merchantAccount": WFP_MERCHANT_ACCOUNT,
        "merchantDomainName": _DOMAIN,
        "orderReference": order_id,
        "orderDate": order_date,
        "amount": product_price,
        "currency": "UAH",
        "productName[]": product_name,
        "productCount[]": product_count,
        "productPrice[]": product_price,
        "merchantSignature": signature,
        "returnUrl": _RETURN_URL,
        "serviceUrl": _SERVICE_URL,
        "language": "RU",
        "paymentSystems": "card;googlePay;applePay",
        "productLogoUrl": "https://i.imgur.com/YVeJq9p.jpeg",
    }
    return _WFP_PAY_URL + "?" + urllib.parse.urlencode(params)


def verify_webhook(data: dict[str, Any]) -> bool:
    """Проверяет HMAC-MD5 подпись входящего вебхука от WayForPay."""
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
    """Ответ который WayForPay ожидает после обработки вебхука."""
    now = int(time.time())
    sign = _sign([order_id, status, now])
    return {
        "orderReference": order_id,
        "status": status,
        "time": now,
        "signature": sign,
    }
