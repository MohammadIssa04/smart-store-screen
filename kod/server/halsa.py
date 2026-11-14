"""Hälsokontroll: boten kollar varje timme att allt fungerar och skriver till ägaren i Telegram om något
är fel – så att ägaren ser problemet innan pappa märker det. Samma problem rapporteras högst en gång per
dygn; när det är löst skickas "OK igen".

Kollar: tjänsterna, att skylten spelar (kl 10-21), disken, temperaturen/strypningen, etikettskrivaren
(kl 10-21), musiken (kl 10-21) och om Gemini har varit nåbar senaste timmen."""
from __future__ import annotations

import json
import logging
import shutil
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path

import konfig

log = logging.getLogger("butiksbot.halsa")
STATUS = konfig.DATA_DIR / "halsa.json"
OPPET = (10, 21)


def _sh(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return ""


def _mpv(prop: str):
    try:
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(2)
        s.connect("/tmp/mpv.sock")
        s.sendall((json.dumps({"command": ["get_property", prop]}) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            buf += s.recv(4096)
        s.close()
        for rad in buf.decode().splitlines():
            d = json.loads(rad)
            if "error" in d:
                return d.get("data")
    except Exception:
        return None


def problem() -> dict[str, str]:
    """{nyckel: kort svensk beskrivning} för allt som är fel just nu."""
    ut: dict[str, str] = {}
    oppet = OPPET[0] <= datetime.now().hour < OPPET[1]
    for s in ("butiksbot", "butiksapi", "butiksmusik"):
        if _sh(["systemctl", "--user", "is-active", s]) != "active":
            ut[f"tjanst_{s}"] = f"Tjänsten {s} kör inte."
    if _sh(["systemctl", "is-active", "skylt.service"]) != "active":
        ut["skylt_tjanst"] = "Skylten (skylt.service) kör inte."
    elif oppet:
        t1 = _mpv("time-pos")
        time.sleep(3)
        t2 = _mpv("time-pos")
        if t1 is None or t2 is None or t1 == t2:
            ut["skylt_spelar"] = "Skylten verkar stå still (videon rör sig inte)."
    ledigt = shutil.disk_usage(konfig.DATA_DIR).free / 1e9
    if ledigt < 5:
        ut["disk"] = f"Nästan full disk: {ledigt:.1f} GB kvar."
    temp = _sh(["vcgencmd", "measure_temp"]).replace("temp=", "").replace("'C", "")
    try:
        if float(temp) >= 78:
            ut["temp"] = f"Pi:n är mycket varm: {temp} °C."
    except ValueError:
        pass
    strypt = _sh(["vcgencmd", "get_throttled"])
    if strypt and strypt != "throttled=0x0":
        ut["strypning"] = f"Pi:n har strypt farten (värme eller för svag strömadapter): {strypt}."
    if oppet:
        try:
            import etikett
            if etikett.skrivarstatus(max_alder=300) == "inte_ansluten":
                ut["skrivare"] = "Etikettskrivaren svarar inte (avstängd eller utom räckhåll)."
        except Exception:
            pass
        try:
            s = socket.socket(socket.AF_UNIX)
            s.settimeout(3)
            s.connect(konfig.STYR_SOCK)
            s.sendall(b'{"cmd": "status"}\n')
            st = json.loads(s.recv(65536).decode())
            s.close()
            if not st.get("spelar") and not st.get("pausad"):
                ut["musik"] = "Musiken spelar inte (och är inte pausad)."
        except Exception:
            ut["musik"] = "Musikspelaren svarar inte."
    try:
        import backup
        f = backup.senaste()
        if f is None or time.time() - f.stat().st_mtime > 2 * 86400 + 3600:
            ut["backup"] = "Ingen säkerhetskopia de senaste två nätterna."
    except Exception:
        pass
    logg = _sh(["journalctl", "--user", "-u", "butiksbot", "-u", "butiksapi", "--since", "-1h", "-o", "cat", "--no-pager"])
    if logg.count("svarade 429") + logg.count("svarade 503") >= 20 and "Igenkänd vara" not in logg:
        ut["gemini"] = "Gemini (AI:n) har varit överbelastad eller slut på gratiskvot senaste timmen."
    return ut


def matvarden() -> dict:
    """Pi:ns läge just nu för appens statussida (snabbt, under en sekund; inga nycklar eller adresser).
    Kända problem kommer från senaste timkontrollen (samma som går till Telegram)."""
    def aktiv(*cmd) -> bool:
        return _sh(list(cmd)) == "active"
    ut: dict = {"tid": datetime.now().isoformat(timespec="seconds")}
    try:
        ut["temp"] = round(float(_sh(["vcgencmd", "measure_temp"]).replace("temp=", "").replace("'C", "")), 1)
    except ValueError:
        try:
            ut["temp"] = round(int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000, 1)
        except (OSError, ValueError):
            ut["temp"] = None
    try:
        import os
        ut["cpu"] = round(100 * os.getloadavg()[0] / (os.cpu_count() or 4))     # belastning senaste minuten, %
    except (OSError, AttributeError):
        ut["cpu"] = None
    try:
        mem = {r.split(":")[0]: int(r.split()[1]) for r in Path("/proc/meminfo").read_text().splitlines()}
        tot, ledigt = mem["MemTotal"], mem.get("MemAvailable", mem.get("MemFree", 0))
        ut["ram"] = {"anvant_gb": round((tot - ledigt) / 1048576, 1), "totalt_gb": round(tot / 1048576, 1),
                     "procent": round(100 * (tot - ledigt) / tot)}
    except (OSError, KeyError, ValueError, ZeroDivisionError):
        ut["ram"] = None
    d = shutil.disk_usage(konfig.DATA_DIR)
    ut["disk"] = {"ledigt_gb": round(d.free / 1e9, 1), "totalt_gb": round(d.total / 1e9, 1),
                  "procent": round(100 * d.used / d.total)}
    strypt = _sh(["vcgencmd", "get_throttled"])
    ut["strypt"] = bool(strypt) and strypt != "throttled=0x0"
    ut["tjanster"] = {"skylt": aktiv("systemctl", "is-active", "skylt.service"),
                      "x25-vakt": aktiv("systemctl", "is-active", "x25-vakt.service"),
                      "musik": aktiv("systemctl", "--user", "is-active", "butiksmusik"),
                      "bot": aktiv("systemctl", "--user", "is-active", "butiksbot")}
    try:
        upp = float(Path("/proc/uptime").read_text().split()[0])
        ut["igang_timmar"] = round(upp / 3600, 1)
    except (OSError, ValueError):
        ut["igang_timmar"] = None
    try:
        ut["problem"] = [v["text"] for v in json.loads(STATUS.read_text(encoding="utf-8")).values()]
    except (OSError, ValueError, KeyError, TypeError):
        ut["problem"] = []
    ut["backup"] = senaste_backup()
    return ut


def senaste_backup() -> str | None:
    try:
        import backup
        f = backup.senaste()
        return datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="minutes") if f else None
    except Exception:
        return None


def kontrollera() -> list[str]:
    """Meddelanden att skicka till ägaren (nya problem, och problem som lösts). Sparar läget."""
    try:
        gammalt = json.loads(STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        gammalt = {}
    nu = time.time()
    aktuella = problem()
    medd = []
    for k, text in aktuella.items():
        senast = gammalt.get(k, {}).get("skickat", 0)
        if nu - senast > 24 * 3600:
            medd.append("⚠️ " + text)
            gammalt[k] = {"text": text, "skickat": nu}
    for k in [k for k in gammalt if k not in aktuella]:
        medd.append("✅ OK igen: " + gammalt.pop(k)["text"])
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(gammalt, ensure_ascii=False), encoding="utf-8")
    for m in medd:
        log.info("Hälsa: %s", m)
    return medd


if __name__ == "__main__":
    print(problem() or "Allt OK")
