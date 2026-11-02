"""«Stop» / «para» said on its own: it stops talking (if it hadn't already, when it
heard its name), stops an answer it is still thinking, or an alarm ringing; nothing
goes to the LLM. «Jarvis, stop» while it speaks interrupts it before this (the ear).
"""

import i18n
from skills import Skill, skill
from text import words


def is_stop_command(text: str) -> bool:
    """«Stop», «Quiet!», «Para»: only to stop it talking, nothing to answer."""
    found = words(text)
    return 0 < len(found) <= 2 and bool(set(found) & set(i18n.L.list("commands.stop")))


@skill
class Stop(Skill):
    order = -2
    local = False
    harmless = True

    def takes(self, text, toks) -> bool:
        return is_stop_command(text)

    def hear(self, text: str, assistant) -> bool:
        if not is_stop_command(text):
            return False
        assistant.hush()
        return True
