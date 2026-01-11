import asyncio
from typing import TypedDict, Optional
from config import QUEUE_MAXSIZE
from state import Mode

class Task(TypedDict):
    type: Mode
    chat_id: int
    prompt: Optional[str]
    photo: Optional[str]

queue: asyncio.Queue[Task] = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
