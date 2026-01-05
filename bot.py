import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import Command
from config import BOT_TOKEN
from database import init_db, get_user, add_user, decrement_free
from loguru import logger

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start(message: Message):
    add_user(message.from_user.id)
    await message.answer(
        "🎬 Привет! Напиши текст — я сгенерирую видео.\n"
        "У тебя есть 3 бесплатные генерации."
    )

@dp.message(F.text)
async def generate(message: Message):
    user = get_user(message.from_user.id)

    if user.free_generations <= 0:
        await message.answer("❌ Бесплатные генерации закончились.")
        return

    decrement_free(message.from_user.id)

    await message.answer(
        f"⏳ Генерация...\n"
        f"Осталось бесплатных: {user.free_generations - 1}"
    )

    # 🔥 ВРЕМЕННАЯ ЗАГЛУШКА
    await asyncio.sleep(2)

    await message.answer("✅ Видео готово (пока заглушка)")

async def main():
    init_db()
    logger.info("Bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
