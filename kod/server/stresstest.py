"""Värsta fall: allt tungt samtidigt medan skylten och musiken spelar. Mäter skyltens tappade bildrutor,
temperatur, strypning, API-svarstider och om musiken hackar. Ändrar inget i butikens data (tillfälliga
mappar; en testtelefon loggas in och spärras efteråt).
    set -a; . ./butiksbot.env; set +a; .venv/bin/python stresstest.py

Samtidigt: 2 renderingar (förbi renderlåset, som om två annonser gjordes på en gång), bildförrådet för 2 varor
(sökning, AI-betyg, friläggning), vridning av en skyltvideo, ljudanalys av en lång låt och 4 "telefoner"
som frågar API:t utan paus."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

import enheter
import konfig

PY = sys.executable
TMP = Path(tempfile.mkdtemp(prefix="stress_"))
matning: list[dict] = []
api_tider: list[float] = []
api_fel = 0


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def ipc(sock, data):
    try:
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(2)
        s.connect(sock)
        s.sendall((json.dumps(data) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            buf += s.recv(65536)
        s.close()
        return json.loads(buf.decode().splitlines()[-1])
    except Exception:
        return None


def mpv(p):
    d = ipc("/tmp/mpv.sock", {"command": ["get_property", p]})
    return d.get("data") if d else None


async def mata(stopp: asyncio.Event, fas: str):
    """Var 2:a sekund: skylten, musiken, temperatur, strypning, last."""
    a, p0 = mpv("frame-drop-count") or 0, mpv("path")
    m0 = (ipc(konfig.STYR_SOCK, {"cmd": "status"}) or {}).get("position")
    while not stopp.is_set():
        await asyncio.sleep(2)
        p, b = mpv("path"), mpv("frame-drop-count") or 0
        tapp = 0 if p != p0 else max(0, b - a)
        a, p0 = b, p
        st = ipc(konfig.STYR_SOCK, {"cmd": "status"}) or {}
        m1 = st.get("position")
        musik_ok = (not st.get("spelar")) or (m0 is not None and m1 is not None and m1 != m0)
        m0 = m1
        matning.append({"fas": fas, "tapp": tapp / 2, "fps": mpv("estimated-display-fps") or 0,
                        "temp": float(sh("vcgencmd measure_temp")[5:-2] or 0), "strypt": sh("vcgencmd get_throttled"),
                        "last": float(open("/proc/loadavg").read().split()[0]), "musik_ok": musik_ok,
                        "mhz": int(sh("vcgencmd measure_clock arm").split("=")[-1]) // 1_000_000})


async def hamra_api(c, h, stopp):
    global api_fel
    vagar = ["/api/annonser", "/api/musik/status", "/api/etiketter/senaste", "/api/hej"]
    i = 0
    while not stopp.is_set():
        t = time.perf_counter()
        try:
            r = await c.get(vagar[i % len(vagar)], headers=h)
            if r.status_code != 200:
                api_fel += 1
        except Exception:
            api_fel += 1
        api_tider.append((time.perf_counter() - t) * 1000)
        i += 1
        await asyncio.sleep(0.2)


def sammanfatta(fas):
    m = [x for x in matning if x["fas"] == fas]
    if not m:
        return
    print(f"\n== {fas} ({len(m) * 2} s)")
    print(f"   skylten: tappade bildrutor/s snitt {statistics.mean(x['tapp'] for x in m):.2f}, "
          f"max {max(x['tapp'] for x in m):.1f};  skärm-fps snitt {statistics.mean(x['fps'] for x in m):.1f}, "
          f"lägst {min(x['fps'] for x in m):.1f}")
    print(f"   temperatur: {min(x['temp'] for x in m):.0f}–{max(x['temp'] for x in m):.0f} °C;  "
          f"processor {min(x['mhz'] for x in m)}–{max(x['mhz'] for x in m)} MHz;  last max {max(x['last'] for x in m):.1f}")
    print(f"   strypning: {sorted(set(x['strypt'] for x in m))}")
    print(f"   musiken: {sum(1 for x in m if not x['musik_ok'])} av {len(m)} mätningar stod still")


async def main():
    stopp = asyncio.Event()
    print("Vila 30 s …", flush=True)
    t = asyncio.create_task(mata(stopp, "vila"))
    await asyncio.sleep(30)
    stopp.set(); await t

    # Tunga jobb, alla med samma prioritet som i drift (lag_prioritet: nice 19, kärna 1-3)
    foto = sorted((konfig.DATA_DIR / "bildforrad" / "potatis").glob("2*_0"))[0]
    lat = max((p for p in (konfig.SKYLT_DIR / "musik" / "bibliotek" / "umm").glob("*.m4a")), key=lambda p: p.stat().st_size)
    skyltfil = sorted((Path.home() / "skylt" / "arkiv-portratt" / "erbjudanden").glob("*.mp4"))[0]
    shutil.copy(skyltfil, TMP / "vrid.mp4.part")
    pre = " ".join(konfig.lag_prioritet_prefix())
    jobb = {
        "rendering 1": f"{PY} demo_video.py {TMP}/r1.mp4 'potatis 7' {foto}",
        "rendering 2": f"{PY} demo_video.py {TMP}/r2.mp4 'potatis 2 för 10' {foto}",
        "bildförråd": f"{PY} -c \"import asyncio, bildsok, konfig; konfig.lag_prioritet(); "
                      f"bildsok.FORRAD = __import__('pathlib').Path('{TMP}/forrad'); "
                      f"import forbered_bilder as f; f.VANLIGA=['Morötter','Citroner']; f.varor=lambda: f.VANLIGA; "
                      f"print(asyncio.run(f.forbered(2)))\"",
        "vridning": f"{PY} -c \"import skyltvrid, pathlib; skyltvrid.vrid(pathlib.Path('{TMP}/vrid.mp4.part'), arkivera=False)\"",
        "ljudanalys": f"{pre} ffmpeg -v error -y -t 2400 -i '{lat}' -vn -ac 1 -ar 16000 -c:a libopus -b:a 12k -threads 1 {TMP}/ljud.ogg",
    }
    kod = enheter.ny_kod()
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8484", timeout=30) as c:
        inl = (await c.post("/api/logga-in", json={"kod": kod, "namn": "Stresstest"})).json()
        h = {"Authorization": f"Bearer {inl['nyckel']}"}
        try:
            print("Värsta fall: " + ", ".join(jobb) + " + 4 telefoner mot API:t …", flush=True)
            stopp = asyncio.Event()
            matt = asyncio.create_task(mata(stopp, "värsta fall"))
            telefoner = [asyncio.create_task(hamra_api(c, h, stopp)) for _ in range(4)]
            start = time.time()
            processer = {n: await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE,
                                                                   stderr=asyncio.subprocess.STDOUT, env=os.environ)
                         for n, cmd in jobb.items()}
            tider = {}
            for n, p in processer.items():
                await p.communicate()
                tider[n] = (time.time() - start, p.returncode)
            stopp.set()
            await asyncio.gather(matt, *telefoner)
        finally:
            enheter.sparra(inl["enhet"])
    print("\nEfter värsta fall: svalnar 60 s …", flush=True)
    stopp = asyncio.Event()
    t = asyncio.create_task(mata(stopp, "efteråt"))
    await asyncio.sleep(60)
    stopp.set(); await t

    for fas in ("vila", "värsta fall", "efteråt"):
        sammanfatta(fas)
    print("\n== Jobben (klara efter, utgångskod)")
    for n, (s, kod_) in tider.items():
        print(f"   {n:12} {s:5.0f} s  {'OK' if kod_ == 0 else 'FEL ' + str(kod_)}")
    srt = sorted(api_tider)
    print(f"\n== API under värsta fall: {len(srt)} anrop, median {statistics.median(srt):.0f} ms, "
          f"95 % {srt[int(len(srt) * 0.95)]:.0f} ms, max {srt[-1]:.0f} ms, fel {api_fel}")
    shutil.rmtree(TMP, ignore_errors=True)


asyncio.run(main())
