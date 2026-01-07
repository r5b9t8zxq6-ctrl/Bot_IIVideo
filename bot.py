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
    CallbackQuery,
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
PORT = int(os.getenv("PORT", 10000))

if not BOT_TOKEN or not WEBHOOK_HOST:
    raise RuntimeError("❌ BOT_TOKEN или WEBHOOK_HOST не заданы")

# =========================
# CONFIG
# =========================
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

SYSTEM_PROMPT = (
    "Ты умный, дружелюбный ассистент. "
    "Отвечай кратко, по делу и по-человечески."
)

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
# KEYBOARDS
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

def image_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Сгенерировать ещё",
                    callback_data="image_again"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💬 Вернуться к тексту",
                    callback_data="mode_text"
                )
            ]
        ]
    )

# =========================
# START
# =========================
@router.message(F.text == "/start")
async def start_cmd(message: Message):
    await message.answer(
        "👋 Привет!\n\n"
        "Я умею:\n"
        "💬 Общаться\n"
        "🖼 Генерировать изображения\n\n"
        "Выбери режим 👇",
        reply_markup=main_keyboard()
    )

# =========================
# MODE SWITCH
# =========================
@router.callback_query(F.data.startswith("mode_"))
async def mode_switch(callback: CallbackQuery):
    mode = callback.data.replace("mode_", "")
    user_mode[callback.from_user.id] = mode

    await callback.message.answer(
        "💬 Режим текста" if mode == "text" else "🖼 Режим генерации изображений"
    )
    await callback.answer()

# =========================
# IMAGE AGAIN
# =========================
@router.callback_query(F.data == "image_again")
async def image_again(callback: CallbackQuery):
    user_mode[callback.from_user.id] = "image"
    await callback.message.answer("🖼 Напиши новый запрос для изображения")
    await callback.answer()

# =========================
# IMAGE GENERATION
# =========================
async def generate_image(prompt: str) -> str:
    loop = asyncio.get_running_loop()

    output = await loop.run_in_executor(
        None,
        lambda: replicate_client.run(
            SDXL_MODEL,
            input={
                "prompt": prompt,
                "width": 1024,
                "height": 1024,
                "num_outputs": 1,
            }
        )
    )

    if isinstance(output, list) and output:
        return output[0]

    raise ValueError("Replicate не вернул изображение")

@router.message(F.text & (lambda m: user_mode[m.from_user.id] == "image"))
async def image_handler(message: Message):
    thinking = await message.answer_sticker(random.choice(THINK_STICKERS))

    try:
        image_url = await generate_image(message.text)

        await message.answer_photo(
            photo=image_url,
            caption=f"🖼 {message.text}",
            reply_markup=image_keyboard()
        )

    except Exception:
        logging.exception("IMAGE ERROR")
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
                    temperature=0.8,
                )
            )

            answer = response.choices[0].message.content

            user_memory[user_id].append(
                {"role": "assistant", "content": answer}
            )

            await message.answer(answer)

        except Exception:
            logging.exception("CHAT ERROR")
            await message.answer("⚠️ Ошибка ответа")

        finally:
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
app = web.Application()

SimpleRequestHandler(
    dispatcher=dp,
    bot=bot,
).register(app, path=WEBHOOK_PATH)

setup_application(
    app,
    dp,
    bot=bot,
    on_startup=on_startup,
    on_shutdown=on_shutdown,
)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=PORT)
