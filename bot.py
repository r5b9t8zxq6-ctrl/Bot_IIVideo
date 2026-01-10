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
from aiogram.filters import CommandStart

# ================= ENV =================

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN

logging.basicConfig(level=logging.INFO)

# ================= BOT =================

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# ================= FASTAPI =================

app = FastAPI()

# ================= FSM =================

class VideoState(StatesGroup):
    prompt = State()

# ================= KEYBOARD =================

main_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Сгенерировать видео", callback_data="gen_video")]
    ]
)

# ================= HANDLERS =================

@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Нажми кнопку 👇",
        reply_markup=main_kb
    )

@router.callback_query(F.data == "gen_video")
async def callback_gen_video(callback: CallbackQuery, state: FSMContext):
    await state.set_state(VideoState.prompt)
    await callback.message.answer("✍️ Напиши описание видео")
    await callback.answer()

@router.message(VideoState.prompt)
async def generate_video(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("⏳ Генерирую видео...")

    try:
        output = replicate.run(
            "kwaivgi/kling-v2.5-turbo-pro",
            input={"prompt": message.text}
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(output.url) as resp:
                video = await resp.read()

        await message.answer_video(
            video=video,
            caption="🎉 Готово!",
            reply_markup=main_kb
        )

    except Exception as e:
        logging.exception(e)
        await message.answer("❌ Ошибка генерации")

# ================= WEBHOOK =================

@app.on_event("startup")
async def startup():
    await bot.set_webhook(
        WEBHOOK_URL,
        allowed_updates=dp.resolve_used_update_types()  # 🔥 КЛЮЧ
    )
    logging.info("✅ Webhook установлен с allowed_updates")

@app.on_event("shutdown")
async def shutdown():
    await bot.session.close()

@app.post("/")
async def telegram_webhook(request: Request):
    update = await request.json()
    await dp.feed_raw_update(bot, update)
    return {"ok": True}

# ================= LOCAL =================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)