import os
import asyncio
import logging
from contextlib import asynccontextmanager
from collections import defaultdict

import replicate
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Update,
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

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
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

# ================= FSM =================
class FlowState(StatesGroup):
    waiting_prompt = State()
    waiting_image_prompt = State()

# ================= QUEUE =================
user_locks = defaultdict(asyncio.Lock)

# ================= KEYBOARD =================
main_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🎨 TEXT → IMAGE → VIDEO",
                callback_data="text_image_video",
            )
        ],
        [
            InlineKeyboardButton(
                text="🖼 TEXT + IMAGE → VIDEO",
                callback_data="text_plus_image_video",
            )
        ],
    ]
)

# ================= HELPERS =================
def enhance_prompt(text: str) -> str:
    return (
        "Ultra realistic cinematic scene. "
        f"{text}. Natural lighting, 35mm, depth of field, dramatic motion."
    )


async def wait_prediction(
    prediction_id: str,
    timeout: int = 300,
    interval: int = 3,
):
    """
    Ожидание результата Replicate
    timeout — максимальное время (сек)
    interval — интервал опроса
    """
    elapsed = 0

    while elapsed < timeout:
        pred = replicate_client.predictions.get(prediction_id)

        if pred.status == "succeeded":
            return pred

        if pred.status == "failed":
            raise RuntimeError(pred.error)

        await asyncio.sleep(interval)
        elapsed += interval

    raise TimeoutError("Generation timeout")


# ================= HANDLERS =================
@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Выбери режим генерации 👇",
        reply_markup=main_kb,
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
    user_id = message.from_user.id
    prompt = message.text
    await state.clear()

    async with user_locks[user_id]:
        try:
            await message.answer("🎨 Генерирую изображение...")

            image_pred = replicate_client.predictions.create(
                model="prunaai/flux-fast",
                input={"prompt": enhance_prompt(prompt)},
            )

            image_result = await wait_prediction(image_pred.id)
            image_url = image_result.output[0]

            await message.answer_photo(image_url)
            await message.answer("🎬 Генерирую видео...")

            video_pred = replicate_client.predictions.create(
                model="kwaivgi/kling-v2.5-turbo-pro",
                input={
                    "start_image": image_url,
                    "prompt": prompt,
                    "duration": 5,
                    "fps": 24,
                },
            )

            video_result = await wait_prediction(video_pred.id)
            video_url = video_result.output[0]

            await message.answer_video(
                video=video_url,
                caption="🎉 Видео готово!",
                reply_markup=main_kb,
            )

        except TimeoutError:
            await message.answer(
                "⏳ Генерация заняла слишком много времени. Попробуй ещё раз.",
                reply_markup=main_kb,
            )

        except Exception as e:
            logging.exception(e)
            await message.answer(
                "❌ Ошибка генерации. Попробуй позже.",
                reply_markup=main_kb,
            )


# ---------- TEXT + IMAGE → VIDEO ----------
@router.message(FlowState.waiting_image_prompt, F.photo)
async def text_plus_image_to_video(message: Message, state: FSMContext):
    user_id = message.from_user.id
    prompt = message.caption or "Cinematic motion"
    await state.clear()

    async with user_locks[user_id]:
        try:
            photo = message.photo[-1]
            file = await bot.get_file(photo.file_id)
            image_url = (
                f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
            )

            await message.answer("🎬 Генерирую видео...")

            video_pred = replicate_client.predictions.create(
                model="kwaivgi/kling-v2.5-turbo-pro",
                input={
                    "start_image": image_url,
                    "prompt": enhance_prompt(prompt),
                    "duration": 5,
                    "fps": 24,
                },
            )

            video_result = await wait_prediction(video_pred.id)
            video_url = video_result.output[0]

            await message.answer_video(
                video=video_url,
                caption="🎉 Видео готово!",
                reply_markup=main_kb,
            )

        except TimeoutError:
            await message.answer(
                "⏳ Видео генерировалось слишком долго. Попробуй ещё раз.",
                reply_markup=main_kb,
            )

        except Exception as e:
            logging.exception(e)
            await message.answer(
                "❌ Ошибка генерации.",
                reply_markup=main_kb,
            )


# ================= FASTAPI + WEBHOOK =================
@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.set_webhook(
        url=WEBHOOK_URL,
        drop_pending_updates=True,
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

    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=10000,
    )