async def worker():
    logger.info("Worker started")

    while True:
        task = await queue.get()
        try:
            input_data = {"prompt": task["prompt"]}

            if task["type"] == "photo_video" and task["photo"]:
                input_data["image"] = task["photo"]

            result = await asyncio.to_thread(
                replicate_client.run,
                KLING_MODEL,
                input_data,
            )

            await bot.send_message(
                task["chat_id"],
                f"✅ Готово:\n{result}"
            )

        except Exception as e:
            logger.exception("Worker error")
            await bot.send_message(
                task["chat_id"],
                "❌ Произошла ошибка при генерации"
            )
        finally:
            queue.task_done()