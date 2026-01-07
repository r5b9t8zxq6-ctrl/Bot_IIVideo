import os
import logging
import asyncio
import random
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message
from aiogram.enums import ChatAction
from aiogram.filters import CommandStart
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from aiohttp import web
from openai import OpenAI

# =========================
# 🔍 ENV DIAGNOSTIC (CRITICAL)
# =========================
print("===== ENV CHECK =====")
print("BOT_TOKEN =", os.getenv("BOT_TOKEN"))
print("OPENAI_API_KEY =", os.getenv("OPENAI_API_KEY"))
print("WEBHOOK_HOST =", os.getenv("WEBHOOK_HOST"))
print("=====================")

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")  # https://xxxx.onrender.com
PORT = int(os.getenv("PORT", 10000))

if not BOT_TOKEN or not OPENAI_API_KEY or not WEBHOOK_HOST:
    raise RuntimeError("❌ Не заданы BOT_TOKEN / OPENAI_API_KEY / WEBHOOK_HOST")

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
dp = Dispatcher()
router = Router()
dp.include_router(router)

openai_client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# LIMITS
# =========================
OPENAI_TIMEOUT = 25
OPENAI_CONCURRENCY = 1
openai_semaphore = asyncio.Semaphore(OPENAI_CONCURRENCY)

# =========================
# STICKERS
# =========================
THINK_STICKERS = [
    "CAACAgIAAxkBAAEVFBFpXQKdMXKrifJH_zqRZaibCtB-lQACtwAD9wLID5Dxtgc7IUgdOAQ",
    "CAACAgIAAxkBAAEVFA9pXQJ_YAVXD8qH9yNaYjarJi04ugACiQoAAnFuiUvTl1zojCsDsDgE",
    "CAACAgIAAxkBAAEVFAdpXQI0gobiAo031YwBUpOU400JjQACrjgAAtuNYEloV73kP0r9tjgE",
]

# =========================
# PROMPT
# =========================
SYSTEM_PROMPT = (
    "Ты дружелюбный и умный помощник. "
    "Отвечай живо, понятно и по-человечески."
)

# =========================
# MEMORY + LOCKS
# =========================
user_memory = defaultdict(lambda: deque(maxlen=6))
user_locks = defaultdict(asyncio.Lock)

# =========================
# HANDLERS
# =========================
@router.message(CommandStart())
async def start(message: Message):
    await message.answer("👋 Я онлайн. Пиши текст.")

@router.message()
async def chat(message: Message):
    user_id = message.from_user.id
    sticker_msg = None

    async with user_locks[user_id]:
        try:
            await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

            sticker_msg = await message.answer_sticker(
                random.choice(THINK_STICKERS)
            )

            user_memory[user_id].append({
                "role": "user",
                "content": message.text
            })

            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            messages.extend(user_memory[user_id])

            async with openai_semaphore:
                loop = asyncio.get_running_loop()
                response = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: openai_client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=messages,
                            temperature=0.8,
                            max_tokens=600,
                        )
                    ),
                    timeout=OPENAI_TIMEOUT
                )

            answer = response.choices[0].message.content

            user_memory[user_id].append({
                "role": "assistant",
                "content": answer
            })

            if sticker_msg:
                await sticker_msg.delete()

            await message.answer(answer)

        except asyncio.TimeoutError:
            if sticker_msg:
                await sticker_msg.delete()
            await message.answer("⏱ Я завис чуть дольше обычного. Напиши ещё раз.")

        except Exception as e:
            logging.exception("❌ Ошибка")
            if sticker_msg:
                try:
                    await sticker_msg.delete()
                except:
                    pass
            await message.answer("⚠️ Ошибка. Попробуй ещё раз.")

# =========================
# WEBHOOK APP
# =========================
async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"✅ Webhook установлен: {WEBHOOK_URL}")

async def on_shutdown(app):
    await bot.delete_webhook()
    await bot.session.close()

def main():
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    ).register(app, path=WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=PORT)

# =========================
# START
# =========================
if __name__ == "__main__":
    main()
