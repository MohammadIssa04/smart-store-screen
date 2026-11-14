"""Testar "olika smaker" i botens riktiga flöde: nätsökning, en bild per smak, video och
Gemini-kontroll. Publicerar inget och skriver till en tillfällig mapp.
    set -a; . ./butiksbot.env; set +a; .venv/bin/python testa_smaker.py "redbull olika smaker" "15 + pant"
"""
import asyncio
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("ALLOWED_IDS", "1")
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
import bot  # noqa: E402
import minne  # noqa: E402
import testa_flode as tf  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="butiksbot_smaker_"))
for namn in ("PRODUKTER", "SYNONYMER", "GODKANDA", "OFORSTATT", "OVERGANGAR", "KONTROLLER"):
    setattr(minne, namn, TMP / getattr(minne, namn).name)
bot.konfig.UTKAST_DIR = TMP / "utkast"
bot.TILLATNA.add(1)          # låtsasanvändaren i testa_flode


async def main() -> None:
    text, pris = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""
    t = time.time()
    await tf.skicka_text(text)
    if pris and bot.vantar.get(1, {}).get("steg") == "pris":
        await tf.skicka_text(pris)
    print("\n".join(tf.SVAR))
    print(f"(tid: {time.time() - t:.0f} s)")
    a = next((u["arende"] for u in bot.utkast.values()), None)
    if a:
        print("Bilder:", a["fotos"])
    for k in minne.kontroller(10):
        print("Kontroll:", k["slutligt"], "| omgörningar", k["omgorningar"],
              "|", [(x["resultat"], (x.get("svar") or {}).get("problem")) for x in k["kontroller"]])


asyncio.run(main())
