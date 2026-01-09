from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from config import BOT_TOKEN
from replicate_utils import client, enhance_prompt, run_replicate

router = Router()


@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🖼 Напиши текст — сгенерирую изображение\n"
        "📸 Или отправь фото + текст — отредактирую"
    )


@router.message(lambda m: m.text and not m.photo)
async def text_to_image(message: Message):
    await message.answer("🎨 Генерирую изображение...")

    def generate():
        return client.run(
            "qwen/qwen-image-edit-2511",
            input={
                "image": [],
                "prompt": enhance_prompt(message.text),
                "aspect_ratio": "3:4",
            },
        )

    result = await run_replicate(generate)

    if result == "RATE_LIMIT":
        await message.answer("⏳ Слишком много запросов. Подожди 10 секунд.")
        return

    if not result:
        await message.answer("❌ Не удалось сгенерировать изображение")
        return

    for url in result:
        await message.answer_photo(url)


@router.message(lambda m: m.photo)
async def image_to_image(message: Message):
    await message.answer("🧠 Обрабатываю изображение...")

    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

    prompt = message.caption or "Improve photo quality"

    def generate():
        return client.run(
            "qwen/qwen-image-edit-2511",
            input={
                "image": [image_url],
                "prompt": enhance_prompt(prompt),
                "aspect_ratio": "3:4",
            },
        )

    result = await run_replicate(generate)

    if result == "RATE_LIMIT":
        await message.answer("⏳ Слишком много запросов. Подожди 10 секунд.")
        return

    if not result:
        await message.answer("❌ Не удалось обработать изображение")
        return

    for url in result:
        await message.answer_photo(url)
