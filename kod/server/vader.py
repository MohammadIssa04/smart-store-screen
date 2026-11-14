"""Väderstyrd skylt: rätt varor vid rätt väder.

1. Prognosen för butikens ort hämtas från SMHI (snow1g, öppet API utan nyckel) och sparas.
2. Varje annons har en vädertyp: kall, varm, grill, mys eller neutral (se klassa()).
3. Reglerna ger en vikt per annons = hur många gånger den kommer med i skyltens spellista.
   Inga annonser försvinner; de som passar vädret kommer bara med oftare.
4. Vikterna skrivs till ~/skylt/erbjudanden/.vikter (filnamn<TAB>vikt) som skylt-play läser.
   Saknas filen visar skylt-play allt en gång, som förut.
Varje ändring loggas i data/minne/vader.jsonl.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import konfig

log = logging.getLogger("butiksbot.vader")

LAT = float(os.environ.get("VADER_LAT", "59.33"))   # butikens plats, sätts i butiksbot.env
LON = float(os.environ.get("VADER_LON", "18.07"))
SMHI_URL = ("https://opendata-download-metfcst.smhi.se/api/category/snow1g/version/1/"
            f"geotype/point/lon/{LON}/lat/{LAT}/data.json")
TZ = ZoneInfo("Europe/Stockholm")
PROGNOS_FIL = konfig.DATA_DIR / "vader" / "prognos.json"
LOGG_FIL = konfig.DATA_DIR / "minne" / "vader.jsonl"
VIKT_FIL = konfig.ERBJUDANDEN_DIR / ".vikter"
MAX_ALDER = timedelta(hours=24)                   # äldre prognos används inte

OPPNAR, STANGER = 10, konfig.STANGNING_TIMME      # skylten visas 10-21
VARMT, MYCKET_VARMT = 18.0, 25.0                  # högsta temp under öppettid
KALLT, MYCKET_KALLT = 5.0, -5.0
REGN_TIMMAR = 3                                   # timmar med nederbörd under öppettid
GRILL_TEMP, GRILL_REGN = 18.0, 1.0                # helgdag: högsta temp, mm regn totalt
SOL = set(range(1, 5))                            # symbol 1-4: klart till halvklart
NEDERBORD = set(range(8, 28))                     # symbol 8-27: skurar, regn, snöblandat, snö
TYPER = ("kall", "varm", "grill", "mys", "neutral")


# ---------- vädertyp per vara ----------

ORD = {
    "kall": ("läsk", "cola", "pepsi", "fanta", "sprite", "7up", "energidryck", "red bull", "redbull", "monster",
             "celsius", "nocco", "powerking", "burn", "prime", "glass", "isglass", "piggelin", "magnum",
             "vattenmelon", "melon", "juice", "smoothie", "iste", "ice tea", "vatten", "ramlösa", "loka",
             "cider", "öl", "festis", "zingo", "trocadero", "frozen", "slush", "sorbet", "is"),
    "varm": ("kaffe", "te", "tepåsar", "soppa", "buljong", "varm choklad", "o'boy", "oboy", "pulverkaffe",
             "glögg", "gröt", "havregryn", "nudlar", "snabbnudlar", "chai", "kakao", "cappuccino", "latte"),
    "grill": ("korv", "grill", "kol", "briketter", "tändvätska", "halloumi", "marinad", "hamburgare",
              "burgare", "spett", "kebab", "kyckling", "entrecote", "karré", "fläskkarré", "majskolv",
              "bbq", "barbecue", "grillkrydda", "lamm", "kotlett"),
    "mys": ("chips", "godis", "choklad", "popcorn", "ostbågar", "dip", "nötter", "kakor", "kex", "lösgodis",
            "marabou", "chokladkaka", "bullar", "kanelbulle", "tårta", "plopp", "polly", "pringles", "olw",
            "estrella", "cheez"),
}


# Korta ord måste vara hela ord ("te" ska inte träffa "potatis", "is" inte "ris").
HELA_ORD = {"te", "is", "öl", "kol", "dip", "lamm", "burn", "prime"}


def _finns(o: str, n: str) -> bool:
    if o in HELA_ORD:
        return re.search(rf"(?<![a-zåäöé]){re.escape(o)}(?![a-zåäöé])", n) is not None
    return o in n


def klassa_ord(namn: str) -> str:
    """Vädertyp från ordlistan, 'neutral' om inget ord passar."""
    n = (namn or "").lower()
    for typ in ("varm", "grill", "mys", "kall"):        # "varm choklad" före "choklad"
        if any(_finns(o, n) for o in ORD[typ]):
            return typ
    return "neutral"


async def klassa(namn: str) -> str:
    """Ordlistan först (gratis). Säger den neutral och AI finns: fråga AI:n kort."""
    typ = klassa_ord(namn)
    if typ != "neutral":
        return typ
    import igenkanning
    if igenkanning.tillganglig():
        ai = await igenkanning.vadertyp(namn)
        if ai in TYPER:
            return ai
    return "neutral"


# ---------- prognos ----------

def _tolka_smhi(data: dict) -> list[dict]:
    """[{'tid': lokal datetime, 'temp', 'symbol', 'mm'}], saknade värden (9999) som None."""
    ut = []
    for t in data.get("timeSeries", []):
        d = t.get("data", {})
        def v(k):
            x = d.get(k)
            return None if x is None or x == 9999 else x
        ut.append({"tid": datetime.fromisoformat(t["time"].replace("Z", "+00:00")).astimezone(TZ),
                   "temp": v("air_temperature"), "symbol": v("symbol_code"),
                   "mm": v("precipitation_amount_mean") or 0.0})
    return ut


async def hamta_prognos() -> bool:
    """Hämtar och sparar SMHI-prognosen. False vid fel (den sparade används då)."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "MinButikBot/1.0"}) as c:
            r = await c.get(SMHI_URL)
        r.raise_for_status()
        data = r.json()
        if not data.get("timeSeries"):
            raise ValueError("tom prognos")
    except Exception as e:
        log.warning("SMHI-prognosen kunde inte hämtas: %s", e)
        return False
    PROGNOS_FIL.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROGNOS_FIL.with_suffix(".tmp")
    tmp.write_text(json.dumps({"hamtad": datetime.now(timezone.utc).isoformat(), "smhi": data}), encoding="utf-8")
    os.replace(tmp, PROGNOS_FIL)
    log.info("SMHI-prognos hämtad: %d tider", len(data["timeSeries"]))
    return True


