"""Skyltens videor sparas redan vridna (liggande 1920x1080), så att skärmkretsen kan visa dem direkt
("drmprime-overlay") utan att grafikkretsen ritar varje bild: exakt 60 bilder/s i stället för 55–58.
Skärmkretsen kan inte vrida 90°, därför vrids filerna här en gång.

Vridningen följer ~/skylt/.rotera (grader medurs, som mpv:s video-rotate; standard 270).
Originalen flyttas till ~/skylt/arkiv-portratt/ (raderas aldrig). Filnamnen behålls, så spellistan,
vädervikterna (.vikter) och utgångstiden (t<ÅÅÅÅMMDDTTMM>_) påverkas inte.

    .venv/bin/python skyltvrid.py          # vrid alla stående videor som skylten visar
    .venv/bin/python skyltvrid.py --visa   # bara lista
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import konfig

log = logging.getLogger("butiksbot.skyltvrid")
ARKIV = konfig.SKYLT_DIR / "arkiv-portratt"
FILTYPER = re.compile(r"\.(mp4|mov|mkv)$", re.I)
TRANSPOSE = {90: "transpose=1", 270: "transpose=2", 180: "transpose=1,transpose=1"}
_las = threading.Lock()


def rotation() -> int:
    try:
        return int((konfig.SKYLT_DIR / ".rotera").read_text().strip()) % 360
    except (OSError, ValueError):
        return 270


def storlek(fil: Path) -> tuple[int, int] | None:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height:stream_side_data=rotation", "-of", "json", str(fil)],
                           capture_output=True, text=True, timeout=20)
        s = json.loads(r.stdout)["streams"][0]
        return int(s["width"]), int(s["height"])
    except Exception:
        return None


def ar_staende(fil: Path) -> bool:
    s = storlek(fil)
    return bool(s and s[1] > s[0])


def skyltfiler() -> list[Path]:
    """Alla videor som skylt-play kan visa: ~/skylt/*, alltid/, veckodagar, timmappar, erbjudanden/."""
    bas = konfig.SKYLT_DIR
    ut = [f for f in bas.iterdir() if f.is_file()]
    for d in bas.iterdir():
        if d.is_dir() and not d.name.startswith(("arkiv", "backup", "musik", "ljud")):
            ut += [f for f in d.iterdir() if f.is_file()]
    return sorted(f for f in ut if FILTYPER.search(f.name))


def vrid(fil: Path, grader: int | None = None, arkivera: bool = True) -> bool:
    """Gör om en stående video till liggande (vriden), på plats. Originalet arkiveras. True om vriden."""
    grader = rotation() if grader is None else grader
    if grader not in TRANSPOSE or not ar_staende(fil):
        return False
    with _las:
        tmp = fil.with_name(fil.name + ".vrid.part")       # inte .mp4: skylt-play får aldrig se den
        cmd = [*konfig.lag_prioritet_prefix(), "ffmpeg", "-v", "error", "-y", "-i", str(fil),
               "-vf", TRANSPOSE[grader], "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
               "-profile:v", "high", "-level", "4.2", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
               "-threads", str(konfig.RENDER_TRADAR), "-f", "mp4", str(tmp)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if r.returncode != 0 or not tmp.is_file() or ar_staende(tmp):
            log.error("Kunde inte vrida %s: %s", fil.name, r.stderr[-300:])
            if tmp.exists():
                tmp.unlink()                   # bara vår egen halvfärdiga tempfil
            return False
        if arkivera:
            rel = fil.relative_to(konfig.SKYLT_DIR) if fil.is_relative_to(konfig.SKYLT_DIR) else Path(fil.name)
            mal = ARKIV / rel
            mal.parent.mkdir(parents=True, exist_ok=True)
            if mal.exists():
                mal = mal.with_name(f"{mal.stem}-{os.getpid()}{mal.suffix}")
            shutil.copy2(fil, mal)             # originalet sparas först ...
        os.replace(tmp, fil)                   # ... sedan byts filen ut i ett steg (samma namn)
        log.info("Vriden %d°: %s", grader, fil.name)
        return True


def liggande_kopia(video: Path) -> Path:
    return video.with_name(video.stem + ".liggande.mp4")


def forvrid(video: Path) -> None:
    """Gör skyltens liggande kopia av en ny video i förväg (bredvid den i utkast/). Fel här stoppar inget:
    publiceringen vrider då själv."""
    try:
        mal = liggande_kopia(video)
        if mal.exists() or not ar_staende(video):
            return
        tmp = mal.with_name(mal.name + ".tmp.part")
        shutil.copy2(video, tmp)
        if vrid(tmp, arkivera=False):
            os.replace(tmp, mal)
            log.info("Liggande kopia klar i förväg: %s", mal.name)
        elif tmp.exists():
            tmp.unlink()                       # vår egen tempfil
    except Exception:
        log.exception("Kunde inte vrida i förväg")


def vrid_alla(visa: bool = False) -> list[str]:
    ut = []
    for f in skyltfiler():
        if ar_staende(f):
            ut.append(f.name)
            if not visa:
                vrid(f)
    return ut


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print(json.dumps(vrid_alla("--visa" in sys.argv), ensure_ascii=False, indent=1))
