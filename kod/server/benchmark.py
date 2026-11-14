"""Benchmark och hälsokontroll av hela Min Butik-systemet på Pi:n. Ändrar ingenting i butikens data
(en tillfällig testtelefon loggas in och spärras efteråt; rendering görs i en tillfällig mapp).
    set -a; . ./butiksbot.env; set +a; .venv/bin/python benchmark.py [--snabb]
--snabb hoppar över rendering och bildsökning."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

import enheter
import konfig

SNABB = "--snabb" in sys.argv
RAPPORT: dict = {}
BAS = "http://127.0.0.1:8484"


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120).stdout.strip()


def rubrik(t):
    print(f"\n== {t}", flush=True)


def rad(namn, varde, varning=False):
    print(f"{'!!' if varning else '  '} {namn:42} {varde}", flush=True)
    RAPPORT[namn] = varde


# ---------- system ----------
def system():
    rubrik("System")
    rad("temperatur", sh("vcgencmd measure_temp"))
    t = sh("vcgencmd get_throttled")
    rad("strypning sedan start", t, varning=t != "throttled=0x0")
    rad("last (1/5/15 min)", open("/proc/loadavg").read().split()[:3])
    m = sh("free -m | awk '/Mem/{print $3\" MB använt av \"$2}'")
    rad("minne", m)
    df = shutil.disk_usage(Path.home())
    ledigt = df.free / 1e9
    rad("disk ledigt", f"{ledigt:.1f} GB av {df.total / 1e9:.1f} GB", varning=ledigt < 5)
    for namn, p in [("utkast/", konfig.UTKAST_DIR), ("cache/", konfig.CACHE_DIR), ("bildförråd", konfig.DATA_DIR / "bildforrad"),
                    ("musikbibliotek", konfig.SKYLT_DIR / "musik"), ("skylt (alla)", konfig.SKYLT_DIR),
                    ("journal", Path("/var/log/journal"))]:
        rad(f"storlek {namn}", sh(f"du -sh '{p}' 2>/dev/null | cut -f1"))
    rad("utkast-mappar", len(list(konfig.UTKAST_DIR.glob("*"))) if konfig.UTKAST_DIR.exists() else 0)


# ---------- tjänster och fel ----------
def tjanster():
    rubrik("Tjänster (omstarter = krascher)")
    for s in ["butiksbot", "butiksapi", "butiksmusik"]:
        aktiv = sh(f"systemctl --user is-active {s}")
        omstarter = sh(f"systemctl --user show {s} -p NRestarts --value")
        rad(f"{s}", f"{aktiv}, NRestarts={omstarter}", varning=aktiv != "active" or omstarter not in ("0", ""))
    for s in ["skylt", "x25-vakt"]:
        rad(f"{s}.service", sh(f"systemctl is-active {s}.service"))
    rubrik("Fel i loggarna senaste 24 h")
    for s in ["butiksbot", "butiksapi", "butiksmusik"]:
        logg = sh(f"journalctl _SYSTEMD_USER_UNIT={s}.service --since '-24h' --no-pager -o cat 2>/dev/null")
        rader = logg.splitlines()
        fel = [r for r in rader if r.startswith(("ERROR", "CRITICAL")) or "Traceback" in r]
        kvot = sum("429" in r for r in rader)
        rad(f"{s}: fel / tracebacks", len(fel), varning=len(fel) > 0)
        if s != "butiksmusik":
            rad(f"{s}: Gemini 429 (kvot slut)", kvot)
        for r in fel[-3:]:
            print("      ", r[:140].replace(os.environ.get("GEMINI_API_KEY", "§§"), "AIza…"))


# ---------- API ----------
async def api(c: httpx.AsyncClient, h: dict):
    rubrik("API-svarstider (ms, median / max av 8)")
    vagar = [("GET", "/api/hej", None), ("GET", "/api/annonser", None), ("GET", "/api/musik/status", None),
             ("GET", "/api/musik/block", None), ("GET", "/api/etiketter/lage", None), ("GET", "/api/etiketter/senaste", None),
             ("POST", "/api/etiketter/forhandsvisa", {"namn": "Röda äpplen", "pris": "19,90/kg"})]
    for metod, vag, kropp in vagar:
        tider = []
        for _ in range(8):
            t = time.perf_counter()
            r = await c.request(metod, vag, headers=h, json=kropp)
            tider.append((time.perf_counter() - t) * 1000)
        med = statistics.median(tider)
        rad(f"{metod} {vag}", f"{med:.0f} / {max(tider):.0f} ms  (HTTP {r.status_code})", varning=med > 1000 or r.status_code != 200)


# ---------- skylten ----------
def skylt():
    rubrik("Skylten (mpv, 45 s)")
    import json as j
    import socket

    def q(p):
        try:
            s = socket.socket(socket.AF_UNIX); s.settimeout(2); s.connect("/tmp/mpv.sock")
            s.sendall((j.dumps({"command": ["get_property", p]}) + "\n").encode())
            buf = b""
            while b"\n" not in buf:
                buf += s.recv(4096)
            s.close()
            for r in buf.decode().splitlines():
                d = j.loads(r)
                if "error" in d:
                    return d.get("data")
        except Exception:
            return None
    tot, sek, p0, a = 0, 0, q("path"), q("frame-drop-count") or 0
    t = time.time()
    while time.time() - t < 45:
        time.sleep(1)
        p, b = q("path"), q("frame-drop-count") or 0
        if p != p0:
            p0, a = p, b
            continue
        tot += max(0, b - a); sek += 1; a = b
    rad("tappade bildrutor/s", round(tot / max(1, sek), 2), varning=tot / max(1, sek) > 1)
    rad("skärmuppdateringar/s", round(q("estimated-display-fps") or 0, 1))
    rad("avkodning", f"{q('hwdec-current')} / {q('hwdec-interop')}")
    rad("mpv CPU %", sh("ps -C mpv -o pcpu=,args= | grep -- '--fs' | awk '{print $1}'"))


# ---------- flödet: bildsök, video, publicering ----------
async def flode():
    rubrik("Annonsflödet (riktig rendering i tillfällig mapp)")
    tmp = Path(tempfile.mkdtemp(prefix="bench_"))
    try:
        r = subprocess.run([sys.executable, "testa_bakgrund.py", "potatis 7"], capture_output=True, text=True,
                           timeout=1800, env={**os.environ})
        ut = r.stdout
        for rad_ in ut.splitlines():
            if rad_.startswith(("OK", "FEL")):
                print("  ", rad_[:120])
        RAPPORT["flöde"] = [x for x in ut.splitlines() if x.startswith(("OK", "FEL"))]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def main():
    t0 = time.time()
    system()
    tjanster()
    kod = enheter.ny_kod()
    async with httpx.AsyncClient(base_url=BAS, timeout=60) as c:
        svar = (await c.post("/api/logga-in", json={"kod": kod, "namn": "Benchmark"})).json()
        h = {"Authorization": f"Bearer {svar['nyckel']}"}
        try:
            await api(c, h)
        finally:
            enheter.sparra(svar["enhet"])                 # testtelefonen spärras direkt
    skylt()
    if not SNABB:
        t = time.time()
        await flode()
        rad("hela flödet (sök + video + publicera)", f"{time.time() - t:.0f} s")
    system()
    rad("benchmark tog", f"{time.time() - t0:.0f} s")
    Path("/tmp/benchmark.json").write_text(json.dumps(RAPPORT, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    asyncio.run(main())
