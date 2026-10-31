"""Confirmation: your «yes» before actions that change something, for any LLM.

- Jarvis's own tools marked needs_yes (@tool(…, needs_yes=True)): a gate in tools/
  refuses the call until you answer «yes» to exactly that call.
- Claude Code: the hook bin/jarvis-confirm (installed by llm-claude while this is on).
- Hermes: its approvals wait here for your answer (llm-hermes).

The pending action and your answer live in store.py (files, so separate processes
agree). While one waits, the face shows «question»; your next sentence answers it.
Off (by hand only: it is a security plugin), nothing asks and everything goes through.
"""

import json
import logging

import i18n
import options
import paths
import settings
from skills import Skill, skill
from text import words
from tools import ToolError, gate

from . import store

log = logging.getLogger("confirmation")
ASK = ("This action changes data and needs the user's confirmation. Don't assume it: ask them in one "
       "short sentence whether to do it (say what you are going to do). If they answer yes, repeat "
       "exactly the same call; if not, don't do it.")

options.add(options.Option("confirm_wait", store.WAIT, "seconds to answer «yes» to an action that changes something",
                           "security", "float", live=True))
options.add(options.Option("confirm_valid", store.VALID, "seconds a «yes» stays valid", "security", "float", live=True))


def asking() -> bool:
    """permissions.json «confirm» (on unless it says false): the same switch Claude's hook follows."""
    try:
        permissions = json.loads(paths.PERMISSIONS.read_text())
    except (OSError, ValueError):
        permissions = {}
    return permissions.get("confirm", True) is not False


def waiting() -> dict | None:
    """The action waiting for your answer, if any (the face shows «question»)."""
    return store.pending(settings.get("confirm_wait") or store.WAIT)


def is_yes(text: str) -> bool:
    """«Yes», «Sure, do it»… but not «No, wait» nor long sentences."""
    heard = set(words(text))
    return (0 < len(heard) <= 6 and not heard & set(i18n.L.list("commands.no"))
            and bool(heard & set(i18n.L.list("commands.yes"))))


@gate
def _ask_first(name: str, arguments: dict):
    """A tool that changes something: only with your «yes» to exactly this call (once)."""
    if not asking():
        return
    sign = store.signature("jarvis", name, arguments)
    if store.confirmed(sign):
        return
    store.ask(sign, f"jarvis: {name} {json.dumps(arguments, ensure_ascii=False)}")
    raise ToolError(ASK)


def answer(text: str) -> bool | None:
    """Your sentence answers the waiting action: «yes» authorizes it, anything else cancels it.
    None if nothing was waiting; True if the sentence was only for that (Hermes's approvals,
    «consume»), False if it still goes on to the LLM (it repeats the call)."""
    if not waiting():
        return None
    yes = is_yes(text)
    found = store.answer(yes, settings.get("confirm_valid") or store.VALID)
    action = settings.private(found.get("action", ""))
    if yes:
        log.info("confirmed: %s", action)
    else:
        log.info("not confirmed («%s»): %s", settings.private(text), action)
    return bool(found.get("consume"))


@skill
class Answer(Skill):
    """Before any other skill: the sentence that answers a waiting action."""
    order = 0
    local = False

    def hear(self, text: str, jarvis) -> bool:
        if answer(text):
            jarvis.show_heard(text)  # resolved by whoever asked: not a new message
            return True
        return False