def las_prognos(nu: datetime | None = None) -> list[dict] | None:
    """Sparad prognos om den är högst MAX_ALDER gammal, annars None."""
    nu = nu or datetime.now(timezone.utc)
    try:
        sparad = json.loads(PROGNOS_FIL.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if nu - datetime.fromisoformat(sparad["hamtad"]) > MAX_ALDER:
        return None
    return _tolka_smhi(sparad["smhi"])


# ---------- väderläge och regler ----------

@dataclass
class Dag:
    datum: str
    max_temp: float | None
    regn_timmar: int
    mm: float
    sol_timmar: int
    timmar: int


@dataclass
class Lage:
    idag: Dag | None
    helg: list[Dag] = field(default_factory=list)
    vikter: dict[str, int] = field(default_factory=dict)     # vädertyp -> vikt
    regler: list[str] = field(default_factory=list)


def _dag(prognos: list[dict], d: date) -> Dag | None:
    """Sammanfattning för öppettiden (10-21) en dag. SMHI ger timvärden de första dagarna,
    sedan glesare; dagar utan värden under öppettid ger None."""
    t = [p for p in prognos if p["tid"].date() == d and OPPNAR <= p["tid"].hour < STANGER]
    if not t:
        return None
    temps = [p["temp"] for p in t if p["temp"] is not None]
    return Dag(d.isoformat(), max(temps) if temps else None,
               sum(1 for p in t if (p["symbol"] in NEDERBORD) or p["mm"] >= 0.2),
               round(sum(p["mm"] for p in t), 1), sum(1 for p in t if p["symbol"] in SOL), len(t))


def lage(prognos: list[dict] | None, nu: datetime | None = None) -> Lage:
    """Vilka vädertyper som ska visas oftare just nu, och varför."""
    nu = (nu or datetime.now(TZ)).astimezone(TZ)
    if not prognos:
        return Lage(None, regler=["ingen prognos: alla visas lika ofta"])
    idag = _dag(prognos, nu.date())
    L = Lage(idag)
    if idag and idag.max_temp is not None:
        if idag.max_temp >= VARMT:
            L.vikter["kall"] = 3 if idag.max_temp >= MYCKET_VARMT else 2
            L.regler.append(f"varmt ({idag.max_temp:.0f} °C): kalla varor x{L.vikter['kall']}")
        elif idag.max_temp < KALLT:
            L.vikter["varm"] = 3 if idag.max_temp <= MYCKET_KALLT else 2
            L.regler.append(f"kallt ({idag.max_temp:.0f} °C): varma varor x{L.vikter['varm']}")
    if idag and idag.regn_timmar >= REGN_TIMMAR:
        L.vikter["mys"] = 2
        L.regler.append(f"regn/snö {idag.regn_timmar} h: mysvaror x2")
    # Grillhelg: från torsdag, om lördag eller söndag blir sol och värme.
    if nu.weekday() >= 3:
        # Torsdag/fredag: kommande lördag+söndag. Lördag: i dag+i morgon. Söndag: bara i dag.
        lordag = nu.date() + timedelta(days=5 - nu.weekday())
        dagar = [d for d in (lordag, lordag + timedelta(days=1)) if d >= nu.date()]
        helg = [d for d in (_dag(prognos, x) for x in dagar) if d]
        L.helg = helg
        bra = [d for d in helg if d.max_temp is not None and d.max_temp >= GRILL_TEMP
               and d.sol_timmar * 2 > d.timmar and d.mm < GRILL_REGN]
        if bra:
            L.vikter["grill"] = 3 if len(bra) == 2 else 2
            L.regler.append(f"grillhelg ({', '.join(f'{d.datum} {d.max_temp:.0f} °C' for d in bra)}): "
                            f"grillvaror x{L.vikter['grill']}")
    if not L.regler:
        L.regler.append("vanligt väder: alla visas lika ofta")
    return L


# ---------- vikter till skylten ----------

def vikter(poster: list[dict], L: Lage) -> dict[str, int]:
    """Filnamn -> vikt för aktiva annonser på skylten."""
    ut = {}
    for p in poster:
        fil = (p.get("kanaler", {}).get("skylt") or {}).get("fil")
        if fil:
            vikt = max(int(p.get("vikt_val") or 1), L.vikter.get(p.get("vadertyp") or "neutral", 1))
            # "Visa extra" från appen: vikt 3 tills den tiden gått ut (vädret kan inte sänka den).
            if p.get("extra_till") and datetime.fromisoformat(p["extra_till"]) > datetime.now():
                vikt = max(vikt, 3)
            ut[Path(fil).name] = vikt
    return ut


def skriv_vikter(poster: list[dict], L: Lage, fil: Path = VIKT_FIL) -> bool:
    """Skriver .vikter om något ändrats och loggar det. True om filen ändrades."""
    v = vikter(poster, L)
    text = "".join(f"{namn}\t{vikt}\n" for namn, vikt in sorted(v.items()))
    try:
        if fil.exists() and fil.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    fil.parent.mkdir(parents=True, exist_ok=True)
    tmp = fil.with_name(fil.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, fil)
    namn = {Path((p.get("kanaler", {}).get("skylt") or {}).get("fil", "")).name: p for p in poster}
    rad = {"tid": datetime.now(TZ).isoformat(timespec="seconds"),
           "idag": asdict(L.idag) if L.idag else None, "helg": [asdict(d) for d in L.helg],
           "regler": L.regler, "vikter": L.vikter,
           "annonser": [{"rubrik": namn[f].get("rubrik"), "vadertyp": namn[f].get("vadertyp"), "vikt": w}
                        for f, w in sorted(v.items()) if f in namn]}
    LOGG_FIL.parent.mkdir(parents=True, exist_ok=True)
    with open(LOGG_FIL, "a", encoding="utf-8") as f:
        f.write(json.dumps(rad, ensure_ascii=False) + "\n")
    log.info("Vikter: %s | %s", "; ".join(L.regler), {k: w for k, w in v.items() if w > 1} or "alla 1")
    return True


def beskriv(L: Lage) -> str:
    """Kort text för /vader."""
    rader = []
    if L.idag and L.idag.max_temp is not None:
        rader.append(f"I dag (kl {OPPNAR}-{STANGER}): högst {L.idag.max_temp:.0f} °C, "
                     f"{'regn/snö ' + str(L.idag.regn_timmar) + ' h' if L.idag.regn_timmar else 'uppehåll'}.")
    for d in L.helg:
        rader.append(f"{d.datum}: högst {d.max_temp:.0f} °C, sol {d.sol_timmar} av {d.timmar} h, {d.mm} mm.")
    rader += ["", "Skylten just nu:"] + [f"• {r}" for r in L.regler]
    return "\n".join(rader)
