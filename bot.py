import os
import asyncio
import logging
from typing import Optional

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest
from fastapi import FastAPI, Request, HTTPException
from dotenv import load_dotenv
import replicate
import httpx

# =======================
# ENV
# =======================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
WEBHOOK_PATH = "/"
PORT = int(os.getenv("PORT", 10000))

MODEL_OWNER = "kwaivgi"
MODEL_NAME = "kling-v2.5-turbo-pro"

MAX_RETRIES = 3
POLL_INTERVAL = 5  # seconds

if not all([BOT_TOKEN, REPLICATE_API_TOKEN, WEBHOOK_SECRET]):
    raise RuntimeError("❌ BOT_TOKEN / REPLICATE_API_TOKEN / WEBHOOK_SECRET missing")

# =======================
# LOGGING
# =======================

logging.basicConfig(level=logging.INFO)

# =======================
# BOT / DISPATCHER
# =======================

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# =======================
# FASTAPI
# =======================

app = FastAPI()

# =======================
# REPLICATE
# =======================

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)
KLING_VERSION: Optional[str] = None

# =======================
# QUEUE
# =======================

generation_queue: asyncio.Queue = asyncio.Queue()

# =======================
# UTILS
# =======================

async def fetch_latest_version() -> str:
    url = f"https://api.replicate.com/v1/models/{MODEL_OWNER}/{MODEL_NAME}/versions"
    headers = {"Authorization": f"Token {REPLICATE_API_TOKEN}"}

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
        return data["results"][0]["id"]

# =======================
# GENERATION WORKER
# =======================

async def generation_worker():
    logging.info("🚀 Generation worker started")

    while True:
        chat_id, prompt = await generation_queue.get()

        try:
            await generate_video(chat_id, prompt)
        except Exception as e:
            logging.exception(e)
            await bot.send_message(
                chat_id,
                "❌ Ошибка генерации.\nВозможно, модель недоступна или перегружена."
            )

        generation_queue.task_done()

# =======================
# GENERATE VIDEO
# =======================

async def generate_video(chat_id: int, prompt: str):
    msg = await bot.send_message(chat_id, "🎬 Генерация началась (0%)")

    last_progress = -1

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

                if progress != last_progress:
                    try:
                        await msg.edit_text(f"⏳ Генерация… {progress}%")
                        last_progress = progress
                    except TelegramBadRequest:
                        pass

            if prediction.status == "succeeded":
                await msg.edit_text("✅ Готово! 100%")
                await bot.send_message(chat_id, prediction.output[0])
                return

            raise RuntimeError("Prediction failed")

        except Exception as e:
            logging.warning(f"Retry {attempt}/{MAX_RETRIES}: {e}")
            if attempt == MAX_RETRIES:
                raise

# =======================
# HANDLERS
# =======================

@router.message(F.text & ~F.text.startswith("/"))
async def handle_prompt(message: Message):
    await generation_queue.put((message.chat.id, message.text))
    await message.answer("📥 Запрос добавлен в очередь")

@router.message(F.text == "/start")
async def start(message: Message):
    await message.answer(
        "👋 Отправь текст — я сгенерирую видео с помощью Kling"
    )

# =======================
# WEBHOOK
# =======================

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(status_code=403)

    update = await request.json()
    await dp.feed_raw_update(bot, update)
    return {"ok": True}

# =======================
# STARTUP
# =======================

@app.on_event("startup")
async def on_startup():
    global KLING_VERSION

    KLING_VERSION = await fetch_latest_version()
    logging.info(f"✅ Kling version: {KLING_VERSION}")

    asyncio.create_task(generation_worker())

    await bot.set_webhook(
        url=os.getenv("WEBHOOK_URL"),
        secret_token=WEBHOOK_SECRET,
    )

# =======================
# LOCAL RUN
# =======================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)