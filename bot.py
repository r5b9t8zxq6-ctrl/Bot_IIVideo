import os
import logging
import random
import asyncio

from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import ChatActions
from dotenv import load_dotenv
from openai import OpenAI

# =========================
# LOAD ENV
# =========================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found")

# =========================
# LOGGING
# =========================
logging.basicConfig(level=logging.INFO)

# =========================
# INIT
# =========================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# STICKERS (замени на свои)
# =========================
THINKING_STICKERS = [
    "CAACAgIAAxkBAAEG1bxl5x1",  # пример
    "CAACAgIAAxkBAAEG1bxm3z2",
    "CAACAgIAAxkBAAEG1bxn9a3",
]

HELP_STICKER = "CAACAgIAAxkBAAEG1bxo_help"

# =========================
# SYSTEM PROMPT
# =========================
SYSTEM_PROMPT = """
Ты дружелюбный, живой ассистент.
Отвечай по-человечески.
Стиль подстраивай под вопрос пользователя.
"""

# =========================
# COMMANDS
# =========================
@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer_sticker(HELP_STICKER)
    await message.answer(
        "Привет 👋\n\n"
        "Я живой ChatGPT-бот.\n"
        "Просто напиши — я отвечу."
    )

# =========================
# CHAT
# =========================

@dp.message_handler()
async def chat(message: types.Message):
    await message.answer_chat_action("typing")

    def ask_openai():
        return client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Ты дружелюбный помощник"},
                {"role": "user", "content": message.text}
            ]
        )

    try:
        response = await asyncio.to_thread(ask_openai)
        answer = response.choices[0].message.content
        await message.answer(answer)

    except Exception as e:
        await message.answer("⚠️ Что-то пошло не так, попробуй ещё раз")
        print(e)

# =========================
# START (POLLING)
# =========================
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
