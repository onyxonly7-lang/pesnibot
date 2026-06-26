import hashlib
import hmac
import time
from typing import Any

from bot.config import WFP_MERCHANT_ACCOUNT, WFP_MERCHANT_SECRET, WEBHOOK_URL, PRICE_UAH

_WFP_URL = "https://secure.wayforpay.com/pay"


def _sign(params: list[str]) -> str:
    msg = ";".join(str(p) for p in params)
    return hmac.new(
        WFP_MERCHANT_SECRET.encode(),
        msg.encode(),
        hashlib.md5,
    ).hexdigest()


def build_payment_url(order_id: str, user_id: int) -> str:
    order_date = int(time.time())
    product_name = "Персональная песня"
    product_count = 1
    product_price = PRICE_UAH

    sign_params = [
        WFP_MERCHANT_ACCOUNT,
        WEBHOOK_URL.rstrip("/") + "/wfp",  # merchantDomainName approximation
        order_id,
        order_date,
        product_price,
        "UAH",
        product_name,
        product_count,
        product_price,
    ]
    signature = _sign(sign_params)

    import urllib.parse

    params = {
        "merchantAccount": WFP_MERCHANT_ACCOUNT,
        "merchantDomainName": WEBHOOK_URL.rstrip("/") + "/wfp",
        "orderReference": order_id,
        "orderDate": order_date,
        "amount": product_price,
        "currency": "UAH",
        "productName[]": product_name,
        "productCount[]": product_count,
        "productPrice[]": product_price,
        "merchantSignature": signature,
        "returnUrl": WEBHOOK_URL.rstrip("/") + "/wfp/return",
        "serviceUrl": WEBHOOK_URL.rstrip("/") + "/wfp",
        "language": "UA",
    }
    return _WFP_URL + "?" + urllib.parse.urlencode(params)


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
