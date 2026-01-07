import os
import asyncio
import logging
import random
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Update
from aiogram.enums import ChatAction
from dotenv import load_dotenv

from aiohttp import web

from openai import OpenAI
import replicate

# =========================
# ENV
# =========================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
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

openai_client = OpenAI(api_key=OPENAI_API_KEY)
replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

user_mode = defaultdict(lambda: "text")
user_memory = defaultdict(lambda: deque(maxlen=6))
user_locks = defaultdict(asyncio.Lock)

THINK_STICKERS = [
    "CAACAgIAAxkBAAEVFBFpXQKdMXKrifJH_zqRZaibCtB-lQACtwAD9wLID5Dxtgc7IUgdOAQ",
    "CAACAgIAAxkBAAEVFA9pXQJ_YAVXD8qH9yNaYjarJi04ugACiQoAAnFuiUvTl1zojCsDsDgE",
]

SDXL_MODEL = "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7d1f7c2e0faeb1d6a9b0c2e4f4a3d"
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
    await cb.message.answer("💬 Режим текста" if mode == "text" else "🖼 Режим генерации изображений")
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
            loop = asyncio.get_running_loop()
            output = await loop.run_in_executor(
                None,
                lambda: replicate_client.run(
                    SDXL_MODEL,
                    input={
                        "prompt": message.text,
                        "width": 1024,
                        "height": 1024,
                        "num_outputs": 1,
                        "guidance_scale": 7.5,
                        "num_inference_steps": 30,
                    }
                )
            )
            await message.answer_photo(output[0], caption=message.text)

        except Exception:
            logging.exception("IMAGE ERROR")
            await message.answer("❌ Ошибка генерации изображения. Подожди 10–15 секунд.")

        finally:
            await thinking.delete()
        return

    # ===== TEXT MODE =====
    async with user_locks[user_id]:
        thinking = await message.answer_sticker(random.choice(THINK_STICKERS))
        try:
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
            logging.exception("CHAT ERROR")
            await message.answer("Ошибка ответа")

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
