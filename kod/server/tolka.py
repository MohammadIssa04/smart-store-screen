"""Tolkar pappas text: "Monster 19 kr 3 dagar", "fynd 50% bröd" osv."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import konfig


@dataclass
class Tolkning:
    typ: str          # "erbjudande" eller "fynd"
    text: str         # originaltexten
    rubrik: str       # produkttexten som visas
    pris: str         # t.ex. "19 kr", "2 för 30 kr", "50%" (kan vara tom)
    dagar: int
    utgar: datetime
    dagar_angivet: bool = False
    antal: int = 1        # antal olika produkter/smaker i videon (1-3)


_FYND = re.compile(r"(?<!\w)fynd(?!\w)[\s:,\-–]*", re.I)
_ANTAL = re.compile(r"(?<!\w)([1-9])\s*(?:olika\s*)?(?:smaker|smak|sorter|sorters|varianter|variant)(?!\w)", re.I)
MAX_ANTAL = 3
# "redbull olika smaker", "monster alla smaker", "chips flera sorter", "läsk smaker" -> 3 olika
_OLIKA = re.compile(r"(?<!\w)(?:(?:olika|alla|flera|blandade|mixade|mix\s+av)\s+)?"
                    r"(?:smaker|sorter|sorters|varianter)(?!\w)", re.I)
# "3 dagar", "3 dag", "3d", "i 3 dagar", "3 dgr"
_DAGAR = re.compile(r"(?<!\w)(?:i\s+)?(\d{1,3})\s*(?:dagar|dag|dgr|d)(?!\w)", re.I)
# "+ pant", "plus pant", "+pant", "exkl pant"
_PANT = re.compile(r"(?:\+|\bplus\b|\bexkl\.?\b|\butan\b)\s*pant(?!\w)", re.I)
_SLUT = r"(?=\s|$|[!.,;)+])"
_ENHET = r"(?:kg|hg|st|l|liter|kilo)"
_PRIS = [
    # Jämförpris: "10 kr/kg", "10kr / kg", "5:-/st", "10/kg", "10 kr kg", "10 kr per kg"
    re.compile(r"(?<!\w)\d+(?:[.,]\d+)?\s*(?:(?:kr|sek|:-)\s*(?:/|per|\s)\s*|/\s*)" + _ENHET + _SLUT, re.I),
    re.compile(r"(?<!\w)\d+\s*för\s*\d+(?:[.,]\d+)?(?:\s*(?:kr|sek)|:-)?" + _SLUT, re.I),
    re.compile(r"(?<!\w)\d+(?:[.,]\d+)?(?:\s*(?:kr|sek|kronor)|:-)" + _SLUT, re.I),
    re.compile(r"-?\d+(?:[.,]\d+)?\s*%"),
]
# Ett ensamt tal ("fynd bröd 10", "redbull 15 + pant") tolkas som kronor.
_BARA_TAL = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)?(?![\w.,%])")

# Vanliga hopskrivna varumärken som pappa skriver snabbt.
KANDA_NAMN = {
    "redbull": "Red Bull", "red bull": "Red Bull", "cocacola": "Coca-Cola", "coca cola": "Coca-Cola",
    "coca-cola": "Coca-Cola", "pepsimax": "Pepsi Max", "pepsi max": "Pepsi Max", "monster": "Monster",
    "fanta": "Fanta", "sprite": "Sprite", "cola": "Cola", "7up": "7UP",
}


def _snygga_pris(p: str) -> str:
    p = re.sub(r"\s+", " ", p.strip())
    p = re.sub(r"(?i)\s*(?:sek|kronor)\b", " kr", p)
    p = re.sub(r"(?i)\bkilo\b", "kg", p)
    p = re.sub(r"(?i)\s+per\s+", "/", p)
    p = re.sub(r"(?i)(kr|:-)\s+(kg|hg|st|l|liter)\b", r"\1/\2", p)   # "10 kr kg" -> "10 kr/kg"
    p = re.sub(r"(?i)^(\d+(?:[.,]\d+)?)\s*/", r"\1 kr/", p)          # "10/kg" -> "10 kr/kg"
    p = re.sub(r"(?i)(\d)\s*kr\b", r"\1 kr", p)
    p = re.sub(r"\s*%", "%", p)
    p = re.sub(r"\s*/\s*", "/", p)                      # "kr / kg" -> "kr/kg"
    p = re.sub(r"(?i)/liter\b", "/l", p)
    if re.search(r"(?i)\bför\b", p) and not re.search(r"(?i)(kr|:-)$", p):
        p += " kr"
    return p


def berakna_utgang(typ: str, dagar: int, nu: datetime, dagar_angivet: bool = False) -> datetime:
    """Stängning (kl 21) den sista dagen. Efter stängning räknas från i morgon.
    Fynd utan angivet antal dagar gäller bara i dag."""
    stang = nu.replace(hour=konfig.STANGNING_TIMME, minute=0, second=0, microsecond=0)
    if nu >= stang:
        stang += timedelta(days=1)
    if typ == "fynd" and not dagar_angivet:
        return stang
    return stang + timedelta(days=dagar - 1)


VECKODAGAR = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"]


def till_och_med(utgar: datetime, nu: datetime | None = None) -> str:
    """'i dag', 'i morgon (fredag)', 'fredag', 'fredag 21/11'."""
    nu = nu or datetime.now()
    dagar = (utgar.date() - nu.date()).days
    dag = VECKODAGAR[utgar.weekday()]
    if dagar <= 0:
        return "i dag"
    if dagar == 1:
        return f"i morgon ({dag})"
    if dagar < 7:
        return dag
    return f"{dag} {utgar.day}/{utgar.month}"


def sammanfattning(rubrik: str, pris: str, utgar: datetime, nu: datetime | None = None) -> str:
    """Det boten har förstått, i klartext: 'Bananer, 10 kr/kg, visas t.o.m. fredag'."""
    delar = [rubrik or "(namn saknas)", pris or "(pris saknas)"]
    return f"{', '.join(delar)}, visas t.o.m. {till_och_med(utgar, nu)}"


def tolka(text: str, nu: datetime | None = None) -> Tolkning:
    nu = nu or datetime.now()
    original = text.strip()
    rest = original

    typ = "erbjudande"
    m = _FYND.search(rest)
    if m:
        typ = "fynd"
        rest = rest[: m.start()] + " " + rest[m.end():]

    dagar = konfig.STANDARD_DAGAR
    m = _DAGAR.search(rest)
    if m:
        dagar = max(1, min(konfig.MAX_DAGAR, int(m.group(1))))
        rest = rest[: m.start()] + " " + rest[m.end():]
    dagar_angivet = bool(m)

    antal = 1
    m = _ANTAL.search(rest)
    if m:
        antal = max(1, min(MAX_ANTAL, int(m.group(1))))
        rest = rest[: m.start()] + " " + rest[m.end():]
    else:
        m = _OLIKA.search(rest)
        if m:
            antal = MAX_ANTAL
            rest = rest[: m.start()] + " " + rest[m.end():]

    pant = False
    m = _PANT.search(rest)
    if m:
        pant = True
        rest = rest[: m.start()] + " " + rest[m.end():]

    pris = ""
    for monster in [*_PRIS, _BARA_TAL]:
        m = monster.search(rest)
        if m:
            pris = _snygga_pris(m.group(0))
            if monster is _BARA_TAL:
                pris += " kr"
            rest = rest[: m.start()] + " " + rest[m.end():]
            break
    if pant and pris:
        pris += " + pant"

    rubrik = re.sub(r"\s+", " ", rest).strip(" -–,:;+")
    # Fyllnadsord runt priset hör inte till produktnamnet: "äpplen pris är 10 kr/kg", "chips nu bara 20 kr".
    rubrik = re.sub(r"(?i)(?:\s+(?:pris(?:et)?(?:\s+är)?|kostar|nu|bara|endast|för|à|a|i|st|styck))+$", "", rubrik).strip(" -–,:;+")
    rubrik = KANDA_NAMN.get(rubrik.lower(), rubrik)
    if rubrik and rubrik[0].islower():
        rubrik = rubrik[0].upper() + rubrik[1:]

    return Tolkning(typ, original, rubrik, pris, dagar, berakna_utgang(typ, dagar, nu, dagar_angivet), dagar_angivet, antal)


def tolka_pris(text: str) -> str:
    """Svar på frågan "Vilket pris?": '19', '19 kr', '19:-', '2 för 30', '50%'."""
    text = text.strip()
    pant = bool(_PANT.search(text))
    text = _PANT.sub(" ", text).strip()
    pris = ""
    for monster in _PRIS:
        m = monster.search(text)
        if m:
            pris = _snygga_pris(m.group(0))
            break
    if not pris:
        m = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(?:kr|kronor|sek)?\.?", text, re.I)
        pris = f"{m.group(1)} kr" if m else ""
    return f"{pris} + pant" if pris and pant else pris


def snygga_pris(p: str) -> str:
    return _snygga_pris(p) if p else ""
