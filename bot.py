import os
import asyncio
import logging
import random
import base64

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    Update,
)
from dotenv import load_dotenv
from aiohttp import web, ClientSession, ClientTimeout

# =========================
# ENV
# =========================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://your-domain/webhook

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

user_mode = {}

THINK_STICKERS = [
    "CAACAgIAAxkBAAEVFBFpXQKdMXKrifJH_zqRZaibCtB-lQACtwAD9wLID5Dxtgc7IUgdOAQ",
    "CAACAgIAAxkBAAEVFA9pXQJ_YAVXD8qH9yNaYjarJi04ugACiQoAAnFuiUvTl1zojCsDsDgE",
]

# =========================
# KEYBOARD
# =========================
def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💬 Текст", callback_data="mode_text"),
                InlineKeyboardButton(text="🖼 Craiyon", callback_data="mode_image"),
            ]
        ]
    )

# =========================
# START
# =========================
@router.message(F.text == "/start")
async def start_cmd(message: Message):
    user_mode[message.from_user.id] = "text"
    await message.answer(
        "Привет 👋\nЯ могу бесплатно генерировать изображения через Craiyon.\n\nВыбери режим:",
        reply_markup=main_keyboard(),
    )

# =========================
# MODE SWITCH
# =========================
@router.callback_query(F.data.startswith("mode_"))
async def mode_switch(cb: CallbackQuery):
    mode = cb.data.replace("mode_", "")
    user_mode[cb.from_user.id] = mode

    titles = {
        "text": "💬 Режим текста",
        "image": "🖼 Генерация изображений (Craiyon)",
    }

    await cb.message.answer(titles.get(mode, "Режим изменён"))
    await cb.answer()

# =========================
# CRAIYON GENERATION
# =========================
async def generate_craiyon(prompt: str) -> list[bytes]:
    url = "https://backend.craiyon.com/generate"
    payload = {"prompt": prompt}

    async with ClientSession(timeout=ClientTimeout(total=120)) as session:
        async with session.post(url, json=payload) as resp:
            if resp.status != 200:
                raise RuntimeError("Craiyon API error")

            data = await resp.json()
            images = data.get("images", [])

            return [base64.b64decode(img) for img in images]

# =========================
# MESSAGE HANDLER
# =========================
@router.message(F.text)
async def handle_message(message: Message):
    mode = user_mode.get(message.from_user.id, "text")

    if mode == "image":
        thinking = await message.answer_sticker(random.choice(THINK_STICKERS))

        try:
            images = await generate_craiyon(message.text)

            if not images:
                await message.answer("❌ Не удалось сгенерировать изображение")
                return

            # Отправляем первые 3 картинки
            for img in images[:3]:
                await message.answer_photo(img)

        except Exception:
            logging.exception("CRAIYON ERROR")
            await message.answer("❌ Ошибка генерации через Craiyon")

        finally:
            await thinking.delete()
        return

    # TEXT MODE
    await message.answer(
        "💬 Текстовый режим\n\n"
        "Переключись на 🖼 Craiyon, чтобы генерировать изображения бесплатно."
    )

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

    web.run_app(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
    )

if __name__ == "__main__":
    main()
