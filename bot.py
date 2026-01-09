import os
import asyncio
import logging
import replicate
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, Update
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv
from replicate.exceptions import ReplicateError

# ---------- INIT ----------
load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not BOT_TOKEN or not REPLICATE_API_TOKEN or not WEBHOOK_URL:
    raise RuntimeError("ENV variables missing")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()
replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)
REPLICATE_SEMAPHORE = asyncio.Semaphore(2)

# ---------- LIFESPAN ----------
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

# ---------- HELPERS ----------
def enhance_prompt(text: str) -> str:
    return (
        "Ultra realistic photo. "
        f"{text}. Natural lighting, 35mm, cinematic realism."
    )

def extract_urls(output):
    return [
        i if isinstance(i, str) else i.url
        for i in output or []
        if isinstance(i, (str, object))
    ]

async def run_replicate(fn):
    async with REPLICATE_SEMAPHORE:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(fn),
                timeout=120
            )
        except ReplicateError as e:
            if "429" in str(e):
                return "RATE_LIMIT"
        except Exception:
            logging.exception("Replicate error")
        return None

# ---------- HANDLERS ----------
@dp.message(CommandStart())
async def start(message: Message):
    await message.answer("🖼 Напиши текст или отправь фото")

@dp.message(F.text)
async def text_to_image(message: Message):
    await message.answer("🎨 Генерирую...")

    def gen():
        return replicate_client.run(
            "qwen/qwen-image-edit-2511",
            input={
                "image": [],
                "prompt": enhance_prompt(message.text),
                "aspect_ratio": "3:4",
            },
        )

    result = await run_replicate(gen)
    if not result:
        await message.answer("❌ Ошибка")
        return

    for url in extract_urls(result):
        await message.answer_photo(url)

@dp.message(F.photo)
async def image_to_image(message: Message):
    await message.answer("🧠 Обрабатываю...")

    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

    def gen():
        return replicate_client.run(
            "qwen/qwen-image-edit-2511",
            input={
                "image": [image_url],
                "prompt": enhance_prompt(message.caption or "Improve photo"),
                "aspect_ratio": "3:4",
            },
        )

    result = await run_replicate(gen)
    if not result:
        await message.answer("❌ Ошибка")
        return

    for url in extract_urls(result):
        await message.answer_photo(url)

# ---------- WEBHOOK ----------
@app.post("/webhook")
async def telegram_webhook(request: Request):
    update = Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}

# ---------- RUN ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 10000)),
    )
