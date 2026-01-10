import os
import asyncio
import aiohttp
import tempfile
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

replicate.Client(api_token=REPLICATE_API_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ================= BOT =================
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()
router = Router()
dp.include_router(router)

# ================= FASTAPI =================
app = FastAPI()

# ================= QUEUE =================
queue = asyncio.Queue()
worker_running = False

# ================= GLOBAL =================
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
    headers = {
        "Authorization": f"Token {REPLICATE_API_TOKEN}"
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as r:
            data = await r.json()
            return data["latest_version"]["id"]


# ================= STARTUP =================
@app.on_event("startup")
async def startup():
    global KLING_VERSION, worker_running
    KLING_VERSION = await get_latest_kling_version()
    print(f"✅ Kling version: {KLING_VERSION}")

    if not worker_running:
        asyncio.create_task(queue_worker())
        worker_running = True

    await bot.set_webhook(
        url=WEBHOOK_URL,
        secret_token=WEBHOOK_SECRET
    )


# ================= WEBHOOK =================
@app.post("/webhook")
async def webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(status_code=403)

    data = await request.json()
    await dp.feed_raw_update(bot, data)
    return {"ok": True}


# ================= UI =================
def main_keyboard():
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


# ================= HANDLERS =================
@router.message(F.text == "/start")
async def start(msg: Message):
    await msg.answer(
        "🚀 <b>AI Studio Bot</b>\n\nВыбери, что создать:",
        reply_markup=main_keyboard()
    )


@router.callback_query()
async def callbacks(call: CallbackQuery):
    await call.message.answer("✍️ Отправь текстовый запрос следующим сообщением.")
    await call.answer()
    await queue.put((call.from_user.id, call.data))


@router.message(F.text)
async def handle_text(msg: Message):
    await queue.put((msg.from_user.id, msg.text))
    await msg.answer("⏳ Запрос добавлен в очередь…")


# ================= WORKER =================
async def queue_worker():
    while True:
        user_id, payload = await queue.get()
        try:
            await process_task(user_id, payload)
        except Exception as e:
            await bot.send_message(user_id, f"❌ Ошибка: {e}")
        finally:
            queue.task_done()


# ================= TASK PROCESS =================
async def process_task(user_id: int, payload: str):
    progress = await bot.send_message(user_id, "⏳ Генерация… 0%")

    def update(p):
        return bot.edit_message_text(
            f"⏳ Генерация… {p}%",
            chat_id=user_id,
            message_id=progress.message_id
        )

    await update(10)

    # ===== VIDEO =====
    if payload == "video":
        output = replicate.run(
            f"{KLING_MODEL}:{KLING_VERSION}",
            input={"prompt": "cinematic dramatic video, ultra realistic"}
        )

        await update(70)
        video_path = await download_to_file(output["video"], ".mp4")

        await bot.send_video(
            user_id,
            video=FSInputFile(video_path),
            caption="🎬 Готово!"
        )

    # ===== IMAGE =====
    elif payload == "image":
        output = replicate.run(
            "bytedance/seedream-4",
            input={"prompt": "cinematic portrait, ultra detailed"}
        )
        img_path = await download_to_file(output[0].url, ".jpg")
        await bot.send_photo(user_id, FSInputFile(img_path))

    # ===== MUSIC =====
    elif payload == "music":
        output = replicate.run(
            "meta/musicgen:671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb",
            input={
                "prompt": "epic cinematic soundtrack",
                "model_version": "stereo-large",
                "output_format": "mp3"
            }
        )
        audio_path = await download_to_file(output.url, ".mp3")
        await bot.send_audio(user_id, FSInputFile(audio_path))

    # ===== GPT =====
    else:
        response = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": payload}]
        )
        await bot.send_message(user_id, response.choices[0].message.content)

    await update(100)