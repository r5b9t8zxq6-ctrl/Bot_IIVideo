import os
import asyncio
import logging
import replicate
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, Update,
    InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery
)
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
from replicate.exceptions import ReplicateError

# ================= INIT =================
load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not BOT_TOKEN or not REPLICATE_API_TOKEN or not WEBHOOK_URL:
    raise RuntimeError("Missing ENV variables")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)

storage = MemoryStorage()
dp = Dispatcher(storage=storage)

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)
REPLICATE_SEMAPHORE = asyncio.Semaphore(2)

# ================= FSM =================
class Mode(StatesGroup):
    flux_text = State()
    qwen_text = State()
    qwen_image = State()
    video_image = State()

# ================= UI =================
def mode_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Текст → Изображение (Fast)", callback_data="flux")],
        [InlineKeyboardButton(text="🎨 Текст → Изображение (Pro)", callback_data="qwen_text")],
        [InlineKeyboardButton(text="🧠 Фото → Фото", callback_data="qwen_image")],
        [InlineKeyboardButton(text="🎬 Фото → Видео", callback_data="video")]
    ])

# ================= HELPERS =================
def enhance_prompt(text: str) -> str:
    return (
        "Ultra realistic, cinematic lighting, high detail. "
        f"{text}"
    )

def extract_urls(output):
    urls = []
    if isinstance(output, list):
        for item in output:
            if isinstance(item, str):
                urls.append(item)
            elif hasattr(item, "url"):
                urls.append(item.url)
    return urls

async def run_replicate(fn, timeout=300):
    async with REPLICATE_SEMAPHORE:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(fn),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            logging.error("Replicate timeout")
        except ReplicateError as e:
            logging.error(f"Replicate error: {e}")
        except Exception:
            logging.exception("Unknown replicate error")
        return None

# ================= START =================
@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Выбери режим 👇",
        reply_markup=mode_keyboard()
    )

# ================= CALLBACKS =================
@dp.callback_query(F.data == "flux")
async def cb_flux(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Mode.flux_text)
    await callback.message.answer("✍️ Напиши текст")
    await callback.answer()

@dp.callback_query(F.data == "qwen_text")
async def cb_qwen_text(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Mode.qwen_text)
    await callback.message.answer("🎨 Опиши сцену")
    await callback.answer()

@dp.callback_query(F.data == "qwen_image")
async def cb_qwen_image(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Mode.qwen_image)
    await callback.message.answer("🖼 Отправь фото + описание")
    await callback.answer()

@dp.callback_query(F.data == "video")
async def cb_video(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Mode.video_image)
    await callback.message.answer("🎬 Отправь фото + описание движения")
    await callback.answer()

# ================= FLUX =================
@dp.message(Mode.flux_text, F.text)
async def flux_text(message: Message):
    await message.answer("⚡ Генерирую изображение...")

    def gen():
        return replicate_client.run(
            "prunaai/flux-fast",
            input={"prompt": message.text}
        )

    result = await run_replicate(gen)

    if result:
        await message.answer_photo(result.url)
    else:
        await message.answer("❌ Ошибка генерации")

# ================= QWEN TEXT =================
@dp.message(Mode.qwen_text, F.text)
async def qwen_text(message: Message):
    await message.answer("🎨 Генерирую изображение...")

    def gen():
        return replicate_client.run(
            "qwen/qwen-image-edit-2511",
            input={
                "image": [],
                "prompt": enhance_prompt(message.text),
                "aspect_ratio": "3:4"
            }
        )

    result = await run_replicate(gen)

    if not result:
        await message.answer("❌ Ошибка")
        return

    for url in extract_urls(result):
        await message.answer_photo(url)

# ================= QWEN IMAGE =================
@dp.message(Mode.qwen_image, F.photo)
async def qwen_image(message: Message):
    await message.answer("🧠 Обрабатываю фото...")

    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

    def gen():
        return replicate_client.run(
            "qwen/qwen-image-edit-2511",
            input={
                "image": [image_url],
                "prompt": enhance_prompt(message.caption or "Improve photo"),
                "aspect_ratio": "3:4"
            }
        )

    result = await run_replicate(gen)

    if not result:
        await message.answer("❌ Ошибка")
        return

    for url in extract_urls(result):
        await message.answer_photo(url)

# ================= VIDEO (KLING) =================
@dp.message(Mode.video_image, F.photo)
async def image_to_video(message: Message):
    await message.answer("🎬 Генерирую видео (это может занять до 2 минут)...")

    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

    prompt = message.caption or "Smooth cinematic motion"

    def gen():
        return replicate_client.run(
            "kwaivgi/kling-v2.5-turbo-pro",
            input={
                "image": image_url,
                "prompt": prompt
            }
        )

    result = await run_replicate(gen, timeout=420)

    if not result:
        await message.answer("❌ Ошибка генерации видео")
        return

    await message.answer_video(result.url)

# ================= FASTAPI =================
@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.set_webhook(
        url=f"{WEBHOOK_URL}/webhook",
        drop_pending_updates=True
    )
    logging.info("✅ Webhook установлен")
    yield
    await bot.delete_webhook()
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def telegram_webhook(request: Request):
    update = Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}

# ================= RUN =================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 10000))
    )