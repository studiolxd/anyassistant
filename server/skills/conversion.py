"""«¿Cuántos kilómetros son 5 millas?», «20 grados en fahrenheit» (units.py)."""

import i18n
from skills import Skill, skill
from skills.calc import spoken
from skills.units import convert, name


@skill
class Conversion(Skill):
    order = 34

    def answer(self, text, toks):
        found = convert(toks)
        if not found:
            return None
        value, source, result, target = found
        return i18n.L("speech.convert", value=spoken(value), source=name(source, value),
                      result=spoken(result), target=name(target, result))
