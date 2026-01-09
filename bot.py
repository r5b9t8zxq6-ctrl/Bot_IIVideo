import os
import asyncio
import logging
import replicate

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
    raise RuntimeError("❌ BOT_TOKEN / REPLICATE_API_TOKEN / WEBHOOK_URL не заданы")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()
app = FastAPI()

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)
REPLICATE_SEMAPHORE = asyncio.Semaphore(2)

# ---------- PROMPT ----------
def enhance_prompt(text: str) -> str:
    return (
        "Ultra realistic photo. "
        f"{text}. "
        "Natural lighting, 35mm, cinematic realism, high detail."
    )

def extract_urls(output):
    images = []
    if isinstance(output, list):
        for i in output:
            if isinstance(i, str):
                images.append(i)
            elif hasattr(i, "url"):
                images.append(i.url)
    return images

async def run_replicate_safe(fn):
    async with REPLICATE_SEMAPHORE:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(fn),
                timeout=120
            )
        except asyncio.TimeoutError:
            return "TIMEOUT"
        except ReplicateError as e:
            if "429" in str(e):
                return "RATE_LIMIT"
            logging.exception("Replicate error")
            return None
        except Exception:
            logging.exception("Unknown error")
            return None

# ---------- HANDLERS ----------
@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🖼 Напиши текст — сгенерирую изображение\n"
        "📸 Или отправь фото + текст — отредактирую"
    )

@dp.message(F.text)
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

    output = await run_replicate_safe(generate)

    if output == "RATE_LIMIT":
        await message.answer("⏳ Слишком много запросов. Подожди немного.")
        return

    if output in (None, "TIMEOUT"):
        await message.answer("❌ Ошибка генерации")
        return

    for url in extract_urls(output):
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

    output = await run_replicate_safe(generate)

    if output == "RATE_LIMIT":
        await message.answer("⏳ Слишком много запросов.")
        return

    if output in (None, "TIMEOUT"):
        await message.answer("❌ Ошибка обработки")
        return

    for url in extract_urls(output):
        await message.answer_photo(url)

# ---------- WEBHOOK ----------
@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}

@app.on_event("startup")
async def on_startup():
    await bot.set_webhook(
        url=f"{WEBHOOK_URL}/webhook",
        drop_pending_updates=True
    )
    logging.info("✅ Webhook установлен")

@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()
    await bot.session.close()

# ---------- RUN ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 10000)),
    )