import os
import asyncio
import uuid
import tempfile
import hashlib
from typing import Dict, Any

import aiohttp
import replicate
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile
)
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart

from fastapi import FastAPI, Request, HTTPException
from openai import AsyncOpenAI

# =========================
# ENV
# =========================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
BASE_URL = os.getenv("BASE_URL")

replicate.Client(api_token=REPLICATE_API_TOKEN)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# =========================
# AI MODELS
# =========================
KLING_MODEL = "kwaivgi/kling-v2.5-turbo-pro"
IMAGE_MODEL = "bytedance/seedream-4"
MUSIC_MODEL = "meta/musicgen:671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb"

# =========================
# BOT
# =========================
bot = Bot(BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()
app = FastAPI()

# очередь задач
queue: asyncio.Queue = asyncio.Queue()
tasks: Dict[str, Dict[str, Any]] = {}

# =========================
# KEYBOARD
# =========================
def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎬 Видео", callback_data="video"),
            InlineKeyboardButton(text="🖼 Изображение", callback_data="image"),
        ],
        [
            InlineKeyboardButton(text="🎵 Музыка", callback_data="music"),
            InlineKeyboardButton(text="🤖 GPT-помощь", callback_data="gpt"),
        ]
    ])

# =========================
# START
# =========================
@dp.message(CommandStart())
async def start(msg: Message):
    await msg.answer(
        "🔥 <b>AI Studio Bot</b>\n\n"
        "Выбери, что хочешь создать:",
        reply_markup=main_keyboard()
    )

# =========================
# CALLBACKS
# =========================
@dp.callback_query(F.data == "video")
async def cb_video(cb: CallbackQuery):
    await cb.message.answer("✍️ Опиши видео (Kling):")
    tasks[cb.from_user.id] = {"mode": "video"}

@dp.callback_query(F.data == "image")
async def cb_image(cb: CallbackQuery):
    await cb.message.answer("✍️ Опиши изображение:")
    tasks[cb.from_user.id] = {"mode": "image"}

@dp.callback_query(F.data == "music")
async def cb_music(cb: CallbackQuery):
    await cb.message.answer("🎵 Опиши музыку (жанр, настроение):")
    tasks[cb.from_user.id] = {"mode": "music"}

@dp.callback_query(F.data == "gpt")
async def cb_gpt(cb: CallbackQuery):
    await cb.message.answer("🤖 Задай вопрос или попроси помощь:")
    tasks[cb.from_user.id] = {"mode": "gpt"}

# =========================
# TEXT HANDLER
# =========================
@dp.message(F.text)
async def handle_text(msg: Message):
    state = tasks.get(msg.from_user.id)
    if not state:
        return

    mode = state["mode"]
    prompt = msg.text

    if mode == "video":
        job_id = str(uuid.uuid4())
        await queue.put(("video", job_id, msg.chat.id, prompt))
        await msg.answer("⏳ Видео добавлено в очередь…")

    elif mode == "image":
        job_id = str(uuid.uuid4())
        await queue.put(("image", job_id, msg.chat.id, prompt))
        await msg.answer("⏳ Генерация изображения…")

    elif mode == "music":
        job_id = str(uuid.uuid4())
        await queue.put(("music", job_id, msg.chat.id, prompt))
        await msg.answer("⏳ Генерация музыки…")

    elif mode == "gpt":
        completion = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Ты профессиональный AI-ассистент."},
                {"role": "user", "content": prompt}
            ]
        )
        await msg.answer(completion.choices[0].message.content)

    tasks.pop(msg.from_user.id, None)

# =========================
# WORKER
# =========================
async def worker():
    while True:
        job = await queue.get()
        kind, job_id, chat_id, prompt = job

        try:
            if kind == "video":
                output = replicate.run(KLING_MODEL, input={
                    "prompt": f"Cinematic, ultra realistic, 4k: {prompt}"
                })
                await send_file(chat_id, output, "mp4")

            elif kind == "image":
                output = replicate.run(IMAGE_MODEL, input={
                    "prompt": f"Ultra detailed, professional photography: {prompt}"
                })
                await send_file(chat_id, output[0], "jpg")

            elif kind == "music":
                output = replicate.run(MUSIC_MODEL, input={
                    "prompt": f"Professional cinematic music: {prompt}",
                    "output_format": "mp3"
                })
                await send_file(chat_id, output, "mp3")

        except Exception as e:
            await bot.send_message(chat_id, f"❌ Ошибка: {e}")

        queue.task_done()

# =========================
# SEND FILE (FSInputFile)
# =========================
async def send_file(chat_id: int, output, ext: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(output.url) as resp:
            data = await resp.read()

    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as f:
        f.write(data)
        path = f.name

    if ext == "mp4":
        await bot.send_video(chat_id, FSInputFile(path))
    elif ext == "jpg":
        await bot.send_photo(chat_id, FSInputFile(path))
    elif ext == "mp3":
        await bot.send_audio(chat_id, FSInputFile(path))

    os.remove(path)

# =========================
# WEBHOOK
# =========================
@app.post("/webhook")
async def telegram_webhook(req: Request):
    body = await req.body()
    signature = req.headers.get("X-Telegram-Bot-Api-Secret-Token")

    if signature != WEBHOOK_SECRET:
        raise HTTPException(status_code=403)

    await dp.feed_raw_update(bot, body)
    return {"ok": True}

# =========================
# STARTUP
# =========================
@app.on_event("startup")
async def on_startup():
    await bot.set_webhook(
        f"{BASE_URL}/webhook",
        secret_token=WEBHOOK_SECRET
    )
    asyncio.create_task(worker())