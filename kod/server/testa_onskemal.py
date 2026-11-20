"""Testar önskemålen 2026-11-13 utan att röra riktig data (tillfälliga mappar):
musikens dagliga byte och arkiv, konsertfiltret, visningstid på skärmen, arabiska svar, sparad chatt,
Facebook-länkar (utan nyckel: tydligt svar, ingen sida läses).
    set -a; . ./butiksbot.env; set +a; .venv/bin/python testa_onskemal.py"""
import asyncio
import json
import os
import socket
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

os.environ["API_PORT"] = "8489"
os.environ.pop("FACEBOOK_SIDTOKEN", None)
import httpx  # noqa: E402
import uvicorn  # noqa: E402

import konfig  # noqa: E402
TMP = Path(tempfile.mkdtemp(prefix="butiksbot_onskemal_"))
konfig.UTKAST_DIR = TMP / "utkast"
import enheter, facebook, oversatt, skyltlista  # noqa: E401,E402
from musik import bibliotek as bib, hamtning  # noqa: E402
for n in ("ENHETER", "KODER", "SEDD", "LOGG"):
    setattr(enheter, n, TMP / getattr(enheter, n).name)
bib.DATA, bib.BIBLIOTEK_FIL, bib.ORDNING_FIL = TMP, TMP / "bibliotek.json", TMP / "ordning.json"
bib.FILER, bib.ARKIV = TMP / "filer", TMP / "filer" / "arkiv"
from api import main  # noqa: E402

res = []


def kolla(namn, ok, info=""):
    res.append(bool(ok))
    print(f"{'OK ' if ok else 'FEL'} {namn}{'  (' + str(info) + ')' if info != '' else ''}", flush=True)


def musik():
    gammal = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
    alla = []
    for i in range(27):                                  # umm: mål 25, alltså 2 över
        f = bib.FILER / "umm" / f"l{i}.m4a"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
        alla.append({"id": f"l{i}", "titel": f"Låt {i}", "artist": "Umm Kulthum", "block": "umm", "langd": 600,
                     "fil": str(f), "kalla": "manuell" if i == 0 else "auto", "status": "aktiv",
                     "tillagd": gammal, "spelad": 50 if i in (0, 1, 2) else i % 3})
    bib.BIBLIOTEK_FIL.write_text(json.dumps(alla), encoding="utf-8")
    ut = bib.rotera_ut("umm", 2)
    kolla("dagligt byte: de 2 mest spelade auto-låtarna till arkivet (inte pappas egna)",
          sorted(l["id"] for l in ut) == ["l1", "l2"] and len(bib.latar("umm")) == 25, [l["id"] for l in ut])
    kolla("utbytta låtar flyttas, raderas inte", all(Path(l["fil"]).is_file() and "arkiv" in l["fil"] for l in ut))
    kolla("inget byts ut när listan inte är över målet", bib.rotera_ut("umm", 2) == [])
    kolla("för nyligen utbytt: kommer inte tillbaka än", bib.ateraktivera("umm") is None)
    alla = json.loads(bib.BIBLIOTEK_FIL.read_text(encoding="utf-8"))
    for l in alla:
        if l["id"] == "l1":
            l["borttagen"] = (datetime.now() - timedelta(days=90)).isoformat(timespec="seconds")
    bib.BIBLIOTEK_FIL.write_text(json.dumps(alla), encoding="utf-8")
    tillbaka = bib.ateraktivera("umm")
    kolla("efter 60 dagar kan en utbytt låt komma tillbaka", tillbaka and tillbaka["id"] == "l1"
          and Path(tillbaka["fil"]).is_file() and "arkiv" not in tillbaka["fil"])
    artist = {"namn": "Umm Kulthum", "sok": ["Umm Kulthum", "أم كلثوم"]}
    konsert = {"titel": "أم كلثوم - فكروني - حفلة كاملة", "kanal": "x", "langd": 54 * 60}
    studio = {"titel": "أم كلثوم - فكروني", "kanal": "x", "langd": 40 * 60}
    kolla("konsertinspelningar (lång inledning) väljs bort vid hämtning",
          not hamtning.ar_lat(konsert, artist, 75) and hamtning.ar_lat(studio, artist, 75))


async def api():
    server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=8489, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", 8489), 0.2).close()
            break
        except OSError:
            time.sleep(0.2)
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8489", timeout=60) as c:
        nyckel = (await c.post("/api/logga-in", json={"kod": enheter.ny_kod(), "namn": "Test"})).json()["nyckel"]
        h = {"Authorization": f"Bearer {nyckel}"}
        har = {**h, "X-Sprak": "ar"}
        j = (await c.post("/api/annonser/ny", headers=har, data={"text": "bananer"})).json()
        for _ in range(60):                     # /ny svarar inom 8 s; tolkningen kan fortsätta i bakgrunden
            if j["status"] != "arbetar":
                break
            await asyncio.sleep(1)
            j = (await c.get(f"/api/annonser/arende/{j['id']}", headers=har)).json()
        m = j["meddelanden"]
        kolla("pappas egna meddelanden sparas (chatten kan visas igen)", m and m[0]["fran"] == "du" and m[0]["text"] == "bananer")
        kolla("arabiska: butikens fråga på arabiska", "ما سعر" in j["fraga"] or "التقط" in j["fraga"], j["fraga"])
        j2 = (await c.get(f"/api/annonser/arende/{j['id']}", headers=h)).json()
        kolla("svenska när telefonen inte bett om arabiska", "pris" in j2["fraga"].lower() or "foto" in j2["fraga"].lower(), j2["fraga"])
        r = await c.post("/api/etiketter/forhandsvisa", headers=har, json={"namn": "", "pris": "1"})
        kolla("arabiska felmeddelanden", r.json()["fel"] == "اكتب اسم السلعة.", r.json())

        j = (await c.post("/api/annonser/ny", headers=h,
                          data={"text": "https://www.facebook.com/exempelbutik/posts/pfbid0abcDEF123"})).json()
        kolla("Facebook-länk utan nyckel: ber om bilden i stället", "Facebook-länkar" in j["fraga"], j["fraga"][:70])
        lista = (await c.get("/api/annonser", headers=h)).json()
        kolla("annonslistan svarar (med visningstid)", "annonser" in lista)


def ovrigt():
    kolla("Facebook-länkar känns igen", facebook.hitta_lank("kolla https://m.facebook.com/story.php?story_fbid=123456789&id=1 tack")
          == "https://m.facebook.com/story.php?story_fbid=123456789&id=1")
    kolla("vanlig text är ingen länk", facebook.hitta_lank("redbull 15 + pant") is None)
    kolla("inläggets id plockas ur länken", {"pfbid0abc", "123456789"} <= facebook._nycklar(
        "https://www.facebook.com/x/posts/pfbid0abc https://facebook.com/story.php?story_fbid=123456789"))
    kolla("arabiska mönster: pris-frågan", oversatt.ar("Vilket pris har Bananer? T.ex. 19, 10/kg, 2 för 30 eller 15 + pant.")
          .startswith("ما سعر Bananer"))
    e = TMP / "e"
    e.mkdir()
    (e / "a.mp4").write_bytes(b"")
    v = skyltlista.visning([e / "a.mp4"])
    kolla("visningstid räknas per annons", "a.mp4" in v and v["a.mp4"]["per_timme"] > 0, v.get("a.mp4"))


musik()
ovrigt()
asyncio.run(api())
print(f"\n{sum(res)}/{len(res)} OK  (testmapp {TMP})")
