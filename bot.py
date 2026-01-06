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
from aiohttp import web

# =========================
# ENV
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
# STICKERS
# =========================
THINK_STICKERS = [
    "CAACAgIAAxkBAAEVFBFpXQKdMXKrifJH_zqRZaibCtB-lQACtwAD9wLID5Dxtgc7IUgdOAQ",
    "CAACAgIAAxkBAAEVFA9pXQJ_YAVXD8qH9yNaYjarJi04ugACiQoAAnFuiUvTl1zojCsDsDgE",
    "CAACAgIAAxkBAAEVFAdpXQI0gobiAo031YwBUpOU400JjQACrjgAAtuNYEloV73kP0r9tjgE",
]

HELP_STICKER = "CAACAgIAAxkBAAAAAAA4"

# =========================
# SYSTEM PROMPT
# =========================
SYSTEM_PROMPT = (
    "Ты дружелюбный, умный помощник. "
    "Отвечай по-человечески, кратко и понятно."
)

# =========================
# MEMORY + LOCKS
# =========================
user_memory = defaultdict(lambda: deque(maxlen=6))
user_locks = defaultdict(asyncio.Lock)

# =========================
# OPENAI SAFE CALL
# =========================
def ask_gpt(messages):
    return client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.8,
        max_tokens=700,
        timeout=25,
    )

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
        sticker_msg = None

        try:
            await bot.send_chat_action(message.chat.id, ChatActions.TYPING)

            sticker_msg = await bot.send_sticker(
                message.chat.id,
                random.choice(THINK_STICKERS)
            )

            user_memory[user_id].append(
                {"role": "user", "content": message.text}
            )

            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            messages.extend(user_memory[user_id])

            response = await asyncio.wait_for(
                asyncio.to_thread(ask_gpt, messages),
                timeout=30
            )

            answer = response.choices[0].message.content

            user_memory[user_id].append(
                {"role": "assistant", "content": answer}
            )

            await message.answer(answer)

            if "спасибо" in message.text.lower():
                await bot.send_sticker(message.chat.id, HELP_STICKER)

        except asyncio.TimeoutError:
            await message.answer("⌛ Я задумался дольше обычного. Напиши ещё раз.")

        except Exception as e:
            logging.exception(e)
            await message.answer("⚠️ Внутренняя ошибка. Попробуй ещё раз.")

        finally:
            if sticker_msg:
                try:
                    await bot.delete_message(
                        message.chat.id,
                        sticker_msg.message_id
                    )
                except:
                    pass

# =========================
# WEBHOOK + HEALTHCHECK
# =========================
async def healthcheck(request):
    return web.Response(text="OK")

async def on_startup(dp):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"Webhook set: {WEBHOOK_URL}")

async def on_shutdown(dp):
    await bot.delete_webhook()
    await bot.session.close()

if __name__ == "__main__":
    app = web.Application()
    app.router.add_get("/", healthcheck)

    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        skip_updates=True,
        host="0.0.0.0",
        port=PORT,
        app=app,
    )
