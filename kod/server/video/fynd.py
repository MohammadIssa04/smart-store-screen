from __future__ import annotations

from pathlib import Path

from .bas import Stil
from .mall import rendera

STIL = Stil(
    namn="fynd",
    bakgrund="0xFAFAF7",
    text="0x141414",
    bricka_bg="0xFFD400",    # gul bricka skiljer fyndet från vanliga erbjudanden
    bricka_text="0x141414",
    etikett="DAGENS FYND",
    etikett_bg="0x141414",
    etikett_text="0xFFD400",
)


async def rendera_fynd(foto: Path, rubrik: str, pris: str, ut: Path) -> Path:
    return await rendera(foto, rubrik, pris, STIL, ut)
