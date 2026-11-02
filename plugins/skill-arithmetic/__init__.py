"""«¿Cuánto es 23 por 47?», «el 15 por ciento de 80», «2 elevado a 10» (calc.py)."""

import i18n
from skills import Skill, skill
from plugins.skills_language import spoken_number as spoken

from .calc import calculate


@skill
class Arithmetic(Skill):
    order = 33
    harmless = True

    def answer(self, text, toks):
        result = calculate(toks)
        return None if result is None else i18n.L("speech.math", result=spoken(result))
