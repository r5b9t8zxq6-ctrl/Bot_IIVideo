import os
import logging
import aiohttp
import replicate

from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage

# ================== ENV ==================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://bot-iivideo.onrender.com/webhook
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

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

# ================== FASTAPI ==================

app = FastAPI()

# ================== FSM ==================

class VideoFSM(StatesGroup):
    waiting_prompt = State()

# ================== KEYBOARDS ==================

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
        reply_markup=main_kb
    )

@router.callback_query(F.data == "gen_video")
async def ask_prompt(callback: CallbackQuery, state: FSMContext):
    await state.set_state(VideoFSM.waiting_prompt)
    await callback.message.answer("✍️ Напиши описание видео\n<i>Например: a woman is dancing</i>")
    await callback.answer()

@router.message(VideoFSM.waiting_prompt)
async def generate_video(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("⏳ Генерирую видео, подожди 1–2 минуты...")

    try:
        output = replicate.run(
            "kwaivgi/kling-v2.5-turbo-pro",
            input={"prompt": message.text}
        )

        video_url = output.url

        async with aiohttp.ClientSession() as session:
            async with session.get(video_url) as resp:
                video = await resp.read()

        await message.answer_video(
            video=video,
            caption="🎉 Готово! Хочешь ещё?",
            reply_markup=main_kb
        )

    except Exception as e:
        logging.exception(e)
        await message.answer("❌ Ошибка генерации. Попробуй позже.")

# ================== WEBHOOK ==================

@app.on_event("startup")
async def startup():
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("✅ Webhook установлен")

@app.on_event("shutdown")
async def shutdown():
    await bot.session.close()

@app.post("/webhook")
async def telegram_webhook(request: Request):
    update = await request.json()
    await dp.feed_raw_update(bot, update)
    return {"ok": True}

# ================== LOCAL ==================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)