"""AI i boten: känner igen varan på foton, läser av priser, betygsätter nätbilder,
kontrollerar friläggningar och tolkar oklar text.

GEMINI_API_KEY: Google Gemini (gratisnivån räcker).
Utan nyckel är AI avstängd: boten frågar i stället vad varan heter."""
from __future__ import annotations

import asyncio
import base64
import json
import time
import logging
import os
import subprocess
from pathlib import Path

import konfig
import httpx

log = logging.getLogger("butiksbot.igenkanning")

# Gemini: snabb Flash-modell som ingår i gratisnivån; Flash-Lite som reserv när
# gratiskvoten för den första är slut (429) eller modellen inte finns.
GEMINI_MODELL = os.environ.get("GEMINI_MODELL", "gemini-3.8-flash")
# Reserver i tur och ordning (kommaseparerat). Varje modell har en egen gratiskvot, så när en är slut
# eller överbelastad tar nästa vid.
GEMINI_RESERVER = [m.strip() for m in os.environ.get(
    "GEMINI_RESERV", "gemini-3.5-flash-lite,gemini-3.7-flash,gemini-3.1-flash-lite,gemini-3.6-flash").split(",")
    if m.strip()]
GEMINI_RESERV = GEMINI_RESERVER[0] if GEMINI_RESERVER else GEMINI_MODELL
_vilar: dict[str, float] = {}          # modell -> tid då den får provas igen (kvoten slut eller saknas)
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
GEMINI_REVISION = "2026-05-20"

SCHEMA = {
    "type": "object",
    "properties": {
        "hittad": {"type": "boolean"},
        "namn": {"type": "string"},
        "pris": {"type": "string"},
        "vartyp": {"type": "string", "enum": ["lösvikt", "klase", "förpackning", "dryck", "annat"]},
        "skarmdump": {"type": "boolean"},
        "ruta": {"type": "object", "properties": {
            "x0": {"type": "integer"}, "y0": {"type": "integer"}, "x1": {"type": "integer"}, "y1": {"type": "integer"}},
            "required": ["x0", "y0", "x1", "y1"], "additionalProperties": False},
        "fyller_bilden": {"type": "boolean"},
    },
    "required": ["hittad", "namn", "pris", "vartyp", "skarmdump", "ruta", "fyller_bilden"],
    "additionalProperties": False,
}

PROMPT = (
    "Fotot är taget i en liten svensk livsmedelsbutik. Bilden ska bli en reklamvideo "
    "för butikens TV-skylt.\n\n"
    "namn: varans namn som det ska stå på skylten, på svenska, kort (högst 4 ord). "
    "Ta med märke och sort när de syns, t.ex. \"Monster Energy Ultra\", \"Coca-Cola Zero 1,5 l\", "
    "\"Bananer\", \"Ruby Extra\".\n"
    "pris: bara om ett pris syns tydligt i bilden (prislapp, skylt), skrivet som "
    "\"19 kr\" eller \"2 för 30 kr\". Annars tom sträng. Gissa aldrig ett pris.\n"
    "hittad: false om ingen vara går att känna igen; namn är då tom sträng.\n"
    "vartyp: \"lösvikt\" för styckfrukt och grönsaker som säljs styckvis eller per kilo (äpplen, "
    "citroner, lök), \"klase\" för klasar och knippen (bananer, vindruvor, örter), \"förpackning\" för "
    "påsar, burkar, flaskor med mat, \"dryck\" för drickburkar och flaskor, annars \"annat\".\n"
    "skarmdump: true om bilden är en skärmdump från en telefon (statusrad, appens knappar, Facebook-"
    "inlägg, text runt ett foto) i stället för ett vanligt foto.\n"
    "ruta: var själva fotot av varan finns i bilden, i tusendelar (0-1000) av bredd och höjd: x0,y0 = "
    "övre vänstra hörnet, x1,y1 = nedre högra. Utan statusrad, knappar, text och tummar. Ligger en ikon ovanpå fotot i ett hörn (ljud av/på, play): dra in rutan så att ikonen hamnar utanför. För ett vanligt "
    "foto: 0,0,1000,1000.\n"
    "fyller_bilden: true om varan fyller hela fotot som en hög eller låda (t.ex. en back full med potatis) "
    "så att ingen enskild vara går att klippa ut; false om en eller några varor står fritt mot en bakgrund."
)

