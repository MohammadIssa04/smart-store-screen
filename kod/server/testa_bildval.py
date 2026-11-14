"""Testar att appen får välja bild bland nätbilderna (tjanst + api/annonser) utan nät och utan AI:
bildsökningen och videon byts mot låtsasfunktioner. Rör inga riktiga filer.
    .venv/bin/python testa_bildval.py"""
import asyncio
import time
import tempfile
from pathlib import Path

from PIL import Image

import tjanst
import bildsok
import igenkanning
from api import annonser
from api import appen

TMP = Path(tempfile.mkdtemp(prefix="butiksbot_bildval_"))
res = []


def kolla(namn, ok, info=""):
    res.append(bool(ok))
    print(f"{'OK ' if ok else 'FEL'} {namn}{'  (' + str(info) + ')' if info != '' else ''}")


omgang = {"n": 0}


async def falsk_sok(namn, mapp, antal=1, forrad=True, lage=None, onskat=None, utom=None, bara_kandidater=False,
                    info=None):
    omgang["n"] += 1
    ut = []
    for i in range(onskat or 3):
        f = mapp / f"webb{omgang['n']}_{i}"
        Image.new("RGB", (300, 300), (200, 40 * i, 90)).save(f, "JPEG")
        ut.append(f)
    if utom:
        kolla("fler: tidigare (och dåliga) bilder skickas med som utom", len(utom) == 4, len(utom))
    kolla(f"omgång {omgang['n']}: utan friläggning när man väljer", bara_kandidater == bool(onskat == tjanst.VALJ_ANTAL))
    return ut

frilagda = []
import video.frilagg as vf


def falsk_frilagg(p, *x, **y):
    frilagda.append(Path(p).name)
    return None if "_3" in Path(p).name else Image.new("RGBA", (10, 10))   # bild 4 "går inte att klippa ut"

vf.frilagg = falsk_frilagg

bildsok.hamta_bilder = falsk_sok
igenkanning.tillganglig = lambda: True
videor = []


async def falsk_video(st, justering=None):
    videor.append(list(st["a"]["fotos"]))
    st.update(status="klar", lage="")

annonser.gor_video = falsk_video


async def vanta(st):
    for _ in range(50):
        await asyncio.sleep(0.02)
        if st["status"] != "arbetar":
            return


