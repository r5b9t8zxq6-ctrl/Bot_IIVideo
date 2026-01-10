import os
import asyncio
import logging
from typing import Optional

import httpx
import replicate
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# ================== ENV ==================

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://bot-iivideo.onrender.com
PORT = int(os.getenv("PORT", 10000))

if not BOT_TOKEN or not REPLICATE_API_TOKEN or not WEBHOOK_URL:
    raise RuntimeError("❌ Missing env variables")

# ================== CONFIG ==================

KLING_MODEL = "kwaivgi/kling-v2.5-turbo-pro"
FALLBACK_KLING_VERSION = "5c7d5dc6dd8bf75c1acaa8565735e7986bc5b66206b55cca93cb72c9bf15ccaa"

MAX_RETRIES = 3
POLL_INTERVAL = 5

# ================== INIT ==================

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

KLING_VERSION: Optional[str] = None
generation_queue: asyncio.Queue = asyncio.Queue()

# ================== FETCH LATEST VERSION ==================

async def fetch_latest_kling_version():
    global KLING_VERSION
    url = f"https://api.replicate.com/v1/models/{KLING_MODEL}"
    headers = {"Authorization": f"Token {REPLICATE_API_TOKEN}"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            KLING_VERSION = r.json()["latest_version"]["id"]
            logging.info(f"✅ Kling latest version: {KLING_VERSION}")
    except Exception as e:
        KLING_VERSION = FALLBACK_KLING_VERSION
        logging.error(f"❌ Version fetch failed: {e}")
        logging.warning(f"⚠ Using fallback: {KLING_VERSION}")

# ================== GENERATION ==================

async def generation_worker():
    logging.info("🚀 Generation worker started")
    while True:
        chat_id, prompt = await generation_queue.get()
        try:
            await generate_video(chat_id, prompt)
        except Exception as e:
            logging.exception(e)
            await bot.send_message(chat_id, "❌ Ошибка генерации. Попробуй позже.")
        generation_queue.task_done()

async def generate_video(chat_id: int, prompt: str):
    msg = await bot.send_message(chat_id, "🎬 Генерация началась (0%)")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            prediction = replicate_client.predictions.create(
                version=KLING_VERSION,
                input={
                    "prompt": prompt,
                    "duration": 5,
                    "fps": 24,
                },
            )

            progress = 0
            while prediction.status not in ("succeeded", "failed"):
                await asyncio.sleep(POLL_INTERVAL)
                prediction = replicate_client.predictions.get(prediction.id)

                progress = min(progress + 10, 90)
                await msg.edit_text(f"⏳ Генерация… {progress}%")

            if prediction.status == "succeeded":
                await msg.edit_text("✅ Готово! 100%")
                await bot.send_message(chat_id, prediction.output[0])
                return

            raise RuntimeError("Prediction failed")

        except Exception as e:
            logging.warning(f"Retry {attempt}/{MAX_RETRIES}: {e}")
            if attempt == MAX_RETRIES:
                raise

# ================== BOT HANDLERS ==================

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("👋 Отправь текст — сгенерирую видео через Kling.")

@dp.message()
async def prompt_handler(message: types.Message):
    await generation_queue.put((message.chat.id, message.text))
    await message.answer("📥 Добавлено в очередь")

# ================== FASTAPI / WEBHOOK ==================

@asynccontextmanager
async def lifespan(app: FastAPI):
    await fetch_latest_kling_version()
    asyncio.create_task(generation_worker())

    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(WEBHOOK_URL)

    logging.info("✅ Webhook установлен")
    yield
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

@app.post("/")
async def telegram_webhook(request: Request):
    update = types.Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}

@app.get("/")
async def health():
    return {"status": "ok"}

# ================== START SERVER ==================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=PORT,
    )