def _nyckel(namn: str) -> str:
    return os.environ.get(namn, "").strip()


def leverantor() -> str | None:
    """'gemini' eller None (ingen nyckel)."""
    return "gemini" if _nyckel("GEMINI_API_KEY") else None


def tillganglig() -> bool:
    return leverantor() is not None


def _forminska(foto: Path, max_px: int = 1280) -> bytes | None:
    """JPEG med högst max_px bredd: snabbare uppladdning, långt under API:ts bildgräns."""
    ut = foto.with_name(f"{foto.name}_ai{max_px}.jpg")
    try:
        subprocess.run([*konfig.lag_prioritet_prefix(), "ffmpeg", "-v", "error", "-y", "-i", str(foto), "-frames:v", "1",
                        "-vf", f"scale='min({max_px},iw)':-2", "-q:v", "3", str(ut)],
                       check=True, capture_output=True, timeout=60)
        return ut.read_bytes()
    except Exception:
        log.warning("Kunde inte läsa bilden %s", foto)
        return None


def _bildblock(data: bytes) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(data).decode()}}


async def _fraga(innehall: list[dict], schema: dict) -> dict | None:
    """Ett anrop med strukturerat JSON-svar till vald leverantör. None vid fel.
    innehall: block i formen {"type": "text", "text"} och _bildblock(...)."""
    if leverantor() == "gemini":
        return await _fraga_gemini(innehall, schema)
    return None


def _gemini_input(innehall: list[dict]) -> list[dict]:
    ut = []
    for b in innehall:
        if b["type"] == "video":
            del_ = {"type": "video", "data": b["data"], "mime_type": b["mime_type"]}
            if b.get("fps"):
                del_["processing"] = {"type": "static", "fps": b["fps"]}
            ut.append(del_)
        elif b["type"] == "audio":
            ut.append({"type": "audio", "data": b["data"], "mime_type": b["mime_type"]})
        elif b["type"] == "image":
            ut.append({"type": "image", "data": b["source"]["data"], "mime_type": b["source"]["media_type"]})
        else:
            ut.append({"type": "text", "text": b["text"]})
    return ut


def _gemini_text(svar: dict) -> str:
    """Texten i sista model_output-steget: steps[].content[].text."""
    for steg in reversed(svar.get("steps") or []):
        if steg.get("type") == "model_output":
            delar = [c.get("text", "") for c in steg.get("content") or [] if c.get("type") == "text"]
            if delar:
                return "".join(delar)
    return svar.get("output_text") or ""


_gemini_http: httpx.AsyncClient | None = None


def gemini_finns() -> bool:
    return bool(_nyckel("GEMINI_API_KEY"))


async def fraga_gemini(innehall: list[dict], schema: dict) -> dict | None:
    """Gemini oavsett AI_LEVERANTOR (används för videokontrollen)."""
    return await _fraga_gemini(innehall, schema) if gemini_finns() else None


