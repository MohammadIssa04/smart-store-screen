"""API:t under last: en rendering + friläggning körs medan 4 "telefoner" frågar API:t. Svarstid per anrop.
    set -a; . ./butiksbot.env; set +a; .venv/bin/python stress_api.py"""
import asyncio
import collections
import statistics
import sys
import tempfile
import time

import httpx

import enheter
import konfig

tider = collections.defaultdict(list)
fel = collections.Counter()


async def telefon(c, h, stopp):
    vagar = ["/api/annonser", "/api/musik/status", "/api/etiketter/lage", "/api/etiketter/senaste", "/api/hej"]
    i = 0
    while not stopp.is_set():
        v = vagar[i % len(vagar)]
        t = time.perf_counter()
        try:
            r = await c.get(v, headers=h)
            if r.status_code != 200:
                fel[f"{v} HTTP {r.status_code}"] += 1
        except Exception as e:
            fel[f"{v} {type(e).__name__}"] += 1
        tider[v].append((time.perf_counter() - t) * 1000)
        i += 1
        await asyncio.sleep(0.2)


async def main():
    tmp = tempfile.mkdtemp(prefix="stressapi_")
    foto = sorted((konfig.DATA_DIR / "bildforrad" / "potatis").glob("2*_0"))[0]
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8484", timeout=40) as c:
        inl = (await c.post("/api/logga-in", json={"kod": enheter.ny_kod(), "namn": "Stresstest API"})).json()
        h = {"Authorization": f"Bearer {inl['nyckel']}"}
        try:
            stopp = asyncio.Event()
            tel = [asyncio.create_task(telefon(c, h, stopp)) for _ in range(4)]
            p = await asyncio.create_subprocess_exec(sys.executable, "demo_video.py", f"{tmp}/r.mp4", "potatis 7", str(foto),
                                                     stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await p.wait()
            stopp.set()
            await asyncio.gather(*tel)
        finally:
            enheter.sparra(inl["enhet"])
    for v, t in tider.items():
        s = sorted(t)
        print(f"{v:26} {len(s):5} anrop  median {statistics.median(s):5.0f} ms  95 % {s[int(len(s) * .95)]:5.0f} ms  max {s[-1]:6.0f} ms")
    print("fel:", dict(fel) or "inga")


asyncio.run(main())
