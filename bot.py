import os
import asyncio
import logging
import aiohttp
import aiofiles
import replicate

from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiohttp import web
from dotenv import load_dotenv

# -------------------- ENV --------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

replicate.Client(api_token=REPLICATE_API_TOKEN)

logging.basicConfig(level=logging.INFO)

# -------------------- AI PROMPT LOGIC --------------------
def enhance_prompt(user_text: str) -> tuple[str, str]:
    base = f"""
Ultra realistic professional photography.
The subject MUST strictly follow these attributes:
{user_text}

Important rules:
- hair color must match EXACTLY
- clothes color must match EXACTLY
- no color variation
- no style deviation
- no reinterpretation

High detail, natural lighting, sharp focus, 8k quality,
cinematic composition, professional color grading.
"""

    negative = """
wrong hair color,
wrong clothes color,
different outfit,
brunette if blonde requested,
blue clothes if white requested,
artistic reinterpretation,
fantasy style,
cartoon,
illustration,
painting,
low quality,
blurry
"""
    return base.strip(), negative.strip()

# -------------------- BOT SETUP --------------------
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# -------------------- UI --------------------
def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎨 Сгенерировать изображение", callback_data="gen")]
        ]
    )

# -------------------- HANDLERS --------------------
@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Отправь описание изображения.\n\n"
        "Пример:\n"
        "👉 блондинка в белых шортах на пляже",
        reply_markup=main_keyboard()
    )

@router.callback_query(lambda c: c.data == "gen")
async def generate(callback):
    await callback.answer("✏️ Напиши описание изображение сообщением")

@router.message()
async def generate_image(message: Message):
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
            async with session.get(image_url) as resp:
                img = await resp.read()

        photo = BufferedInputFile(img, filename="image.png")
        await message.answer_photo(photo, caption="✅ Готово")

    except Exception as e:
        logging.exception(e)
        await message.answer("❌ Ошибка генерации. Попробуй изменить описание.")

# -------------------- WEBHOOK --------------------
async def webhook_handler(request):
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
app.router.add_post("/webhook", webhook_handler)
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=8000)
