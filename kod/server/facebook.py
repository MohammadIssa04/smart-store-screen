"""Facebook-inlägg -> annons. Pappa skickar länken till ett inlägg på butikens Facebook-sida; boten hämtar
inläggets text och bild via Facebooks officiella Graph API och gör en annons av dem (som vanligt: video,
förhandsvisning, pappa väljer Publicera).

Kräver en sidnyckel (Page access token) för butikens sida i butiksbot.env:
    FACEBOOK_SIDTOKEN=...        (behörighet pages_read_engagement / pages_read_user_content)
    FACEBOOK_GRAPH_VERSION=v23.0 (valfri)
Utan nyckel: boten ber pappa skicka bilden direkt i stället. Sidor läses aldrig utan Facebooks API.
"""
from __future__ import annotations

import logging
import os
import re

import httpx

log = logging.getLogger("butiksbot.facebook")
LANK = re.compile(r"https?://(?:www\.|m\.|web\.|business\.)?(?:facebook\.com|fb\.com|fb\.watch)/\S+", re.I)
MAX_BILD = 15 * 1024 * 1024


class FacebookFel(Exception):
    """Kort svensk förklaring för pappa."""


def hitta_lank(text: str) -> str | None:
    m = LANK.search(text or "")
    return m.group(0).rstrip(".,)") if m else None


def finns() -> bool:
    return bool(os.environ.get("FACEBOOK_SIDTOKEN", "").strip())


def _nycklar(lank: str) -> set[str]:
    """Delar av länken som känns igen i inläggets permalänk: pfbid…, story_fbid, siffer-id, photo fbid."""
    delar = set(re.findall(r"pfbid[A-Za-z0-9]+", lank))
    delar |= set(re.findall(r"(?:story_fbid|fbid|v)=(\d+)", lank))
    delar |= set(re.findall(r"/(?:posts|photos|videos|reel)/(?:[^/?]+/)?(\d{6,})", lank))
    return delar


async def hamta(lank: str) -> dict:
    """{'text', 'bild' (bytes eller None), 'lank'} för inlägget. Kastar FacebookFel."""
    token = os.environ.get("FACEBOOK_SIDTOKEN", "").strip()
    if not token:
        raise FacebookFel("Jag kan inte läsa Facebook-länkar. Öppna bilden i inlägget, tryck Dela och välj "
                          "Min Butik (eller spara bilden och skicka den här), så gör jag annonsen av den.")
    version = os.environ.get("FACEBOOK_GRAPH_VERSION", "v23.0").strip()
    nycklar = _nycklar(lank)
    async with httpx.AsyncClient(timeout=30) as c:
        try:
            r = await c.get(f"https://graph.facebook.com/{version}/me/posts",
                            params={"fields": "id,message,full_picture,permalink_url,created_time",
                                    "limit": 50, "access_token": token})
        except httpx.HTTPError as e:
            raise FacebookFel("Fick ingen kontakt med Facebook. Försök igen om en stund.") from e
        if r.status_code in (400, 401, 403):
            log.error("Facebook svarade %s: %s", r.status_code, r.text[:200].replace(token, "…"))
            raise FacebookFel("Facebook-nyckeln fungerar inte längre. Säg till ägaren.")
        if r.status_code >= 400:
            raise FacebookFel("Facebook svarade inte. Försök igen om en stund.")
        inlagg = r.json().get("data") or []
        traff = None
        for p in inlagg:
            perma, pid = p.get("permalink_url", ""), p.get("id", "")
            if lank.rstrip("/") == perma.rstrip("/") or any(n in perma or pid.endswith(n) for n in nycklar):
                traff = p
                break
        if traff is None:
            raise FacebookFel("Jag hittar inte det inlägget bland butikens senaste 50 inlägg på Facebook. "
                              "Är det från butikens egen sida?")
        bild = None
        if traff.get("full_picture"):
            try:
                b = await c.get(traff["full_picture"], follow_redirects=True)
                if b.status_code == 200 and len(b.content) <= MAX_BILD:
                    bild = b.content
            except httpx.HTTPError:
                log.warning("Kunde inte hämta inläggets bild")
    text = (traff.get("message") or "").strip()
    log.info("Facebook-inlägg %s: %d tecken text, bild=%s", traff.get("id"), len(text), bool(bild))
    return {"text": text, "bild": bild, "lank": traff.get("permalink_url", lank)}
