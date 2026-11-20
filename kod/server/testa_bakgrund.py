"""Testar appens flöde utan foto: bildsökningen körs i bakgrunden med lägesrapporter, videon blir 30 fps,
publiceringen vrider skyltens kopia och "Tills vidare" sätter slutet långt fram. Tillfälliga mappar,
inget hamnar på den riktiga skylten.
    set -a; . ./butiksbot.env; set +a; .venv/bin/python testa_bakgrund.py [vara]"""
import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ["API_PORT"] = "8490"
import httpx  # noqa: E402
import uvicorn  # noqa: E402

import konfig  # noqa: E402
TMP = Path(tempfile.mkdtemp(prefix="butiksbot_bakgrund_"))
konfig.UTKAST_DIR = TMP / "utkast"
konfig.ERBJUDANDEN_DIR, konfig.ARKIV_DIR = TMP / "skylt", TMP / "skylt" / "arkiv"
import enheter, minne, tjanst, vader  # noqa: E401,E402
from lager import Lager  # noqa: E402
for n in ("ENHETER", "KODER", "SEDD", "LOGG"):
    setattr(enheter, n, TMP / getattr(enheter, n).name)
for n in ("PRODUKTER", "SYNONYMER", "GODKANDA", "OFORSTATT", "OVERGANGAR", "KONTROLLER"):
    setattr(minne, n, TMP / getattr(minne, n).name)
minne.BILDER = TMP / "bilder"
tjanst.lager = Lager(TMP / "erbjudanden.json")
vader.VIKT_FIL, vader.LOGG_FIL = konfig.ERBJUDANDEN_DIR / ".vikter", TMP / "vader.jsonl"
from api import main  # noqa: E402

VARA = sys.argv[1] if len(sys.argv) > 1 else "röda äpplen 12/kg"
res = []


def kolla(namn, ok, info=""):
    res.append(bool(ok))
    print(f"{'OK ' if ok else 'FEL'} {namn}{'  (' + str(info) + ')' if info != '' else ''}", flush=True)


def probe(f):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                        "stream=width,height,r_frame_rate,nb_read_frames", "-of", "csv=p=0", str(f)],
                       capture_output=True, text=True)
    return r.stdout.strip()


async def main_test():
    server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=8490, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", 8490), 0.2).close()
            break
        except OSError:
            time.sleep(0.2)
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8490", timeout=30) as c:
        h = {"Authorization": "Bearer " + (await c.post("/api/logga-in", json={"kod": enheter.ny_kod(), "namn": "Test"})).json()["nyckel"]}
        t = time.time()
        j = (await c.post("/api/annonser/ny", headers=h, data={"text": VARA})).json()
        kolla("svarar direkt (under 15 s)", time.time() - t < 15, f"{time.time() - t:.1f} s, status {j['status']}")
        aid = j["id"]
        lagen, t = [], time.time()
        while time.time() - t < 1200:
            j = (await c.get(f"/api/annonser/arende/{aid}", headers=h)).json()
            if j["lage"] and (not lagen or lagen[-1] != j["lage"]):
                lagen.append(j["lage"])
                print("   läge:", j["lage"], flush=True)
            if j["status"] != "arbetar":
                break
            await asyncio.sleep(2)
        # Bilden kan komma ur bildförrådet direkt (då ingen "Söker"): minst två lägen räcker
        kolla("lägesrapporter under arbetet", len(lagen) >= 2 or any("Söker" in l for l in lagen), lagen[:4])
        if j["status"] == "fragar":
            print("   frågar:", j["fraga"])
            j = (await c.post(f"/api/annonser/arende/{aid}/svar", headers=h, data={"text": "12/kg"})).json()
            while j["status"] == "arbetar":
                await asyncio.sleep(3)
                j = (await c.get(f"/api/annonser/arende/{aid}", headers=h)).json()
        kolla("video klar", j["status"] == "klar", j["status"] + " " + str(j["meddelanden"][-1]["text"])[:80])
        if j["status"] != "klar":
            return
        u = Path(next(konfig.UTKAST_DIR.glob(f"*_{aid}"))) if list(konfig.UTKAST_DIR.glob(f"*_{aid}")) else None
        videor = sorted(u.glob("video*.mp4")) if u else []
        p = probe(videor[-1]) if videor else ""
        kolla("videon är 1080x1920 i 30 fps, 270 bildrutor", p.startswith("1080,1920,30/1") and p.endswith(",270"), p)
        await asyncio.sleep(45)          # som när pappa tittar på förhandsvisningen: kopian vrids under tiden
        u2 = next(konfig.UTKAST_DIR.glob(f"*_{aid}"))
        kolla("liggande kopia gjord i förväg", list(u2.glob("*.liggande.mp4")), [f.name for f in u2.glob("*.liggande.mp4")])
        t = time.time()
        j = (await c.post(f"/api/annonser/arende/{aid}/publicera", headers=h)).json()
        kolla("publicera svarar direkt", time.time() - t < 5, f"{time.time() - t:.1f} s, {j['status']} {j['lage']}")
        while j["status"] == "arbetar":
            await asyncio.sleep(2)
            j = (await c.get(f"/api/annonser/arende/{aid}", headers=h)).json()
        kolla("publicerad", j["status"] == "publicerad", j["meddelanden"][-1]["text"][:70])
        kolla("publiceringen gick fort (kopian fanns)", time.time() - t < 10, f"{time.time() - t:.1f} s")
        filer = list(konfig.ERBJUDANDEN_DIR.glob("t*.mp4"))
        kolla("publicerad: skyltens kopia liggande", filer and probe(filer[0]).startswith("1920,1080,30/1"), probe(filer[0]) if filer else "")
        pid = j.get("post_id")
        j = (await c.post(f"/api/annonser/{pid}/tills-vidare", headers=h)).json()
        filer = list(konfig.ERBJUDANDEN_DIR.glob("t*.mp4"))
        kolla("tills vidare: slut 2099 i filnamnet", j.get("ok") and filer and filer[0].name.startswith("t2099"),
              filer[0].name[:14] if filer else "")
        j = (await c.post(f"/api/annonser/{pid}/vader", headers=h, json={"typ": "varm"})).json()
        lista = (await c.get("/api/annonser", headers=h)).json()["annonser"]
        kolla("väder valt av pappa: varm vara", j.get("ok") and lista[0]["vadertyp_kod"] == "varm", j.get("meddelande"))
        r = await c.post(f"/api/annonser/{pid}/vader", headers=h, json={"typ": "fel"})
        kolla("okänd vädertyp nekas", r.status_code == 400)
        kolla("appen ser 'tills vidare'", lista and lista[0]["tills_vidare"], lista[0]["slutar"] if lista else "")
        v = await c.get(f"/api/annonser/{pid}/video", headers=h)
        tmpv = TMP / "app.mp4"
        tmpv.write_bytes(v.content)
        kolla("appen får den stående originalvideon", probe(tmpv).startswith("1080,1920"), probe(tmpv))
        await c.post(f"/api/annonser/{pid}/ta-bort", headers=h)
    print(f"\n{sum(res)}/{len(res)} OK  (testmapp {TMP})")


asyncio.run(main_test())
