"""Plan B: when the LLM can't answer (llm.Unavailable: no network, a usage limit, signed
out, its process died), another answers that sentence, and says so first: «Claude
isn't answering; I'll answer with the local model».

Settings «llm_fallback»: auto (Apple's local model if this Mac has it), the name of an
LLM, or none. The next sentence tries the usual LLM again.
"""

import logging

import llm
import options
import settings
from options import Option

log = logging.getLogger("llm")
LOCAL = ["apple"]  # what «auto» tries: models that run on this computer, with no network
_ready: dict[str, llm.LLM] = {}


def _choices():
    return ["auto", "none"] + list(llm.available())


options.add(Option("llm_fallback", "auto", "if the LLM can't answer, another one does: auto (Apple's local model "
                   "if there is one), an LLM's name, or none", "assistant", "choice", _choices, live=True))


def chosen(current: str) -> str | None:
    """Which LLM answers instead of «current», or None."""
    wanted = settings.get("llm_fallback") or "auto"
    candidates = LOCAL if wanted == "auto" else [] if wanted == "none" else [wanted]
    return next((name for name in candidates
                 if name != current and name in llm.available() and llm.ready(name) is None), None)


def instead(current) -> llm.LLM | None:
    """The other LLM, ready to answer (made the first time it is needed)."""
    name = chosen(current.name)
    if not name:
        return None
    if name not in _ready:
        log.info("plan B: %s answers when %s can't", name, current.name)
        _ready[name] = llm.create(name, model=None, mcp=settings.get("mcp"))
    return _ready[name]
