"""Enkel JSON-lagring av publicerade erbjudanden.

Varje post är en dict, så senare kanaler (Instagram, etiketter ...) kan
lägga till egna fält under post["kanaler"][namn] utan schemaändringar.

Två processer använder lagret (Telegram-boten och app-API:t): filen läses om före varje
läsning och skrivs under ett fillås, så att ingen skriver över den andras ändringar."""
from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


class Lager:
    def __init__(self, fil: Path):
        self.fil = fil

    @contextmanager
    def _last(self):
        self.fil.parent.mkdir(parents=True, exist_ok=True)
        with open(self.fil.with_name(self.fil.name + ".las"), "w") as l:
            fcntl.flock(l, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(l, fcntl.LOCK_UN)

    @property
    def poster(self) -> list[dict]:
        try:
            return json.loads(self.fil.read_text(encoding="utf-8")).get("poster", [])
        except (OSError, ValueError):
            return []

    def _skriv(self, poster: list[dict]) -> None:
        tmp = self.fil.with_suffix(".tmp")
        tmp.write_text(json.dumps({"poster": poster}, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.fil)

    def spara(self, post: dict) -> None:
        with self._last():
            poster = self.poster
            for i, p in enumerate(poster):
                if p["id"] == post["id"]:
                    poster[i] = post
                    break
            else:
                poster.append(post)
            self._skriv(poster)

    def hamta(self, post_id: str) -> dict | None:
        return next((p for p in self.poster if p["id"] == post_id), None)

    def aktiva(self) -> list[dict]:
        return sorted((p for p in self.poster if p.get("status") == "aktiv"), key=lambda p: p["utgar"])


def tid(s: str) -> datetime:
    return datetime.fromisoformat(s)
