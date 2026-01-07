import os
import logging
import asyncio
import random
import aiohttp

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile
from aiogram.filters import CommandStart
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://xxx.onrender.com/webhook

logging.basicConfig(level=logging.INFO)

bot = Bot(TOKEN)
dp = Dispatcher()

# -------------------- BING IMAGE (FREE) --------------------

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
}

async def generate_bing_image(prompt: str) -> bytes:
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(
            "https://www.bing.com/images/create",
            params={"q": prompt, "form": "BICAI"},
            allow_redirects=True,
        ) as resp:
            html = await resp.text()

        # ищем первую картинку
        start = html.find("murl&quot;:&quot;")
        if start == -1:
            raise RuntimeError("Bing не вернул изображение")

        start += len("murl&quot;:&quot;")
        end = html.find("&quot;", start)
        image_url = html[start:end]

        async with session.get(image_url) as img:
            return await img.read()

# -------------------- HANDLERS --------------------

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🖼 Напиши любой запрос, и я сгенерирую картинку\n\n"
        "Пример:\n"
        "• cyberpunk city at night\n"
        "• realistic portrait of a woman"
    )

@dp.message(F.text)
async def handle_prompt(message: Message):
    thinking = await message.answer("🎨 Генерирую изображение...")

    try:
        image_bytes = await generate_bing_image(message.text)

        path = f"/tmp/{random.randint(1000,9999)}.jpg"
        with open(path, "wb") as f:
            f.write(image_bytes)

        await message.answer_photo(
            FSInputFile(path),
            caption=f"🖼 Запрос:\n{message.text}"
        )

    except Exception as e:
        logging.exception("IMAGE ERROR")
        await message.answer("❌ Не удалось сгенерировать изображение.\nПопробуй переформулировать запрос.")

    finally:
        await thinking.delete()

# -------------------- WEBHOOK --------------------

async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("Webhook установлен")

async def on_shutdown(app):
    await bot.delete_webhook()
    await bot.session.close()

app = web.Application()

SimpleRequestHandler(
    dispatcher=dp,
    bot=bot,
).register(app, path="/webhook")

app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

if __name__ == "__main__":
    web.run_app(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
    )
