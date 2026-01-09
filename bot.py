import os
import logging
import asyncio
import replicate

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv
from replicate.exceptions import ReplicateError

# ---------- INIT ----------
load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

if not BOT_TOKEN or not REPLICATE_API_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN или REPLICATE_API_TOKEN не заданы")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

# 🔐 ограничение одновременных запросов
REPLICATE_SEMAPHORE = asyncio.Semaphore(2)

# ---------- PROMPT ----------
def enhance_prompt(text: str) -> str:
    return (
        "Ultra realistic photo. "
        f"{text}. "
        "Natural lighting, 35mm, cinematic realism, high detail."
    )

# ---------- UTILS ----------
def extract_urls(output) -> list[str]:
    images = []

    if isinstance(output, list):
        for item in output:
            if isinstance(item, str):
                images.append(item)
            elif hasattr(item, "url"):
                images.append(item.url)

    if isinstance(output, dict):
        images.extend(output.get("images", []))

    return images

async def run_replicate_safe(generate_func):
    async with REPLICATE_SEMAPHORE:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(generate_func),
                timeout=120
            )

        except asyncio.TimeoutError:
            logging.error("⏱ Replicate timeout")
            return "TIMEOUT"

        except ReplicateError as e:
            if "429" in str(e):
                return "RATE_LIMIT"
            logging.exception("Replicate error")
            return None

        except Exception:
            logging.exception("Unknown error")
            return None

# ---------- HANDLERS ----------
@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🖼 Напиши текст — сгенерирую изображение\n"
        "📸 Или отправь фото + текст — отредактирую"
    )

@dp.message(F.text)
async def text_to_image(message: Message):
    await bot.send_chat_action(message.chat.id, "typing")
    await message.answer("🎨 Генерирую изображение...")

    def generate():
        return replicate_client.run(
            "qwen/qwen-image-edit-2511",
            input={
                "image": [],
                "prompt": enhance_prompt(message.text),
                "aspect_ratio": "3:4",
            },
        )

    output = await run_replicate_safe(generate)

    if output == "RATE_LIMIT":
        await message.answer("⏳ Слишком много запросов. Подожди 10 секунд.")
        return

    if output in (None, "TIMEOUT"):
        await message.answer("❌ Ошибка генерации изображения")
        return

    images = extract_urls(output)

    if not images:
        await message.answer("❌ Модель не вернула изображение")
        return

    for url in images:
        await message.answer_photo(url)

@dp.message(F.photo)
async def image_to_image(message: Message):
    await bot.send_chat_action(message.chat.id, "typing")
    await message.answer("🧠 Обрабатываю изображение...")

    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)

    image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
    prompt = message.caption or "Improve photo quality"

    def generate():
        return replicate_client.run(
            "qwen/qwen-image-edit-2511",
            input={
                "image": [image_url],
                "prompt": enhance_prompt(prompt),
                "aspect_ratio": "3:4",
            },
        )

    output = await run_replicate_safe(generate)

    if output == "RATE_LIMIT":
        await message.answer("⏳ Слишком много запросов. Подожди 10 секунд.")
        return

    if output in (None, "TIMEOUT"):
        await message.answer("❌ Ошибка обработки изображения")
        return

    images = extract_urls(output)

    if not images:
        await message.answer("❌ Модель не вернула изображение")
        return

    for url in images:
        await message.answer_photo(url)

# ---------- RUN ----------
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("✅ Бот запущен (polling)")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
