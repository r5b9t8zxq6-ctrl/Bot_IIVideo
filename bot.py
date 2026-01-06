import os
import asyncio
import logging
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
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")  # https://bot-iivideo.onrender.com
PORT = int(os.environ.get("PORT", 10000))

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

if not all([BOT_TOKEN, OPENAI_API_KEY, WEBHOOK_HOST]):
    raise ValueError("❌ Проверь BOT_TOKEN / OPENAI_API_KEY / WEBHOOK_HOST")

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
# CONFIG
# =========================
SYSTEM_PROMPT = (
    "Ты дружелюбный, умный ассистент. "
    "Отвечай кратко, живо и по-человечески."
)

MAX_HISTORY = 10          # память диалога
QUEUE_LIMIT = 50          # максимум запросов в очереди
GPT_TIMEOUT = 25          # секунд
WORKERS = 2               # GPT воркеры

# =========================
# STORAGE
# =========================
dialog_history = defaultdict(lambda: deque(maxlen=MAX_HISTORY))
request_queue = asyncio.Queue(maxsize=QUEUE_LIMIT)

# =========================
# HANDLERS
# =========================
@dp.message_handler(commands=["start"])
async def start_cmd(message: types.Message):
    await message.answer("👋 Я жив. Пиши — отвечу!")

@dp.message_handler()
async def chat_handler(message: types.Message):
    if request_queue.full():
        await message.answer("🚦 Я сейчас перегружен, попробуй чуть позже")
        return

    await bot.send_chat_action(message.chat.id, ChatActions.TYPING)
    await message.answer("🤔 Думаю...")

    await request_queue.put((message.chat.id, message.text))

# =========================
# GPT WORKER
# =========================
async def gpt_worker(worker_id: int):
    logging.info(f"🧠 GPT worker #{worker_id} запущен")

    while True:
        chat_id, user_text = await request_queue.get()

        try:
            history = list(dialog_history[chat_id])

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                *history,
                {"role": "user", "content": user_text},
            ]

            response = await asyncio.wait_for(
                asyncio.to_thread(
                    client.chat.completions.create,
                    model="gpt-4o-mini",
                    messages=messages,
                    temperature=0.9,
                    max_tokens=700,
                ),
                timeout=GPT_TIMEOUT,
            )

            answer = response.choices[0].message.content

            dialog_history[chat_id].append({"role": "user", "content": user_text})
            dialog_history[chat_id].append({"role": "assistant", "content": answer})

            await bot.send_message(chat_id, answer)

        except asyncio.TimeoutError:
            await bot.send_message(chat_id, "⏳ Я завис на ответе, попробуй ещё раз")

        except Exception as e:
            logging.exception(e)
            await bot.send_message(chat_id, "⚠️ Ошибка. Попробуй позже")

        finally:
            request_queue.task_done()

# =========================
# WEBHOOK
# =========================
async def on_startup(dp):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"🌍 Webhook установлен: {WEBHOOK_URL}")

    for i in range(WORKERS):
        asyncio.create_task(gpt_worker(i))

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
