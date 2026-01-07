import os
import logging
import asyncio
import random
from collections import defaultdict, deque

from dotenv import load_dotenv
from openai import OpenAI

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatAction
from aiogram.types import Message
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

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
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# LIMITS
# =========================
OPENAI_TIMEOUT = 30
OPENAI_CONCURRENCY = 1
openai_semaphore = asyncio.Semaphore(OPENAI_CONCURRENCY)

# =========================
# MEMORY
# =========================
user_memory = defaultdict(lambda: deque(maxlen=6))
user_locks = defaultdict(asyncio.Lock)

# =========================
# PROMPT
# =========================
SYSTEM_PROMPT = (
    "Ты умный и дружелюбный ассистент. "
    "Если пользователь описывает картинку — создай изображение. "
    "Иначе — отвечай текстом."
)

# =========================
# START
# =========================
@dp.message(F.text == "/start")
async def start_cmd(message: Message):
    await message.answer(
        "👋 Напиши текст — я отвечу или сгенерирую изображение / видео."
    )

# =========================
# MAIN HANDLER
# =========================
@dp.message(F.text)
async def chat(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()

    async with user_locks[user_id]:
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

        try:
            # ===== IMAGE MODE =====
            if text.lower().startswith(("нарисуй", "создай изображение", "image:", "draw")):
                async with openai_semaphore:
                    img = await asyncio.to_thread(
                        client.images.generate,
                        model="gpt-image-1",
                        prompt=text,
                        size="1024x1024"
                    )

                await message.answer_photo(img.data[0].url)
                return

            # ===== CHAT MODE =====
            user_memory[user_id].append({
                "role": "user",
                "content": text
            })

            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            messages.extend(user_memory[user_id])

            async with openai_semaphore:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        client.chat.completions.create,
                        model="gpt-4o-mini",
                        messages=messages,
                        temperature=0.8,
                        max_tokens=700
                    ),
                    timeout=OPENAI_TIMEOUT
                )

            answer = response.choices[0].message.content

            user_memory[user_id].append({
                "role": "assistant",
                "content": answer
            })

            await message.answer(answer)

        except asyncio.TimeoutError:
            await message.answer("⏱ Я задумался слишком долго. Попробуй ещё раз.")
        except Exception as e:
            logging.exception("Ошибка")
            await message.answer("⚠️ Произошла ошибка. Попробуй ещё раз.")

# =========================
# WEBHOOK
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

    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp)

    web.run_app(app, host="0.0.0.0", port=PORT)

# =========================
# START
# =========================
if __name__ == "__main__":
    main()
