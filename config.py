import os

def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing env var: {name}")
    return value

BOT_TOKEN = require_env("BOT_TOKEN")
REPLICATE_API_TOKEN = require_env("REPLICATE_API_TOKEN")
OPENAI_API_KEY = require_env("OPENAI_API_KEY")
WEBHOOK_URL = require_env("WEBHOOK_URL")

WEBHOOK_PATH = "/webhook"
FULL_WEBHOOK_URL = f"{WEBHOOK_URL}{WEBHOOK_PATH}"

KLING_MODEL = "kwaivgi/kling-v2.5-turbo-pro"
QUEUE_MAXSIZE = 100