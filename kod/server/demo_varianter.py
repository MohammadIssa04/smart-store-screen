"""Renderar några annonser med olika varianter (layout, färgton, bricka, entré) och gör ett ark med en
bildruta från varje, för granskning. Publicerar inget.   .venv/bin/python demo_varianter.py [antal]"""
import asyncio
import random
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

import konfig
from video.animation import ny_variant, rendera
from video.overgangar import INGANGAR, UTGANGAR

konfig.lag_prioritet()
VAROR = [("potatis", "Potatis", "7 kr", "hog", 3), ("tomater", "Tomater", "29,90 kr/kg", "hog", 3),
         ("gurka", "Gurka", "2 för 20 kr", "rad", 2), ("rodlok", "Rödlök", "15 kr/kg", "hog", 3)]


async def main():
    antal = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    ut = Path(tempfile.mkdtemp(prefix="varianter_"))
    slump = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 5)
    v = None
    rutor = []
    for i in range(antal):
        mapp_namn, namn, pris, stil, ex = VAROR[i % len(VAROR)]
        foton = sorted((konfig.DATA_DIR / "bildforrad" / mapp_namn).glob("2*_0"))
        if not foton:
            continue
        v = ny_variant(v, slump)
        og = (slump.choice(INGANGAR), slump.choice(UTGANGAR))
        r = await rendera([foton[0]], namn, pris, False, ut / f"v{i}.mp4", exemplar=ex, stil=stil, overgang=og, variant=v)
        print(f"v{i}: {namn} {og} {v}", flush=True)
        ruta = ut / f"v{i}.png"
        for t in ("1.0", "5.2"):          # mitt i entrén och när allt står still
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", t, "-i", str(r["video"]), "-frames:v", "1", str(ruta)])
            rutor.append(Image.open(ruta).resize((360, 640)))
    ark = Image.new("RGB", (360 * len(rutor) + 10 * (len(rutor) + 1), 660), (40, 40, 40))
    for i, r in enumerate(rutor):
        ark.paste(r, (10 + i * 370, 10))
    ark.save(ut / "ark.png")
    print("ark", ut / "ark.png")


asyncio.run(main())
