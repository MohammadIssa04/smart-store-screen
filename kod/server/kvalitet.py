"""Automatisk kvalitetskontroll av varje video med Gemini, innan pappa ser förhandsvisningen.

Gemini tittar på hela videon (inte bara bildrutor) och svarar i fast JSON: godkänd,
problem och en åtgärd per problem. Boten åtgärdar det som går och gör om videon,
högst MAX_OMGORNINGAR gånger. Det som inte gick att rätta blir korta tips till pappa.

Kontrollen stoppar aldrig boten: fel, överbelastning eller slut kvot ger videon ändå,
med notisen KONTROLL_EJ_GJORD. Varje kontroll loggas i data/minne/kontroller.jsonl.

Modulen känner inte till Telegram, så samma kontroll kan användas från en framtida app.
"""
from __future__ import annotations

import base64
import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

import igenkanning
import konfig
import minne
from video.frilagg import ORDNING, cache_fil

log = logging.getLogger("butiksbot.kvalitet")

MAX_OMGORNINGAR = 1          # högst en omgörning (2026-11-14: det tog för lång tid med två)
FPS_KONTROLL = 6          # bildrutor/s som Gemini tittar på: rörelse syns, få tokens
STEG = 1.12               # så mycket större/mindre en åtgärd gör produkt eller pris
KONTROLL_EJ_GJORD = "Automatisk kontroll kunde inte göras just nu."

# Åtgärder Gemini får välja, och vad boten gör.
ATGARDER = {
    "ingen": "inget behöver göras",
    "gor_om": "gör om videon (t.ex. fel i animation eller övergång)",
    "ratta_text": "namn eller pris i videon stämmer inte med texten: gör om med rätt text",
    "annan_bild": "byt till en annan bild (bara när bilden kom från nätet)",
    "storre_produkt": "gör produkterna större",
    "mindre_produkt": "gör produkterna mindre (t.ex. något går utanför kanten)",
    "storre_pris": "gör prisbrickan större",
    "gor_om_frilaggning": "gör om friläggningen (hål, fransar, bakgrundsrester)",
    "egen_bild": "bara pappa kan rätta det: ett nytt eget foto behövs (suddigt, snett, fel vara)",
}

