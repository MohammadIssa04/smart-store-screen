from __future__ import annotations

from pathlib import Path


class Kanal:
    """Gränssnitt för en publiceringskanal.

    publicera() får posten och den färdiga videon och returnerar en dict
    som sparas i post["kanaler"][namn]. ta_bort() avpublicerar (flyttar
    till arkiv, tar ner utkast osv.) men raderar aldrig något."""

    namn = "bas"

    def publicera(self, post: dict, video: Path) -> dict:
        raise NotImplementedError

    def ta_bort(self, post: dict) -> None:
        raise NotImplementedError
