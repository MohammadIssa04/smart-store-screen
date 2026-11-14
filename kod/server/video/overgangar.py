"""Val av in- och utgång för en video, så att skylten inte känns enformig.

Alla övergångar börjar och slutar på den rosa bakgrundsfärgen, så bytet till nästa
skyltvideo blir sömlöst oavsett vilken kombination som valts:
  fade    mjuk tonad övergång
  glid    produkterna glider in från ena sidan och ut åt andra hållet
  zoom    bilden zoomar in från mitten (ut: krymper mot mitten)
  wipe    en rosa yta sveper över skärmen
  cirkel  en cirkel öppnar sig från mitten (ut: stänger sig)
"""
from __future__ import annotations

import random
from collections import Counter

INGANGAR = ("fade", "glid", "zoom", "wipe", "cirkel")
UTGANGAR = ("fade", "glid", "zoom", "wipe", "cirkel")
NAMN = {"fade": "mjuk fade", "glid": "glid från sidan", "zoom": "zoom från mitten",
        "wipe": "rosa svep", "cirkel": "cirkel från mitten"}


def _minst_anvand(val: tuple[str, ...], anvanda: list[str], undvik: str | None,
                  slump: random.Random) -> str:
    """Den minst använda övergången, men aldrig samma som förra videon om det går."""
    antal = Counter(anvanda)
    kandidater = [v for v in val if v != undvik] or list(val)
    minst = min(antal[v] for v in kandidater)
    return slump.choice([v for v in kandidater if antal[v] == minst])


def valj(anvanda: list[tuple[str, str]] | None = None, senaste: tuple[str, str] | None = None,
         slump: random.Random | None = None) -> tuple[str, str]:
    """anvanda: övergångar för videor som visas på skylten nu. senaste: förra videons.
    Ger (in, ut). Slumpad, men undviker förra videons in/ut och sprider ut valen."""
    slump = slump or random.Random()
    anvanda = [tuple(a) for a in (anvanda or []) if a]
    ing = _minst_anvand(INGANGAR, [a[0] for a in anvanda], senaste[0] if senaste else None, slump)
    ut = _minst_anvand(UTGANGAR, [a[1] for a in anvanda], senaste[1] if senaste else None, slump)
    return ing, ut


def beskriv(overgang: tuple[str, str]) -> str:
    return f"in: {NAMN.get(overgang[0], overgang[0])}, ut: {NAMN.get(overgang[1], overgang[1])}"
