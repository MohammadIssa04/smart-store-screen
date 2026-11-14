"""Uppdateringar av appen utan att skicka APK-filer för hand.

Den senaste appen läggs på Pi:n (av Mohammad, från datorn):
    data/appversion/minbutik.apk      appen (samma signering som den installerade, annars vägrar Android)
    data/appversion/version.json      {"kod": 16, "namn": "1.3", "nytt": ["Musiken först", "..."]}
Appen frågar vid start (GET /api/app/version) och visar "Ny version finns" om koden är högre än sin egen.
Trycker man Uppdatera hämtas filen (GET /api/app/apk) och Android frågar om installationen.
"""
from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from konfig import DATA_DIR

router = APIRouter(prefix="/api/app", tags=["appen"])
MAPP = DATA_DIR / "appversion"      # inte data/app: där ligger telefonernas inloggningar


def _version() -> dict | None:
    try:
        v = json.loads((MAPP / "version.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    apk = MAPP / "minbutik.apk"
    if not isinstance(v.get("kod"), int) or not apk.is_file():
        return None
    return {"kod": v["kod"], "namn": str(v.get("namn", "")), "nytt": [str(x) for x in v.get("nytt", [])][:8],
            "storlek_mb": round(apk.stat().st_size / 1e6, 1)}


@router.get("/version")
async def version():
    return _version() or {"kod": 0}


@router.get("/apk")
async def apk():
    if not _version():
        return JSONResponse({"fel": "Ingen uppdatering finns."}, status_code=404)
    return FileResponse(MAPP / "minbutik.apk", media_type="application/vnd.android.package-archive",
                        filename="minbutik.apk")
