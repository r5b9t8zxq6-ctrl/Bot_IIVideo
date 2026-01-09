import asyncio
import logging

import replicate
from replicate.exceptions import ReplicateError

from config import REPLICATE_API_TOKEN

client = replicate.Client(api_token=REPLICATE_API_TOKEN)


def enhance_prompt(text: str) -> str:
    return (
        "Ultra realistic photo. "
        f"{text}. "
        "Natural lighting, 35mm, high detail, cinematic realism."
    )


def extract_urls(output):
    images = []
    if isinstance(output, list):
        for item in output:
            if isinstance(item, str):
                images.append(item)
            elif hasattr(item, "url"):
                images.append(item.url)
    elif isinstance(output, dict):
        images = output.get("images", [])
    return images


async def run_replicate(generate_func, timeout=120):
    try:
        output = await asyncio.wait_for(
            asyncio.to_thread(generate_func),
            timeout=timeout
        )
        return extract_urls(output)

    except asyncio.TimeoutError:
        logging.error("Replicate timeout")
        return None

    except ReplicateError as e:
        if "429" in str(e):
            return "RATE_LIMIT"
        logging.exception("Replicate API error")
        return None

    except Exception:
        logging.exception("Unknown replicate error")
        return None
