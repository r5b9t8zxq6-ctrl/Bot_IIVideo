import os
import logging
from dotenv import load_dotenv

import replicate
from openai import OpenAI

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiohttp import web

# --------------------
# ENV
# --------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

logging.basicConfig(level=logging.INFO)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing")
if not REPLICATE_API_TOKEN:
    raise RuntimeError("REPLICATE_API_TOKEN missing")

# --------------------
# CLIENTS
# --------------------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

openai_client = None
if OPENAI_API_KEY:
    openai_client = OpenAI(api_key=OPENAI_API_KEY)

# --------------------
# IMAGE SOURCES (базовые)
# --------------------
BASE_IMAGES = [
    "https://replicate.delivery/pbxt/OHhQ8FA8tnsvZWK2uq79oxnWwwfS2LYsV1DssplVT6283Xn5/01.webp",
    "https://replicate.delivery/pbxt/OHhQ8AxCldMQssx9Nt0rHFn9gM0OynvI0uoc3fKpzEV7UUAs/jennai.jpg"
]

# --------------------
# PROMPT ENHANCER (RU → EN + фиксация)
# --------------------
def enhance_prompt_ru(text: str) -> str:
    if not openai_client:
        return text

    resp = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.1,
        messages=[
            {
                "role": "system",
                "content": (
                    "Translate Russian description into STRICT English image-edit prompt.\n"
                    "Preserve gender, hair color, clothing type and colors EXACTLY.\n"
                    "NO creativity. NO substitutions. NO style changes."
                )
            },
            {"role": "user", "content": text}
        ]
    )

    base = resp.choices[0].message.content.strip()

    return f"""
PHOTO-REALISTIC IMAGE EDIT.

{base}

STRICT RULES:
- Exact hair color
- Exact clothing colors
- Exact garments
- No color changes
- No hairstyle changes
"""

# --------------------
# HANDLERS
# --------------------
@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🖼 Редактирование изображений\n\n"
        "Напиши описание по-русски.\n\n"
        "Пример:\n"
        "Сделай женщину справа блондинкой в белых шортах"
    )

@dp.message()
async def generate(message: Message):
    await message.answer("🎨 Обрабатываю изображение...")

    try:
        prompt = enhance_prompt_ru(message.text)

        output = replicate_client.run(
            "qwen/qwen-image-edit-2511",
            input={
                "image": BASE_IMAGES,
                "prompt": prompt,
                "aspect_ratio": "3:4"
            }
        )

        # модель возвращает массив
        for item in output:
            await message.answer_photo(item.url)

    except Exception as e:
        logging.exception(e)
        await message.answer("❌ Ошибка генерации")

# --------------------
# WEBHOOK
# --------------------
async def handle(request):
    data = await request.json()
    update = types.Update(**data)
    await dp.feed_update(bot, update)
    return web.Response()

async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("Webhook set")

async def on_shutdown(app):
    await bot.session.close()

def main():
    app = web.Application()
    app.router.add_post("/", handle)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    web.run_app(app, port=8000)

if __name__ == "__main__":
    main()
