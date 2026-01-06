import os
from threading import Thread
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from fastapi import FastAPI
import uvicorn
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# ---------- КНОПКИ ----------

def main_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("✍️ Сгенерировать текст", callback_data="gen_text"),
        InlineKeyboardButton("🎬 Идея для видео", callback_data="gen_video"),
        InlineKeyboardButton("📜 Сценарий Reels", callback_data="gen_script"),
    )
    return keyboard

# ---------- ХЕНДЛЕРЫ ----------

@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer(
        "👋 Привет!\n\n"
        "Выбери, что хочешь сгенерировать:",
        reply_markup=main_keyboard()
    )

@dp.callback_query_handler(lambda c: c.data == "gen_text")
async def generate_text(callback: types.CallbackQuery):
    await callback.message.answer(
        "✍️ Генерация текста\n\n"
        "⚠️ GPT будет подключён на следующем шаге"
    )
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "gen_video")
async def generate_video(callback: types.CallbackQuery):
    await callback.message.answer(
        "🎬 Идея для видео\n\n"
        "⚠️ Генерация идей скоро будет доступна"
    )
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "gen_script")
async def generate_script(callback: types.CallbackQuery):
    await callback.message.answer(
        "📜 Сценарий Reels\n\n"
        "⚠️ GPT-логика будет добавлена"
    )
    await callback.answer()

# ---------- FASTAPI ДЛЯ RENDER ----------

app = FastAPI()

@app.get("/")
def healthcheck():
    return {"status": "ok", "bot": "running"}

def run_web():
    uvicorn.run(app, host="0.0.0.0", port=PORT)

# ---------- ЗАПУСК ----------

if __name__ == "__main__":
    Thread(target=run_web).start()
    executor.start_polling(dp, skip_updates=True)
