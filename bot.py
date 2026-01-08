import os
import logging
import replicate
from aiogram import Bot, Dispatcher, F
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

# fallback image (если юзер не прислал фото)
BASE_IMAGES = [
    "https://replicate.delivery/pbxt/OHhQ8FA8tnsvZWK2uq79oxnWwwfS2LYsV1DssplVT6283Xn5/01.webp"
]


def enhance_prompt_ru(text: str) -> str:
    return f"""
ULTRA REALISTIC PHOTO EDIT

TASK:
{text}

RULES:
- photo realistic
- natural lighting
- 35mm lens
- sharp focus
- no style changes unless requested
"""


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🖼 Я умею:\n"
        "— генерировать изображение по описанию\n"
        "— редактировать твоё фото\n\n"
        "📸 Пришли фото + текст\n"
        "✍️ Или просто напиши текст"
    )


@dp.message(F.photo)
async def edit_user_photo(message: Message):
    await message.answer("🎨 Редактирую твоё фото...")

    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    photo_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

    prompt = enhance_prompt_ru(message.caption or "improve photo realism")

    try:
        output = replicate_client.run(
            "qwen/qwen-image-edit-2511",
            input={
                "image": [photo_url],
                "prompt": prompt,
                "aspect_ratio": "3:4"
            }
        )

        for item in output:
            await message.answer_photo(item.url)

    except Exception as e:
        logging.exception(e)
        await message.answer("❌ Ошибка обработки изображения")


@dp.message(F.text)
async def generate_from_text(message: Message):
    await message.answer("🎨 Генерирую изображение...")

    prompt = enhance_prompt_ru(message.text)

    try:
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
        await message.answer("❌ Ошибка генерации")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
