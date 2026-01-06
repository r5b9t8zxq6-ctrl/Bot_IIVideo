import os
from threading import Thread

from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from fastapi import FastAPI
import uvicorn

from dotenv import load_dotenv
from openai import OpenAI

# ---------- ENV ----------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PORT = int(os.getenv("PORT", 10000))

# ---------- INIT ----------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
client = OpenAI(api_key=OPENAI_API_KEY)

# ---------- КНОПКИ ----------
def main_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("✍️ Сгенерировать текст", callback_data="gen_text"),
        InlineKeyboardButton("🎬 Идея для видео", callback_data="gen_video"),
        InlineKeyboardButton("📜 Сценарий Reels", callback_data="gen_script"),
    )
    return kb

# ---------- GPT ----------
def generate_text():
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Ты мотивационный копирайтер. "
                    "Пиши коротко, жёстко, цепляюще. "
                    "Формат — текст для Reels."
                )
            },
            {
                "role": "user",
                "content": "Сгенерируй мотивационный текст про рост и дисциплину"
            }
        ],
        max_tokens=200,
        temperature=0.9
    )
    return response.choices[0].message.content

# ---------- ХЕНДЛЕРЫ ----------
@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer(
        "👋 Привет!\n\n"
        "Я генерирую тексты и идеи для Reels.\n"
        "Выбери действие:",
        reply_markup=main_keyboard()
    )

@dp.callback_query_handler(lambda c: c.data == "gen_text")
async def gen_text(callback: types.CallbackQuery):
    await callback.message.answer("✍️ Генерирую текст...")
    
    text = generate_text()

    await callback.message.answer(text)
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "gen_video")
async def gen_video(callback: types.CallbackQuery):
    await callback.message.answer("🎬 Генерация идей для видео — следующий шаг")
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "gen_script")
async def gen_script(callback: types.CallbackQuery):
    await callback.message.answer("📜 Генерация сценариев — скоро")
    await callback.answer()

# ---------- FASTAPI ----------
app = FastAPI()

@app.get("/")
def health():
    return {"status": "ok"}

def run_web():
    uvicorn.run(app, host="0.0.0.0", port=PORT)

# ---------- START ----------
if __name__ == "__main__":
    Thread(target=run_web).start()
    executor.start_polling(dp, skip_updates=True)
