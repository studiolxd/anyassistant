"""«Recarga las herramientas» (after authorizing an MCP server) and «reiníciate»."""

import logging

import i18n
from skills import Skill, skill
from text import words

log = logging.getLogger("skills")


def command(text: str) -> str | None:
    """«Reload the tools» → "reload"; «Restart» → "restart". Only short commands."""
    heard = words(text)
    if not 0 < len(heard) <= 5:
        return None
    if any(w.startswith(tuple(i18n.L.list("commands.reload"))) for w in heard):
        return "reload"
    if set(heard) & set(i18n.L.list("commands.restart")):
        return "restart"
    return None


async def _reload(jarvis):
    log.info("reloading tools")
    await jarvis.llm.reload()
    jarvis.say(i18n.L("speech.reloaded"))


@skill
class Restart(Skill):
    order = 13
    local = False

    def hear(self, text, jarvis):
        found = command(text)
        if not found:
            return False
        jarvis.show_heard(text)
        if found == "reload":
            jarvis.later(_reload(jarvis))
        else:
            jarvis.restart(i18n.L("speech.restarting"))
        return True
