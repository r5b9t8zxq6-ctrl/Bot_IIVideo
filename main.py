import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from config import BOT_TOKEN
from handlers import router

logging.basicConfig(level=logging.INFO)

async def main():
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML")
    )

    dp = Dispatcher()
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Запуск в режиме polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
