import os
import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher, Router
from aiogram.types import (
    Message, Update,
    InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery
)
from aiogram.filters import CommandStart
from dotenv import load_dotenv
import replicate

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

# =====================
# PROMPT ENGINE
# =====================
def build_prompt(user_prompt: str, style: str = "cinema") -> str:
    base = (
        f"{user_prompt}. "
        "High quality, ultra-detailed, sharp focus, professional lighting, "
        "cinematic composition, shallow depth of field, natural skin tones, "
        "35mm lens, f1.8, soft shadows, realistic textures."
    )

    styles = {
        "photo": "Photorealistic, DSLR photography, true-to-life colors.",
        "cinema": "Cinematic film still, dramatic lighting, movie scene.",
        "illustration": "Highly detailed illustration, digital art, concept art.",
    }

    return base + " " + styles.get(style, "")

# =====================
# KEYBOARD
# =====================
def action_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎨 Перегенерировать", callback_data="regen"),
        ],
        [
            InlineKeyboardButton(text="📸 Фото", callback_data="style_photo"),
            InlineKeyboardButton(text="🎞 Кино", callback_data="style_cinema"),
            InlineKeyboardButton(text="🖌 Иллюстрация", callback_data="style_illustration"),
        ]
    ])

# =====================
# STATE (простое хранение)
# =====================
user_last_prompt = {}

# =====================
# HANDLERS
# =====================
@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Привет!\n\n"
        "Напиши идею изображения:\n"
        "Например: *девушка в наушниках ночью в комнате*\n\n"
        "Я сам улучшу промт и создам качественное изображение 🎨",
        parse_mode="Markdown"
    )

@router.message()
async def generate(message: Message):
    user_text = message.text.strip()
    user_last_prompt[message.from_user.id] = {
        "prompt": user_text,
        "style": "cinema"
    }
    await run_generation(message.chat.id, message.from_user.id)

@router.callback_query()
async def callbacks(call: CallbackQuery):
    uid = call.from_user.id

    if uid not in user_last_prompt:
        await call.answer("Нет данных")
        return

    if call.data == "regen":
        await call.answer("🔄")
        await run_generation(call.message.chat.id, uid)

    elif call.data.startswith("style_"):
        style = call.data.replace("style_", "")
        user_last_prompt[uid]["style"] = style
        await call.answer(f"Стиль: {style}")
        await run_generation(call.message.chat.id, uid)

# =====================
# GENERATION
# =====================
async def run_generation(chat_id: int, user_id: int):
    data = user_last_prompt[user_id]
    final_prompt = build_prompt(data["prompt"], data["style"])

    await bot.send_message(chat_id, "⏳ Генерирую изображение...")

    loop = asyncio.get_running_loop()

    try:
        async with lock:
            output = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: replicate_client.run(
                        "ideogram-ai/ideogram-v3-balanced",
                        input={
                            "prompt": final_prompt,
                            "aspect_ratio": "3:2"
                        }
                    )
                ),
                timeout=180
            )
    except Exception as e:
        logging.exception("Ошибка генерации")
        await bot.send_message(chat_id, "❌ Ошибка генерации")
        return

    image_url = None

    if hasattr(output, "url"):
        image_url = output.url
    elif isinstance(output, list) and output:
        first = output[0]
        if hasattr(first, "url"):
            image_url = first.url
        elif isinstance(first, str):
            image_url = first
    elif isinstance(output, str):
        image_url = output

    if not image_url:
        await bot.send_message(chat_id, "❌ Изображение не получено")
        return

    await bot.send_photo(
        chat_id,
        photo=image_url,
        caption=f"🎨 *Стиль:* {data['style']}",
        parse_mode="Markdown",
        reply_markup=action_keyboard()
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

# =====================
# APP
# =====================
app = web.Application()
app.router.add_post(WEBHOOK_PATH, webhook_handler)
app.on_startup.append(on_startup)

if __name__ == "__main__":
    web.run_app(app, port=int(os.environ.get("PORT", 10000)))
