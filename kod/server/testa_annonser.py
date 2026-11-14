"""Testar Skärmen i appen hela vägen via HTTP (riktiga renderingar), i tillfälliga mappar:
inget hamnar på den riktiga skylten, i lagret, minnet eller bland telefonerna.
    set -a; . ./butiksbot.env; set +a; .venv/bin/python testa_annonser.py foto.jpg
Flöde: foto + 'röda äpplen' -> fråga om pris -> '12/kg' -> video -> 'Gör om: större pris' -> ny video
-> publicera -> visa extra (3 dagar) -> förläng (2 dagar) -> ta bort."""
import asyncio
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ["API_PORT"] = "8487"
import httpx  # noqa: E402
import uvicorn  # noqa: E402

import konfig  # noqa: E402
TMP = Path(tempfile.mkdtemp(prefix="butiksbot_annons_"))
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

FOTO = Path(sys.argv[1])
res = []


def kolla(namn, ok, info=""):
    res.append(bool(ok))
    print(f"{'OK ' if ok else 'FEL'} {namn}{'  (' + str(info) + ')' if info != '' else ''}", flush=True)


async def vanta_klar(c, h, aid, max_s=900):
    t = time.time()
    while time.time() - t < max_s:
        j = (await c.get(f"/api/annonser/arende/{aid}", headers=h)).json()
        if j["status"] != "arbetar":
            return j, round(time.time() - t)
        await asyncio.sleep(5)
    return j, round(time.time() - t)


async def main_test():
    server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=8487, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", 8487), 0.2).close()
            break
        except OSError:
            time.sleep(0.2)
    kod = enheter.ny_kod()
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8487", timeout=120) as c:
        nyckel = (await c.post("/api/logga-in", json={"kod": kod, "namn": "Test"})).json()["nyckel"]
        h = {"Authorization": f"Bearer {nyckel}"}
        kolla("utan nyckel: 401", (await c.get("/api/annonser")).status_code == 401)

        r = await c.post("/api/annonser/ny", headers=h, data={"text": "röda äpplen"},
                         files=[("fotos", ("foto.jpg", FOTO.read_bytes(), "image/jpeg"))])
        j = r.json()
        kolla("foto + text utan pris: frågar efter pris", j["status"] == "fragar" and j["behover"] == "pris", j["fraga"])
        aid = j["id"]
        j = (await c.post(f"/api/annonser/arende/{aid}/svar", headers=h, data={"text": "12/kg"})).json()
        kolla("svar '12/kg': börjar göra video", j["status"] == "arbetar", j.get("lage"))
        j, sek = await vanta_klar(c, h, aid)
        kolla("video klar", j["status"] == "klar", f"{sek} s, {j.get('sammanfattning', '').splitlines()[0] if j.get('sammanfattning') else j['meddelanden'][-1]}")
        v = await c.get(f"/api/annonser/arende/{aid}/video", headers=h)
        b = await c.get(f"/api/annonser/arende/{aid}/bild", headers=h)
        kolla("förhandsvisning och bild hämtas", v.status_code == 200 and len(v.content) > 500_000
              and b.headers.get("content-type") == "image/jpeg", f"{len(v.content) // 1024} kB video")
        forsta = len(v.content)

        j = (await c.post(f"/api/annonser/arende/{aid}/gor-om", headers=h, json={"feedback": "större pris tack"})).json()
        kolla("Gör om 'större pris': ny video påbörjas", j["status"] == "arbetar")
        j, sek = await vanta_klar(c, h, aid)
        v2 = await c.get(f"/api/annonser/arende/{aid}/video", headers=h)
        kolla("ny video klar", j["status"] == "klar" and v2.status_code == 200 and len(v2.content) != forsta, f"{sek} s")

        j = (await c.post(f"/api/annonser/arende/{aid}/publicera", headers=h)).json()
        while j["status"] == "arbetar":            # publiceringen sker i bakgrunden (skyltens kopia vrids)
            await asyncio.sleep(2)
            j = (await c.get(f"/api/annonser/arende/{aid}", headers=h)).json()
        kolla("publicerad", j["status"] == "publicerad", j["meddelanden"][-1]["text"][:90])
        lista = (await c.get("/api/annonser", headers=h)).json()["annonser"]
        kolla("syns i listan", len(lista) == 1, lista[0]["sammanfattning"] if lista else "")
        pid = lista[0]["id"]
        filer = list(konfig.ERBJUDANDEN_DIR.glob("t*.mp4"))
        kolla("filen ligger på (test-)skylten", len(filer) == 1, filer[0].name if filer else "")

        j = (await c.post(f"/api/annonser/{pid}/extra", headers=h, json={"dagar": 3})).json()
        vikter = vader.VIKT_FIL.read_text() if vader.VIKT_FIL.exists() else ""
        kolla("visa extra 3 dagar: vikt 3", j.get("ok") and j["annons"]["extra"] and "\t3" in vikter, j.get("meddelande"))
        fore = filer[0].name
        j = (await c.post(f"/api/annonser/{pid}/forlang", headers=h, json={"dagar": 2})).json()
        efter = [f.name for f in konfig.ERBJUDANDEN_DIR.glob("t*.mp4")]
        kolla("förläng 2 dagar: nytt slut i filnamnet", j.get("ok") and efter and efter[0] != fore,
              f"{fore[:14]} -> {efter[0][:14] if efter else '-'}")
        vb = await c.get(f"/api/annonser/{pid}/video", headers=h)
        kolla("publicerad video hämtas", vb.status_code == 200 and len(vb.content) > 500_000)
        j = (await c.post(f"/api/annonser/{pid}/ta-bort", headers=h)).json()
        kolla("ta bort: till arkivet", j.get("ok") and not list(konfig.ERBJUDANDEN_DIR.glob("t*.mp4"))
              and list(konfig.ARKIV_DIR.glob("*.mp4")), j.get("meddelande"))
        kolla("listan tom", (await c.get("/api/annonser", headers=h)).json()["annonser"] == [])
    print(f"\n{sum(res)}/{len(res)} OK  (testmapp {TMP})")


asyncio.run(main_test())
