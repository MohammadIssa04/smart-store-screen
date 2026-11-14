"""Pi:ns läge för appens statussida: temperatur, belastning, minne, disk, tjänster, Bluetooth-ampen,
senaste säkerhetskopia och kända problem (från timkontrollen, samma som går till Telegram)."""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter

import halsa
import oversatt
from api.musik import styr

router = APIRouter(prefix="/api", tags=["system"])
_cache: dict = {"tid": 0.0, "data": None}


@router.get("/status")
async def status():
    if _cache["data"] is None or time.time() - _cache["tid"] > 10:      # högst var 10:e sekund
        d = await asyncio.to_thread(halsa.matvarden)
        m = await styr("status")
        d["ampen_ansluten"] = bool(m.get("ampen_ansluten")) if "fel" not in m else None
        _cache.update(tid=time.time(), data=d)
    d = dict(_cache["data"])
    d["problem"] = [oversatt.t(p) for p in d.get("problem", [])]
    return d
