import os
import asyncio
from typing import Dict, Literal
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery,
)
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from asyncio import Queue
import replicate

# ================== CONFIG ==================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = os.getenv("WEBHOOK_URL") + WEBHOOK_PATH

KLING_MODEL = "kwaivgi/kling-v2.5-turbo-pro"

replicate_client = replicate.Client(api_token=os.getenv("REPLICATE_API_TOKEN"))

# ================== BOT ==================

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()

app = FastAPI()

# ================== STATE ==================

Mode = Literal["video", "image", "music", "gpt", "photo_video"]

user_modes: Dict[int, Mode] = {}
user_photos: Dict[int, str] = {}

queue: Queue = Queue()

# ================== UI ==================

def main_keyboard():
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
                InlineKeyboardButton(text="💬 GPT", callback_data="gpt"),
            ],
        ]
    )

# ================== COMMANDS ==================

@dp.message(F.text == "/start")
async def start(msg: Message):
    await msg.answer(
        "🔥 <b>AI Studio Bot</b>\n\nВыбери режим:",
        reply_markup=main_keyboard(),
    )

# ================== CALLBACKS ==================

@dp.callback_query()
async def set_mode(call: CallbackQuery):
    mode = call.data
    user_modes[call.from_user.id] = mode

    text = {
        "video": "🎬 Отправь описание видео",
        "image": "🖼 Отправь описание изображения",
        "photo_video": "📸 Отправь фото",
        "gpt": "💬 Напиши запрос",
    }.get(mode, "Ок")

    await call.message.answer(text)
    await call.answer()

# ================== PHOTO ==================

@dp.message(F.photo)
async def handle_photo(msg: Message):
    if user_modes.get(msg.from_user.id) != "photo_video":
        return

    photo = msg.photo[-1]
    file = await bot.get_file(photo.file_id)

    user_photos[msg.from_user.id] = file.file_path
    await msg.answer("✍️ Теперь отправь описание для видео")

# ================== TEXT ==================

@dp.message(F.text)
async def handle_text(msg: Message):
    mode = user_modes.get(msg.from_user.id)
    if not mode:
        await msg.answer("⚠️ Сначала выбери режим")
        return

    # PHOTO + TEXT → VIDEO
    if mode == "photo_video":
        photo_path = user_photos.get(msg.from_user.id)
        if not photo_path:
            await msg.answer("📸 Сначала отправь фото")
            return

        await queue.put(
            {
                "mode": "photo_video",
                "chat_id": msg.chat.id,
                "prompt": msg.text,
                "photo": photo_path,
            }
        )
        await msg.answer("🎬 Генерирую видео из фото...")
        return

    await queue.put(
        {
            "mode": mode,
            "chat_id": msg.chat.id,
            "prompt": msg.text,
        }
    )
    await msg.answer("⏳ Запрос принят")

# ================== WORKER ==================

async def worker():
    while True:
        task = await queue.get()

        try:
            if task["mode"] == "photo_video":
                photo_url = (
                    f"https://api.telegram.org/file/bot{BOT_TOKEN}/{task['photo']}"
                )

                output = replicate_client.run(
                    KLING_MODEL,
                    input={
                        "prompt": task["prompt"],
                        "image": photo_url,
                    },
                )

                await bot.send_video(task["chat_id"], output)

        except Exception as e:
            await bot.send_message(task["chat_id"], f"❌ Ошибка: {e}")

        queue.task_done()

# ================== WEBHOOK ==================

@app.on_event("startup")
async def on_startup():
    await bot.set_webhook(WEBHOOK_URL)
    asyncio.create_task(worker())

@app.post(WEBHOOK_PATH)
async def webhook(request: Request):
    update = await request.json()
    await dp.feed_raw_update(bot, update)
    return {"ok": True}