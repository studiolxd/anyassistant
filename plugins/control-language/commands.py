"""What a sentence asks the computer for, if it is one of these commands (the words of each
language in the locales, «control»):

    «abre Safari», «abre la aplicación Notas»          → app      (only if an app answers to it)
    «ejecuta el atajo Buenas noches», «atajo Descansar» → shortcut
    «abre el archivo informe septiembre»                → file
    «abre la carpeta Descargas»                         → folder
    «ve a la ventana de Mail», «go to the Mail window»  → window
    «cambia a Safari», «switch to Chrome»               → switch   (a window or an app; only if one answers)
    «teclea hola, ¿qué tal?», «type hello»              → type     (the text as it was said)
    «¿qué puedo decir?»                                 → help

Conservative on purpose: a sentence is a command only when it starts with one of the verbs
(after the assistant's name) and names something short; what is said in any other way, or
names nothing, goes to the LLM («abre la puerta», «¿me abres el correo?», «escribe un correo a
mamá»). Pure, so the decisions are tested sentence by sentence.
"""

import re
import unicodedata
from dataclasses import dataclass

import i18n
import settings

MAX_NAME = 5  # words a name may have: more is a sentence, not a command


@dataclass
class Command:
    kind: str  # app, shortcut, file, folder, window, switch, type, help
    name: str  # what was named, plain («crom»), or the text to type as it was said


def _list(key: str) -> list[str]:
    return i18n.L.list(f"control.{key}")


def _plain(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in plain if not unicodedata.combining(c))


def words(text: str) -> list[str]:
    """«¡Abre Chrome 2!» → ["abre", "chrome", "2"]: lowercase, no accents, letters and digits."""
    return re.findall(r"[^\W_]+", _plain(text))


def _heard(text: str) -> list[str]:
    """The words, without the assistant's name («Jarvis, abre Safari»)."""
    name = set(words(settings.get("name") or "Jarvis"))
    return [w for w in words(text) if w not in name]


def _after_phrase(text: str, phrase: list[str]) -> str:
    """What follows the phrase in the text as it was said («Teclea Hola, ¿qué tal?.» → «Hola, ¿qué tal?»),
    with the assistant's name and a final full stop dropped."""
    name = set(words(settings.get("name") or "Jarvis"))
    tokens = [m for m in re.finditer(r"[^\W_]+", text) if _plain(m.group()) not in name]
    if [_plain(m.group()) for m in tokens[:len(phrase)]] != phrase:
        return ""
    rest = text[tokens[len(phrase) - 1].end():].strip()
    rest = rest.lstrip(",:;.-¡¿ ").rstrip()
    return rest[:-1].rstrip() if rest.endswith(".") and not rest.endswith("...") else rest


def parse(text: str) -> Command | None:
    """The command in the sentence, or None if it isn't one (the LLM's)."""
    heard = _heard(text)
    if not heard:
        return None
    for phrase in sorted(_list("type"), key=len, reverse=True):  # any length: a dictated sentence
        phrase_words = phrase.split()
        if heard[:len(phrase_words)] == phrase_words and len(heard) > len(phrase_words):
            typed = _after_phrase(text, phrase_words)
            return Command("type", typed) if typed else None
    if len(heard) > 12:
        return None  # a sentence, not a command
    if " ".join(heard) in _list("help"):
        return Command("help", "")
    fillers = set(_list("fillers")) | set(_list("app_words"))
    kept = [w for w in heard if w not in fillers]
    if not kept:
        return None
    verb, rest = kept[0], kept[1:]
    not_a_name = set(_list("not_a_name"))

    def named(found: list[str]) -> str | None:
        if not found or len(found) > MAX_NAME or set(found) & not_a_name:
            return None
        return " ".join(found)

    shortcut = next((i for i, w in enumerate(kept) if w in _list("shortcut")), None)
    if shortcut is not None:
        if shortcut == 0 or verb in _list("run"):
            name = named(kept[shortcut + 1:])
            return Command("shortcut", name) if name else None
        return None
    marker = next((i for i, w in enumerate(kept) if w in _list("file") or w in _list("folder")), None)
    if marker is not None:
        if marker > 0 and (verb in _list("open") or verb in _list("go")):
            name = named(kept[marker + 1:])
            kind = "folder" if kept[marker] in _list("folder") else "file"
            return Command(kind, name) if name else None
        return None
    window = next((i for i, w in enumerate(kept) if w in _list("window")), None)
    if window is not None:
        if window > 0 and verb in _list("go"):
            name = named([w for i, w in enumerate(rest, 1) if i != window])
            return Command("window", name) if name else None
        return None
    if verb in _list("go"):
        name = named(rest)
        return Command("switch", name) if name else None
    if verb in _list("open"):
        name = named(rest)
        return Command("app", name) if name else None
    return None


def help_sentence() -> str:
    """What it understands, to say aloud."""
    return i18n.L("speech.control_help")
