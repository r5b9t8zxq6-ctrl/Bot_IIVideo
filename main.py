import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from bot import bot, dp
from router import router
from config import FULL_WEBHOOK_URL, WEBHOOK_PATH
from logger import setup_logging

# --------------------
# Logging
# --------------------
setup_logging()
logger = logging.getLogger(__name__)

# --------------------
# Routers
# --------------------
dp.include_router(router)

# --------------------
# Lifespan
# --------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Startup")

    await bot.set_webhook(FULL_WEBHOOK_URL)

    yield

    logger.info("🛑 Shutdown")
    await bot.delete_webhook()
    await bot.session.close()

# --------------------
# FastAPI app
# --------------------
app = FastAPI(lifespan=lifespan)

# --------------------
# Webhook endpoint
# --------------------
@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    update = await request.json()
    await dp.feed_raw_update(bot, update)
    return {"ok": True}