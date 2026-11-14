"""Testar startpunkt och favoriter per låt (musik/bibliotek.py) i en tillfällig mapp. Rör inga riktiga filer.
    .venv/bin/python testa_latval.py"""
import json
import random
import tempfile
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from musik import bibliotek as bib

TMP = Path(tempfile.mkdtemp(prefix="butiksbot_latval_"))
bib.DATA = TMP
bib.BIBLIOTEK_FIL, bib.ORDNING_FIL, bib.LATVAL_FIL = TMP / "bibliotek.json", TMP / "ordning.json", TMP / "latval.json"
gammal = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
latar = [{"id": f"l{i}", "titel": f"Låt {i}", "artist": "A", "block": "b", "status": "aktiv", "langd": 600,
          "fil": str(TMP / f"l{i}.mp3"), "kalla": "auto", "tillagd": gammal, "spelad": 50 - i} for i in range(20)]
bib.BIBLIOTEK_FIL.write_text(json.dumps(latar), encoding="utf-8")
bib.hitta_block = lambda b: {"id": "b", "mal": 18}
fore = bib.BIBLIOTEK_FIL.read_text(encoding="utf-8")
res = []


def kolla(namn, ok, info=""):
    res.append(bool(ok))
    print(f"{'OK ' if ok else 'FEL'} {namn}{'  (' + str(info) + ')' if info != '' else ''}")


kolla("utan val: börjar från början", bib.startpunkt("l1") == 0)
kolla("+10 s sparas", bib.satt_startpunkt("l1", bib.startpunkt("l1") + 10) == 10 and bib.startpunkt("l1") == 10)
bib.satt_startpunkt("l1", bib.startpunkt("l1") + 10)
kolla("+10 igen = 20 s", bib.startpunkt("l1") == 20)
kolla("-10 under noll blir 0", bib.satt_startpunkt("l2", -10) == 0 and bib.startpunkt("l2") == 0)
kolla("högst 30 s före slutet", bib.satt_startpunkt("l3", 9999) == 570)
kolla("från början sparas som eget val", bib.satt_startpunkt("l3", 0) == 0 and bib.latval("l3").get("start") == 0)
kolla("okontrollerad låt börjar från början", bib.startpunkt("l4") == 0)
kolla("okänd låt: 0", bib.startpunkt(None) == 0)
bib.satt_favorit("l19", True)
bib.satt_favorit("l18", True)
kolla("favorit sparas", bib.ar_favorit("l19") and bib.latval("l19").get("favorit"))
kolla("startpunkt och favorit samtidigt", bib.latval("l1") .get("start") == 20)
bib.satt_favorit("l18", False)
kolla("favorit kan tas bort", not bib.ar_favorit("l18"))
kolla("bibliotek.json orörd", bib.BIBLIOTEK_FIL.read_text(encoding="utf-8") == fore)

# Automatisk start där sången börjar (inledningskontrollens sang_borjar), om inget eget val finns
alla = json.loads(fore)
for l in alla:
    l["sang_borjar"] = {"l5": 95, "l6": 4, "l7": -1, "l3": 80, "l8": 590}.get(l["id"], l.get("sang_borjar"))
bib.BIBLIOTEK_FIL.write_text(json.dumps(alla), encoding="utf-8")
kolla("börjar där sången börjar (2 s före)", bib.startpunkt("l5") == 93, bib.startpunkt("l5"))
kolla("kort inledning: från början", bib.startpunkt("l6") == 0)
kolla("ingen sång: från början", bib.startpunkt("l7") == 0)
kolla("eget val (från början) går före", bib.startpunkt("l3") == 0)
kolla("aldrig närmare än 30 s före slutet", bib.startpunkt("l8") == 570, bib.startpunkt("l8"))
bib.satt_startpunkt("l5", bib.startpunkt("l5") + 10)
kolla("+10 från den automatiska", bib.startpunkt("l5") == 103)
bib.BIBLIOTEK_FIL.write_text(fore, encoding="utf-8")

# Viktad blandning: favoriten l19 hamnar oftare bland de första fem
forst = Counter()
for d in range(300):
    ids = [l["id"] for l in latar]
    forst.update(bib._blanda(ids, random.Random(d))[:5])
kolla("favorit oftare tidigt", forst["l19"] > 1.5 * (sum(forst.values()) - forst["l19"]) / 19, f"{forst['l19']} av 300")
ids = [l["id"] for l in latar]
kolla("blandningen tappar inga låtar", sorted(bib._blanda(list(ids), random.Random(1))) == sorted(ids))

# Rotationen byter aldrig ut en favorit (l19 är minst spelad, l0 mest; gör l0 till favorit)
bib.satt_favorit("l0", True)
moved = []
bib.ta_bort = lambda i, b, orsak="": moved.append(i) or {"id": i}
bib.rotera_ut("b", 2)
kolla("rotationen skonar favoriter", "l0" not in moved and len(moved) == 2, moved)

# Spelordningen fungerar med favoriter
spelade = [bib.nasta("b", date(2026, 11, 14))["id"] for _ in range(20)]
kolla("hela varvet utan upprepning", len(set(spelade)) == 20)

print(f"{sum(res)}/{len(res)} OK  (testmapp {TMP})")
