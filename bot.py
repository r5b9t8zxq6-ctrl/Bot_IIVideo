import os
import asyncio
import logging
import tempfile
from typing import Any, Dict, Literal

import aiohttp
import replicate
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
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("ai-studio-bot")

# =========================
# ENV
# =========================
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
MUSIC_MODEL = "meta/musicgen:671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb"

# =========================
# QUEUE & STATE
# =========================
QUEUE_MAX_SIZE = 100
queue: asyncio.Queue["Task"] = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)

class Task:
    __slots__ = ("mode", "chat_id", "prompt")

    def __init__(self, mode: Mode, chat_id: int, prompt: str):
        self.mode = mode
        self.chat_id = chat_id
        self.prompt = prompt

user_modes: Dict[int, Mode] = {}

# =========================
# KEYBOARD
# =========================
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

# =========================
# HANDLERS
# =========================
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
    mode = user_modes.pop(msg.from_user.id, None)
    if not mode:
        return

    try:
        queue.put_nowait(Task(mode, msg.chat.id, msg.text))
        await msg.answer("⏳ Запрос принят, обрабатываю…")
    except asyncio.QueueFull:
        await msg.answer("🚫 Очередь переполнена. Попробуйте позже.")

# =========================
# WORKER
# =========================
async def run_replicate(model: str, payload: Dict[str, Any]) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: replicate_client.run(model, input=payload),
    )

async def worker(worker_id: int):
    logger.info("Worker %s started", worker_id)

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            task: Task = await queue.get()
            try:
                logger.info("Processing %s for chat %s", task.mode, task.chat_id)

                if task.mode == "gpt":
                    res = await asyncio.wait_for(
                        openai_client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=[{"role": "user", "content": task.prompt}],
                        ),
                        timeout=30,
                    )
                    await bot.send_message(task.chat_id, res.choices[0].message.content)
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

                url = extract_url(output)
                await download_and_send(task.chat_id, url, ext, session)

            except asyncio.TimeoutError:
                await bot.send_message(task.chat_id, "⏱ Таймаут запроса.")
            except Exception as e:
                logger.exception("Task failed")
                await bot.send_message(task.chat_id, "❌ Ошибка обработки запроса.")
            finally:
                queue.task_done()

# =========================
# HELPERS
# =========================
def extract_url(output: Any) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, list) and output and isinstance(output[0], str):
        return output[0]
    raise ValueError("Invalid model output")

async def download_and_send(
    chat_id: int,
    url: str,
    ext: str,
    session: aiohttp.ClientSession,
):
    async with session.get(url) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Download failed: {resp.status}")
        data = await resp.read()

    with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as f:
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

# =========================
# FASTAPI
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    if BASE_URL and BASE_URL.startswith("https://"):
        await bot.set_webhook(
            f"{BASE_URL}/webhook",
            secret_token=WEBHOOK_SECRET,
        )
        logger.info("Webhook set")
    else:
        logger.warning("Webhook skipped")

    workers = [asyncio.create_task(worker(i)) for i in range(2)]
    yield
    for w in workers:
        w.cancel()
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
        port=int(os.getenv("PORT", "8000")),
        log_level="info",
    )