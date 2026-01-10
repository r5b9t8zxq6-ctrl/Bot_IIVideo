import os
import asyncio
import logging
import aiohttp
import replicate

from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage

# ================== CONFIG ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN

logging.basicConfig(level=logging.INFO)

# ================== INIT ==================
bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

app = FastAPI()

# ================== STATES ==================
class GenState(StatesGroup):
    text_only = State()
    text_plus_image = State()

# ================== KEYBOARD ==================
main_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(
        text="🎨 TEXT → IMAGE → VIDEO",
        callback_data="text_image_video"
    )],
    [InlineKeyboardButton(
        text="📝 TEXT + IMAGE → VIDEO",
        callback_data="text_plus_image_video"
    )]
])

# ================== START ==================
@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Выбери режим генерации:",
        reply_markup=main_kb
    )

# ================== CALLBACKS ==================
@router.callback_query(F.data == "text_image_video")
async def cb_text_image_video(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GenState.text_only)
    await callback.message.answer("✍️ Напиши описание сцены")
    await callback.answer()

@router.callback_query(F.data == "text_plus_image_video")
async def cb_text_plus_image_video(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GenState.text_plus_image)
    await callback.message.answer("📝 Напиши описание, затем отправь изображение")
    await callback.answer()

# ================== TEXT → IMAGE → VIDEO ==================
@router.message(GenState.text_only)
async def text_to_image_to_video(message: Message, state: FSMContext):
    prompt = message.text

    await message.answer("🎨 Генерирую изображение...")

    image = replicate.run(
        "prunaai/flux-fast",
        input={"prompt": prompt}
    )

    image_url = image.url
    await message.answer_photo(image_url, caption="🖼 Кадр готов")

    await asyncio.sleep(8)

    await message.answer("🎬 Генерирую видео...")

    video = replicate.run(
        "kwaivgi/kling-v2.1",
        input={
            "start_image": image_url,
            "prompt": prompt,
            "duration": 5,
            "fps": 24
        }
    )

    async with aiohttp.ClientSession() as session:
        async with session.get(video.url) as resp:
            video_bytes = await resp.read()

    await message.answer_video(
        video_bytes,
        caption="🎉 Видео готово!",
        reply_markup=main_kb
    )

    await state.clear()

# ================== TEXT + IMAGE → VIDEO ==================
@router.message(GenState.text_plus_image)
async def text_plus_image_to_video(message: Message, state: FSMContext):
    data = await state.get_data()

    # Шаг 1 — текст
    if message.text and "prompt" not in data:
        await state.update_data(prompt=message.text)
        await message.answer("🖼 Теперь отправь изображение")
        return

    # Шаг 2 — изображение
    if not message.photo:
        await message.answer("❌ Нужно отправить изображение")
        return

    prompt = data.get("prompt", "cinematic motion")

    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

    await asyncio.sleep(8)

    await message.answer("🎬 Генерирую видео...")

    video = replicate.run(
        "kwaivgi/kling-v2.1",
        input={
            "start_image": image_url,
            "prompt": prompt,
            "duration": 5,
            "fps": 24
        }
    )

    async with aiohttp.ClientSession() as session:
        async with session.get(video.url) as resp:
            video_bytes = await resp.read()

    await message.answer_video(
        video_bytes,
        caption="🎉 Видео готово!",
        reply_markup=main_kb
    )

    await state.clear()

# ================== WEBHOOK ==================
@app.post("/")
async def webhook(request: Request):
    update = await request.json()
    await dp.feed_raw_update(bot, update)
    return {"ok": True}

@app.on_event("startup")
async def on_startup():
    await bot.set_webhook(
        WEBHOOK_URL,
        allowed_updates=["message", "callback_query"]
    )
    logging.info("✅ Webhook установлен")

@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()