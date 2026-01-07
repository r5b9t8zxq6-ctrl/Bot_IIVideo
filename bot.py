import os
import asyncio
import logging
import base64

from aiohttp import web
from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message, BufferedInputFile
from aiogram.filters import CommandStart

from openai import OpenAI

# ================== ENV ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# принимаем ЛЮБОЙ вариант
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")

if not WEBHOOK_URL and WEBHOOK_HOST:
    WEBHOOK_URL = WEBHOOK_HOST.rstrip("/") + "/webhook"

if not BOT_TOKEN or not OPENAI_API_KEY or not WEBHOOK_URL:
    raise RuntimeError(
        f"❌ ENV error:\n"
        f"BOT_TOKEN={bool(BOT_TOKEN)}\n"
        f"OPENAI_API_KEY={bool(OPENAI_API_KEY)}\n"
        f"WEBHOOK_URL={WEBHOOK_URL}"
    )

# ================== LOG ==================
logging.basicConfig(level=logging.INFO)

# ================== INIT ==================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

openai = OpenAI(api_key=OPENAI_API_KEY)

# ================== START ==================
@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Я работаю.\n\n"
        "🖼 Генерация изображений:\n"
        "`/img описание`",
        parse_mode="Markdown"
    )

# ================== IMAGE ==================
@router.message(lambda m: m.text and m.text.startswith("/img"))
async def image(message: Message):
    prompt = message.text.replace("/img", "", 1).strip()

    if not prompt:
        await message.answer("❗️Напиши описание после /img")
        return

    wait_msg = await message.answer("🎨 Генерирую изображение...")

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
        photo = BufferedInputFile(img_bytes, "image.png")

        await wait_msg.delete()
        await message.answer_photo(photo, caption="🖼 Готово")

    except Exception:
        logging.exception("IMAGE ERROR")
        await wait_msg.edit_text("⚠️ Ошибка генерации")

# ================== TEXT ==================
@router.message(lambda m: m.text)
async def chat(message: Message):
    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Ты дружелюбный ассистент."},
                    {"role": "user", "content": message.text}
                ]
            )
        )
        await message.answer(response.choices[0].message.content)

    except Exception:
        logging.exception("CHAT ERROR")
        await message.answer("⚠️ Ошибка")

# ================== WEBHOOK ==================
async def on_startup(app: web.Application):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"✅ Webhook установлен: {WEBHOOK_URL}")

async def on_shutdown(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()

app = web.Application()
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

from aiogram.webhook.aiohttp_server import SimpleRequestHandler

SimpleRequestHandler(
    dispatcher=dp,
    bot=bot
).register(app, path="/webhook")

if __name__ == "__main__":
    web.run_app(app, port=int(os.getenv("PORT", 8080)))
