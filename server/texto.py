"""Utilidades de texto compartidas."""

import re
import unicodedata


def normalizar(texto: str) -> list[str]:
    """«¡Apágate, Jarvis!» → ["apagate", "jarvis"]"""
    sin_tildes = unicodedata.normalize("NFKD", texto.lower())
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return re.findall(r"[a-zñ]+", sin_tildes)
