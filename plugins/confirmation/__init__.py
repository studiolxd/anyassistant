"""Confirmation: your «yes» before actions that change something, for any LLM.

- Jarvis's own tools marked needs_yes (@tool(…, needs_yes=True)): a gate in tools/
  refuses the call until you answer «yes» to exactly that call.
- Claude Code: the hook bin/anyassistant-confirm (installed by llm-claude while this is on).
- Hermes: its approvals wait here for your answer (llm-openai).
- Codex: it asks Jarvis before each MCP tool (let_through()); Gemini CLI and OpenCode too, and
  wait meanwhile (decision()).

The pending action and your answer live in store.py (files, so separate processes
agree). While one waits, the face shows «question»; your next sentence answers it.
Off (by hand only: it is a security plugin), nothing asks and everything goes through.
"""

import asyncio
import json
import logging
import time

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
    sign = store.signature("anyassistant", name, arguments)
    if store.confirmed(sign):
        return
    store.ask(sign, f"anyassistant: {name} {json.dumps(arguments, ensure_ascii=False)}")
    raise ToolError(ASK)


def free(server: str, tool: str) -> bool:
    """Whether an LLM's MCP tool may run without your «yes», with the same rule as Claude's hook:
    reads (get_, list_…), Jarvis's own tools (they ask themselves), or «confirm» off."""
    return server == "anyassistant" or tool.startswith(store.READS) or not asking()


def let_through(server: str, tool: str, arguments: dict) -> bool:
    """An LLM's CLI asks whether one of its MCP tools may run (Codex's approvals): if it isn't
    free, only with your «yes» to exactly this call, once. Otherwise it is left waiting (False): the
    CLI refuses it, the LLM asks you, and after your «yes» it calls it again."""
    if free(server, tool):
        return True
    sign = store.signature(f"mcp__{server}__{tool}", arguments)
    if store.confirmed(sign):
        return True
    store.ask(sign, f"{server}: {tool} {json.dumps(arguments, ensure_ascii=False)}")
    return False


async def decision(sign: str, action: str) -> bool:
    """Asks you about an action that waits meanwhile (Gemini's and OpenCode's approvals, like
    Hermes's): your answer is for whoever asked, not a new message for the LLM («consume»).
    True if you said «yes» in time; anything else, or nothing, is a «no»."""
    store.ask(sign, action, consume=True)
    deadline = time.time() + (settings.get("confirm_wait") or store.WAIT)
    while time.time() < deadline:
        await asyncio.sleep(0.2)
        if store.confirmed(sign):
            return True
        if not store.waiting(sign):
            return False  # the answer wasn't «yes»
    if store.waiting(sign):
        store.answer(False)  # too late: dropped
    return False


def ask_about(action: str) -> str:
    """Something with no tool behind it waits for your «yes» (what a voice it didn't recognise well
    said: the plugin «voices»); the answer is for whoever asked, not a new message for the LLM.
    Its signature, to know whether it is still waiting (waiting_for)."""
    sign = store.signature("ask", action, time.time())
    store.ask(sign, action, consume=True)
    return sign


def waiting_for(sign: str) -> bool:
    """Whether that question is the one waiting for your answer."""
    return bool(waiting()) and store.waiting(sign)


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

    def hear(self, text: str, assistant) -> bool:
        if answer(text):
            assistant.show_heard(text)  # resolved by whoever asked: not a new message
            return True
        return False
