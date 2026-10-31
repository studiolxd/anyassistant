"""«¿Cuánto es 23 por 47?», «el 15 por ciento de 80», «2 elevado a 10» (calc.py)."""

import i18n
from skills import Skill, skill
from skills.calc import calculate, spoken


@skill
class Arithmetic(Skill):
    order = 33

    def answer(self, text, toks):
        result = calculate(toks)
        return None if result is None else i18n.L("speech.math", result=spoken(result))
