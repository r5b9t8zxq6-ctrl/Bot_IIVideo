import os
import time
import asyncio
import logging
import aiohttp
import replicate

from fastapi import FastAPI, Request
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Update
)
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

if not BOT_TOKEN or not REPLICATE_API_TOKEN or not WEBHOOK_URL:
    raise RuntimeError("ENV variables missing")

os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN

logging.basicConfig(level=logging.INFO)

# ================= BOT =================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

# ================= FSM =================

class FlowState(StatesGroup):
    waiting_prompt = State()
    waiting_image_prompt = State()

# ================= KEYBOARD =================

main_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🎨 TEXT → IMAGE → VIDEO",
                callback_data="text_image_video"
            )
        ],
        [
            InlineKeyboardButton(
                text="🖼 TEXT + IMAGE → VIDEO",
                callback_data="text_plus_image_video"
            )
        ]
    ]
)

# ================= HELPERS =================

def enhance_prompt(text: str) -> str:
    return (
        "Ultra realistic cinematic scene. "
        f"{text}. Natural lighting, 35mm, depth of field, dramatic motion."
    )

def wait_for_prediction(prediction):
    while prediction.status not in ("succeeded", "failed"):
        time.sleep(3)
        prediction.reload()

    if prediction.status == "failed":
        raise RuntimeError("Generation failed")

    return prediction.output

async def download_file(url: str) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.read()

# ================= HANDLERS =================

@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Выбери режим генерации 👇",
        reply_markup=main_kb
    )

# ---------- BUTTONS ----------

@router.callback_query(F.data == "text_image_video")
async def text_image_video_btn(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(FlowState.waiting_prompt)
    await cb.message.answer("✍️ Напиши описание сцены")
    await cb.answer()

@router.callback_query(F.data == "text_plus_image_video")
async def text_plus_image_video_btn(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(FlowState.waiting_image_prompt)
    await cb.message.answer("🖼 Отправь изображение с описанием")
    await cb.answer()

# ---------- TEXT → IMAGE → VIDEO ----------

@router.message(FlowState.waiting_prompt)
async def text_to_image_to_video(message: Message, state: FSMContext):
    prompt = message.text
    await state.clear()

    await message.answer("🎨 Генерирую изображение...")

    image_prediction = replicate.predictions.create(
        model="prunaai/flux-fast",
        input={"prompt": enhance_prompt(prompt)}
    )

    image_output = await asyncio.to_thread(wait_for_prediction, image_prediction)
    image_url = image_output.url

    await message.answer_photo(image_url)

    await message.answer("🎬 Генерирую видео...")

    video_prediction = replicate.predictions.create(
        model="kwaivgi/kling-v2.5-turbo-pro",
        input={
            "start_image": image_url,
            "prompt": prompt,
            "duration": 5,
            "fps": 24
        }
    )

    video_output = await asyncio.to_thread(wait_for_prediction, video_prediction)
    video_url = video_output.url

    video_bytes = await download_file(video_url)

    await message.answer_video(
        video=video_bytes,
        caption="🎉 Видео готово!",
        reply_markup=main_kb
    )

# ---------- TEXT + IMAGE → VIDEO ----------

@router.message(FlowState.waiting_image_prompt, F.photo)
async def text_plus_image_to_video(message: Message, state: FSMContext):
    prompt = message.caption or "Cinematic motion"
    await state.clear()

    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

    await message.answer("🎬 Генерирую видео...")

    video_prediction = replicate.predictions.create(
        model="kwaivgi/kling-v2.5-turbo-pro",
        input={
            "start_image": image_url,
            "prompt": enhance_prompt(prompt),
            "duration": 5,
            "fps": 24
        }
    )

    video_output = await asyncio.to_thread(wait_for_prediction, video_prediction)
    video_url = video_output.url

    video_bytes = await download_file(video_url)

    await message.answer_video(
        video=video_bytes,
        caption="🎉 Видео готово!",
        reply_markup=main_kb
    )

# ================= FASTAPI + WEBHOOK =================

@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.set_webhook(
        url=WEBHOOK_URL,
        drop_pending_updates=True
    )
    logging.info("✅ Webhook установлен")
    yield
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

@app.post("/")
async def telegram_webhook(request: Request):
    update = Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}

# ================= LOCAL =================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("bot:app", host="0.0.0.0", port=10000)