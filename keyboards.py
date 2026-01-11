from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎬 Видео", callback_data="video"),
                InlineKeyboardButton(text="🖼 Изображение", callback_data="image"),
            ],
            [InlineKeyboardButton(text="📸➡️🎬 Фото → Видео", callback_data="photo_video")],
            [InlineKeyboardButton(text="🧠➡️🎬 GPT → Видео", callback_data="gpt_kling")],
            [InlineKeyboardButton(text="📸 Instagram", callback_data="instagram")],
            [InlineKeyboardButton(text="💬 GPT", callback_data="gpt")],
        ]
    )

def instagram_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎬 Сценарий + субтитры", callback_data="insta_script")],
            [InlineKeyboardButton(text="🎙 Текст для озвучки", callback_data="insta_voice")],
        ]
    )
