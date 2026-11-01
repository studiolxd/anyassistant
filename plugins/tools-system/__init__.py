"""Jarvis's settings and itself, as tools: status, name, voice, language, LLM, detail
level, reloading and restarting.

Settings are saved to settings.json and applied after the answer
(plugins/brain-assistant): some at once, voice, name and language with a restart.
Reloading and restarting also wait for the answer to end: doing it in the middle
would cut off the LLM while it is still using the tool.
"""

import re
import subprocess
import sys

import i18n
import kernel
import settings
import tools
from tools import ToolError, tool


def voices() -> dict[str, str]:
    """{name: locale} of the Mac's voices, from `say -v ?` (none elsewhere, for now)."""
    if sys.platform != "darwin":
        return {}
    output = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    found = {}
    for line in output.splitlines():
        match = re.match(r"(.+?)\s+([a-z]{2}_[A-Z]{2})\s+#", line)
        if match:
            name = match.group(1).strip()
            found[name] = found[name.split(" (")[0]] = match.group(2)  # «Mónica (Español (España))» or «Mónica»
    return found


@tool("Whether the device and its camera are connected, the language, the LLM, eyes and memory.")
def get_status() -> str:
    device = tools.session()
    camera = bool(device and device.frames)
    return (f"device connected: {'yes' if device else 'no'}; camera: {'yes' if camera else 'no'}; "
            f"language: {i18n.L.code}; LLM: {settings.get('llm')} ({settings.get('llm_model') or 'default'}); "
            f"eyes: {'on' if kernel.enabled('eyes') else 'off'}; memory: {memory.mode() if (memory := kernel.module('memory')) else 'off'}")


@tool("Your name, skin (and the ones there are), detail level, voice and language.")
def get_settings() -> str:
    import llm
    
    return (f"name: {settings.get('name')}; skin: {settings.get('skin')} (skins: {', '.join(page.skins.available()) if (page := kernel.module('page')) else '-'}); "
            f"detail: {settings.get('detail') or 'neutral'} (levels: {', '.join(llm.detail_levels())}); "
            f"voice: {settings.get('voice') or 'the language default'}; language: {i18n.L.code} "
            f"(available: {', '.join(i18n.available())})")


@tool("Your voice in the current language: a macOS voice name (e.g. Mónica, Samantha).", needs_yes=True)
def set_voice(voice: str) -> str:
    found = voices()
    if voice not in found:
        raise ToolError(f"there is no voice «{voice}» on this Mac")
    if not found[voice].startswith(i18n.L.code):
        raise ToolError(f"«{voice}» speaks {found[voice]}, not {i18n.L.code}")
    current = settings.load().get("voice")
    current = current if isinstance(current, dict) else ({} if current is None else {i18n.L.code: current})
    settings.save(voice={**current, i18n.L.code: voice.split(" (")[0]})
    return "Saved: it restarts with the new voice when you finish answering."


@tool("Your name, which is also your wake word («Hey …»).", needs_yes=True)
def set_name(name: str) -> str:
    if not re.fullmatch(r"[^\W\d_]+( [^\W\d_]+)?", name.strip()):
        raise ToolError("a name is one or two words, letters only")
    settings.save(name=name.strip())
    return "Saved: it restarts with the new name (and wake word) when you finish answering."


@tool("The language you speak and understand (a code such as en, es).", needs_yes=True)
def set_language(language: str) -> str:
    if language not in i18n.available():
        raise ToolError(f"available languages: {', '.join(i18n.available())}")
    settings.save(language=language)
    return "Saved: it restarts in that language when you finish answering."


def llm_ready(name: str) -> str | None:
    import llm

    return llm.ready(name)


@tool("The LLMs Jarvis can use, which one is in use and whether each is available.")
def get_llms() -> str:
    import llm

    lines = []
    for name in llm.available():
        why = llm_ready(name)
        current = name == settings.get("llm")
        model = settings.get("llm_model") or "its default model"
        lines.append(f"{name}: " + ("in use, " + model + "; " if current else "")
                     + ("available" if why is None else f"not available ({why})"))
    return "\n".join(lines)


@tool("Switch to another LLM (claude, codex, gemini, apple, openai…: get_llms), optionally with a model (for "
      "Claude: sonnet, opus, haiku…; empty for the default); for every device, or only the one the user is "
      "talking to (this_device: «usa Gemini aquí»; from its next question, no restart). Apple's can't use "
      "tools: to come back, the user says «use Claude».", needs_yes=True)