async def main():
    # Gammal app / Telegram (utan valja): väljer första bilden själv, som förut.
    a = tjanst.nytt_arende(rubrik="Bananer", pris="19 kr/kg")
    a["mapp"] = str(TMP / "gammal"); Path(a["mapp"]).mkdir()
    st = {"a": a, "status": "fragar", "meddelanden": [], "skapad": time.time()}
    annonser.fortsatt(st)
    await vanta(st)
    kolla("utan valja: video direkt med bild 1", st["status"] == "klar" and videor[-1] and "webb1_0" in videor[-1][0])

    # Ny app (valja=1): frågar vilken bild
    a = tjanst.nytt_arende(rubrik="Bananer", pris="19 kr/kg")
    a["valja"] = True
    a["mapp"] = str(TMP / "ny"); Path(a["mapp"]).mkdir()
    st = {"a": a, "status": "fragar", "meddelanden": [], "skapad": time.time()}
    annonser.arenden[a["id"]] = st
    annonser.fortsatt(st)
    await vanta(st)
    ut = annonser.utan_interna(st)
    kolla("med valja: frågar vilken bild", ut["behover"] == "valj_bild" and ut["bilder"] == tjanst.VALJ_ANTAL, ut["behover"])
    kolla("kan be om fler", ut.get("kan_fler") is True)
    kolla("webb-flaggan ligger kvar", a.get("webb") is True and not a.get("ny_bild"))
    r = await annonser.kandidat(a["id"], 2)
    kolla("bild att välja: jpeg", Path(r.path).is_file() and Image.open(r.path).size == (600, 600))
    r = await annonser.kandidat(a["id"], 9)
    kolla("okänd bild: 404", r.status_code == 404)

    # Fler bilder
    await annonser.fler_bilder(a["id"])
    await vanta(st)
    await asyncio.sleep(0.05)
    ut = annonser.utan_interna(st)
    kolla("fler: 8 att välja mellan", ut["bilder"] == 8 and ut["behover"] == "valj_bild", ut["bilder"])

    # Pappa skriver "6" i chatten: bild 6 (webb3_1), en gång, ingen ny fråga
    frilagda.clear()
    await annonser.svar(a["id"], text="6", fotos=[])
    await vanta(st)
    kolla("siffra i chatten = bildval", st["status"] == "klar" and "webb3_1" in videor[-1][0], videor[-1])
    kolla("bara den valda klipps ut", frilagda == ["webb3_1"], frilagda)
    fragor = [m["text"] for m in st["meddelanden"] if m["text"].startswith("Vilken bild")]
    kolla("frågade bara en gång", len(fragor) == 1, len(fragor))
    kolla("chatten visar valet en gång", [m["text"] for m in st["meddelanden"] if m["fran"] == "du"] == ["6"],
          [m["text"] for m in st["meddelanden"] if m["fran"] == "du"])
    r = await annonser.valj_bild(a["id"], annonser.ValjBild(nr=1))
    kolla("välja igen efteråt: 409", getattr(r, "status_code", 200) == 409)

    # Bild som inte går att frilägga: används ändå (i ram), ingen ny fråga
    a3 = tjanst.nytt_arende(rubrik="Bananer", pris="19 kr/kg")
    a3.update(valja=True, mapp=str(TMP / "ram"))
    Path(a3["mapp"]).mkdir()
    st3 = {"a": a3, "status": "fragar", "meddelanden": [], "skapad": time.time()}
    annonser.arenden[a3["id"]] = st3
    annonser.fortsatt(st3)
    await vanta(st3)
    await annonser.valj_bild(a3["id"], annonser.ValjBild(nr=3))
    await vanta(st3)
    kolla("ofrilagd bild: video i ram ändå", st3["status"] == "klar" and a3.get("fyller") is True and "_3" in videor[-1][0])

    # Stavfel i namnet rättas (AI), märken och pappas egna rättningar lämnas
    async def falsk_ai(innehall, schema):
        t = innehall[0]["text"]
        return {"namn": "Apelsiner"} if '"apelsint"' in t.split("så här:")[1][:14].lower() else {"namn": t.split('\"')[1]}
    igenkanning.fraga_gemini = falsk_ai
    igenkanning.gemini_finns = lambda: True
    kolla("apelsint -> Apelsiner", await tjanst.ratta_namn("apelsint") == "Apelsiner")
    a4 = tjanst.nytt_arende()
    await tjanst.tolka_text(a4, "apelsint 15kr")
    kolla("tolka_text rättar namnet", a4["rubrik"] == "Apelsiner", a4["rubrik"])

    # Eget foto medan man väljer: valet försvinner
    a2 = tjanst.nytt_arende(rubrik="Cola", pris="15")
    a2.update(valja=True, mapp=str(TMP / "foto"))
    Path(a2["mapp"]).mkdir()
    st2 = {"a": a2, "status": "fragar", "meddelanden": [], "skapad": time.time()}
    annonser.fortsatt(st2)
    await vanta(st2)

    class Uppl:
        async def read(self, n):
            return b"\xff\xd8eget foto"
    await annonser.spara_fotos(a2, [Uppl()])
    kolla("eget foto tar bort bildvalet", not a2.get("valj_bild") and tjanst.nasta_steg(a2).behover == "video")

    # Appuppdatering
    appen.MAPP = TMP / "app"
    kolla("ingen uppdatering: kod 0", (await appen.version())["kod"] == 0)
    appen.MAPP.mkdir()
    (appen.MAPP / "minbutik.apk").write_bytes(b"PK" + b"0" * 1000)
    (appen.MAPP / "version.json").write_text('{"kod": 16, "namn": "1.3", "nytt": ["Musiken först"]}', encoding="utf-8")
    v = await appen.version()
    kolla("uppdatering finns", v["kod"] == 16 and v["namn"] == "1.3" and v["nytt"] == ["Musiken först"], v)
    kolla("apk skickas", str((await appen.apk()).path).endswith("minbutik.apk"))
    from api import problem
    import os
    os.environ.pop("NTFY_AMNE", None)
    kolla("ntfy utan ämne: skickas inte", await problem._ntfy("t", "x") is False)

asyncio.run(main())
print(f"{sum(res)}/{len(res)} OK  (testmapp {TMP})")
