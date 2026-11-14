"""Designförslag som stillbilder:
    .venv/bin/python skisser.py monster.jpg bananer.jpg utmapp/
"""
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

from video.design import DESIGNER, poppins, stillbild

monster, bananer, ut = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
ut.mkdir(parents=True, exist_ok=True)
fall = [("monster", monster, "Monster Energy Ultra", "19 kr", False),
        ("bananer", bananer, "Bananer", "2 för 10 kr", True)]
bilder = {}
for kod, fn in DESIGNER.items():
    for namn, foto, rubrik, pris, fynd in fall:
        t = time.time()
        l = fn(foto, rubrik, pris, fynd)
        b = stillbild(l)
        b.save(ut / f"{kod}_{namn}.jpg", quality=92)
        bilder[(kod, namn)] = b
        print(f"{kod} {namn}: frilagd={l.frilagd} {time.time() - t:.1f}s")

# Översikt: en rad per design
sm = 360
ark = Image.new("RGB", (2 * sm + 140, 3 * (sm * 16 // 9) + 40), (30, 30, 30))
d = ImageDraw.Draw(ark)
for i, kod in enumerate(DESIGNER):
    y = 20 + i * (sm * 16 // 9)
    d.text((40, y + 300), kod, font=poppins("Black", 90), fill=(255, 255, 255), anchor="mm")
    for j, namn in enumerate(["monster", "bananer"]):
        ark.paste(bilder[(kod, namn)].resize((sm - 10, sm * 16 // 9 - 10)), (90 + j * (sm + 10), y))
ark.save(ut / "oversikt.jpg", quality=90)
print("klar")
