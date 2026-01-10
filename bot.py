import os
import re
import time
import asyncio
import logging
import secrets
import string
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
    Update,
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import CommandStart
from aiogram.exceptions import TelegramBadRequest

# ================= LOGGING =================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# ================= ENV =================

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not all([BOT_TOKEN, REPLICATE_API_TOKEN, WEBHOOK_URL]):
    raise RuntimeError("❌ Missing required ENV variables")

os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN

# ================= WEBHOOK SECRET SAFE =================

def sanitize_webhook_secret(secret: str | None) -> str:
    if secret and re.fullmatch(r"[A-Za-z0-9]{1,256}", secret):
        return secret

    logging.warning("⚠️ Invalid WEBHOOK_SECRET, generating safe one")
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(32))

WEBHOOK_SECRET = sanitize_webhook_secret(os.getenv("WEBHOOK_SECRET"))

# ================= BOT =================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

# ================= GLOBALS =================

generation_queue: asyncio.Queue = asyncio.Queue()
KLING_VERSION: str | None = None
MAX_RETRIES = 2
GEN_TIMEOUT = 300  # 5 minutes

# ================= FSM =================

class FlowState(StatesGroup):
    waiting_prompt = State()

# ================= KEYBOARD =================

main_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="🎬 TEXT → VIDEO", callback_data="text_video")]
    ]
)

# ================= HELPERS =================

def enhance_prompt(text: str) -> str:
    return (
        "Ultra realistic cinematic scene, dramatic lighting, smooth camera motion. "
        f"{text}. 35mm, depth of field, film grain."
    )

async def download_file(url: str) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()

def get_latest_kling_version() -> str:
    model = replicate_client.models.get("kwaivgi/kling-v2.5-turbo-pro")
    return model.latest_version.id

# ================= GENERATION =================

async def generate_video(chat_id: int, prompt: str):
    msg = await bot.send_message(chat_id, "⏳ Генерация… 0%")

    for attempt in range(1, MAX_RETRIES + 2):
        try:
            prediction = replicate_client.predictions.create(
                version=KLING_VERSION,
                input={
                    "prompt": enhance_prompt(prompt),
                    "duration": 5,
                    "fps": 24,
                },
            )

            start_time = time.time()
            last_progress = -1

            while True:
                prediction.reload()

                if prediction.status == "failed":
                    raise RuntimeError("Generation failed")

                if prediction.status == "succeeded":
                    break

                elapsed = time.time() - start_time
                if elapsed > GEN_TIMEOUT:
                    raise TimeoutError("Generation timeout")

                progress = min(95, int(elapsed / GEN_TIMEOUT * 100))
                if progress != last_progress:
                    try:
                        await msg.edit_text(f"⏳ Генерация… {progress}%")
                    except TelegramBadRequest:
                        pass
                    last_progress = progress

                await asyncio.sleep(3)

            output_url = prediction.output
            video_bytes = await download_file(output_url)

            await msg.delete()
            await bot.send_video(
                chat_id,
                video=video_bytes,
                caption="🎉 Видео готово!",
                reply_markup=main_kb,
            )
            return

        except Exception as e:
            logging.exception(f"❌ Attempt {attempt} failed")
            if attempt > MAX_RETRIES:
                await msg.edit_text(
                    "❌ Ошибка генерации.\nМодель перегружена или недоступна."
                )
                return
            await asyncio.sleep(5)

# ================= QUEUE WORKER =================

async def generation_worker():
    logging.info("✅ Generation worker started")
    while True:
        chat_id, prompt = await generation_queue.get()
        try:
            await generate_video(chat_id, prompt)
        finally:
            generation_queue.task_done()

# ================= HANDLERS =================

@router.message(CommandStart())
async def start(message: Message):
    await message.answer("Выбери режим 👇", reply_markup=main_kb)

@router.callback_query(F.data == "text_video")
async def text_video(cb: CallbackQuery, state: FSMContext):
    await state.set_state(FlowState.waiting_prompt)
    await cb.message.answer("✍️ Опиши сцену")
    await cb.answer()

@router.message(FlowState.waiting_prompt)
async def receive_prompt(message: Message, state: FSMContext):
    await state.clear()
    await generation_queue.put((message.chat.id, message.text))
    await message.answer("📥 Запрос добавлен в очередь")

# ================= FASTAPI + WEBHOOK =================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global KLING_VERSION

    KLING_VERSION = get_latest_kling_version()
    logging.info(f"✅ Kling version loaded: {KLING_VERSION}")

    asyncio.create_task(generation_worker())

    await bot.set_webhook(
        url=WEBHOOK_URL,
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=True,
    )
    logging.info("✅ Webhook set")

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