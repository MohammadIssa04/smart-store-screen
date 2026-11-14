"""Testar väderstyrningen hela vägen: påhittat väder -> regler -> .vikter -> skylt-plays spellista.
Kör på Pi:n (behöver bash och tidszonsdata):  .venv/bin/python testa_vader.py [skylt-play-fil]
Använder en tillfällig skyltmapp; rör varken den riktiga skylten eller boten."""
import asyncio
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import vader

SKRIPT = Path(sys.argv[1] if len(sys.argv) > 1 else "skylt-play.vader").resolve()
TMP = Path(tempfile.mkdtemp(prefix="butiksbot_vader_"))
BAS, ERB = TMP / "skylt", TMP / "skylt" / "erbjudanden"
vader.LOGG_FIL = TMP / "vader.jsonl"

VANLIGA = ["oppettider.mp4", "facebook.mp4", "liba-brod.mp4"]
ANNONSER = ["Red Bull", "Kaffe", "Grillkorv", "Chips", "Basmatiris"]


def prognos(dagar: dict, start: datetime) -> list[dict]:
    """Timprognos: {dagindex: (temp, symbol, mm per timme)} för kl 10-21."""
    ut = []
    for i, (temp, symbol, mm) in dagar.items():
        d = (start + timedelta(days=i)).date()
        for h in range(10, 21):
            ut.append({"tid": datetime(d.year, d.month, d.day, h, tzinfo=vader.TZ), "temp": temp,
                       "symbol": symbol, "mm": mm})
    return ut


# Symboler: 1 klart, 3 växlande, 6 mulet, 18 lätt regn, 25 lätt snö
FALL = {
    "Varm sommardag (ons 15 juli, 27 °C, sol)":
        (datetime(2026, 7, 15, 12, tzinfo=vader.TZ), {0: (27, 1, 0), 1: (26, 1, 0)}),
    "Kall vinterdag (ons 20 jan, -7 °C, klart)":
        (datetime(2027, 1, 20, 12, tzinfo=vader.TZ), {0: (-7, 1, 0)}),
    "Regnig höstdag (ons 14 okt, 11 °C, regn hela dagen)":
        (datetime(2026, 10, 14, 12, tzinfo=vader.TZ), {0: (11, 18, 0.8)}),
    "Grillhelg (tors 18 juni 15 °C mulet; lör 24 °C sol, sön 22 °C sol)":
        (datetime(2026, 6, 18, 12, tzinfo=vader.TZ), {0: (15, 6, 0), 1: (16, 6, 0), 2: (24, 1, 0), 3: (22, 2, 0)}),
}


def forbered() -> list[dict]:
    (BAS / "alltid").mkdir(parents=True)
    ERB.mkdir(parents=True)
    for v in VANLIGA:
        (BAS / "alltid" / v).write_bytes(b"x")
    poster = []
    for i, rubrik in enumerate(ANNONSER):
        fil = ERB / f"t209912312100_{rubrik.lower().replace(' ', '-')}_{i}.mp4"
        fil.write_bytes(b"x")
        poster.append({"rubrik": rubrik, "vadertyp": vader.klassa_ord(rubrik),
                       "kanaler": {"skylt": {"fil": str(fil)}}})
    return poster


def spellista() -> list[str]:
    """Kör skylt-plays riktiga funktioner (allt före mpv-delen) kl 12 med den tillfälliga mappen."""
    funktioner = SKRIPT.read_text(encoding="utf-8").split("# ---- mpv")[0]
    bash = (funktioner + '\ndate() { case "$1" in +%H) echo 12;; +%u) echo 3;; *) command date "$@";; esac; }\n'
            "bygg_lista\n")
    ut = subprocess.run(["bash", "-c", bash], env={"SKYLT_BAS": str(BAS), "PATH": "/usr/bin:/bin"},
                        capture_output=True, text=True, check=True).stdout
    return [Path(x).name for x in ut.splitlines() if x]


def visa(rubrik: str, L: vader.Lage, poster: list[dict]) -> None:
    vader.skriv_vikter(poster, L, ERB / ".vikter")
    lista = spellista()
    namn = {Path(p["kanaler"]["skylt"]["fil"]).name: p["rubrik"] for p in poster}
    print(f"\n=== {rubrik}")
    print("Regler:", "; ".join(L.regler))
    print("Vikter:", ", ".join(f"{p['rubrik']} ({p['vadertyp']}) x{L.vikter.get(p['vadertyp'], 1)}" for p in poster))
    print(f"Spellista ({len(lista)} poster):")
    for i, x in enumerate(lista, 1):
        print(f"  {i:2}. {'  ' if x in VANLIGA else '★ '}{namn.get(x, x.replace('.mp4', ''))}")


async def main() -> None:
    poster = forbered()
    (ERB / ".vikter").unlink(missing_ok=True)
    print("=== Utan .vikter (som förut)")
    print("  " + " | ".join(namn.replace(".mp4", "") for namn in spellista()))
    for rubrik, (nu, dagar) in FALL.items():
        visa(rubrik, vader.lage(prognos(dagar, nu), nu), poster)
    if await vader.hamta_prognos():
        visa(f"Riktig prognos just nu ({datetime.now(vader.TZ):%a %d %b %H:%M})",
             vader.lage(vader.las_prognos()), poster)
    print("\nLogg:", vader.LOGG_FIL, f"({len(vader.LOGG_FIL.read_text().splitlines())} rader)")
    shutil.rmtree(BAS)


asyncio.run(main())
