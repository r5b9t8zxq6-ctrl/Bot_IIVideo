import os
import asyncio
import logging
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.enums import ChatAction
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from openai import OpenAI

# ======================
# ENV
# ======================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")  # https://xxx.onrender.com
PORT = int(os.getenv("PORT", 10000))

if not BOT_TOKEN or not OPENAI_API_KEY or not WEBHOOK_HOST:
    raise RuntimeError("❌ ENV variables missing")

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

# ======================
# LOGGING
# ======================
logging.basicConfig(level=logging.INFO)

# ======================
# INIT
# ======================
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
openai_client = OpenAI(api_key=OPENAI_API_KEY)

openai_semaphore = asyncio.Semaphore(1)  # Render-safe

SYSTEM_PROMPT = (
    "Ты дружелюбный, умный ассистент. "
    "Отвечай понятно, по-человечески."
)

# ======================
# START
# ======================
@dp.message(F.text == "/start")
async def start_cmd(message: Message):
    await message.answer(
        "👋 Напиши текст — я отвечу или сгенерирую изображение / видео.\n\n"
        "🖼 картинка: описание\n"
        "🎬 видео: описание"
    )

# ======================
# IMAGE GENERATION
# ======================
@dp.message(F.text.lower().startswith("картинка"))
async def image_gen(message: Message):
    prompt = message.text.split(":", 1)[-1].strip()
    if not prompt:
        await message.answer("❗ Напиши так:\nкартинка: закат в горах")
        return

    await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)

    async with openai_semaphore:
        result = openai_client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size="1024x1024"
        )

    image_url = result.data[0].url
    await message.answer_photo(image_url, caption=f"🖼 {prompt}")

# ======================
# VIDEO (ЗАГЛУШКА)
# ======================
@dp.message(F.text.lower().startswith("видео"))
async def video_gen(message: Message):
    prompt = message.text.split(":", 1)[-1].strip()
    await message.answer(
        "🎬 Генерация видео скоро будет доступна.\n\n"
        f"Запрос сохранён: {prompt}"
    )

# ======================
# CHAT (GPT)
# ======================
@dp.message(F.text)
async def chat(message: Message):
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    async with openai_semaphore:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message.text},
            ],
            temperature=0.8,
            max_tokens=600,
        )

    answer = response.choices[0].message.content
    await message.answer(answer)

# ======================
# WEBHOOK
# ======================
async def on_startup(app: web.Application):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"✅ Webhook set: {WEBHOOK_URL}")

async def on_shutdown(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()

def main():
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    ).register(app, path=WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)

    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
