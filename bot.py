import os
import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message, Update
from aiogram.filters import CommandStart

import replicate
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://xxx.onrender.com
WEBHOOK_PATH = "/webhook"

logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

# 🔒 только ОДНА генерация за раз
generation_lock = asyncio.Semaphore(1)

# ---------- handlers ----------

@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Привет!\n\n"
        "Отправь текст — я сгенерирую изображение.\n"
        "⚠️ Генерация может занять до 1 минуты."
    )

@router.message()
async def generate_image(message: Message):
    prompt = message.text.strip()

    await message.answer("🎨 Генерирую изображение, подожди немного…")

    loop = asyncio.get_running_loop()

    async with generation_lock:
        try:
            output = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: replicate_client.run(
                        "google/imagen-3",
                        input={
                            "prompt": prompt,
                            "safety_filter_level": "block_medium_and_above"
                        }
                    )
                ),
                timeout=120  # ⏱ максимум 2 минуты
            )
        except asyncio.TimeoutError:
            await message.answer("⏱ Слишком долго. Попробуй другой запрос.")
            return
        except Exception as e:
            logging.exception("Ошибка генерации")
            await message.answer("❌ Ошибка генерации изображения.")
            return

    # результат — список URL
    if isinstance(output, list) and output:
        await bot.send_photo(message.chat.id, photo=output[0])
    else:
        await message.answer("❌ Не удалось получить изображение.")

    await asyncio.sleep(0)  # освобождаем event loop

# ---------- webhook ----------

async def webhook_handler(request: web.Request):
    data = await request.json()
    update = Update(**data)
    await dp.feed_webhook_update(bot, update)
    return web.Response(text="ok")

async def on_startup(app: web.Application):
    await bot.set_webhook(WEBHOOK_URL + WEBHOOK_PATH)
    logging.info("✅ Webhook установлен")

# ---------- app ----------

app = web.Application()
app.router.add_post(WEBHOOK_PATH, webhook_handler)
app.on_startup.append(on_startup)

if __name__ == "__main__":
    web.run_app(app, port=int(os.environ.get("PORT", 10000)))
