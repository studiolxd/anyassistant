"""Simple sums: «cuánto es 23 por 47», «what's 15 percent of 80», «2 elevado a 10».

Two numbers and an operation (words per language: locale skills.operators); no
eval, no expressions: anything else goes to the LLM.
"""

import math

from plugins.skills_language import spoken_number as spoken  # noqa: F401 — «1081», «3,5»
from plugins.skills_language.parse import Token, number, vocabulary, words

SQUARED = {"cuadrado": 2, "squared": 2, "cubo": 3, "cubed": 3}


def operator(word: str) -> str | None:
    for symbol, names in vocabulary()["operators"].items():
        if word in names:
            return symbol
    return None


def calculate(toks: list[Token]) -> float | None:
    """The result, if the sentence is a question about two numbers and nothing else."""
    triggers = words("math")
    i = 0
    while i < len(toks) and toks[i].plain in triggers | {"el", "the", "la"}:
        i += 1
    if i == 0:
        return None  # «cuánto es», «what's»… must be said
    first = number(toks, i)
    if not first:
        return None
    a, j = first
    ops, k = [], j
    while k < len(toks):  # the operation's words, before the second number
        word = toks[k].plain
        if word in SQUARED:
            return a ** SQUARED[word] if _only_fillers(toks, k + 1) else None
        if operator(word):  # before numbers: «ciento» is also 100
            ops.append(operator(word))
        elif word not in {"a", "de", "of", "by", "to", "the", "al", "el", "la"}:
            break
        k += 1
    second = number(toks, k)
    if not ops or not second or not _only_fillers(toks, second[1]):
        return None
    b = second[0]
    if "%" in ops:  # «15 por ciento de 80» («por» is also «times»)
        return a * b / 100
    op = ops[0]
    if op == "/" and b == 0:
        return math.inf
    return {"+": a + b, "-": a - b, "*": a * b, "/": a / b if b else math.inf, "^": a ** b}[op]


def _only_fillers(toks: list[Token], i: int) -> bool:
    return all(t.plain in {"por", "favor", "please"} for t in toks[i:])
