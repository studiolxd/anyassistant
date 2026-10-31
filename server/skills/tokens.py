"""How a sentence reaches a skill: its words as said and plain (lowercase, no accents), and
numbers. Part of what a skill is (Skill.answer(text, toks)); what the words mean is in the
plugin skills-language."""

import re
import unicodedata
from dataclasses import dataclass


@dataclass
class Token:
    word: str  # as said: «mamá»
    plain: str  # to compare: «mama»


def plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def tokens(text: str) -> list[Token]:
    """Words, numbers (with decimals: «3,5», «3.5») and «%»."""
    found = re.finditer(r"\d+(?:[.,]\d+)?|%|[^\W\d_]+", text)
    return [Token(m.group(), plain(m.group()).replace(",", ".")) for m in found]
