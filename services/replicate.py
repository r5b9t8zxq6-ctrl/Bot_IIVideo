import asyncio
import replicate
from config import REPLICATE_API_TOKEN, KLING_MODEL

client = replicate.Client(api_token=REPLICATE_API_TOKEN)

async def generate_video(prompt: str, image: str | None = None):
    input_data = {"prompt": prompt}
    if image:
        input_data["image"] = image

    return await asyncio.to_thread(
        client.run,
        KLING_MODEL,
        input_data,
    )
