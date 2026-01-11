from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from bot import bot
from keyboards import main_keyboard, instagram_keyboard
from state import user_modes, user_photos
from queue import queue
from config import BOT_TOKEN

router = Router()

@router.message(F.text == "/start")
async def start(msg: Message):
    await msg.answer("🔥 <b>AI Studio Bot</b>", reply_markup=main_keyboard())

@router.callback_query(F.data)
async def callbacks(call: CallbackQuery):
    user_modes[call.from_user.id] = call.data

    if call.data == "instagram":
        await call.message.answer("📸 Instagram режим:", reply_markup=instagram_keyboard())
    else:
        await call.message.answer("✍️ Отправь описание")

    await call.answer()

@router.message(F.photo)
async def photo_handler(msg: Message):
    if user_modes.get(msg.from_user.id) != "photo_video":
        return

    file = await bot.get_file(msg.photo[-1].file_id)
    user_photos[msg.from_user.id] = (
        f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
    )
    await msg.answer("✍️ Теперь описание")

@router.message(F.text)
async def text_handler(msg: Message):
    mode = user_modes.get(msg.from_user.id)
    if not mode:
        await msg.answer("⚠️ Выбери режим")
        return

    await queue.put({
        "type": mode,
        "chat_id": msg.chat.id,
        "prompt": msg.text,
        "photo": user_photos.pop(msg.from_user.id, None),
    })

    await msg.answer("⏳ Запрос принят")
