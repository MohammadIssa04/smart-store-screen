"""Testar prisetiketterna via HTTP i tillfälliga mappar (testläge: ingen skrivare, inget i riktiga minnet).
    set -a; . ./butiksbot.env; set +a; .venv/bin/python testa_etikett.py [foto.jpg]
Med foto och GEMINI_API_KEY testas även AI-avläsningen av namnet."""
import asyncio
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ["API_PORT"] = "8488"
os.environ["ETIKETT_LAGE"] = "test"
import httpx  # noqa: E402
import uvicorn  # noqa: E402
from PIL import Image  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="butiksbot_etikett_"))
import enheter, etikett, minne  # noqa: E401,E402
for n in ("ENHETER", "KODER", "SEDD", "LOGG"):
    setattr(enheter, n, TMP / getattr(enheter, n).name)
for n in ("PRODUKTER", "SYNONYMER", "GODKANDA", "OFORSTATT", "OVERGANGAR", "KONTROLLER"):
    setattr(minne, n, TMP / getattr(minne, n).name)
etikett.MAPP, etikett.LOGG = TMP / "etiketter", TMP / "etiketter" / "logg.jsonl"
from api import main  # noqa: E402

FOTO = Path(sys.argv[1]) if len(sys.argv) > 1 else None
res = []


def kolla(namn, ok, info=""):
    res.append(bool(ok))
    print(f"{'OK ' if ok else 'FEL'} {namn}{'  (' + str(info) + ')' if info != '' else ''}", flush=True)


async def main_test():
    e = etikett.rita("Red Bull", "15 kr + pant")
    kolla("mallen 559x320 svartvit", e.size == (559, 320) and e.mode == "1", e.size)
    s = etikett.for_skrivaren(e)
    svart_ruta = s.convert("L").point(lambda v: 255 - v).getbbox()      # där det finns svart
    kolla("för skrivaren: hela huvudets bredd, centrerad", s.size == (etikett.HUVUD, 320)
          and abs(svart_ruta[0] - (etikett.HUVUD - svart_ruta[2])) <= 2, svart_ruta)
    svart = e.convert("L").histogram()[0] / (559 * 320)
    kolla("lagom med svart (band, text, ram)", 0.08 < svart < 0.45, f"{svart:.0%}")

    server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=8488, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", 8488), 0.2).close()
            break
        except OSError:
            time.sleep(0.2)
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8488", timeout=120) as c:
        nyckel = (await c.post("/api/logga-in", json={"kod": enheter.ny_kod(), "namn": "Test"})).json()["nyckel"]
        h = {"Authorization": f"Bearer {nyckel}"}
        kolla("utan nyckel: 401", (await c.post("/api/etiketter/forhandsvisa", json={"namn": "a", "pris": "1"})).status_code == 401)
        j = (await c.get("/api/etiketter/lage", headers=h)).json()
        kolla("läge: test", j["lage"] == "test", j)

        r = await c.post("/api/etiketter/forhandsvisa", headers=h, json={"namn": "Bananer", "pris": "19,90/kg"})
        ok = r.status_code == 200 and r.headers["content-type"] == "image/png"
        kolla("förhandsvisning PNG", ok, f"{len(r.content) // 1024} kB")
        r = await c.post("/api/etiketter/forhandsvisa", headers=h, json={"namn": "Bananer", "pris": "billigt"})
        kolla("pris som inte går att läsa: tydligt fel", r.status_code == 400 and "priset" in r.json()["fel"], r.json())
        r = await c.post("/api/etiketter/forhandsvisa", headers=h, json={"namn": "  ", "pris": "10"})
        kolla("tomt namn: tydligt fel", r.status_code == 400, r.json())

        j = (await c.post("/api/etiketter/skriv-ut", headers=h,
                          json={"namn": "Red Bull Energy", "pris": "15 + pant", "antal": 2, "ai_namn": "Redbull"})).json()
        filer = list((etikett.MAPP / "test").glob("*.png"))
        kolla("skriv ut i testläge: sparas som bild", j.get("lage") == "test" and len(filer) == 1, j.get("meddelande"))
        if filer:
            b = Image.open(filer[0])
            kolla("sparad bild som skrivaren får (huvudets bredd x 320, 1 bit)", b.size == (etikett.HUVUD, 320) and b.mode == "1", b.size)
        kolla("rättat AI-namn sparas som synonym", minne.synonym("Redbull") == "Red Bull Energy")
        await c.post("/api/etiketter/skriv-ut", headers=h, json={"namn": "Mjölk", "pris": "9"})
        await c.post("/api/etiketter/skriv-ut", headers=h, json={"namn": "red bull energy", "pris": "15 kr + pant"})
        j = (await c.get("/api/etiketter/senaste", headers=h)).json()["etiketter"]
        kolla("senaste: nyast först, utan dubbletter", [x["namn"] for x in j] == ["red bull energy", "Mjölk"], j)

        os.environ["ETIKETT_LAGE"] = "usb"
        r = await c.post("/api/etiketter/skriv-ut", headers=h, json={"namn": "Mjölk", "pris": "9"})
        kolla("USB-läge utan skrivare: svenskt fel, ingen krasch", r.status_code == 503 and r.json().get("fel"), r.json())
        os.environ["ETIKETT_LAGE"] = "test"

        if FOTO:
            r = await c.post("/api/etiketter/las", headers=h, data={"text": "25"},
                             files={"fotos": ("foto.jpg", FOTO.read_bytes(), "image/jpeg")})
            j = r.json()
            kolla("AI läser namnet från fotot", r.status_code == 200 and j.get("namn") and j.get("pris") == "25 kr", j)
    print(f"\n{sum(res)}/{len(res)} OK  (testmapp {TMP})")


asyncio.run(main_test())
