import os
import logging
import random
import asyncio
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, types
from aiogram.types import ChatActions
from aiogram.utils.executor import start_webhook
from dotenv import load_dotenv
from openai import OpenAI

# =========================
# LOAD ENV
# =========================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
PORT = int(os.environ.get("PORT", 10000))

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
# STICKERS (ЗАМЕНИ НА СВОИ)
# =========================
THINK_STICKERS = [
    "CAACAgIAAxkBAAEVFBFpXQKdMXKrifJH_zqRZaibCtB-lQACtwAD9wLID5Dxtgc7IUgdOAQ",  # 🤔 думает 1
    "CAACAgIAAxkBAAEVFA9pXQJ_YAVXD8qH9yNaYjarJi04ugACiQoAAnFuiUvTl1zojCsDsDgE",  # 🤔 думает 2
    "CAACAgIAAxkBAAEVFAdpXQI0gobiAo031YwBUpOU400JjQACrjgAAtuNYEloV73kP0r9tjgE",  # 🤔 думает 3
]

HELP_STICKER = "CAACAgIAAxkBAAAAAAA4"  # 🙌 рад помочь

# =========================
# SYSTEM PROMPT
# =========================
SYSTEM_PROMPT = (
    "Ты дружелюбный, умный помощник. "
    "Отвечай по-человечески, кратко и понятно."
)

# =========================
# MEMORY + QUEUE
# =========================
user_memory = defaultdict(lambda: deque(maxlen=6))
user_locks = defaultdict(asyncio.Lock)

# =========================
# HANDLERS
# =========================
@dp.message_handler(commands=["start"])
async def start_cmd(message: types.Message):
    await message.answer("👋 Я жив. Пиши, помогу.")

@dp.message_handler()
async def chat(message: types.Message):
    user_id = message.from_user.id

    async with user_locks[user_id]:
        await bot.send_chat_action(message.chat.id, ChatActions.TYPING)

        # 🎬 Отправляем thinking-стикер
        thinking_sticker = random.choice(THINK_STICKERS)
        sticker_msg = await bot.send_sticker(
            message.chat.id,
            thinking_sticker
        )

        try:
            # память
            user_memory[user_id].append(
                {"role": "user", "content": message.text}
            )

            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            messages.extend(user_memory[user_id])

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.8,
                max_tokens=700,
                timeout=30,
            )

            answer = response.choices[0].message.content

            user_memory[user_id].append(
                {"role": "assistant", "content": answer}
            )

            # 🧹 УДАЛЯЕМ thinking-стикер
            await bot.delete_message(
                chat_id=message.chat.id,
                message_id=sticker_msg.message_id
            )

            # 💬 Ответ
            await message.answer(answer)

            # 🙌 Доп. стикер
            if "спасибо" in message.text.lower():
                await bot.send_sticker(message.chat.id, HELP_STICKER)

        except Exception as e:
            logging.error(e)

            # пробуем удалить стикер даже при ошибке
            try:
                await bot.delete_message(
                    message.chat.id,
                    sticker_msg.message_id
                )
            except:
                pass

            await message.answer("⚠️ Ошибка. Попробуй ещё раз.")

# =========================
# WEBHOOK
# =========================
async def on_startup(dp):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"Webhook set: {WEBHOOK_URL}")

async def on_shutdown(dp):
    await bot.delete_webhook()
    await bot.session.close()

# =========================
# START
# =========================
if __name__ == "__main__":
    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        skip_updates=True,
        host="0.0.0.0",
        port=PORT,
    )
