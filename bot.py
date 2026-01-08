import os
import asyncio
import logging
from dotenv import load_dotenv

from aiohttp import web
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, Update

import replicate

# =======================
# ENV
# =======================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 8000))

if not BOT_TOKEN or not REPLICATE_API_TOKEN or not WEBHOOK_URL:
    raise RuntimeError("❌ Не заданы ENV переменные")

# =======================
# LOG
# =======================
logging.basicConfig(level=logging.INFO)

# =======================
# BOT
# =======================
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

# =======================
# START
# =======================
@router.message(F.text == "/start")
async def start(message: Message):
    await message.answer(
        "👋 Пришли текст — я сгенерирую изображение через Google Imagen-3"
    )

# =======================
# MESSAGE HANDLER
# =======================
@router.message(F.text)
async def handle_prompt(message: Message):
    # ❗ ничего долгого здесь
    asyncio.create_task(generate_and_send_image(message))

# =======================
# IMAGE GENERATION (BACKGROUND)
# =======================
async def generate_and_send_image(message: Message):
    thinking = await message.answer("🎨 Генерирую изображение...")

    try:
        loop = asyncio.get_running_loop()

        output = await loop.run_in_executor(
            None,
            lambda: replicate_client.run(
                "google/imagen-3",
                input={
                    "prompt": message.text,
                    "safety_filter_level": "block_medium_and_above"
                }
            )
        )

        # Imagen может вернуть список или одиночный FileOutput
        if isinstance(output, list):
            image = output[0]
        else:
            image = output

        image_url = image.url

        await message.answer_photo(
            photo=image_url,
            caption=message.text
        )

    except Exception:
        logging.exception("IMAGE ERROR")
        await message.answer("❌ Ошибка генерации изображения")

    finally:
        await thinking.delete()

# =======================
# WEBHOOK
# =======================
async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("✅ Webhook установлен")

async def on_shutdown(app):
    await bot.delete_webhook()
    await bot.session.close()

async def webhook_handler(request: web.Request):
    update = Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return web.Response()

# =======================
# SERVER
# =======================
def main():
    app = web.Application()
    app.router.add_post("/webhook", webhook_handler)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
