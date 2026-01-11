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
# MODES
# =========================
Mode = Literal["video", "photo_video", "image", "music", "gpt"]

# =========================
# MODELS
# =========================
KLING_MODEL = "kwaivgi/kling-v2.5-turbo-pro"
IMAGE_MODEL = "bytedance/seedream-4"
MUSIC_MODEL = "meta/musicgen:671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb"

# =========================
# QUEUE & STATE
# =========================
queue: asyncio.Queue["Task"] = asyncio.Queue(maxsize=100)

class Task:
    def __init__(self, mode: Mode, chat_id: int, prompt: str):
        self.mode = mode
        self.chat_id = chat_id
        self.prompt = prompt

user_modes: Dict[int, Mode] = {}
user_photos: Dict[int, str] = {}

# =========================
# KEYBOARD
# =========================
def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton("🎬 Видео", callback_data="video"),
                InlineKeyboardButton("📸➡️🎬 Фото → Видео", callback_data="photo_video"),
            ],
            [
                InlineKeyboardButton("🖼 Изображение", callback_data="image"),
                InlineKeyboardButton("🎵 Музыка", callback_data="music"),
            ],
            [
                InlineKeyboardButton("🤖 GPT", callback_data="gpt"),
            ],
        ]
    )

# =========================
# GPT PROMPT ENHANCER
# =========================
async def enhance_prompt(prompt: str) -> str:
    system = (
        "You are a professional cinematic prompt engineer for AI video generation. "
        "Rewrite the user prompt into a highly detailed cinematic video prompt. "
        "Add camera movement, lighting, atmosphere, realism, motion, style. "
        "Return ONLY the prompt text. No explanations."
    )

    res = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
    )

    return res.choices[0].message.content.strip()

# =========================
# HANDLERS
# =========================
@dp.message(CommandStart())
async def start(msg: Message):
    await msg.answer("🔥 AI Studio Bot\n\nВыбери режим:", reply_markup=main_keyboard())

@dp.callback_query(F.data.in_({"video", "photo_video", "image", "music", "gpt"}))
async def select_mode(cb: CallbackQuery):
    user_modes[cb.from_user.id] = cb.data  # type: ignore
    if cb.data == "photo_video":
        await cb.message.answer("📸 Отправь фото")
    else:
        await cb.message.answer("✍️ Введите запрос")

@dp.message(F.photo)
async def photo_handler(msg: Message):
    if user_modes.get(msg.from_user.id) != "photo_video":
        return
    file = await bot.get_file(msg.photo[-1].file_id)
    user_photos[msg.from_user.id] = file.file_path
    await msg.answer("✍️ Теперь отправь описание для видео")

@dp.message(F.text)
async def text_handler(msg: Message):
    mode = user_modes.get(msg.from_user.id)
    if not mode:
        return await msg.answer("Выбери режим")

    if mode == "photo_video":
        photo = user_photos.get(msg.from_user.id)
        if not photo:
            return await msg.answer("Сначала фото")
        combined = f"{msg.text}\nPHOTO:{photo}"
        queue.put_nowait(Task(mode, msg.chat.id, combined))
        return await msg.answer("🎬 Генерация запущена")

    queue.put_nowait(Task(mode, msg.chat.id, msg.text))
    await msg.answer("⏳ Принято")

# =========================
# WORKER
# =========================
async def worker():
    while True:
        task = await queue.get()
        try:
            if task.mode in ("video", "photo_video"):
                prompt = task.prompt
                image_url = None

                if task.mode == "photo_video":
                    prompt, photo = prompt.split("\nPHOTO:", 1)
                    image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{photo}"

                enhanced = await enhance_prompt(prompt)

                payload = {"prompt": enhanced}
                if image_url:
                    payload["image"] = image_url

                output = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: replicate_client.run(KLING_MODEL, input=payload)
                )

                await send_output(task.chat_id, output, "mp4")

            elif task.mode == "image":
                out = replicate_client.run(IMAGE_MODEL, input={"prompt": task.prompt})
                await send_output(task.chat_id, out, "jpg")

            elif task.mode == "music":
                out = replicate_client.run(
                    MUSIC_MODEL, input={"prompt": task.prompt, "output_format": "mp3"}
                )
                await send_output(task.chat_id, out, "mp3")

            else:
                res = await openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": task.prompt}],
                )
                await bot.send_message(task.chat_id, res.choices[0].message.content)

        except Exception:
            logger.exception("Generation error")
            await bot.send_message(task.chat_id, "❌ Ошибка")
        finally:
            queue.task_done()

# =========================
# SEND OUTPUT
# =========================
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
        raise HTTPException(403)
    await dp.feed_raw_update(bot, await req.json())
    return {"ok": True}

if __name__ == "__main__":
    uvicorn.run("bot:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))