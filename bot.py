import os
import asyncio
import logging
from typing import Any, AsyncIterator

import replicate
import uvicorn
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, Update
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# ================== CONFIG ==================

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
KLING_VERSION = os.getenv("KLING_VERSION")  # ОБЯЗАТЕЛЬНО
PORT = int(os.getenv("PORT", 10000))

logging.basicConfig(level=logging.INFO)

if not KLING_VERSION:
    raise RuntimeError("KLING_VERSION env variable is required")

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

# ================== BOT ==================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

dp = Dispatcher()
router = Router()
dp.include_router(router)

# ================== QUEUE ==================

generation_queue: asyncio.Queue = asyncio.Queue()

GENERATION_TIMEOUT = 180
POLL_INTERVAL = 3
MAX_POLLS = GENERATION_TIMEOUT // POLL_INTERVAL

# ================== HELPERS ==================

def extract_video_url(output: Any) -> str:
    if not output:
        raise RuntimeError("Empty output")

    if isinstance(output, str) and output.startswith("http"):
        return output

    if isinstance(output, list):
        for item in output:
            try:
                return extract_video_url(item)
            except Exception:
                pass

    if isinstance(output, dict):
        for value in output.values():
            try:
                return extract_video_url(value)
            except Exception:
                pass

    raise RuntimeError(f"Unknown output format: {output}")

async def wait_with_progress(prediction, progress_message: Message):
    for step in range(1, MAX_POLLS + 1):
        prediction.reload()

        percent = min(int(step / MAX_POLLS * 100), 99)

        try:
            await progress_message.edit_text(
                f"🎬 Генерация видео\n"
                f"⏳ Прогресс: <b>{percent}%</b>"
            )
        except Exception:
            pass

        if prediction.status == "succeeded":
            await progress_message.edit_text(
                "🎬 Готово!\n⏳ Прогресс: <b>100%</b>"
            )
            return prediction

        if prediction.status == "failed":
            raise RuntimeError("Generation failed")

        await asyncio.sleep(POLL_INTERVAL)

    raise TimeoutError("Generation timeout")

# ================== WORKER ==================

async def generation_worker():
    logging.info("Generation worker started")

    while True:
        message, prompt = await generation_queue.get()

        try:
            progress_message = await message.answer(
                "🎬 Генерация видео\n⏳ Прогресс: <b>0%</b>"
            )

            prediction = replicate_client.predictions.create(
                version=KLING_VERSION,
                input={"prompt": prompt},
            )

            prediction = await wait_with_progress(prediction, progress_message)

            video_url = extract_video_url(prediction.output)
            await message.answer_video(video_url)

        except Exception as e:
            logging.exception(e)
            await message.answer(
                "❌ Ошибка генерации.\n"
                "Возможно, модель недоступна или перегружена."
            )

        finally:
            generation_queue.task_done()

# ================== HANDLERS ==================

@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Привет!\n\n"
        "Отправь текст — я сгенерирую видео.\n"
        "🎬 Генерации идут по очереди\n"
        "⏳ Прогресс показывается в процентах"
    )

@router.message(F.text)
async def generate(message: Message):
    await generation_queue.put((message, message.text))
    await message.answer("📥 Запрос добавлен в очередь")

# ================== FASTAPI ==================

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    asyncio.create_task(generation_worker())
    yield

app = FastAPI(lifespan=lifespan)

@app.post("/")
async def webhook(request: Request):
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}

@app.get("/ping")
async def ping():
    return {"status": "ok"}

# ================== RUN ==================

if __name__ == "__main__":
    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=PORT,
        log_level="info",
    )