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
# STATUS HELPER
# =========================
async def update_status(status_msg: Message | None, text: str):
    if not status_msg:
        return
    try:
        await status_msg.edit_text(text)
    except Exception:
        pass

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
    mode = user_modes.get(msg.from_user.id)
    if not mode:
        await msg.answer("⚠️ Сначала выбери режим кнопками ниже.")
        return

    try:
        queue.put_nowait(Task(mode, msg.chat.id, msg.text))
        await msg.answer("⏳ Запрос принят, обрабатываю…")
    except asyncio.QueueFull:
        await msg.answer("🚫 Очередь переполнена. Попробуйте позже.")

# =========================
# REPLICATE
# =========================
async def run_replicate(model: str, payload: Dict[str, Any]) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: replicate_client.run(model, input=payload),
    )

# =========================
# OUTPUT HANDLER
# =========================
async def send_replicate_output(
    chat_id: int,
    output: Any,
    ext: str,
):
    data: bytes | None = None

    if isinstance(output, FileOutput):
        data = output.read()

    elif isinstance(output, str):
        async with aiohttp.ClientSession() as session:
            async with session.get(output) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Download failed: {resp.status}")
                data = await resp.read()

    elif isinstance(output, list):
        for item in output:
            try:
                return await send_replicate_output(chat_id, item, ext)
            except Exception:
                pass

    elif isinstance(output, dict):
        for value in output.values():
            try:
                return await send_replicate_output(chat_id, value, ext)
            except Exception:
                pass

    if not data:
        raise ValueError(f"Unsupported output format: {type(output)}")

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

# =========================
# WORKER
# =========================
async def worker(worker_id: int):
    logger.info("Worker %s started", worker_id)

    while True:
        task: Task = await queue.get()
        status_msg: Message | None = None

        try:
            logger.info("Processing %s for chat %s", task.mode, task.chat_id)

            status_msg = await bot.send_message(
                task.chat_id,
                "🧠 Подготовка запроса…"
            )

            if task.mode == "gpt":
                await update_status(status_msg, "🤖 Генерация ответа GPT…")

                res = await asyncio.wait_for(
                    openai_client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": task.prompt}],
                    ),
                    timeout=30,
                )

                await bot.send_message(
                    task.chat_id,
                    res.choices[0].message.content,
                )
                await update_status(status_msg, "✅ Готово")
                continue

            await update_status(
                status_msg,
                "⚙️ Генерация контента (может занять до 1 минуты)…"
            )

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

            await update_status(status_msg, "📦 Загрузка результата…")
            await send_replicate_output(task.chat_id, output, ext)
            await update_status(status_msg, "✅ Готово")

        except asyncio.TimeoutError:
            await bot.send_message(task.chat_id, "⏱ Таймаут запроса.")
        except Exception:
            logger.exception("Task failed")
            await bot.send_message(task.chat_id, "❌ Ошибка обработки запроса.")
        finally:
            queue.task_done()

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