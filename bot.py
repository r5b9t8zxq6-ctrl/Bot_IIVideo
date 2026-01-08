import os
import asyncio
import logging
import time

from aiohttp import web
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from dotenv import load_dotenv
import replicate

# ================== НАСТРОЙКИ ==================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://your-app.onrender.com/webhook
WEBHOOK_PATH = "/webhook"
PORT = int(os.getenv("PORT", 10000))

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ================== СОСТОЯНИЯ ==================

user_last_prompt = {}
user_cooldown = {}
COOLDOWN = 8  # секунд
lock = asyncio.Semaphore(1)

# ================== КНОПКИ ==================

def style_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📸 Реализм", callback_data="style_realistic"),
                InlineKeyboardButton(text="🎨 Кино", callback_data="style_cinematic")
            ],
            [
                InlineKeyboardButton(text="🧠 Арт", callback_data="style_art"),
                InlineKeyboardButton(text="✨ Премиум", callback_data="style_premium")
            ],
            [
                InlineKeyboardButton(text="🚀 Сгенерировать", callback_data="generate")
            ]
        ]
    )

# ================== PROMPT BUILDER ==================

def build_prompt(text: str, style: str) -> str:
    base = f"{text}. Ultra high quality, sharp focus, professional photography."

    styles = {
        "realistic": "photorealistic, natural lighting, DSLR, 85mm lens",
        "cinematic": "cinematic lighting, shallow depth of field, film still",
        "art": "artistic composition, painterly style, creative colors",
        "premium": "luxury editorial style, perfect composition, premium look"
    }

    return f"{base} {styles.get(style, '')}"

# ================== HANDLERS ==================

@router.message(F.text)
async def handle_text(message: Message):
    user_last_prompt[message.from_user.id] = {
        "text": message.text,
        "style": "realistic"
    }

    await message.answer(
        "📝 Текст получен.\nВыбери стиль:",
        reply_markup=style_keyboard()
    )

@router.callback_query(F.data.startswith("style_"))
async def select_style(call: CallbackQuery):
    style = call.data.replace("style_", "")
    user_last_prompt[call.from_user.id]["style"] = style

    await call.answer(f"Стиль выбран: {style}")

@router.callback_query(F.data == "generate")
async def generate(call: CallbackQuery):
    uid = call.from_user.id
    chat_id = call.message.chat.id

    if uid not in user_last_prompt:
        await call.answer("Сначала введи текст")
        return

    now = time.time()
    if now - user_cooldown.get(uid, 0) < COOLDOWN:
        await call.answer("⏳ Подожди пару секунд")
        return

    user_cooldown[uid] = now
    await call.answer()

    await generate_image(chat_id, uid)

# ================== GENERATION ==================

async def generate_image(chat_id: int, user_id: int):
    data = user_last_prompt[user_id]
    prompt = build_prompt(data["text"], data["style"])

    await bot.send_message(chat_id, "⏳ Генерирую изображение...")

    loop = asyncio.get_running_loop()

    try:
        async with lock:
            output = await loop.run_in_executor(
                None,
                lambda: replicate_client.run(
                    "ideogram-ai/ideogram-v3-balanced",
                    input={
                        "prompt": prompt,
                        "aspect_ratio": "3:2"
                    }
                )
            )

        # 🔥 ДОСТАЁМ URL ПРАВИЛЬНО
        if isinstance(output, list):
            image_url = output[0].url
        else:
            image_url = output.url

        await bot.send_photo(
            chat_id,
            photo=image_url,
            caption=f"🎨 Стиль: {data['style']}",
            reply_markup=style_keyboard()
        )

    except Exception as e:
        logging.exception(e)
        await bot.send_message(chat_id, "❌ Ошибка генерации")

# ================== WEBHOOK ==================

async def on_startup(bot: Bot):
    await bot.set_webhook(WEBHOOK_URL + WEBHOOK_PATH)
    logging.info("✅ Webhook установлен")

async def on_shutdown(bot: Bot):
    await bot.delete_webhook()

def main():
    app = web.Application()

    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot
    ).register(app, path=WEBHOOK_PATH)

    setup_application(app, dp, bot=bot, on_startup=on_startup, on_shutdown=on_shutdown)

    web.run_app(app, port=PORT)

if __name__ == "__main__":
    main()
