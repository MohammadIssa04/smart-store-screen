"""Det boten lär sig över tid. Allt ligger som vanliga filer under data/minne/ så att
det går att läsa, rätta och säkerhetskopiera för hand – och så att en framtida app
(pappas musikapp) kan använda samma minne utan Telegram.

  produkter.json   namn -> sparade bilder (original + friläggning) och varutyp
  synonymer.json   pappas egna ord: "redbull sockerfri" -> "Red Bull Sugarfree"
  godkanda.jsonl   texter som blev publicerade, med hur de tolkades (exempel till AI:n)
  oforstatt.jsonl  allt boten inte förstod, som avbröts eller rättades (att gå igenom)
  overgangar.json  senast använda övergång
  kontroller.jsonl varje automatisk kvalitetskontroll (Gemini): problem, åtgärder, försök
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path

import konfig

log = logging.getLogger("butiksbot.minne")

MAPP = konfig.DATA_DIR / "minne"
BILDER = MAPP / "bilder"
PRODUKTER = MAPP / "produkter.json"
SYNONYMER = MAPP / "synonymer.json"
GODKANDA = MAPP / "godkanda.jsonl"
OFORSTATT = MAPP / "oforstatt.jsonl"
OVERGANGAR = MAPP / "overgangar.json"
KONTROLLER = MAPP / "kontroller.jsonl"

_las = threading.Lock()


def nyckel(namn: str) -> str:
    """'Red Bull ', 'red-bull', 'REDBULL' -> 'redbull'. Samma vara oavsett stavning/mellanslag."""
    return re.sub(r"[^0-9a-zåäöéü]", "", (namn or "").lower())


def _las_json(fil: Path, standard):
    try:
        return json.loads(fil.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return standard
    except Exception:
        log.exception("Kunde inte läsa %s", fil)
        return standard


def _skriv_json(fil: Path, data) -> None:
    fil.parent.mkdir(parents=True, exist_ok=True)
    tmp = fil.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(fil)


def _lagg_till(fil: Path, rad: dict) -> None:
    fil.parent.mkdir(parents=True, exist_ok=True)
    rad = {"tid": datetime.now().isoformat(timespec="seconds"), **rad}
    with _las, open(fil, "a", encoding="utf-8") as f:
        f.write(json.dumps(rad, ensure_ascii=False) + "\n")


def _las_rader(fil: Path) -> list[dict]:
    try:
        rader = fil.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    ut = []
    for r in rader:
        try:
            ut.append(json.loads(r))
        except json.JSONDecodeError:
            pass
    return ut


# ---------- synonymer ----------

def synonym(namn: str) -> str:
    """Pappas rättade namn om han har rättat det förut, annars namnet som det är."""
    return _las_json(SYNONYMER, {}).get(nyckel(namn), namn)


def spara_synonym(fran: str, till: str) -> None:
    if not fran or not till or nyckel(fran) == nyckel(till):
        return
    with _las:
        s = _las_json(SYNONYMER, {})
        s[nyckel(fran)] = till
        _skriv_json(SYNONYMER, s)
    log.info("Synonym: %r -> %r", fran, till)


# ---------- produktminne ----------

def hitta_produkt(namn: str) -> dict | None:
    """Sparad vara med bilder som fortfarande finns, eller None."""
    p = _las_json(PRODUKTER, {}).get(nyckel(synonym(namn)))
    if not p:
        return None
    bilder = [b for b in p.get("bilder", []) if Path(b).exists()]
    return {**p, "bilder": bilder} if bilder else None


def spara_produkt(namn: str, fotos: list[str], vartyp: str | None = None) -> None:
    """Kopierar fotona och deras friläggning (<foto>.mask.png) till minnet.
    Senast publicerade bilderna gäller; gamla filer ligger kvar (raderas aldrig)."""
    k = nyckel(namn)
    if not k or not fotos:
        return
    BILDER.mkdir(parents=True, exist_ok=True)
    stampel = datetime.now().strftime("%Y%m%d%H%M%S")
    sparade = []
    for i, f in enumerate(fotos):
        kalla = Path(f)
        if not kalla.exists():
            continue
        mal = BILDER / f"{k}_{stampel}_{i}{kalla.suffix}"
        shutil.copy2(kalla, mal)
        mask = kalla.with_name(kalla.name + ".mask.png")
        if mask.exists():
            shutil.copy2(mask, mal.with_name(mal.name + ".mask.png"))
        sparade.append(str(mal))
    if not sparade:
        return
    with _las:
        alla = _las_json(PRODUKTER, {})
        gammal = alla.get(k, {})
        alla[k] = {"namn": namn, "bilder": sparade, "vartyp": vartyp or gammal.get("vartyp"),
                   "publicerad": gammal.get("publicerad", 0) + 1,
                   "senast": datetime.now().isoformat(timespec="seconds")}
        _skriv_json(PRODUKTER, alla)
    log.info("Produktminne: %s (%d bilder)", namn, len(sparade))


# ---------- godkända exempel och sådant boten inte förstod ----------

def spara_godkand(text: str, tolkat: dict) -> None:
    if text:
        _lagg_till(GODKANDA, {"text": text, "tolkat": tolkat})


def senaste_godkanda(n: int = 8) -> list[dict]:
    return _las_rader(GODKANDA)[-n:]


def logga_oforstatt(handelse: str, text: str = "", **detaljer) -> None:
    """handelse: 'pris_saknas', 'pris_oforstatt', 'namn_saknas', 'ej_igenkand', 'avbruten',
    'namn_rattat', 'annan_bild', 'ai_tolkning' ..."""
    _lagg_till(OFORSTATT, {"handelse": handelse, "text": text, **detaljer})


def oforstatt(n: int = 50) -> list[dict]:
    return _las_rader(OFORSTATT)[-n:]


# ---------- övergångar ----------

def senaste_overgang() -> tuple[str, str] | None:
    s = _las_json(OVERGANGAR, {}).get("senaste")
    return tuple(s) if s else None


def spara_overgang(overgang: tuple[str, str]) -> None:
    with _las:
        d = _las_json(OVERGANGAR, {})
        d["senaste"] = list(overgang)
        _skriv_json(OVERGANGAR, d)


def senaste_variant() -> dict | None:
    return _las_json(OVERGANGAR, {}).get("variant")


def spara_variant(variant: dict) -> None:
    with _las:
        d = _las_json(OVERGANGAR, {})
        d["variant"] = variant
        _skriv_json(OVERGANGAR, d)


# ---------- kvalitetskontroller ----------

def logga_kontroll(rad: dict) -> None:
    _lagg_till(KONTROLLER, rad)


def kontroller(n: int = 50) -> list[dict]:
    return _las_rader(KONTROLLER)[-n:]
