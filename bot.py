import os
import logging
import replicate
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import CommandStart
from dotenv import load_dotenv
import asyncio

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

# 🔒 Референс-изображения (можно заменить)
BASE_IMAGES = [
    "https://replicate.delivery/pbxt/OHhQ8FA8tnsvZWK2uq79oxnWwwfS2LYsV1DssplVT6283Xn5/01.webp"
]

# 🧠 Усиление промта + фиксация внешности
def enhance_prompt_ru(text: str) -> str:
    text = text.lower().strip()

    hair_map = {
        "блондинка": "blonde woman",
        "брюнетка": "brunette woman",
        "рыжая": "red-haired woman",
        "блондин": "blonde man",
        "брюнет": "brunette man"
    }

    clothes_map = {
        "белых шортах": "white shorts",
        "черных шортах": "black shorts",
        "синей куртке": "blue jacket",
        "белой футболке": "white t-shirt",
        "черном платье": "black dress"
    }

    appearance = []
    clothing = []

    for ru, en in hair_map.items():
        if ru in text:
            appearance.append(en)

    for ru, en in clothes_map.items():
        if ru in text:
            clothing.append(en)

    appearance_text = ", ".join(appearance) if appearance else "young woman"
    clothing_text = ", ".join(clothing) if clothing else "casual outfit"

    return f"""
ULTRA-REALISTIC PHOTO EDIT.

SUBJECT:
{appearance_text}

CLOTHING:
{clothing_text}

STYLE:
photo-realistic, natural lighting, 35mm lens, shallow depth of field,
sharp focus, cinematic realism, high detail skin texture

STRICT RULES:
- DO NOT change hair color
- DO NOT change clothing colors
- DO NOT change gender
- NO artistic interpretation
- NO random outfit changes
"""

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🖼 Напиши описание внешности и одежды.\n\n"
        "Пример:\n"
        "👉 блондинка в белых шортах и черной майке"
    )

@dp.message()
async def generate(message: Message):
    if not message.text:
        await message.answer("❗ Отправь текстовое описание.")
        return

    await message.answer("🎨 Генерирую изображение...")

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

        for item in output:
            await message.answer_photo(item.url)

    except Exception as e:
        logging.exception(e)
        await message.answer("❌ Ошибка генерации. Попробуй другой текст.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
