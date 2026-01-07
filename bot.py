import os
import asyncio
import logging
import base64

from aiohttp import web
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, BufferedInputFile
from aiogram.filters import CommandStart

from openai import OpenAI

# ================== ENV ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not WEBHOOK_URL and WEBHOOK_HOST:
    WEBHOOK_URL = WEBHOOK_HOST.rstrip("/") + "/webhook"

if not BOT_TOKEN or not OPENAI_API_KEY or not WEBHOOK_URL:
    raise RuntimeError("❌ ENV variables missing")

# ================== LOG ==================
logging.basicConfig(level=logging.INFO)

# ================== INIT ==================
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

openai = OpenAI(api_key=OPENAI_API_KEY)

# ================== /start ==================
@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Я умею:\n\n"
        "🖼 Генерировать изображения:\n"
        "`/img кот в киберпанк стиле`\n\n"
        "💬 Отвечать на текст",
        parse_mode="Markdown"
    )

# ================== IMAGE (ТОЛЬКО /img) ==================
@router.message(F.text.startswith("/img"))
async def image_handler(message: Message):
    prompt = message.text[4:].strip()

    if not prompt:
        await message.answer("❗️Напиши описание после /img")
        return

    wait = await message.answer("🎨 Рисую...")

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: openai.images.generate(
                model="gpt-image-1",
                prompt=prompt,
                size="1024x1024"
            )
        )

        img_bytes = base64.b64decode(result.data[0].b64_json)
        image = BufferedInputFile(img_bytes, filename="image.png")

        await wait.delete()
        await message.answer_photo(image, caption="🖼 Готово")

    except Exception as e:
        logging.exception("IMAGE ERROR")
        await wait.edit_text("⚠️ Ошибка генерации изображения")

# ================== CHAT (ВСЁ ОСТАЛЬНОЕ) ==================
@router.message(F.text)
async def chat_handler(message: Message):
    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Ты краткий помощник."},
                    {"role": "user", "content": message.text}
                ]
            )
        )

        await message.answer(response.choices[0].message.content)

    except Exception:
        logging.exception("CHAT ERROR")
        await message.answer("⚠️ Ошибка ответа")

# ================== WEBHOOK ==================
async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"✅ Webhook установлен: {WEBHOOK_URL}")

async def on_shutdown(app):
    await bot.delete_webhook()
    await bot.session.close()

app = web.Application()
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

from aiogram.webhook.aiohttp_server import SimpleRequestHandler
SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")

if __name__ == "__main__":
    web.run_app(app, port=int(os.getenv("PORT", 8080)))
