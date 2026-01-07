import os
import asyncio
import logging
import random
from collections import defaultdict, deque

from aiohttp import web
from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, Update
from aiogram.enums import ChatAction
from aiogram.filters import CommandStart

from openai import OpenAI
import replicate

# =========================
# ENV
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")  # https://bot-iivideo.onrender.com
PORT = int(os.getenv("PORT", 10000))

if not BOT_TOKEN or not WEBHOOK_HOST:
    raise RuntimeError("❌ BOT_TOKEN или WEBHOOK_HOST не заданы")

# =========================
# CONFIG
# =========================

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = WEBHOOK_HOST + WEBHOOK_PATH

SYSTEM_PROMPT = "Ты умный, дружелюбный ассистент. Отвечай кратко и по делу."

THINK_STICKERS = [
    "CAACAgIAAxkBAAEVFBFpXQKdMXKrifJH_zqRZaibCtB-lQACtwAD9wLID5Dxtgc7IUgdOAQ",
    "CAACAgIAAxkBAAEVFA9pXQJ_YAVXD8qH9yNaYjarJi04ugACiQoAAnFuiUvTl1zojCsDsDgE",
]

SDXL_MODEL = "stability-ai/sdxl"

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

user_mode = defaultdict(lambda: "text")
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

# =========================
# START
# =========================

@router.message(CommandStart())
async def start_cmd(message: Message):
    await message.answer("👋 Привет! Выбери режим 👇", reply_markup=main_keyboard())

# =========================
# MODE SWITCH
# =========================

@router.callback_query()
async def mode_switch(callback):
    if not callback.data.startswith("mode_"):
        return

    mode = callback.data.replace("mode_", "")
    user_mode[callback.from_user.id] = mode

    await callback.message.answer(
        "💬 Режим текста" if mode == "text" else "🖼 Режим генерации изображений"
    )
    await callback.answer()

# =========================
# IMAGE
# =========================

async def generate_image(prompt: str) -> str:
    loop = asyncio.get_running_loop()

    output = await loop.run_in_executor(
        None,
        lambda: replicate_client.run(
            SDXL_MODEL,
            input={"prompt": prompt, "width": 1024, "height": 1024}
        )
    )

    return output[0] if isinstance(output, list) else output

# =========================
# TEXT / IMAGE HANDLER
# =========================

@router.message()
async def main_handler(message: Message):
    user_id = message.from_user.id
    mode = user_mode[user_id]

    thinking = await message.answer_sticker(random.choice(THINK_STICKERS))

    try:
        if mode == "image":
            image_url = await generate_image(message.text)
            await message.answer_photo(photo=image_url, caption=f"🖼 {message.text}")
            return

        async with user_locks[user_id]:
            await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

            user_memory[user_id].append({"role": "user", "content": message.text})

            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            messages.extend(user_memory[user_id])

            response = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    max_tokens=500,
                )
            )

            answer = response.choices[0].message.content
            user_memory[user_id].append({"role": "assistant", "content": answer})

            await message.answer(answer)

    except Exception:
        logging.exception("BOT ERROR")
        await message.answer("⚠️ Ошибка. Попробуй ещё раз.")
    finally:
        await thinking.delete()

# =========================
# WEBHOOK
# =========================

async def telegram_webhook(request: web.Request):
    update = Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return web.Response(text="ok")

async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"✅ Webhook установлен: {WEBHOOK_URL}")

async def on_shutdown(app):
    await bot.delete_webhook()
    await bot.session.close()

# =========================
# APP
# =========================

def main():
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, telegram_webhook)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
