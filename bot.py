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
    Update,
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import CommandStart
from aiogram.exceptions import TelegramBadRequest

# ================= ENV =================

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

if not all([BOT_TOKEN, REPLICATE_API_TOKEN, WEBHOOK_URL, WEBHOOK_SECRET]):
    raise RuntimeError("❌ Missing ENV variables")

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

# ================= GLOBALS =================

generation_queue: asyncio.Queue = asyncio.Queue()
KLING_VERSION: str | None = None

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
        "Ultra realistic cinematic scene. "
        f"{text}. Natural lighting, 35mm, depth of field, dramatic motion."
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

    try:
        prediction = await asyncio.to_thread(
            replicate_client.predictions.create,
            version=KLING_VERSION,
            input={
                "prompt": enhance_prompt(prompt),
                "duration": 5,
                "fps": 24,
            },
        )

        start = time.time()
        progress = 0

        while True:
            await asyncio.sleep(3)
            prediction.reload()

            if prediction.status == "failed":
                raise RuntimeError("Generation failed")

            # ✅ КЛЮЧЕВО: ждём не только succeeded, но и output
            if prediction.status == "succeeded" and prediction.output:
                break

            if time.time() - start > 420:
                raise TimeoutError("Generation timeout")

            progress = min(progress + 5, 95)
            try:
                await msg.edit_text(f"⏳ Генерация… {progress}%")
            except TelegramBadRequest:
                pass

        # ================= OUTPUT PARSE =================

        output = prediction.output
        video_url = None

        if isinstance(output, list):
            for item in output:
                if isinstance(item, dict):
                    video_url = item.get("video") or item.get("url")
                    if video_url:
                        break

        elif isinstance(output, dict):
            video_url = output.get("video") or output.get("url")

        if not video_url:
            raise RuntimeError(f"Video URL not found. Output: {output}")

        video_bytes = await download_file(video_url)

        await msg.delete()
        await bot.send_video(
            chat_id,
            video=video_bytes,
            caption="🎉 Видео готово!",
            reply_markup=main_kb,
        )

    except Exception:
        logging.exception("❌ Generation error")
        try:
            await msg.edit_text(
                "❌ Ошибка генерации.\nМодель может быть перегружена."
            )
        except TelegramBadRequest:
            pass

# ================= QUEUE WORKER =================

async def generation_worker():
    logging.info("✅ Generation worker started")
    while True:
        chat_id, prompt = await generation_queue.get()
        try:
            await generate_video(chat_id, prompt)
        except Exception:
            logging.exception("❌ Worker error prevented")
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

# ================= FASTAPI =================

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