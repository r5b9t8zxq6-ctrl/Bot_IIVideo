import os
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Header, HTTPException
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.types import Message
from dotenv import load_dotenv
import replicate

# =======================
# ENV
# =======================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

if not all([BOT_TOKEN, WEBHOOK_URL, WEBHOOK_SECRET, REPLICATE_API_TOKEN]):
    raise RuntimeError("❌ Не заданы переменные окружения")

# =======================
# LOGGING
# =======================
logging.basicConfig(level=logging.INFO)

# =======================
# BOT
# =======================
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# =======================
# REPLICATE
# =======================
replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

KLING_VERSION = "5c7d5dc6dd8bf75c1acaa8565735e7986bc5b66206b55cca93cb72c9bf15ccaa"

# =======================
# QUEUE
# =======================
generation_queue: asyncio.Queue = asyncio.Queue()
MAX_RETRIES = 3
TIMEOUT = 600  # 10 минут

# =======================
# GENERATION WORKER
# =======================
async def generation_worker():
    logging.info("🚀 Generation worker started")

    while True:
        task = await generation_queue.get()
        chat_id, prompt = task

        try:
            await bot.send_message(chat_id, "🎬 Генерация началась...\nПрогресс: 0%")

            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    prediction = replicate_client.predictions.create(
                        version=KLING_VERSION,
                        input={
                            "prompt": prompt
                        }
                    )

                    # Ожидание с прогрессом
                    for i in range(TIMEOUT):
                        prediction.reload()

                        if prediction.status == "succeeded":
                            video_url = prediction.output
                            await bot.send_message(
                                chat_id,
                                f"✅ Готово!\n\n{video_url}"
                            )
                            break

                        if prediction.status == "failed":
                            raise RuntimeError("Generation failed")

                        progress = min(int((i / TIMEOUT) * 100), 99)
                        await bot.send_message(
                            chat_id,
                            f"⏳ Генерация...\nПрогресс: {progress}%",
                        )

                        await asyncio.sleep(1)
                    else:
                        raise TimeoutError("Timeout")

                    break

                except Exception as e:
                    logging.error(f"⚠️ Attempt {attempt} failed: {e}")

                    if attempt == MAX_RETRIES:
                        await bot.send_message(
                            chat_id,
                            "❌ Ошибка генерации.\nВозможно, модель недоступна или перегружена."
                        )

        finally:
            generation_queue.task_done()

# =======================
# HANDLERS
# =======================
@dp.message()
async def handle_message(message: Message):
    await generation_queue.put((message.chat.id, message.text))
    await message.answer("📥 Запрос добавлен в очередь")

# =======================
# FASTAPI
# =======================
@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.set_webhook(
        url=WEBHOOK_URL,
        secret_token=WEBHOOK_SECRET
    )
    asyncio.create_task(generation_worker())
    yield
    await bot.delete_webhook()

app = FastAPI(lifespan=lifespan)

@app.post("/")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(None)
):
    if x_telegram_bot_api_secret_token != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    update = types.Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}

@app.get("/")
async def health():
    return {"status": "ok"}