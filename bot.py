import os
import asyncio
import aiohttp
import tempfile
from contextlib import asynccontextmanager
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from fastapi import FastAPI, Request, HTTPException
from openai import OpenAI
import replicate

# ================= ENV =================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

openai_client = OpenAI(api_key=OPENAI_API_KEY)
replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

# ================= BOT =================
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()
router = Router()
dp.include_router(router)

# ================= GLOBAL =================
queue = asyncio.Queue()
KLING_MODEL = "kwaivgi/kling-v2.5-turbo-pro"
KLING_VERSION = None

# ================= UTILS =================
async def download_to_file(url: str, suffix: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=300) as r:
            r.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
                f.write(await r.read())
                return f.name


async def get_latest_kling_version():
    url = f"https://api.replicate.com/v1/models/{KLING_MODEL}"
    headers = {"Authorization": f"Token {REPLICATE_API_TOKEN}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as r:
            data = await r.json()
            return data["latest_version"]["id"]

# ================= QUEUE WORKER =================
async def queue_worker():
    while True:
        user_id, task = await queue.get()
        try:
            await process_task(user_id, task)
        except Exception as e:
            await bot.send_message(user_id, f"❌ Ошибка: {e}")
        finally:
            queue.task_done()

# ================= TASK PROCESS =================
async def process_task(user_id: int, task: str):
    progress = await bot.send_message(user_id, "⏳ Генерация… 0%")

    async def update(p):
        await bot.edit_message_text(
            f"⏳ Генерация… {p}%",
            chat_id=user_id,
            message_id=progress.message_id
        )

    await update(15)

    if task == "video":
        output = replicate_client.run(
            f"{KLING_MODEL}:{KLING_VERSION}",
            input={"prompt": "cinematic ultra realistic dramatic video"}
        )
        await update(70)
        path = await download_to_file(output["video"], ".mp4")
        await bot.send_video(user_id, FSInputFile(path), caption="🎬 Готово")

    elif task == "image":
        output = replicate_client.run(
            "bytedance/seedream-4",
            input={"prompt": "cinematic portrait, ultra detailed"}
        )
        path = await download_to_file(output[0].url, ".jpg")
        await bot.send_photo(user_id, FSInputFile(path))

    elif task == "music":
        output = replicate_client.run(
            "meta/musicgen:671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb",
            input={
                "prompt": "epic cinematic soundtrack",
                "model_version": "stereo-large",
                "output_format": "mp3"
            }
        )
        path = await download_to_file(output.url, ".mp3")
        await bot.send_audio(user_id, FSInputFile(path))

    else:
        response = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": task}]
        )
        await bot.send_message(user_id, response.choices[0].message.content)

    await update(100)

# ================= UI =================
def keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎬 Видео", callback_data="video"),
            InlineKeyboardButton(text="🖼 Изображение", callback_data="image")
        ],
        [
            InlineKeyboardButton(text="🎵 Музыка", callback_data="music"),
            InlineKeyboardButton(text="🤖 GPT", callback_data="gpt")
        ]
    ])

@router.message(F.text == "/start")
async def start(msg: Message):
    await msg.answer("🚀 AI Studio Bot", reply_markup=keyboard())

@router.callback_query()
async def cb(call: CallbackQuery):
    await call.answer()
    await call.message.answer("✍️ Отправь запрос")
    await queue.put((call.from_user.id, call.data))

@router.message(F.text)
async def text(msg: Message):
    await msg.answer("⏳ Добавлено в очередь")
    await queue.put((msg.from_user.id, msg.text))

# ================= FASTAPI LIFESPAN =================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global KLING_VERSION
    KLING_VERSION = await get_latest_kling_version()
    print("✅ Kling version:", KLING_VERSION)
    asyncio.create_task(queue_worker())
    await bot.set_webhook(WEBHOOK_URL, secret_token=WEBHOOK_SECRET)
    yield

app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(status_code=403)
    update = await request.json()
    await dp.feed_raw_update(bot, update)
    return {"ok": True}