"""Publiceringskanaler. Lägg till nya kanaler (instagram.py, facebook.py,
tiktok.py ...) som underklasser till Kanal och registrera dem i KANALER."""
from .bas import Kanal
from .skylt import Skylt

KANALER: list[Kanal] = [Skylt()]
