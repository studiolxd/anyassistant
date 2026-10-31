"""«Use Claude», «Cambia a Hermes»: a command, not for the LLM. Apple's model has no
tools, so this is the way back from it."""

import logging

import i18n
import llm
import settings
from skills import Skill, skill
from text import words

log = logging.getLogger("skills")


def command(text: str) -> str | None:
    """«Use Claude», «Cambia a Hermes» → "claude", "hermes"."""
    heard = [w for w in words(text) if w not in words(settings.get("name", "Jarvis"))]
    if not 0 < len(heard) <= 5 or heard[0] not in i18n.L.list("commands.switch"):
        return None
    rest = heard[1:]
    for name, spoken in llm.spoken_names().items():
        if any(w in spoken for w in rest) and all(w in spoken or len(w) <= 3 or w in i18n.L.list("commands.llm_words")
                                                 for w in rest):
            return name
    return None


@skill
class ChooseLLM(Skill):
    order = 12
    local = False

    def hear(self, text, assistant):
        name = command(text)
        if not name:
            return False
        assistant.show_heard(text)
        why = llm.ready(name)
        if name == settings.get("llm"):
            assistant.say(i18n.L("speech.llm_same", llm=name.capitalize()))
        elif why:
            log.info("can't switch to %s: %s", name, why)
            assistant.say(i18n.L("speech.llm_unavailable", llm=name.capitalize()))
        else:
            log.info("switching to %s", name)
            settings.save(llm=name, llm_model=None)
            assistant.restart(i18n.L("speech.llm_changing", llm=name.capitalize()))
        return True