SCHEMA = {
    "type": "object",
    "properties": {
        "godkand": {"type": "boolean"},
        "sammanfattning": {"type": "string"},
        "problem": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "beskrivning": {"type": "string"},
                    "allvar": {"type": "string", "enum": ["allvarligt", "litet"]},
                    "atgard": {"type": "string", "enum": list(ATGARDER)},
                    "tips": {"type": "string"},
                },
                "required": ["beskrivning", "allvar", "atgard", "tips"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["godkand", "sammanfattning", "problem"],
    "additionalProperties": False,
}

PROMPT = """Du är reklamdesigner och granskar en 9 sekunders stående reklamvideo (1080x1920, 60 fps)
för TV-skylten i en liten svensk livsmedelsbutik, Min Butik. Kunder ser den på några meters håll.

SÅ SKA VIDEON SE UT (detta är avsiktligt, inte fel):
- Rosa/magenta bakgrund med strålar, glitter och bubblor. Loggan "MIN BUTIK" högst upp.
- Frilagda produktfoton som glider in en i taget, studsar lite och sedan gungar lätt. Mjuk kontaktskugga under.
- Flera exemplar av samma vara är avsiktligt (t.ex. 3 burkar, mittersta större och framför; frukt i en hög).
- En rund, tandad prisbricka poppar in under produkterna: stort tal, "kr" under, ev. "+ pant" mindre längst ner.
  "2 för 30 kr" skrivs "2 för" ovanför "30". Brickan är lite vriden.
- Varans namn står längst ner. En ljus glansstrimma sveper ibland över bilden.
- In- och utgång: fade, glid från sidan, zoom från mitten, rosa svep eller cirkel. Videon ska börja och sluta
  helt rosa (rosa bakgrund utan innehåll är rätt de första och sista bråkdelarna av en sekund).

DET HÄR SKA STÅ I VIDEON:
- Namn: {namn}
- Pris: {pris}
- Ägarens meddelande: "{text}"
- Antal exemplar: {exemplar} ({stil})
- Bilden kommer från: {kalla}

KONTROLLERA:
1. Stämmer pris, namn och "+ pant" exakt med ovan?
2. Syns hela produkten, eller är något avklippt eller utanför bildkanten?
3. Täcker prisbrickan någon produkt? Är priset stort och läsbart på håll?
4. Hål, fransar, kanter eller bakgrundsrester efter friläggningen?
5. Ser produkterna äkta ut, eller platta, snedfotade, uppblåsta, utdragna eller överbearbetade?
6. Har produkterna likartat ljus och färg så att de hör ihop?
7. Ser frukt och grönt fräscht och aptitligt ut?
8. Är det rätt produkt (t.ex. inte bananyoghurt när det står bananer)?
9. Hackar animationen, blinkar något fel, och börjar och slutar videon på rosa?

SVARA:
- godkand: true om en kund inte skulle märka något fel. Var sträng med fel pris/namn, avklippta produkter,
  täckta produkter och fel vara; var förlåtande med småsaker.
- problem: ett per problem. allvar "allvarligt" om en kund skulle märka det, annars "litet".
  atgard: en av {atgarder}.
  Välj "annan_bild" bara om bilden kommer från nätet; för ägarens egna foton välj "egen_bild" när bilden är dålig.
- tips: EN kort mening på enkel svenska till butiksägaren, bara när han själv kan göra något
  (t.ex. "Bilden är lite suddig, skicka gärna ett eget foto."). Inga tekniska ord. Annars tom sträng.
- sammanfattning: en mening om videon.
Inga problem: godkand true och tom lista."""


@dataclass
class Resultat:
    res: dict                          # svaret från rendera() för videon som ska visas
    notiser: list[str] = field(default_factory=list)
    kontroller: list[dict] = field(default_factory=list)
    omgorningar: int = 0


async def kontrollera(video: Path, forvantat: dict) -> dict | None:
    """Geminis bedömning av videon, eller None om kontrollen inte gick att göra."""
    if not igenkanning.gemini_finns():
        return None
    try:
        data = base64.standard_b64encode(Path(video).read_bytes()).decode()
    except OSError:
        log.exception("Kunde inte läsa videon %s", video)
        return None
    text = PROMPT.format(
        namn=forvantat.get("namn", ""), pris=forvantat.get("pris", "") or "(inget pris)",
        text=forvantat.get("text", ""), exemplar=forvantat.get("exemplar", 1),
        stil=forvantat.get("stil", ""), kalla=forvantat.get("kalla", "ägarens eget foto"),
        atgarder=", ".join(f'"{k}" ({v})' for k, v in ATGARDER.items()))
    innehall = [{"type": "video", "data": data, "mime_type": "video/mp4", "fps": FPS_KONTROLL}]
    stillbild = _stillbild(Path(video))
    if stillbild:
        # En skarp bildruta när allt är på plats: kanter, pris och friläggning syns tydligare än
        # i videons nedsamplade rutor.
        innehall.append(igenkanning._bildblock(stillbild))
        text += ("\n\nDu får också en skarp stillbild från när allt är på plats (ca 5 s in). Kontrollera "
                 "särskilt på den att ingen produkt är avklippt vid vänster/höger kant.")
    svar = await igenkanning.fraga_gemini([*innehall, {"type": "text", "text": text}], SCHEMA)
    if not isinstance(svar, dict) or "godkand" not in svar:
        return None
    svar["problem"] = [p for p in svar.get("problem") or [] if isinstance(p, dict)]
    return svar


def _stillbild(video: Path, t: float = 5.2) -> bytes | None:
    ut = video.with_name(video.stem + "_kontroll.jpg")
    try:
        subprocess.run([*konfig.lag_prioritet_prefix(), "ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", str(video), "-frames:v", "1",
                        "-q:v", "3", str(ut)], check=True, capture_output=True, timeout=60)
        return ut.read_bytes()
    except Exception:
        log.warning("Kunde inte ta stillbild ur %s", video)
        return None


def allvarliga(kontroll: dict) -> list[dict]:
    return [p for p in kontroll["problem"] if p.get("allvar") == "allvarligt"]


def ny_justering(problem: list[dict], justering: dict, kan_byta_bild: bool) -> tuple[dict, list[str]]:
    """Översätter Geminis åtgärder till inställningar för nästa rendering.
    Ger (ny justering, åtgärder som faktiskt görs). Tom lista = inget går att rätta."""
    j = dict(justering)
    gjort: list[str] = []
    for p in problem:
        a = p.get("atgard")
        if a in gjort:
            continue
        if a == "storre_produkt":
            j["produkt"] = j.get("produkt", 1.0) * STEG
        elif a == "mindre_produkt":
            j["produkt"] = j.get("produkt", 1.0) / STEG
        elif a == "storre_pris":
            j["pris"] = j.get("pris", 1.0) * STEG
        elif a == "gor_om_frilaggning" and not j.get("ny_frilaggning"):
            j["ny_frilaggning"] = True
            j["modeller"] = tuple(reversed(ORDNING))
        elif a == "annan_bild" and kan_byta_bild:
            j["annan_bild"] = j.get("annan_bild", 0) + 1
        elif a in ("gor_om", "ratta_text"):
            j["gor_om"] = j.get("gor_om", 0) + 1
        else:
            continue
        gjort.append(a)
    # Testflaggor gäller bara första renderingen (den medvetet dåliga).
    for k in [k for k in j if k.startswith("test_")]:
        j.pop(k)
    return j, gjort


def ny_frilaggning(fotos: list[Path]) -> None:
    """Flytta undan sparade friläggningar (raderas inte) så att de görs om med andra modeller."""
    for f in fotos:
        c = cache_fil(Path(f))
        if c.exists():
            c.rename(c.with_name(c.name.replace(".mask.png", f".mask.fore{int(time.time())}.png")))


# Åtgärder som boten själv gör: deras tips är inte till pappa.
BOTTENS = {"gor_om", "ratta_text", "storre_produkt", "mindre_produkt", "storre_pris", "gor_om_frilaggning"}


def _tips(kontroll: dict | None) -> list[str]:
    if kontroll is None:
        return [KONTROLL_EJ_GJORD]
    tips = list(dict.fromkeys(
        ("Någon bild blev inte riktigt bra – skicka gärna egna foton." if p.get("atgard") == "annan_bild"
         else p["tips"].strip())
        for p in allvarliga(kontroll)
        if (p.get("tips", "").strip() or p.get("atgard") == "annan_bild") and p.get("atgard") not in BOTTENS))
    if not kontroll.get("gemini_ok", True):
        tips.append(KONTROLL_EJ_GJORD)
    if not tips and allvarliga(kontroll):
        tips = ["Videon blev inte helt perfekt – titta extra noga innan du publicerar."]
    return tips[:2]


async def gor_och_kontrollera(gor_video: Callable[[dict, int], Awaitable[dict]], forvantat: dict,
                              kan_byta_bild: bool = False, justering: dict | None = None,
                              status: Callable[[str], Awaitable[None]] | None = None) -> Resultat:
    """gor_video(justering, försök) -> rendera()-svar. Gör, kontrollerar och gör om vid behov."""
    justering = dict(justering or {})
    res = await gor_video(justering, 0)
    forsok = 0
    kontroller: list[dict] = []
    basta: tuple[int, dict, dict | None] | None = None      # (antal allvarliga, res, kontroll)
    while True:
        if status:
            await status("🔍 Kontrollerar videon …")
        t = time.time()
        k = await kontrollera(res["video"], forvantat)
        egna = res.get("layout") or []
        if k is not None:
            k["gemini_ok"] = True
        elif egna:
            k = {"godkand": False, "sammanfattning": "Gemini svarade inte; bottens egen kontroll.",
                 "problem": [], "gemini_ok": False}
        if k is not None and egna:
            # Bottens egen mätning är exakt: lägg till det Gemini inte redan sett.
            k["problem"] = [*egna, *k["problem"]]
            k["godkand"] = False
        post = {"forsok": forsok, "video": str(res["video"]), "justering": {k_: v for k_, v in justering.items()
                                                                          if k_ != "modeller"},
                "sekunder": round(time.time() - t, 1)}
        if k is None:
            post["resultat"] = "ej_gjord"
            kontroller.append(post)
            basta = (0, res, None)     # senaste videon (med eventuella rättningar), okontrollerad
            break
        n = len(allvarliga(k))
        post.update(resultat="godkand" if k["godkand"] and not n else "underkand", svar=k)
        kontroller.append(post)
        if basta is None or n <= basta[0]:
            basta = (n, res, k)
        if (k["godkand"] and not n) or forsok >= MAX_OMGORNINGAR:
            break
        justering, gjort = ny_justering(allvarliga(k) or k["problem"], justering, kan_byta_bild)
        post["atgarder"] = gjort
        if not gjort:
            break                      # inget som boten själv kan rätta
        forsok += 1
        if justering.get("ny_frilaggning") and "ny_frilaggning" in gjort:
            ny_frilaggning(forvantat.get("fotos", []))
        if status:
            await status(f"🔧 Rättar till videon ({forsok}/{MAX_OMGORNINGAR}) …")
        res = await gor_video(justering, forsok)

    _, res_vald, k_vald = basta
    resultat = Resultat(res_vald, _tips(k_vald), kontroller, forsok)
    minne.logga_kontroll({"namn": forvantat.get("namn"), "pris": forvantat.get("pris"),
                          "text": forvantat.get("text"), "omgorningar": forsok,
                          "slutligt": ("ej_gjord" if k_vald is None else
                                       "godkand" if k_vald["godkand"] and not allvarliga(k_vald) else "underkand"),
                          "vald_video": str(res_vald["video"]), "notiser": resultat.notiser,
                          "kontroller": kontroller})
    return resultat
