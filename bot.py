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
Mode = Literal["video", "image", "music", "gpt", "photo_to_video"]

KLING_MODEL = "kwaivgi/kling-v2.5-turbo-pro"
IMAGE_MODEL = "bytedance/seedream-4"
MUSIC_MODEL = "meta/musicgen:671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb"

# =========================
# QUEUE & STATE
# =========================
queue: asyncio.Queue["Task"] = asyncio.Queue(maxsize=100)

class Task:
    __slots__ = ("mode", "chat_id", "prompt")
    def __init__(self, mode: Mode, chat_id: int, prompt: str):
        self.mode = mode
        self.chat_id = chat_id
        self.prompt = prompt

user_modes: Dict[int, Mode] = {}
user_photos: Dict[int, str] = {}
user_previews: Dict[int, Dict[str, str]] = {}

# =========================
# KEYBOARDS
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
            [
                InlineKeyboardButton(text="📸 Фото → 🎬 Видео", callback_data="photo_to_video"),
            ],
        ]
    )

def confirm_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Генерировать видео", callback_data="confirm_video"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_video"),
            ]
        ]
    )

# =========================
# HELPERS
# =========================
async def update_status(msg: Message | None, text: str):
    if msg:
        try:
            await msg.edit_text(text)
        except Exception:
            pass

async def enhance_video_prompt(text: str) -> str:
    try:
        res = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Rewrite into a cinematic video prompt. "
                        "Add camera motion, lighting, realism, mood. "
                        "Return ONLY the prompt."
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0.8,
        )
        return res.choices[0].message.content.strip()
    except Exception:
        return text

# =========================
# HANDLERS
# =========================
@dp.message(CommandStart())
async def start(msg: Message):
    await msg.answer("🔥 <b>AI Studio Bot</b>\n\nВыбери режим:", reply_markup=main_keyboard())

@dp.callback_query(F.data.in_({"video", "image", "music", "gpt", "photo_to_video"}))
async def select_mode(cb: CallbackQuery):
    user_modes[cb.from_user.id] = cb.data  # type: ignore
    if cb.data == "photo_to_video":
        await cb.message.answer("📸 Отправь фото")
    else:
        await cb.message.answer("✍️ Введите запрос:")

@dp.message(F.photo)
async def handle_photo(msg: Message):
    if user_modes.get(msg.from_user.id) != "photo_to_video":
        return
    file = msg.photo[-1]
    tg_file = await bot.get_file(file.file_id)
    user_photos[msg.from_user.id] = tg_file.file_path
    await msg.answer("✍️ Теперь отправь описание видео")

@dp.message(F.text)
async def handle_text(msg: Message):
    mode = user_modes.get(msg.from_user.id)
    if not mode:
        return await msg.answer("⚠️ Выбери режим")

    if mode == "photo_to_video":
        photo = user_photos.get(msg.from_user.id)
        if not photo:
            return await msg.answer("📸 Сначала отправь фото")

        enhanced = await enhance_video_prompt(msg.text)
        user_previews[msg.from_user.id] = {
            "prompt": enhanced,
            "photo": photo,
        }

        photo_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{photo}"

        await msg.answer_photo(
            photo=photo_url,
            caption=f"<b>🎬 Предпросмотр</b>\n\n{enhanced}",
            reply_markup=confirm_keyboard(),
        )
        return

    queue.put_nowait(Task(mode, msg.chat.id, msg.text))
    await msg.answer("⏳ Запрос принят")

@dp.callback_query(F.data.in_({"confirm_video", "cancel_video"}))
async def confirm(cb: CallbackQuery):
    uid = cb.from_user.id

    if cb.data == "cancel_video":
        user_previews.pop(uid, None)
        user_photos.pop(uid, None)
        return await cb.message.edit_text("❌ Отменено")

    preview = user_previews.get(uid)
    if not preview:
        return await cb.message.edit_text("⚠️ Превью не найдено")

    combined = f"{preview['prompt']}\nPHOTO:{preview['photo']}"
    queue.put_nowait(Task("photo_to_video", cb.message.chat.id, combined))
    await cb.message.edit_text("🎬 Генерация видео запущена…")

# =========================
# REPLICATE
# =========================
async def run_replicate(model: str, payload: Dict[str, Any]):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: replicate_client.run(model, input=payload))

async def send_output(chat_id: int, output: Any, ext: str):
    if isinstance(output, list):
        output = output[0]

    if isinstance(output, FileOutput):
        data = output.read()
    else:
        async with aiohttp.ClientSession() as s:
            async with s.get(output) as r:
                data = await r.read()

    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as f:
        f.write(data)
        path = f.name

    file = FSInputFile(path)
    if ext == "mp4":
        await bot.send_video(chat_id, file)
    elif ext == "jpg":
        await bot.send_photo(chat_id, file)
    else:
        await bot.send_audio(chat_id, file)

    os.remove(path)

# =========================
# WORKER
# =========================
async def worker():
    while True:
        task = await queue.get()
        try:
            if task.mode == "photo_to_video":
                prompt, photo = task.prompt.split("\nPHOTO:")
                url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{photo}"
                out = await run_replicate(KLING_MODEL, {"prompt": prompt, "image": url})
                await send_output(task.chat_id, out, "mp4")

            elif task.mode == "video":
                out = await run_replicate(KLING_MODEL, {"prompt": task.prompt})
                await send_output(task.chat_id, out, "mp4")

            elif task.mode == "image":
                out = await run_replicate(IMAGE_MODEL, {"prompt": task.prompt})
                await send_output(task.chat_id, out, "jpg")

            elif task.mode == "music":
                out = await run_replicate(MUSIC_MODEL, {"prompt": task.prompt})
                await send_output(task.chat_id, out, "mp3")

            elif task.mode == "gpt":
                res = await openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": task.prompt}],
                )
                await bot.send_message(task.chat_id, res.choices[0].message.content)

        except Exception:
            logger.exception("Task failed")
            await bot.send_message(task.chat_id, "❌ Ошибка")
        finally:
            queue.task_done()

# =========================
# FASTAPI
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    if BASE_URL:
        await bot.set_webhook(f"{BASE_URL}/webhook", secret_token=WEBHOOK_SECRET)
    asyncio.create_task(worker())
    yield
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def webhook(req: Request):
    if WEBHOOK_SECRET and req.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(status_code=403)
    await dp.feed_raw_update(bot, await req.json())
    return {"ok": True}

if __name__ == "__main__":
    uvicorn.run("bot:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))