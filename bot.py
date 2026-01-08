import os
import asyncio
import logging
from aiohttp import web
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Update
)
from aiogram.filters import CommandStart

import replicate

# ================== CONFIG ==================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://xxx.onrender.com/webhook

if not BOT_TOKEN or not REPLICATE_API_TOKEN or not WEBHOOK_URL:
    raise RuntimeError("❌ Проверь BOT_TOKEN / REPLICATE_API_TOKEN / WEBHOOK_URL")

logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

FIXED_SEED = 777777  # фиксация внешности

# ================== PROMPT ENGINE ==================

def enhance_prompt(user_text: str) -> str:
    """
    Усиливаем промт, чтобы модель НЕ игнорировала детали
    """
    return f"""
ULTRA-REALISTIC PROFESSIONAL PHOTO.
STRICTLY FOLLOW THE DESCRIPTION. DO NOT CHANGE ATTRIBUTES.

{user_text}

Rules (MANDATORY):
- Hair color, clothing color and gender MUST match exactly
- If user says blonde → ONLY blonde, NOT brunette
- If user says white shorts → ONLY white shorts
- No creative substitutions
- No random changes

Style:
- Photorealistic
- DSLR, 85mm lens
- Shallow depth of field
- Natural lighting
- High detail skin texture
- Accurate colors
- Sharp focus
""".strip()


NEGATIVE_PROMPT = """
wrong hair color,
wrong clothing color,
brunette if blonde specified,
blue clothes if white specified,
extra people,
distorted face,
cartoon,
anime,
painting,
low quality,
blurry
"""

# ================== KEYBOARD ==================

def generate_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎨 Сгенерировать", callback_data="generate")
            ]
        ]
    )

# ================== HANDLERS ==================

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Отправь описание изображения.\n\n"
        "Пример:\n"
        "«Блондинка в белых шортах, стоит на пляже, фотореализм»",
        reply_markup=generate_keyboard()
    )


@dp.message(F.text)
async def store_prompt(message: Message):
    # сохраняем промт во временное состояние (просто в message)
    message.bot_data = {"prompt": message.text}
    await message.answer("✅ Описание принято. Нажми «Сгенерировать» 👇",
                         reply_markup=generate_keyboard())


@dp.callback_query(F.data == "generate")
async def generate_image(callback):
    message = callback.message
    user_prompt = getattr(message, "bot_data", {}).get("prompt")

    if not user_prompt:
        await message.answer("❌ Сначала отправь описание")
        return

    await message.answer("⏳ Генерирую изображение...")

    prompt = enhance_prompt(user_prompt)

    try:
        loop = asyncio.get_running_loop()

        output = await loop.run_in_executor(
            None,
            lambda: replicate_client.run(
                "ideogram-ai/ideogram-v3-balanced",
                input={
                    "prompt": prompt,
                    "negative_prompt": NEGATIVE_PROMPT,
                    "seed": FIXED_SEED,
                    "guidance_scale": 11,
                    "aspect_ratio": "3:2"
                }
            )
        )

        if not output or not isinstance(output, list) or "url" not in output[0]:
            raise ValueError("Пустой или некорректный ответ Replicate")

        image_url = output[0]["url"]

        await message.answer_photo(
            image_url,
            caption="✅ Готово\n\n"
                    "Если что-то не совпало — уточни описание и попробуй ещё раз."
        )

    except Exception as e:
        logging.exception("GENERATION ERROR")
        await message.answer(f"❌ Ошибка генерации:\n{e}")

# ================== WEBHOOK ==================

async def webhook_handler(request: web.Request):
    data = await request.json()
    update = Update(**data)
    await dp.feed_webhook_update(bot, update)
    return web.Response(text="ok")


async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("✅ Webhook установлен")


def main():
    app = web.Application()
    app.router.add_post("/webhook", webhook_handler)
    app.on_startup.append(on_startup)
    web.run_app(app, port=int(os.environ.get("PORT", 8080)))


if __name__ == "__main__":
    main()
