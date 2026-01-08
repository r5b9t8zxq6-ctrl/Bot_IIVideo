import os
import logging
import aiohttp
import replicate

from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message, BufferedInputFile
from aiogram.filters import CommandStart
from aiohttp import web
from dotenv import load_dotenv

# -------------------- ENV --------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://bot-iivideo.onrender.com/

replicate.Client(api_token=REPLICATE_API_TOKEN)

logging.basicConfig(level=logging.INFO)

# -------------------- PROMPT --------------------
def enhance_prompt(text: str):
    prompt = f"""
Ultra realistic professional photography.

STRICT REQUIREMENTS:
{text}

Rules:
- hair color EXACT
- clothes color EXACT
- no reinterpretation
- no color deviation

8k, sharp focus, natural light, professional color grading.
"""

    negative = """
wrong hair color,
wrong clothes color,
different outfit,
artistic reinterpretation,
cartoon,
illustration,
painting,
low quality,
blurry
"""
    return prompt.strip(), negative.strip()

# -------------------- BOT --------------------
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Напиши описание изображения.\n\n"
        "Пример:\n"
        "👉 блондинка в белых шортах на пляже"
    )

@router.message()
async def generate(message: Message):
    prompt, negative = enhance_prompt(message.text)
    await message.answer("⏳ Генерирую изображение...")

    try:
        output = replicate.run(
            "ideogram-ai/ideogram-v3-balanced",
            input={
                "prompt": prompt,
                "negative_prompt": negative,
                "aspect_ratio": "3:2"
            }
        )

        image_url = output[0] if isinstance(output, list) else output.url

        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as r:
                image_bytes = await r.read()

        photo = BufferedInputFile(image_bytes, filename="image.png")
        await message.answer_photo(photo, caption="✅ Готово")

    except Exception as e:
        logging.exception(e)
        await message.answer("❌ Ошибка генерации")

# -------------------- WEBHOOK --------------------
async def handle_update(request):
    data = await request.json()
    await dp.feed_webhook_update(bot, data)
    return web.Response(text="OK")

async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("✅ Webhook установлен")

async def on_shutdown(app):
    await bot.session.close()
    logging.info("🛑 Bot session closed")

# -------------------- APP --------------------
app = web.Application()
app.router.add_post("/", handle_update)  # 👈 ВАЖНО
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=8000)
