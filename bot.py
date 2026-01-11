import os
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Dict, Literal, TypedDict, Optional

from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

import replicate
from openai import OpenAI

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("ai-studio-bot")

# =========================================================
# CONFIG
# =========================================================

def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing env var: {name}")
    return value


BOT_TOKEN = require_env("BOT_TOKEN")
REPLICATE_API_TOKEN = require_env("REPLICATE_API_TOKEN")
OPENAI_API_KEY = require_env("OPENAI_API_KEY")
WEBHOOK_URL = require_env("WEBHOOK_URL")

WEBHOOK_PATH = "/webhook"
FULL_WEBHOOK_URL = f"{WEBHOOK_URL}{WEBHOOK_PATH}"

KLING_MODEL = "kwaivgi/kling-v2.5-turbo-pro"

# =========================================================
# CLIENTS
# =========================================================

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# =========================================================
# BOT
# =========================================================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

# =========================================================
# TYPES / STATE
# =========================================================

Mode = Literal[
    "video",
    "image",
    "photo_video",
    "gpt",
    "gpt_kling",
    "instagram",
    "insta_script",
    "insta_voice",
]


class TaskPayload(TypedDict):
    type: Mode
    chat_id: int
    prompt: Optional[str]
    topic: Optional[str]
    photo: Optional[str]


user_modes: Dict[int, Mode] = {}
user_photos: Dict[int, str] = {}

queue: asyncio.Queue[TaskPayload] = asyncio.Queue(maxsize=100)

# =========================================================
# UI
# =========================================================

def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎬 Видео", callback_data="video"),
                InlineKeyboardButton(text="🖼 Изображение", callback_data="image"),
            ],
            [InlineKeyboardButton(text="📸➡️🎬 Фото → Видео", callback_data="photo_video")],
            [InlineKeyboardButton(text="🧠➡️🎬 GPT → Видео", callback_data="gpt_kling")],
            [InlineKeyboardButton(text="📸 Instagram", callback_data="instagram")],
            [InlineKeyboardButton(text="💬 GPT", callback_data="gpt")],
        ]
    )


def instagram_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎬 Сценарий + субтитры", callback_data="insta_script")],
            [InlineKeyboardButton(text="🎙 Текст для озвучки", callback_data="insta_voice")],
        ]
    )

# =========================================================
# HANDLERS
# =========================================================

@dp.message(F.text == "/start")
async def start(msg: Message):
    await msg.answer("🔥 <b>AI Studio Bot</b>\n\nВыбери режим:", reply_markup=main_keyboard())


@dp.callback_query()
async def callbacks(call: CallbackQuery):
    user_modes[call.from_user.id] = call.data

    if call.data == "instagram":
        await call.message.answer("📸 Instagram режим:", reply_markup=instagram_keyboard())
    else:
        await call.message.answer("✍️ Отправь описание")

    await call.answer()


@dp.message(F.photo)
async def photo_handler(msg: Message):
    if user_modes.get(msg.from_user.id) != "photo_video":
        return

    file = await bot.get_file(msg.photo[-1].file_id)
    user_photos[msg.from_user.id] = file.file_path
    await msg.answer("✍️ Теперь отправь описание видео")


@dp.message(F.text)
async def text_handler(msg: Message):
    mode = user_modes.get(msg.from_user.id)
    if not mode:
        await msg.answer("⚠️ Выбери режим через /start")
        return

    task: TaskPayload = {
        "type": mode,
        "chat_id": msg.chat.id,
        "prompt": msg.text,
        "topic": msg.text,
        "photo": user_photos.get(msg.from_user.id),
    }

    try:
        queue.put_nowait(task)
    except asyncio.QueueFull:
        await msg.answer("⏳ Сервер перегружен")
        return

    await msg.answer("⏳ Запрос принят")

# =========================================================
# WORKER
# =========================================================

async def worker():
    logger.info("Worker started")
    while True:
        task = await queue.get()
        try:
            await asyncio.to_thread(
                replicate_client.run,
                KLING_MODEL,
                {"prompt": task.get("prompt")},
            )
            await bot.send_message(task["chat_id"], "✅ Готово")
        except Exception:
            logger.exception("Worker error")
            await bot.send_message(task["chat_id"], "❌ Ошибка")
        finally:
            queue.task_done()

# =========================================================
# FASTAPI LIFESPAN
# =========================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Startup")
    await bot.set_webhook(FULL_WEBHOOK_URL)
    worker_task = asyncio.create_task(worker())

    yield

    logger.info("Shutdown")
    worker_task.cancel()
    await bot.delete_webhook()


app = FastAPI(lifespan=lifespan)

@app.post(WEBHOOK_PATH)
async def webhook(request: Request):
    update = await request.json()
    await dp.feed_raw_update(bot, update)
    return {"ok": True}

# =========================================================
# ENTRYPOINT (если python bot.py)
# =========================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 10000)),
        log_level="info",
    )