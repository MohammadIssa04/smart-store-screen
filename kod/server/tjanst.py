"""Annonsflödet utan Telegram: samma logik för Telegram-boten och appen (api/annonser.py).

Ett "ärende" är en annons på väg: text och foton in -> tolkning -> bilder -> video (med
Geminis kvalitetskontroll) -> förhandsvisning -> publicering. Boten och appen frågar själva
användaren när något saknas; nasta_steg() säger vad som behövs.

Publicerade annonser ligger i lagret (lager.py) och på skylten (kanaler/). Härifrån tas de
bort (till arkivet), förlängs, eller visas extra ofta en tid (vikt 3 i skyltens spellista).
"""
from __future__ import annotations

import asyncio
import fcntl
import logging
import re
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageOps

import bildsok
import igenkanning
import konfig
import kvalitet
import minne
import tolka
import uppstallning
import vader
from kanaler import KANALER
from lager import Lager, tid
from video import overgangar
from video.animation import MAX_PRODUKTER
from video.animation import rendera as skapa_video

log = logging.getLogger("butiksbot.tjanst")

lager = Lager(konfig.LAGER_FIL)

VECKODAGAR = ["mån", "tis", "ons", "tors", "fre", "lör", "sön"]
EXTRA_VIKT = 3
RENDER_LAS = konfig.DATA_DIR / "render.las"


# ---------- text till användaren ----------

def datum(d: datetime) -> str:
    return f"{VECKODAGAR[d.weekday()]} {d.day}/{d.month} kl {d:%H:%M}"


def rubrik_kort(post: dict) -> str:
    return " – ".join(x for x in (post.get("rubrik"), post.get("pris")) if x) or "erbjudande"


def beskriv(post: dict) -> str:
    """'Erbjudande: Bananer, 10 kr/kg, visas t.o.m. fredag (slutar fre 14/11 kl 21:00)'."""
    utgar = tid(post["utgar"])
    typ = "⭐ Dagens fynd" if post["typ"] == "fynd" else "Erbjudande"
    return (f"{typ}: {tolka.sammanfattning(post.get('rubrik', ''), post.get('pris', ''), utgar)}\n"
            f"(slutar {datum(utgar)})")


# ---------- ärenden ----------

def nytt_arende(typ: str = "erbjudande", rubrik: str = "", pris: str = "",
                dagar: int = konfig.STANDARD_DAGAR, text: str = "") -> dict:
    uid = secrets.token_hex(3)
    mapp = konfig.UTKAST_DIR / f"{datetime.now():%Y%m%d-%H%M%S}_{uid}"
    mapp.mkdir(parents=True, exist_ok=True)
    return {"id": uid, "mapp": str(mapp), "typ": typ, "rubrik": rubrik, "pris": pris,
            "dagar": dagar, "text": text, "fotos": [], "antal": 1, "kandidater": [], "nr": 0,
            "steg": "", "tid": datetime.now().timestamp()}


def fran_text(a: dict, text: str) -> None:
    """Fyll i det som texten säger (rubrik, pris, fynd, dagar, antal smaker) utan att skriva över."""
    t = tolka.tolka(text)
    a["text"] = (a["text"] + " " + text).strip()
    if t.typ == "fynd":
        a["typ"] = "fynd"
    if t.dagar_angivet:
        a["dagar"] = t.dagar
        a["dagar_angivet"] = True
    if t.antal > 1:
        a["antal"] = t.antal
    a["rubrik"] = a["rubrik"] or minne.synonym(t.rubrik)
    a["pris"] = a["pris"] or t.pris


def oklar(text: str) -> bool:
    """Reglerna hittade inget namn, eller det blev konstigt (siffror kvar utan pris, väldigt långt)."""
    t = tolka.tolka(text)
    return (not t.rubrik or (not t.pris and bool(re.search(r"\d", t.rubrik)))
            or len(t.rubrik.split()) > 5)


