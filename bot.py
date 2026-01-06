import os
import logging
from aiogram import Bot, Dispatcher, executor, types
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = """
Ты — умный, дружелюбный AI-помощник в Telegram.
Ты умеешь:
- вести обычный диалог
- писать эссе
- сочинять песни
- писать стихи
- помогать с идеями и мыслями

Отвечай ясно, интересно и по теме.
Формат выбирай сам, исходя из запроса пользователя.
"""

@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer(
        "Привет 👋\n\n"
        "Я могу общаться с тобой, писать эссе, стихи, песни и любые тексты.\n"
        "Просто напиши, что тебе нужно 🙂"
    )

@dp.message_handler()
async def chat_with_gpt(message: types.Message):
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
        await message.answer(answer)

    except Exception as e:
        logging.exception(e)
        await message.answer("⚠️ Произошла ошибка. Попробуй позже.")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
