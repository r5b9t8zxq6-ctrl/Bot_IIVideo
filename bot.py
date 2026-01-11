import os
import asyncio
from typing import Dict, Literal
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery,
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from asyncio import Queue
import replicate
from openai import OpenAI

# ================== CONFIG ==================

BOT_TOKEN = os.getenv("BOT_TOKEN")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_PATH = "/webhook"
FULL_WEBHOOK_URL = WEBHOOK_URL + WEBHOOK_PATH

KLING_MODEL = "kwaivgi/kling-v2.5-turbo-pro"

replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ================== BOT ==================

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

dp = Dispatcher()
app = FastAPI()

# ================== STATE ==================

Mode = Literal["photo_video", "gpt_kling"]

user_modes: Dict[int, Mode] = {}
user_photos: Dict[int, str] = {}
user_gpt_style: Dict[int, str] = {}

queue: Queue = Queue()

# ================== UI ==================

def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📸➡️🎬 Фото → Видео",
                    callback_data="photo_video"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🧠➡️🎬 GPT → Видео",
                    callback_data="gpt_kling"
                )
            ],
        ]
    )

def gpt_style_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton("🔥 Reels", callback_data="reels"),
                InlineKeyboardButton("📢 Реклама", callback_data="ads"),
            ],
            [
                InlineKeyboardButton("💪 Мотивация", callback_data="motivation"),
                InlineKeyboardButton("📖 Story", callback_data="story"),
            ],
        ]
    )

# ================== START ==================

@dp.message(F.text == "/start")
async def start(msg: Message):
    await msg.answer(
        "🔥 <b>AI Video Generator</b>\n\nВыбери режим:",
        reply_markup=main_keyboard(),
    )

# ================== CALLBACKS ==================

@dp.callback_query()
async def callbacks(call: CallbackQuery):
    user_id = call.from_user.id
    data = call.data

    if data == "photo_video":
        user_modes[user_id] = "photo_video"
        await call.message.answer("📸 Отправь фото")
        await call.answer()
        return

    if data == "gpt_kling":
        user_modes[user_id] = "gpt_kling"
        await call.message.answer(
            "🎬 Выбери стиль видео:",
            reply_markup=gpt_style_keyboard(),
        )
        await call.answer()
        return

    if data in {"reels", "ads", "motivation", "story"}:
        user_gpt_style[user_id] = data
        await call.message.answer("✍️ Напиши тему видео")
        await call.answer()
        return

# ================== PHOTO ==================

@dp.message(F.photo)
async def handle_photo(msg: Message):
    if user_modes.get(msg.from_user.id) != "photo_video":
        return

    file = await bot.get_file(msg.photo[-1].file_id)
    user_photos[msg.from_user.id] = file.file_path

    await msg.answer("✍️ Теперь отправь описание видео")

# ================== TEXT ==================

@dp.message(F.text)
async def handle_text(msg: Message):
    user_id = msg.from_user.id
    mode = user_modes.get(user_id)

    if not mode:
        await msg.answer("⚠️ Нажми /start и выбери режим")
        return

    # ===== PHOTO → VIDEO =====
    if mode == "photo_video":
        photo = user_photos.get(user_id)
        if not photo:
            await msg.answer("📸 Сначала отправь фото")
            return

        await queue.put({
            "type": "photo_video",
            "chat_id": msg.chat.id,
            "photo": photo,
            "prompt": msg.text,
        })

        await msg.answer("🎬 Генерирую видео из фото...")
        return

    # ===== GPT → KLING =====
    if mode == "gpt_kling":
        style = user_gpt_style.get(user_id)
        if not style:
            await msg.answer("⚠️ Выбери стиль")
            return

        await queue.put({
            "type": "gpt_kling",
            "chat_id": msg.chat.id,
            "topic": msg.text,
            "style": style,
        })

        await msg.answer("🧠➡️🎬 GPT генерирует видео...")
        return

# ================== WORKER ==================

async def worker():
    while True:
        task = await queue.get()

        try:
            # ===== PHOTO → VIDEO =====
            if task["type"] == "photo_video":
                photo_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{task['photo']}"

                output = replicate_client.run(
                    KLING_MODEL,
                    input={
                        "image": photo_url,
                        "prompt": task["prompt"],
                    },
                )

                await bot.send_video(task["chat_id"], video=output)

            # ===== GPT → KLING =====
            if task["type"] == "gpt_kling":
                style_prompt = {
                    "reels": "короткое динамичное вирусное видео",
                    "ads": "рекламное продающее видео",
                    "motivation": "мотивационное вдохновляющее видео",
                    "story": "сторителлинг видео с атмосферой",
                }[task["style"]]

                gpt = openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Ты видеопродюсер.\n"
                                "1. Создай короткий сценарий.\n"
                                "2. Создай ВИЗУАЛЬНЫЙ prompt для видео-генерации (англ).\n"
                                "Ответ строго в формате:\n\n"
                                "SCENARIO:\n...\n\n"
                                "VIDEO_PROMPT:\n..."
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"{style_prompt}. Тема: {task['topic']}",
                        },
                    ],
                )

                content = gpt.choices[0].message.content
                scenario, video_prompt = content.split("VIDEO_PROMPT:")

                video = replicate_client.run(
                    KLING_MODEL,
                    input={"prompt": video_prompt.strip()},
                )

                await bot.send_video(task["chat_id"], video=video)
                await bot.send_message(
                    task["chat_id"],
                    f"🎬 <b>Сценарий:</b>\n{scenario.replace('SCENARIO:', '').strip()}",
                )

        except Exception as e:
            await bot.send_message(task["chat_id"], f"❌ Ошибка: {e}")

        queue.task_done()

# ================== WEBHOOK ==================

@app.on_event("startup")
async def startup():
    await bot.set_webhook(FULL_WEBHOOK_URL)
    asyncio.create_task(worker())

@app.on_event("shutdown")
async def shutdown():
    await bot.delete_webhook()

@app.post(WEBHOOK_PATH)
async def webhook(request: Request):
    update = await request.json()
    await dp.feed_raw_update(bot, update)
    return {"ok": True}

# ================== RUN ==================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
    )