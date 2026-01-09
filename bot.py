import os
import logging
import asyncio
import replicate

from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher
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
PORT = int(os.getenv("PORT", 10000))

if not BOT_TOKEN or not REPLICATE_API_TOKEN:
    raise RuntimeError("BOT_TOKEN или REPLICATE_API_TOKEN не заданы")

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = "https://bot-iivideo.onrender.com/webhook"

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)

dp = Dispatcher()
app = FastAPI()

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

# ---------- PROMPT ----------
def enhance_prompt(text: str) -> str:
    return (
        "Ultra realistic photo. "
        f"{text}. "
        "Natural lighting, 35mm, high detail, cinematic realism."
    )

# ---------- REPLICATE ----------
def extract_urls(output):
    images = []

    if isinstance(output, list):
        for item in output:
            if isinstance(item, str):
                images.append(item)
            elif hasattr(item, "url"):
                images.append(item.url)

    elif isinstance(output, dict):
        images = output.get("images", [])

    return images


async def run_replicate(generate_func):
    try:
        output = await asyncio.wait_for(
            asyncio.to_thread(generate_func),
            timeout=120
        )
        return extract_urls(output)

    except asyncio.TimeoutError:
        logging.error("Replicate timeout")
        return None

    except ReplicateError as e:
        if "429" in str(e):
            return "RATE_LIMIT"
        logging.exception("Replicate API error")
        return None

    except Exception:
        logging.exception("Unknown replicate error")
        return None

# ---------- HANDLERS ----------
@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🖼 Напиши текст — сгенерирую изображение\n"
        "📸 Или отправь фото + текст — отредактирую"
    )

@dp.message(lambda m: m.text and not m.photo)
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
        await message.answer("⏳ Слишком много запросов. Подожди 10 секунд.")
        return

    if not result:
        await message.answer("❌ Не удалось сгенерировать изображение")
        return

    for url in result:
        await message.answer_photo(url)

@dp.message(lambda m: m.photo)
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
        await message.answer("⏳ Слишком много запросов. Подожди 10 секунд.")
        return

    if not result:
        await message.answer("❌ Не удалось обработать изображение")
        return

    for url in result:
        await message.answer_photo(url)

# ---------- WEBHOOK ----------
@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    update = Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}

# ---------- HEALTH ----------
@app.get("/")
async def health():
    return {"status": "ok"}

# ---------- LIFECYCLE ----------
@app.on_event("startup")
async def on_startup():
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("Webhook установлен")

@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()
    await bot.session.close()

# ---------- RUN ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
