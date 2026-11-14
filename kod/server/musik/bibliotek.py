"""Butiksmusiken: tidsblock, låtbibliotek och spelordning.

Block (data/musik/block.json, kan ändras):
  10-12 Fairouz | 12-18 klassisk arabisk musik | 18-21 Umm Kulthum
Låtar ligger som egna filer i ~/skylt/musik/bibliotek/<block>/<id>.<ext>; uppgifterna i
data/musik/bibliotek.json. Borttagna låtar flyttas till bibliotek/arkiv/ (raderas aldrig).

Spelordning (data/musik/ordning.json): blandad, ny blandning varje dag, och ingen låt kommer
igen förrän alla i blocket har spelats.
"""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import threading
import unicodedata
from datetime import date, datetime
from pathlib import Path

import konfig

DATA = konfig.DATA_DIR / "musik"
BLOCK_FIL = DATA / "block.json"
BIBLIOTEK_FIL = DATA / "bibliotek.json"
ORDNING_FIL = DATA / "ordning.json"
# Pappas val per låt, i en egen fil (bibliotek.json och låtfilerna ändras aldrig för detta):
# {låt-id: {"start": sekunder, "favorit": true}}. Saknas en låt här gäller start 0 och ingen favorit.
LATVAL_FIL = DATA / "latval.json"
FAVORIT_VIKT = 2.5          # favoriter hamnar tidigare i dagens blandning (ungefär 2,5 gånger så ofta först)
FILER = konfig.SKYLT_DIR / "musik" / "bibliotek"
ARKIV = FILER / "arkiv"

STANDARD_BLOCK = [
    {"id": "fairouz", "namn": "Fairouz", "fran": 10, "till": 12, "mal": 40, "max_min": 8,
     "artister": [{"namn": "Fairouz", "sok": ["Fairuz", "Fairouz", "فيروز"]}]},
    {"id": "klassisk", "namn": "Klassisk arabisk", "fran": 12, "till": 18, "mal": 60, "max_min": 10,
     "artister": [
         {"namn": "Abdel Halim Hafez", "sok": ["Abdel Halim Hafez", "عبد الحليم حافظ", "عبدالحليم"]},
         {"namn": "Majida El Roumi", "sok": ["Majida El Roumi", "ماجدة الرومي"]},
         {"namn": "Warda", "sok": ["Warda Al Jazairia", "وردة الجزائرية", "Warda"]},
         {"namn": "Mohammed Abdel Wahab", "sok": ["Mohammed Abdel Wahab", "محمد عبد الوهاب"]},
         {"namn": "Wadih El Safi", "sok": ["Wadih El Safi", "وديع الصافي"]},
         # "صباح" betyder också "morgon" (t.ex. "فيروزيات الصباح"): bara hennes fullständiga namn.
         {"namn": "Sabah", "sok": ["Sabah El Shahroura", "صباح الشحرورة", "الشحرورة صباح"]},
     ]},
    {"id": "umm", "namn": "Umm Kulthum", "fran": 18, "till": 21, "mal": 25, "max_min": 40,
     "artister": [{"namn": "Umm Kulthum", "sok": ["Umm Kulthum", "Oum Kalthoum", "أم كلثوم", "ام كلثوم"]}]},
]

_las = threading.RLock()


def _las_json(fil: Path, standard):
    try:
        return json.loads(fil.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return standard


def _skriv_json(fil: Path, data) -> None:
    fil.parent.mkdir(parents=True, exist_ok=True)
    tmp = fil.with_name(fil.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, fil)


def normalisera(text: str) -> str:
    """Gemener, utan diakritiska tecken och med arabiska varianter förenade (أ إ آ -> ا, ة -> ه, ى -> ي)."""
    t = unicodedata.normalize("NFKD", text or "").lower()
    t = "".join(c for c in t if not unicodedata.combining(c))
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي"), ("ـ", "")):
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t).strip()


# ---------- block ----------

def block() -> list[dict]:
    b = _las_json(BLOCK_FIL, None)
    if not b:
        _skriv_json(BLOCK_FIL, STANDARD_BLOCK)
        b = STANDARD_BLOCK
    return b


def block_nu(nu: datetime | None = None) -> dict | None:
    h = (nu or datetime.now()).hour
    return next((b for b in block() if b["fran"] <= h < b["till"]), None)


def hitta_block(block_id: str) -> dict | None:
    return next((b for b in block() if b["id"] == block_id), None)


# ---------- bibliotek ----------

def latar(block_id: str | None = None, bara_aktiva: bool = True) -> list[dict]:
    alla = _las_json(BIBLIOTEK_FIL, [])
    return [l for l in alla if (block_id is None or l["block"] == block_id)
            and (not bara_aktiva or l.get("status") == "aktiv")]