async def _fraga_gemini(innehall: list[dict], schema: dict) -> dict | None:
    global _gemini_http
    if _gemini_http is None:
        _gemini_http = httpx.AsyncClient(timeout=180.0)
    rubriker = {"x-goog-api-key": _nyckel("GEMINI_API_KEY"), "Content-Type": "application/json",
                "Api-Revision": GEMINI_REVISION}
    kropp = {
        "input": _gemini_input(innehall),
        "response_format": {"type": "text", "mime_type": "application/json", "schema": schema},
        "generation_config": {"thinking_level": "low"},
        "stream": False,
        "store": False,       # spara inte bilder och texter hos Google i onödan
    }
    # Huvudmodellen är ofta överbelastad: kort tidsgräns, sedan reserverna en i taget. Modeller vars
    # kvot är slut hoppas över en stund. Sist ett nytt försök med första reserven efter en kort paus.
    alla = [(GEMINI_MODELL, 75.0)] + [(m, 120.0) for m in GEMINI_RESERVER]
    forsok = [(m, t) for m, t in alla if _vilar.get(m, 0) < time.monotonic()] or alla[:1]
    if len(forsok) > 1:
        forsok.append(forsok[1])
    for nr, (modell, tidsgrans) in enumerate(forsok):
        if nr and _vilar.get(modell, 0) > time.monotonic():
            continue                          # kvoten tog slut under det här anropet
        if nr == len(forsok) - 1 and nr >= 2:
            await asyncio.sleep(8)
        try:
            r = await _gemini_http.post(GEMINI_URL, headers=rubriker, json={"model": modell, **kropp},
                                        timeout=tidsgrans)
            if r.status_code == 400 and "store" in r.text.lower() and "store" in kropp:
                kropp.pop("store")            # om API:t inte tar emot store=false
                r = await _gemini_http.post(GEMINI_URL, headers=rubriker, json={"model": modell, **kropp})
            if r.status_code == 400 and "thinking" in r.text.lower() and "generation_config" in kropp:
                kropp.pop("generation_config")   # äldre modeller saknar thinking_level
                r = await _gemini_http.post(GEMINI_URL, headers=rubriker, json={"model": modell, **kropp})
            if r.status_code == 400 and ("processing" in r.text.lower() or "fps" in r.text.lower()):
                for b in kropp["input"]:      # om bildfrekvensen inte går att välja: standard (1/s)
                    b.pop("processing", None)
                r = await _gemini_http.post(GEMINI_URL, headers=rubriker, json={"model": modell, **kropp})
        except httpx.HTTPError as e:
            # Tidsgräns eller avbruten anslutning (ofta vid hög belastning): prova reservmodellen.
            log.warning("Ingen kontakt med Gemini %s: %s %s", modell, type(e).__name__, e)
            continue
        if r.status_code in (401, 403):
            log.error("GEMINI_API_KEY är ogiltig eller saknar behörighet (%s)", r.status_code)
            return None
        if r.status_code in (404, 429):
            _vilar[modell] = time.monotonic() + (3600 if r.status_code == 404 else 600)
        if r.status_code in (404, 429, 503):
            log.warning("Gemini %s svarade %s (%s) – provar reservmodellen", modell, r.status_code,
                        "gratiskvoten slut" if r.status_code == 429 else r.text[:150])
            continue
        if r.status_code >= 400:
            log.error("Gemini-fel %s: %s", r.status_code, r.text[:300])
            return None
        data = r.json()
        if data.get("status") not in (None, "completed"):
            log.warning("Gemini status %s: %s", data.get("status"), data.get("errors"))
            return None
        text = _gemini_text(data)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            log.warning("Oväntat svar från Gemini: %r", text[:200])
            return None
    return None



SOKORD_SCHEMA = {
    "type": "object",
    "properties": {
        "sv": {"type": "string"},
        "en": {"type": "string"},
        "farskvara": {"type": "boolean"},
    },
    "required": ["sv", "en", "farskvara"],
    "additionalProperties": False,
}


async def sokord(namn: str, antal: int = 1) -> dict:
    """Sökord för bildsökningen: svenska (Open Food Facts Sverige) och engelska (fotokällor)."""
    flera = (f" Butiken vill visa {antal} OLIKA smaker/varianter i samma video, så sökorden ska "
             "täcka hela serien, inte en enskild smak." if antal > 1 else "")
    d = await _fraga([{"type": "text", "text": (
        f"En svensk livsmedelsbutik vill ha en produktbild på \"{namn}\".{flera}\n"
        "sv: kort svenskt sökord för produktdatabasen Open Food Facts (märke + sort om det är en märkesvara).\n"
        "en: kort engelskt sökord för en fri bilddatabas, som ger en aptitlig produktbild "
        "(t.ex. \"ripe bananas isolated\", \"red apples isolated white background\", \"Monster Energy Ultra can\"). "
        "För färskvaror: be om varan ENSAM (\"isolated\"), inte på ett bord, i en korg eller i en rätt – "
        "bakgrunden tas bort och då måste bara varan finnas kvar.\n"
        "farskvara: true för frukt, grönt, bröd och annat utan förpackning, false för förpackade märkesvaror.")}],
        SOKORD_SCHEMA)
    if not d or not d.get("sv"):
        return {"sv": namn, "en": namn, "farskvara": False}
    return {"sv": d["sv"].strip(), "en": (d.get("en") or namn).strip(), "farskvara": bool(d.get("farskvara"))}


