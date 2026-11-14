"""Gör en video av ett eget foto som appen/boten skulle göra (känner igen, beskär skärmdumpar, väljer
uppställning, renderar med kvalitetskontroll). Publicerar inget.
    set -a; . ./butiksbot.env; set +a; .venv/bin/python demo_foto.py foto.jpg [text]"""
import asyncio
import logging
import shutil
import sys
from pathlib import Path

import tjanst

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def main():
    a = tjanst.nytt_arende(text=" ".join(sys.argv[2:]))
    mal = Path(a["mapp"]) / "foto0"
    shutil.copy(sys.argv[1], mal)
    a["fotos"].append(str(mal))
    if a["text"]:
        await tjanst.tolka_text(a, a["text"])
    await tjanst.kanna_igen_fotos(a)
    if m := tjanst.fran_minnet(a):
        print(m)
    if tjanst.nasta_steg(a).behover == "leta_bilder":
        print("letar på nätet:", await tjanst.leta_bilder(a) or "hittade", flush=True)
    print("ärende:", a["rubrik"], a["pris"], "fyller:", a.get("fyller"), "fotos:", a["fotos"], flush=True)
    u = await tjanst.gor_video(a)
    print("VIDEO", u.post["video"], u.notiser, flush=True)


asyncio.run(main())
