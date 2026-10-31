"""«Speak English», «Háblame en inglés»: saves the language and restarts in it."""

import logging

import i18n
import settings
from skills import Skill, skill
from text import words

log = logging.getLogger("skills")


def command(text: str) -> str | None:
    """«Speak Spanish», «Háblame en inglés» → "es", "en". Understood in any language.

    A verb of some locale's commands.language first, a language's name in some
    locale's «languages» and nothing else but short linking words («to», «en»…):
    «¿Quién habla inglés en Suiza?» or «Pasa el correo a inglés» are not commands.
    Any language because Parakeet may well write «Speak Spanish» while in Spanish.
    """
    heard = [w for w in words(text) if w not in words(settings.get("name", "Jarvis"))]
    if not 0 < len(heard) <= 6:
        return None
    locales = [i18n.Locale(code) for code in i18n.available()]
    if not any(heard[0] in locale.list("commands.language") for locale in locales):
        return None
    for locale in locales:
        for code, name in locale.data["languages"].items():
            name = words(name)
            for i in range(1, len(heard) - len(name) + 1):
                rest = heard[1:i] + heard[i + len(name):]
                if heard[i:i + len(name)] == name and code in i18n.available() and all(len(w) <= 3 for w in rest):
                    return code
    return None


@skill
class Language(Skill):
    order = 10
    local = False

    def hear(self, text, assistant):
        code = command(text)
        if not code:
            return False
        assistant.show_heard(text)
        name = i18n.L.data["languages"].get(code, code)
        if code == i18n.L.code:
            assistant.say(i18n.L("speech.language_same", language=name))
        else:
            log.info("switching to %s", code)
            settings.save(language=code)
            assistant.restart(i18n.L("speech.language_changing", language=name))
        return True
