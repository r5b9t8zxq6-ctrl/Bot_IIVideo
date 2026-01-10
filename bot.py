import os
import asyncio
import logging
from typing import Optional

import httpx
import replicate
from fastapi import FastAPI
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# ================== CONFIG ==================

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

KLING_MODEL = "kwaivgi/kling-v2.5-turbo-pro"
FALLBACK_KLING_VERSION = "5c7d5dc6dd8bf75c1acaa8565735e7986bc5b66206b55cca93cb72c9bf15ccaa"

MAX_RETRIES = 3
POLL_INTERVAL = 5  # seconds

# ============================================

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

app = FastAPI()

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

KLING_VERSION: Optional[str] = None
generation_queue: asyncio.Queue = asyncio.Queue()


# ================== VERSION FETCH ==================

async def fetch_latest_kling_version():
    global KLING_VERSION

    url = f"https://api.replicate.com/v1/models/{KLING_MODEL}"
    headers = {"Authorization": f"Token {REPLICATE_API_TOKEN}"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()

            KLING_VERSION = data["latest_version"]["id"]
            logging.info(f"✅ Kling latest_version loaded: {KLING_VERSION}")

    except Exception as e:
        KLING_VERSION = FALLBACK_KLING_VERSION
        logging.error(f"❌ Failed to fetch Kling version: {e}")
        logging.warning(f"⚠ Using fallback version: {KLING_VERSION}")


# ================== GENERATION WORKER ==================

async def generation_worker():
    logging.info("🚀 Generation worker started")

    while True:
        task = await generation_queue.get()
        chat_id, prompt = task

        try:
            await process_generation(chat_id, prompt)
        except Exception as e:
            await bot.send_message(chat_id, "❌ Ошибка генерации.\nМодель может быть перегружена.")
            logging.error(e)

        generation_queue.task_done()


async def process_generation(chat_id: int, prompt: str):
    if not KLING_VERSION:
        raise RuntimeError("Kling version not loaded")

    await bot.send_message(chat_id, "🎬 Генерация началась (0%)")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            prediction = replicate_client.predictions.create(
                version=KLING_VERSION,
                input={
                    "prompt": prompt,
                    "duration": 5,
                    "fps": 24
                }
            )

            last_percent = -1

            while prediction.status not in ("succeeded", "failed", "canceled"):
                await asyncio.sleep(POLL_INTERVAL)

                prediction = replicate_client.predictions.get(prediction.id)

                percent = estimate_progress(prediction)
                if percent != last_percent:
                    await bot.send_message(chat_id, f"⏳ Прогресс: {percent}%")
                    last_percent = percent

            if prediction.status == "succeeded":
                video_url = prediction.output[0]
                await bot.send_message(chat_id, f"✅ Готово!\n{video_url}")
                return

            raise RuntimeError("Prediction failed")

        except Exception as e:
            logging.warning(f"Retry {attempt}/{MAX_RETRIES}: {e}")
            if attempt == MAX_RETRIES:
                raise


def estimate_progress(prediction) -> int:
    if prediction.status == "starting":
        return 5
    if prediction.status == "processing":
        return 50
    if prediction.status == "succeeded":
        return 100
    return 0


# ================== BOT HANDLERS ==================

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "👋 Отправь текст — я сгенерирую видео через Kling.\n"
        "Очередь: 1 видео за раз."
    )


@dp.message()
async def handle_prompt(message: types.Message):
    await generation_queue.put((message.chat.id, message.text))
    await message.answer("📥 Запрос добавлен в очередь")


# ================== STARTUP ==================

@app.on_event("startup")
async def on_startup():
    await fetch_latest_kling_version()
    asyncio.create_task(generation_worker())


# ================== WEBHOOK HEALTHCHECK ==================

@app.get("/")
async def root():
    return {"status": "ok"}


# ================== ENTRY ==================

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())