from typing import Dict, Literal

Mode = Literal[
    "video",
    "image",
    "photo_video",
    "gpt",
    "gpt_kling",
    "instagram",
    "insta_script",
    "insta_voice",
]

user_modes: Dict[int, Mode] = {}
user_photos: Dict[int, str] = {}
