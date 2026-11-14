"""Nattlig säkerhetskopia av det som är svårt att göra om: inställningar, annonser (lagret, inte videorna),
musikens metadata (bibliotek, spelordning, startpunkter, favoriter, blocken), produktminnet och skyltens
egna inställningar. Stora mediefiler (musik, videor) och tillfälliga mappar tas inte med: de finns redan
som original, och kopiorna skulle fylla disken.

Aldrig med: butiksbot.env (nycklar och tokens). Den säkerhetskopieras för hand av ägaren.

Kopian: ~/backup/butiksbot/butiksbot-ÅÅÅÅMMDD-TTMM.tar.gz (rättigheter 600). Inget raderas: gamla kopior
ligger kvar (de är små). Boten kör den kl 03:30.
    .venv/bin/python backup.py            # gör en kopia nu
    .venv/bin/python backup.py --visa     # visar vad som skulle tas med och hur stort det är

Återställa (packa aldrig upp direkt över de riktiga filerna):
    mkdir /tmp/aterstall && tar -xzf ~/backup/butiksbot/butiksbot-<datum>.tar.gz -C /tmp/aterstall
    # jämför och kopiera tillbaka det som behövs, t.ex. /tmp/aterstall/butiksbot/data/erbjudanden.json
"""
from __future__ import annotations

import logging
import os
import re
import sys
import tarfile
from datetime import datetime
from pathlib import Path

import konfig

log = logging.getLogger("butiksbot.backup")
HEM = Path.home()
MAL = HEM / "backup" / "butiksbot"
# Mappar och filer som tas med (relativt hemkatalogen). Saknas något hoppas det över.
MED = [konfig.DATA_DIR, HEM / "skylt" / ".rotera", HEM / "skylt" / "erbjudanden" / ".vikter",
       HEM / ".config" / "mpv", HEM / ".config" / "wireplumber", HEM / ".config" / "systemd" / "user"]
# Stora eller tillfälliga saker som inte behövs (eller finns kvar som original någon annanstans).
UTAN_MAPPAR = {"utkast", "bildforrad", "cache", "test", "tmp", "__pycache__"}
UTAN_FILER = re.compile(r"\.(mp4|mov|mkv|webm|mp3|m4a|opus|ogg|wav|flac|part|las|lock|env|apk)$|^butiksbot\.env$", re.I)
MAX_FIL = 20 * 1024 * 1024          # enstaka filer över 20 MB tas inte med


def filer() -> list[Path]:
    ut = []
    for bas in MED:
        if bas.is_file():
            ut.append(bas)
        elif bas.is_dir():
            for rot, mappar, namn in os.walk(bas):
                mappar[:] = [m for m in mappar if m not in UTAN_MAPPAR]
                for n in namn:
                    f = Path(rot) / n
                    try:
                        if not UTAN_FILER.search(n) and f.is_file() and f.stat().st_size <= MAX_FIL:
                            ut.append(f)
                    except OSError:
                        pass
    return ut


def gor(visa: bool = False) -> Path | None:
    lista = filer()
    storlek = sum(f.stat().st_size for f in lista)
    if visa:
        print(f"{len(lista)} filer, {storlek / 1e6:.1f} MB före komprimering")
        return None
    MAL.mkdir(parents=True, exist_ok=True)
    os.chmod(MAL, 0o700)
    ut = MAL / f"butiksbot-{datetime.now():%Y%m%d-%H%M}.tar.gz"
    tmp = ut.with_name(ut.name + ".part")
    gammal_mask = os.umask(0o077)               # kopian ska bara kunna läsas av minbutik
    try:
        with tarfile.open(tmp, "w:gz") as tar:
            for f in lista:
                try:
                    tar.add(f, arcname=str(f.relative_to(HEM)) if f.is_relative_to(HEM) else str(f).lstrip("/"))
                except OSError as e:            # en fil som byts just nu: hoppa över den, inte hela kopian
                    log.warning("Hoppade över %s: %s", f.name, e)
        os.replace(tmp, ut)
    finally:
        os.umask(gammal_mask)
    log.info("Säkerhetskopia klar: %s (%d filer, %.1f MB)", ut.name, len(lista), ut.stat().st_size / 1e6)
    return ut


def senaste() -> Path | None:
    kopior = sorted(MAL.glob("butiksbot-*.tar.gz")) if MAL.is_dir() else []
    return kopior[-1] if kopior else None


if __name__ == "__main__":
    logging.basicConfig(format="%(levelname)s %(name)s: %(message)s", level=logging.INFO)
    r = gor("--visa" in sys.argv)
    if r:
        print(r)
