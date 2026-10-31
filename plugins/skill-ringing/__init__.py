"""While a timer, alarm or reminder rings: «pospón (10 minutos)» snoozes it, and only
words meant to stop it stop it («para», «apaga la alarma», «vale»): its own tone,
transcribed («Kimbo.»), is ignored."""

import logging
import time

import i18n
import settings
from plugins.skill_alarms import timers
from plugins.skills_language import spoken_duration
from skills import Skill, skill
from plugins.skills_language.parse import duration, tokens
from text import words

log = logging.getLogger("skills")


def stops_it(text: str) -> bool:
    """«Para», «apaga la alarma», «vale», «cancélalo»…: words meant to stop it."""
    vocabulary = i18n.L.data["skills"]["words"]
    meant = set(i18n.L.list("commands.stop")) | set(i18n.L.list("commands.yes")) | set(i18n.L.list("commands.sleep"))
    meant |= set(vocabulary["cancel"]) | set(vocabulary["timer"]) | set(vocabulary["alarm"]) | set(vocabulary["reminder"])
    meant |= set(i18n.L.list("commands.camera_off"))  # «apaga»
    return bool(set(words(text)) & meant)


def snooze(item: dict, text: str) -> str:
    span = duration(tokens(text))
    seconds = span.value if span else (settings.get("snooze_minutes") or 5) * 60
    timers.add(item["kind"], time.time() + seconds, item.get("label", ""), item.get("device"), item.get("where", ""))
    return i18n.L("speech.snoozed", duration=spoken_duration(seconds))


@skill
class Ringing(Skill):
    order = 20
    local = False

    def hear(self, text, assistant):
        if assistant.rang and set(words(text)) & set(i18n.L.data["skills"]["words"]["snooze"]):
            assistant.show_heard(text)
            item = assistant.rang
            assistant.stop()
            assistant.say(snooze(item, text))
            return True
        if not assistant.ringing:
            return False
        if stops_it(text):
            assistant.show_heard(text)
            assistant.stop()
        else:  # not a word for it: dropped
            log.info("ignored while ringing: «%s»", settings.private(text))
        return True
