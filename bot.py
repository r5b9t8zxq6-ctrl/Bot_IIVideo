import os
import asyncio
import logging
import random
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.enums import ChatAction
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from dotenv import load_dotenv

from openai import OpenAI
import replicate

# =========================
# ENV
# =========================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")  # https://xxxx.onrender.com
PORT = int(os.environ.get("PORT", 10000))

if not BOT_TOKEN or not WEBHOOK_HOST:
    raise RuntimeError("❌ Не заданы BOT_TOKEN или WEBHOOK_HOST")

# =========================
# CONFIG
# =========================
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

OPENAI_TIMEOUT = 25
OPENAI_CONCURRENCY = 1

SYSTEM_PROMPT = (
    "Ты умный, дружелюбный ассистент. "
    "Отвечай кратко, по делу и по-человечески."
)

THINK_STICKERS = [
    "CAACAgIAAxkBAAEVFBFpXQKdMXKrifJH_zqRZaibCtB-lQACtwAD9wLID5Dxtgc7IUgdOAQ",
    "CAACAgIAAxkBAAEVFA9pXQJ_YAVXD8qH9yNaYjarJi04ugACiQoAAnFuiUvTl1zojCsDsDgE",
]

# =========================
# INIT
# =========================
logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

openai_client = OpenAI(api_key=OPENAI_API_KEY)
replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

openai_semaphore = asyncio.Semaphore(OPENAI_CONCURRENCY)

user_memory = defaultdict(lambda: deque(maxlen=6))
user_locks = defaultdict(asyncio.Lock)

# =========================
# KEYBOARD
# =========================
def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💬 Текст", callback_data="mode_text"),
            InlineKeyboardButton(text="🖼 Картинка", callback_data="mode_image"),
        ]
    ])

user_mode = defaultdict(lambda: "text")

# =========================
# START
# =========================
@router.message(F.text == "/start")
async def start_cmd(message: Message):
    await message.answer(
        "👋 Привет!\n\n"
        "Я умею:\n"
        "💬 Отвечать на вопросы\n"
        "🖼 Генерировать изображения\n\n"
        "Выбери режим 👇",
        reply_markup=main_keyboard()
    )

# =========================
# MODE SWITCH
# =========================
@router.callback_query(F.data.startswith("mode_"))
async def mode_switch(callback):
    mode = callback.data.replace("mode_", "")
    user_mode[callback.from_user.id] = mode

    text = "💬 Режим текста" if mode == "text" else "🖼 Режим генерации изображений"
    await callback.message.answer(text)
    await callback.answer()

# =========================
# IMAGE GENERATION
# =========================
@router.message(F.text & (lambda m: user_mode[m.from_user.id] == "image"))
async def image_handler(message: Message):
    prompt = message.text.strip()

    thinking = await message.answer_sticker(random.choice(THINK_STICKERS))

    try:
        output = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: replicate_client.run(
                "stability-ai/sdxl",
                input={
                    "prompt": prompt,
                    "width": 1024,
                    "height": 1024,
                    "num_outputs": 1,
                }
            )
        )

        image_url = output[0]

        await message.answer_photo(
            photo=image_url,
            caption=f"🖼 {prompt}"
        )

    except Exception:
        await message.answer("⚠️ Ошибка генерации изображения")

    finally:
        await thinking.delete()

# =========================
# TEXT CHAT
# =========================
@router.message(F.text)
async def chat_handler(message: Message):
    user_id = message.from_user.id

    async with user_locks[user_id]:
        thinking = None
        try:
            await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
            thinking = await message.answer_sticker(random.choice(THINK_STICKERS))

            user_memory[user_id].append({
                "role": "user",
                "content": message.text
            })

            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            messages.extend(user_memory[user_id])

            async with openai_semaphore:
                response = await asyncio.wait_for(
                    asyncio.get_running_loop().run_in_executor(
                        None,
                        lambda: openai_client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=messages,
                            max_tokens=600,
                            temperature=0.8,
                        )
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
        except Exception:
            logging.exception("CHAT ERROR")
            await message.answer("⚠️ Ошибка. Попробуй ещё раз.")
        finally:
            if thinking:
                await thinking.delete()

# =========================
# WEBHOOK
# =========================
async def on_startup(bot: Bot):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"✅ Webhook установлен: {WEBHOOK_URL}")

async def on_shutdown(bot: Bot):
    await bot.delete_webhook()
    await bot.session.close()

# =========================
# APP
# =========================
async def main():
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot, on_startup=on_startup, on_shutdown=on_shutdown)
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    asyncio.run(main())
