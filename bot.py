import os
import asyncio
import logging
import time
from typing import Dict, Any

import replicate
import httpx
from dotenv import load_dotenv

from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.enums import ParseMode

from openai import AsyncOpenAI

# =======================
# ENV
# =======================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
PORT = int(os.getenv("PORT", 10000))

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

logging.basicConfig(level=logging.INFO)

# =======================
# BOT / FASTAPI
# =======================
bot = Bot(BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()
router = Router()
dp.include_router(router)

app = FastAPI()

# =======================
# QUEUE
# =======================
generation_queue: asyncio.Queue = asyncio.Queue()
user_context: Dict[int, Dict[str, Any]] = {}

# =======================
# KEYBOARDS
# =======================
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="🎬 Видео"),
            KeyboardButton(text="🖼 Изображение"),
        ],
        [
            KeyboardButton(text="🎵 Музыка"),
            KeyboardButton(text="💬 GPT Chat"),
        ],
    ],
    resize_keyboard=True,
)

video_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="📝 Текст → Видео", callback_data="video_text"),
            InlineKeyboardButton(text="🖼 Фото → Видео", callback_data="video_photo"),
        ]
    ]
)

image_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="🖼 Текст → Изображение", callback_data="image_text")
        ]
    ]
)

music_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="🎵 Создать трек", callback_data="music_text"),
            InlineKeyboardButton(text="🎼 Помощь со стилем", callback_data="music_help"),
        ]
    ]
)

# =======================
# START
# =======================
@router.message(F.text == "/start")
async def start(msg: types.Message):
    await msg.answer(
        "🚀 <b>AI Media Studio</b>\n\n"
        "Видео • Картинки • Музыка • GPT\n\n"
        "Выбери, что хочешь создать 👇",
        reply_markup=main_kb,
    )

# =======================
# MAIN MENU
# =======================
@router.message(F.text == "🎬 Видео")
async def menu_video(msg: types.Message):
    await msg.answer("Выбери тип видео:", reply_markup=video_kb)

@router.message(F.text == "🖼 Изображение")
async def menu_image(msg: types.Message):
    await msg.answer("Создание изображений:", reply_markup=image_kb)

@router.message(F.text == "🎵 Музыка")
async def menu_music(msg: types.Message):
    await msg.answer("Музыка:", reply_markup=music_kb)

@router.message(F.text == "💬 GPT Chat")
async def menu_gpt(msg: types.Message):
    user_context[msg.from_user.id] = {"mode": "gpt"}
    await msg.answer("💬 Напиши сообщение — я помогу ✨")

# =======================
# CALLBACKS
# =======================
@router.callback_query()
async def callbacks(cb: types.CallbackQuery):
    uid = cb.from_user.id

    if cb.data == "video_text":
        user_context[uid] = {"mode": "video_text"}
        await cb.message.answer("📝 Опиши сцену для видео")

    elif cb.data == "video_photo":
        user_context[uid] = {"mode": "video_photo"}
        await cb.message.answer("🖼 Отправь фото + описание")

    elif cb.data == "image_text":
        user_context[uid] = {"mode": "image_text"}
        await cb.message.answer("🖼 Опиши изображение")

    elif cb.data == "music_text":
        user_context[uid] = {"mode": "music_text"}
        await cb.message.answer("🎵 Опиши музыку")

    elif cb.data == "music_help":
        await cb.message.answer(
            "🎼 Примеры:\n\n"
            "• cinematic epic orchestral\n"
            "• lo-fi chill beats\n"
            "• techno cyberpunk\n"
            "• ambient meditation\n"
            "• trap dark aggressive"
        )

    await cb.answer()

# =======================
# MESSAGE HANDLER
# =======================
@router.message()
async def handle_text(msg: types.Message):
    uid = msg.from_user.id
    ctx = user_context.get(uid)

    if not ctx:
        return

    mode = ctx.get("mode")

    if mode == "video_text":
        await generation_queue.put(("video_text", uid, msg.text))
        await msg.answer("⏳ Запрос добавлен в очередь")

    elif mode == "image_text":
        await generation_queue.put(("image_text", uid, msg.text))
        await msg.answer("⏳ Генерация изображения")

    elif mode == "music_text":
        await generation_queue.put(("music_text", uid, msg.text))
        await msg.answer("⏳ Генерация музыки")

    elif mode == "gpt":
        response = await gpt_chat(msg.text)
        await msg.answer(response)

# =======================
# GPT CHAT
# =======================
async def gpt_chat(prompt: str) -> str:
    completion = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Ты профессиональный AI ассистент."},
            {"role": "user", "content": prompt},
        ],
    )
    return completion.choices[0].message.content

# =======================
# WORKER
# =======================
async def worker():
    while True:
        task, uid, data = await generation_queue.get()
        try:
            if task == "video_text":
                await generate_video(uid, data)
            elif task == "image_text":
                await generate_image(uid, data)
            elif task == "music_text":
                await generate_music(uid, data)
        except Exception as e:
            logging.exception(e)
            await bot.send_message(uid, "❌ Ошибка генерации")
        finally:
            generation_queue.task_done()

# =======================
# GENERATION
# =======================
async def generate_video(uid: int, prompt: str):
    enhanced = await gpt_chat(f"Усиль кинематографично: {prompt}")

    prediction = replicate_client.predictions.create(
        model="kwaivgi/kling-v2.5-turbo-pro",
        input={"prompt": enhanced},
    )

    while prediction.status not in ("succeeded", "failed"):
        await asyncio.sleep(3)
        prediction = replicate_client.predictions.get(prediction.id)

    if prediction.status != "succeeded":
        raise RuntimeError("Video failed")

    video_url = prediction.output
    if isinstance(video_url, list):
        video_url = video_url[0]

    await bot.send_video(uid, video=video_url, caption="🎬 Видео готово!")

async def generate_image(uid: int, prompt: str):
    output = replicate_client.run(
        "bytedance/seedream-4",
        input={"prompt": prompt, "aspect_ratio": "4:3"},
    )
    await bot.send_photo(uid, photo=output[0].url)

async def generate_music(uid: int, prompt: str):
    enhanced = await gpt_chat(f"Сделай музыкальный промт: {prompt}")

    output = replicate_client.run(
        "meta/musicgen:671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb",
        input={
            "prompt": enhanced,
            "model_version": "stereo-large",
            "output_format": "mp3",
            "normalization_strategy": "peak",
        },
    )

    await bot.send_audio(uid, audio=output.url, caption="🎵 Трек готов!")

# =======================
# WEBHOOK
# =======================
@app.post("/")
async def webhook(req: Request):
    if req.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(status_code=403)
    update = types.Update.model_validate(await req.json())
    await dp.feed_update(bot, update)
    return {"ok": True}

@app.on_event("startup")
async def startup():
    await bot.set_webhook(
        WEBHOOK_URL,
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=True,
    )
    asyncio.create_task(worker())

# =======================
# RUN
# =======================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)