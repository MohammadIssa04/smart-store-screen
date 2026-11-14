"""Hittar och hämtar låtar med yt-dlp (samma verktyg som den gamla musiksidan).

Påfyllning: för varje block söks artisterna; bara enskilda låtar av rätt artist tas med
(inga timslånga mixar, "best of", kovers eller karaoke), dubbletter hoppas över. Körs med lägsta
prioritet på kärna 1-3 så att skylten och musiken aldrig störs. Varje hämtning loggas.
"""
from __future__ import annotations

import json
import logging
import random
import re
import subprocess
from datetime import datetime
from pathlib import Path

import konfig
from musik import bibliotek as bib
from musik import inledning

log = logging.getLogger("butiksbot.musik")
YTDLP = "/usr/local/bin/yt-dlp"
LOGG = bib.DATA / "hamtning.jsonl"
MIN_SEK = 120
PER_KORNING = 8             # nya låtar per block och påfyllning
NYA_PER_DAG = 2             # varje morgon byts 2 låtar per block: 2 nya in, de 2 mest spelade till arkivet

# Ord som avslöjar mixar, samlingar och annat än en enskild låt (jämförs normaliserat).
UTESLUT = ("best of", "mix", "non stop", "nonstop", "greatest hits", "playlist", "full album", "compilation",
           "top 10", "top 20", "hour", "hours", "live stream", "cover", "karaoke", "كوكتيل", "اجمل اغاني",
           "اجمل مقاطع", "روائع", "ساعه", "ساعات", "دقيقه", "مجموعه", "باقه", "عزف", "كاريوكي", "تجميعه",
           "remix", "ريمكس", "slowed", "reverb", "8d", "shorts", "#")
# Konsertinspelningar har ofta en mycket lång inledning innan sången börjar (se musik/inledning.py).
KONSERT = ("حفلة", "concert", "كونسير", "live")


def _konsert(titel: str, langd: int) -> bool:
    """Lång konsertinspelning (titeln är redan normaliserad)."""
    if langd <= 20 * 60:
        return False
    return any(bib.normalisera(o) in titel for o in KONSERT) or "حفل" in titel.split()


def _kor(argument: list[str], timeout: int) -> str:
    r = subprocess.run([*konfig.lag_prioritet_prefix(), YTDLP, "--no-warnings", *argument],
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout


def sok(fraga: str, antal: int = 10) -> list[dict]:
    """[{id, titel, kanal, langd}] från YouTube-sökning (ingen nedladdning)."""
    try:
        ut = _kor([f"ytsearch{antal}:{fraga}", "--flat-playlist",
                   "--print", "%(id)s\t%(duration)s\t%(channel)s\t%(title)s"], timeout=60)
    except subprocess.TimeoutExpired:
        return []
    traffar = []
    for rad in ut.splitlines():
        delar = rad.split("\t")
        if len(delar) == 4 and re.fullmatch(r"[A-Za-z0-9_-]{11}", delar[0]):
            langd = int(float(delar[1])) if delar[1] not in ("NA", "None", "") else 0
            traffar.append({"id": delar[0], "langd": langd, "kanal": delar[2].strip(), "titel": delar[3].strip()})
    return traffar


def ar_lat(t: dict, artist: dict, max_min: int) -> bool:
    """En enskild låt av rätt artist, rimlig längd, inte mix/samling/kover."""
    titel, kanal = bib.normalisera(t["titel"]), bib.normalisera(t["kanal"])
    if not (MIN_SEK <= t["langd"] <= max_min * 60):
        return False
    if any(o in titel for o in UTESLUT):
        return False
    if _konsert(titel, t["langd"]):
        return False
    namn = [bib.normalisera(s) for s in artist["sok"]]
    return any(n in titel or n in kanal for n in namn)


def _titel_nyckel(titel: str, artist: dict) -> str:
    # Bara första delen: "Fairuz - Le Beirut | فيروز - لبيروت" och "FAIRUZ - LE BEIRUT" är samma låt.
    t = bib.normalisera(re.split(r"\s[|｜]\s", titel)[0])
    for s in artist["sok"]:
        t = t.replace(bib.normalisera(s), "")
    t = re.sub(r"\((official|lyric|lyrics|audio|video)[^)]*\)|official|lyric video|lyrics|audio|video|hd|hq", "", t)
    return re.sub(r"[^\w]+", "", t)


def hamta(t: dict, block_id: str, artist_namn: str, kalla: str = "auto") -> dict | None:
    """Hämtar en låt till blockets mapp och lägger in den i biblioteket."""
    mapp = bib.FILER / block_id
    mapp.mkdir(parents=True, exist_ok=True)
    try:
        _kor(["-f", "bestaudio[ext=m4a]/bestaudio", "--no-playlist", "-o", str(mapp / "%(id)s.%(ext)s"),
              f"https://www.youtube.com/watch?v={t['id']}"], timeout=900)
    except subprocess.TimeoutExpired:
        log.warning("Hämtningen tog för lång tid: %s", t["titel"])
        return None
    fil = next((f for f in mapp.glob(f"{t['id']}.*") if not f.name.endswith((".part", ".ytdl"))), None)
    if not fil:
        log.warning("Kunde inte hämta %s", t["titel"])
        return None
    lat = {"id": t["id"], "titel": t["titel"], "artist": artist_namn, "block": block_id,
           "langd": t["langd"], "fil": str(fil), "kalla": kalla}
    bib.lagg_till(lat)
    with open(LOGG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"tid": datetime.now().isoformat(timespec="seconds"), **lat}, ensure_ascii=False) + "\n")
    log.info("Ny låt i %s: %s (%s)", block_id, t["titel"], artist_namn)
    return lat


