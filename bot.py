import os
import logging
import replicate
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import CommandStart
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from dotenv import load_dotenv

# ─────────────────────────────────────
# ENV
# ─────────────────────────────────────
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://xxx.onrender.com/webhook
PORT = int(os.getenv("PORT", 8080))

# ─────────────────────────────────────
# LOGGING
# ─────────────────────────────────────
logging.basicConfig(level=logging.INFO)

# ─────────────────────────────────────
# BOT
# ─────────────────────────────────────
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

# ─────────────────────────────────────
# PROMPT ENHANCER
# ─────────────────────────────────────
def enhance_prompt_ru(text: str) -> str:
    return f"""
PHOTO-REALISTIC IMAGE.

TASK:
{text}

STYLE:
ultra realistic photo,
natural lighting,
35mm lens,
sharp focus,
cinematic look,
high detail

RULES:
- no cartoon
- no art style
- realistic proportions
"""

# ─────────────────────────────────────
# HANDLERS
# ─────────────────────────────────────
@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🖼 Я умею:\n"
        "— Генерировать изображения по тексту\n"
        "— Редактировать фото (добавлять / убирать объекты)\n\n"
        "📌 Примеры:\n"
        "• блондинка в черном платье\n"
        "• (фото) + «убери людей на фоне»"
    )

# 📸 Фото + текст → редактирование
@dp.message(F.photo)
async def edit_image(message: Message):
    if not message.caption:
        await message.answer("✏️ Напиши, что нужно сделать с фото")
        return

    await message.answer("🎨 Редактирую изображение...")

    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

    try:
        output = replicate_client.run(
            "qwen/qwen-image-edit-2511",
            input={
                "image": [image_url],
                "prompt": enhance_prompt_ru(message.caption),
                "aspect_ratio": "3:4"
            }
        )

        for img in output:
            await message.answer_photo(img.url)

    except Exception as e:
        logging.exception(e)
        await message.answer("❌ Ошибка редактирования")

# ✨ Только текст → генерация
@dp.message(F.text)
async def generate_image(message: Message):
    await message.answer("🎨 Генерирую изображение...")

    try:
        output = replicate_client.run(
            "qwen/qwen-image-edit-2511",
            input={
                "prompt": enhance_prompt_ru(message.text),
                "aspect_ratio": "3:4"
            }
        )

        for img in output:
            await message.answer_photo(img.url)

    except Exception as e:
        logging.exception(e)
        await message.answer("❌ Ошибка генерации")

# ─────────────────────────────────────
# WEBHOOK
# ─────────────────────────────────────
async def on_startup(app):
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_webhook(WEBHOOK_URL)
        logging.info(f"Webhook set: {WEBHOOK_URL}")
    except Exception:
        logging.exception("Webhook setup failed")

async def on_shutdown(app):
    await bot.session.close()

def main():
    app = web.Application()

    handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )
    handler.register(app, path="/webhook")

    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
