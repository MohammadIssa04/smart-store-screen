"""Ritar provetiketter (som de skrivs ut) och ett ark med alla för granskning. Skriver inte ut något.

    python demo_etikett.py [mapp]      (standard /tmp/etiketter)
"""
import sys
from pathlib import Path

from PIL import Image

import etikett

PROV = [
    ("Red Bull", "15 kr + pant"),
    ("Bananer", "19,90 kr/kg"),
    ("Coca-Cola Zero 33 cl", "2 för 20 kr"),
    ("Basmatiris Tilda 5 kg", "129 kr"),
    ("Färska dadlar Medjool extra stora", "49 kr"),
    ("Mjölk", "9 kr"),
    ("Libanesiskt bröd", "2 för 30"),
    ("Olivolja extra jungfru 1 liter från Libanon", "1 299 kr"),
]

ut = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/etiketter")
ut.mkdir(parents=True, exist_ok=True)
bilder = []
for i, (namn, pris) in enumerate(PROV):
    e = etikett.rita(namn, pris)
    assert e.size == (etikett.BREDD, etikett.HOJD) and e.mode == "1", e
    e.save(ut / f"{i}.png")
    bilder.append(e.convert("L"))
ark = Image.new("L", (etikett.BREDD * 2 + 30, (etikett.HOJD + 20) * 4 + 10), 180)
for i, b in enumerate(bilder):
    ark.paste(b, (10 + (i % 2) * (etikett.BREDD + 10), 10 + (i // 2) * (etikett.HOJD + 20)))
ark.save(ut / "ark.png")
s = etikett.for_skrivaren(etikett.rita("Mjölk", "9 kr"))
print("skrivarbild", s.size, s.mode)
print("ark", ut / "ark.png")
