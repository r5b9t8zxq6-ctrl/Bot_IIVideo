import os
from aiogram import Bot, Dispatcher, executor, types
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Кнопки
main_kb = types.InlineKeyboardMarkup(row_width=2)
main_kb.add(
    types.InlineKeyboardButton("📝 Сгенерировать текст", callback_data="text"),
    types.InlineKeyboardButton("🎬 Идея видео", callback_data="video")
)

@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer(
        "Привет 👋\nЯ помогу с контентом для Reels.\nВыбери, что нужно:",
        reply_markup=main_kb
    )

@dp.callback_query_handler(lambda c: c.data == "text")
async def gen_text(callback: types.CallbackQuery):
    text = (
        "«Никто не скажет, что ты готов.\n"
        "Ты просто встаёшь — и делаешь.\n"
        "А потом это называют успехом.»"
    )
    await callback.message.answer(text)
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "video")
async def gen_video(callback: types.CallbackQuery):
    idea = (
        "🎬 Идея Reels:\n"
        "Кадр: ты идёшь по улице ночью\n"
        "Текст на экране:\n"
        "«Я не стал лучше.\n"
        "Я просто перестал сдаваться.»»"
    )
    await callback.message.answer(idea)
    await callback.answer()

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
