"""Demovideo utan Telegram, med samma regler som boten för text, antal exemplar och övergångar:
    .venv/bin/python demo_video.py ut.mp4 "redbull 15 + pant" foto1 [foto2 foto3] [--in zoom --ut wipe]
Texten tolkas precis som när pappa skriver den. Utan --in/--ut slumpas övergångarna.
"""
import argparse
import asyncio
import time
from pathlib import Path

import konfig
import tolka
import uppstallning
from video import overgangar
from video.animation import rendera


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ut", type=Path)
    ap.add_argument("text")
    ap.add_argument("fotos", nargs="+", type=Path)
    ap.add_argument("--in", dest="ing", choices=overgangar.INGANGAR)
    ap.add_argument("--ut", dest="utg", choices=overgangar.UTGANGAR)
    a = ap.parse_args()
    konfig.lag_prioritet()      # som boten: lägsta prioritet, kärna 1-3
    t = tolka.tolka(a.text)
    print("tolkat:", tolka.sammanfattning(t.rubrik, t.pris, t.utgar))
    valt = overgangar.valj()
    overgang = (a.ing or valt[0], a.utg or valt[1])
    upp = uppstallning.bestam(t.rubrik, t.pris, len(a.fotos), t.antal)
    print(f"uppställning: {upp.exemplar} exemplar, {upp.stil} ({upp.skal}); {overgangar.beskriv(overgang)}")
    a.ut.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    res = await rendera(a.fotos, t.rubrik, t.pris, t.typ == "fynd", a.ut, upp.exemplar, upp.stil, overgang)
    print(f"klar: {a.ut}  ({time.time() - start:.1f} s totalt)  små bilder: {res['sma']}")


asyncio.run(main())