async def tolka_text(a: dict, text: str) -> None:
    """Reglerna först. Är texten oklar och AI:n finns: låt AI:n tolka, med pappas senaste
    godkända meddelanden som exempel. Allt oklart loggas för genomgång."""
    if oklar(text):
        d = await igenkanning.tolka_text(text, minne.senaste_godkanda(8))
        minne.logga_oforstatt("oklar_text", text, ai=d)
        if d:
            a["text"] = (a["text"] + " " + text).strip()
            a["rubrik"] = a["rubrik"] or minne.synonym(d["namn"].strip())
            a["pris"] = a["pris"] or tolka.snygga_pris(d.get("pris", ""))
            if d.get("dagar"):
                a["dagar"], a["dagar_angivet"] = max(1, min(konfig.MAX_DAGAR, d["dagar"])), True
            if d.get("fynd"):
                a["typ"] = "fynd"
            return
        a["oklar"] = True        # varken reglerna eller AI:n förstod: fråga hellre än gissa
    fore = a["rubrik"]
    fran_text(a, text)
    if a["rubrik"] and a["rubrik"] != fore and minne.synonym(a["rubrik"]) == a["rubrik"]:
        a["rubrik"] = await ratta_namn(a["rubrik"])     # stavfel (pappas egna rättningar i minnet går före)


async def kanna_igen_fotos(a: dict) -> bool:
    """Namn (och ev. pris) från fotona om de saknas. False om varan inte kändes igen."""
    if (a["rubrik"] and a["pris"]) or not igenkanning.tillganglig() or not a["fotos"]:
        return True
    svar = await igenkanning.kanna_igen([Path(f) for f in a["fotos"]])
    if svar:
        a["rubrik"] = a["rubrik"] or minne.synonym(svar["namn"])
        a["pris"] = a["pris"] or tolka.snygga_pris(svar["pris"])
        a["vartyp"] = svar.get("vartyp")
        anpassa_foto(a, svar)
        return True
    if not a["rubrik"]:
        minne.logga_oforstatt("ej_igenkand", a["text"], fotos=a["fotos"])
    return False


