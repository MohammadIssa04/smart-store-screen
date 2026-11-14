"""Provar bildsöket för några varor (utan Telegram, publicerar inget) och gör ett ark med de
frilagda bilderna för granskning.  .venv/bin/python demo_bildsok.py [vara ...]"""
import asyncio
import logging
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

import bildsok
import konfig
from video.frilagg import cache_fil

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
konfig.lag_prioritet()
VAROR = sys.argv[1:] or ["Röda äpplen", "Liba bröd", "Coca-Cola Zero 33 cl", "Bananer"]


async def main():
    rot = Path(tempfile.mkdtemp(prefix="bildsok_"))
    rader = []
    for vara in VAROR:
        mapp = rot / vara.replace(" ", "_")
        mapp.mkdir()
        bilder = await bildsok.hamta_bilder(vara, mapp)
        print(f"== {vara}: {len(bilder)} godkända", flush=True)
        rader.append((vara, [cache_fil(b) for b in bilder]))
    ark = Image.new("RGB", (4 * 300, len(rader) * 340), (233, 30, 99))
    d = ImageDraw.Draw(ark)
    for y, (vara, bilder) in enumerate(rader):
        d.text((10, y * 340 + 5), f"{vara}: {len(bilder)}", fill="white")
        for x, b in enumerate(bilder[:4]):
            im = Image.open(b).convert("RGBA")
            im.thumbnail((280, 300))
            ark.paste(im, (x * 300 + 10, y * 340 + 30), im)
    ark.save(rot / "ark.png")
    print("ark", rot / "ark.png")


asyncio.run(main())
