import os
import uuid
import asyncio
import logging
from typing import Dict, Optional

import aiohttp
import aiofiles
import replicate
from dotenv import load_dotenv

from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode

from openai import AsyncOpenAI

# =========================
# 🔧 CONFIG
# =========================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://your-app.onrender.com

assert BOT_TOKEN
assert REPLICATE_API_TOKEN
assert OPENAI_API_KEY
assert WEBHOOK_URL

os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN

logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()
app = FastAPI()

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# =========================
# 🧠 STATE
# =========================

user_state: Dict[int, str] = {}
user_photo: Dict[int, str] = {}

KLING_MODEL = "kwaivgi/kling-v2.5-turbo-pro"
KLING_VERSION: Optional[str] = None

# =========================
# 🔄 STARTUP
# =========================

async def load_kling_version():
    global KLING_VERSION
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"https://api.replicate.com/v1/models/{KLING_MODEL}",
            headers={"Authorization": f"Token {REPLICATE_API_TOKEN}"}
        ) as resp:
            data = await resp.json()
            KLING_VERSION = data["latest_version"]["id"]
            logging.info(f"✅ Kling version loaded: {KLING_VERSION}")

@app.on_event("startup")
async def on_startup():
    await load_kling_version()
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("✅ Webhook set")

# =========================
# 🧩 UI
# =========================

def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎥 Видео", callback_data="video"),
            InlineKeyboardButton(text="🖼 Изображение", callback_data="image"),
        ],
        [
            InlineKeyboardButton(text="🎵 Музыка", callback_data="music"),
            InlineKeyboardButton(text="💬 GPT Чат", callback_data="chat"),
        ],
    ])

# =========================
# 🤖 HANDLERS
# =========================

@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer(
        "🚀 <b>AI Studio Bot</b>\n\n"
        "Выбери, что хочешь создать:",
        reply_markup=main_keyboard()
    )

@dp.callback_query()
async def callbacks(call: types.CallbackQuery):
    user_state[call.from_user.id] = call.data
    await call.message.answer(
        {
            "video": "🎥 Отправь описание видео или сначала фото",
            "image": "🖼 Напиши описание изображения",
            "music": "🎵 Опиши настроение и стиль музыки",
            "chat": "💬 Задай вопрос",
        }[call.data]
    )
    await call.answer()

@dp.message(F.photo)
async def photo_handler(message: types.Message):
    file = await bot.get_file(message.photo[-1].file_id)
    path = f"/tmp/{uuid.uuid4()}.jpg"
    await bot.download_file(file.file_path, path)
    user_photo[message.from_user.id] = path
    await message.answer("📸 Фото получено. Теперь напиши описание видео.")

@dp.message(F.text)
async def text_handler(message: types.Message):
    uid = message.from_user.id
    mode = user_state.get(uid)

    if mode == "video":
        await generate_video(message)
    elif mode == "image":
        await generate_image(message)
    elif mode == "music":
        await generate_music(message)
    elif mode == "chat":
        await gpt_chat(message)
    else:
        await message.answer("Выбери действие кнопками 👇", reply_markup=main_keyboard())

# =========================
# 🎥 VIDEO (Kling)
# =========================

async def generate_video(message: types.Message):
    uid = message.from_user.id
    await message.answer("⏳ Генерация видео...")

    prompt = (
        "Ultra cinematic, realistic lighting, smooth camera motion, "
        "high detail, professional video quality. "
        + message.text
    )

    input_data = {
        "prompt": prompt,
        "duration": 5,
        "aspect_ratio": "16:9",
    }

    if uid in user_photo:
        input_data["image"] = open(user_photo.pop(uid), "rb")

    prediction = replicate.predictions.create(
        version=KLING_VERSION,
        input=input_data
    )

    video_url = await wait_for_output(prediction.id)
    path = await download_file(video_url, "mp4")

    await message.answer_video(
        video=FSInputFile(path),
        caption="🎬 Готово!"
    )

# =========================
# 🖼 IMAGE
# =========================

async def generate_image(message: types.Message):
    await message.answer("🎨 Генерация изображения...")

    output = replicate.run(
        "bytedance/seedream-4",
        input={"prompt": message.text, "aspect_ratio": "4:3"}
    )

    path = await download_file(output[0].url, "jpg")
    await message.answer_photo(FSInputFile(path))

# =========================
# 🎵 MUSIC
# =========================

async def generate_music(message: types.Message):
    await message.answer("🎼 Создание музыки...")

    enhanced = (
        "High quality cinematic music, professional composition, "
        "clear melody, emotional. " + message.text
    )

    output = replicate.run(
        "meta/musicgen:671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb",
        input={
            "prompt": enhanced,
            "model_version": "stereo-large",
            "output_format": "mp3",
            "normalization_strategy": "peak"
        }
    )

    path = await download_stream(output.url, "mp3")
    await message.answer_audio(FSInputFile(path))

# =========================
# 💬 GPT CHAT
# =========================

async def gpt_chat(message: types.Message):
    resp = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Ты профессиональный креативный AI помощник."},
            {"role": "user", "content": message.text}
        ]
    )
    await message.answer(resp.choices[0].message.content)

# =========================
# ⏱ UTILS
# =========================

async def wait_for_output(pid: str) -> str:
    while True:
        pred = replicate.predictions.get(pid)
        if pred.status == "succeeded":
            return pred.output
        if pred.status == "failed":
            raise Exception("Generation failed")
        await asyncio.sleep(3)

async def download_file(url: str, ext: str) -> str:
    path = f"/tmp/{uuid.uuid4()}.{ext}"
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            async with aiofiles.open(path, "wb") as f:
                await f.write(await r.read())
    return path

async def download_stream(url: str, ext: str) -> str:
    path = f"/tmp/{uuid.uuid4()}.{ext}"
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            async with aiofiles.open(path, "wb") as f:
                async for chunk in r.content.iter_chunked(1024):
                    await f.write(chunk)
    return path

# =========================
# 🌐 WEBHOOK
# =========================

@app.post("/")
async def webhook(request: Request):
    update = types.Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}