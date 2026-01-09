import os
import asyncio
import logging

from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import StatesGroup, State
from aiogram.enums import ParseMode

import replicate
import aiohttp

# ================== НАСТРОЙКИ ==================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://bot-iivideo.onrender.com/webhook
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN

logging.basicConfig(level=logging.INFO)

# ================== BOT / DISPATCHER ==================

bot = Bot(BOT_TOKEN, parse_mode=ParseMode.HTML)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

router = Router()
dp.include_router(router)

# ================== FASTAPI ==================

app = FastAPI()

# ================== FSM ==================

class VideoFSM(StatesGroup):
    waiting_prompt = State()

# ================== КЛАВИАТУРЫ ==================

main_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Сгенерировать видео", callback_data="gen_video")]
    ]
)

# ================== HANDLERS ==================

@router.message(F.text == "/start")
async def start(message: Message):
    await message.answer(
        "Привет 👋\n\nНажми кнопку ниже, чтобы сгенерировать видео 🎬",
        reply_markup=main_kb,
    )


@router.callback_query(F.data == "gen_video")
async def gen_video(callback: CallbackQuery, state: FSMContext):
    await state.set_state(VideoFSM.waiting_prompt)
    await callback.message.answer(
        "✍️ Опиши видео (например: <i>a woman is dancing</i>)"
    )
    await callback.answer()


@router.message(VideoFSM.waiting_prompt)
async def process_prompt(message: Message, state: FSMContext):
    prompt = message.text
    await state.clear()

    await message.answer("⏳ Генерирую видео, это может занять 1–2 минуты...")

    try:
        output = replicate.run(
            "kwaivgi/kling-v2.5-turbo-pro",
            input={"prompt": prompt},
        )

        video_url = output.url

        async with aiohttp.ClientSession() as session:
            async with session.get(video_url) as resp:
                video_bytes = await resp.read()

        await message.answer_video(
            video=video_bytes,
            caption="🎉 Готово!\n\nХочешь ещё одно видео?",
            reply_markup=main_kb,
        )

    except Exception as e:
        logging.exception(e)
        await message.answer("❌ Ошибка генерации. Попробуй позже.")

# ================== WEBHOOK ==================

@app.on_event("startup")
async def on_startup():
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("✅ Webhook установлен")


@app.on_event("shutdown")
async def on_shutdown():
    await bot.session.close()


@app.post("/webhook")
async def webhook(request: Request):
    update = await request.json()
    await dp.feed_raw_update(bot, update)
    return {"status": "ok"}

# ================== LOCAL RUN (НЕ ДЛЯ RENDER) ==================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)