def fyll(block_id: str | None = None, max_nya: int | None = None, byt: bool = False) -> int:
    """Fyller på blocken upp till sitt mål. byt=True (varje morgon): även fulla block får NYA_PER_DAG nya
    låtar och lika många av de mest spelade flyttas till arkivet, så att listan byts lite varje dag.
    Långa nya låtar kontrolleras (inledning) innan de räknas. Ger antal nya låtar."""
    totalt = 0
    for b in bib.block():
        if block_id and b["id"] != block_id:
            continue
        har = bib.latar(b["id"])
        behov = max(0, b.get("mal", 40) - len(har))
        idag = sum(1 for l in har if l.get("kalla") == "auto"
                   and datetime.fromisoformat(l["tillagd"]).date() == datetime.now().date())
        if behov == 0 and byt:
            behov = max(0, NYA_PER_DAG - idag)
        behov = min(behov, max_nya or PER_KORNING)
        if behov == 0:
            continue
        sedda_titlar = {_titel_nyckel(l["titel"], a) for l in bib.latar(b["id"], False) for a in b["artister"]}
        kandidater = []
        for artist in b["artister"]:
            for fraga in artist["sok"][:2]:
                for t in sok(fraga, 25):
                    if bib.finns(t["id"], b["id"]) or not ar_lat(t, artist, b.get("max_min", 15)):
                        continue
                    nyckel = _titel_nyckel(t["titel"], artist)
                    if not nyckel or nyckel in sedda_titlar:
                        continue
                    sedda_titlar.add(nyckel)
                    kandidater.append((t, artist["namn"]))
        # Kortare låtar först (med lite slump så att det inte blir samma ordning varje gång), och högst
        # ungefär lika många från varje artist.
        kandidater.sort(key=lambda k: k[0]["langd"] * random.uniform(0.8, 1.25))
        per_artist: dict[str, int] = {}
        tak = max(1, -(-behov // len(b["artister"])) + 1)
        for t, artist_namn in kandidater:
            if behov <= 0:
                break
            if per_artist.get(artist_namn, 0) >= tak:
                continue
            lat = hamta(t, b["id"], artist_namn)
            if lat and inledning.kontrollera_nu(lat) == "flyttad":      # var börjar sången (alla nya låtar)
                continue
            if lat:
                per_artist[artist_namn] = per_artist.get(artist_namn, 0) + 1
                behov -= 1
                totalt += 1
        while behov > 0 and (tillbaka := bib.ateraktivera(b["id"])):   # inget nytt på nätet: ta tillbaka gamla
            log.info("Tillbaka i %s: %s", b["id"], tillbaka["titel"])
            behov -= 1
            totalt += 1
        if byt:
            for l in bib.rotera_ut(b["id"], NYA_PER_DAG):
                log.info("Byttes ut i %s: %s (spelad %d gånger)", b["id"], l["titel"], l.get("spelad", 0))
    return totalt
