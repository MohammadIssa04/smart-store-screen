"""Gör skyltens fasta videor (~/skylt/alltid/: Facebook, öppettider) till vanliga annonser som visas tills
vidare. Då syns de i appen och kan styras där: hur ofta, väder, visa extra, ta bort (arkiv).

Filen flyttas till erbjudanden/ som t209912312100_<namn>_<id>.mp4 (tills vidare). Appen visar den stående
originalen ur ~/skylt/arkiv-portratt/alltid/ om den finns. Raderar inget.
    .venv/bin/python fasta_videor.py [--visa]"""
from __future__ import annotations

import os
import secrets
import sys
from datetime import datetime
from pathlib import Path

import konfig
import tjanst
from kanaler.skylt import _ledigt_namn, _slug

NAMN = {"facebook": "Min Butik på Facebook", "oppettider": "Öppettider"}


def rubrik(fil: Path) -> str:
    n = fil.stem.lower()
    for nyckel, text in NAMN.items():
        if nyckel in n:
            return text
    return fil.stem.replace("_", " ").replace("60fps", "").strip().capitalize()


def flytta(visa: bool = False) -> list[str]:
    alltid = konfig.SKYLT_DIR / "alltid"
    gjort = []
    for fil in sorted(alltid.glob("*.mp4")):
        pid = secrets.token_hex(3)
        namn = rubrik(fil)
        mal = _ledigt_namn(konfig.ERBJUDANDEN_DIR / f"t{tjanst.TILLS_VIDARE:%Y%m%d%H%M}_{_slug(namn)}_{pid}.mp4")
        original = konfig.SKYLT_DIR / "arkiv-portratt" / "alltid" / fil.name
        gjort.append(f"{fil.name} -> {mal.name} ({namn})")
        if visa:
            continue
        nu = datetime.now().isoformat(timespec="seconds")
        post = {"id": pid, "typ": "fast", "text": "", "rubrik": namn, "pris": "", "dagar": 0,
                "utgar": tjanst.TILLS_VIDARE.isoformat(timespec="minutes"), "skapad": nu,
                "video": str(original if original.is_file() else mal), "bilder": [],
                "kanaler": {"skylt": {"fil": str(mal)}}, "status": "aktiv", "overgang": None,
                "vadertyp": "neutral", "publicerad": nu, "av": "flyttad från alltid/"}
        os.replace(fil, mal)                       # samma disk: flyttas i ett steg, skylten ser den direkt
        tjanst.lager.spara(post)
    if gjort and not visa:
        tjanst.uppdatera_vikter()
    return gjort


if __name__ == "__main__":
    for r in flytta("--visa" in sys.argv):
        print(r)
