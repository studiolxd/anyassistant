"""«Go to sleep» / «apágate»: it falls asleep at once (otherwise, after follow_up
seconds without talking). Close words count too: Parakeet writes «Apparaté»,
«Aparate»…; «apaga (la cámara)» doesn't (locale commands.sleep, commands.not_sleep).
"""

from difflib import SequenceMatcher

import i18n
from skills import Skill, skill
from text import words

SIMILARITY = 0.75


def is_sleep_command(text: str) -> bool:
    """A short command with the sleep word or something close (not «how do I turn off the oven?»)."""
    found = words(text)
    return len(found) <= 4 and any(
        SequenceMatcher(None, w, command).ratio() >= SIMILARITY
        for w in found
        if w not in i18n.L.list("commands.not_sleep")  # «apaga (la cámara)» is not «apágate»
        for command in i18n.L.list("commands.sleep")
    )


@skill
class Sleep(Skill):
    order = -1  # before anything else: even an action waiting for a «yes» stays waiting
    local = False
    harmless = True

    def takes(self, text, toks) -> bool:
        return is_sleep_command(text)

    def hear(self, text: str, assistant) -> bool:
        if not is_sleep_command(text):
            return False
        assistant.sleep(text)
        return True
