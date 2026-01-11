import os
import asyncio
import logging
import tempfile
from typing import Any, Dict, Literal

import aiohttp
import replicate
from replicate.helpers import FileOutput
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties

from fastapi import FastAPI, Request, HTTPException
from openai import AsyncOpenAI
import uvicorn

# =========================
# LOGGING
# =========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-studio-bot")

# =========================
# ENV
# =========================
load_dotenv()

def require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"ENV {name} is required")
    return val

BOT_TOKEN = require_env("BOT_TOKEN")
REPLICATE_API_TOKEN = require_env("REPLICATE_API_TOKEN")
OPENAI_API_KEY = require_env("OPENAI_API_KEY")

BASE_URL = os.getenv("BASE_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

# =========================
# CLIENTS
# =========================
replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# =========================
# BOT
# =========================
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

# =========================
# MODELS
# =========================
Mode = Literal["video", "image", "music", "gpt"]

KLING_MODEL = "kwaivgi/kling-v2.5-turbo-pro"
IMAGE_MODEL = "bytedance/seedream-4"
MUSIC_MODEL = "meta/musicgen"

# =========================
# STATE
# =========================
user_modes: Dict[int, Mode] = {}

# =========================
# KEYBOARD
# =========================
def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎬 Видео", callback_data="video"),
                InlineKeyboardButton(text="🖼 Изображение", callback_data="image"),
            ],
            [
                InlineKeyboardButton(text="🎵 Музыка", callback_data="music"),
                InlineKeyboardButton(text="🤖 GPT", callback_data="gpt"),
            ],
        ]
    )

# =========================
# HELPERS
# =========================
def normalize_caption(text: str | None) -> str | None:
    if not text:
        return None
    return text[:1024]

async def download_to_file(url: str, suffix: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as r:
            if r.status != 200:
                raise RuntimeError("Failed download")
            data = await r.read()

    f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    f.write(data)
    f.close()
    return f.name

async def run_replicate(model: str, payload: Dict[str, Any]) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: replicate_client.run(model, input=payload),
    )

async def send_file(chat_id: int, path: str, kind: str, caption: str | None = None):
    file = FSInputFile(path)
    try:
        if kind == "video":
            await bot.send_video(chat_id, file, caption=normalize_caption(caption))
        elif kind == "image":
            await bot.send_photo(chat_id, file, caption=normalize_caption(caption))
        else:
            await bot.send_audio(chat_id, file)
    finally:
        os.remove(path)

# =========================
# HANDLERS
# =========================
@dp.message(CommandStart())
async def start(msg: Message):
    await msg.answer("🔥 <b>AI Studio Bot</b>\nВыбери режим:", reply_markup=main_keyboard())

@dp.callback_query(F.data.in_({"video", "image", "music", "gpt"}))
async def select_mode(cb: CallbackQuery):
    user_modes[cb.from_user.id] = cb.data  # type: ignore
    await cb.message.answer("✍️ Введите запрос:")

@dp.message(F.text)
async def handle_text(msg: Message):
    mode = user_modes.get(msg.from_user.id)
    if not mode:
        await msg.answer("Выбери режим 👇")
        return

    prompt = msg.text

    # photo + text => video logic
    if mode == "video" and "описание:" in prompt.lower():
        parts = prompt.split("Описание:", 1)
        prompt = f"Cinematic video. Scene: {parts[0].strip()}. Style: {parts[1].strip()}"

    if mode == "gpt":
        res = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
        )
        await msg.answer(res.choices[0].message.content)
        return

    await msg.answer("⏳ Генерация...")

    if mode == "image":
        out = await run_replicate(IMAGE_MODEL, {"prompt": prompt})
        url = out[0] if isinstance(out, list) else out
        path = await download_to_file(url, ".jpg")
        await send_file(msg.chat.id, path, "image", prompt)

    elif mode == "video":
        out = await run_replicate(KLING_MODEL, {"prompt": prompt})
        url = out if isinstance(out, str) else out[0]
        path = await download_to_file(url, ".mp4")
        await send_file(msg.chat.id, path, "video", prompt)

    elif mode == "music":
        out = await run_replicate(MUSIC_MODEL, {"prompt": prompt})
        url = out if isinstance(out, str) else out[0]
        path = await download_to_file(url, ".mp3")
        await send_file(msg.chat.id, path, "audio")

# =========================
# FASTAPI
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    if BASE_URL:
        await bot.set_webhook(f"{BASE_URL}/webhook", secret_token=WEBHOOK_SECRET)
    yield
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def webhook(req: Request):
    if WEBHOOK_SECRET:
        if req.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
            raise HTTPException(403)
    await dp.feed_raw_update(bot, await req.json())
    return {"ok": True}

if __name__ == "__main__":
    uvicorn.run("bot:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))