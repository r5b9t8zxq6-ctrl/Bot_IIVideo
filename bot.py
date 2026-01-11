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
from aiogram.client.default import DefaultBotProperties
from asyncio import Queue
import replicate
from openai import OpenAI

# ================== CONFIG ==================

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://bot-iivideo.onrender.com
WEBHOOK_PATH = "/webhook"
FULL_WEBHOOK_URL = WEBHOOK_URL + WEBHOOK_PATH

KLING_MODEL = "kwaivgi/kling-v2.5-turbo-pro"

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ================== BOT ==================

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

dp = Dispatcher()
app = FastAPI()

# ================== STATE ==================

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

def instagram_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎬 Сценарий + субтитры",
                    callback_data="insta_script",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎙 Текст для озвучки",
                    callback_data="insta_voice",
                )
            ],
        ]
    )

# ================== START ==================

@dp.message(F.text == "/start")
async def start(msg: Message):
    await msg.answer(
        "🔥 <b>AI Studio Bot</b>\n\nВыбери режим:",
        reply_markup=main_keyboard(),
    )

# ================== CALLBACKS ==================

@dp.callback_query()
async def callbacks(call: CallbackQuery):
    user_id = call.from_user.id
    data = call.data

    if data in {
        "video", "image", "photo_video",
        "gpt", "gpt_kling"
    }:
        user_modes[user_id] = data
        await call.message.answer("✍️ Отправь описание")
        await call.answer()
        return

    if data == "instagram":
        user_modes[user_id] = "instagram"
        await call.message.answer(
            "📸 Instagram режим:",
            reply_markup=instagram_keyboard(),
        )
        await call.answer()
        return

    if data in {"insta_script", "insta_voice"}:
        user_modes[user_id] = data
        await call.message.answer("✍️ Напиши тему Reels")
        await call.answer()
        return

# ================== PHOTO ==================

@dp.message(F.photo)
async def handle_photo(msg: Message):
    if user_modes.get(msg.from_user.id) != "photo_video":
        return

    file = await bot.get_file(msg.photo[-1].file_id)
    user_photos[msg.from_user.id] = file.file_path
    await msg.answer("✍️ Теперь отправь описание видео")

# ================== TEXT ==================

@dp.message(F.text)
async def handle_text(msg: Message):
    user_id = msg.from_user.id
    mode = user_modes.get(user_id)

    if not mode:
        await msg.answer("⚠️ Выбери режим через /start")
        return

    if mode == "photo_video":
        photo = user_photos.get(user_id)
        if not photo:
            await msg.answer("📸 Сначала отправь фото")
            return

        await queue.put({
            "type": "photo_video",
            "chat_id": msg.chat.id,
            "photo": photo,
            "prompt": msg.text,
        })
        await msg.answer("🎬 Генерирую видео...")
        return

    if mode in {"insta_script", "insta_voice"}:
        await queue.put({
            "type": mode,
            "chat_id": msg.chat.id,
            "topic": msg.text,
        })
        await msg.answer("🧠 GPT генерирует контент...")
        return

    await queue.put({
        "type": mode,
        "chat_id": msg.chat.id,
        "prompt": msg.text,
    })
    await msg.answer("⏳ Запрос принят")

# ================== WORKER ==================

async def worker():
    while True:
        task = await queue.get()
        try:
            if task["type"] == "photo_video":
                photo_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{task['photo']}"
                video = replicate_client.run(
                    KLING_MODEL,
                    input={"image": photo_url, "prompt": task["prompt"]},
                )
                await bot.send_video(task["chat_id"], video=video)

            elif task["type"] == "gpt_kling":
                gpt = openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "Создай сценарий и video prompt."},
                        {"role": "user", "content": task["prompt"]},
                    ],
                )
                prompt = gpt.choices[0].message.content
                video = replicate_client.run(KLING_MODEL, input={"prompt": prompt})
                await bot.send_video(task["chat_id"], video=video)

            elif task["type"] == "insta_script":
                gpt = openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "Сценарий + субтитры Reels"},
                        {"role": "user", "content": task["topic"]},
                    ],
                )
                await bot.send_message(task["chat_id"], gpt.choices[0].message.content)

            elif task["type"] == "insta_voice":
                gpt = openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "Текст для озвучки Reels"},
                        {"role": "user", "content": task["topic"]},
                    ],
                )
                await bot.send_message(task["chat_id"], gpt.choices[0].message.content)

        except Exception as e:
            await bot.send_message(task["chat_id"], f"❌ Ошибка: {e}")

        queue.task_done()

# ================== WEBHOOK ==================

@app.on_event("startup")
async def startup():
    print("🚀 STARTUP")
    await bot.set_webhook(FULL_WEBHOOK_URL)
    asyncio.create_task(worker())

@app.on_event("shutdown")
async def shutdown():
    await bot.delete_webhook()

@app.post(WEBHOOK_PATH)
async def webhook(request: Request):
    update = await request.json()
    print("📩 INCOMING UPDATE:", update)
    await dp.feed_raw_update(bot, update)
    return {"ok": True}