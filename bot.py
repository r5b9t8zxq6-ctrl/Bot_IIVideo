import os
import logging
import random

from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import ChatActions
from dotenv import load_dotenv
from openai import OpenAI

# =========================
# LOAD ENV
# =========================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found")

# =========================
# LOGGING
# =========================
logging.basicConfig(level=logging.INFO)

# =========================
# INIT BOT
# =========================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# STICKERS (ВСТАВЬ СВОИ file_id)
# =========================
STICKERS_THINK = [
    "PASTE_THINK_1",
    "PASTE_THINK_2",
    "PASTE_THINK_3",
    "PASTE_THINK_4",
]

STICKER_HELLO = "PASTE_HELLO"
STICKER_HELP = "PASTE_HELP"   # «рад помочь»
STICKER_ERROR = "PASTE_ERROR"

# =========================
# STYLE DETECTOR
# =========================
def detect_style(text: str) -> str:
    t = text.lower()

    if any(x in t for x in ["как", "почему", "ошибка", "не работает", "сделать"]):
        return "help"

    if any(x in t for x in ["придумай", "сценарий", "текст", "идею", "креатив"]):
        return "creative"

    if any(x in t for x in ["объясни", "что такое", "значит", "пример"]):
        return "explain"

    return "chat"

# =========================
# PROMPTS
# =========================
PROMPTS = {
    "chat": "Отвечай дружелюбно и по-человечески, как в обычном разговоре.",
    "help": "Отвечай спокойно, пошагово и поддерживающе, помогая разобраться.",
    "creative": "Отвечай креативно, вдохновляюще, с образами и идеями.",
    "explain": "Объясняй просто и понятно, без заумных слов."
}

# =========================
# /START
# =========================
@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer_sticker(STICKER_HELLO)
    await message.answer(
        "Привет!\n\n"
        "Я здесь, чтобы помочь 🙂\n"
        "Задавай любой вопрос или просто напиши."
    )

# =========================
# CHAT
# =========================
@dp.message_handler()
async def chat(message: types.Message):
    await bot.send_chat_action(message.chat.id, ChatActions.TYPING)

    think_sticker = await message.answer_sticker(random.choice(STICKERS_THINK))

    style = detect_style(message.text)

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": f"""
Ты дружелюбный и вежливый собеседник.
{PROMPTS[style]}
"""
                },
                {"role": "user", "content": message.text}
            ],
            temperature=0.85,
            max_tokens=700
        )

        answer = response.choices[0].message.content

        await think_sticker.delete()
        await message.answer(answer)

        # 🫶 СТИКЕР «РАД ПОМОЧЬ» (НЕ ВСЕГДА)
        if (
            len(answer) < 400
            or any(x in message.text.lower() for x in ["спасибо", "благодарю"])
        ):
            if random.random() < 0.6:  # 60% шанс
                await message.answer_sticker(STICKER_HELP)

    except Exception as e:
        logging.error(e)
        await think_sticker.delete()
        await message.answer_sticker(STICKER_ERROR)
        await message.answer("Что-то пошло не так. Давай попробуем ещё раз чуть позже.")

# =========================
# START BOT
# =========================
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