def set_llm(llm: str, model: str = "", this_device: bool = False) -> str:
    import llm as plugins

    if this_device:
        devices, device = kernel.module("devices"), tools.session()
        if not devices or not device or not device.device:
            raise ToolError("no device connected")
        if llm not in plugins.available():
            raise ToolError(f"installed LLMs: {', '.join(plugins.available())}")
        devices.set_llm(device.device, llm)  # fixed for it, whatever the default becomes
        return f"Saved: this device uses {llm} from its next question."
    if llm not in plugins.available():
        raise ToolError(f"installed LLMs: {', '.join(plugins.available())}")
    why = llm_ready(llm)
    if why:
        raise ToolError(f"{llm} can't be used: {why}")
    if model and not re.fullmatch(r"[\w.\-\[\]:]+", model):
        raise ToolError("that isn't a model name")
    settings.save(llm=llm, llm_model=model or None)
    return f"Saved: it restarts with {llm} when you finish answering."


@tool("How much you say in your answers: concise, neutral, detailed (or another level from get_settings), "
      "when the user asks you to be briefer or to give more detail.")
def set_detail(level: str) -> str:
    import llm

    if level not in llm.detail_levels():
        raise ToolError(f"levels: {', '.join(llm.detail_levels())}")
    settings.save(detail=level)
    return "Saved: from your next answer on."


SCREEN = {"show_time": "the time (asleep)", "show_date": "the date (asleep)", "show_hint": "«Say “Hey, …”» (asleep)",
          "show_status": "«Listening», «Thinking…»", "show_heard": "what the user said (the transcription)",
          "show_answer": "what you answer", "show_timers": "timers, alarms and reminders",
          "show_stats": "the connection's figures", "history": "how many earlier sentences stay (a number)",
          "clock": "12 or 24 hours, or auto"}


@tool("Show or hide parts of the screen, on every device and with any skin: " + "; ".join(
      f"{k}: {v}" for k, v in SCREEN.items()) + ". value: yes/no for show_*, a number for history, 12/24/auto for "
      "clock. Use this (not a new skin) when the user wants something on the screen shown or hidden.",
      choices={"setting": list(SCREEN)})
def set_screen(setting: str, value: str) -> str:
    import options

    if setting not in SCREEN:
        raise ToolError(f"settings: {', '.join(SCREEN)}")
    said = str(value).strip().lower()
    if setting.startswith("show_"):
        if said not in {"yes", "no", "true", "false", "on", "off", "show", "hide", "sí", "si", "1", "0"}:
            raise ToolError("value: yes or no")
        chosen = said in {"yes", "true", "on", "show", "sí", "si", "1"}
    elif setting == "history":
        try:
            chosen = max(0, int(said))
        except ValueError:
            raise ToolError("value: a number (0: none)") from None
    else:
        chosen = said
    problems = options.check({setting: chosen})
    if problems:
        raise ToolError("; ".join(problems))
    settings.save(**{setting: chosen})
    return "Saved: the screen changes when you finish answering."


@tool("Create a detail level, or change one's instruction, when the user asks for a new way of answering "
      "(«a teacher mode that explains step by step»). The instruction is added to your prompt: write it in "
      "English, one or two sentences, about how much and how to answer (it is spoken: no lists). When asking "
      "for confirmation, say it in the user's language.", needs_yes=True)
def add_detail_level(name: str, instruction: str) -> str:
    import llm

    name, instruction = name.strip().lower(), instruction.strip()
    if not re.fullmatch(r"[^\W_][\w -]{0,29}", name):
        raise ToolError("a level's name is a word or two (up to 30 characters)")
    if not 10 <= len(instruction) <= 500:
        raise ToolError("the instruction must be a sentence or two (10 to 500 characters)")
    levels = settings.load().get("detail_levels") or {}
    settings.save(detail_levels={**levels, name: instruction})
    verb = "Changed" if name in llm.detail_levels() else "Added"
    return f"{verb}: the level «{name}». To use it: set_detail."


@tool("Remove a detail level the user created (built-in ones go back to their text).", needs_yes=True)
def remove_detail_level(name: str) -> str:
    import llm

    name = name.strip().lower()
    levels = settings.load().get("detail_levels") or {}
    if name not in levels:
        if name in llm.DETAIL_LEVELS:
            raise ToolError(f"«{name}» is built in and can't be removed")
        raise ToolError(f"no level «{name}»; levels: {', '.join(llm.detail_levels())}")
    del levels[name]
    changes = {"detail_levels": levels}
    if settings.get("detail") == name and name not in llm.DETAIL_LEVELS:
        changes["detail"] = "neutral"  # it was in use
    settings.save(**changes)
    if name in llm.DETAIL_LEVELS:
        return f"Removed your text for «{name}»: it is back to the built-in one."
    return "Removed." + (" Back to neutral." if "detail" in changes else "")


@tool("Read the MCP servers and permissions again (after the user authorized one).", needs_yes=True)
def reload_tools() -> str:
    tools.requested.add("reload")
    return "It reloads its tools when you finish answering."


@tool("Restart the whole server.", needs_yes=True)
def restart() -> str:
    tools.requested.add("restart")
    return "It restarts when you finish answering."
