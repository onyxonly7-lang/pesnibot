import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
OPENAI_API_KEY: str = os.environ["OPENAI_API_KEY"]
ADMIN_CHAT_ID: int = int(os.environ["ADMIN_CHAT_ID"])
MUREKA_API_KEY: str = os.getenv("MUREKA_API_KEY", "")
WFP_MERCHANT_ACCOUNT: str = os.getenv("WFP_MERCHANT_ACCOUNT", "")
WFP_MERCHANT_SECRET: str = os.getenv("WFP_MERCHANT_SECRET", "")
WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")
IBAN: str = os.getenv("IBAN", "")
MANAGER_USERNAME: str = os.getenv("MANAGER_USERNAME", "@manager")

EXAMPLE_SONG_MOM: str = os.getenv("EXAMPLE_SONG_MOM", "")
EXAMPLE_SONG_BELOVED_FEMALE: str = os.getenv("EXAMPLE_SONG_BELOVED_FEMALE", "")
EXAMPLE_SONG_BELOVED_MALE: str = os.getenv("EXAMPLE_SONG_BELOVED_MALE", "")

PRICE_UAH: int = 349
PREVIEW_START_MS: int = 0
PREVIEW_END_MS: int = 60_000
PREVIEW_FADEOUT_SEC: int = 3
