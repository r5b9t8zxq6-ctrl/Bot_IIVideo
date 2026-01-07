import os
import asyncio
import logging
import random
import urllib.parse
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    Update,
)
from aiogram.enums import ChatAction
from dotenv import load_dotenv
from aiohttp import web

from openai import OpenAI

# =========================
# ENV
# =========================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not BOT_TOKEN or not WEBHOOK_URL:
    raise RuntimeError("BOT_TOKEN или WEBHOOK_URL не заданы")

# =========================
# INIT
# =========================
logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

openai_client = OpenAI(api_key=OPENAI_API_KEY)

user_mode = defaultdict(lambda: "text")
user_memory = defaultdict(lambda: deque(maxlen=6))
user_locks = defaultdict(asyncio.Lock)

THINK_STICKERS = [
    "CAACAgIAAxkBAAEVFBFpXQKdMXKrifJH_zqRZaibCtB-lQACtwAD9wLID5Dxtgc7IUgdOAQ",
    "CAACAgIAAxkBAAEVFA9pXQJ_YAVXD8qH9yNaYjarJi04ugACiQoAAnFuiUvTl1zojCsDsDgE",
]

SYSTEM_PROMPT = "Ты дружелюбный ассистент. Отвечай кратко и по делу."

# =========================
# KEYBOARD
# =========================
def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💬 Текст", callback_data="mode_text"),
                InlineKeyboardButton(text="🖼 Картинка", callback_data="mode_image"),
            ]
        ]
    )

# =========================
# POLLINATIONS
# =========================
def pollinations_image_url(prompt: str) -> str:
    q = urllib.parse.quote(prompt)
    return f"https://image.pollinations.ai/prompt/{q}?width=1024&height=1024&seed={random.randint(1, 999999)}"

# =========================
# START
# =========================
@router.message(F.text == "/start")
async def start_cmd(message: Message):
    await message.answer("Привет 👋\nВыбери режим:", reply_markup=main_keyboard())

# =========================
# MODE SWITCH
# =========================
@router.callback_query(F.data.startswith("mode_"))
async def mode_switch(cb: CallbackQuery):
    mode = cb.data.replace("mode_", "")
    user_mode[cb.from_user.id] = mode
    await cb.message.answer(
        "💬 Режим текста" if mode == "text" else "🖼 Режим генерации изображений"
    )
    await cb.answer()

# =========================
# MESSAGE HANDLER
# =========================
@router.message(F.text)
async def handle_message(message: Message):
    user_id = message.from_user.id
    mode = user_mode[user_id]

    # ===== IMAGE MODE =====
    if mode == "image":
        thinking = await message.answer_sticker(random.choice(THINK_STICKERS))
        try:
            await asyncio.sleep(1)
            image_url = pollinations_image_url(message.text)
            await message.answer_photo(image_url, caption=message.text)
        except Exception:
            logging.exception("POLLINATIONS ERROR")
            await message.answer("❌ Ошибка генерации изображения")
        finally:
            await thinking.delete()
        return

    # ===== TEXT MODE =====
    async with user_locks[user_id]:
        thinking = await message.answer_sticker(random.choice(THINK_STICKERS))
        try:
            await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

            user_memory[user_id].append(
                {"role": "user", "content": message.text}
            )

            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            messages.extend(user_memory[user_id])

            response = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    max_tokens=500,
                ),
            )

            answer = response.choices[0].message.content
            user_memory[user_id].append(
                {"role": "assistant", "content": answer}
            )

            await message.answer(answer)

        except Exception:
            logging.exception("CHAT ERROR")
            await message.answer("❌ Ошибка ответа")
        finally:
            await thinking.delete()

# =========================
# WEBHOOK SERVER
# =========================
async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("Webhook установлен")

async def on_shutdown(app):
    await bot.delete_webhook()
    await bot.session.close()

async def handle_webhook(request: web.Request):
    update = Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return web.Response()

def main():
    app = web.Application()
    app.router.add_post("/webhook", handle_webhook)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))

if __name__ == "__main__":
    main()
