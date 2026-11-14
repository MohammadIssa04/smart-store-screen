"""Inloggning för appen: engångskoder och en personlig nyckel per telefon.

Flöde: ägaren skriver /kod till Telegram-boten -> får en 6-siffrig kod (gäller 10 min, en gång)
-> skriver in den i appen -> telefonen får en egen nyckel. Ägaren ser telefonerna med /telefoner
och kan spärra dem en och en. Används av både boten och API:t (filerna i data/app delas).

Bara kodens och nyckelns SHA-256 sparas, aldrig klartext. Inga nycklar loggas.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path

import konfig

MAPP = konfig.DATA_DIR / "app"
ENHETER = MAPP / "enheter.json"     # telefoner: id, namn, nyckelns hash, spärrad
KODER = MAPP / "koder.json"         # den aktiva engångskoden (hash) och felräknare
SEDD = MAPP / "sedd.json"           # när och varifrån varje telefon senast hördes av
LOGG = MAPP / "inloggning.jsonl"    # alla inloggningsförsök

KOD_GILTIG = 10 * 60                # sekunder
MAX_FEL_IP = 5                      # felaktiga koder från samma adress ...
SPARR_IP = 15 * 60                  # ... ger spärr så här länge
MAX_FEL_TOTALT = 20                 # felaktiga koder totalt -> koden ogiltig, ny /kod krävs

_las = threading.Lock()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _las_json(fil: Path, standard):
    try:
        return json.loads(fil.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return standard


def _skriv_json(fil: Path, data) -> None:
    fil.parent.mkdir(parents=True, exist_ok=True)
    tmp = fil.with_name(fil.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, fil)


def _logga(handelse: str, **detaljer) -> None:
    MAPP.mkdir(parents=True, exist_ok=True)
    rad = {"tid": datetime.now().isoformat(timespec="seconds"), "handelse": handelse, **detaljer}
    with open(LOGG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rad, ensure_ascii=False) + "\n")


# ---------- engångskod ----------

def ny_kod() -> str:
    """Ny 6-siffrig kod som ersätter alla tidigare. Häver också totalspärren."""
    kod = f"{secrets.randbelow(10 ** 6):06d}"
    with _las:
        _skriv_json(KODER, {"hash": _hash(kod), "giltig_till": time.time() + KOD_GILTIG,
                            "anvand": False, "fel": 0})
    _logga("ny_kod")
    return kod


class InloggningsFel(Exception):
    """meddelande: kort svensk text som appen kan visa."""


class Inloggning:
    """Håller räkningen på felaktiga försök per adress (i API-processen)."""

    def __init__(self) -> None:
        self.fel: dict[str, list[float]] = {}

    def sparrad_till(self, ip: str) -> float:
        nu = time.time()
        forsok = [t for t in self.fel.get(ip, []) if nu - t < SPARR_IP]
        self.fel[ip] = forsok
        return forsok[-1] + SPARR_IP if len(forsok) >= MAX_FEL_IP else 0.0

    def logga_in(self, kod: str, namn: str, ip: str) -> tuple[str, dict]:
        """(nyckel, enhet) eller InloggningsFel."""
        if self.sparrad_till(ip):
            _logga("sparrad_ip", ip=ip)
            raise InloggningsFel("För många fel. Vänta en kvart och försök igen.")
        with _las:
            k = _las_json(KODER, {})
            giltig = (k.get("hash") and not k.get("anvand") and time.time() < k.get("giltig_till", 0)
                      and k.get("fel", 0) < MAX_FEL_TOTALT)
            if not giltig or not hmac.compare_digest(_hash((kod or "").strip()), k["hash"]):
                if k.get("hash"):
                    k["fel"] = k.get("fel", 0) + 1
                    _skriv_json(KODER, k)
                self.fel.setdefault(ip, []).append(time.time())
                _logga("fel_kod", ip=ip, namn=namn[:40], totalt=k.get("fel", 0))
                raise InloggningsFel("Fel kod, eller så har koden gått ut. Be om en ny kod.")
            k["anvand"] = True
            _skriv_json(KODER, k)
            nyckel = secrets.token_urlsafe(32)
            enhet = {"id": secrets.token_hex(3), "namn": (namn or "Telefon").strip()[:40],
                     "nyckel": _hash(nyckel), "skapad": datetime.now().isoformat(timespec="seconds"),
                     "ip": ip, "sparrad": False}
            alla = _las_json(ENHETER, [])
            alla.append(enhet)
            _skriv_json(ENHETER, alla)
        _logga("inloggad", ip=ip, enhet=enhet["id"], namn=enhet["namn"])
        return nyckel, {k: v for k, v in enhet.items() if k != "nyckel"}


# ---------- nycklar och telefoner ----------

_cache: dict = {"mtime": None, "enheter": []}


def kontrollera(nyckel: str) -> dict | None:
    """Telefonen som nyckeln tillhör, eller None (okänd eller spärrad)."""
    if not nyckel:
        return None
    try:
        mtime = ENHETER.stat().st_mtime
    except OSError:
        return None
    if mtime != _cache["mtime"]:
        _cache.update(mtime=mtime, enheter=_las_json(ENHETER, []))
    h = _hash(nyckel)
    for e in _cache["enheter"]:
        if hmac.compare_digest(e.get("nyckel", ""), h):
            return None if e.get("sparrad") else e
    return None


_senast_skrivet: dict[str, float] = {}


def sedd(enhet_id: str, ip: str, via: str) -> None:
    """Senast sedd per telefon (högst en skrivning per minut och telefon)."""
    if time.time() - _senast_skrivet.get(enhet_id, 0) < 60:
        return
    _senast_skrivet[enhet_id] = time.time()
    with _las:
        s = _las_json(SEDD, {})
        s[enhet_id] = {"tid": datetime.now().isoformat(timespec="seconds"), "ip": ip, "via": via}
        _skriv_json(SEDD, s)


def lista() -> list[dict]:
    s = _las_json(SEDD, {})
    return [{**{k: v for k, v in e.items() if k != "nyckel"}, "sedd": s.get(e["id"])}
            for e in _las_json(ENHETER, [])]


def sparra(enhet_id: str, sparrad: bool = True) -> dict | None:
    with _las:
        alla = _las_json(ENHETER, [])
        for e in alla:
            if e["id"] == enhet_id:
                e["sparrad"] = sparrad
                _skriv_json(ENHETER, alla)
                _logga("sparrad" if sparrad else "oppnad", enhet=enhet_id, namn=e.get("namn"))
                return e
    return None
