import os
import logging
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = os.getenv("TELEGRAM_TOKEN")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# ===== КНОПКИ =====
def main_menu():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("✍️ Генерировать текст", callback_data="gen_text"),
        InlineKeyboardButton("🎥 Генерировать видео", callback_data="gen_video"),
    )
    return keyboard


# ===== /start =====
@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer(
        "Выбери, что нужно сгенерировать 👇",
        reply_markup=main_menu()
    )


# ===== ОБРАБОТКА КНОПОК =====
@dp.callback_query_handler(lambda c: c.data == "gen_text")
async def text_button(callback: types.CallbackQuery):
    await callback.message.answer("✍️ Напиши тему или запрос для текста:")
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data == "gen_video")
async def video_button(callback: types.CallbackQuery):
    await callback.message.answer("🎥 Опиши сцену для видео:")
    await callback.answer()


# ===== ГЕНЕРАЦИЯ ТЕКСТА (ЗАГЛУШКА) =====
@dp.message_handler()
async def generate(message: types.Message):
    user_text = message.text

    # Пока заглушка, дальше подключим OpenAI / Replicate
    result_text = f"🧠 Сгенерированный результат:\n\n{user_text}"

    await message.answer(result_text)
    await message.answer("Хочешь ещё?", reply_markup=main_menu())


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
