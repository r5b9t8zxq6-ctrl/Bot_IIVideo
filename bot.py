# ===========================
# bot.py — Production Ready
# ===========================
import os
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Dict, Literal, List, Optional, Any
from aiogram.types import Update

import replicate
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties
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

def env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"ENV {name} is required")
    return value

BOT_TOKEN = env("BOT_TOKEN")
REPLICATE_API_TOKEN = env("REPLICATE_API_TOKEN")
OPENAI_API_KEY = env("OPENAI_API_KEY")

BASE_URL = os.getenv("BASE_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

QUEUE_MAXSIZE = int(os.getenv("QUEUE_MAXSIZE", "50"))
WORKERS = int(os.getenv("WORKERS", "2"))
USER_TASK_LIMIT = 2
SESSION_TTL = 600  # seconds

# =====================================================
# CLIENTS
# =====================================================
replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, timeout=30)

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
# TYPES
# =====================================================
Mode = Literal["video", "image", "music", "gpt"]

# =====================================================
# SESSION MANAGEMENT (SAFE)
# =====================================================
@dataclass(slots=True)
class UserSession:
    mode: Optional[Mode] = None
    images: List[bytes] = field(default_factory=list)
    style: str = "cinematic"
    duration: int = 5
    updated_at: float = field(default_factory=time.time)

sessions: Dict[int, UserSession] = {}
sessions_lock = asyncio.Lock()

async def get_session(user_id: int) -> UserSession:
    async with sessions_lock:
        s = sessions.get(user_id)
        if not s:
            s = UserSession()
            sessions[user_id] = s
        s.updated_at = time.time()
        return s

async def cleanup_sessions():
    while True:
        await asyncio.sleep(60)
        now = time.time()
        async with sessions_lock:
            for uid in list(sessions):
                if now - sessions[uid].updated_at > SESSION_TTL:
                    sessions.pop(uid, None)

# =====================================================
# TASK QUEUE
# =====================================================
@dataclass(slots=True)
class Task:
    user_id: int
    chat_id: int
    mode: Mode
    prompt: str
    images: List[bytes]
    style: str
    duration: int

queue: asyncio.Queue[Task] = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
user_tasks: Dict[int, int] = {}

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

# =====================================================
# HANDLERS
# =====================================================
@dp.message(CommandStart())
async def start(msg: Message):
    async with sessions_lock:
        sessions.pop(msg.from_user.id, None)
    await msg.answer("🔥 <b>AI Studio Bot</b>\n\nВыбери режим:", reply_markup=main_keyboard())

@dp.callback_query(F.data.in_({"video", "image", "music", "gpt"}))
async def select_mode(cb: CallbackQuery):
    s = await get_session(cb.from_user.id)
    s.mode = cb.data  # type: ignore
    s.images.clear()
    await cb.message.answer("✍️ Введите запрос")

@dp.message(F.text)
async def handle_text(msg: Message):
    uid = msg.from_user.id

    if user_tasks.get(uid, 0) >= USER_TASK_LIMIT:
        await msg.answer("⚠️ Подождите завершения текущего запроса")
        return

    s = await get_session(uid)
    if not s.mode:
        await msg.answer("⚠️ Сначала выберите режим")
        return

    try:
        queue.put_nowait(Task(
    user_id=uid,
    chat_id=msg.chat.id,
    mode=s.mode,
    prompt=msg.text,
    images=list(s.images),
    style=s.style,
    duration=s.duration,
))
        user_tasks[uid] = user_tasks.get(uid, 0) + 1
        await msg.answer("⏳ Запрос принят")
    except asyncio.QueueFull:
        await msg.answer("🚫 Сервер перегружен, попробуйте позже")

# =====================================================
# REPLICATE
# =====================================================
async def run_replicate(model: str, payload: Dict[str, Any]) -> Any:
    async with replicate_semaphore:
        return await asyncio.wait_for(
            asyncio.to_thread(replicate_client.run, model, input=payload),
            timeout=300,
        )

# =====================================================
# WORKER
# =====================================================
async def worker(worker_id: int):
    logger.info("Worker %s started", worker_id)
    while True:
        try:
            task = await asyncio.wait_for(queue.get(), timeout=5)
        except asyncio.TimeoutError:
            continue

        try:
            if task.mode == "gpt":
                r = await openai_client.responses.create(
                    model="gpt-4.1-mini",
                    input=task.prompt,
                )
                await bot.send_message(task.chat_id, r.output_text)

            else:
                await bot.send_message(task.chat_id, "⚠️ Режим временно отключен")

        except Exception:
            logger.exception("Worker error")
            await bot.send_message(task.chat_id, "❌ Ошибка обработки")
        finally:
    user_tasks[task.user_id] -= 1
    queue.task_done()

# =====================================================
# FASTAPI
# =====================================================
@asynccontextmanager
async def lifespan(_: FastAPI):
    workers = [asyncio.create_task(worker(i)) for i in range(WORKERS)]
    cleanup = asyncio.create_task(cleanup_sessions())

    if BASE_URL:
        await bot.set_webhook(f"{BASE_URL}/webhook", secret_token=WEBHOOK_SECRET)

    yield

    for w in workers:
        w.cancel()
    cleanup.cancel()
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def webhook(req: Request):
    if WEBHOOK_SECRET and req.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(403)

    update = Update.model_validate(await req.json())
    await dp.feed_update(bot, update)

    return {"ok": True}

# =====================================================
# RUN
# =====================================================
if __name__ == "__main__":
    uvicorn.run("bot:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))