import os
import logging
import random
import asyncio
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, types
from aiogram.types import ChatActions, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.executor import start_webhook
from dotenv import load_dotenv
from openai import OpenAI

# =========================
# ENV
# =========================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")
PORT = int(os.environ.get("PORT", 10000))

if not BOT_TOKEN or not OPENAI_API_KEY or not WEBHOOK_HOST:
    raise RuntimeError("❌ Не заданы переменные окружения")

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

# =========================
# LOGGING
# =========================
logging.basicConfig(level=logging.INFO)

# =========================
# INIT
# =========================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# LIMITS
# =========================
OPENAI_TIMEOUT = 25
OPENAI_CONCURRENCY = 1
openai_semaphore = asyncio.Semaphore(OPENAI_CONCURRENCY)

# =========================
# STICKERS
# =========================
THINK_STICKERS = [
    "CAACAgIAAxkBAAEVFBFpXQKdMXKrifJH_zqRZaibCtB-lQACtwAD9wLID5Dxtgc7IUgdOAQ",
    "CAACAgIAAxkBAAEVFA9pXQJ_YAVXD8qH9yNaYjarJi04ugACiQoAAnFuiUvTl1zojCsDsDgE",
    "CAACAgIAAxkBAAEVFAdpXQI0gobiAo031YwBUpOU400JjQACrjgAAtuNYEloV73kP0r9tjgE",
]

# =========================
# PROMPT
# =========================
SYSTEM_PROMPT = (
    "Ты дружелюбный и умный помощник. "
    "Отвечай живо и понятно."
)

# =========================
# MEMORY
# =========================
user_memory = defaultdict(lambda: deque(maxlen=6))
user_locks = defaultdict(asyncio.Lock)
last_user_prompt = {}

# =========================
# KEYBOARD
# =========================
def generate_keyboard():
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("🖼 Сгенерировать изображение", callback_data="gen_image"),
        InlineKeyboardButton("🎬 Сгенерировать видео", callback_data="gen_video"),
    )

# =========================
# HANDLERS
# =========================
@dp.message_handler(commands=["start"])
async def start_cmd(message: types.Message):
    await message.answer("👋 Напиши текст — я отвечу или сгенерирую изображение / видео.")

@dp.message_handler()
async def chat(message: types.Message):
    user_id = message.from_user.id
    sticker_msg = None

    async with user_locks[user_id]:
        try:
            await bot.send_chat_action(message.chat.id, ChatActions.TYPING)

            sticker_msg = await bot.send_sticker(
                message.chat.id, random.choice(THINK_STICKERS)
            )

            last_user_prompt[user_id] = message.text

            user_memory[user_id].append(
                {"role": "user", "content": message.text}
            )

            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            messages.extend(user_memory[user_id])

            async with openai_semaphore:
                loop = asyncio.get_running_loop()
                response = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=messages,
                            temperature=0.8,
                            max_tokens=400,
                        )
                    ),
                    timeout=OPENAI_TIMEOUT
                )

            answer = response.choices[0].message.content
            user_memory[user_id].append(
                {"role": "assistant", "content": answer}
            )

            await bot.delete_message(message.chat.id, sticker_msg.message_id)

            await message.answer(
                answer,
                reply_markup=generate_keyboard()
            )

        except Exception:
            logging.exception("Ошибка")
            if sticker_msg:
                await bot.delete_message(message.chat.id, sticker_msg.message_id)
            await message.answer("⚠️ Ошибка. Попробуй ещё раз.")

# =========================
# IMAGE GENERATION
# =========================
@dp.callback_query_handler(lambda c: c.data == "gen_image")
async def generate_image(call: types.CallbackQuery):
    prompt = last_user_prompt.get(call.from_user.id)
    if not prompt:
        await call.answer("Нет текста для генерации", show_alert=True)
        return

    await call.message.answer("🖼 Генерирую изображение...")
    await call.answer()

    async with openai_semaphore:
        image = client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size="1024x1024"
        )

    await bot.send_photo(
        call.message.chat.id,
        image.data[0].url,
        caption=f"🖼 {prompt}"
    )

# =========================
# VIDEO (ЗАГЛУШКА)
# =========================
@dp.callback_query_handler(lambda c: c.data == "gen_video")
async def generate_video(call: types.CallbackQuery):
    await call.answer()
    await call.message.answer(
        "🎬 Генерация видео скоро будет доступна.\n"
        "Планируется подключение Runway / Pika / Kling."
    )

# =========================
# WEBHOOK
# =========================
async def on_startup(dp):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"Webhook set: {WEBHOOK_URL}")

async def on_shutdown(dp):
    await bot.delete_webhook()
    await bot.session.close()

# =========================
# START
# =========================
if __name__ == "__main__":
    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        skip_updates=True,
        host="0.0.0.0",
        port=PORT,
    )
