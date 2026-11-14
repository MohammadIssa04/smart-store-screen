"""Testar Gemini-kvalitetskontrollen i botens riktiga flöde (utan Telegram, publicerar inget):
  1. bra video (Red Bull, 3 burkar)
  2. fel pris i videon jämfört med texten
  3. en burk utanför bildkanten
    set -a; . ./butiksbot.env; set +a; .venv/bin/python testa_kvalitet.py foto.jpg [fall ...]
Skriver vad boten sa till pappa och vad Gemini svarade vid varje kontroll."""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("ALLOWED_IDS", "1")
import bot  # noqa: E402
import minne  # noqa: E402
import testa_flode as tf  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="butiksbot_kvalitet_"))
minne.KONTROLLER = TMP / "kontroller.jsonl"
minne.OVERGANGAR = TMP / "overgangar.json"
bot.konfig.UTKAST_DIR = TMP / "utkast"
FOTO = Path(sys.argv[1])

FALL = {
    "bra": {},
    "fel_pris": {"pris_forsta": "19 kr"},
    "utanfor_kant": {"justering": {"test_flytta_x": 400}},
}


async def kor(namn: str, test: dict) -> None:
    a = bot.nytt_arende(rubrik="Red Bull", pris="15 kr + pant", text="redbull 15 + pant")
    foto = Path(a["mapp"]) / "foto0.jpg"
    shutil.copy(FOTO, foto)
    mask = FOTO.with_name(FOTO.name + ".mask.png")
    if mask.exists():
        shutil.copy(mask, foto.with_name(foto.name + ".mask.png"))
    a["fotos"], a["test"] = [str(foto)], test
    fore = len(minne.kontroller(1000))
    t = time.time()
    await bot.gor_utkast(tf.Meddelande(), tf.ctx, a)
    print(f"\n==================== FALL: {namn}  ({time.time() - t:.0f} s) ====================")
    print("Till pappa:")
    for rad in tf.SVAR:
        print("   ", rad)
    tf.SVAR.clear()
    for logg in minne.kontroller(1000)[fore:]:
        print(f"Resultat: {logg['slutligt']}, omgörningar: {logg['omgorningar']}, vald video: "
              f"{Path(logg['vald_video']).name}, notiser: {logg['notiser']}")
        for k in logg["kontroller"]:
            print(f"  -- försök {k['forsok']} ({Path(k['video']).name}, {k['sekunder']} s, justering "
                  f"{k['justering']}): {k['resultat']}, åtgärder {k.get('atgarder', [])}")
            if k.get("svar"):
                print("     Gemini:", json.dumps(k["svar"], ensure_ascii=False, indent=2).replace("\n", "\n     "))


async def main() -> None:
    for namn in sys.argv[2:] or FALL:
        await kor(namn, FALL[namn])
    print("\nKlart. Videor och logg i", TMP)


asyncio.run(main())
