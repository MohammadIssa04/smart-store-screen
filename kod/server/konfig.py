"""Inställningar. Hemligheter (token, ID:n) läses från miljön, som systemd
fyller i från butiksbot.env (rättigheter 600). Inget hemligt i koden."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

HEM = Path(__file__).resolve().parent

SKYLT_DIR = Path(os.environ.get("SKYLT_DIR", "/home/minbutik/skylt"))
ERBJUDANDEN_DIR = SKYLT_DIR / "erbjudanden"
ARKIV_DIR = ERBJUDANDEN_DIR / "arkiv"

DATA_DIR = HEM / "data"
UTKAST_DIR = DATA_DIR / "utkast"
CACHE_DIR = DATA_DIR / "cache"
LAGER_FIL = DATA_DIR / "erbjudanden.json"

# Skylten är tänd 10-21. Erbjudanden gäller till stängning sista dagen.
STANGNING_TIMME = int(os.environ.get("STANGNING_TIMME", "21"))
STANDARD_DAGAR = 7
MAX_DAGAR = 60


# ---------- tunga jobb får aldrig störa skylten ----------
# Rendering och friläggning körs med lägsta CPU- och diskprioritet och bara på kärna 1-3,
# så att kärna 0 alltid är fri för skyltens video och musiken. Det tar lite längre tid.
RENDER_TRADAR = int(os.environ.get("RENDER_TRADAR", "3"))     # hemservern: fler
RENDER_KARNOR = os.environ.get("RENDER_KARNOR", "1-3")       # kärna 0 är skyltens och musikens


# Musikspelarens styrsocket (API:t pratar med spelaren här). Ligger i konfig så att API:t inte behöver
# läsa in hela musikspelaren – en halvt utbytt spelare.py fick API:t att krascha 20 gånger 2026-11-13.
STYR_SOCK = os.environ.get("BUTIKSMUSIK_STYR_SOCK", "/tmp/butiksmusik-styr.sock")


def lag_prioritet_prefix() -> list[str]:
    """Kommandoprefix för tunga underprocesser (ffmpeg): nice 19, ionice idle, kärna 1-3."""
    ut = ["nice", "-n", "19"]
    if shutil.which("ionice"):
        ut += ["ionice", "-c", "3"]
    if shutil.which("taskset") and (os.cpu_count() or 1) >= 4:
        ut += ["taskset", "-c", RENDER_KARNOR]
    return ut


def lag_prioritet() -> None:
    """Sätter lägsta prioritet och kärna 1-3 för den anropande tråden. Trådar och processer som
    startas därefter ärver det (på Linux gäller nice/affinitet per tråd), så anropa tidigt:
    först i bot.main() och i tråden som gör friläggningen."""
    try:
        os.nice(19 - os.nice(0))
    except (AttributeError, OSError):
        pass
    if hasattr(os, "sched_setaffinity") and (os.cpu_count() or 1) >= 4:
        try:
            a, b = (int(x) for x in RENDER_KARNOR.split("-"))
            os.sched_setaffinity(0, set(range(a, b + 1)))
        except OSError:
            pass
    if shutil.which("ionice"):
        tid = getattr(__import__("threading"), "get_native_id", os.getpid)()
        subprocess.run(["ionice", "-c", "3", "-p", str(tid)], capture_output=True, timeout=5)


def token() -> str:
    return os.environ.get("TELEGRAM_TOKEN", "").strip()


def tillatna_id() -> set[int]:
    raw = os.environ.get("ALLOWED_IDS", "")
    ids = set()
    for del_ in raw.replace(";", ",").replace(" ", ",").split(","):
        del_ = del_.strip()
        if del_.lstrip("-").isdigit():
            ids.add(int(del_))
    return ids
