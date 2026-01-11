# ===========================
# bot.py — Production Ready (FIXED)
# ===========================
import os
import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Literal, List, Optional

import aiohttp
import replicate
from replicate.helpers import File, FileOutput
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties

from fastapi import FastAPI, Request, HTTPException
from openai import AsyncOpenAI
import uvicorn

# =====================================================
# LOGGING
# =====================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("ai-studio-bot")

# =====================================================
# ENV
# =====================================================
load_dotenv()

def require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"ENV {name} is required")
    return v

BOT_TOKEN = require_env("BOT_TOKEN")
REPLICATE_API_TOKEN = require_env("REPLICATE_API_TOKEN")
OPENAI_API_KEY = require_env("OPENAI_API_KEY")

BASE_URL = os.getenv("BASE_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

QUEUE_MAXSIZE = int(os.getenv("QUEUE_MAXSIZE", "100"))
WORKERS = int(os.getenv("WORKERS", "2"))

# =====================================================
# CLIENTS
# =====================================================
replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

replicate_semaphore = asyncio.Semaphore(2)

# =====================================================
# BOT
# =====================================================
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

# =====================================================
# CONSTANTS
# =====================================================
Mode = Literal["video", "image", "music", "gpt"]

KLING_MODEL = "kwaivgi/kling-v2.5-turbo-pro"
IMAGE_MODEL = "bytedance/seedream-4"
MUSIC_MODEL = "meta/musicgen:671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb"

# =====================================================
# SESSION
# =====================================================
@dataclass
class UserSession:
    mode: Optional[Mode] = None
    images: List[bytes] = field(default_factory=list)
    style: str = "cinematic"
    duration: int = 5

sessions: Dict[int, UserSession] = {}

def get_session(uid: int) -> UserSession:
    return sessions.setdefault(uid, UserSession())

# =====================================================
# TASK (SNAPSHOT)
# =====================================================
@dataclass(slots=True)
class Task:
    mode: Mode
    chat_id: int
    prompt: str
    images: List[bytes]
    style: str
    duration: int

queue: asyncio.Queue[Task] = asyncio.Queue(maxsize=QUEUE_MAXSIZE)

# =====================================================
# KEYBOARDS
# =====================================================
def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Видео", callback_data="video"),
         InlineKeyboardButton(text="🖼 Изображение", callback_data="image")],
        [InlineKeyboardButton(text="🎵 Музыка", callback_data="music"),
         InlineKeyboardButton(text="🤖 GPT", callback_data="gpt")],
    ])

def style_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Cinematic", callback_data="style_cinematic"),
         InlineKeyboardButton(text="🎨 Anime", callback_data="style_anime")],
        [InlineKeyboardButton(text="🤖 Cyberpunk", callback_data="style_cyberpunk"),
         InlineKeyboardButton(text="📸 Realistic", callback_data="style_realistic")],
    ])

def duration_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏱ 5 сек", callback_data="dur_5"),
         InlineKeyboardButton(text="⏱ 10 сек", callback_data="dur_10"),
         InlineKeyboardButton(text="⏱ 15 сек", callback_data="dur_15")],
    ])

# =====================================================
# HANDLERS
# =====================================================
@dp.message(CommandStart())
async def start(msg: Message):
    sessions.pop(msg.from_user.id, None)
    await msg.answer("🔥 <b>AI Studio Bot</b>\n\nВыбери режим:", reply_markup=main_keyboard())

@dp.callback_query(F.data.in_({"video", "image", "music", "gpt"}))
async def select_mode(cb: CallbackQuery):
    s = get_session(cb.from_user.id)
    s.mode = cb.data  # type: ignore
    s.images.clear()
    await cb.message.answer("📸 Отправь 1–5 фото" if cb.data == "video" else "✍️ Введите запрос")

@dp.message(F.photo)
async def handle_photo(msg: Message):
    s = get_session(msg.from_user.id)
    if s.mode != "video":
        return
    if len(s.images) >= 5:
        await msg.answer("⚠️ Максимум 5 фото")
        return
    file = await bot.get_file(msg.photo[-1].file_id)
    data = await bot.download_file(file.file_path)
    s.images.append(data.read())
    await msg.answer(f"📸 Фото добавлено ({len(s.images)}/5)", reply_markup=style_keyboard())

@dp.callback_query(F.data.startswith("style_"))
async def set_style(cb: CallbackQuery):
    get_session(cb.from_user.id).style = cb.data.replace("style_", "")
    await cb.message.answer("⏱ Выбери длительность", reply_markup=duration_keyboard())

@dp.callback_query(F.data.startswith("dur_"))
async def set_duration(cb: CallbackQuery):
    get_session(cb.from_user.id).duration = int(cb.data.replace("dur_", ""))
    await cb.message.answer("✍️ Теперь введи текст")

@dp.message(F.text)
async def handle_text(msg: Message):
    s = get_session(msg.from_user.id)
    if not s.mode:
        await msg.answer("⚠️ Сначала выбери режим")
        return
    await queue.put(Task(
        mode=s.mode,
        chat_id=msg.chat.id,
        prompt=msg.text,
        images=list(s.images),
        style=s.style,
        duration=s.duration,
    ))
    await msg.answer("⏳ Запрос принят")

# =====================================================
# REPLICATE WRAPPER
# =====================================================
async def run_replicate(model: str, payload: Dict[str, Any]) -> Any:
    async with replicate_semaphore:
        return await asyncio.wait_for(
            asyncio.to_thread(replicate_client.run, model, input=payload),
            timeout=420,
        )

# =====================================================
# WORKER
# =====================================================
async def worker(worker_id: int, http: aiohttp.ClientSession):
    logger.info("Worker %s started", worker_id)

    while True:
        task = await queue.get()
        try:
            if task.mode == "video":
                output = await replicate_client.run(
                    KLING_MODEL,
                    input={
                        "prompt": task.prompt,
                        "images": task.images,   # ✅ bytes напрямую
                        "style": task.style,
                        "duration": task.duration,
                        "aspect_ratio": "9:16",
                        "fps": 30,
                    },
                )

                await send_output(task.chat_id, output, "mp4", http)

            elif task.mode == "image":
                output = await replicate_client.run(
                    IMAGE_MODEL,
                    input={"prompt": task.prompt},
                )
                await send_output(task.chat_id, output, "jpg", http)

            elif task.mode == "music":
                output = await replicate_client.run(
                    MUSIC_MODEL,
                    input={"prompt": task.prompt},
                )
                await send_output(task.chat_id, output, "mp3", http)

            else:  # gpt
                r = await openai_client.responses.create(
                    model="gpt-4.1-mini",
                    input=task.prompt,
                )
                await bot.send_message(task.chat_id, r.output_text)

        except Exception as e:
            logger.exception("Worker error")
            await bot.send_message(task.chat_id, "❌ Ошибка обработки запроса")

        finally:
            queue.task_done()

# =====================================================
# FASTAPI
# =====================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    workers = [asyncio.create_task(worker(i)) for i in range(WORKERS)]

    if BASE_URL:
        await bot.set_webhook(f"{BASE_URL}/webhook", secret_token=WEBHOOK_SECRET)

    yield

    for w in workers:
        w.cancel()
    await asyncio.gather(*workers, return_exceptions=True)
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def webhook(req: Request):
    if WEBHOOK_SECRET and req.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(403)
    await dp.feed_raw_update(bot, await req.json())
    return {"ok": True}

# =====================================================
# RUN
# =====================================================
if __name__ == "__main__":
    uvicorn.run("bot:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))