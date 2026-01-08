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
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 8000))

if not BOT_TOKEN or not REPLICATE_API_TOKEN or not WEBHOOK_URL:
    raise RuntimeError("❌ Проверь BOT_TOKEN / REPLICATE_API_TOKEN / WEBHOOK_URL")

logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

FIXED_SEED = 777777

# ================== PROMPT ENGINE ==================

def enhance_prompt(user_text: str) -> str:
    return f"""
ULTRA-REALISTIC PHOTO. STRICT RULES.

{user_text}

MANDATORY:
- Exact hair color
- Exact clothing color
- No substitutions
- No creativity

Photo style:
- DSLR 85mm
- Natural lighting
- Sharp focus
- Realistic colors
""".strip()

NEGATIVE_PROMPT = """
wrong hair color,
wrong clothes color,
color mismatch,
extra people,
anime,
cartoon,
painting,
blurry,
low quality
"""

# ================== UI ==================

def keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎨 Сгенерировать", callback_data="generate")]
        ]
    )

# ================== HANDLERS ==================

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Отправь описание изображения.\n\n"
        "Пример:\n"
        "«Блондинка в белых шортах на пляже, фотореализм»",
        reply_markup=keyboard()
    )

@dp.message(F.text)
async def save_prompt(message: Message):
    dp.workflow_data[message.chat.id] = message.text
    await message.answer("✅ Описание сохранено", reply_markup=keyboard())

@dp.callback_query(F.data == "generate")
async def generate(call):
    chat_id = call.message.chat.id
    user_prompt = dp.workflow_data.get(chat_id)

    if not user_prompt:
        await call.message.answer("❌ Сначала отправь описание")
        return

    await call.message.answer("⏳ Генерация...")

    try:
        loop = asyncio.get_running_loop()

        output = await loop.run_in_executor(
            None,
            lambda: replicate_client.run(
                "ideogram-ai/ideogram-v3-balanced",
                input={
                    "prompt": enhance_prompt(user_prompt),
                    "negative_prompt": NEGATIVE_PROMPT,
                    "seed": FIXED_SEED,
                    "guidance_scale": 12,
                    "aspect_ratio": "3:2"
                }
            )
        )

        image_url = output[0]["url"]
        await call.message.answer_photo(image_url)

    except Exception as e:
        logging.exception("GEN ERROR")
        await call.message.answer(f"❌ Ошибка генерации:\n{e}")

# ================== WEBHOOK ==================

async def webhook_handler(request: web.Request):
    update = Update.model_validate(await request.json())
    await dp.feed_webhook_update(bot, update)
    return web.Response(text="ok")

async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("✅ Webhook установлен")

async def on_shutdown(app):
    await bot.session.close()
    logging.info("🛑 Bot session closed")

def main():
    app = web.Application()
    app.router.add_post("/webhook", webhook_handler)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
