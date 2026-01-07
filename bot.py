import os
import re
import uuid
import logging
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.types import FSInputFile
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# =========================
# 🔥 BING IMAGE GENERATION
# =========================
async def generate_bing_image(prompt: str) -> bytes:
    session_id = str(uuid.uuid4())
    url = "https://www.bing.com/images/create"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html",
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://www.bing.com/images/create"
    }

    data = {
        "q": prompt,
        "rt": "4",
        "FORM": "GENCRE"
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(url, data=data) as resp:
            text = await resp.text()

            image_urls = re.findall(r'https://[^"]+\.jpg', text)
            if not image_urls:
                raise RuntimeError("Bing не вернул изображения")

            image_url = image_urls[0]

        async with session.get(image_url) as img_resp:
            return await img_resp.read()


# =========================
# 🤖 HANDLER
# =========================
@dp.message()
async def handle_message(message: types.Message):
    await message.answer("🎨 Генерирую изображение, подожди...")

    try:
        image_bytes = await generate_bing_image(message.text)

        file_path = f"/tmp/{uuid.uuid4()}.jpg"
        with open(file_path, "wb") as f:
            f.write(image_bytes)

        await message.answer_photo(FSInputFile(file_path))

    except Exception as e:
        logging.exception("BING ERROR")
        await message.answer("❌ Не удалось сгенерировать изображение. Попробуй другой запрос.")


# =========================
# 🚀 WEBHOOK
# =========================
async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("Webhook установлен")

async def on_shutdown(app):
    await bot.delete_webhook()

app = web.Application()
SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
setup_application(app, on_startup=on_startup, on_shutdown=on_shutdown)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
