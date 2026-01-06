import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.utils.executor import start_webhook
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

APP_HOST = "0.0.0.0"
APP_PORT = int(os.getenv("PORT", 10000))

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_URL") + WEBHOOK_PATH

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = """
Ты — дружелюбный ChatGPT в Telegram.
Ты можешь:
— общаться на любые темы
— писать эссе
— стихи
— песни
— философствовать
"""

@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer(
        "Привет 👋\n"
        "Я AI-бот.\n"
        "Могу общаться, писать стихи, песни и эссе.\n\n"
        "Просто напиши сообщение 🙂"
    )

@dp.message_handler()
async def chat(message: types.Message):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message.text}
            ],
            temperature=0.9,
            max_tokens=800
        )

        await message.answer(response.choices[0].message.content)

    except Exception as e:
        logging.exception(e)
        await message.answer("Ошибка 😕 Попробуй позже.")

async def on_startup(dp):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("Webhook set")

async def on_shutdown(dp):
    await bot.delete_webhook()

if __name__ == "__main__":
    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        skip_updates=True,
        host=APP_HOST,
        port=APP_PORT,
    )
