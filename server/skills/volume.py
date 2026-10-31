"""«Sube / baja el volumen», «volumen al 70», «al máximo»: its voice and sounds (settings «volume»)."""

import i18n
import settings
from skills import Skill, skill
from skills.parse import number, words
from tools import tool

STEP = 20


def set_volume(percent: int) -> str:
    percent = max(5, min(100, int(percent)))
    settings.save(volume=percent)
    settings.refresh()
    return i18n.L("speech.volume", percent=percent)


@skill
class Volume(Skill):
    order = 30

    def answer(self, text, toks):
        said = {t.plain for t in toks}
        if not said & words("volume"):
            return None
        current = settings.get("volume") or 100
        amount = next((number(toks, i)[0] for i in range(len(toks)) if number(toks, i) and (
            toks[i].plain[0].isdigit() or toks[i].plain not in ("un", "una", "a", "an"))), None)
        if said & words("max"):
            return set_volume(100)
        if said & words("min"):
            return set_volume(10)
        if amount is not None:
            return set_volume(amount)
        if said & words("down"):
            return set_volume(current - STEP)
        if said & words("up"):
            return set_volume(current + STEP)
        return None  # «el volumen está demasiado alto»: for the interpreter or the LLM


@tool("Its voice's volume, 5–100 %.", name="set_volume")
def volume_tool(percent: int) -> str:
    return set_volume(percent)
