"""Kollar att Pixabay- och Facebook-nycklarna i butiksbot.env fungerar. Skriver aldrig ut nycklarna.
    set -a; . ./butiksbot.env; set +a; .venv/bin/python kolla_nycklar.py"""
import os

import httpx


def maska(text: str) -> str:
    for n in ("PIXABAY_API_KEY", "PEXELS_API_KEY", "FACEBOOK_SIDTOKEN"):
        v = os.environ.get(n, "").strip()
        if v:
            text = text.replace(v, "…")
    return text


pix = os.environ.get("PIXABAY_API_KEY", "").strip()
if not pix:
    print("Pixabay: ingen nyckel i butiksbot.env")
else:
    r = httpx.get("https://pixabay.com/api/", params={"key": pix, "q": "potato", "per_page": 3}, timeout=20)
    if r.status_code == 200:
        print(f"Pixabay: OK ({r.json().get('totalHits', 0)} bilder på 'potato')")
    else:
        print("Pixabay: FEL", r.status_code, maska(r.text[:150]))

pex = os.environ.get("PEXELS_API_KEY", "").strip()
if not pex:
    print("Pexels: ingen nyckel i butiksbot.env")
else:
    r = httpx.get("https://api.pexels.com/v1/search", headers={"Authorization": pex},
                  params={"query": "potato", "per_page": 3}, timeout=20)
    print(f"Pexels: OK ({r.json().get('total_results', 0)} bilder på 'potato')" if r.status_code == 200
          else f"Pexels: FEL {r.status_code}")

fb = os.environ.get("FACEBOOK_SIDTOKEN", "").strip()
version = os.environ.get("FACEBOOK_GRAPH_VERSION", "v23.0").strip()
if not fb:
    print("Facebook: ingen nyckel i butiksbot.env")
else:
    r = httpx.get(f"https://graph.facebook.com/{version}/me", params={"fields": "name", "access_token": fb}, timeout=20)
    if r.status_code != 200:
        print("Facebook: FEL", r.status_code, maska(r.text[:200]))
    else:
        print("Facebook: nyckeln hör till sidan:", r.json().get("name"))
        r = httpx.get(f"https://graph.facebook.com/{version}/me/posts",
                      params={"fields": "message,full_picture,created_time", "limit": 3, "access_token": fb}, timeout=20)
        if r.status_code == 200:
            for p in r.json().get("data", []):
                print("  inlägg", p.get("created_time", "")[:10], (p.get("message") or "(utan text)")[:50].replace("\n", " "),
                      "| bild" if p.get("full_picture") else "| ingen bild")
        else:
            print("Facebook: kan inte läsa inläggen", r.status_code, maska(r.text[:200]))
        d = httpx.get(f"https://graph.facebook.com/{version}/debug_token",
                      params={"input_token": fb, "access_token": fb}, timeout=20)
        if d.status_code == 200:
            utgar = d.json().get("data", {}).get("expires_at", None)
            print("  nyckeln går ut:", "aldrig" if utgar == 0 else utgar)