def finns(lat_id: str, block_id: str | None = None) -> bool:
    return any(l["id"] == lat_id and (block_id is None or l["block"] == block_id)
               for l in _las_json(BIBLIOTEK_FIL, []))


def lagg_till(lat: dict) -> None:
    """lat: id, titel, artist, block, langd, fil, kalla ('auto'/'manuell')."""
    with _las:
        alla = _las_json(BIBLIOTEK_FIL, [])
        alla = [l for l in alla if not (l["id"] == lat["id"] and l["block"] == lat["block"])]
        alla.append({**lat, "status": "aktiv", "tillagd": datetime.now().isoformat(timespec="seconds"),
                     "spelad": 0})
        _skriv_json(BIBLIOTEK_FIL, alla)


def ta_bort(lat_id: str, block_id: str | None = None, orsak: str = "borttagen") -> dict | None:
    """Flyttar låten till arkivet (filen raderas inte) och tar bort den ur listan.
    orsak: 'borttagen' (av pappa), 'lång inledning', 'roterad' (byttes ut mot en ny, kan komma tillbaka)."""
    with _las:
        alla = _las_json(BIBLIOTEK_FIL, [])
        for l in alla:
            if l["id"] == lat_id and (block_id is None or l["block"] == block_id) and l.get("status") == "aktiv":
                fil = Path(l.get("fil", ""))
                if fil.is_file():
                    ARKIV.mkdir(parents=True, exist_ok=True)
                    mal = ARKIV / f"{l['block']}_{fil.name}"
                    shutil.move(str(fil), str(mal))
                    l["fil"] = str(mal)
                l["status"] = "arkiv"
                l["orsak"] = orsak
                l["borttagen"] = datetime.now().isoformat(timespec="seconds")
                _skriv_json(BIBLIOTEK_FIL, alla)
                return l
    return None


def ateraktivera(block_id: str, minst_dagar: int = 60) -> dict | None:
    """Tar tillbaka den låt som roterades ut längst sedan (minst minst_dagar dagar), när inga nya finns."""
    with _las:
        alla = _las_json(BIBLIOTEK_FIL, [])
        kandidater = [l for l in alla if l["block"] == block_id and l.get("status") == "arkiv"
                      and l.get("orsak") == "roterad" and Path(l.get("fil", "")).is_file()
                      and (datetime.now() - datetime.fromisoformat(l["borttagen"])).days >= minst_dagar]
        if not kandidater:
            return None
        l = min(kandidater, key=lambda x: x["borttagen"])
        fil = Path(l["fil"])
        mal = FILER / block_id / fil.name.removeprefix(f"{block_id}_")
        mal.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(fil), str(mal))
        l.update(fil=str(mal), status="aktiv", tillagd=datetime.now().isoformat(timespec="seconds"))
        l.pop("orsak", None)
        _skriv_json(BIBLIOTEK_FIL, alla)
        return l


def rotera_ut(block_id: str, antal: int, skydda_dagar: int = 14) -> list[dict]:
    """Byter ut: flyttar de mest spelade auto-låtarna (inte nya, inte pappas egna) till arkivet."""
    b = hitta_block(block_id) or {}
    aktiva = latar(block_id)
    over = len(aktiva) - b.get("mal", 40)
    antal = min(antal, over)
    if antal <= 0:
        return []
    fav = {i for i, v in latval().items() if v.get("favorit")}
    kandidater = [l for l in aktiva if l.get("kalla") == "auto" and l["id"] not in fav     # favoriter stannar
                  and (datetime.now() - datetime.fromisoformat(l["tillagd"])).days >= skydda_dagar]
    # Låtar längre än blockets max_min (från tiden då gränsen var högre) byts ut först: kortare låtar i butiken.
    max_sek = b.get("max_min", 15) * 60
    kandidater.sort(key=lambda l: (l.get("langd", 0) <= max_sek, -l.get("spelad", 0), l["tillagd"]))
    return [r for l in kandidater[:antal] if (r := ta_bort(l["id"], block_id, orsak="roterad"))]


# ---------- pappas val per låt: startpunkt och favorit ----------

def latval(lat_id: str | None = None) -> dict:
    alla = _las_json(LATVAL_FIL, {})
    return alla if lat_id is None else dict(alla.get(lat_id) or {})


def _andra_latval(lat_id: str, **varden) -> dict:
    with _las:
        alla = _las_json(LATVAL_FIL, {})
        v = dict(alla.get(lat_id) or {})
        for k, x in varden.items():
            if x is None:
                v.pop(k, None)
            else:
                v[k] = x
        if v:
            alla[lat_id] = v
        else:
            alla.pop(lat_id, None)
        _skriv_json(LATVAL_FIL, alla)
        return v


