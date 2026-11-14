"""Avgör hur många exemplar av en vara som visas i videon, och hur de ställs upp.

Prioritet (först som gäller vinner):
  1. Pappa skickade flera foton           -> hans foton, ingen duplicering ("rad")
  2. Flera smaker/varianter ("3 smaker")  -> en av varje, högst 3 ("rad")
  3. Flerköp ("2 för 30")                 -> så många som erbjudandet gäller, högst 3 ("rad")
  4. Klase/knippe (bananer, druvor, örter) -> 1 ("enkel")
  5. Lösvikt/styckfrukt (kr/kg, kr/st, äpplen, citroner ...) -> 3 i en hög ("hog")
  6. Dryck i burk/flaska (Red Bull, cola, 33 cl ...) -> 3 av samma, mitten större ("trio")
  7. Förpackning (ris, olja, mjöl, konserver) eller osäkert -> 1 ("enkel")
AI:ns klassning (när API-nyckeln finns) används när reglerna inte själva avgör."""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX = 3

KLASAR = ("banan", "vindruv", "druv", "örter", "basilika", "persilja", "dill", "koriander",
          "mynta", "gräslök", "salladslök", "rädis", "dadlar på kvist", "tomater på kvist")
LOSVIKT = ("äpple", "äpplen", "apelsin", "citron", "lime", "avokado", "tomat", "lök", "päron",
           "kiwi", "mango", "persika", "nektarin", "plommon", "granatäpple", "grapefrukt",
           "clementin", "mandarin", "potatis", "sötpotatis", "paprika", "gurka", "aubergine",
           "zucchini", "squash", "melon", "ingefära", "vitlök", "morot", "morötter", "kokosnöt",
           "fikon", "passionsfrukt", "pomegranat")
# Drycker i burk/flaska ser bäst ut i grupp om tre.
DRYCK = ("red bull", "redbull", "monster", "cola", "pepsi", "fanta", "sprite", "7up", "zingo",
         "trocadero", "loka", "ramlösa", "festis", "celsius", "nocco", "powerking", "burn",
         "rockstar", "battery", "vitamin well", "energidryck", "läsk", "juice", "dryck", "vatten",
         "öl", "cider", "iste", "ice tea", "smoothie", "burk", "flaska", "mtn dew", "prime",
         "schweppes", "mirinda", "lipton", "arizona", "oboy")
# ... men inte stora flaskor som hör till skafferiet.
INTE_DRYCK = ("olja", "vinäger", "soja", "sås", "ketchup", "senap", "sirap", "fond")
_VOLYM = re.compile(r"(?i)\b\d+(?:[.,]\d+)?\s*(?:cl|ml)\b")
# Förädlat/förpackat trots fruktnamn: "krossade tomater", "äppeljuice", "lökringar".
INTE_LOSVIKT = ("krossad", "passerad", "konserv", "puré", "pure", "juice", "sylt", "mos", "chips",
                "torkad", "soltorkad", "ringar", "pulver", "sås", "dryck", "läsk", "burk", "paket")
VARTYPER = ("lösvikt", "klase", "förpackning", "dryck", "annat")


@dataclass
class Uppstallning:
    exemplar: int      # hur många produkter som visas
    stil: str          # "enkel" | "rad" | "hog"
    skal: str          # förklaring (loggas)


def _flerkop(pris: str) -> int:
    m = re.match(r"(?i)^\s*(\d+)\s*för\b", pris or "")
    return int(m.group(1)) if m else 0


def _har(namn: str, ord_: tuple[str, ...]) -> bool:
    n = (namn or "").lower()
    return any(o in n for o in ord_)


def bestam(namn: str, pris: str, antal_foton: int, antal_smaker: int = 1,
           ai_vartyp: str | None = None) -> Uppstallning:
    if antal_foton > 1:
        return Uppstallning(min(antal_foton, MAX), "rad", "olika foton, en per smak/variant")
    if antal_smaker > 1:
        return Uppstallning(min(antal_smaker, MAX), "rad", "olika smaker")
    fler = _flerkop(pris)
    if fler > 1:
        return Uppstallning(min(fler, MAX), "rad", f"flerköp {fler} för")
    if _har(namn, KLASAR) or ai_vartyp == "klase":
        return Uppstallning(1, "enkel", "klase/knippe")
    styck = bool(re.search(r"(?i)(kr|:-)\s*/\s*(kg|hg|st)\b", pris or ""))
    if styck or (_har(namn, LOSVIKT) and not _har(namn, INTE_LOSVIKT)) or ai_vartyp == "lösvikt":
        return Uppstallning(3, "hog", "lösvikt/styckvara")
    dryck = _har(namn, DRYCK) or bool(_VOLYM.search(namn or "")) or ai_vartyp == "dryck"
    if dryck and not _har(namn, INTE_DRYCK):
        return Uppstallning(3, "trio", "dryck: 3 burkar/flaskor")
    return Uppstallning(1, "enkel", "förpackning eller osäkert")
