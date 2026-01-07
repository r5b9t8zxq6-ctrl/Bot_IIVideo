import os
import asyncio
import logging
import random
from collections import defaultdict

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
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
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")
PORT = int(os.getenv("PORT", 10000))

if not BOT_TOKEN or not WEBHOOK_HOST:
    raise RuntimeError("ENV не заданы")

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

# =========================
# INIT
# =========================
logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

openai_client = OpenAI()
replicate_client = replicate.Client()

user_mode = defaultdict(lambda: "text")

THINK_STICKER = "CAACAgIAAxkBAAEVFBFpXQKdMXKrifJH_zqRZaibCtB-lQACtwAD9wLID5Dxtgc7IUgdOAQ"

# =========================
# KEYBOARD
# =========================
def mode_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="💬 Текст", callback_data="mode_text"),
            InlineKeyboardButton(text="🖼 Картинка", callback_data="mode_image"),
        ]]
    )

# =========================
# START
# =========================
@router.message(F.text == "/start")
async def start(message: Message):
    await message.answer(
        "Выбери режим 👇",
        reply_markup=mode_keyboard()
    )

# =========================
# MODE SWITCH
# =========================
@router.callback_query(F.data.startswith("mode_"))
async def switch_mode(cb: CallbackQuery):
    mode = cb.data.replace("mode_", "")
    user_mode[cb.from_user.id] = mode

    await cb.message.answer(
        "🖼 Режим генерации изображений" if mode == "image" else "💬 Текстовый режим"
    )
    await cb.answer()  # ОБЯЗАТЕЛЬНО

# =========================
# IMAGE HANDLER
# =========================
@router.message(F.text)
async def main_handler(message: Message):
    mode = user_mode[message.from_user.id]

    # ===== IMAGE MODE =====
    if mode == "image":
        sticker = await message.answer_sticker(THINK_STICKER)
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: replicate_client.run(
                    "stability-ai/sdxl",
                    input={"prompt": message.text}
                )
            )

            await message.answer_photo(
                photo=result[0],
                caption=f"🖼 {message.text}"
            )
        except Exception:
            logging.exception("IMAGE ERROR")
            await message.answer("⚠️ Ошибка генерации изображения")
        finally:
            await sticker.delete()
        return

    # ===== TEXT MODE =====
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": message.text}],
            temperature=0.8,
        )
        await message.answer(response.choices[0].message.content)
    except Exception:
        logging.exception("TEXT ERROR")
        await message.answer("⚠️ Ошибка ответа")

# =========================
# WEBHOOK
# =========================
async def on_startup(bot: Bot):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"Webhook установлен: {WEBHOOK_URL}")

async def on_shutdown(bot: Bot):
    await bot.delete_webhook()

app = web.Application()

SimpleRequestHandler(dp, bot).register(app, path=WEBHOOK_PATH)
setup_application(app, dp, bot=bot, on_startup=on_startup, on_shutdown=on_shutdown)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=PORT)
