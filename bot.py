import os
import logging
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from openai import OpenAI

# ---------- ENV ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN не задан")
if not OPENAI_API_KEY:
    raise RuntimeError("❌ OPENAI_API_KEY не задан")

# ---------- LOGGING ----------
logging.basicConfig(level=logging.INFO)

# ---------- INIT ----------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())
client = OpenAI(api_key=OPENAI_API_KEY)

# ---------- MEMORY (диалог) ----------
user_context = {}

SYSTEM_PROMPT = (
    "Ты дружелюбный, умный и полезный собеседник. "
    "Отвечай понятно, живо и по делу."
)

# ---------- START ----------
@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    user_context[message.from_user.id] = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]
    await message.answer(
        "👋 Привет!\n\n"
        "Я ИИ-собеседник.\n"
        "Можешь писать **о чём угодно** — я отвечу 🙂"
    )

# ---------- CHAT ----------
@dp.message_handler(content_types=types.ContentTypes.TEXT)
async def chat(message: types.Message):
    uid = message.from_user.id

    if uid not in user_context:
        user_context[uid] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    user_context[uid].append(
        {"role": "user", "content": message.text}
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=user_context[uid],
            temperature=0.8,
        )

        reply = response.choices[0].message.content

        user_context[uid].append(
            {"role": "assistant", "content": reply}
        )

        # ограничиваем историю (чтобы не жрало токены)
        if len(user_context[uid]) > 20:
            user_context[uid] = user_context[uid][-20:]

        await message.answer(reply)

    except Exception as e:
        logging.exception(e)
        await message.answer("⚠️ Ошибка. Попробуй ещё раз позже.")

# ---------- RUN ----------
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
