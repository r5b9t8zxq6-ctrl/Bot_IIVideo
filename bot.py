import os
import asyncio
import logging
from typing import Any

import replicate
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, Update
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# ================== CONFIG ==================

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
PORT = int(os.getenv("PORT", 10000))

replicate.Client(api_token=REPLICATE_API_TOKEN)

logging.basicConfig(level=logging.INFO)

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
GENERATION_TIMEOUT = 120        # максимум ожидания генерации
POLL_INTERVAL = 3               # секунд между запросами
MAX_POLLS = GENERATION_TIMEOUT // POLL_INTERVAL


# ================== HELPERS ==================

def extract_video_url(output: Any) -> str:
    """
    Универсальный парсер Kling / Replicate output
    """
    if not output:
        raise RuntimeError("Empty output")

    # строка
    if isinstance(output, str) and output.startswith("http"):
        return output

    # список
    if isinstance(output, list):
        for item in output:
            try:
                return extract_video_url(item)
            except Exception:
                pass

    # dict
    if isinstance(output, dict):
        for key in ("video", "url", "output", "file"):
            if key in output:
                return extract_video_url(output[key])

    raise RuntimeError(f"Unknown Kling output format: {output}")


async def wait_for_prediction(prediction):
    """
    Polling Replicate с тайм-аутом
    """
    for _ in range(MAX_POLLS):
        prediction.reload()
        if prediction.status == "succeeded":
            return prediction
        if prediction.status == "failed":
            raise RuntimeError("Generation failed")
        await asyncio.sleep(POLL_INTERVAL)

    raise TimeoutError("Generation timeout")


# ================== WORKER ==================

async def generation_worker():
    while True:
        message, prompt = await generation_queue.get()
        try:
            await message.answer("🎬 Генерирую видео, подожди...")

            prediction = replicate.predictions.create(
                version="kling-ai/kling-video:latest",
                input={
                    "prompt": prompt,
                },
            )

            prediction = await wait_for_prediction(prediction)

            video_url = extract_video_url(prediction.output)

            await message.answer_video(video_url)

        except TimeoutError:
            await message.answer("⏳ Время ожидания вышло. Попробуй ещё раз.")
        except Exception as e:
            logging.exception(e)
            await message.answer("❌ Ошибка генерации.")
        finally:
            generation_queue.task_done()


# ================== HANDLERS ==================

@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Привет 👋\n"
        "Отправь текст — я сгенерирую видео.\n"
        "⚠️ Генерации идут по очереди."
    )


@router.message(F.text)
async def generate_video(message: Message):
    await generation_queue.put((message, message.text))
    await message.answer("📥 Запрос добавлен в очередь.")


# ================== FASTAPI ==================

app = FastAPI()


@app.on_event("startup")
async def on_startup():
    asyncio.create_task(generation_worker())
    logging.info("Worker started")


@app.post("/")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}


@app.get("/ping")
async def ping():
    return {"status": "ok"}