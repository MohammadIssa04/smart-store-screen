from __future__ import annotations

from pathlib import Path

from .erbjudande import rendera_erbjudande
from .fynd import rendera_fynd


async def skapa_video(foto: Path, typ: str, rubrik: str, pris: str, ut: Path) -> Path:
    if typ == "fynd":
        return await rendera_fynd(foto, rubrik, pris, ut)
    return await rendera_erbjudande(foto, rubrik, pris, ut)
