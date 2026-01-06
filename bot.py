import os
import logging
import asyncio

from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import ChatActions

from openai import OpenAI

# -------------------
# НАСТРОЙКИ
# -------------------

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = (
    "Ты умный, дружелюбный собеседник. "
    "Можешь вести диалог, писать эссе, стихи, песни, рассказы."
)

WAIT_STICKER_ID = "CAACAgIAAxkBAAEKQZ5lXxk5p7n9X3v3lZ5qz1cQxQACJgADVp29CkU1kF9t4x4YNgQ"

# -------------------
# BOT / DISPATCHER
# -------------------

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# -------------------
# HANDLERS
# -------------------

@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer(
        "👋 Привет!\n\n"
        "Я умею общаться, писать:\n"
        "• эссе\n"
        "• стихи\n"
        "• песни\n"
        "• рассказы\n\n"
        "Просто напиши тему ✍️"
    )

@dp.message_handler()
async def chat(message: types.Message):
    # typing...
    await bot.send_chat_action(message.chat.id, ChatActions.TYPING)

    wait_msg = await message.answer("🤔 Думаю...")
    sticker_msg = await message.answer_sticker(WAIT_STICKER_ID)

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

        answer = response.choices[0].message.content

        await wait_msg.delete()
        await sticker_msg.delete()

        await message.answer(answer)

    except Exception as e:
        await wait_msg.delete()
        await sticker_msg.delete()
        await message.answer("⚠️ Ошибка. Попробуй позже.")

# -------------------
# START
# -------------------

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
