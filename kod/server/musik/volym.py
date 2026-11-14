"""En enda volymkontroll för butiksmusiken.

- Appen styr BARA musikspelarens egen volym (mpv, 0-100). Den sparas i data/musik/installningar.json
  och gäller efter omstart och nästa morgon.
- System-/Bluetooth-volymen (PipeWire-utgången) ska ligga still på en fast nivå. Med Bluetooth
  absolut volym (AVRCP) är den samma sak som ampens egen volym, och WirePlumber återställer en
  sparad nivå varje gång ampen ansluter – det var därför 60 i appen blev 44.
- När utgången byts (t.ex. ampen ansluter) sätts systemvolymen till LAST_SYSTEMVOLYM, om låset är på.
- Varje ändring loggas i data/musik/volym.jsonl med orsak: appen (vilken telefon), ny utgång,
  låset, eller "utifrån" (ampens ratt, gamla musiksidan, WirePlumber).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime

from musik import bibliotek as bib

INSTALLNINGAR = bib.DATA / "installningar.json"
LOGG = bib.DATA / "volym.jsonl"
STANDARD_VOLYM = 60
# Låset: fast nivå för systemvolymen när en Bluetooth-utgång ansluter. None = av (rör inte systemet).
# Slås på med BUTIKSMUSIK_LAS_SYSTEMVOLYM=1.0 i butiksbot.env (1.0 = 100 %, ampens ratt styr resten).
LAST_SYSTEMVOLYM = float(os.environ["BUTIKSMUSIK_LAS_SYSTEMVOLYM"]) if os.environ.get("BUTIKSMUSIK_LAS_SYSTEMVOLYM") else None


def _las() -> dict:
    try:
        return json.loads(INSTALLNINGAR.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def spelarvolym() -> int:
    return int(_las().get("volym", STANDARD_VOLYM))


def spara_spelarvolym(v: int) -> None:
    d = _las()
    d["volym"] = int(v)
    INSTALLNINGAR.parent.mkdir(parents=True, exist_ok=True)
    tmp = INSTALLNINGAR.with_name(INSTALLNINGAR.name + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, INSTALLNINGAR)


def pausad_datum() -> str | None:
    """Dagen då musiken pausades i appen (pausen gäller som längst till nästa dag, även efter omstart)."""
    return _las().get("pausad")


def spara_paus(datum: str | None) -> None:
    d = _las()
    if datum:
        d["pausad"] = datum
    else:
        d.pop("pausad", None)
    INSTALLNINGAR.parent.mkdir(parents=True, exist_ok=True)
    tmp = INSTALLNINGAR.with_name(INSTALLNINGAR.name + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, INSTALLNINGAR)


def logga(handelse: str, **detaljer) -> None:
    LOGG.parent.mkdir(parents=True, exist_ok=True)
    rad = {"tid": datetime.now().isoformat(timespec="seconds"), "handelse": handelse, **detaljer}
    with open(LOGG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rad, ensure_ascii=False) + "\n")


def systemutgang() -> tuple[str | None, float | None]:
    """(utgångens namn, volym 0-1 som wpctl visar den) för standardutgången."""
    try:
        namn = re.search(r'node\.name = "([^"]+)"', subprocess.run(
            ["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"], capture_output=True, text=True, timeout=3).stdout)
        vol = re.search(r"([0-9.]+)", subprocess.run(
            ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], capture_output=True, text=True, timeout=3).stdout)
        return (namn.group(1) if namn else None), (float(vol.group(1)) if vol else None)
    except Exception:
        return None, None


def satt_systemvolym(v: float) -> None:
    subprocess.run(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{v:.2f}"], timeout=3)


class Vakt:
    """Körs från spelaren var 5:e sekund: ser byte av utgång och ändringar utifrån."""

    def __init__(self) -> None:
        self.namn, self.vol = systemutgang()
        logga("start", utgang=self.namn, systemvolym=self.vol, spelarvolym=spelarvolym(),
              las=LAST_SYSTEMVOLYM)

    def kontrollera(self) -> None:
        namn, vol = systemutgang()
        if namn is None:
            return
        if namn != self.namn:
            logga("ny_utgang", fran=self.namn, till=namn, systemvolym=vol,
                  orsak="ampen ansluten" if namn.startswith("bluez") else "utgången byttes")
            if LAST_SYSTEMVOLYM is not None and namn.startswith("bluez") and vol != LAST_SYSTEMVOLYM:
                satt_systemvolym(LAST_SYSTEMVOLYM)
                logga("systemvolym_last", utgang=namn, fran=vol, till=LAST_SYSTEMVOLYM, orsak="låst nivå vid anslutning")
                namn, vol = systemutgang()
        elif vol is not None and self.vol is not None and abs(vol - self.vol) >= 0.01:
            logga("systemvolym_andrad", utgang=namn, fran=self.vol, till=vol,
                  orsak="utifrån: ampens ratt (AVRCP), gamla musiksidan eller WirePlumber")
        self.namn, self.vol = namn, vol
