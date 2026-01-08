import os
import asyncio
import logging
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

import replicate

# ======================
# ENV
# ======================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # ОБЯЗАТЕЛЬНО .../webhook
PORT = int(os.getenv("PORT", 10000))

logging.basicConfig(level=logging.INFO)

# ======================
# INIT
# ======================
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

# ======================
# HANDLERS
# ======================
@router.message(F.text == "/start")
async def start(message: Message):
    logging.info("📩 /start received")
    await message.answer("Бот работает ✅\nНапиши любой текст")

@router.message(F.text)
async def prompt_handler(message: Message):
    logging.info(f"📩 Message: {message.text}")
    await message.answer("🎨 Генерирую...")

    loop = asyncio.get_running_loop()
    try:
        output = await loop.run_in_executor(
            None,
            lambda: replicate_client.run(
                "recraft-ai/recraft-v3",
                input={
                    "prompt": message.text,
                    "size": "1365x1024"
                }
            )
        )

        await message.answer_photo(output.url)

    except Exception as e:
        logging.exception("IMAGE ERROR")
        await message.answer("❌ Ошибка генерации")

# ======================
# WEBHOOK
# ======================
async def on_startup(bot: Bot):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"✅ Webhook set: {WEBHOOK_URL}")

async def on_shutdown(bot: Bot):
    await bot.delete_webhook()
    logging.info("🛑 Webhook deleted")

# ======================
# APP
# ======================
def main():
    app = web.Application()

    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot
    ).register(app, path="/webhook")

    setup_application(app, dp, bot=bot, on_startup=on_startup, on_shutdown=on_shutdown)

    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