def anpassa_foto(a: dict, svar: dict) -> None:
    """Skärmdump (t.ex. av ett Facebook-inlägg): beskär till själva fotot. Varan fyller hela fotot
    (en låda potatis): visa fotot i ram, en gång – den går inte att klippa ut och ska inte tredubblas."""
    if len(a["fotos"]) != 1:
        return
    foto = Path(a["fotos"][0])
    r = svar.get("ruta") or {}
    if svar.get("skarmdump") and all(isinstance(r.get(k), int) for k in ("x0", "y0", "x1", "y1")):
        try:
            with Image.open(foto) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                b, h = im.size
                ruta = (max(0, r["x0"]) * b // 1000, max(0, r["y0"]) * h // 1000,
                        min(1000, r["x1"]) * b // 1000, min(1000, r["y1"]) * h // 1000)
                if ruta[2] - ruta[0] > b * 0.3 and ruta[3] - ruta[1] > h * 0.2:
                    foto.rename(foto.with_name(foto.name + ".skarmdump"))      # originalet sparas
                    im.crop(ruta).save(foto, "JPEG", quality=95)
                    log.info("Skärmdump beskuren till fotot: %s", ruta)
        except Exception:
            log.exception("Kunde inte beskära skärmdumpen")
    a["fyller"] = bool(svar.get("fyller_bilden"))
    if a["fyller"] and a["rubrik"]:
        # En låda/hög går inte att göra snygg reklam av: visa bara varan (t.ex. potatis). Först
        # produktminnet, sedan en ren bild från nätet. Pappas foto (i ram) bara om inget hittas.
        a["eget_foto"], a["fotos"] = str(foto), []
        if not minne.hitta_produkt(a["rubrik"]):
            a["webb"] = True
        log.info("Fotot visar en låda/hög med %s: letar en bild på bara varan", a["rubrik"])


def tillbaka_till_eget_foto(a: dict) -> bool:
    """Inget på nätet: använd pappas foto av lådan ändå (i ram, en gång)."""
    if a["fotos"] or not a.get("eget_foto"):
        return False
    a["fotos"], a["webb"], a["fyller"] = [a.pop("eget_foto")], False, True
    return True


def valj_kandidat(a: dict) -> bool:
    """En produkt från nätet: använd bild nr a['nr'] av de utvalda sökbilderna."""
    if a["nr"] < len(a["kandidater"]):
        a["fotos"] = [a["kandidater"][a["nr"]]]
        return True
    return False


def fran_minnet(a: dict) -> str | None:
    """Varan har publicerats förut: återanvänd samma (redan frilagda) bild. Ger ett meddelande."""
    if a["fotos"] or a.get("webb") or a.get("ny_bild"):
        return None
    sparad = minne.hitta_produkt(a["rubrik"])
    if not sparad or len(sparad["bilder"]) < a["antal"]:
        return None
    a["fotos"] = sparad["bilder"][:MAX_PRODUKTER]
    a["fran_minne"] = True
    a["fyller"] = False
    a["vartyp"] = a.get("vartyp") or sparad.get("vartyp")
    a["antal"] = max(a["antal"], len(a["fotos"]))
    return f"Jag använder bilden på {sparad['namn']} från förra gången."


async def leta_bilder(a: dict, lage=None) -> str | None:
    """Bilder från nätet. Ger ett meddelande om det inte räckte (då behövs egna foton).
    lage(text): lägesrapporter under sökningen ('Söker bilder på …', 'Klipper ut bild 1 av 3 …')."""
    # Appen låter pappa välja bild själv (a["valja"]): då tas fler alternativ fram.
    valja = bool(a.get("valja")) and a["antal"] == 1
    info: dict = {}
    hittade = [str(p) for p in await bildsok.hamta_bilder(a["rubrik"], Path(a["mapp"]), a["antal"], lage=lage,
                                                           onskat=VALJ_ANTAL if valja else None,
                                                           bara_kandidater=valja, info=info)]
    a["farskvara"] = bool(info.get("farskvara"))
    if a["antal"] > 1:
        a["fotos"], a["kandidater"] = (hittade if len(hittade) >= 2 else []), []
        if not a["fotos"]:
            return (f"Jag hittade inte tillräckligt snygga bilder på olika smaker av {a['rubrik']}. "
                    "Ta ett foto per smak och skicka dem.")
        if len(hittade) < a["antal"]:
            return f"Jag hittade bara {len(hittade)} snygga bilder på olika smaker. Jag gör videon med dem."
        return None
    a["kandidater"], a["nr"] = hittade, 0
    if valja and len(hittade) >= 2:
        a["valj_bild"] = True                # pappa väljer i appen (nasta_steg frågar); bara den valda klipps ut
        return None
    if valja and hittade and not await bildsok.forbered(a["rubrik"], Path(hittade[0]), a["farskvara"]):
        a["kandidater"] = []                 # den enda bilden gick inte att klippa ut snyggt
    if not valj_kandidat(a):
        if tillbaka_till_eget_foto(a):
            return f"Jag hittade ingen snygg bild på bara {a['rubrik']}, så jag visar ditt foto i en ram."
        return f"Jag hittade ingen tillräckligt snygg bild på {a['rubrik']}. Ta ett eget foto och skicka det."
    a["fyller"] = False                      # nätbilden visar bara varan: vanlig uppställning
    return None


VALJ_ANTAL = 4          # alternativ att välja mellan i appen (varje friläggning tar ca 15-20 s på Pi:n)


async def valj_bild(a: dict, nr: int) -> str:
    """Pappa valde bild nr (0-baserat) i appen. Valet gäller alltid (ingen ny fråga): bilden klipps ut,
    och går det inte visas den i en ram. 'ok' | 'ram' | 'finns_inte'."""
    if not a.get("valj_bild") or not 0 <= nr < len(a["kandidater"]):
        return "finns_inte"
    vald = Path(a["kandidater"][nr])
    from video.frilagg import frilagg
    ok = await asyncio.to_thread(frilagg, vald) is not None
    a["nr"], a["valj_bild"], a["fyller"] = nr, False, not ok
    valj_kandidat(a)
    return "ok" if ok else "ram"


async def ratta_namn(namn: str) -> str:
    """Rättar stavfel i varans namn ("apelsint" -> "Apelsiner"). Märken och rätt stavade namn lämnas.
    Utan AI, eller om svaret ser konstigt ut: namnet som det var."""
    if not namn or not igenkanning.gemini_finns():
        return namn
    try:
        d = await igenkanning.fraga_gemini([{"type": "text", "text": (
            f"En svensk livsmedelsbutik skriver varans namn så här: \"{namn}\". Rätta bara stavfel och skriv "
            "namnet som det ska stå på en skylt i butiken: svenska, stor första bokstav, vanlig pluralform för "
            "frukt och grönt (t.ex. \"apelsint\" -> \"Apelsiner\", \"banan\" -> \"Bananer\"). Märkesnamn "
            "(Red Bull, Monster, Coca-Cola, Pepsi …) skrivs som märket stavas. Är namnet redan rätt: svara med "
            "samma namn. Lägg aldrig till ord som inte står där.")}],
            {"type": "object", "properties": {"namn": {"type": "string"}}, "required": ["namn"]})
    except Exception:
        return namn
    ny = ((d or {}).get("namn") or "").strip()
    if not ny or len(ny) > max(40, 2 * len(namn)) or len(ny.split()) > len(namn.split()) + 1:
        return namn
    if ny != namn:
        log.info("Rättade namnet: %r -> %r", namn, ny)
    return ny


async def fler_bilder(a: dict, lage=None) -> int:
    """'Fler bilder': söker nya alternativ (utan de som redan visats) och lägger dem sist. Ger antalet nya."""
    nya = await bildsok.hamta_bilder(a["rubrik"], Path(a["mapp"]), 1, forrad=False, lage=lage,
                                     onskat=VALJ_ANTAL, utom=[Path(k) for k in a["kandidater"] + a.get("daliga", [])],
                                     bara_kandidater=True)
    nya = [str(p) for p in nya if str(p) not in a["kandidater"]]
    a["kandidater"].extend(nya)
    return len(nya)


@dataclass
class Steg:
    """Vad ärendet behöver härnäst: 'namn', 'foto', 'fler_foton', 'pris', 'leta_bilder', 'valj_bild' (bara appen)
    eller 'video'."""
    behover: str
    fraga: str = ""


def nasta_steg(a: dict) -> Steg:
    if not a["rubrik"]:
        minne.logga_oforstatt("namn_saknas", a["text"])
        return Steg("namn", "Vad heter varan?")
    if not a["fotos"] and not a["pris"]:
        # Fråga priset först (går fort), sedan letar den bild – så slipper pappa vänta på bildsökningen
        # för att sedan få en fråga.
        return Steg("pris", f"Vilket pris har {a['rubrik']}? T.ex. 19, 10/kg, 2 för 30 eller 15 + pant.")
    if not a["fotos"] and a.get("valj_bild") and a["kandidater"]:
        return Steg("valj_bild", f"Vilken bild på {a['rubrik']} är bäst? Tryck på den.")
    if not a["fotos"]:
        # Inget foto: leta på nätet direkt (förrådet först, sedan sökning). Ett eget foto går alltid före.
        if a.get("webb") or (igenkanning.tillganglig() and not a.get("ny_bild")):
            return Steg("leta_bilder")
        if a["antal"] > 1:
            return Steg("foto", f"Ta {a['antal']} foton på {a['rubrik']}, ett per smak, och skicka dem.")
        return Steg("foto", f"Ta ett foto på {a['rubrik']} och skicka det.")
    if len(a["fotos"]) < a["antal"] and not a.get("webb") and not a.get("racker"):
        return Steg("fler_foton", f"Tack! Skicka {a['antal'] - len(a['fotos'])} foto till (ett per smak).")
    if not a["pris"]:
        minne.logga_oforstatt("pris_saknas", a["text"], rubrik=a["rubrik"])
        return Steg("pris", f"Vilket pris har {a['rubrik']}? T.ex. 19, 10/kg, 2 för 30 eller 15 + pant.")
    return Steg("video")


# ---------- video ----------

class _RenderLas:
    """Bara en rendering åt gången på Pi:n, även mellan boten och API:t (fillås)."""

    async def __aenter__(self):
        RENDER_LAS.parent.mkdir(parents=True, exist_ok=True)
        self.fil = open(RENDER_LAS, "w")
        await asyncio.to_thread(fcntl.flock, self.fil, fcntl.LOCK_EX)
        return self

    async def __aexit__(self, *_):
        fcntl.flock(self.fil, fcntl.LOCK_UN)
        self.fil.close()


@dataclass
class Utkast:
    post: dict
    arende: dict
    notiser: list[str] = field(default_factory=list)


async def gor_video(a: dict, status=None, justering: dict | None = None) -> Utkast:
    """Renderar videon (med kvalitetskontroll) och ger en opublicerad post. status(text) får lägesrapporter.
    justering: önskemål från 'Gör om' (t.ex. {'pris': 1.12} = större prisbricka)."""
    upp = uppstallning.bestam(a["rubrik"], a["pris"], len(a["fotos"]), 1, a.get("vartyp"))
    if a.get("fyller") and len(a["fotos"]) == 1:
        upp = uppstallning.Uppstallning(1, "enkel", "varan fyller fotot (låda/hög): fotot i ram")
    log.info("Uppställning: %d exemplar, %s (%s)", upp.exemplar, upp.stil, upp.skal)
    overgang = overgangar.valj([p.get("overgang") for p in lager.aktiva()], minne.senaste_overgang())
    minne.spara_overgang(overgang)
    # Layout, färgton, prisbricka och entré varieras också, så att annonserna inte ser likadana ut.
    from video.animation import ny_variant
    variant = ny_variant(minne.senaste_variant())
    minne.spara_variant(variant)
    test = a.get("test", {})              # bara testa_kvalitet.py: medvetet dåliga videor
    byten = {"bild": 0, "gor_om": 0}

    async def rendera(just: dict, forsok: int) -> dict:
        nonlocal overgang, variant
        while byten["bild"] < just.get("annan_bild", 0):
            byten["bild"] += 1
            if a["nr"] + 1 < len(a["kandidater"]):
                a["nr"] += 1
                valj_kandidat(a)
        if byten["gor_om"] < just.get("gor_om", 0):
            byten["gor_om"] = just["gor_om"]
            overgang = overgangar.valj([p.get("overgang") for p in lager.aktiva()], overgang)
            variant = ny_variant(variant)          # "Gör om": ny layout också
            minne.spara_variant(variant)
        pris = test.get("pris_forsta", a["pris"]) if forsok == 0 else a["pris"]
        ut = Path(a["mapp"]) / f"video{a['nr']}_{a.get('omgang', 0)}_{forsok}.mp4"
        async with _RenderLas():
            return await skapa_video([Path(f) for f in a["fotos"]], a["rubrik"], pris, a["typ"] == "fynd", ut,
                                     upp.exemplar, upp.stil, overgang, justering=just, variant=variant,
                                     langd=a.get("sekunder"))

    start = {**dict(test.get("justering", {})), **(justering or {})}
    if a.get("fyller") and len(a["fotos"]) == 1:
        start.setdefault("modeller", ())        # ingen friläggning: fotot visas i ram med rundade hörn
    forvantat = {"namn": a["rubrik"], "pris": a["pris"], "text": a["text"], "exemplar": upp.exemplar,
                 "stil": upp.skal, "fotos": [Path(f) for f in a["fotos"]],
                 "kalla": "nätet" if a.get("webb") else ("tidigare publicerad bild" if a.get("fran_minne")
                                                         else "ägarens eget foto")}
    if igenkanning.gemini_finns():
        k = await kvalitet.gor_och_kontrollera(rendera, forvantat, kan_byta_bild=bool(a["kandidater"]),
                                              justering=start, status=status)
        res, notiser = k.res, list(k.notiser)
    else:
        res, notiser = await rendera(start, 0), []
    if res["sma"] and not a.get("webb"):
        notiser.insert(0, "Bilden är lite liten, skicka gärna en större om du har." if len(a["fotos"]) == 1
                       else f"Bild {', '.join(str(i + 1) for i in res['sma'])} är lite liten, skicka gärna en större.")
    utgar = tolka.berakna_utgang(a["typ"], a["dagar"], datetime.now(), a.get("dagar_angivet", False))
    post = {
        "id": f"{a['id']}{a['nr'] or ''}{a.get('omgang', 0) or ''}", "typ": a["typ"], "text": a["text"],
        "rubrik": a["rubrik"], "pris": a["pris"], "dagar": a["dagar"],
        "utgar": utgar.isoformat(timespec="minutes"), "skapad": datetime.now().isoformat(timespec="seconds"),
        "mapp": a["mapp"], "video": str(res["video"]),
        "bildkalla": "natet" if a.get("webb") else "foto", "bilder": a["fotos"],
        "kanaler": {}, "status": "utkast", "overgang": list(res["overgang"]),
        # Det som behövs för att rendera om annonsen senare (t.ex. ny visningstid):
        "variant": res.get("variant"), "langd": res.get("langd"), "exemplar": upp.exemplar, "stil": upp.stil,
        "fyller": bool(a.get("fyller")),
        "vadertyp": await vader.klassa(a["rubrik"]),
    }
    # Skyltens liggande kopia görs redan nu i bakgrunden (ca 35 s, lägsta prioritet) medan pappa tittar på
    # förhandsvisningen – då kommer videon upp på skärmen direkt när han trycker Publicera.
    import skyltvrid
    threading.Thread(target=skyltvrid.forvrid, args=(Path(post["video"]),), daemon=True).start()
    return Utkast(post, a, list(dict.fromkeys(notiser)))


def miniatyr(video: Path) -> Path:
    """En bildruta (när allt är på plats) att visa i appen."""
    import subprocess
    ut = video.with_suffix(".jpg")
    if not ut.exists():
        subprocess.run([*konfig.lag_prioritet_prefix(), "ffmpeg", "-v", "error", "-y", "-ss", "5.2", "-i", str(video),
                        "-frames:v", "1", "-vf", "scale=540:-2", "-q:v", "4", str(ut)], timeout=60)
    return ut


# ---------- publicera, ta bort, förläng, visa extra ----------

def uppdatera_vikter() -> None:
    """Hur ofta varje annons visas (väder och 'visa extra'). Fel här får aldrig stoppa något."""
    try:
        vader.skriv_vikter(lager.aktiva(), vader.lage(vader.las_prognos()))
    except Exception:
        log.exception("Kunde inte räkna vikter")


def publicera(u: Utkast, av: str = "") -> dict:
    post, a = u.post, u.arende
    for k in KANALER:
        post["kanaler"][k.namn] = k.publicera(post, Path(post["video"]))
    post["status"] = "aktiv"
    post["publicerad"] = datetime.now().isoformat(timespec="seconds")
    post["av"] = av
    lager.spara(post)
    uppdatera_vikter()
    try:                                    # lärande: kom ihåg varan och hur texten tolkades
        minne.spara_produkt(post["rubrik"], post["bilder"], a.get("vartyp"))
        minne.spara_godkand(a["text"], {"namn": post["rubrik"], "pris": post["pris"],
                                        "dagar": post["dagar"] if a.get("dagar_angivet") else 0,
                                        "fynd": post["typ"] == "fynd"})
    except Exception:
        log.exception("Kunde inte spara i minnet")
    return post


def avbryt(u: Utkast) -> None:
    u.post["status"] = "avbruten"
    lager.spara(u.post)
    minne.logga_oforstatt("avbruten", u.arende["text"], rubrik=u.post["rubrik"], pris=u.post["pris"])


def avpublicera(post: dict, status: str) -> None:
    """Tar bort annonsen från skylten (filen flyttas till arkivet, raderas aldrig)."""
    for k in KANALER:
        try:
            k.ta_bort(post)
        except Exception:
            log.exception("Kunde inte ta bort från %s", k.namn)
    post["status"] = status
    post["avslutad"] = datetime.now().isoformat(timespec="seconds")
    lager.spara(post)
    uppdatera_vikter()


def forlang(post: dict, dagar: int) -> dict:
    """Visas `dagar` dagar till (räknat från nuvarande slut, eller från i dag om den redan gått ut i kväll)."""
    gammal = tid(post["utgar"])
    if gammal.year >= TILLS_VIDARE.year:          # från "tills vidare" till ett slutdatum: räkna från i dag
        gammal = datetime.now().replace(hour=konfig.STANGNING_TIMME, minute=0, second=0, microsecond=0)
    bas = max(gammal, datetime.now().replace(hour=konfig.STANGNING_TIMME, minute=0, second=0, microsecond=0))
    ny = bas + timedelta(days=dagar)
    for k in KANALER:                      # skylt-play läser slutet ur filnamnet: byt namn
        if hasattr(k, "nytt_slut"):
            post["kanaler"][k.namn] = k.nytt_slut(post, ny)
    post["utgar"] = ny.isoformat(timespec="minutes")
    lager.spara(post)
    uppdatera_vikter()
    return post


TILLS_VIDARE = datetime(2099, 12, 31, 21, 0)


def tills_vidare(post: dict) -> dict:
    """Visas tills någon tar bort den (slutet sätts långt fram, även i filnamnet som skylt-play läser)."""
    for k in KANALER:
        if hasattr(k, "nytt_slut"):
            post["kanaler"][k.namn] = k.nytt_slut(post, TILLS_VIDARE)
    post["utgar"] = TILLS_VIDARE.isoformat(timespec="minutes")
    lager.spara(post)
    uppdatera_vikter()
    return post


def satt_visningar(post: dict, vikt: int) -> dict:
    """Pappas val: 1 = normalt, 2 = oftare, 3 = mycket ofta (gäller tills han ändrar)."""
    post["vikt_val"] = max(1, min(3, int(vikt)))
    lager.spara(post)
    uppdatera_vikter()
    return post


async def byt_langd(post: dict, sekunder: float) -> dict:
    """Ny visningstid för en publicerad annons: renderar om samma annons (samma bilder, layout och övergång)
    i den nya längden och byter filen på skylten. Den gamla filen arkiveras. Tar ungefär en minut."""
    from video.animation import LANGD, MAX_LANGD, MIN_LANGD
    sek = max(MIN_LANGD, min(MAX_LANGD, round(float(sekunder))))
    fotos = [Path(f) for f in post.get("bilder", [])]
    if not fotos or not all(f.is_file() for f in fotos):
        raise FileNotFoundError("bilderna till annonsen finns inte kvar")
    mapp = Path(post.get("mapp") or konfig.UTKAST_DIR / post["id"])
    mapp.mkdir(parents=True, exist_ok=True)
    ut = mapp / f"langd{sek}_{datetime.now():%H%M%S}.mp4"
    if post.get("exemplar"):
        exemplar, stil = post["exemplar"], post.get("stil", "rad")
    else:                                       # äldre annons: räkna ut uppställningen igen
        upp = uppstallning.bestam(post["rubrik"], post["pris"], len(fotos), 1, None)
        exemplar, stil = upp.exemplar, upp.stil
    just = {"modeller": ()} if post.get("fyller") and len(fotos) == 1 else {}
    async with _RenderLas():
        res = await skapa_video(fotos, post["rubrik"], post["pris"], post["typ"] == "fynd", ut, exemplar, stil,
                                tuple(post.get("overgang") or ("fade", "fade")), justering=just,
                                variant=post.get("variant"), langd=sek)
    import skyltvrid
    for k in KANALER:
        if hasattr(k, "byt_video"):
            post["kanaler"][k.namn] = k.byt_video(post, res["video"])
    post["video"] = str(res["video"])           # appen visar den stående originalvideon
    post["langd"] = sek
    post["variant"] = res.get("variant")
    lager.spara(post)
    uppdatera_vikter()
    return post


def ar_tills_vidare(post: dict) -> bool:
    return tid(post["utgar"]).year >= TILLS_VIDARE.year


def visa_extra(post: dict, dagar: int) -> dict:
    """Visas oftare (vikt EXTRA_VIKT) till stängning om `dagar` dagar (1 = i dag)."""
    slut = datetime.now().replace(hour=konfig.STANGNING_TIMME, minute=0, second=0, microsecond=0) \
        + timedelta(days=max(1, dagar) - 1)
    post["extra_till"] = slut.isoformat(timespec="minutes")
    lager.spara(post)
    uppdatera_vikter()
    return post


def extra_aktiv(post: dict) -> bool:
    return bool(post.get("extra_till")) and tid(post["extra_till"]) > datetime.now()
