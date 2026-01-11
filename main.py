import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request

from bot import bot, dp
from router import router
from worker import worker
from config import FULL_WEBHOOK_URL, WEBHOOK_PATH
from logging import logger
from logger import setup_logging

dp.include_router(router)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Startup")
    await bot.set_webhook(FULL_WEBHOOK_URL)
    task = asyncio.create_task(worker())
    yield
    task.cancel()
    await bot.delete_webhook()
    logger.info("Shutdown")

app = FastAPI(lifespan=lifespan)

setup_logging()

import logging
logger = logging.getLogger(__name__)

logger.info("Bot started")

@app.post(WEBHOOK_PATH)
async def webhook(request: Request):
    update = await request.json()
    await dp.feed_raw_update(bot, update)
    return {"ok": True}
