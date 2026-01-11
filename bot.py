import os
import asyncio
import logging
import tempfile
from contextlib import asynccontextmanager
from typing import Any, Dict, Literal

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

# Ограничиваем доступ к blocking API
replicate_semaphore = asyncio.Semaphore(2)
executor = asyncio.get_running_loop if False else None  # marker

# =====================================================
# BOT
# =====================================================
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

# =====================================================
# MODELS / STATE
# =====================================================
Mode = Literal["video", "image", "music", "gpt"]

KLING_MODEL = "kwaivgi/kling-v2.5-turbo-pro"
IMAGE_MODEL = "bytedance/seedream-4"
MUSIC_MODEL = "meta/musicgen:671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb"

queue: asyncio.Queue["Task"] = asyncio.Queue(maxsize=QUEUE_MAXSIZE)

user_modes: Dict[int, Mode] = {}
user_locks: Dict[int, asyncio.Semaphore] = {}

# =====================================================
# DATA
# =====================================================
class Task:
    __slots__ = ("mode", "chat_id", "prompt", "user_id")

    def __init__(self, mode: Mode, chat_id: int, user_id: int, prompt: str):
        self.mode = mode
        self.chat_id = chat_id
        self.user_id = user_id
        self.prompt = prompt


# =====================================================
# KEYBOARD
# =====================================================
def main_keyboard() -> InlineKeyboardMarkup:
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

# =====================================================
# HANDLERS
# =====================================================
@dp.message(CommandStart())
async def start(msg: Message):
    await msg.answer(
        "🔥 <b>AI Studio Bot</b>\n\nВыбери режим:",
        reply_markup=main_keyboard(),
    )


@dp.callback_query(F.data.in_({"video", "image", "music", "gpt"}))
async def select_mode(cb: CallbackQuery):
    user_modes[cb.from_user.id] = cb.data  # type: ignore
    await cb.message.answer("✍️ Введите запрос:")


@dp.message(F.text)
async def handle_text(msg: Message):
    mode = user_modes.get(msg.from_user.id)
    if not mode:
        await msg.answer("⚠️ Сначала выбери режим кнопками ниже.")
        return

    if msg.from_user.id not in user_locks:
        user_locks[msg.from_user.id] = asyncio.Semaphore(1)

    if queue.full():
        await msg.answer("🚫 Очередь переполнена. Попробуйте позже.")
        return

    await queue.put(Task(mode, msg.chat.id, msg.from_user.id, msg.text))
    await msg.answer("⏳ Запрос принят, обрабатываю…")

# =====================================================
# REPLICATE
# =====================================================
async def run_replicate(model: str, payload: Dict[str, Any]) -> Any:
    async with replicate_semaphore:
        return await asyncio.wait_for(
            asyncio.to_thread(
                replicate_client.run,
                model,
                input=payload,
            ),
            timeout=180,
        )

# =====================================================
# OUTPUT
# =====================================================
async def send_output(chat_id: int, output: Any, ext: str, session: aiohttp.ClientSession):
    data: bytes | None = None

    if isinstance(output, FileOutput):
        data = output.read()

    elif isinstance(output, str):
        async with session.get(output) as resp:
            if resp.status != 200:
                raise RuntimeError("Download failed")
            data = await resp.read()

    elif isinstance(output, list):
        for item in output:
            try:
                return await send_output(chat_id, item, ext, session)
            except Exception:
                pass

    if not data:
        raise RuntimeError("Unsupported output")

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
        lock = user_locks[task.user_id]

        async with lock:
            try:
                if task.mode == "gpt":
                    res = await openai_client.responses.create(
                        model="gpt-4.1-mini",
                        input=task.prompt,
                    )
                    await bot.send_message(task.chat_id, res.output_text)
                    continue

                if task.mode == "video":
                    output = await run_replicate(KLING_MODEL, {"prompt": task.prompt})
                    ext = "mp4"
                elif task.mode == "image":
                    output = await run_replicate(IMAGE_MODEL, {"prompt": task.prompt})
                    ext = "jpg"
                else:
                    output = await run_replicate(
                        MUSIC_MODEL,
                        {"prompt": task.prompt, "output_format": "mp3"},
                    )
                    ext = "mp3"

                await send_output(task.chat_id, output, ext, session)

            except asyncio.TimeoutError:
                await bot.send_message(task.chat_id, "⏱ Таймаут запроса.")
            except Exception:
                logger.exception("Task failed")
                await bot.send_message(task.chat_id, "❌ Ошибка обработки.")
            finally:
                queue.task_done()

# =====================================================
# FASTAPI
# =====================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    session = aiohttp.ClientSession()

    workers = [
        asyncio.create_task(worker(i, session))
        for i in range(WORKERS)
    ]

    if BASE_URL and BASE_URL.startswith("https://"):
        await bot.set_webhook(
            f"{BASE_URL}/webhook",
            secret_token=WEBHOOK_SECRET,
        )
        logger.info("Webhook set")

    yield

    for w in workers:
        w.cancel()

    await session.close()
    await bot.session.close()


app = FastAPI(lifespan=lifespan)


@app.post("/webhook")
async def telegram_webhook(req: Request):
    if WEBHOOK_SECRET:
        if req.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
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