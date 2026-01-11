import os
import asyncio
import logging
from typing import Dict, Literal, TypedDict, Optional

from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
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
# CONFIG VALIDATION
# =========================================================

def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
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
app = FastAPI()

# =========================================================
# TYPES
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


# =========================================================
# STATE (bounded & safe)
# =========================================================

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
            [
                InlineKeyboardButton(text="📸➡️🎬 Фото → Видео", callback_data="photo_video"),
            ],
            [
                InlineKeyboardButton(text="🧠➡️🎬 GPT → Видео", callback_data="gpt_kling"),
            ],
            [
                InlineKeyboardButton(text="📸 Instagram", callback_data="instagram"),
            ],
            [
                InlineKeyboardButton(text="💬 GPT", callback_data="gpt"),
            ],
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
async def start_handler(msg: Message) -> None:
    await msg.answer("🔥 <b>AI Studio Bot</b>\n\nВыбери режим:", reply_markup=main_keyboard())


@dp.callback_query()
async def callback_handler(call: CallbackQuery) -> None:
    user_id = call.from_user.id
    mode = call.data

    user_modes[user_id] = mode  # validated by UI

    if mode == "instagram":
        await call.message.answer("📸 Instagram режим:", reply_markup=instagram_keyboard())
    else:
        await call.message.answer("✍️ Отправь описание")

    await call.answer()


@dp.message(F.photo)
async def photo_handler(msg: Message) -> None:
    if user_modes.get(msg.from_user.id) != "photo_video":
        return

    file = await bot.get_file(msg.photo[-1].file_id)
    user_photos[msg.from_user.id] = file.file_path
    await msg.answer("✍️ Теперь отправь описание видео")


@dp.message(F.text)
async def text_handler(msg: Message) -> None:
    user_id = msg.from_user.id
    mode = user_modes.get(user_id)

    if not mode:
        await msg.answer("⚠️ Выбери режим через /start")
        return

    payload: TaskPayload = {
        "type": mode,
        "chat_id": msg.chat.id,
        "prompt": None,
        "topic": None,
        "photo": None,
    }

    if mode == "photo_video":
        payload["photo"] = user_photos.get(user_id)
        payload["prompt"] = msg.text
    elif mode in {"insta_script", "insta_voice"}:
        payload["topic"] = msg.text
    else:
        payload["prompt"] = msg.text

    try:
        queue.put_nowait(payload)
    except asyncio.QueueFull:
        await msg.answer("⏳ Сервер перегружен, попробуй позже")
        return

    await msg.answer("⏳ Запрос принят")

# =========================================================
# WORKER
# =========================================================

async def worker() -> None:
    logger.info("Worker started")

    while True:
        task = await queue.get()
        try:
            await process_task(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Task failed")
            await bot.send_message(task["chat_id"], "❌ Внутренняя ошибка")
        finally:
            queue.task_done()


async def process_task(task: TaskPayload) -> None:
    t = task["type"]

    if t == "photo_video":
        photo_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{task['photo']}"
        video = await asyncio.to_thread(
            replicate_client.run,
            KLING_MODEL,
            {"image": photo_url, "prompt": task["prompt"]},
        )
        await bot.send_video(task["chat_id"], video)

    elif t == "gpt_kling":
        gpt = await asyncio.to_thread(
            openai_client.chat.completions.create,
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Создай сценарий и video prompt."},
                {"role": "user", "content": task["prompt"]},
            ],
        )
        prompt = gpt.choices[0].message.content
        video = await asyncio.to_thread(
            replicate_client.run,
            KLING_MODEL,
            {"prompt": prompt},
        )
        await bot.send_video(task["chat_id"], video)

    elif t in {"insta_script", "insta_voice"}:
        gpt = await asyncio.to_thread(
            openai_client.chat.completions.create,
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Контент для Reels"},
                {"role": "user", "content": task["topic"]},
            ],
        )
        await bot.send_message(task["chat_id"], gpt.choices[0].message.content)

# =========================================================
# FASTAPI LIFECYCLE
# =========================================================

@app.on_event("startup")
async def startup() -> None:
    logger.info("Startup")
    await bot.set_webhook(FULL_WEBHOOK_URL)
    app.state.worker_task = asyncio.create_task(worker())


@app.on_event("shutdown")
async def shutdown() -> None:
    logger.info("Shutdown")
    app.state.worker_task.cancel()
    await bot.delete_webhook()


@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    update = await request.json()
    await dp.feed_raw_update(bot, update)
    return {"ok": True}