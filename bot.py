import os
import logging
import asyncio
import replicate
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import CommandStart
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

# 🧠 Улучшение промта
def enhance_prompt_ru(text: str) -> str:
    return f"""
PHOTO-REALISTIC IMAGE EDIT.

TASK:
{text}

STYLE:
ultra realistic photo, natural lighting, 35mm lens,
sharp focus, high detail, cinematic look

RULES:
- Keep realism
- No random changes
- No art style
"""

# ▶️ /start
@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🖼 Я умею:\n"
        "1️⃣ Генерировать изображения по тексту\n"
        "2️⃣ Редактировать фото (добавлять / убирать объекты)\n\n"
        "📌 Просто:\n"
        "— напиши текст\n"
        "— или отправь фото + текст"
    )

# 🖼 Фото + текст = редактирование
@dp.message(F.photo)
async def image_edit(message: Message):
    if not message.caption:
        await message.answer("✏️ Напиши, что сделать с этим фото")
        return

    await message.answer("🎨 Редактирую изображение...")

    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

    prompt = enhance_prompt_ru(message.caption)

    try:
        output = replicate_client.run(
            "qwen/qwen-image-edit-2511",
            input={
                "image": [image_url],
                "prompt": prompt,
                "aspect_ratio": "3:4"
            }
        )

        for img in output:
            await message.answer_photo(img.url)

    except Exception as e:
        logging.exception(e)
        await message.answer("❌ Ошибка редактирования")

# ✨ Только текст = генерация
@dp.message(F.text)
async def image_generate(message: Message):
    await message.answer("🎨 Генерирую изображение...")

    prompt = enhance_prompt_ru(message.text)

    try:
        output = replicate_client.run(
            "qwen/qwen-image-edit-2511",
            input={
                "prompt": prompt,
                "aspect_ratio": "3:4"
            }
        )

        for img in output:
            await message.answer_photo(img.url)

    except Exception as e:
        logging.exception(e)
        await message.answer("❌ Ошибка генерации")

# 🌐 WEBHOOK
async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)

async def on_shutdown(app):
    await bot.delete_webhook()

def main():
    app = web.Application()

    webhook_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )

    webhook_handler.register(app, path="/webhook")
    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

if __name__ == "__main__":
    main()
