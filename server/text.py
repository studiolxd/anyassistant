"""Shared text utilities."""

import re
import unicodedata


def words(text: str) -> list[str]:
    """«¡Apágate, Jarvis!» → ["apagate", "jarvis"]: lowercase, no accents, letters only."""
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return re.findall(r"[^\W\d_]+", plain)  # any letter, any language
