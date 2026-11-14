"""Nattjobbet: förbereder snygga bilder på butikens vanliga varor medan Gemini-kvoten är ledig, så att
pappa får en färdig bild direkt när han gör en annons ("potatis 7") – utan väntan.

Varor: allt som har annonserats förut + en lista med vanlig frukt och grönt (VANLIGA). Varor som har en
färsk bild i förrådet (yngre än FORNYA_DAGAR) eller i produktminnet (pappa har publicerat dem) hoppas
över. Högst MAX_PER_NATT varor per natt. Körs av boten kl 02:30 med lägsta prioritet på kärna 1-3.
    set -a; . ./butiksbot.env; set +a; .venv/bin/python forbered_bilder.py [max]
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import bildsok
import konfig
import minne
from lager import Lager

log = logging.getLogger("butiksbot.forbered")
MAX_PER_NATT = 12
FORNYA_DAGAR = 45
LOGG = konfig.DATA_DIR / "minne" / "forrad.jsonl"

VANLIGA = [
    "Potatis", "Tomater", "Gurka", "Bananer", "Röda äpplen", "Gröna äpplen", "Apelsiner", "Citroner",
    "Gul lök", "Rödlök", "Vitlök", "Röd paprika", "Morötter", "Avokado", "Gröna vindruvor", "Päron",
    "Clementiner", "Persilja", "Mynta", "Aubergine", "Zucchini", "Vattenmelon", "Kiwi", "Mango",
    "Granatäpple", "Dadlar", "Ingefära", "Grön chili", "Isbergssallad", "Koriander", "Lime", "Blomkål",
]


def varor() -> list[str]:
    """Tidigare annonserade varor först (de är butikens egna), sedan VANLIGA. Utan dubbletter."""
    namn: list[str] = []
    try:
        poster = sorted(Lager(konfig.LAGER_FIL).poster, key=lambda p: p.get("skapad", ""), reverse=True)
        namn += [p["rubrik"] for p in poster if p.get("rubrik")]
    except Exception:
        log.exception("Kunde inte läsa annonserna")
    namn += VANLIGA
    ut, sedda = [], set()
    for n in namn:
        k = minne.nyckel(minne.synonym(n))
        if k and k not in sedda:
            sedda.add(k)
            ut.append(n)
    return ut


def behover(namn: str) -> bool:
    if minne.hitta_produkt(namn):
        return False                      # pappas egen publicerade bild finns redan
    try:
        info = json.loads((bildsok.FORRAD / bildsok._forrad_nyckel(namn) / "info.json").read_text(encoding="utf-8"))
        return time.time() - info.get("tid", 0) > FORNYA_DAGAR * 86400
    except (OSError, ValueError):
        return True


async def forbered(max_varor: int = MAX_PER_NATT) -> dict:
    klara, tomma = [], []
    for namn in [n for n in varor() if behover(n)][:max_varor]:
        with tempfile.TemporaryDirectory(prefix="forrad_") as mapp:
            try:
                bilder = await bildsok.hamta_bilder(namn, Path(mapp), forrad=False)
            except Exception:
                log.exception("Bildsöket misslyckades för %s", namn)
                bilder = []
            antal = bildsok.spara_i_forradet(namn, bilder)
        (klara if antal else tomma).append(namn)
        LOGG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOGG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"tid": datetime.now().isoformat(timespec="seconds"), "namn": namn,
                                "bilder": antal}, ensure_ascii=False) + "\n")
        log.info("Förrådet: %s -> %d bilder", namn, antal)
    return {"klara": klara, "utan_bild": tomma}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    konfig.lag_prioritet()
    print(asyncio.run(forbered(int(sys.argv[1]) if len(sys.argv) > 1 else MAX_PER_NATT)))
