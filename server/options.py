"""Every option, in one place: the command line, settings.json, what applies without
restarting, the checks, the README's table and (soon) the app's settings window
are all made from OPTIONS.

    python server/options.py markdown    the README's table
    python server/options.py json        for a settings window
"""

import argparse
import json
import sys
from dataclasses import dataclass


@dataclass
class Option:
    name: str  # as in settings.json; --name-with-dashes on the command line
    default: object
    help: str
    group: str
    kind: str = "text"  # text, bool, int, float, choice, json, secret (in the keychain, never in settings.json)
    choices: object = None  # a list, or a function that lists them (plugins, themes…)
    live: bool = False  # applies without restarting
    screen: bool = False  # the page shows it (sent in /config)
    flag: str = ""  # another command-line name (--lang)
    plugin: str | None = None  # the plugin that added it (None: the core's); its texts are in its locales
    empty: str = ""  # what happens when it isn't set («the language's voice»), for the app
    hidden: bool = False  # not in the settings (edited elsewhere: the mail accounts, on their page)
    keychain: tuple = ()  # a secret: (service, account) in the system's keychain
    prefer: tuple = ()  # an engine: the default is the first of these this computer has (resolve())

    def options(self) -> list:
        return list(self.choices()) if callable(self.choices) else list(self.choices or [])

    def resolve(self):
        """Its default for this computer: the first it prefers that is there (the Mac's engines on
        the Mac, others on Windows and Linux). Once the plugins are loaded."""
        if self.prefer:
            there = self.options()
            self.default = next((p for p in self.prefer if p in there), there[0] if there else self.default)


def _plugins(package):
    def available():
        module = __import__(package)
        return module.available()
    return available


def _languages():
    import i18n
    return i18n.available()



def _detail_levels():
    import llm
    return list(llm.DETAIL_LEVELS)


OPTIONS = [
    # The plugins
    Option("plugins", None, 'which plugins are on or off, if not as they come: {"memory": true, "tap-to-wake": false}',
           "plugins", "json", live=True),
    # The assistant
    Option("name", "Jarvis", "the assistant's name: its wake word, the page's title, what the LLM calls itself", "assistant"),
    Option("language", None, "en, es…: what it speaks and understands (default: the system's)", "assistant",
           "choice", _languages, flag="--lang", empty="the system's language"),
    Option("llm", "claude", "the LLM: claude, codex, gemini, opencode, apple, openai, ollama, hermes…", "assistant", "choice", _plugins("llm")),
    Option("llm_model", None, "the LLM's model (for Claude: sonnet, opus, haiku…)", "assistant",
           empty="the LLM's own"),
    Option("mcp", None, ".mcp.json with the MCP servers (default: your data folder's)", "assistant",
           empty="the one in your data folder"),
    Option("instructions", None, "yours, added to the LLM's (text or a list of lines): who you are, how to talk…",
           "assistant", "longtext", live=True, empty="none"),
    Option("detail", "neutral", "how much it says: concise, neutral, detailed or one of detail_levels", "assistant",
           "choice", lambda: list(__import__("llm").detail_levels()), live=True),
    Option("detail_levels", None, 'more levels, or other texts for these: {"name": "instruction for the prompt"}',
           "assistant", "dict", live=True, empty="only the built-in ones"),
    Option("ignore_others", True, "the LLM stays quiet when what it hears is clearly not for it", "assistant",
           "bool", live=True),
    # Listening and speaking
    Option("stt", "parakeet", "speech recognition: parakeet, mlx-whisper…", "voice", "choice", _plugins("stt"),
           prefer=("parakeet", "parakeet-onnx", "faster-whisper", "mlx-whisper")),
    Option("stt_model", None, "its model", "voice", empty="the engine's own"),
    Option("stt_unload_minutes", 30, "minutes without transcribing before the speech recognition model leaves memory "
           "(0: never); it comes back when needed", "voice", "int", live=True),
    Option("tts", "avspeech", "its voice engine: avspeech, macos, kokoro, piper… or none", "voice", "choice",
           lambda: _plugins("tts")() + ["none"], prefer=("avspeech", "kokoro", "piper", "macos", "none")),
    Option("voice", None, "the voice (default: the language's); one, or one per language: "
           '{"es": "Mónica", "en": "Samantha"}', "voice", "json", empty="the language's"),
    Option("rate", None, "words per minute", "voice", "int", empty="the voice's own"),
    Option("volume", 100, "its voice and sounds, 5–100 %", "voice", "int", live=True),
    Option("wake", "whisper", "the wake word engine: whisper, openwakeword… or none", "voice", "choice",
           lambda: _plugins("wake")() + ["none"], prefer=("whisper", "none")),
    Option("wake_word", None, "the word or model (default: its name)", "voice", empty="its name"),
    Option("threshold", None, "how sure the wake word must be (each engine has its own default)", "voice", "float",
           empty="the engine's own"),
    Option("vad", "silero", "voice activity detection: silero…", "voice", "choice", _plugins("vad")),
    Option("silence", 0.6, "seconds of silence that end a sentence", "voice", "float"),
    Option("follow_up", 20, "seconds it keeps listening without its name after it last spoke or heard you",
           "voice", "float", live=True),
    Option("echo_guard", 1.2, "seconds without listening after speaking (its own echo)", "voice", "float"),
    Option("voice_interrupt", True, "«Jarvis, stop» while it speaks", "voice", "bool", live=True),
    # In /config too («screen»): the apps read it, the Mac's stops its microphone by it.
    Option("pause_when_microphone_busy", True, "it stops listening while another app uses the device's microphone "
           "(a call, a meeting); back when it ends", "voice", "bool", live=True, screen=True),
    Option("listen_while_speaking", True, "it keeps listening while it speaks and stops if someone talks over it, "
           "telling its own echo by loudness (experimental)", "voice", "bool", live=True),
    Option("echo_match", 0.8, "how alike the loudness of what it hears must be to what it sends to count as its "
           "own echo (0–1, with listen_while_speaking)", "voice", "float", live=True, hidden=True),
    Option("tap_to_stop", True, "tapping the screen stops it talking", "voice", "bool", live=True),
    Option("fillers", True, "«One moment, let me check» when a tool is slow", "voice", "bool", live=True),
    # Skills
    Option("skills", True, "time, date, timers, alarms, reminders, sums, units and volume, without the LLM",
           "assistant", "bool", live=True),
    # The screen
    # Privacy and security
    Option("log_transcripts", False, "write what it hears and says to the log (to debug); otherwise only lengths",
           "security", "bool", live=True),
    # The server
    Option("host", "0.0.0.0", "the address it listens on", "server"),
    Option("port", 8080, "the port (bin/anyassistant reads it too)", "server", "int"),
    Option("mode", "assistant", "assistant, transcribe (only shows what it hears) or parrot (repeats it)", "server",
           "choice", _plugins("brain")),
    Option("record", False, "saves everything that arrives to a WAV, in the cache's «recordings» (to debug)",
           "server", "bool"),
]

