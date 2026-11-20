"""Bildtjänsten på hemservern (CT 114 butik-bild): räknar ut friläggningsmasken åt Pi:n.

Samma modeller och samma beräkning som video/frilagg.mask på Pi:n, men på en snabbare dator.
Pi:n gör allt annat själv (vit bakgrund, kanter, uppfräschning) och klarar sig utan tjänsten.

    POST /mask?modell=isnet-general-use   (kropp: bilden, rubrik X-Nyckel)  -> PNG (gråskala, bildens storlek)
    GET  /hej                                                              -> {"ok": true}

Nyckeln står i /etc/butik-bild.env (BILD_NYCKEL, rättigheter 600) och i Pi:ns butiksbot.env (BILDSERVER_NYCKEL).
Modellerna ligger i /opt/bild/assets/ (kopior från Pi:n)."""
from __future__ import annotations

import hmac
import io
import os
import threading
from pathlib import Path

import numpy as np
from fastapi import FastAPI, Header, Query, Request, Response
from PIL import Image

ASSETS = Path(os.environ.get("BILD_ASSETS", "/opt/bild/assets"))
MODELLER = {
    "isnet-general-use": ("isnet-general-use.onnx", (0.5, 0.5, 0.5), (1.0, 1.0, 1.0), 1024, False),
    "u2netp": ("u2netp.onnx", (0.485, 0.456, 0.406), (0.229, 0.224, 0.225), 320, False),
}
_sessioner: dict = {}
_las = threading.Lock()
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def _sess(namn: str):
    with _las:
        if namn not in _sessioner:
            import onnxruntime as ort
            so = ort.SessionOptions()
            so.intra_op_num_threads = int(os.environ.get("BILD_TRADAR", "4"))
            _sessioner[namn] = ort.InferenceSession(str(ASSETS / MODELLER[namn][0]), so,
                                                    providers=["CPUExecutionProvider"])
        return _sessioner[namn]


def mask(img: Image.Image, modell: str) -> np.ndarray:
    _, medel, std, sz, _ = MODELLER[modell]
    rgb = img.convert("RGB")
    a = np.asarray(rgb.resize((sz, sz), Image.LANCZOS)).astype(np.float32)
    a = a / max(float(a.max()), 1e-6)
    a = (a - np.array(medel)) / np.array(std)
    a = a.transpose(2, 0, 1)[None].astype(np.float32)
    s = _sess(modell)
    ut = s.run(None, {s.get_inputs()[0].name: a})[0][0, 0]
    ut = (ut - ut.min()) / (ut.max() - ut.min() + 1e-6)
    return np.asarray(Image.fromarray((ut * 255).astype(np.uint8)).resize(rgb.size, Image.LANCZOS))


@app.get("/hej")
def hej():
    return {"ok": True}


@app.post("/mask")
async def maskera(request: Request, modell: str = Query("isnet-general-use"),
                  x_nyckel: str = Header("")):
    nyckel = os.environ.get("BILD_NYCKEL", "")
    if not nyckel or not hmac.compare_digest(x_nyckel, nyckel):
        return Response(status_code=401)
    if modell not in MODELLER:
        return Response(status_code=400)
    data = await request.body()
    if not data or len(data) > 25_000_000:
        return Response(status_code=400)
    import asyncio
    img = Image.open(io.BytesIO(data))
    m = await asyncio.to_thread(mask, img, modell)
    buf = io.BytesIO()
    Image.fromarray(m).save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png")


_render_las = None


@app.post("/render")
async def render(request: Request, x_nyckel: str = Header("")):
    """Hela reklamvideon: samma kod som på Pi:n (butiksbot/video, kopierad till /opt/bild/butiksbot).
    Formulär: param (JSON med rendera()-argumenten) + fotos (filer). Svar: mp4, info i rubriken X-Info."""
    import asyncio
    import base64
    import json
    import sys
    import tempfile
    global _render_las
    nyckel = os.environ.get("BILD_NYCKEL", "")
    if not nyckel or not hmac.compare_digest(x_nyckel, nyckel):
        return Response(status_code=401)
    form = await request.form()
    p = json.loads(form["param"])
    fotos = form.getlist("fotos")
    if not fotos or len(fotos) > 12:
        return Response(status_code=400)
    sys.path.insert(0, "/opt/bild/butiksbot")
    from video import animation
    if _render_las is None:
        _render_las = asyncio.Lock()
    with tempfile.TemporaryDirectory(prefix="render_") as d:
        mapp = Path(d)
        sokvagar = []
        for i, f in enumerate(fotos):
            sok = mapp / Path(f.filename or f"foto{i}").name
            sok.write_bytes(await f.read())
            sokvagar.append(sok)
        ut = mapp / "video.mp4"
        async with _render_las:
            res = await animation.rendera_har(
                sokvagar, p["namn"], p["pris"], bool(p["fynd"]), ut, int(p.get("exemplar") or 1),
                p.get("stil") or "rad", tuple(p.get("overgang") or ("fade", "fade")), bool(p.get("glid_hoger", True)),
                p.get("justering") or None, p.get("variant"), p.get("langd"))
        data = ut.read_bytes()
    res.pop("video", None)
    info = base64.b64encode(json.dumps(res, default=list).encode()).decode()
    return Response(data, media_type="video/mp4", headers={"X-Info": info})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("BILD_PORT", "8590")), server_header=False)
