"""Testar AI-anslutningen med riktiga anrop (kräver GEMINI_API_KEY):
    set -a; . ./butiksbot.env; set +a; .venv/bin/python testa_ai.py foto.jpg
Känner igen varan på fotot och tolkar en oklar text. Publicerar inget."""
import asyncio
import sys
from pathlib import Path

import igenkanning as ai


async def main() -> None:
    print("Leverantör:", ai.leverantor() or "INGEN (nyckel saknas)")
    if not ai.tillganglig():
        return
    print("Igenkänning:", await ai.kanna_igen(Path(sys.argv[1])))
    print("Oklar text:", await ai.tolka_text("har fått in redbull, kör 15 spänn plus pant hela veckan",
                                             [{"text": "bananer 10/kg 3d",
                                               "tolkat": {"namn": "Bananer", "pris": "10 kr/kg", "dagar": 3,
                                                          "fynd": False}}]))


asyncio.run(main())
