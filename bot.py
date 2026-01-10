import os
import asyncio
import tempfile
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
from aiogram.client.default import DefaultBotProperties

from fastapi import FastAPI, Request, HTTPException
from openai import AsyncOpenAI
import uvicorn
from contextlib import asynccontextmanager

# =========================
# ENV
# =========================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
BASE_URL = os.getenv("BASE_URL")  # https://your-app.onrender.com

replicate.Client(api_token=REPLICATE_API_TOKEN)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# =========================
# BOT
# =========================
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# =========================
# MODELS
# =========================
KLING_MODEL = "kwaivgi/kling-v2.5-turbo-pro"
IMAGE_MODEL = "bytedance/seedream-4"
MUSIC_MODEL = "meta/musicgen:671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb"

queue: asyncio.Queue = asyncio.Queue()
states: Dict[int, Dict[str, Any]] = {}

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
            InlineKeyboardButton(text="🤖 GPT", callback_data="gpt"),
        ]
    ])

# =========================
# HANDLERS
# =========================
@dp.message(CommandStart())
async def start(msg: Message):
    await msg.answer(
        "🔥 <b>AI Studio Bot</b>\n\nВыбери режим:",
        reply_markup=main_keyboard()
    )

@dp.callback_query(F.data.in_({"video", "image", "music", "gpt"}))
async def select_mode(cb: CallbackQuery):
    states[cb.from_user.id] = {"mode": cb.data}
    await cb.message.answer("✍️ Введите запрос:")

@dp.message(F.text)
async def handle_text(msg: Message):
    state = states.pop(msg.from_user.id, None)
    if not state:
        return

    await queue.put((state["mode"], msg.chat.id, msg.text))
    await msg.answer("⏳ Запрос добавлен в очередь...")

# =========================
# WORKER
# =========================
async def worker():
    while True:
        mode, chat_id, prompt = await queue.get()
        try:
            if mode == "video":
                output = replicate.run(KLING_MODEL, input={"prompt": prompt})
                await send_file(chat_id, output, "mp4")

            elif mode == "image":
                output = replicate.run(IMAGE_MODEL, input={"prompt": prompt})
                await send_file(chat_id, output[0], "jpg")

            elif mode == "music":
                output = replicate.run(MUSIC_MODEL, input={
                    "prompt": prompt,
                    "output_format": "mp3"
                })
                await send_file(chat_id, output, "mp3")

            elif mode == "gpt":
                res = await openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}]
                )
                await bot.send_message(chat_id, res.choices[0].message.content)

        except Exception as e:
            await bot.send_message(chat_id, f"❌ Ошибка: {e}")

        queue.task_done()

# =========================
# SEND FILE
# =========================
async def send_file(chat_id: int, output, ext: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(output.url) as r:
            data = await r.read()

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
# FASTAPI (LIFESPAN)
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.set_webhook(
        f"{BASE_URL}/webhook",
        secret_token=WEBHOOK_SECRET
    )
    asyncio.create_task(worker())
    yield
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def telegram_webhook(req: Request):
    if req.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(status_code=403)

    update = await req.json()
    await dp.feed_raw_update(bot, update)
    return {"ok": True}

# =========================
# RUN SERVER
# =========================
if __name__ == "__main__":
    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        log_level="info"
    )