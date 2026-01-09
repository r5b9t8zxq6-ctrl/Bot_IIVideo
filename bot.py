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
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://your-app.onrender.com

if not BOT_TOKEN or not REPLICATE_API_TOKEN or not WEBHOOK_URL:
    raise RuntimeError("❌ BOT_TOKEN / REPLICATE_API_TOKEN / WEBHOOK_URL не заданы")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)

dp = Dispatcher()
replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

# ограничение параллельных запросов к Replicate
REPLICATE_SEMAPHORE = asyncio.Semaphore(2)

# ---------- FASTAPI LIFESPAN ----------
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
    urls = []
    if isinstance(output, list):
        for item in output:
            if isinstance(item, str):
                urls.append(item)
            elif hasattr(item, "url"):
                urls.append(item.url)
    return urls

async def run_replicate(fn):
    async with REPLICATE_SEMAPHORE:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(fn),
                timeout=120
            )
        except asyncio.TimeoutError:
            logging.error("⏳ Replicate timeout")
        except ReplicateError as e:
            if "429" in str(e):
                return "RATE_LIMIT"
            logging.exception("Replicate API error")
        except Exception:
            logging.exception("Unknown Replicate error")
        return None

# ---------- HANDLERS ----------
@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🖼 Напиши текст — сгенерирую изображение\n"
        "📸 Или отправь фото + текст — отредактирую"
    )

@dp.message(F.text & ~F.photo)
async def text_to_image(message: Message):
    await message.answer("🎨 Генерирую изображение...")

    def generate():
        return replicate_client.run(
            "qwen/qwen-image-edit-2511",
            input={
                "image": [],
                "prompt": enhance_prompt(message.text),
                "aspect_ratio": "3:4",
            },
        )

    result = await run_replicate(generate)

    if result == "RATE_LIMIT":
        await message.answer("⏳ Слишком много запросов. Попробуй позже.")
        return

    if not result:
        await message.answer("❌ Не удалось сгенерировать изображение")
        return

    for url in extract_urls(result):
        await message.answer_photo(url)

@dp.message(F.photo)
async def image_to_image(message: Message):
    await message.answer("🧠 Обрабатываю изображение...")

    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

    prompt = message.caption or "Improve photo quality"

    def generate():
        return replicate_client.run(
            "qwen/qwen-image-edit-2511",
            input={
                "image": [image_url],
                "prompt": enhance_prompt(prompt),
                "aspect_ratio": "3:4",
            },
        )

    result = await run_replicate(generate)

    if result == "RATE_LIMIT":
        await message.answer("⏳ Слишком много запросов. Попробуй позже.")
        return

    if not result:
        await message.answer("❌ Не удалось обработать изображение")
        return

    for url in extract_urls(result):
        await message.answer_photo(url)

# ---------- WEBHOOK ----------
@app.post("/webhook")
async def telegram_webhook(request: Request):
    update = Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}

# ---------- OPTIONAL HEALTHCHECK ----------
@app.get("/")
async def health():
    return {"status": "ok"}

# ---------- LOCAL RUN ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 10000)),
    )
