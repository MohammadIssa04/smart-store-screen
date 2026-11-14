"""Räknar ut hur länge och hur ofta varje annons syns på skylten, på samma sätt som skylt-play bygger
sin spellista: vanliga videor (alltid/, veckodagens mapp, timmesmappar som 12-18/) varvas med
erbjudandena: vanlig, erbjudande, vanlig, erbjudande ... den kortaste listan går runt.
Med väderversionen (skylt-play.vader) får ett erbjudande med vikt 2 dubbelt så många platser."""
from __future__ import annotations

import re
import subprocess
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import konfig

FILTYPER = re.compile(r"\.(jpg|jpeg|png|webp|mp4|mov|mkv)$", re.I)
BILD = re.compile(r"\.(jpg|jpeg|png|webp)$", re.I)
DAGAR = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"]
INSTALLERAD = Path("/usr/local/bin/skylt-play")
OPPEN = (10, 21)


def vanliga(timme: int, nu: datetime) -> list[Path]:
    bas = konfig.SKYLT_DIR
    filer = [f for f in bas.iterdir() if f.is_file()]
    for d in bas.iterdir():
        if not d.is_dir():
            continue
        m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", d.name)
        if d.name in ("alltid", DAGAR[nu.weekday()]) or (m and int(m[1]) <= timme < int(m[2])):
            filer += [f for f in d.iterdir() if f.is_file()]
    return sorted(f for f in filer if FILTYPER.search(f.name))


@lru_cache(maxsize=512)
def _langd(fil: str, mtime: float) -> float:
    if BILD.search(fil):
        return 10.0                                   # mpv --image-display-duration=10
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", fil],
                           capture_output=True, text=True, timeout=10)
        return float(r.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired, OSError):
        return 9.0


def langd(f: Path) -> float:
    try:
        return _langd(str(f), f.stat().st_mtime)
    except OSError:
        return 9.0


def viktat() -> bool:
    try:
        return ".vikter" in INSTALLERAD.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def vikter() -> dict[str, int]:
    ut = {}
    try:
        for rad in (konfig.ERBJUDANDEN_DIR / ".vikter").read_text(encoding="utf-8").splitlines():
            namn, _, v = rad.partition("\t")
            if v.strip() in ("1", "2", "3"):
                ut[namn.strip()] = int(v)
    except OSError:
        pass
    return ut


def per_timme_med_vikt(fil: str, nu: datetime | None = None) -> dict[int, int]:
    """{1: n, 2: n, 3: n}: ungefär hur många gånger i timmen annonsen visas med vikt 1, 2 eller 3."""
    ut = {}
    for w in (1, 2, 3):
        ut[w] = visning(nu=nu, andra_vikter={fil: w}).get(fil, {}).get("per_timme", 0)
    return ut


def aktiva_erbjudanden(nu: datetime) -> list[Path]:
    """Som skylt-play: filer i erbjudanden/, utom de vars t<ÅÅÅÅMMDDTTMM>_ har passerat."""
    d = konfig.ERBJUDANDEN_DIR
    if not d.is_dir():
        return []
    ut = []
    for f in sorted(d.iterdir()):
        m = re.match(r"t(\d{12})_", f.name)
        if f.is_file() and FILTYPER.search(f.name) and not (m and m[1] <= nu.strftime("%Y%m%d%H%M")):
            ut.append(f)
    return ut


def visning(annonsfiler: list[Path] | None = None, nu: datetime | None = None,
            andra_vikter: dict[str, int] | None = None) -> dict[str, dict]:
    """{filnamn: {sek, per_timme, sek_per_timme, sek_per_dag, vikt}} för erbjudandena i annonsfiler.
    Utanför öppettiderna räknas som kl 12."""
    nu = nu or datetime.now()
    timme = nu.hour if OPPEN[0] <= nu.hour < OPPEN[1] else 12
    V = vanliga(timme, nu)
    E = [f for f in (annonsfiler if annonsfiler is not None else aktiva_erbjudanden(nu)) if f.is_file()]
    if not E:
        return {}
    w = vikter() if viktat() else {}
    w = {**w, **(andra_vikter or {})}
    vikt = {f.name: w.get(f.name, 1) for f in E}
    platser = sum(vikt.values())
    k = max(len(V), platser)
    varv = sum(langd(V[i % len(V)]) for i in range(k)) if V else 0.0
    varv += sum(langd(f) * vikt[f.name] * k / platser for f in E)
    ut = {}
    for f in E:
        ggr_varv = k * vikt[f.name] / platser
        per_timme = 3600 / varv * ggr_varv if varv else 0
        sek = langd(f)
        ut[f.name] = {"sek": round(sek), "per_timme": round(per_timme), "sek_per_timme": round(per_timme * sek),
                      "sek_per_dag": round(per_timme * sek * (OPPEN[1] - OPPEN[0])), "vikt": vikt[f.name],
                      "andel": round(100 * ggr_varv * sek / varv) if varv else 0}
    return ut
