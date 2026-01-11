# ===========================
# bot.py — Production Ready
# ===========================
import os
import asyncio
import logging
import tempfile
from contextlib import asynccontextmanager, ExitStack
from dataclasses import dataclass, field
from typing import Any, Dict, Literal, List, Optional

import aiohttp
import replicate
from replicate.helpers import FileOutput
from dotenv import load_dotenv

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
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"ENV {name} is required")
    return value

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
# USER SESSION
# =====================================================
@dataclass
class UserSession:
    mode: Optional[Mode] = None
    images: List[bytes] = field(default_factory=list)
    style: str = "cinematic"
    duration: int = 5
    lock: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(1))

user_sessions: Dict[int, UserSession] = {}

def get_session(user_id: int) -> UserSession:
    return user_sessions.setdefault(user_id, UserSession())

# =====================================================
# TASK
# =====================================================
@dataclass(slots=True)
class Task:
    mode: Mode
    chat_id: int
    user_id: int
    prompt: str

queue: asyncio.Queue[Task] = asyncio.Queue(maxsize=QUEUE_MAXSIZE)

# =====================================================
# KEYBOARDS
# =====================================================
def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton("🎬 Видео", callback_data="video"),
                InlineKeyboardButton("🖼 Изображение", callback_data="image"),
            ],
            [
                InlineKeyboardButton("🎵 Музыка", callback_data="music"),
                InlineKeyboardButton("🤖 GPT", callback_data="gpt"),
            ],
        ]
    )

def style_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton("🎬 Cinematic", callback_data="style_cinematic"),
                InlineKeyboardButton("🎨 Anime", callback_data="style_anime"),
            ],
            [
                InlineKeyboardButton("🤖 Cyberpunk", callback_data="style_cyberpunk"),
                InlineKeyboardButton("📸 Realistic", callback_data="style_realistic"),
            ],
        ]
    )

def duration_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton("⏱ 5 сек", callback_data="dur_5"),
                InlineKeyboardButton("⏱ 10 сек", callback_data="dur_10"),
                InlineKeyboardButton("⏱ 15 сек", callback_data="dur_15"),
            ]
        ]
    )

# =====================================================
# HANDLERS
# =====================================================
@dp.message(CommandStart())
async def start(msg: Message):
    user_sessions.pop(msg.from_user.id, None)
    await msg.answer(
        "🔥 <b>AI Studio Bot</b>\n\nВыбери режим:",
        reply_markup=main_keyboard(),
    )

@dp.callback_query(F.data.in_({"video", "image", "music", "gpt"}))
async def select_mode(cb: CallbackQuery):
    session = get_session(cb.from_user.id)
    session.mode = cb.data  # type: ignore
    session.images.clear()

    if cb.data == "video":
        await cb.message.answer("📸 Отправь 1–5 фото")
    else:
        await cb.message.answer("✍️ Введите запрос")

@dp.message(F.photo)
async def handle_photo(msg: Message):
    session = get_session(msg.from_user.id)
    if session.mode != "video":
        return

    if len(session.images) >= 5:
        await msg.answer("⚠️ Максимум 5 фото")
        return

    file = await bot.get_file(msg.photo[-1].file_id)
    data = await bot.download_file(file.file_path)
    session.images.append(data.read())

    await msg.answer(
        f"📸 Фото добавлено ({len(session.images)}/5)\nВыбери стиль:",
        reply_markup=style_keyboard(),
    )

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
    session = get_session(msg.from_user.id)
    if not session.mode:
        await msg.answer("⚠️ Сначала выбери режим")
        return

    try:
        await asyncio.wait_for(
            queue.put(Task(session.mode, msg.chat.id, msg.from_user.id, msg.text)),
            timeout=2,
        )
    except asyncio.TimeoutError:
        await msg.answer("🚫 Очередь перегружена")
        return

    await msg.answer("⏳ Запрос принят")

# =====================================================
# REPLICATE
# =====================================================
async def run_replicate(model: str, payload: Dict[str, Any]) -> Any:
    async with replicate_semaphore:
        for attempt in range(3):
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(replicate_client.run, model, input=payload),
                    timeout=300,
                )
            except Exception as e:
                logger.warning("Replicate retry %s: %s", attempt + 1, e)
                await asyncio.sleep(2)
        raise RuntimeError("Replicate failed")

# =====================================================
# OUTPUT
# =====================================================
async def send_output(chat_id: int, output: Any, ext: str, session: aiohttp.ClientSession):
    data: Optional[bytes] = None

    if isinstance(output, FileOutput):
        data = await asyncio.to_thread(output.read)
    elif isinstance(output, str):
        async with session.get(output, timeout=aiohttp.ClientTimeout(total=60)) as r:
            data = await r.read()
    elif isinstance(output, list):
        for item in output:
            try:
                return await send_output(chat_id, item, ext, session)
            except Exception:
                continue

    if not data:
        raise RuntimeError("Empty output")

    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as f:
        f.write(data)
        path = f.name

    try:
        file = FSInputFile(path)
        if ext == "mp4":
            await bot.send_video(chat_id, file)
        elif ext == "jpg":
            await bot.send_photo(chat_id, file)
        else:
            await bot.send_audio(chat_id, file)
    finally:
        os.remove(path)

# =====================================================
# WORKER
# =====================================================
async def worker(worker_id: int, session: aiohttp.ClientSession):
    logger.info("Worker %s started", worker_id)

    while True:
        task = await queue.get()
        session_user = get_session(task.user_id)

        try:
            async with session_user.lock:
                if task.mode == "video":
                    if not session_user.images:
                        raise RuntimeError("No images")

                    paths: List[str] = []
                    with ExitStack() as stack:
                        for img in session_user.images:
                            f = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                            f.write(img)
                            f.close()
                            paths.append(f.name)

                        files = [stack.enter_context(open(p, "rb")) for p in paths]

                        output = await run_replicate(
                            KLING_MODEL,
                            {
                                "prompt": task.prompt,
                                "images": files,
                                "style": session_user.style,
                                "duration": session_user.duration,
                                "aspect_ratio": "9:16",
                                "fps": 30,
                            },
                        )

                    await send_output(task.chat_id, output, "mp4", session)

                elif task.mode == "image":
                    o = await run_replicate(IMAGE_MODEL, {"prompt": task.prompt})
                    await send_output(task.chat_id, o, "jpg", session)

                elif task.mode == "music":
                    o = await run_replicate(MUSIC_MODEL, {"prompt": task.prompt})
                    await send_output(task.chat_id, o, "mp3", session)

                else:
                    r = await openai_client.responses.create(
                        model="gpt-4.1-mini",
                        input=task.prompt,
                    )
                    await bot.send_message(task.chat_id, r.output_text)

        except Exception:
            logger.exception("Task failed")
            await bot.send_message(task.chat_id, "❌ Ошибка обработки")
        finally:
            queue.task_done()

# =====================================================
# FASTAPI
# =====================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))
    workers = [asyncio.create_task(worker(i, session)) for i in range(WORKERS)]

    if BASE_URL and BASE_URL.startswith("https://"):
        await bot.set_webhook(f"{BASE_URL}/webhook", secret_token=WEBHOOK_SECRET)
        logger.info("Webhook set")

    yield

    for w in workers:
        w.cancel()
        await asyncio.gather(w, return_exceptions=True)

    await session.close()
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def telegram_webhook(req: Request):
    if WEBHOOK_SECRET and req.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(status_code=403)

    await dp.feed_raw_update(bot, await req.json())
    return {"ok": True}

# =====================================================
# RUN
# =====================================================
if __name__ == "__main__":
    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        log_level="info",
    )