from __future__ import annotations

from pathlib import Path

from .bas import Stil
from .mall import rendera

STIL = Stil(
    namn="erbjudande",
    bakgrund="0xFAFAF7",     # nästan vit
    text="0x141414",         # nästan svart
    bricka_bg="0xE4002B",    # klassisk röd prisbricka
    bricka_text="0xFFFFFF",
)


async def rendera_erbjudande(foto: Path, rubrik: str, pris: str, ut: Path) -> Path:
    return await rendera(foto, rubrik, pris, STIL, ut)
