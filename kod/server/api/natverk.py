"""Vilka nätverk API:t svarar på: bara Tailscale och Pi:ns eget lokala nät (butikens wifi/kabel).

API:t lyssnar på alla adresser men avvisar varje anrop som inte kommer från de näten. Det lokala
nätet läses av löpande, så det fungerar även om routern ger Pi:n en ny adress. Interna nät som
containerd/docker (br-*, docker*, veth*, cni*) räknas inte."""
from __future__ import annotations

import ipaddress
import json
import subprocess
import time

TAILSCALE = [ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48")]
LOKALA_GRANSSNITT = ("eth", "wlan", "en", "wl")       # eth0, wlan0, enp..., wlp...
_cache: dict = {"tid": 0.0, "nat": [], "adresser": []}


def _las() -> None:
    if time.time() - _cache["tid"] < 30:
        return
    nat, adresser = [], []
    try:
        data = json.loads(subprocess.run(["ip", "-j", "-4", "addr", "show"], capture_output=True,
                                         text=True, timeout=5).stdout or "[]")
    except Exception:
        data = []
    for g in data:
        if not g.get("ifname", "").startswith(LOKALA_GRANSSNITT) or "UP" not in g.get("flags", []):
            continue
        for a in g.get("addr_info", []):
            if a.get("family") == "inet":
                nat.append(ipaddress.ip_network(f"{a['local']}/{a['prefixlen']}", strict=False))
                adresser.append(a["local"])
    _cache.update(tid=time.time(), nat=nat, adresser=adresser)


def via(ip: str) -> str | None:
    """'tailscale', 'lokalt', 'pi' (anrop från Pi:n själv) eller None = avvisas."""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if a.is_loopback:
        return "pi"
    if any(a in n for n in TAILSCALE):
        return "tailscale"
    _las()
    if any(a in n for n in _cache["nat"]):
        return "lokalt"
    return None


def lokala_adresser() -> list[str]:
    """Pi:ns adresser på det lokala nätet (för mDNS-annonsen)."""
    _las()
    return list(_cache["adresser"])
