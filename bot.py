import os
import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message, Update
from aiogram.filters import CommandStart

import replicate
from dotenv import load_dotenv

# =====================
# ENV
# =====================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://xxx.onrender.com
WEBHOOK_PATH = "/webhook"

logging.basicConfig(level=logging.INFO)

# =====================
# INIT
# =====================
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

generation_lock = asyncio.Semaphore(1)

# =====================
# HANDLERS
# =====================
@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Привет!\n\n"
        "Напиши текст — я сгенерирую изображение.\n"
        "⏳ Обычно 20–60 секунд."
    )

@router.message()
async def generate_image(message: Message):
    prompt = message.text.strip()
    await message.answer("🎨 Генерирую изображение...")

    loop = asyncio.get_running_loop()

    try:
        async with generation_lock:
            output = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: replicate_client.run(
                        "google/imagen-3",
                        input={
                            "prompt": prompt,
                            "safety_filter_level": "block_medium_and_above",
                        }
                    )
                ),
                timeout=120
            )
    except Exception as e:
        logging.exception("Ошибка Replicate")
        await message.answer("❌ Ошибка генерации.")
        return

    # =====================
    # ПРАВИЛЬНАЯ ОБРАБОТКА
    # =====================
    image_url = None

    if isinstance(output, str):
        image_url = output
    elif isinstance(output, list) and output:
        image_url = output[0]
    elif hasattr(output, "url"):
        image_url = output.url

    if not image_url:
        await message.answer("❌ Изображение не получено.")
        return

    await bot.send_photo(
        chat_id=message.chat.id,
        photo=image_url,
        caption="✅ Готово"
    )

# =====================
# WEBHOOK
# =====================
async def webhook_handler(request: web.Request):
    update = Update.model_validate(await request.json())
    await dp.feed_webhook_update(bot, update)
    return web.Response(text="ok")

async def on_startup(app: web.Application):
    await bot.set_webhook(WEBHOOK_URL + WEBHOOK_PATH)
    logging.info("✅ Webhook установлен")

# =====================
# APP
# =====================
app = web.Application()
app.router.add_post(WEBHOOK_PATH, webhook_handler)
app.on_startup.append(on_startup)

if __name__ == "__main__":
    web.run_app(app, port=int(os.environ.get("PORT", 10000)))
