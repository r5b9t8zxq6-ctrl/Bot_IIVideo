import os
import asyncio
import logging
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message
from aiogram.enums import ChatAction
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from aiohttp import web
import replicate

# =========================
# ENV
# =========================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://your-app.onrender.com/webhook
PORT = int(os.getenv("PORT", 10000))

if not BOT_TOKEN or not REPLICATE_API_TOKEN or not WEBHOOK_URL:
    raise RuntimeError("❌ Проверь BOT_TOKEN / REPLICATE_API_TOKEN / WEBHOOK_URL")

# =========================
# INIT
# =========================
logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

# =========================
# START
# =========================
@router.message(F.text == "/start")
async def start_cmd(message: Message):
    await message.answer(
        "Привет 👋\n\n"
        "Напиши любой текст — я сгенерирую изображение 🎨\n"
        "Бот работает через Replicate (Recraft v3)"
    )

# =========================
# MESSAGE HANDLER
# =========================
@router.message(F.text)
async def handle_prompt(message: Message):
    # ⚠️ ВАЖНО: ничего тяжелого тут не делаем
    asyncio.create_task(generate_and_send_image(message))

# =========================
# IMAGE GENERATION (BACKGROUND)
# =========================
async def generate_and_send_image(message: Message):
    thinking = await message.answer("🎨 Генерирую изображение...")
    await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)

    try:
        loop = asyncio.get_running_loop()

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

        # Recraft возвращает объект с .url
        image_url = output.url

        await message.answer_photo(
            photo=image_url,
            caption=message.text
        )

    except Exception as e:
        logging.exception("IMAGE ERROR")
        await message.answer("❌ Ошибка генерации изображения")

    finally:
        await thinking.delete()

# =========================
# WEBHOOK SETUP
# =========================
async def on_startup(bot: Bot):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("✅ Webhook установлен")

async def on_shutdown(bot: Bot):
    await bot.delete_webhook()
    logging.info("🛑 Webhook удалён")

# =========================
# MAIN (AIOHTTP)
# =========================
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
