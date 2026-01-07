import os
import time
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
# ENV
# =========================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")  # https://xxxx.onrender.com
PORT = int(os.environ.get("PORT", 10000))

if not BOT_TOKEN or not OPENAI_API_KEY or not WEBHOOK_HOST:
    raise RuntimeError("❌ Не заданы переменные окружения")

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

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
# STICKERS
# =========================
THINK_STICKERS = [
    "CAACAgIAAxkBAAEVFBFpXQKdMXKrifJH_zqRZaibCtB-lQACtwAD9wLID5Dxtgc7IUgdOAQ",
    "CAACAgIAAxkBAAEVFA9pXQJ_YAVXD8qH9yNaYjarJi04ugACiQoAAnFuiUvTl1zojCsDsDgE",
    "CAACAgIAAxkBAAEVFAdpXQI0gobiAo031YwBUpOU400JjQACrjgAAtuNYEloV73kP0r9tjgE",
]

HELP_STICKER = "CAACAgIAAxkBAAAAAAA4"

# =========================
# PROMPT
# =========================
SYSTEM_PROMPT = (
    "Ты дружелюбный, спокойный и умный помощник. "
    "Отвечай по-человечески, кратко и понятно."
)

# =========================
# MEMORY / QUEUE / FLOOD
# =========================
user_memory = defaultdict(lambda: deque(maxlen=6))
user_locks = defaultdict(asyncio.Lock)

FLOOD_DELAY = 3  # секунд
user_last_message_time = defaultdict(lambda: 0.0)

# =========================
# HANDLERS
# =========================
@dp.message_handler(commands=["start"])
async def start_cmd(message: types.Message):
    await message.answer("👋 Я на связи. Пиши.")

@dp.message_handler()
async def chat(message: types.Message):
    user_id = message.from_user.id

    # 🚦 АНТИФЛУД
    now = time.time()
    if now - user_last_message_time[user_id] < FLOOD_DELAY:
        await message.answer("⏳ Подожди пару секунд, я ещё отвечаю")
        return
    user_last_message_time[user_id] = now

    async with user_locks[user_id]:
        sticker_msg = None

        try:
            await bot.send_chat_action(message.chat.id, ChatActions.TYPING)

            # 🤔 THINKING STICKER
            sticker_msg = await bot.send_sticker(
                message.chat.id,
                random.choice(THINK_STICKERS)
            )

            # 🧠 MEMORY
            user_memory[user_id].append({
                "role": "user",
                "content": message.text
            })

            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            messages.extend(user_memory[user_id])

            # 🧵 OpenAI (в executor, чтобы не блокировать event loop)
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    temperature=0.8,
                    max_tokens=600,
                )
            )

            answer = response.choices[0].message.content

            user_memory[user_id].append({
                "role": "assistant",
                "content": answer
            })

            # 🧹 DELETE STICKER
            if sticker_msg:
                await bot.delete_message(
                    message.chat.id,
                    sticker_msg.message_id
                )

            await message.answer(answer)

            if "спасибо" in message.text.lower():
                await bot.send_sticker(message.chat.id, HELP_STICKER)

        except Exception:
            logging.exception("❌ Ошибка обработки")

            if sticker_msg:
                try:
                    await bot.delete_message(
                        message.chat.id,
                        sticker_msg.message_id
                    )
                except:
                    pass

            await message.answer("⚠️ Произошла ошибка. Попробуй ещё раз.")

# =========================
# WEBHOOK
# =========================
async def on_startup(dp):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"✅ Webhook установлен: {WEBHOOK_URL}")

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
