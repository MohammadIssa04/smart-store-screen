"""Slår på skyltens TV på morgonen och av på kvällen via HDMI-CEC (cec-ctl, /dev/cec0).

Kräver att HDMI-CEC är påslaget i TV:n (Samsung: Anynet+, LG: SIMPLINK, Sony: BRAVIA Sync,
Philips: EasyLink). Svarar TV:n inte loggas det, och hälsokontrollen kan visa det.
    .venv/bin/python tv.py pa | av | status | lage
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import time

import konfig

log = logging.getLogger("butiksbot.tv")
ENHET = "/dev/cec0"
STATUS = konfig.DATA_DIR / "tv.json"


def _cec(*arg: str) -> tuple[bool, str]:
    """True om TV:n tog emot meddelandet (ACK)."""
    try:
        r = subprocess.run(["cec-ctl", "-d", ENHET, "--playback", "--to", "0", *arg],
                           capture_output=True, text=True, timeout=20)
    except Exception as e:
        return False, repr(e)
    ut = r.stdout + r.stderr
    return r.returncode == 0 and "Not Acknowledged" not in ut, ut


def _spara(handelse: str, ok: bool) -> None:
    try:
        STATUS.write_text(json.dumps({"handelse": handelse, "ok": ok, "tid": time.time()}))
    except OSError:
        pass


def sla_pa() -> bool:
    """Väcker TV:n och byter till Pi:ns ingång. Tre försök (TV:n kan vara seg ur viloläget)."""
    for forsok in range(3):
        ok, _ = _cec("--image-view-on")
        if ok:
            _cec("--active-source", "phys-addr=1.0.0.0")
            log.info("TV:n påslagen (försök %d)", forsok + 1)
            _spara("pa", True)
            return True
        time.sleep(10)
    log.warning("TV:n svarade inte på HDMI-CEC: slå på Anynet+/SIMPLINK/HDMI-CEC i TV:ns inställningar")
    _spara("pa", False)
    return False


def stang_av() -> bool:
    ok, _ = _cec("--standby")
    log.info("TV:n i viloläge: %s", "ok" if ok else "svarade inte")
    _spara("av", ok)
    return ok


def svarar() -> bool:
    return _cec("--give-device-power-status")[0]


def lage() -> str:
    """'pa' | 'av' (viloläge) | 'svarar_inte' (CEC avstängt i TV:n eller TV:n helt avstängd)."""
    ok, ut = _cec("--give-device-power-status", "--wait-for-msgs", "1", "-t", "5")
    if not ok:
        return "svarar_inte"
    ut = ut.lower()
    if "pwr-state: on" in ut and "to-on" not in ut:
        return "pa"
    if "standby" in ut or "to-on" in ut:
        return "av"
    return "pa"                     # svarade men utan läge: räkna som på


def vakta() -> str:
    """Var 5:e minut under öppettid: har TV:n stängt av sig, slå på den igen. Loggas i data/tv.jsonl."""
    l = lage()
    if l == "av":
        log.warning("TV:n hade stängt av sig: slår på den igen")
        ok = sla_pa()
        try:
            with open(konfig.DATA_DIR / "tv.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"tid": time.strftime("%Y-%m-%dT%H:%M:%S"), "handelse": "stangd_av_sig",
                                    "pa_igen": ok}) + chr(10))
        except OSError:
            pass
    return l


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    val = sys.argv[1] if len(sys.argv) > 1 else "status"
    print({"pa": sla_pa, "av": stang_av, "status": svarar, "lage": lage}[val]())
