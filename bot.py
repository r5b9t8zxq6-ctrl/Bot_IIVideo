import os
import logging
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from openai import OpenAI

# ---------- ENV ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN не задан")
if not OPENAI_API_KEY:
    raise RuntimeError("❌ OPENAI_API_KEY не задан")

# ---------- LOGGING ----------
logging.basicConfig(level=logging.INFO)

# ---------- INIT ----------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())
client = OpenAI(api_key=OPENAI_API_KEY)

# ---------- STATES ----------
class TextGen(StatesGroup):
    topic = State()
    style = State()
    length = State()

# ---------- KEYBOARDS ----------
def main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🧠 Сгенерировать текст")
    return kb

def after_text_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🔄 Сгенерировать ещё")
    kb.add("🏠 В меню")
    return kb

# ---------- START ----------
@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer(
        "Привет 👋\n\nЯ могу сгенерировать текст **на любую тему**.\n"
        "Нажми кнопку ниже 👇",
        reply_markup=main_menu()
    )

# ---------- MENU ----------
@dp.message_handler(lambda m: m.text == "🏠 В меню", state="*")
async def back_to_menu(message: types.Message, state: FSMContext):
    await state.finish()
    await start(message)

# ---------- START GENERATION ----------
@dp.message_handler(lambda m: m.text in ["🧠 Сгенерировать текст", "🔄 Сгенерировать ещё"])
async def ask_topic(message: types.Message):
    await TextGen.topic.set()
    await message.answer("📌 Напиши тему текста\n\nНапример:\n• мотивация\n• бизнес\n• отношения\n• философия")

# ---------- TOPIC ----------
@dp.message_handler(state=TextGen.topic)
async def get_topic(message: types.Message, state: FSMContext):
    await state.update_data(topic=message.text)
    await TextGen.next()
    await message.answer("🎭 В каком стиле писать?\n\nНапример:\n• жёстко\n• мотивационно\n• философски\n• иронично")

# ---------- STYLE ----------
@dp.message_handler(state=TextGen.style)
async def get_style(message: types.Message, state: FSMContext):
    await state.update_data(style=message.text)
    await TextGen.next()
    await message.answer("📏 Длина текста?\n\nНапример:\n• коротко\n• средне\n• длинно")

# ---------- LENGTH + GENERATION ----------
@dp.message_handler(state=TextGen.length)
async def generate_text(message: types.Message, state: FSMContext):
    data = await state.get_data()

    topic = data["topic"]
    style = data["style"]
    length = message.text

    prompt = (
        f"Сгенерируй текст на тему: {topic}.\n"
        f"Стиль: {style}.\n"
        f"Длина: {length}.\n\n"
        "Текст должен быть живым, цепляющим и понятным."
    )

    await message.answer("⏳ Генерирую текст...")

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Ты профессиональный автор текстов."},
            {"role": "user", "content": prompt}
        ]
    )

    text = response.choices[0].message.content

    await message.answer(
        f"✨ **Готово:**\n\n{text}",
        reply_markup=after_text_kb(),
        parse_mode="Markdown"
    )

    await state.finish()

# ---------- RUN ----------
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
