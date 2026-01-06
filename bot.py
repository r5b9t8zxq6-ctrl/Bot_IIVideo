import os
import logging
import asyncio
from collections import defaultdict

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
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")
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
# MEMORY
# =========================
dialog_history = defaultdict(list)
MAX_HISTORY = 6  # 🔴 ВАЖНО: уменьшили

SYSTEM_PROMPT = "Ты дружелюбный, живой и полезный ассистент."

# =========================
# GPT
# =========================
async def ask_gpt_and_reply(chat_id: int, text: str):
    try:
        history = dialog_history[chat_id]

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *history,
            {"role": "user", "content": text},
        ]

        response = await asyncio.to_thread(
            client.chat.completions.create,
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.9,
            max_tokens=600,
        )

        answer = response.choices[0].message.content

        history.extend([
            {"role": "user", "content": text},
            {"role": "assistant", "content": answer},
        ])

        dialog_history[chat_id] = history[-MAX_HISTORY:]

        await bot.send_message(chat_id, answer)

    except Exception as e:
        logging.exception(e)
        await bot.send_message(chat_id, "⚠️ GPT временно недоступен")

# =========================
# HANDLERS
# =========================
@dp.message_handler(commands=["start"])
async def start_cmd(message: types.Message):
    await message.answer("👋 Я готов. Пиши.")

@dp.message_handler(commands=["reset"])
async def reset_cmd(message: types.Message):
    dialog_history.pop(message.chat.id, None)
    await message.answer("🧠 Память очищена")

@dp.message_handler()
async def chat(message: types.Message):
    # 🔴 СРАЗУ отвечаем Telegram
    await message.answer("🤔 Думаю...")

    # 🔥 GPT уходит в фон
    asyncio.create_task(
        ask_gpt_and_reply(message.chat.id, message.text)
    )

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
        port=int(os.environ.get("PORT", 10000)),
    )
