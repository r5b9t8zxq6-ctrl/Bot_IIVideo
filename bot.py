import os
import asyncio
import logging
from typing import Dict

from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

import replicate
from dotenv import load_dotenv

# ================== CONFIG ==================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

KLING_VERSION = "5c7d5dc6dd8bf75c1acaa8565735e7986bc5b66206b55cca93cb72c9bf15ccaa"

GEN_TIMEOUT = 300        # максимум 5 минут
RETRY_COUNT = 2
QUEUE_LIMIT = 10

logging.basicConfig(level=logging.INFO)

# ================== BOT ==================
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

# ================== FASTAPI ==================
app = FastAPI()

# ================== QUEUE ==================
generation_queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_LIMIT)
active_jobs: Dict[int, asyncio.Event] = {}

# ================== UTILS ==================
async def safe_sleep(seconds: int):
    try:
        await asyncio.sleep(seconds)
    except asyncio.CancelledError:
        pass

# ================== GENERATION WORKER ==================
async def generation_worker():
    logging.info("Generation worker started")

    while True:
        message, prompt = await generation_queue.get()
        chat_id = message.chat.id

        try:
            await bot.send_message(chat_id, "🎬 Генерация началась…\n0%")

            prediction = None

            for attempt in range(RETRY_COUNT + 1):
                try:
                    prediction = replicate_client.predictions.create(
                        version=KLING_VERSION,
                        input={
                            "prompt": prompt,
                            "duration": 5,
                            "fps": 24
                        }
                    )
                    break
                except Exception as e:
                    logging.error(f"Replicate error: {e}")
                    if attempt >= RETRY_COUNT:
                        raise
                    await safe_sleep(3)

            start_time = asyncio.get_event_loop().time()

            progress_msg = await bot.send_message(chat_id, "⏳ Прогресс: 5%")

            last_percent = 5

            while prediction.status not in ("succeeded", "failed"):
                elapsed = asyncio.get_event_loop().time() - start_time

                if elapsed > GEN_TIMEOUT:
                    raise TimeoutError("Generation timeout")

                prediction.reload()

                percent = min(95, int((elapsed / GEN_TIMEOUT) * 100))
                if percent - last_percent >= 5:
                    last_percent = percent
                    await progress_msg.edit_text(f"⏳ Прогресс: {percent}%")

                await safe_sleep(2)

            if prediction.status == "failed":
                raise RuntimeError("Generation failed")

            await progress_msg.edit_text("✅ Готово! 100%")

            video_url = prediction.output

            await bot.send_video(
                chat_id=chat_id,
                video=video_url,
                caption="🎥 Видео сгенерировано"
            )

        except Exception as e:
            logging.exception(e)
            await bot.send_message(
                chat_id,
                "❌ Ошибка генерации.\nВозможно, модель недоступна или перегружена."
            )

        finally:
            generation_queue.task_done()

# ================== HANDLERS ==================
@dp.message()
async def handle_text(message: Message):
    if generation_queue.full():
        await message.answer("⛔ Очередь переполнена, попробуй позже")
        return

    prompt = message.text.strip()

    await generation_queue.put((message, prompt))
    await message.answer("📥 Запрос добавлен в очередь")

# ================== WEBHOOK ==================
@app.post("/")
async def telegram_webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(status_code=403)

    update = types.Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}

# ================== STARTUP ==================
@app.on_event("startup")
async def on_startup():
    await bot.set_webhook(
        url=WEBHOOK_URL,
        secret_token=WEBHOOK_SECRET
    )
    asyncio.create_task(generation_worker())

@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()