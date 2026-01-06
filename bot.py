import asyncio
from aiogram import types
from aiogram.types import ChatActions

WAIT_STICKER_ID = "CAACAgIAAxkBAAEKQZ5lXxk5p7n9X3v3lZ5qz1cQxQACJgADVp29CkU1kF9t4x4YNgQ"

@dp.message_handler()
async def chat(message: types.Message):
    # 1️⃣ typing...
    await bot.send_chat_action(message.chat.id, ChatActions.TYPING)

    # 2️⃣ сообщение ожидания
    wait_msg = await message.answer("🤔 Думаю над ответом...")

    # 3️⃣ стикер ожидания
    sticker_msg = await message.answer_sticker(WAIT_STICKER_ID)

    try:
        # 4️⃣ запрос к ChatGPT
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message.text}
            ],
            temperature=0.9,
            max_tokens=800
        )

        answer = response.choices[0].message.content

        # 5️⃣ удаляем ожидание
        await wait_msg.delete()
        await sticker_msg.delete()

        # 6️⃣ отправляем ответ
        await message.answer(answer)

    except Exception as e:
        await wait_msg.delete()
        await sticker_msg.delete()
        await message.answer("😕 Произошла ошибка. Попробуй ещё раз.")
