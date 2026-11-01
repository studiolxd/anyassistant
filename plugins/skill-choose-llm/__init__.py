"""«Use Claude», «Cambia a Hermes»: a command, not for the LLM. Apple's model has no
tools, so this is the way back from it. «Usa Gemini aquí»: only this device's (the plugin
«devices»), from its next question, without restarting; without «aquí», every device's (and this
one follows it again)."""

import logging

import hub
import i18n
import kernel
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
    allowed = i18n.L.list("commands.llm_words") + i18n.L.list("commands.here")
    for name, spoken in llm.spoken_names().items():
        if any(w in spoken for w in rest) and all(w in spoken or len(w) <= 3 or w in allowed for w in rest):
            return name
    return None


def here(text: str) -> bool:
    """«… aquí»: only for this device."""
    return bool(set(words(text)) & set(i18n.L.list("commands.here")))


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
        session, devices = hub.of(assistant), kernel.module("devices")
        device = session.device if session else None
        own = devices.llm_of(device) if devices and device else None
        general = settings.get("llm")
        if devices and device and here(text):  # this device's only, fixed (whatever the default becomes)
            if name == own:
                assistant.say(i18n.L("speech.llm_same", llm=name.capitalize()))
            elif why:
                assistant.say(i18n.L("speech.llm_unavailable", llm=name.capitalize()))
            else:
                devices.set_llm(device, name)
                assistant.say(i18n.L("speech.llm_here", llm=name.capitalize()))
            return True
        if devices and device and own and name == general:  # «usa Claude», the default: this one follows it again
            devices.set_llm(device, None)
            assistant.say(i18n.L("speech.llm_here", llm=name.capitalize()))
            return True
        if name == general:
            assistant.say(i18n.L("speech.llm_same", llm=name.capitalize()))
        elif why:
            log.info("can't switch to %s: %s", name, why)
            assistant.say(i18n.L("speech.llm_unavailable", llm=name.capitalize()))
        else:
            log.info("switching to %s", name)
            if own:  # every device's now: this one follows it again
                devices.set_llm(device, None)
            settings.save(llm=name, llm_model=None)
            assistant.restart(i18n.L("speech.llm_changing", llm=name.capitalize()))
        return True
