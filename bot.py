import os
import asyncio
import logging
import base64

from aiohttp import web
from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message, BufferedInputFile
from aiogram.filters import CommandStart

from openai import OpenAI
from dotenv import load_dotenv

# ================== ENV ==================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not all([BOT_TOKEN, OPENAI_API_KEY, WEBHOOK_URL]):
    raise RuntimeError("❌ Не заданы BOT_TOKEN / OPENAI_API_KEY / WEBHOOK_URL")

# ================== LOG ==================
logging.basicConfig(level=logging.INFO)

# ================== INIT ==================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ================== START ==================
@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Напиши текст — я отвечу.\n\n"
        "🖼 Чтобы создать изображение, начни сообщение с:\n"
        "`/img описание картинки`",
        parse_mode="Markdown"
    )

# ================== IMAGE ==================
@router.message(lambda m: m.text and m.text.startswith("/img"))
async def generate_image(message: Message):
    prompt = message.text.replace("/img", "", 1).strip()

    if not prompt:
        await message.answer("❗️ Напиши описание после `/img`")
        return

    await message.answer("🎨 Генерирую изображение...")

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: openai_client.images.generate(
                model="gpt-image-1",
                prompt=prompt,
                size="1024x1024"
            )
        )

        image_base64 = result.data[0].b64_json
        image_bytes = base64.b64decode(image_base64)

        photo = BufferedInputFile(
            image_bytes,
            filename="image.png"
        )

        await message.answer_photo(photo, caption="🖼 Готово")

    except Exception:
        logging.exception("Ошибка генерации изображения")
        await message.answer("⚠️ Ошибка. Попробуй ещё раз.")

# ================== TEXT ==================
@router.message(lambda m: m.text)
async def chat(message: Message):
    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Ты полезный ассистент."},
                    {"role": "user", "content": message.text}
                ],
                temperature=0.7
            )
        )

        await message.answer(response.choices[0].message.content)

    except Exception:
        logging.exception("Ошибка генерации текста")
        await message.answer("⚠️ Ошибка. Попробуй ещё раз.")

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
