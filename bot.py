import os
import asyncio
import logging
import aiofiles
import replicate
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://xxx.onrender.com

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

# ─────────────────────────────
# 🔒 FIXED IDENTITY (НЕ МЕНЯТЬ)
# ─────────────────────────────

FIXED_SEED = 284771

IDENTITY_PROFILE = """
Same person in all images.

Facial features:
Oval face shape.
Soft jawline.
Straight nose.
Medium-sized lips.
Symmetrical face.
Natural skin texture.

Eyes:
Almond-shaped eyes.
Neutral calm gaze.

Skin:
Light natural skin tone.
No freckles.
No scars.

IMPORTANT:
This is the SAME PERSON.
Face structure MUST NOT change.
"""

# ─────────────────────────────
# 🎨 RECOGNITION MAPS
# ─────────────────────────────

HAIR_MAP = {
    "блондин": "blonde hair",
    "блондинка": "blonde hair",
    "брюнет": "dark brown hair",
    "брюнетка": "dark brown hair",
    "рыж": "red hair",
}

COLOR_MAP = {
    "бел": "white",
    "черн": "black",
    "син": "blue",
    "красн": "red",
    "зел": "green",
    "желт": "yellow",
}

CLOTHES_MAP = {
    "шорты": "shorts",
    "платье": "dress",
    "курт": "jacket",
    "футбол": "t-shirt",
    "кофта": "sweater",
}

# ─────────────────────────────
# 🧠 PROMPT ENHANCER
# ─────────────────────────────

def enhance_prompt(user_text: str):
    text = user_text.lower()

    hair = "blonde hair"
    color = "white"
    clothes = "shorts"

    for k, v in HAIR_MAP.items():
        if k in text:
            hair = v

    for k, v in COLOR_MAP.items():
        if k in text:
            color = v

    for k, v in CLOTHES_MAP.items():
        if k in text:
            clothes = v

    positive_prompt = f"""
{IDENTITY_PROFILE}

Appearance:
Hair color is {hair}.
Hair MUST be {hair}.

Clothing:
She is wearing {color} {clothes}.
Clothing MUST be {clothes}.
Color MUST be {color}.

Photography:
Ultra realistic professional photo.
DSLR photo, 85mm lens.
Shallow depth of field.
Natural daylight.
Cinematic lighting.
High detail skin texture.
"""

    negative_prompt = """
different person
different face
face change
age change
wrong hair color
brunette, black hair, brown hair, red hair
wrong clothing
dress, skirt, jeans, pants, jacket
cartoon, anime, illustration, 3d
low quality, blurry
"""

    return positive_prompt.strip(), negative_prompt.strip()

# ─────────────────────────────
# 🎛 KEYBOARD
# ─────────────────────────────

def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎨 Сгенерировать изображение", callback_data="gen")],
        ]
    )

# ─────────────────────────────
# 🤖 HANDLERS
# ─────────────────────────────

@dp.message(F.text == "/start")
async def start(message: Message):
    await message.answer(
        "🧠 Напиши описание изображения:\n\n"
        "Пример:\n"
        "👉 блондинка в белых шортах\n\n"
        "Я зафиксирую внешность и создам реалистичное фото.",
        reply_markup=main_keyboard()
    )

@dp.callback_query(F.data == "gen")
async def ask_prompt(callback):
    await callback.message.answer("✍️ Напиши описание (одежда, цвет, образ):")

@dp.message(F.text)
async def generate_image(message: Message):
    await message.answer("⏳ Генерирую изображение...")

    prompt, negative = enhance_prompt(message.text)

    try:
        output = replicate_client.run(
            "ideogram-ai/ideogram-v3-balanced",
            input={
                "prompt": prompt,
                "negative_prompt": negative,
                "seed": FIXED_SEED,
                "guidance_scale": 11,
                "aspect_ratio": "3:2"
            }
        )

        image_url = output[0]
        await message.answer_photo(image_url, caption="✅ Готово")

    except Exception as e:
        logging.exception(e)
        await message.answer("❌ Ошибка генерации")

# ─────────────────────────────
# 🌐 WEBHOOK
# ─────────────────────────────

async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("✅ Webhook установлен")

async def on_shutdown(app):
    await bot.delete_webhook()

def main():
    app = web.Application()
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    ).register(app, path="/")

    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

if __name__ == "__main__":
    main()
