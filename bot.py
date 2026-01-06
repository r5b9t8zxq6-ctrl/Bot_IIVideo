import os
import logging
import asyncio

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
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")  # https://bot-iivideo.onrender.com

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

PORT = int(os.environ.get("PORT", 10000))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found")
if not WEBHOOK_HOST:
    raise ValueError("WEBHOOK_HOST not found")

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
# SYSTEM PROMPT
# =========================
SYSTEM_PROMPT = """
Ты дружелюбный, умный ChatGPT.
Отвечай живо, по-человечески и полезно.
"""

# =========================
# OPENAI SYNC CALL
# =========================
def ask_gpt_sync(user_text: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text}
        ],
        temperature=0.9,
        max_tokens=800
    )
    return response.choices[0].message.content

# =========================
# HANDLERS
# =========================
@dp.message_handler(commands=["start"])
async def start_cmd(message: types.Message):
    await message.answer("👋 Я жив и готов помочь!")

@dp.message_handler()
async def chat(message: types.Message):
    await bot.send_chat_action(message.chat.id, ChatActions.TYPING)
    wait_msg = await message.answer("🤔 Думаю...")

    loop = asyncio.get_event_loop()

    try:
        answer = await loop.run_in_executor(
            None,
            ask_gpt_sync,
            message.text
        )

        await wait_msg.delete()
        await message.answer(answer)

    except Exception as e:
        logging.exception("OpenAI error")
        await wait_msg.delete()
        await message.answer("⚠️ Ошибка. Попробуй позже.")

# =========================
# WEBHOOK START / STOP
# =========================
async def on_startup(dp):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"Webhook set: {WEBHOOK_URL}")

async def on_shutdown(dp):
    await bot.delete_webhook()
    await bot.session.close()

# =========================
# START WEBHOOK
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
