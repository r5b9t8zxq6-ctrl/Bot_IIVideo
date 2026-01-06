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
# LOAD ENV
# =========================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")  # https://bot-iivideo.onrender.com
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

if not BOT_TOKEN or not OPENAI_API_KEY or not WEBHOOK_HOST:
    raise ValueError("ENV variables missing")

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
SYSTEM_PROMPT = (
    "Ты дружелюбный, умный ChatGPT. "
    "Отвечай кратко, живо и по-человечески."
)

# =========================
# MEMORY
# =========================
dialog_history = defaultdict(list)
MAX_HISTORY = 8  # 4 вопроса + 4 ответа

# =========================
# OPENAI (SYNC)
# =========================
def ask_gpt(chat_id: int, text: str) -> str:
    history = dialog_history[chat_id]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": text},
    ]

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.9,
        max_tokens=700,
    )

    answer = response.choices[0].message.content

    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": answer})

    if len(history) > MAX_HISTORY:
        dialog_history[chat_id] = history[-MAX_HISTORY:]

    return answer

# =========================
# HANDLERS
# =========================
@dp.message_handler(commands=["start"])
async def start_cmd(message: types.Message):
    await message.answer("👋 Я жив. Пиши.")

@dp.message_handler(commands=["reset"])
async def reset_cmd(message: types.Message):
    dialog_history.pop(message.chat.id, None)
    await message.answer("🧠 Память очищена.")

@dp.message_handler()
async def chat(message: types.Message):
    await bot.send_chat_action(message.chat.id, ChatActions.TYPING)
    wait = await message.answer("🤔 Думаю...")

    loop = asyncio.get_event_loop()

    try:
        answer = await loop.run_in_executor(
            None,
            ask_gpt,
            message.chat.id,
            message.text
        )

        await wait.delete()
        await message.answer(answer)

    except Exception as e:
        logging.exception(e)
        await wait.delete()
        await message.answer("⚠️ Ошибка. Попробуй ещё раз.")

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
