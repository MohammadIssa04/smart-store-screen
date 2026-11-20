"""Prisetiketter för Niimbot B31 (termoskrivare, 203 dpi, 75 mm/600 punkters skrivhuvud).

Mall: 70 x 40 mm = 559 x 320 punkter, svartvit. Svart band med "MIN BUTIK" (Bitter, som skylten),
varans namn till vänster och stort pris till höger (Poppins). Priset tolkas som på skylten:
"19 kr", "10 kr/kg", "2 för 30 kr", "15 kr + pant".

Utskrift (ETIKETT_LAGE i butiksbot.env):
  test (standard) – etiketten sparas som bild i data/etiketter/test/, inget skickas till skrivaren
  usb             – via USB-kabel (ETIKETT_PORT, t.ex. /dev/ttyACM0)
  bluetooth       – via Bluetooth (ETIKETT_BT = skrivarens adress). Sitter skrivaren i USB används
                    USB i stället, av sig själv: alltid ansluten, laddas, och musiken till ampen störs aldrig.
Skrivaren nås med biblioteket niimprint (installeras när skrivaren testas, se ETIKETTER-TEST.md).
Varje utskrift loggas i data/etiketter/logg.jsonl.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import threading
from datetime import datetime

from PIL import Image, ImageDraw

import konfig
import tolka
from video.design import bitter, dela_pris, poppins, radbryt

log = logging.getLogger("butiksbot.etikett")

DPI = 203
BREDD_MM, HOJD_MM = 70, 40
BREDD, HOJD = round(BREDD_MM / 25.4 * DPI), round(HOJD_MM / 25.4 * DPI)    # 559 x 320
HUVUD = int(os.environ.get("ETIKETT_HUVUD", "576"))   # B31:s skrivhuvud: 576 punkter (72 mm); med 600 klipptes ramen till höger
MARG = 16                         # ca 2 mm: skrivaren når inte ända ut i kanten
K = 2                             # ritas i dubbel upplösning och skalas ner (skarpare text)

MAPP = konfig.DATA_DIR / "etiketter"
LOGG = MAPP / "logg.jsonl"
_las = threading.Lock()


def installning(namn: str, standard: str = "") -> str:
    return os.environ.get(namn, standard).strip()


# ---------- mallen ----------

def rita(namn: str, pris: str) -> Image.Image:
    """Etiketten som svartvit bild (läge '1'), BREDD x HOJD punkter."""
    W, H, m = BREDD * K, HOJD * K, MARG * K
    bild = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(bild)

    # Ram och svart band med butikens namn
    d.rounded_rectangle((m // 2, m // 2, W - m // 2, H - m // 2), radius=18 * K, outline=0, width=3 * K)
    band = 46 * K
    d.rounded_rectangle((m // 2, m // 2, W - m // 2, m // 2 + band), radius=18 * K, fill=0)
    d.rectangle((m // 2, m // 2 + band // 2, W - m // 2, m // 2 + band), fill=0)
    d.text((W / 2, m // 2 + band / 2 + 2 * K), "ROSA LIVS", font=bitter(30 * K), fill=255, anchor="mm")

    # Priset till höger
    topp = m // 2 + band + 10 * K
    botten = H - m
    prisb = 236 * K
    px0 = W - m - prisb
    tillagg = ""
    p = tolka.snygga_pris(pris)
    if re.search(r"(?i)\+\s*pant$", p):
        tillagg, p = "+ pant", re.sub(r"(?i)\s*\+\s*pant$", "", p)
    over, stor, under = dela_pris(p)
    hojd = botten - topp - (34 * K if over else 0) - (40 * K if under else 0) - (28 * K if tillagg else 0)
    s = 170 * K
    while s > 40 * K and (poppins("Black", s).getlength(stor) > prisb - 22 * K or
                          -poppins("Black", s).getbbox(stor, anchor="ls")[1] > hojd):
        s -= 4 * K
    f = poppins("Black", s)
    h_stor = -f.getbbox(stor, anchor="ls")[1]
    block = h_stor + (34 * K if over else 0) + (40 * K if under else 0) + (28 * K if tillagg else 0)
    y = topp + (botten - topp - block) / 2 + (34 * K if over else 0)
    mitt = px0 + prisb / 2
    if over:
        d.text((mitt, y - 6 * K), over, font=poppins("ExtraBold", 28 * K), fill=0, anchor="ms")
    d.text((mitt, y + h_stor), stor, font=f, fill=0, anchor="ms")
    y += h_stor
    if under:
        d.text((mitt, y + 6 * K), under, font=poppins("ExtraBold", 32 * K), fill=0, anchor="mt")
        y += 40 * K
    if tillagg:
        d.text((mitt, y + 6 * K), tillagg, font=poppins("Bold", 22 * K), fill=0, anchor="mt")

    # Avdelare och namnet till vänster (högst 3 rader, så stort det får plats)
    d.line((px0 - 12 * K, topp + 6 * K, px0 - 12 * K, botten - 6 * K), fill=0, width=2 * K)
    namnb = px0 - 34 * K - (m + 10 * K)
    font, rader = radbryt(namn.strip() or "–", lambda st: poppins("Bold", st), namnb, 58 * K, 24 * K, maxrader=3)
    rad_h = font.size * 1.12
    y0 = topp + (botten - topp - rad_h * len(rader)) / 2
    for i, rad in enumerate(rader):
        d.text((m + 10 * K, y0 + i * rad_h), rad, font=font, fill=0, anchor="lt")

    liten = bild.resize((BREDD, HOJD), Image.LANCZOS)
    return liten.point(lambda v: 255 if v > 140 else 0).convert("1")


def forhandsvisning(namn: str, pris: str, skala: int = 2) -> bytes:
    """PNG för appen: etiketten (som den skrivs ut) på ett vitt kort med mjuk kant."""
    e = rita(namn, pris).convert("L").resize((BREDD * skala, HOJD * skala), Image.NEAREST)
    kort = Image.new("RGB", (e.width + 24, e.height + 24), (236, 230, 232))
    mask = Image.new("L", e.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, e.width - 1, e.height - 1), radius=14 * skala, fill=255)
    kort.paste(e.convert("RGB"), (12, 12), mask)
    ut = io.BytesIO()
    kort.save(ut, "PNG")
    return ut.getvalue()


def for_skrivaren(e: Image.Image) -> Image.Image:
    """Mitt på skrivhuvudet (600 punkter): skrivaren ritar från punkt 0, så etiketten centreras.
    ETIKETT_FORSKJUTNING (punkter, kan vara negativ) och ETIKETT_ROTERA (0/90/180/270) justeras vid test."""
    rot = int(installning("ETIKETT_ROTERA", "0") or 0)
    if rot:
        e = e.rotate(rot, expand=True)
    if e.width >= HUVUD:
        return e
    bred = Image.new("1", (HUVUD, e.height), 1)
    x = (HUVUD - e.width) // 2 + int(installning("ETIKETT_FORSKJUTNING", "0") or 0)
    bred.paste(e, (max(0, min(HUVUD - e.width, x)), 0))
    return bred


# ---------- utskrift ----------

class SkrivFel(Exception):
    """Kort svensk förklaring som appen kan visa."""


def _bt_transport(adress: str, tidsgrans: float = 15.0):
    """Som niimprints BluetoothTransport, men med tidsgräns (en avstängd skrivare får aldrig låsa
    utskrifterna) och som går att stänga efteråt."""
    import socket
    from niimprint.printer import BaseTransport

    class TidsBluetooth(BaseTransport):
        def __init__(self):
            self._sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            self._sock.settimeout(tidsgrans)
            self._sock.connect((adress, 1))

        def read(self, length: int) -> bytes:
            return self._sock.recv(length)

        def write(self, data: bytes):
            return self._sock.send(data)

        def close(self):
            try:
                self._sock.close()
            except OSError:
                pass

    return TidsBluetooth()


def usb_port() -> str | None:
    """Skrivarens USB-port om kabeln sitter i, annars None."""
    port = installning("ETIKETT_PORT", "/dev/ttyACM0")
    return port if os.path.exists(port) else None


def _skrivare():
    lage = installning("ETIKETT_LAGE", "test").lower()
    if lage == "bluetooth" and usb_port():
        lage = "usb"                               # kabeln sitter i: USB går före Bluetooth
    try:
        from niimprint import PrinterClient, SerialTransport
    except ImportError as e:
        raise SkrivFel("Skrivarprogrammet (niimprint) är inte installerat på Pi:n än.") from e
    if lage == "usb":
        return PrinterClient(SerialTransport(port=installning("ETIKETT_PORT", "/dev/ttyACM0")))
    if lage == "bluetooth":
        adress = installning("ETIKETT_BT")
        if not adress:
            raise SkrivFel("Skrivarens Bluetooth-adress saknas (ETIKETT_BT).")
        return PrinterClient(_bt_transport(adress))
    raise SkrivFel(f"Okänt skrivarläge: {lage}")


def _radpaket(bild: Image.Image):
    """Bildrader som Niimbot-paket 0x85: radnummer, svarta punkter i tre delar, upprepning, punkterna."""
    import math
    import struct
    from niimprint.printer import NiimbotPacket
    from PIL import ImageOps
    img = ImageOps.invert(bild.convert("L")).convert("1")
    b = img.width
    del_b = math.ceil(b / 3)
    for y in range(img.height):
        rad = [1 if img.getpixel((x, y)) else 0 for x in range(b)]
        antal = [min(255, sum(rad[i * del_b:(i + 1) * del_b])) for i in range(3)]
        data = int("".join(map(str, rad)), 2).to_bytes(math.ceil(b / 8), "big")
        yield NiimbotPacket(0x85, struct.pack(">H3BB", y, *antal, 1) + data)


def skriv_b1(skrivare, bild: Image.Image, tathet: int, antal: int) -> None:
    """Utskrift med B1-protokollet (som B31 använder, enligt niimbluelib): en sida med 'antal' kopior.
    niimprints print_image är skrivet för B21 och skickar sidstorleken på det gamla sättet – då
    matade B31 fram papperet för långt."""
    import struct
    import time
    from niimprint.printer import RequestCodeEnum as R
    skrivare.set_label_density(tathet)
    skrivare.set_label_type(1)                                    # etiketter med mellanrum
    skrivare._transceive(R.START_PRINT, struct.pack(">H", antal) + bytes(4) + b"\x00")   # 7 byte: sidor, 0, färg
    skrivare._transceive(R.START_PAGE_PRINT, b"\x01")
    skrivare._transceive(R.SET_DIMENSION, struct.pack(">HHH", bild.height, bild.width, antal))  # rader, kolumner, kopior
    for paket in _radpaket(bild):
        skrivare._send(paket)
    skrivare._transceive(R.END_PAGE_PRINT, b"\x01")
    slut = time.time() + 20 + 6 * antal
    while time.time() < slut:                                     # vänta tills alla kopior är utskrivna
        time.sleep(0.5)
        try:
            svar = skrivare._transceive(R.GET_PRINT_STATUS, b"\x01", 16)
            if svar and len(svar.data) >= 2 and int.from_bytes(svar.data[:2], "big") >= antal:
                break
        except Exception:
            pass
    for _ in range(20):
        svar = skrivare._transceive(R.END_PRINT, b"\x01")
        if svar and svar.data and svar.data[0]:
            break
        time.sleep(0.2)


def _stang(skrivare) -> None:
    t = getattr(skrivare, "_transport", None)
    if t is not None and hasattr(t, "close"):
        t.close()


_STATUS_FIL = MAPP / "status.json"
_klient = None              # den öppna anslutningen (bara i API-processen, som håller den)


def _spara_status(ok: bool) -> None:
    import time
    try:
        MAPP.mkdir(parents=True, exist_ok=True)
        _STATUS_FIL.write_text(json.dumps({"ok": ok, "tid": time.time()}))
    except OSError:
        pass


def skrivarstatus(max_alder: float = 30) -> str:
    """'test' | 'ansluten' | 'inte_ansluten'. Läser vad API:ts anslutning senast såg (ansluter aldrig
    själv: varje nytt försök stör musiken till ampen). max_alder finns kvar för gamla anrop."""
    import time
    if installning("ETIKETT_LAGE", "test").lower() not in ("usb", "bluetooth"):
        return "test"
    try:
        st = json.loads(_STATUS_FIL.read_text())
        if st.get("ok") and time.time() - st.get("tid", 0) < 3 * VAKEN_MINUTER * 60:
            return "ansluten"
    except (OSError, ValueError):
        pass
    return "inte_ansluten"


VAKEN_MINUTER = 5           # kontakt var 5:e min över den öppna anslutningen (skrivaren stänger av efter 60)


VILA_EFTER_FEL = 3 * 3600   # svarar skrivaren inte: försök inte igen på 3 h (utskrift försöker ändå)
_FEL_FIL = MAPP / "senast_svarade_inte"


def _vilar_efter_fel() -> bool:
    """Ett misslyckat Bluetooth-försök låser radion ca 40 s och då hackar musiken till ampen.
    Därför väntar både boten och API:t (filen delas) en stund efter ett fel. Bara Bluetooth."""
    import time
    if installning("ETIKETT_LAGE", "test").lower() != "bluetooth" or usb_port():
        return False
    try:
        return time.time() - _FEL_FIL.stat().st_mtime < VILA_EFTER_FEL
    except OSError:
        return False


def _svarade() -> None:
    """Skrivaren svarade: glöm tidigare fel (markeringen nollställs, inte raderad)."""
    import os
    try:
        if _FEL_FIL.exists():
            os.utime(_FEL_FIL, (0, 0))
    except OSError:
        pass


def hall_vaken() -> bool:
    """Kort kontakt med skrivaren (heartbeat) så att den inte stänger av sig. Hoppar över om en
    utskrift pågår. False om skrivaren inte svarar (avstängd, utom räckhåll eller ansluten till en telefon)."""
    if installning("ETIKETT_LAGE", "test").lower() not in ("usb", "bluetooth"):
        return True
    global _klient
    if not _las.acquire(blocking=False):
        return True                                  # en utskrift pågår: den håller den vaken
    try:
        ok = None
        if _klient is not None:
            try:
                _klient.heartbeat()                  # över den öppna anslutningen: stör inte musiken
                ok = True
            except Exception as e:
                log.info("Anslutningen till skrivaren bröts: %s, ansluter igen", e)
                _koppla_ner()
        if ok is None:
            if _vilar_efter_fel():
                ok = False                           # svarade inte nyss: stör inte musiken igen
            else:
                try:
                    _klient = _skrivare()            # en ny anslutning, som sedan hålls öppen
                    _klient.heartbeat()
                    log.info("Etikettskrivaren ansluten (hålls ansluten)")
                    ok = True
                except Exception as e:
                    _koppla_ner()
                    log.info("Skrivaren svarade inte: %s (nästa försök om %d h)", e, VILA_EFTER_FEL // 3600)
                    try:
                        _FEL_FIL.parent.mkdir(parents=True, exist_ok=True)
                        _FEL_FIL.touch()
                    except OSError:
                        pass
                    ok = False
        if ok:
            _svarade()
        _spara_status(ok)
        return ok
    finally:
        _las.release()


def _koppla_ner() -> None:
    global _klient
    if _klient is not None:
        _stang(_klient)
        _klient = None


def skriv_ut(namn: str, pris: str, antal: int = 1, av: str = "") -> dict:
    """Skriver ut (eller sparar som bild i testläge). {'lage', 'meddelande', 'filer'}."""
    global _klient
    antal = max(1, min(20, int(antal)))
    e = rita(namn, pris)
    lage = installning("ETIKETT_LAGE", "test").lower()
    rad = {"tid": datetime.now().isoformat(timespec="seconds"), "namn": namn, "pris": pris,
           "antal": antal, "lage": lage, "av": av}
    with _las:                                      # en utskrift åt gången
        if lage == "test":
            mapp = MAPP / "test"
            mapp.mkdir(parents=True, exist_ok=True)
            fil = mapp / f"{datetime.now():%Y%m%d-%H%M%S}_{re.sub(r'[^a-z0-9]+', '-', namn.lower())[:30]}.png"
            for_skrivaren(e).save(fil)
            rad.update(resultat="sparad", fil=str(fil))
            svar = {"lage": "test", "filer": [str(fil)],
                    "meddelande": "Testläge: etiketten sparades som bild (skrivaren är inte inkopplad)."}
        else:
            try:
                if _klient is None:
                    _klient = _skrivare()
                skrivare = _klient
                tathet = int(installning("ETIKETT_TATHET", "3") or 3)
                if installning("ETIKETT_PROTOKOLL", "b1").lower() == "gammal":
                    for _ in range(antal):
                        skrivare.print_image(for_skrivaren(e), density=tathet)
                else:
                    skriv_b1(skrivare, for_skrivaren(e), tathet, antal)
            except SkrivFel as f:
                _koppla_ner()
                rad.update(resultat="fel", fel=str(f))
                _logga(rad)
                raise
            except Exception as f:
                _koppla_ner()                        # nästa gång: en ny anslutning
                log.exception("Utskriften misslyckades")
                rad.update(resultat="fel", fel=repr(f))
                _logga(rad)
                _spara_status(False)
                raise SkrivFel("Skrivaren svarade inte. Är den på och har etiketter?") from f
            rad["resultat"] = "utskriven"
            _spara_status(True)
            _svarade()
            svar = {"lage": lage, "filer": [],
                    "meddelande": f"{antal} etikett{'er' if antal > 1 else ''} utskriven{'a' if antal > 1 else ''}."}
    _logga(rad)
    return svar


def _logga(rad: dict) -> None:
    MAPP.mkdir(parents=True, exist_ok=True)
    with open(LOGG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rad, ensure_ascii=False) + "\n")