BETYG_SCHEMA = {
    "type": "object",
    "properties": {
        "bilder": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nr": {"type": "integer"},
                    "ratt_produkt": {"type": "boolean"},
                    "nordisk_version": {"type": "string", "enum": ["ja", "nej", "okant"]},
                    "fraschhet": {"type": "integer"},
                    "skarpa_ljus": {"type": "integer"},
                    "ren_bakgrund": {"type": "integer"},
                    "saljande": {"type": "integer"},
                    "rakt_framifran": {"type": "boolean"},
                    "variant": {"type": "string"},
                    "problem": {"type": "string"},
                },
                "required": ["nr", "ratt_produkt", "nordisk_version", "fraschhet", "skarpa_ljus",
                             "ren_bakgrund", "saljande", "rakt_framifran", "variant", "problem"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["bilder"],
    "additionalProperties": False,
}

# Krav för att en nätbild ska användas (betyg 1-10).
KRAV_SALJANDE = 8
KRAV_SKARPA = 7
KRAV_BAKGRUND = 6
KRAV_FRASCHHET = 8      # bara färskvaror


def _godkand(b: dict, farskvara: bool) -> bool:
    return (b["ratt_produkt"] and b["saljande"] >= KRAV_SALJANDE and b["skarpa_ljus"] >= KRAV_SKARPA
            and b["ren_bakgrund"] >= KRAV_BAKGRUND and (not farskvara or b["fraschhet"] >= KRAV_FRASCHHET)
            # Förpackningar måste vara fotade rakt framifrån (annars ser de sneda och uppblåsta ut).
            and (farskvara or b["rakt_framifran"]))


def _godkand_frilaggs(b: dict, farskvara: bool = False) -> bool:
    """Lägre krav när bakgrunden ändå tas bort: rätt vara, skarp, framsidan. Förpackningar rakt
    framifrån; färskvaror (frukt, grönt, bröd) måste se fräscha ut i stället."""
    if farskvara:
        return b["ratt_produkt"] and b["skarpa_ljus"] >= 6 and b["saljande"] >= 6 and b["fraschhet"] >= 7
    return (b["ratt_produkt"] and b["rakt_framifran"] and b["skarpa_ljus"] >= 6 and b["saljande"] >= 6)


def _poang(b: dict, farskvara: bool) -> int:
    p = 2 * b["saljande"] + b["skarpa_ljus"] + b["ren_bakgrund"]
    if farskvara:
        p += b["fraschhet"]
    p += {"ja": 4, "okant": 0, "nej": -6}[b["nordisk_version"]]
    if b.get("kalla", "").startswith("off"):
        p -= 8          # Open Food Facts: privata foton, bara sista utväg
    return p


async def betygsatt(namn: str, bilder: list[Path], farskvara: bool,
                    bara_nordiska: bool = True, frilaggs: bool = False) -> list[tuple[Path, str]]:
    """frilaggs=True: bakgrunden tas bort ändå (och friläggningen kontrolleras efteråt), så
    bara produkten själv bedöms – används vid olika smaker, där bara vanliga produktfoton finns."""
    """Låt AI:n betygsätta varje kandidat. Returnerar godkända (bild, variant), bästa först.
    Tom lista om ingen håller måttet (eller vid fel): då ber boten om ett eget foto."""
    if not tillganglig() or not bilder:
        return []
    innehall: list[dict] = []
    nummer: list[Path] = []
    for b in bilder:
        data = _forminska(b, 512)
        if data:
            nummer.append(b)
            innehall += [{"type": "text", "text": f"Bild {len(nummer)}:"}, _bildblock(data)]
    innehall.append({"type": "text", "text": (
        f"Bilderna ovan är sökträffar för \"{namn}\". Den bästa ska bli huvudbild i en reklamvideo på en "
        "svensk livsmedelsbutiks TV-skylt. Betygsätt VARJE bild strängt, 1-10 (10 = proffsig reklambild):\n"
        "ratt_produkt: visar bilden just den varan (rätt märke OCH rätt sort)? false om det är en annan "
        "produkt av samma märke (t.ex. bagels eller hamburgerbröd när det gäller \"Liba Original\"), en "
        "förpackad/inlagd variant av en färskvara (t.ex. inlagd gurka när det gäller gurka) eller en annan vara.\n"
        "nordisk_version: är förpackningen den svenska/nordiska versionen? \"nej\" om texten är på t.ex. "
        "spanska eller kinesiska, \"okant\" om det inte går att se eller om det är en färskvara.\n"
        "fraschhet: ser varan fräsch och aptitlig ut? Bruna fläckar, blekhet, skador = lågt. "
        "För förpackningar: hel och snygg förpackning.\n"
        "skarpa_ljus: skärpa, upplösning och ljus. Suddigt, mörkt eller brusigt = lågt.\n"
        "ren_bakgrund: packshot på vit eller neutral bakgrund = högt; rörig miljö, händer, "
        "hyllor, flera andra produkter = lågt.\n"
        "saljande: helhetsintryck – skulle en kund bli sugen? Var hård: hellre för lågt än för högt. "
        "Amatörfoton (snett, för nära, ojämnt ljus, blixt) ska få lågt.\n"
        "rakt_framifran: true om produkten är fotad rakt framifrån i sin egen höjd och på lite avstånd "
        "(locket syns knappt, sidorna är raka och parallella, inte rund eller uppblåst av närbild).\n"
        "variant: vilken smak/sort bilden visar, kort (t.ex. \"Ultra Violet\", \"Ultra White\"); "
        "samma text för samma smak.\n"
        "problem: kort om vad som drar ner (tomt om inget)."
        + ("\n\nOBS: bakgrunden tas bort automatiskt, så bedöm BARA produkten själv. ren_bakgrund och saljande "
           "ska inte dras ner av rörig bakgrund, men en bild som bara visar baksidan/ingredienserna, är "
           "avklippt eller där produkten skyms ska få lågt." if frilaggs else ""))})
    d = await _fraga(innehall, BETYG_SCHEMA)
    if d is None:
        return []
    betyg = []
    for b in d.get("bilder", []):
        if isinstance(b.get("nr"), int) and 1 <= b["nr"] <= len(nummer):
            for k in ("fraschhet", "skarpa_ljus", "ren_bakgrund", "saljande"):
                b[k] = max(1, min(10, int(b.get(k) or 1)))
            b["kalla"] = nummer[b["nr"] - 1].name.rsplit("_", 1)[0]   # "off_se", "commons" ...
            betyg.append(b)
    godkanda = [b for b in betyg if (_godkand_frilaggs(b, farskvara) if frilaggs else _godkand(b, farskvara))]
    # Märkesvaror: välj bort utländska förpackningar om det finns andra godkända.
    # (Vid olika smaker räcker poängavdraget: hellre en utländsk burk än en smak för lite.)
    if bara_nordiska and any(b["nordisk_version"] != "nej" for b in godkanda):
        godkanda = [b for b in godkanda if b["nordisk_version"] != "nej"]
    godkanda.sort(key=lambda b: _poang(b, farskvara), reverse=True)
    for b in betyg:
        log.info("Bild %d %s: sälj %d skärpa %d bakgr %d fräsch %d nordisk %s %s", b["nr"],
                 "OK" if b in godkanda else "nej", b["saljande"], b["skarpa_ljus"], b["ren_bakgrund"],
                 b["fraschhet"], b["nordisk_version"], b["problem"])
    log.info("Bildval för %r: %d av %d godkända", namn, len(godkanda), len(nummer))
    ut, sedda = [], set()
    for b in godkanda:
        p = nummer[b["nr"] - 1]
        if p not in sedda:
            sedda.add(p)
            ut.append((p, (b.get("variant") or "").strip().lower()))
    return ut


FORPACKNINGAR = ["500 ml", "330 ml", "330 ml smal", "250 ml smal", "355 ml smal", "annan"]

KONTROLL_SCHEMA = {
    "type": "object",
    "properties": {
        "hel_produkt": {"type": "boolean"},
        "rakt_framifran": {"type": "boolean"},
        "forpackning": {"type": "string", "enum": FORPACKNINGAR},
        "problem": {"type": "string"},
    },
    "required": ["hel_produkt", "rakt_framifran", "forpackning", "problem"],
    "additionalProperties": False,
}


async def kontrollera_frilaggning(namn: str, frilagd: Path, farskvara: bool = False) -> dict:
    """Visar AI:n den frilagda produkten (på grå bakgrund).
    {'ok': bool, 'forpackning': str}. Utan API-nyckel: ok (då gäller bara de mätbara kontrollerna)."""
    if not tillganglig():
        return {"ok": True, "forpackning": "annan"}
    data = _forminska(frilagd, 512)
    if data is None:
        return {"ok": False, "forpackning": "annan"}
    if farskvara:
        # Frukt, grönt, bröd: ingen förpackning, så "framifrån" och burkformen gäller inte.
        d = await _fraga([_bildblock(data), {"type": "text", "text": (
            f"Bilden är en automatiskt frilagd bild av \"{namn}\" på grå bakgrund, till en reklamvideo.\n"
            "hel_produkt: true om varan syns hel och tydlig (en eller några frukter/grönsaker/bröd), ser "
            "fräsch och aptitlig ut, kanten är ren (inga avklippta bitar, inga hål) och inga rester av "
            "bakgrunden syns (bord, tallrik, korg, händer, blad från andra växter). false om det är en "
            "rörig hög med andra varor, skuren/tillagad mat eller om varan är suddig.\n"
            "rakt_framifran: true (gäller inte färskvaror).\nforpackning: \"annan\".\n"
            "problem: kort beskrivning av det som inte stämmer.")}], KONTROLL_SCHEMA)
        if d is None:
            return {"ok": True, "forpackning": "annan"}
        if not d.get("hel_produkt"):
            log.info("AI underkände färskvarubilden: %s", d.get("problem"))
        return {"ok": bool(d.get("hel_produkt")), "forpackning": "annan"}
    d = await _fraga([_bildblock(data), {"type": "text", "text": (
        f"Bilden är en automatiskt frilagd produktbild av \"{namn}\" på grå bakgrund, till en reklamvideo.\n"
        "hel_produkt: true bara om hela produkten är med (t.ex. hela burken, inte bara loggan), det är "
        "FRAMSIDAN (inte baksidan med näringsvärden eller streckkod), kanten är hel (inga bitar som "
        "fattas, inga hål) och inga rester av den gamla bakgrunden syns.\n"
        "rakt_framifran: true bara om fotot är taget rakt framifrån i produktens höjd, på lite avstånd: "
        "burkens lock syns knappt (ingen sned ovansida), sidorna är raka och parallella och produkten ser "
        "inte rund eller uppblåst ut av att mobilen var för nära.\n"
        "forpackning: vilken förpackning det är (\"annan\" om det inte är en burk eller om du är osäker).\n"
        "problem: kort beskrivning av det som inte stämmer.")}],
        KONTROLL_SCHEMA)
    if d is None:
        return {"ok": True, "forpackning": "annan"}
    ok = bool(d.get("hel_produkt")) and bool(d.get("rakt_framifran"))
    if not ok:
        log.info("AI underkände produktbilden: %s", d.get("problem"))
    return {"ok": ok, "forpackning": d.get("forpackning") or "annan"}


async def kanna_igen(fotos: Path | list[Path]) -> dict | None:
    """{'namn': ..., 'pris': ...} eller None om varan inte gick att känna igen.
    Flera foton (olika smaker av samma vara) ger ett gemensamt namn, t.ex. "Monster Energy Ultra"."""
    if not tillganglig():
        return None
    fotos = [fotos] if isinstance(fotos, Path) else list(fotos)
    innehall = []
    for f in fotos:
        data = _forminska(f, 1280 if len(fotos) == 1 else 800)
        if data is not None:
            innehall.append(_bildblock(data))
    if not innehall:
        return None
    prompt = PROMPT
    if len(innehall) > 1:
        prompt += ("\n\nDet är flera foton på olika smaker/varianter av samma vara. namn: ett gemensamt "
                   "namn för alla (t.ex. \"Monster Energy Ultra\" för olika Ultra-smaker), inte en enskild smak.")
    d = await _fraga([*innehall, {"type": "text", "text": prompt}], SCHEMA)
    if d is None:
        return None
    namn = (d.get("namn") or "").strip()
    if not d.get("hittad") or not namn:
        return None
    log.info("Igenkänd vara: %r pris=%r typ=%s", namn, d.get("pris"), d.get("vartyp"))
    return {"namn": namn, "pris": (d.get("pris") or "").strip(), "vartyp": d.get("vartyp") or "annat",
            "skarmdump": bool(d.get("skarmdump")), "ruta": d.get("ruta") or {},
            "fyller_bilden": bool(d.get("fyller_bilden"))}


TEXT_SCHEMA = {
    "type": "object",
    "properties": {
        "forstod": {"type": "boolean"},
        "namn": {"type": "string"},
        "pris": {"type": "string"},
        "dagar": {"type": "integer"},
        "fynd": {"type": "boolean"},
    },
    "required": ["forstod", "namn", "pris", "dagar", "fynd"],
    "additionalProperties": False,
}

TEXT_PROMPT = """Du hjälper en svensk livsmedelsbutik (Min Butik) att tolka korta meddelanden från
ägaren som ska bli reklam på butikens skylt. Han skriver snabbt, ofta utan exakta format.

Ta fram:
- namn: varans namn som det ska stå på skylten (rätt stavat varumärke, t.ex. "Red Bull", "Coca-Cola").
  Utan pris, dagar och ord som "pris", "nu", "bara".
- pris: t.ex. "19 kr", "10 kr/kg", "2 för 30 kr", "15 kr + pant", "50%". Tom sträng om inget pris finns.
- dagar: hur många dagar erbjudandet ska visas, 0 om det inte står.
- fynd: true om han skriver att det är ett fynd.
- forstod: false om meddelandet inte handlar om en vara och ett erbjudande.

Så här har han skrivit tidigare, och så blev det rätt tolkat:
{exempel}

Meddelande: {text}"""


async def tolka_text(text: str, exempel: list[dict]) -> dict | None:
    """AI-tolkning av text som reglerna inte klarade. exempel: pappas senaste godkända
    meddelanden ({'text', 'tolkat'}), så att AI:n lär sig hur just han skriver."""
    if not tillganglig() or not text.strip():
        return None
    rader = "\n".join(f"- \"{e['text']}\" -> {json.dumps(e.get('tolkat', {}), ensure_ascii=False)}"
                      for e in exempel if e.get("text")) or "(inga än)"
    d = await _fraga([{"type": "text", "text": TEXT_PROMPT.format(exempel=rader, text=text)}], TEXT_SCHEMA)
    if not d or not d.get("forstod") or not (d.get("namn") or "").strip():
        return None
    log.info("AI-tolkning av %r: %s", text, d)
    return d


VALJ_SCHEMA = {
    "type": "object",
    "properties": {
        "smaker": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"smak": {"type": "string"}, "nr": {"type": "array", "items": {"type": "integer"}}},
                "required": ["smak", "nr"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["smaker"],
    "additionalProperties": False,
}


async def valj_smaker(namn: str, produkter: list[str], antal: int) -> list[dict]:
    """Väljer olika smaker ur varumärkets produktnamn: [{'smak', 'nr': [index, ...]}], populäraste
    först. Flera nr per smak = samma smak i olika storlekar/länder (reserver om ett foto är dåligt)."""
    lista = "\n".join(f"{i}: {p}" for i, p in enumerate(produkter))
    d = await _fraga([{"type": "text", "text": (
        f"En svensk livsmedelsbutik vill visa {antal} OLIKA smaker av \"{namn}\" i burk/flaska i en reklamvideo.\n"
        f"Här är produkter ur Open Food Facts (nr: namn):\n{lista}\n\n"
        f"Välj {antal + 2} tydligt olika smaker, de som är populärast i Sverige först, gärna med olika "
        "färg på förpackningen. Hoppa över annat än vanliga burkar/flaskor (t.ex. adventskalender, "
        "multipack, cola-varianter från en annan serie, okända namn). smak: kort svenskt smaknamn. "
        "nr: alla nummer i listan som är just den smaken (samma smak kan finnas flera gånger), bästa först.")}],
        VALJ_SCHEMA)
    ut = []
    for s in (d or {}).get("smaker", []):
        nr = [n for n in s.get("nr", []) if isinstance(n, int) and 0 <= n < len(produkter)]
        if nr and (s.get("smak") or "").strip():
            ut.append({"smak": s["smak"].strip(), "nr": nr[:3]})
    log.info("Valda smaker av %r: %s", namn, [(s["smak"], s["nr"]) for s in ut])
    return ut


VARIANT_SCHEMA = {
    "type": "object",
    "properties": {
        "marke": {"type": "string"},
        "varianter": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"sok": {"type": "string"}, "en": {"type": "string"}},
                "required": ["sok", "en"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["marke", "varianter"],
    "additionalProperties": False,
}


async def varianter(namn: str, antal: int) -> tuple[str, list[dict]]:
    """Olika smaker/sorter av en vara som säljs i Sverige, som sökord: [{'sok', 'en'}].
    Används när pappa skriver "redbull olika smaker"."""
    d = await _fraga([{"type": "text", "text": (
        f"En svensk livsmedelsbutik vill visa olika smaker/sorter av \"{namn}\" i en reklamvideo.\n"
        f"Ge {antal} vanliga, tydligt OLIKA smaker/sorter som säljs i Sverige, populäraste först, "
        "gärna med olika färg på förpackningen.\n"
        "sok: fullständigt produktnamn för sökning i Open Food Facts, märke + smak "
        "(t.ex. \"Red Bull Sugarfree\", \"Monster Energy Ultra White\").\n"
        "en: samma på engelska med förpackningstyp (t.ex. \"Red Bull Sugarfree can\").\n"
        "marke: bara varumärket som det skrivs i Open Food Facts (t.ex. \"Red Bull\", \"Monster Energy\").")}],
        VARIANT_SCHEMA)
    ut = []
    for v in (d or {}).get("varianter", []):
        if isinstance(v, dict) and (v.get("sok") or "").strip():
            ut.append({"sok": v["sok"].strip(), "en": (v.get("en") or v["sok"]).strip()})
    marke = ((d or {}).get("marke") or namn).strip()
    log.info("Varianter av %r (märke %r): %s", namn, marke, [v["sok"] for v in ut])
    return marke, ut[:antal]


VADERTYP_SCHEMA = {
    "type": "object",
    "properties": {"typ": {"type": "string", "enum": ["kall", "varm", "grill", "mys", "neutral"]}},
    "required": ["typ"],
    "additionalProperties": False,
}


async def vadertyp(namn: str) -> str | None:
    """Vilket väder varan säljer bäst i (för väderstyrd skylt). Kort textanrop."""
    d = await _fraga([{"type": "text", "text": (
        f"En svensk livsmedelsbutik gör reklam för \"{namn}\". När säljer varan bäst?\n"
        "kall: svalkande, köps när det är varmt (läsk, energidryck, glass, vattenmelon, öl, is).\n"
        "varm: värmande, köps när det är kallt (kaffe, te, soppa, varm choklad, glögg).\n"
        "grill: till grillen (korv, grillkol, halloumi, marinerat kött, grillspett).\n"
        "mys: småätande inomhus, t.ex. regniga kvällar (chips, godis, choklad, popcorn, dip).\n"
        "neutral: säljer lika oavsett väder (ris, mjöl, tvättmedel, bröd, frukt i allmänhet).")}],
        VADERTYP_SCHEMA)
    return (d or {}).get("typ")


FEEDBACK_SCHEMA = {
    "type": "object",
    "properties": {
        "atgarder": {"type": "array", "items": {"type": "string", "enum": [
            "gor_om", "storre_produkt", "mindre_produkt", "storre_pris", "gor_om_frilaggning", "annan_bild"]}},
        "pris": {"type": "string"},
        "namn": {"type": "string"},
    },
    "required": ["atgarder", "pris", "namn"],
    "additionalProperties": False,
}


async def tolka_feedback(text: str) -> dict | None:
    """Butiksägarens önskemål om en reklamvideo ('kan priset synas mer?') -> åtgärder, nytt pris/namn."""
    return await _fraga([{"type": "text", "text": (
        "En butiksägare har sett en reklamvideo för sin skylt och vill ändra något. Hans meddelande:\n"
        f"\"{text}\"\n\n"
        "atgarder: vad som ska göras – storre_pris (prisbrickan större/tydligare), storre_produkt, "
        "mindre_produkt (t.ex. något går utanför), gor_om_frilaggning (fula kanter/rester runt varan), "
        "annan_bild (fel eller ful bild), gor_om (annat, t.ex. ny animation). Tom lista om han bara ändrar text.\n"
        "pris: nytt pris om han anger ett (t.ex. \"12 kr\", \"2 för 30 kr\"), annars tom.\n"
        "namn: nytt namn på varan om han anger ett, annars tom.")}], FEEDBACK_SCHEMA)
