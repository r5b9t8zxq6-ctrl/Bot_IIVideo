from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, Update,
    InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery
)
from aiogram.filters import CommandStart
from aiohttp import web
import asyncio
import logging
import os
import replicate
from dotenv import load_dotenv

# =====================
# ENV
# =====================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_PATH = "/webhook"

logging.basicConfig(level=logging.INFO)

# =====================
# INIT
# =====================
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)
lock = asyncio.Semaphore(1)

user_last_prompt = {}

# =====================
# PROMPT ENGINE
# =====================
def build_prompt(text: str, style: str):
    base = (
        f"{text}. "
        "High quality, ultra-detailed, professional lighting, "
        "cinematic composition, shallow depth of field, 35mm lens, f1.8."
    )

    styles = {
        "photo": "Photorealistic DSLR photography.",
        "cinema": "Cinematic film still, dramatic lighting.",
        "illustration": "Highly detailed digital illustration."
    }

    return base + " " + styles.get(style, "")

# =====================
# KEYBOARD
# =====================
def keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Перегенерировать", callback_data="regen")],
        [
            InlineKeyboardButton(text="📸 Фото", callback_data="style_photo"),
            InlineKeyboardButton(text="🎞 Кино", callback_data="style_cinema"),
            InlineKeyboardButton(text="🖌 Арт", callback_data="style_illustration"),
        ]
    ])

# =====================
# HANDLERS
# =====================
@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Напиши описание изображения.\n"
        "Я сделаю качественный промт и сгенерирую картинку 🎨"
    )

@router.message(F.text)
async def generate(message: Message):
    text = message.text.strip()

    user_last_prompt[message.from_user.id] = {
        "text": text,
        "style": "cinema"
    }

    await generate_image(message.chat.id, message.from_user.id)

@router.callback_query()
async def callbacks(call: CallbackQuery):
    uid = call.from_user.id
    if uid not in user_last_prompt:
        await call.answer("Нет данных")
        return

    if call.data == "regen":
        await call.answer("🔄")
        await generate_image(call.message.chat.id, uid)

    if call.data.startswith("style_"):
        style = call.data.replace("style_", "")
        user_last_prompt[uid]["style"] = style
        await call.answer(style)
        await generate_image(call.message.chat.id, uid)

# =====================
# GENERATION
# =====================
async def generate_image(chat_id: int, user_id: int):
    data = user_last_prompt[user_id]
    prompt = build_prompt(data["text"], data["style"])

    await bot.send_message(chat_id, "⏳ Генерация...")

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
    except Exception as e:
        logging.exception(e)
        await bot.send_message(chat_id, "❌ Ошибка генерации")
        return

    image_url = output[0] if isinstance(output, list) else output

    await bot.send_photo(
        chat_id,
        photo=image_url,
        caption=f"🎨 Стиль: {data['style']}",
        reply_markup=keyboard()
    )

# =====================
# WEBHOOK
# =====================
async def webhook_handler(request: web.Request):
    update = Update.model_validate(await request.json())
    await dp.feed_webhook_update(bot, update)
    return web.Response(text="ok")

async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL + WEBHOOK_PATH)
    logging.info("✅ Webhook установлен")

app = web.Application()
app.router.add_post(WEBHOOK_PATH, webhook_handler)
app.on_startup.append(on_startup)

if __name__ == "__main__":
    web.run_app(app, port=int(os.environ.get("PORT", 10000)))
