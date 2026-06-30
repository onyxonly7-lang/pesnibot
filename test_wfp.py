"""Run this in Railway Console: python test_wfp.py"""
import asyncio, json, logging, os, sys
logging.basicConfig(level=logging.INFO, format="%(message)s")

sys.path.insert(0, "/app")  # Railway working dir

async def main():
    from bot.services.wayforpay import create_invoice, _sign, _DOMAIN, _API_URL
    from bot.config import WFP_MERCHANT_ACCOUNT, WFP_MERCHANT_SECRET, PRICE_UAH
    import aiohttp, time

    order_id = f"TEST-{int(time.time())}"
    order_date = int(time.time())
    product_name = f"Персональна пісня {order_id}"

    sign_string = ";".join(str(p) for p in [
        WFP_MERCHANT_ACCOUNT, _DOMAIN, order_id, order_date,
        PRICE_UAH, "UAH", product_name, 1, PRICE_UAH,
    ])
    print(f"\n=== SIGN STRING ===\n{sign_string}\n")
    print(f"MERCHANT_ACCOUNT: {WFP_MERCHANT_ACCOUNT}")
    print(f"DOMAIN: {_DOMAIN}")
    print(f"SECRET (first 4 chars): {WFP_MERCHANT_SECRET[:4]}...")
    print(f"PRICE: {PRICE_UAH}\n")

    payload = {
        "transactionType": "CREATE_INVOICE",
        "merchantAccount": WFP_MERCHANT_ACCOUNT,
        "merchantDomainName": _DOMAIN,
        "merchantSignature": _sign([
            WFP_MERCHANT_ACCOUNT, _DOMAIN, order_id, order_date,
            PRICE_UAH, "UAH", product_name, 1, PRICE_UAH,
        ]),
        "apiVersion": 1,
        "orderReference": order_id,
        "orderDate": order_date,
        "amount": PRICE_UAH,
        "currency": "UAH",
        "productName": [product_name],
        "productCount": [1],
        "productPrice": [PRICE_UAH],
        "returnUrl": "https://worker-production-2e5c.up.railway.app/wfp/return",
        "serviceUrl": "https://worker-production-2e5c.up.railway.app/wfp",
        "language": "UA",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(_API_URL, json=payload) as resp:
            text = await resp.text()
            print(f"=== HTTP STATUS: {resp.status} ===")
            print(f"=== RESPONSE BODY ===\n{text}\n")
            try:
                parsed = json.loads(text)
                print(f"reasonCode: {parsed.get('reasonCode')}")
                print(f"reason:     {parsed.get('reason')}")
                print(f"invoiceUrl: {parsed.get('invoiceUrl')}")
            except Exception as e:
                print(f"Could not parse JSON: {e}")

asyncio.run(main())
