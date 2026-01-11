from bot import bot
from queue import queue
from services.replicate import generate_video
from logging import logger

async def worker():
    logger.info("Worker started")

    while True:
        task = await queue.get()
        try:
            result = await generate_video(
                prompt=task["prompt"],
                image=task.get("photo"),
            )
            await bot.send_message(
                task["chat_id"],
                f"✅ Готово:\n{result}"
            )
        except Exception:
            logger.exception("Worker error")
            await bot.send_message(task["chat_id"], "❌ Ошибка генерации")
        finally:
            queue.task_done()
