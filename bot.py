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
BASE_URL = os.getenv("BASE_URL")  # https://xxx.onrender.com

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set")

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)
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
    async with aiohttp.ClientSession() as session:
        while True:
            mode, chat_id, prompt = await queue.get()
            try:
                if mode == "video":
                    output = replicate_client.run(
                        KLING_MODEL,
                        input={"prompt": prompt}
                    )
                    url = extract_url(output)
                    await send_file(chat_id, url, "mp4", session)

                elif mode == "image":
                    output = replicate_client.run(
                        IMAGE_MODEL,
                        input={"prompt": prompt}
                    )
                    url = extract_url(output)
                    await send_file(chat_id, url, "jpg", session)

                elif mode == "music":
                    output = replicate_client.run(
                        MUSIC_MODEL,
                        input={"prompt": prompt, "output_format": "mp3"}
                    )
                    url = extract_url(output)
                    await send_file(chat_id, url, "mp3", session)

                elif mode == "gpt":
                    res = await openai_client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": prompt}]
                    )
                    await bot.send_message(
                        chat_id,
                        res.choices[0].message.content
                    )

            except Exception as e:
                await bot.send_message(chat_id, f"❌ Ошибка: {e}")

            queue.task_done()

# =========================
# HELPERS
# =========================
def extract_url(output) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, list) and output:
        return output[0]
    if hasattr(output, "url"):
        return output.url
    raise ValueError("Не удалось извлечь URL из ответа модели")

async def send_file(chat_id: int, url: str, ext: str, session: aiohttp.ClientSession):
    async with session.get(url) as r:
        if r.status != 200:
            raise RuntimeError("Ошибка загрузки файла")
        data = await r.read()

    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as f:
        f.write(data)
        path = f.name

    try:
        if ext == "mp4":
            await bot.send_video(chat_id, FSInputFile(path))
        elif ext == "jpg":
            await bot.send_photo(chat_id, FSInputFile(path))
        elif ext == "mp3":
            await bot.send_audio(chat_id, FSInputFile(path))
    finally:
        os.remove(path)

# =========================
# FASTAPI
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    if BASE_URL and BASE_URL.startswith("https://"):
        await bot.set_webhook(
            f"{BASE_URL}/webhook",
            secret_token=WEBHOOK_SECRET
        )
        print("✅ Webhook установлен")
    else:
        print("⚠️ BASE_URL не задан или не https — webhook пропущен")

    asyncio.create_task(worker())
    yield
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def telegram_webhook(req: Request):
    if WEBHOOK_SECRET:
        if req.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
            raise HTTPException(status_code=403)

    update = await req.json()
    await dp.feed_raw_update(bot, update)
    return {"ok": True}

# =========================
# RUN
# =========================
if __name__ == "__main__":
    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        log_level="info"
    )