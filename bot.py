import os
import asyncio
from aiogram import Bot, Dispatcher, executor, types
from fastapi import FastAPI
import uvicorn
from threading import Thread
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# ---------- Telegram handlers ----------

@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer(
        "👋 Привет!\n\n"
        "Я бот.\n"
        "Скоро здесь будет генерация текста и видео 🎬"
    )

@dp.message_handler()
async def echo(message: types.Message):
    await message.answer("Я получил сообщение ✅")

# ---------- FastAPI (для Render) ----------

app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok", "bot": "running"}

def run_web():
    uvicorn.run(app, host="0.0.0.0", port=PORT)

# ---------- Start everything ----------

if __name__ == "__main__":
    # запускаем web-сервер в отдельном потоке
    Thread(target=run_web).start()

    # запускаем бота
    executor.start_polling(dp, skip_updates=True)