def hitta_lat(lat_id: str) -> dict | None:
    return next((l for l in _las_json(BIBLIOTEK_FIL, []) if l["id"] == lat_id), None)


AUTO_MIN = 10       # börjar sången efter minst 10 s hoppar låten dit av sig själv ...
AUTO_FORE = 2       # ... och börjar 2 s före sången


def auto_start(lat: dict | None) -> int:
    """Där sången börjar (från inledningskontrollen, 'sang_borjar'), lite före. 0 = från början."""
    s = (lat or {}).get("sang_borjar")
    if not isinstance(s, int) or s < AUTO_MIN:
        return 0
    langd = int((lat or {}).get("langd") or 0)
    return max(0, min(s - AUTO_FORE, langd - 30 if langd else s))


def startpunkt(lat_id: str | None) -> int:
    """Sekund där låten ska börja. Pappas eget val gäller alltid (även "Från början" = 0);
    annars börjar låten där sången börjar (auto_start)."""
    if not lat_id:
        return 0
    v = latval(lat_id)
    if "start" in v:
        return int(v["start"])
    return auto_start(hitta_lat(lat_id))


def satt_startpunkt(lat_id: str, sek: int | None, langd: int | None = None) -> int:
    """Sparar pappas startpunkt (0 = från början, och det gäller då i stället för den automatiska).
    Högst 30 s före låtens slut."""
    if langd is None:
        langd = int((hitta_lat(lat_id) or {}).get("langd") or 0)
    sek = max(0, int(sek or 0))
    if langd:
        sek = min(sek, max(0, langd - 30))
    _andra_latval(lat_id, start=sek, start_andrad=datetime.now().isoformat(timespec="seconds"))
    return sek


def ar_favorit(lat_id: str | None) -> bool:
    return bool(lat_id and latval(lat_id).get("favorit"))


def satt_favorit(lat_id: str, pa: bool) -> bool:
    _andra_latval(lat_id, favorit=True if pa else None)
    return bool(pa)


def _blanda(ids: list[str], slump: random.Random) -> list[str]:
    """Blandar så att favoriter oftare hamnar tidigt (viktad blandning). Utan favoriter = vanlig blandning."""
    fav = {i for i, v in latval().items() if v.get("favorit")}
    if not fav & set(ids):
        slump.shuffle(ids)
        return ids
    nycklar = {i: slump.random() ** (1 / (FAVORIT_VIKT if i in fav else 1.0)) for i in ids}
    ids.sort(key=lambda i: -nycklar[i])
    return ids


def spelad(lat_id: str) -> None:
    with _las:
        alla = _las_json(BIBLIOTEK_FIL, [])
        for l in alla:
            if l["id"] == lat_id:
                l["spelad"] = l.get("spelad", 0) + 1
                l["senast"] = datetime.now().isoformat(timespec="seconds")
        _skriv_json(BIBLIOTEK_FIL, alla)


# ---------- spelordning ----------

def nasta(block_id: str, idag: date | None = None) -> dict | None:
    """Nästa låt i blocket. Blandat, ny blandning varje dag, ingen upprepning förrän alla spelats."""
    idag = idag or date.today()
    with _las:
        aktiva = {l["id"]: l for l in latar(block_id)}
        if not aktiva:
            return None
        ordning = _las_json(ORDNING_FIL, {})
        o = ordning.get(block_id, {"kvar": [], "spelade": [], "datum": "", "senast": None, "varv": 0})
        o["kvar"] = [i for i in o["kvar"] if i in aktiva]
        o["spelade"] = [i for i in o["spelade"] if i in aktiva]
        nya = [i for i in aktiva if i not in o["kvar"] and i not in o["spelade"]]
        if nya:                                     # nya låtar kommer med redan i det här varvet
            o["kvar"] += nya
            _blanda(o["kvar"], random.Random(f"{idag}{block_id}nya{len(o['kvar'])}"))
        if o["datum"] != idag.isoformat():          # ny dag: ny blandning av det som är kvar
            _blanda(o["kvar"], random.Random(f"{idag}{block_id}"))
            o["datum"] = idag.isoformat()
        if not o["kvar"]:                           # alla spelade: nytt varv
            o["varv"] = o.get("varv", 0) + 1
            o["kvar"] = list(aktiva)
            _blanda(o["kvar"], random.Random(f"{idag}{block_id}{o['varv']}"))
            if len(o["kvar"]) > 1 and o["kvar"][0] == o.get("senast"):
                o["kvar"].append(o["kvar"].pop(0))  # aldrig samma låt två gånger i rad
            o["spelade"] = []
        lat_id = o["kvar"].pop(0)
        o["spelade"].append(lat_id)
        o["senast"] = lat_id
        ordning[block_id] = o
        _skriv_json(ORDNING_FIL, ordning)
        return aktiva[lat_id]
