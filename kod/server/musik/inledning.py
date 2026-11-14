"""Låtar med jättelång inledning (t.ex. Umm Kulthums konsertinspelningar där sången börjar efter
20-30 minuter) passar inte i butiken. Gemini lyssnar på början av låten och säger när sången börjar;
börjar den senare än INLEDNING_MAX_MIN (standard 8) flyttas låten till arkivet (raderas inte).

    .venv/bin/python -m musik.inledning            # kontrollerar alla långa låtar som inte är kontrollerade
    .venv/bin/python -m musik.inledning --visa     # bara visa, flytta inget
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import igenkanning
import konfig
from musik import bibliotek as bib

log = logging.getLogger("butiksbot.musik.inledning")
MAX_MIN = float(os.environ.get("INLEDNING_MAX_MIN", "8"))
LYSSNA_MIN = 40                 # så mycket av början som skickas (lågt bitflöde, mono)
LOGG = bib.DATA / "inledning.jsonl"

SCHEMA = {
    "type": "object",
    "properties": {
        "sang_borjar_sek": {"type": "integer", "description": "sekund då sångaren börjar sjunga, -1 om ingen sång hörs"},
        "saker": {"type": "boolean"},
    },
    "required": ["sang_borjar_sek", "saker"],
}
PROMPT = ("Detta är början (högst {min} minuter) av en arabisk låt av {artist}. Vid vilken sekund börjar "
          "sångaren eller sångerskan sjunga för första gången? Räkna inte instrument, orkesterns inledning, "
          "publikens applåder eller jubel, eller en presentatör som pratar. Hörs ingen sång alls i klippet: -1. "
          "saker = true om du är säker.")


def lang_lat(lat: dict) -> bool:
    """Bara långa låtar kan flyttas till arkivet för lång inledning (korta får börja där sången börjar)."""
    return lat.get("langd", 0) > MAX_MIN * 60 + 60


def behover_kontroll(lat: dict) -> bool:
    """Ingen vet ännu var sången börjar (alla låtar kontrolleras, så att de kan börja där)."""
    return "sang_borjar" not in lat


def _klipp(fil: Path, ut: Path) -> bool:
    r = subprocess.run([*konfig.lag_prioritet_prefix(), "ffmpeg", "-v", "error", "-y", "-t", str(LYSSNA_MIN * 60),
                        "-i", str(fil), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "12k",
                        "-threads", "1", str(ut)], capture_output=True, timeout=600)
    return r.returncode == 0 and ut.is_file() and ut.stat().st_size > 1000


async def sang_borjar(lat: dict) -> int | None:
    """Sekunden då sången börjar, -1 om ingen sång hörs, None om det inte gick att avgöra."""
    if not igenkanning.gemini_finns():
        return None
    with tempfile.TemporaryDirectory() as mapp:
        klipp = Path(mapp) / "borjan.ogg"
        if not await asyncio.to_thread(_klipp, Path(lat["fil"]), klipp):
            log.warning("Kunde inte klippa %s", lat.get("titel"))
            return None
        data = base64.standard_b64encode(klipp.read_bytes()).decode()
    svar = await igenkanning.fraga_gemini(
        [{"type": "audio", "data": data, "mime_type": "audio/ogg"},
         {"type": "text", "text": PROMPT.format(min=LYSSNA_MIN, artist=lat.get("artist", ""))}], SCHEMA)
    if not svar or not isinstance(svar.get("sang_borjar_sek"), int):
        return None
    return svar["sang_borjar_sek"]


def _spara(lat_id: str, block_id: str, sek: int) -> None:
    with bib._las:
        alla = bib._las_json(bib.BIBLIOTEK_FIL, [])
        for l in alla:
            if l["id"] == lat_id and l["block"] == block_id:
                l["sang_borjar"] = sek
        bib._skriv_json(bib.BIBLIOTEK_FIL, alla)


async def kontrollera(lat: dict, flytta: bool = True) -> str:
    """'ok' | 'flyttad' | 'okand'. Sparar resultatet i biblioteket och loggar."""
    sek = await sang_borjar(lat)
    if sek is None:
        resultat = "okand"
    else:
        _spara(lat["id"], lat["block"], sek)
        lang = lang_lat(lat) and (sek < 0 or sek > MAX_MIN * 60)
        resultat = "flyttad" if (lang and flytta) else ("lang" if lang else "ok")
        if lang and flytta:
            bib.ta_bort(lat["id"], lat["block"], orsak="lång inledning")
    rad = {"tid": datetime.now().isoformat(timespec="seconds"), "id": lat["id"], "block": lat["block"],
           "titel": lat.get("titel"), "langd": lat.get("langd"), "sang_borjar": sek, "resultat": resultat}
    with open(LOGG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rad, ensure_ascii=False) + "\n")
    log.info("Inledning %s: sång vid %s s -> %s", lat.get("titel"), sek, resultat)
    return resultat


def kontrollera_nu(lat: dict) -> str:
    """Från vanlig kod (t.ex. påfyllningen i en tråd): egen händelseloop och ny HTTP-klient."""
    igenkanning._gemini_http = None          # klienten hör till en annan loop
    try:
        return asyncio.run(kontrollera(lat))
    finally:
        igenkanning._gemini_http = None


def kontrollera_nagra(antal: int = 12, paus: float = 20) -> int:
    """Natten: kontrollerar några låtar som inte är kontrollerade (gratiskvoten: paus mellan). Ger antal."""
    import time
    gjorda = 0
    for lat in [l for l in bib.latar() if behover_kontroll(l)][:antal]:
        kontrollera_nu(lat)
        gjorda += 1
        time.sleep(paus)
    return gjorda


async def kontrollera_alla(flytta: bool = True, paus: float = 20) -> dict:
    ut: dict[str, int] = {}
    for lat in [l for l in bib.latar() if behover_kontroll(l)]:
        r = await kontrollera(lat, flytta)
        ut[r] = ut.get(r, 0) + 1
        print(f"{r:8} {round(lat['langd'] / 60):3} min  {lat['titel'][:70]}", flush=True)
        await asyncio.sleep(paus)            # gratiskvoten: inte för många minuter ljud på en gång
    return ut


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    print(asyncio.run(kontrollera_alla(flytta="--visa" not in sys.argv)))
