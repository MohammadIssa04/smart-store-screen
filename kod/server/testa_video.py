"""Gör en testvideo utan Telegram:
    .venv/bin/python testa_video.py foto.jpg "Monster 19 kr 3 dagar" ut.mp4
"""
import asyncio
import sys
from pathlib import Path

import tolka
from video import skapa_video


async def main() -> None:
    foto, text, ut = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    t = tolka.tolka(text)
    print(t)
    ut.parent.mkdir(parents=True, exist_ok=True)
    await skapa_video(foto, t.typ, t.rubrik, t.pris, ut)
    print("klar:", ut)


asyncio.run(main())