def add(option: Option):
    """A plugin's own option (call it when the plugin loads)."""
    import kernel

    option.plugin = option.plugin or kernel.current()
    if option.name not in {o.name for o in OPTIONS}:
        OPTIONS.append(option)
        BY_NAME[option.name] = option
        if option.live:
            LIVE.add(option.name)
        if option.screen:
            SCREEN.add(option.name)


BY_NAME = {o.name: o for o in OPTIONS}
LIVE = {o.name for o in OPTIONS if o.live}
SCREEN = {o.name for o in OPTIONS if o.screen}
GROUPS = {"plugins": "Plugins", "assistant": "Assistant", "memory": "Memory", "voice": "Voice", "skills": "Skills",
          "screen": "Screen", "security": "Privacy and security", "server": "Server"}


def parser() -> argparse.ArgumentParser:
    """The command line: one --option per option (--no-option to turn a bool off), the plugins' too."""
    import kernel

    kernel.load_all()  # they add their options when they load
    resolve_defaults()
    made = argparse.ArgumentParser(description="Jarvis's server. Options also come from settings.json.")
    for o in OPTIONS:
        flag = o.flag or "--" + o.name.replace("_", "-")
        kwargs = {"dest": o.name, "default": o.default, "help": o.help}
        if o.kind == "bool":
            kwargs["action"] = argparse.BooleanOptionalAction
        elif o.kind in ("int", "float"):
            kwargs["type"] = int if o.kind == "int" else float
        elif o.kind in ("json", "dict", "longtext"):
            kwargs["type"] = _json_or_text
        made.add_argument(flag, **kwargs)
    return made


def resolve_defaults():
    """The engines' defaults for this computer (the plugins loaded)."""
    for o in OPTIONS:
        o.resolve()


def _json_or_text(value: str):
    try:
        return json.loads(value)
    except ValueError:
        return value


def check(values: dict) -> list[str]:
    """What is wrong with these values («face: smiley is not one of…»)."""
    problems = []
    for o in OPTIONS:
        value = values.get(o.name)
        if value is None or o.kind != "choice" or o.name == "detail":  # detail: below, with these values' levels
            continue
        allowed = o.options()
        if value not in allowed:
            problems.append(f"{o.name}: «{value}» is not one of {', '.join(map(str, allowed))}")
    levels = {**_levels_now(), **(values.get("detail_levels") or {})}
    if values.get("detail") and values["detail"] not in levels:
        problems.append(f"detail: «{values['detail']}» is not one of {', '.join(levels)}")
    return problems


def _levels_now() -> dict:
    import llm
    return llm.DETAIL_LEVELS


def markdown() -> str:
    """The README's table of options, by group."""
    lines = []
    for group, title in GROUPS.items():
        lines += [f"**{title}**", "", "| Option | Default | |", "|---|---|---|"]
        for o in OPTIONS:
            if o.group == group:
                default = "—" if o.default is None else f"`{json.dumps(o.default)}`"
                live = "" if o.live else " *(restarts)*"
                shown = o.help.replace("{name}", "Jarvis")  # a help that names it: the default name here
                lines.append(f"| `{o.name}` | {default} | {shown}{live} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def describe() -> list[dict]:
    """For a settings window: every option with what it needs to be shown and edited."""
    return [{"name": o.name, "default": o.default, "help": o.help, "group": o.group, "kind": o.kind,
             "choices": o.options() if o.kind == "choice" else None, "live": o.live} for o in OPTIONS]


if __name__ == "__main__":
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    import kernel

    kernel.load_all()  # plugins may bring options of their own
    if sys.argv[1:] == ["markdown"]:
        print(markdown(), end="")
    elif sys.argv[1:] == ["json"]:
        print(json.dumps(describe(), ensure_ascii=False, indent=2))
    else:
        print(__doc__)
