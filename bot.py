import os
import logging
import aiohttp
import replicate
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage

# ================== ENV ==================

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not BOT_TOKEN or not REPLICATE_API_TOKEN or not WEBHOOK_URL:
    raise RuntimeError("❌ ENV variables missing")

os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN

logging.basicConfig(level=logging.INFO)

# ================== BOT ==================

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# ================== FSM ==================

class GenState(StatesGroup):
    text_prompt = State()
    image_prompt = State()
    image_url = State()

# ================== KEYBOARDS ==================

main_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="🎨 Text → Image", callback_data="text_image")],
        [InlineKeyboardButton(text="🎬 Image → Video", callback_data="image_video")],
        [InlineKeyboardButton(text="🚀 Text → Image → Video", callback_data="text_image_video")]
    ]
)

# ================== HELPERS ==================

async def download_file(url: str) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.read()

# ================== HANDLERS ==================

@router.message(F.text == "/start")
async def start(message: Message):
    await message.answer("Выбери режим 👇", reply_markup=main_kb)

# ---------- TEXT → IMAGE ----------

@router.callback_query(F.data == "text_image")
async def text_image(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GenState.text_prompt)
    await callback.message.answer("✍️ Опиши изображение")
    await callback.answer()

@router.message(GenState.text_prompt)
async def generate_image(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🎨 Генерирую изображение...")

    try:
        output = replicate.run(
            "prunaai/flux-fast",
            input={"prompt": message.text}
        )

        image_url = output.url
        await message.answer_photo(image_url, reply_markup=main_kb)

    except Exception as e:
        logging.exception(e)
        await message.answer("❌ Ошибка генерации изображения")

# ---------- IMAGE → VIDEO ----------

@router.callback_query(F.data == "image_video")
async def ask_image(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GenState.image_url)
    await callback.message.answer("🖼 Отправь изображение")
    await callback.answer()

@router.message(GenState.image_url, F.photo)
async def image_to_video(message: Message, state: FSMContext):
    await message.answer("🎬 Генерирую видео...")

    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

    try:
        output = replicate.run(
    "kwaivgi/kling-v2.1",
    input={
        "start_image": image_url,
        "prompt": "cinematic motion",
        "duration": 5,
        "fps": 24
    }
)

        video = await download_file(output.url)
        await message.answer_video(video=video, reply_markup=main_kb)

    except Exception as e:
        logging.exception(e)
        await message.answer("❌ Ошибка генерации видео")

    await state.clear()

# ---------- TEXT → IMAGE → VIDEO ----------

@router.callback_query(F.data == "text_image_video")
async def text_image_video(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GenState.image_prompt)
    await callback.message.answer("✍️ Опиши сцену")
    await callback.answer()

@router.message(GenState.image_prompt)
async def text_to_image_to_video(message: Message, state: FSMContext):
    import asyncio

    await message.answer("🎨 Генерирую изображение...")

    try:
        # 1️⃣ TEXT → IMAGE
        image_output = replicate.run(
            "prunaai/flux-fast",
            input={
                "prompt": message.text,
                "width": 1024,
                "height": 1024
            }
        )

        image_url = image_output.url
        await message.answer_photo(image_url, caption="🖼 Кадр готов")

        # ⛔ ОБЯЗАТЕЛЬНАЯ ПАУЗА (иначе 429)
        await asyncio.sleep(8)

        await message.answer("🎬 Генерирую видео...")

        # 2️⃣ IMAGE → VIDEO (Kling)
        video_output = replicate.run(
            "kwaivgi/kling-v2.1",
            input={
                "start_image": image_url,   # 🔴 КЛЮЧЕВО
                "prompt": "smooth cinematic motion, camera movement",
                "duration": 5,
                "fps": 24
            }
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(video_output.url) as resp:
                video_bytes = await resp.read()

        await message.answer_video(
            video=video_bytes,
            caption="🎉 Видео готово!",
            reply_markup=main_kb
        )

    except Exception as e:
        logging.exception("VIDEO ERROR")
        await message.answer(f"❌ Ошибка генерации:\n<code>{e}</code>")

    await state.clear()

# ================== FASTAPI + WEBHOOK ==================

@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.set_webhook(
        url=WEBHOOK_URL,
        allowed_updates=["message", "callback_query"]
    )
    logging.info("✅ Webhook установлен")
    yield
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

@app.post("/")
async def telegram_webhook(request: Request):
    update = await request.json()
    await dp.feed_raw_update(bot, update)
    return {"ok": True}

# ================== LOCAL ==================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)