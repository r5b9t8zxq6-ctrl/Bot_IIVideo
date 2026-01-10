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

# =======================
# ENV
# =======================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 10000))

MODEL_SLUG = "kwaivgi/kling-v2.5-turbo-pro"

MAX_RETRIES = 3
POLL_INTERVAL = 5

if not all([BOT_TOKEN, REPLICATE_API_TOKEN, WEBHOOK_SECRET, WEBHOOK_URL]):
    raise RuntimeError("❌ Missing env variables")

# =======================
# LOGGING
# =======================

logging.basicConfig(level=logging.INFO)

# =======================
# BOT / FASTAPI
# =======================

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

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
# GET LATEST VERSION (SDK — ПРАВИЛЬНО)
# =======================

def get_latest_kling_version() -> str:
    model = replicate_client.models.get(MODEL_SLUG)
    return model.latest_version.id

# =======================
# WORKER
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
                "❌ Ошибка генерации.\nМодель перегружена или временно недоступна."
            )
        generation_queue.task_done()

# =======================
# GENERATION
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

@router.message(F.text == "/start")
async def start(message: Message):
    await message.answer("👋 Отправь текст — я сгенерирую видео через Kling")

@router.message(F.text & ~F.text.startswith("/"))
async def handle_prompt(message: Message):
    await generation_queue.put((message.chat.id, message.text))
    await message.answer("📥 Запрос добавлен в очередь")

# =======================
# WEBHOOK
# =======================

@app.post("/")
async def telegram_webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(status_code=403)

    await dp.feed_raw_update(bot, await request.json())
    return {"ok": True}

# =======================
# LIFESPAN (НЕ deprecated)
# =======================

@app.on_event("startup")
async def startup():
    global KLING_VERSION

    try:
        KLING_VERSION = get_latest_kling_version()
        logging.info(f"✅ Kling version: {KLING_VERSION}")
    except Exception as e:
        logging.exception("❌ Failed to fetch Kling version")
        raise RuntimeError("Kling model unavailable")

    asyncio.create_task(generation_worker())

    await bot.set_webhook(
        url=WEBHOOK_URL,
        secret_token=WEBHOOK_SECRET,
    )

# =======================
# LOCAL
# =======================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)