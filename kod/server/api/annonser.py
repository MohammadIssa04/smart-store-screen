"""Skärmen i appen: skapa annonser som en chatt, och sköta annonserna som visas.

Skapa (samma logik som Telegram-boten, via tjanst.py):
  POST /api/annonser/ny                 text + 0-3 foton -> ett ärende (svarar med fråga, eller börjar göra video)
  POST /api/annonser/arende/{id}/svar   svar på frågan (text och/eller foton)
  POST /api/annonser/arende/{id}/leta-bild   leta bild på nätet i stället för eget foto
  (med ?valja=1 på /ny får pappa välja bland nätbilderna:)
  GET  /api/annonser/arende/{id}/kandidat/{nr}   bild nr att välja (jpeg)
  POST /api/annonser/arende/{id}/valj-bild {"nr"} | fler-bilder
  GET  /api/annonser/arende/{id}        läget: fragar | arbetar | klar | fel | publicerad | avbruten
  GET  /api/annonser/arende/{id}/video  förhandsvisningen;  .../bild = en bildruta
  POST /api/annonser/arende/{id}/publicera | avbryt
  POST /api/annonser/arende/{id}/gor-om  {"feedback": "större pris"} -> ny video
Sköta (publicerade):
  GET  /api/annonser                    det som visas på skärmen
  GET  /api/annonser/{id}/video | bild
  POST /api/annonser/{id}/ta-bort | forlang {"dagar"} | extra {"dagar": 1|3|7}
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import facebook
import igenkanning
import kvalitet
import skyltlista
import minne
import tjanst
import oversatt
import tolka
import vader
from lager import tid
from video.animation import MAX_PRODUKTER

log = logging.getLogger("butiksbot.api.annonser")
router = APIRouter(prefix="/api/annonser")
MAX_FOTO = 15 * 1024 * 1024
arenden: dict[str, dict] = {}            # ärende-id -> läge (finns kvar i 24 h)


def fel(text: str, kod: int = 400):
    return JSONResponse({"fel": oversatt.t(text)}, status_code=kod)


def _rensa_gamla() -> None:
    for k in [k for k, v in arenden.items() if time.time() - v["skapad"] > 24 * 3600]:
        arenden.pop(k, None)


def utan_interna(st: dict) -> dict:
    """Det appen får se av ett ärende."""
    a, u = st["a"], st.get("utkast")
    T = oversatt.t
    meddelanden = [{**m, "text": T(m["text"])} if m.get("fran") == "butiken" else m for m in st["meddelanden"]]
    ut = {"id": a["id"], "status": st["status"], "meddelanden": meddelanden, "fraga": T(st.get("fraga", "")),
          "behover": st.get("behover", ""), "lage": T(st.get("lage", "")), "notiser": [T(n) for n in st.get("notiser", [])],
          "kan_leta_bild": st.get("behover") == "foto" and igenkanning.tillganglig()}
    if st.get("behover") == "valj_bild":
        ut["bilder"] = len(a["kandidater"])
        ut["kan_fler"] = igenkanning.tillganglig()
    if u:
        ut["sammanfattning"] = tjanst.beskriv(u.post)
        ut["post_id"] = u.post["id"]
    return ut


def du(st: dict, text: str, fotos: list) -> None:
    """Pappas eget meddelande sparas också, så att appen kan visa hela chatten igen efter flikbyte/omstart."""
    if text.strip() or fotos:
        st["meddelanden"].append({"fran": "du", "text": text.strip(), "fotos": len(fotos),
                                  "tid": datetime.now().isoformat(timespec="seconds")})


def bot(st: dict, text: str) -> None:
    st["meddelanden"].append({"fran": "butiken", "text": text, "tid": datetime.now().isoformat(timespec="seconds")})


async def spara_fotos(a: dict, fotos: list[UploadFile]) -> int:
    if fotos and a.get("webb"):                     # egna foton går alltid före nätbilder
        a["fotos"], a["webb"], a["kandidater"], a["nr"], a["valj_bild"] = [], False, [], 0, False
    antal = 0
    for f in fotos[: MAX_PRODUKTER - len(a["fotos"])]:
        data = await f.read(MAX_FOTO + 1)
        if not data or len(data) > MAX_FOTO:
            continue
        mal = Path(a["mapp"]) / f"foto{len(a['fotos'])}"
        mal.write_bytes(data)
        a["fotos"].append(str(mal))
        antal += 1
    a["antal"] = max(a["antal"], len(a["fotos"]))
    return antal


async def bearbeta(st: dict, text: str, fotos: list[UploadFile]) -> None:
    """Ta emot text/foton och gå vidare tills något saknas (fråga) eller videon kan göras."""
    a = st["a"]
    text = (text or "").strip()
    behover = st.get("behover")
    if lank := facebook.hitta_lank(text):          # länk till ett Facebook-inlägg: gör annonsen av inlägget
        st["lage"] = "Läser Facebook-inlägget …"
        try:
            inlagg = await facebook.hamta(lank)
        except facebook.FacebookFel as f:
            st.update(status="fragar", behover="namn" if not a["rubrik"] else st.get("behover", ""), lage="",
                      fraga=str(f))
            bot(st, str(f))
            return
        if inlagg["bild"] and len(a["fotos"]) < MAX_PRODUKTER:
            mal = Path(a["mapp"]) / f"foto{len(a['fotos'])}"
            mal.write_bytes(inlagg["bild"])
            a["fotos"].append(str(mal))
            a["antal"] = max(a["antal"], len(a["fotos"]))
        a["facebook"] = inlagg["lank"]
        rad = inlagg["text"].splitlines()[0][:90] if inlagg["text"] else ""
        bot(st, f"Hittade inlägget: {rad}" if rad else "Hittade inlägget (utan text).")
        text = (facebook.LANK.sub(" ", text) + " " + inlagg["text"]).strip()
    if text:
        if behover == "pris" and (pris := tolka.tolka_pris(text)):
            a["pris"] = pris
        elif behover == "namn" and not tolka.tolka(text).pris:
            a["rubrik"] = minne.synonym(text[:60])
        else:
            await tjanst.tolka_text(a, text)
            if behover == "pris" and not a["pris"]:
                minne.logga_oforstatt("pris_oforstatt", text, rubrik=a["rubrik"])
    if fotos:
        if await spara_fotos(a, fotos):
            if not a["rubrik"] or not a["pris"]:
                st["lage"] = "Tittar på bilden …"
                if not await tjanst.kanna_igen_fotos(a) and not a["rubrik"]:
                    bot(st, "Jag kände inte igen varan.")
    if a.pop("oklar", False) and not a["rubrik"]:
        st.update(status="fragar", behover="namn", fraga="Jag förstod inte riktigt. Skriv vara och pris, "
                  "t.ex. \"bananer 10/kg 3 dagar\" eller \"redbull 15 + pant\".")
        bot(st, st["fraga"])
        return
    if meddelande := tjanst.fran_minnet(a):
        bot(st, meddelande + " Vill du ha en ny bild trycker du \"Annan bild\".")
    fortsatt(st)


async def leta_och_fortsatt(st: dict) -> None:
    """Bildsökningen tar minuter: körs i bakgrunden, och läget ('Söker bilder på …') syns i appen."""
    a = st["a"]
    try:
        def lage(text: str) -> None:
            st["lage"] = text
        if meddelande := await tjanst.leta_bilder(a, lage=lage):
            bot(st, meddelande)
        if not a["fotos"] and not a.get("valj_bild"):
            a["webb"], a["ny_bild"] = False, True
        fortsatt(st)
    except Exception:
        log.exception("Bildsökningen misslyckades")
        a["webb"], a["ny_bild"] = False, True
        st.update(status="fragar", behover="foto", lage="", fraga="Bildsökningen gick inte. Ta ett eget foto och skicka det.")
        bot(st, st["fraga"])


def fortsatt(st: dict) -> None:
    """Nästa steg: fråga pappa, leta bilder (i bakgrunden) eller gör videon (i bakgrunden)."""
    a = st["a"]
    while True:
        steg = tjanst.nasta_steg(a)
        if steg.behover == "leta_bilder":
            if not a.get("webb_sagt"):
                bot(st, "Jag letar en bild på nätet. Vill du hellre använda ett eget foto kan du skicka det.")
                a["webb_sagt"] = True
            a["webb"] = True
            st.update(status="arbetar", behover="", fraga="", lage=f"Söker bilder på {a['rubrik']} …")
            asyncio.create_task(leta_och_fortsatt(st))
            return
        if steg.behover == "video":
            st.update(status="arbetar", behover="", fraga="")
            asyncio.create_task(gor_video(st))
            return
        st.update(status="fragar", behover=steg.behover, fraga=steg.fraga, lage="")
        if steg.behover == "valj_bild":
            if a.get("fragat_valj"):
                return                       # "Vilken bild …?" bara en gång, även efter "Fler bilder"
            a["fragat_valj"] = True
        bot(st, steg.fraga)
        return


async def gor_video(st: dict, justering: dict | None = None) -> None:
    a = st["a"]
    n = len(a["fotos"])
    st["lage"] = f"Gör videon … (ca {1 + n // 2}–{2 + n // 2} minuter)"

    async def lage(text: str) -> None:
        st["lage"] = text.lstrip("🔍🔧🎬 ")
    try:
        u = await tjanst.gor_video(a, status=lage, justering=justering)
        await asyncio.to_thread(tjanst.miniatyr, Path(u.post["video"]))
        st.update(utkast=u, notiser=u.notiser, status="klar", lage="")
        bot(st, "Här är förhandsvisningen. Tryck Publicera, eller Gör om och skriv vad som ska ändras.")
    except Exception:
        log.exception("Kunde inte göra videon")
        st.update(status="fel", lage="")
        bot(st, "Något gick fel när videon skulle göras. Försök igen, eller med en annan bild.")


def hamta(arende_id: str) -> dict | None:
    _rensa_gamla()
    return arenden.get(arende_id)


@router.post("/ny")
async def ny(text: str = Form(""), fotos: list[UploadFile] = File(default=[]), valja: bool = False):
    a = tjanst.nytt_arende()
    a["valja"] = valja                  # appen 1.3+: pappa väljer själv bland nätbilderna
    st = {"a": a, "status": "fragar", "meddelanden": [], "skapad": time.time()}
    arenden[a["id"]] = st
    if not text.strip() and not fotos:
        return fel("Skriv vad varan heter eller ta ett foto.")
    du(st, text, fotos)
    await bearbeta(st, text, fotos)
    return utan_interna(st)


@router.post("/arende/{arende_id}/svar")
async def svar(arende_id: str, text: str = Form(""), fotos: list[UploadFile] = File(default=[])):
    st = hamta(arende_id)
    if not st:
        return fel("Ärendet finns inte längre. Börja om.", 404)
    if st["status"] == "arbetar":
        return fel("Vänta, jag håller på.", 409)
    siffra = text.strip().lstrip("#").removeprefix("bild").strip()
    if st.get("behover") == "valj_bild" and not fotos and siffra.isdigit():
        du(st, text, [])
        st["valjer"] = True
        return await valj_bild(arende_id, ValjBild(nr=int(siffra) - 1))
    if text.strip().lower() in ("klar", "kör", "gör videon") and st.get("behover") == "fler_foton":
        st["a"]["racker"] = True
        text = ""
    du(st, text, fotos)
    await bearbeta(st, text, fotos)
    return utan_interna(st)


@router.post("/arende/{arende_id}/leta-bild")
async def leta_bild(arende_id: str):
    st = hamta(arende_id)
    if not st or st["status"] == "arbetar":
        return fel("Går inte just nu.", 409)
    st["a"]["webb"], st["a"]["ny_bild"] = True, False
    st["a"]["fotos"], st["a"]["kandidater"], st["a"]["nr"], st["a"]["valj_bild"] = [], [], 0, False
    bot(st, "Okej, jag letar efter en bild på nätet.")
    st["a"]["webb_sagt"] = True
    fortsatt(st)                       # svarar direkt; sökningen fortsätter i bakgrunden
    return utan_interna(st)


@router.get("/arende/{arende_id}/kandidat/{nr}")
async def kandidat(arende_id: str, nr: int):
    """En av bilderna att välja mellan: den frilagda varan på ljus botten, liten (snabb i telefonen)."""
    st = hamta(arende_id)
    k = st["a"]["kandidater"] if st else []
    if not 0 <= nr < len(k):
        return fel("Bilden finns inte.", 404)
    ut = Path(k[nr] + ".val.jpg")
    if not ut.is_file():
        await asyncio.to_thread(_valbild, Path(k[nr]), ut)
    return FileResponse(ut, media_type="image/jpeg")


def _valbild(foto: Path, ut: Path) -> None:
    from PIL import Image
    from video.frilagg import cache_fil
    kalla = cache_fil(foto) if cache_fil(foto).is_file() else foto
    bild = Image.open(kalla).convert("RGBA")
    bild.thumbnail((520, 520))
    botten = Image.new("RGB", (600, 600), (255, 246, 240))
    botten.paste(bild, ((600 - bild.width) // 2, (600 - bild.height) // 2), bild)
    botten.save(ut, "JPEG", quality=85)


class ValjBild(BaseModel):
    nr: int


@router.post("/arende/{arende_id}/valj-bild")
async def valj_bild(arende_id: str, data: ValjBild):
    st = hamta(arende_id)
    if not st or st.get("behover") != "valj_bild":
        return fel("Går inte just nu.", 409)
    if not 0 <= data.nr < len(st["a"]["kandidater"]):
        return fel("Bilden finns inte.", 404)
    if not st.get("valjer"):
        du(st, f"Bild {data.nr + 1}", [])
    st.update(status="arbetar", behover="", lage="Klipper ut bilden …", valjer=False)

    async def jobb():
        try:
            await tjanst.valj_bild(st["a"], data.nr)
        except Exception:
            log.exception("Den valda bilden gick inte att förbereda")
            st["a"].update(fotos=[st["a"]["kandidater"][data.nr]], valj_bild=False, fyller=True)
        bot(st, "Bra val! Jag gör videon med den bilden.")
        st["behover"] = ""
        fortsatt(st)
    asyncio.create_task(jobb())
    return utan_interna(st)


@router.post("/arende/{arende_id}/fler-bilder")
async def fler_bilder(arende_id: str):
    """Söker fler bilder att välja mellan (tar en eller ett par minuter, i bakgrunden)."""
    st = hamta(arende_id)
    if not st or st.get("behover") != "valj_bild":
        return fel("Går inte just nu.", 409)
    a = st["a"]
    st.update(status="arbetar", lage=f"Söker fler bilder på {a['rubrik']} …")

    async def jobb():
        try:
            def lage(text: str) -> None:
                st["lage"] = text
            nya = await tjanst.fler_bilder(a, lage=lage)
            bot(st, f"Hittade {nya} till." if nya else "Jag hittade inga fler bra bilder. Välj en av dessa, "
                                                      "eller ta ett eget foto.")
        except Exception:
            log.exception("Fler bilder misslyckades")
            bot(st, "Det gick inte att söka fler bilder just nu.")
        fortsatt(st)
    asyncio.create_task(jobb())
    return utan_interna(st)


@router.get("/arende/{arende_id}")
async def lage(arende_id: str):
    st = hamta(arende_id)
    return utan_interna(st) if st else fel("Ärendet finns inte längre.", 404)


def _arende_fil(arende_id: str, bild: bool):
    st = hamta(arende_id)
    if not st or not st.get("utkast"):
        return fel("Ingen video än.", 404)
    video = Path(st["utkast"].post["video"])
    return FileResponse(tjanst.miniatyr(video) if bild else video,
                        media_type="image/jpeg" if bild else "video/mp4")


@router.get("/arende/{arende_id}/video")
async def arende_video(arende_id: str):
    return _arende_fil(arende_id, False)


@router.get("/arende/{arende_id}/bild")
async def arende_bild(arende_id: str):
    return _arende_fil(arende_id, True)


@router.post("/arende/{arende_id}/publicera")
async def publicera(arende_id: str, request: Request):
    st = hamta(arende_id)
    if not st or st["status"] != "klar":
        return fel("Det finns ingen färdig video att publicera.", 409)
    # Skyltens kopia vrids vid publiceringen (ca en halv minut): i bakgrunden, appen följer läget.
    av = f"app:{request.state.enhet['namn']}"
    st.update(status="arbetar", lage="Lägger ut på skärmen …")

    async def jobb():
        try:
            post = await asyncio.to_thread(tjanst.publicera, st["utkast"], av)
            st.update(status="publicerad", lage="")
            bot(st, "✅ Publicerad på skärmen. " + tjanst.beskriv(post).replace("\n", " "))
        except Exception:
            log.exception("Publiceringen misslyckades")
            st.update(status="klar", lage="")
            bot(st, "Det gick inte att lägga ut videon. Försök igen.")
    asyncio.create_task(jobb())
    return utan_interna(st)


@router.post("/arende/{arende_id}/avbryt")
async def avbryt(arende_id: str):
    st = hamta(arende_id)
    if not st:
        return fel("Ärendet finns inte längre.", 404)
    if st.get("utkast") and st["status"] == "klar":
        tjanst.avbryt(st["utkast"])
    st["status"] = "avbruten"
    return utan_interna(st)


class GorOm(BaseModel):
    feedback: str = ""


@router.post("/arende/{arende_id}/gor-om")
async def gor_om(arende_id: str, data: GorOm):
    """Feedback i fri text -> ändring + ny video. 'större pris', 'annan bild', 'priset är 12 kr' ..."""
    st = hamta(arende_id)
    if not st or st["status"] not in ("klar", "fel"):
        return fel("Det går inte att göra om just nu.", 409)
    a, text = st["a"], data.feedback.strip()
    st["meddelanden"].append({"fran": "du", "text": text or "Gör om", "tid": datetime.now().isoformat(timespec="seconds")})
    minne.logga_oforstatt("gor_om", text, rubrik=a["rubrik"])
    if st.get("utkast"):
        tjanst.avbryt(st["utkast"])
    andring = await tolka_feedback(text)
    if andring.get("pris"):
        a["pris"] = andring["pris"]
    if andring.get("namn"):
        minne.spara_synonym(a["rubrik"], andring["namn"])
        a["rubrik"] = andring["namn"]
    atgarder = andring.get("atgarder", [])
    if "annan_bild" in atgarder and not a["kandidater"]:
        # Eget foto (eller bild ur minnet): be om ett nytt foto.
        a["fotos"], a["fran_minne"], a["ny_bild"] = [], False, True
        st.update(status="fragar", behover="foto", fraga="Ta ett nytt foto och skicka det.", utkast=None)
        bot(st, st["fraga"])
        return utan_interna(st)
    justering, _ = kvalitet.ny_justering([{"atgard": x} for x in atgarder or ["gor_om"]],
                                         st.get("justering", {}), bool(a["kandidater"]))
    # Pappas egen önskan ska synas tydligt: dubbelt steg (ca 25 %) mot kvalitetskontrollens 12 %.
    for nyckel, atgard in (("pris", "storre_pris"), ("produkt", "storre_produkt")):
        if atgard in atgarder:
            justering[nyckel] = justering.get(nyckel, 1.0) * kvalitet.STEG
    if "mindre_produkt" in atgarder:
        justering["produkt"] = justering.get("produkt", 1.0) / kvalitet.STEG
    if justering.get("ny_frilaggning"):
        kvalitet.ny_frilaggning([Path(f) for f in a["fotos"]])
    st["justering"] = justering
    a["omgang"] = a.get("omgang", 0) + 1
    st.update(status="arbetar", utkast=None, notiser=[])
    bot(st, "Jag gör om videon.")
    asyncio.create_task(gor_video(st, {k: v for k, v in justering.items() if not k.startswith("test_")}))
    return utan_interna(st)


ORD = {"storre_pris": ("större pris", "större prislapp", "priset större", "prislappen större", "bricka större"),
       "storre_produkt": ("större vara", "större produkt", "större bild", "varan större", "större burk"),
       "mindre_produkt": ("mindre vara", "mindre produkt", "mindre bild", "utanför", "klipps"),
       "annan_bild": ("annan bild", "ny bild", "annat foto", "nytt foto", "fel bild", "fel vara"),
       "gor_om_frilaggning": ("kant", "fransar", "hål", "frilägg", "bakgrund")}


async def tolka_feedback(text: str) -> dict:
    """{'atgarder': [...], 'pris': ..., 'namn': ...} ur pappas feedback. Ordlista först, sedan AI."""
    t = text.lower()
    atgarder = [k for k, ord_ in ORD.items() if any(o in t for o in ord_)]
    pris = tolka.tolka_pris(text) if any(o in t for o in ("pris", "kr", ":-", "för ")) else ""
    namn = ""
    for prefix in ("heter ", "namnet ska vara ", "namn: "):
        if prefix in t:
            namn = text[t.index(prefix) + len(prefix):].strip(" .")[:60]
    if not (atgarder or pris or namn) and text and igenkanning.tillganglig():
        d = await igenkanning.tolka_feedback(text)
        if d:
            atgarder = [x for x in d.get("atgarder", []) if x in kvalitet.ATGARDER]
            pris = tolka.snygga_pris(d.get("pris", "")) or pris
            namn = d.get("namn", "").strip() or namn
    return {"atgarder": atgarder, "pris": pris, "namn": namn}


# ---------- publicerade annonser ----------

VADERTYP = {"kall": "kall vara", "varm": "varm vara", "mys": "mysvara", "grill": "grillvara"}


def _post_ut(p: dict, visning: dict | None = None, vikter: dict | None = None) -> dict:
    utgar = tid(p["utgar"])
    fil = Path((p.get("kanaler", {}).get("skylt") or {}).get("fil") or "")
    v = (visning or {}).get(fil.name, {})
    vikt = (vikter or {}).get(fil.name, 1)
    return {"visning": v, "vikt": vikt, "vadertyp": VADERTYP.get(p.get("vadertyp") or "", ""),
            "vadertyp_kod": p.get("vadertyp") or "neutral", "vikt_val": int(p.get("vikt_val") or 1),
            "fast": p.get("typ") == "fast", "id": p["id"], "rubrik": p.get("rubrik", ""), "pris": p.get("pris", ""), "typ": p["typ"],
            "sammanfattning": tolka.sammanfattning(p.get("rubrik", ""), p.get("pris", ""), utgar),
            "slutar": oversatt.t("tills vidare") if tjanst.ar_tills_vidare(p) else tjanst.datum(utgar),
            "tills_vidare": tjanst.ar_tills_vidare(p), "extra": tjanst.extra_aktiv(p),
            "langd": int(p.get("langd") or v.get("sek") or 9), "langd_andras": p["id"] in _LANGD_PAGAR,
            "kan_andra_langd": bool(p.get("bilder")),
            "extra_till": tjanst.datum(tid(p["extra_till"])) if tjanst.extra_aktiv(p) else ""}


@router.get("")
async def lista():
    """Annonserna och hur länge/ofta var och en syns (sek per visning, gånger och sekunder per timme)."""
    try:
        v = await asyncio.to_thread(skyltlista.visning)
    except Exception:
        log.exception("Kunde inte räkna visningstid")
        v = {}
    poster = tjanst.lager.aktiva()
    vaderinfo, vikter = {}, {}
    try:
        L = vader.lage(vader.las_prognos())
        vikter = vader.vikter(poster, L)
        idag = L.idag
        vaderinfo = {"temp": round(idag.max_temp) if idag and idag.max_temp is not None else None,
                     "regn_timmar": idag.regn_timmar if idag else 0,
                     "regler": [oversatt.t(r) for r in L.regler], "typer": sorted(L.vikter),
                     "aktivt": skyltlista.viktat()}
    except Exception:
        log.exception("Kunde inte läsa vädret")
    return {"annonser": [_post_ut(p, v, vikter) for p in poster], "vader": vaderinfo}


def _aktiv(post_id: str) -> dict | None:
    p = tjanst.lager.hamta(post_id)
    return p if p and p.get("status") == "aktiv" else None


@router.get("/{post_id}/video")
async def video(post_id: str):
    p = _aktiv(post_id)
    if not p:
        return fel("Finns inte.", 404)
    # Appen visar den stående originalvideon (skyltens kopia är vriden för skärmkretsen).
    fil = Path(p["video"]) if Path(p["video"]).is_file() else Path((p.get("kanaler", {}).get("skylt") or {}).get("fil") or "")
    return FileResponse(fil if fil.is_file() else p["video"], media_type="video/mp4")


@router.get("/{post_id}/bild")
async def bild(post_id: str):
    p = _aktiv(post_id)
    if not p:
        return fel("Finns inte.", 404)
    return FileResponse(await asyncio.to_thread(tjanst.miniatyr, Path(p["video"])), media_type="image/jpeg")


@router.post("/{post_id}/ta-bort")
async def ta_bort(post_id: str):
    p = _aktiv(post_id)
    if not p:
        return fel("Redan borttagen.", 404)
    tjanst.avpublicera(p, "borttagen")
    return {"ok": True, "meddelande": f"{tjanst.rubrik_kort(p)} togs bort från skärmen"}


class Dagar(BaseModel):
    dagar: int


@router.post("/{post_id}/forlang")
async def forlang(post_id: str, data: Dagar):
    p = _aktiv(post_id)
    if not p or not 1 <= data.dagar <= 30:
        return fel("Går inte att förlänga.", 400)
    p = tjanst.forlang(p, data.dagar)
    return {"ok": True, "meddelande": f"Visas nu till {tjanst.datum(tid(p['utgar']))}", "annons": _post_ut(p)}


class Visningar(BaseModel):
    vikt: int              # 1 normalt, 2 oftare, 3 mycket ofta


@router.post("/{post_id}/visningar")
async def visningar(post_id: str, data: Visningar):
    p = _aktiv(post_id)
    if not p or data.vikt not in (1, 2, 3):
        return fel("Välj normalt, oftare eller mycket ofta.", 400)
    p = tjanst.satt_visningar(p, data.vikt)
    text = {1: "Visas som vanligt", 2: "Visas oftare", 3: "Visas mycket ofta"}[data.vikt]
    return {"ok": True, "meddelande": oversatt.t(text), "annons": _post_ut(p)}


_LANGD_PAGAR: dict[str, int] = {}      # annonser som renderas om med ny visningstid just nu


class Langd(BaseModel):
    sekunder: int


@router.post("/{post_id}/langd")
async def langd(post_id: str, data: Langd):
    """Egen visningstid i sekunder (6–30, standard 9). Annonsen renderas om i bakgrunden (ungefär en minut);
    den gamla videon visas tills den nya är klar."""
    from video.animation import MAX_LANGD, MIN_LANGD
    p = _aktiv(post_id)
    if not p:
        return fel("Finns inte.", 404)
    if not MIN_LANGD <= data.sekunder <= MAX_LANGD:
        return fel(oversatt.t(f"Välj mellan {MIN_LANGD} och {MAX_LANGD} sekunder."), 400)
    if not p.get("bilder"):
        return fel(oversatt.t("Den här videon kan inte göras om. Gör en ny annons i stället."), 409)
    if post_id in _LANGD_PAGAR:
        return {"ok": True, "meddelande": oversatt.t("Håller redan på att ändra visningstiden …")}
    _LANGD_PAGAR[post_id] = data.sekunder

    async def jobb():
        try:
            await tjanst.byt_langd(p, data.sekunder)
            log.info("Ny visningstid %s s: %s", data.sekunder, p.get("rubrik"))
        except Exception:
            log.exception("Ny visningstid misslyckades")
        finally:
            _LANGD_PAGAR.pop(post_id, None)
    asyncio.create_task(jobb())
    return {"ok": True, "meddelande": oversatt.t(f"Gör om videon till {data.sekunder} sekunder. Det tar ungefär en minut."),
            "annons": _post_ut(p)}


@router.get("/{post_id}/visningar")
async def visningar_val(post_id: str):
    """Ungefär hur många gånger i timmen annonsen visas med varje val (appen visar det i valet)."""
    p = _aktiv(post_id)
    if not p:
        return fel("Finns inte.", 404)
    fil = Path((p.get("kanaler", {}).get("skylt") or {}).get("fil") or "").name
    per = await asyncio.to_thread(skyltlista.per_timme_med_vikt, fil)
    return {"vald": int(p.get("vikt_val") or 1), "per_timme": {str(k): v for k, v in per.items()}}


class Vadertyp(BaseModel):
    typ: str               # kall | varm | mys | grill | neutral


@router.post("/{post_id}/vader")
async def satt_vader(post_id: str, data: Vadertyp):
    """Pappa väljer själv vid vilket väder annonsen visas oftare (AI:ns gissning skrivs över)."""
    p = _aktiv(post_id)
    if not p or data.typ not in ("kall", "varm", "mys", "grill", "neutral"):
        return fel("Går inte.", 400)
    p["vadertyp"] = data.typ
    p["vadertyp_av"] = "pappa"
    tjanst.lager.spara(p)
    tjanst.uppdatera_vikter()
    text = {"kall": "Visas oftare när det är varmt", "varm": "Visas oftare när det är kallt",
            "mys": "Visas oftare när det regnar eller snöar", "grill": "Visas oftare när det är grillväder",
            "neutral": "Visas lika ofta oavsett väder"}[data.typ]
    return {"ok": True, "meddelande": oversatt.t(text), "annons": _post_ut(p)}


@router.post("/{post_id}/tills-vidare")
async def tills_vidare(post_id: str):
    p = _aktiv(post_id)
    if not p:
        return fel("Finns inte.", 404)
    p = tjanst.tills_vidare(p)
    return {"ok": True, "meddelande": oversatt.t("Visas nu tills vidare"), "annons": _post_ut(p)}


@router.post("/{post_id}/extra")
async def extra(post_id: str, data: Dagar):
    p = _aktiv(post_id)
    if not p or data.dagar not in (1, 3, 7):
        return fel("Välj i dag, 3 dagar eller en vecka.", 400)
    p = tjanst.visa_extra(p, data.dagar)
    return {"ok": True, "meddelande": f"Visas oftare till {tjanst.datum(tid(p['extra_till']))}", "annons": _post_ut(p)}
