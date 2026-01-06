import os
import logging
import random

from aiogram import Bot, Dispatcher, types
from aiogram.types import ChatActions
from aiogram.utils.executor import start_webhook
from dotenv import load_dotenv
from openai import OpenAI
from aiohttp import web

# =========================
# LOAD ENV
# =========================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")

WEBHOOK_HOST = WEBHOOK_URL
WEBHOOK_ENDPOINT = WEBHOOK_PATH
WEBHOOK_FULL_URL = f"{WEBHOOK_HOST}{WEBHOOK_ENDPOINT}"

WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = int(os.getenv("PORT", 10000))

# =========================
# LOGGING
# =========================
logging.basicConfig(level=logging.INFO)

# =========================
# INIT BOT
# =========================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# STICKERS
# =========================
STICKERS_THINK = [
    "PASTE_THINK_1",
    "PASTE_THINK_2",
    "PASTE_THINK_3",
]

STICKER_HELLO = "PASTE_HELLO"
STICKER_HELP = "PASTE_HELP"
STICKER_ERROR = "PASTE_ERROR"

# =========================
# STYLE DETECTOR
# =========================
def detect_style(text: str) -> str:
    t = text.lower()
    if any(x in t for x in ["как", "почему", "ошибка", "не работает"]):
        return "help"
    if any(x in t for x in ["придумай", "сценарий", "идею"]):
        return "creative"
    if any(x in t for x in ["объясни", "что такое"]):
        return "explain"
    return "chat"

PROMPTS = {
    "chat": "Отвечай дружелюбно, легко и по-человечески.",
    "help": "Отвечай спокойно и пошагово, помогая разобраться.",
    "creative": "Отвечай креативно и вдохновляюще.",
    "explain": "Объясняй просто и понятно."
}

# =========================
# HANDLERS
# =========================
@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer_sticker(STICKER_HELLO)
    await message.answer("Привет! Я здесь, чтобы помочь 🙂")

@dp.message_handler()
async def chat(message: types.Message):
    await bot.send_chat_action(message.chat.id, ChatActions.TYPING)
    think = await message.answer_sticker(random.choice(STICKERS_THINK))

    style = detect_style(message.text)

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": f"""
Ты дружелюбный собеседник.
{PROMPTS[style]}
"""
                },
                {"role": "user", "content": message.text}
            ],
            temperature=0.85,
            max_tokens=700
        )

        await think.delete()
        await message.answer(response.choices[0].message.content)

        if random.random() < 0.6:
            await message.answer_sticker(STICKER_HELP)

    except Exception as e:
        logging.error(e)
        await think.delete()
        await message.answer_sticker(STICKER_ERROR)
        await message.answer("Что-то пошло не так. Попробуем ещё раз.")

# =========================
# WEBHOOK STARTUP / SHUTDOWN
# =========================
async def on_startup(dp):
    await bot.set_webhook(WEBHOOK_FULL_URL)
    logging.info(f"Webhook set: {WEBHOOK_FULL_URL}")

async def on_shutdown(dp):
    await bot.delete_webhook()
    await bot.session.close()

# =========================
# START WEBHOOK
# =========================
if __name__ == "__main__":
    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_ENDPOINT,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        skip_updates=True,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT,
    )
