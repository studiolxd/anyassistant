"""Lists and notes, by voice and without the LLM:

    «Añade leche, huevos y pan a la lista de la compra»     «¿Qué hay en la lista de la compra?»
    «Quita el pan de la lista»                              «Vacía la lista de tareas»
    «Toma nota de que el fontanero viene el jueves»         «¿Qué notas tengo?»

How they are said is in this plugin's locales (lists.*: patterns over the sentence without
accents or punctuation); what is kept, as you said it, in lists.json in your data folder.
A list with another name («la lista de regalos») is made the first time. The LLM has
them too, as tools.
"""

import json
import re
import time
import unicodedata

import i18n
import paths
from skills import Skill, skill
from plugins.skills_language import spoken_list
from tools import ToolError, tool

PATH = paths.HOME / "lists.json"
DROP = "¿?¡!.;:\"«»“”'’"


def load() -> dict:
    try:
        data = json.loads(PATH.read_text())
    except (OSError, ValueError):
        data = {}
    return {"lists": data.get("lists", {}), "notes": data.get("notes", [])}


def save(data: dict):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


# --- Understanding the sentence ---

def _plain(text: str) -> str:
    """Lowercase, no accents, punctuation as spaces: the same length as the text, so a match's
    position is the original words' (kept with their accents)."""
    return "".join(" " if c in DROP else unicodedata.normalize("NFD", c)[0] for c in text.lower())


def _pattern(name: str) -> re.Pattern:
    body = i18n.L.data["lists"][name].strip("^$").replace(" ", r"\s+")
    return re.compile(r"^\s*" + body + r"[\s,]*$")


def match(name: str, text: str):
    """The pattern «name» on the sentence: {group: the original words} or None."""
    found = _pattern(name).match(_plain(text))
    if not found:
        return None
    return {key: text[found.start(key):found.end(key)].strip(" ,") if found.group(key) else None
            for key in found.groupdict()}


def items(said: str) -> list[str]:
    """«leche, huevos y pan» → ["leche", "huevos", "pan"]."""
    joiners = "|".join(re.escape(j.strip()) for j in i18n.L.data["lists"]["and"] if j.strip())
    parts = re.split(r"\s*,\s*" + (rf"|\s+(?:{joiners})\s+" if joiners else ""), said, flags=re.I)
    return [p.strip() for p in parts if p.strip()]


def list_name(said: str | None) -> str:
    """The list meant: one of the known ones by any of its names, or a new one as said."""
    names = i18n.L.data["lists"]["names"]
    if not said:
        return i18n.L.data["lists"]["default"]
    plain = _plain(said).strip()
    for key, spoken in names.items():
        if plain in spoken or any(plain.startswith(s) for s in spoken):
            return key
    return said.strip().lower()


def shown(name: str) -> str:
    """How a list is said: «la compra» (locale lists.display), or its own name."""
    return i18n.L.data["lists"].get("display", {}).get(name, name)


def _same(a: str, b: str) -> bool:
    return _plain(a).strip() == _plain(b).strip()


# --- Doing it ---

def add(name: str, new: list[str]) -> str:
    data = load()
    current = data["lists"].setdefault(name, [])
    added = [i for i in new if not any(_same(i, c) for c in current)]
    if not added:
        return i18n.L("speech.list_already", list=shown(name))
    current.extend(added)
    save(data)
    return i18n.L("speech.list_added", list=shown(name), items=spoken_list(added))


def remove(name: str, gone: list[str]) -> str:
    data = load()
    current = data["lists"].get(name, [])
    removed = [c for c in current if any(_same(c, g) or _same(c, g.split(" ", 1)[-1]) for g in gone)]
    if not removed:
        return i18n.L("speech.list_not_there", list=shown(name))
    data["lists"][name] = [c for c in current if c not in removed]
    save(data)
    return i18n.L("speech.list_removed", list=shown(name), items=spoken_list(removed))


def read(name: str) -> str:
    current = load()["lists"].get(name, [])
    if not current:
        return i18n.L("speech.list_empty", list=shown(name))
    return i18n.L("speech.list_read", list=shown(name), items=spoken_list(current))


def clear(name: str) -> str:
    data = load()
    data["lists"][name] = []
    save(data)
    return i18n.L("speech.list_cleared", list=shown(name))


def note(text: str) -> str:
    data = load()
    data["notes"].append({"at": time.time(), "text": text.strip()})
    save(data)
    return i18n.L("speech.note_taken")


def notes() -> str:
    found = [n["text"] for n in load()["notes"]]
    if not found:
        return i18n.L("speech.notes_empty")
    key = "speech.note_read" if len(found) == 1 else "speech.notes_read"
    return i18n.L(key, count=len(found), notes=spoken_list(found))


def clear_notes() -> str:
    data = load()
    data["notes"] = []
    save(data)
    return i18n.L("speech.notes_cleared")


@skill
class Lists(Skill):
    order = 40

    def answer(self, text, toks):
        if found := match("add", text):
            return add(list_name(found["list"]), items(found["items"]))
        if found := match("remove", text):
            return remove(list_name(found["list"]), items(found["items"]))
        if found := match("read", text):
            return read(list_name(found["list"]))
        if found := match("clear", text):
            return clear(list_name(found["list"]))
        if match("notes", text) is not None:  # no parts to take: an empty dict
            return notes()
        if match("clear_notes", text) is not None:
            return clear_notes()
        if found := match("note", text):
            return note(found["text"])
        return None


# --- For the LLM ---

@tool("The user's lists (shopping, tasks…) and notes.")
def get_lists() -> str:
    data = load()
    lines = [f"{name}: {', '.join(entries) or '(empty)'}" for name, entries in data["lists"].items()]
    lines += [f"note: {n['text']}" for n in data["notes"]]
    return "\n".join(lines) or "(no lists or notes)"


@tool("Add items to one of the user's lists (e.g. list «shopping», items [«milk», «bread»]).")
def add_to_list(list: str, items: str) -> str:
    entries = [i.strip() for i in items.split(",") if i.strip()]
    if not entries:
        raise ToolError("which items? (separated by commas)")
    return add(list.strip().lower() or i18n.L.data["lists"]["default"], entries)


@tool("Remove items from one of the user's lists (separated by commas).")
def remove_from_list(list: str, items: str) -> str:
    return remove(list.strip().lower(), [i.strip() for i in items.split(",") if i.strip()])


@tool("Keep a note for the user.")
def take_note(text: str) -> str:
    return note(text)
