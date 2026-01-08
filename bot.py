import os
import logging
import asyncio
import replicate
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import Message

from openai import OpenAI
from aiohttp import web

# --------------------
# ENV
# --------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

replicate.Client(api_token=REPLICATE_API_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --------------------
# GPT PROMPT BUILDER
# --------------------
def gpt_enhance_prompt_ru(user_text: str) -> str:
    system_prompt = """
You are a professional prompt engineer for image generation.

TASK:
Convert Russian user description into a STRICT English image prompt.

RULES:
- Preserve hair color EXACTLY
- Preserve clothing and colors EXACTLY
- Preserve gender EXACTLY
- NO creativity
- NO reinterpretation
- NO alternative looks
- User description is absolute truth

Return ONLY the final English prompt.
"""

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text}
        ],
        temperature=0.1
    )

    base_prompt = response.choices[0].message.content.strip()

    final_prompt = f"""
ULTRA REALISTIC PHOTO. STRICT LOCKED ATTRIBUTES.

SUBJECT (DO NOT CHANGE):
{base_prompt}

CRITICAL:
- Hair color must be exact
- Clothing colors must be exact
- No creative variations
- No substitutions
- No reinterpretation

Photography style:
Professional DSLR, 85mm lens, shallow depth of field,
natural soft light, high resolution, cinematic realism
"""

    return final_prompt

# --------------------
# HANDLERS
# --------------------
@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Напиши описание изображения по-русски.\n\n"
        "Пример:\n"
        "👉 Блондинка в белых шортах и черной футболке, фотореализм"
    )

@dp.message()
async def generate_image(message: Message):
    await message.answer("🎨 Генерирую изображение, подожди...")

    try:
        prompt = gpt_enhance_prompt_ru(message.text)

        output = replicate.run(
            "ideogram-ai/ideogram-v3-balanced",
            input={
                "prompt": prompt,
                "aspect_ratio": "3:2"
            }
        )

        image_url = output[0] if isinstance(output, list) else output.url

        await message.answer_photo(image_url)

    except Exception as e:
        logging.exception("Generation error")
        await message.answer("❌ Ошибка генерации. Попробуй изменить описание.")

# --------------------
# WEBHOOK (RENDER)
# --------------------
async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("✅ Webhook установлен")

async def on_shutdown(app):
    await bot.session.close()
    logging.info("🛑 Bot session closed")

async def handle(request):
    update = await request.json()
    await dp.feed_update(bot, types.Update(**update))
    return web.Response()

def main():
    app = web.Application()
    app.router.add_post("/", handle)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    web.run_app(app, port=8000)

if __name__ == "__main__":
    main()
