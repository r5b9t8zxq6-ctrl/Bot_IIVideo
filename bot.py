import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart

from aiohttp import web
from dotenv import load_dotenv
from openai import OpenAI

# ================== НАСТРОЙКИ ==================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://xxxx.onrender.com
WEBHOOK_PATH = "/webhook"
WEBHOOK_FULL_URL = f"{WEBHOOK_URL}{WEBHOOK_PATH}"

if not BOT_TOKEN or not OPENAI_API_KEY or not WEBHOOK_URL:
    raise RuntimeError("❌ Не заданы BOT_TOKEN / OPENAI_API_KEY / WEBHOOK_URL")

logging.basicConfig(level=logging.INFO)

# ================== ОБЪЕКТЫ ==================

bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()
router = Router()
dp.include_router(router)

openai_client = OpenAI(api_key=OPENAI_API_KEY)

# защита от одновременных запросов
openai_semaphore = asyncio.Semaphore(2)

# ================== ХЭНДЛЕРЫ ==================

@router.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "👋 <b>Привет!</b>\n\n"
        "Напиши:\n"
        "• обычный текст — я отвечу\n"
        "• <i>«нарисуй ...»</i> — я создам изображение 🎨"
    )


@router.message(F.text)
async def message_handler(message: Message):
    text = message.text.strip()
    text_lower = text.lower()

    try:
        # ---------- ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЯ ----------
        image_triggers = (
            "нарисуй",
            "создай изображение",
            "сделай изображение",
            "картинку",
            "изображение",
            "draw",
            "image",
        )

        if any(t in text_lower for t in image_triggers):
            async with openai_semaphore:
                result = await asyncio.to_thread(
                    openai_client.images.generate,
                    model="gpt-image-1",
                    prompt=text,
                    size="1024x1024",
                )

            image_url = result.data[0].url
            await message.answer_photo(image_url)
            return

        # ---------- ГЕНЕРАЦИЯ ТЕКСТА ----------
        async with openai_semaphore:
            response = await asyncio.to_thread(
                openai_client.chat.completions.create,
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Ты полезный Telegram-бот."},
                    {"role": "user", "content": text},
                ],
            )

        reply = response.choices[0].message.content
        await message.answer(reply)

    except Exception as e:
        logging.exception("Ошибка обработки сообщения")
        await message.answer("⚠️ Ошибка. Попробуй ещё раз.")


# ================== WEBHOOK ==================

async def on_startup(app: web.Application):
    await bot.set_webhook(WEBHOOK_FULL_URL)
    logging.info(f"✅ Webhook установлен: {WEBHOOK_FULL_URL}")


async def on_shutdown(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()


async def handle_webhook(request: web.Request):
    update = await request.json()
    await dp.feed_raw_update(bot, update)
    return web.Response(text="OK")


def main():
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, handle_webhook)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))


if __name__ == "__main__":
    main()
