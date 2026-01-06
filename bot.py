import os
import logging
import random

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
    await bot.send_chat_action(message.chat.id, ChatActions.TYPING)

    # 🎯 случайный «думаю» стикер
    await message.answer_sticker(random.choice(THINKING_STICKERS))

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message.text},
            ],
            temperature=0.9,
            max_tokens=700,
        )

        answer = response.choices[0].message.content
        await message.answer(answer)

    except Exception as e:
        logging.exception(e)
        await message.answer("Что-то пошло не так 😕 Попробуй ещё раз.")

# =========================
# START (POLLING)
# =========================
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
