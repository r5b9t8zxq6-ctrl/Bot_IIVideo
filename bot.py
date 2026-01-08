import os
import asyncio
import logging
import random

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, Update
from aiogram.enums import ChatAction
from aiohttp import web
from dotenv import load_dotenv
import replicate

# =====================
# ENV
# =====================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not BOT_TOKEN or not REPLICATE_API_TOKEN or not WEBHOOK_URL:
    raise RuntimeError("ENV variables missing")

# =====================
# INIT
# =====================
logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

THINK_STICKERS = [
    "CAACAgIAAxkBAAEVFBFpXQKdMXKrifJH_zqRZaibCtB-lQACtwAD9wLID5Dxtgc7IUgdOAQ",
    "CAACAgIAAxkBAAEVFA9pXQJ_YAVXD8qH9yNaYjarJi04ugACiQoAAnFuiUvTl1zojCsDsDgE",
]

RECRAFT_MODEL = "recraft-ai/recraft-v3"

# =====================
# HANDLER
# =====================
@router.message(F.text)
async def handle_prompt(message: Message):
    thinking = await message.answer_sticker(random.choice(THINK_STICKERS))
    await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)

    try:
        loop = asyncio.get_running_loop()

        output = await loop.run_in_executor(
            None,
            lambda: replicate_client.run(
                RECRAFT_MODEL,
                input={
                    "prompt": message.text,
                    "size": "1365x1024"
                }
            )
        )

        # Recraft возвращает File-like объект
        image_url = output.url

        await message.answer_photo(
            photo=image_url,
            caption=message.text
        )

    except Exception:
        logging.exception("IMAGE ERROR")
        await message.answer("❌ Ошибка генерации изображения")

    finally:
        await thinking.delete()

# =====================
# WEBHOOK
# =====================
async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("Webhook установлен")

async def on_shutdown(app):
    await bot.delete_webhook()
    await bot.session.close()

async def handle_webhook(request: web.Request):
    update = Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return web.Response()

def main():
    app = web.Application()
    app.router.add_post("/webhook", handle_webhook)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))

if __name__ == "__main__":
    main()
