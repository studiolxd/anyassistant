"""How a spoken name reaches a written one, and the rankings built on it. Pure: nothing here
asks the computer anything, so every rule is tested on names written by hand.

The recognizer is set to Spanish (or English) and the names it is asked to write are mostly
English: what comes back is the name spelled as it sounded, differently each day («crom»,
«crome», «cromo» for Chrome; «fotochop»; «guasap»). Comparing spellings can only catch those one
alias at a time, so a spelling is reduced to its sounds first (phonetic(), from the part of
Spanish orthography that is many-to-one: b and v, c/k/qu, c/z/s, ll/y, a silent h…) and two
spellings of the same sounds compare equal. On top of that, the usual slack: a prefix long enough
to be meant, one edit in a long word.

Ported from minion (the same author, in Rust): text::phonetic, text::similarity,
targets::rank_windows, files::rank, shortcuts::best_match.
"""

import re
import unicodedata
from dataclasses import dataclass

VOWELS = "aeiou"
FRONT = "ei"  # the vowels that soften c and g

# Words of a name that say which maker it is from, not which app: «chrome» alone names
# «Google Chrome» in full. And the little words in a name («Ajustes del Sistema»).
BRANDS = {"google", "microsoft", "adobe", "apple", "mozilla", "jetbrains", "affinity", "autodesk"}
STOP = {"de", "del", "la", "el", "los", "las", "y", "the", "of", "and", "for", "para"}


def normalise(text: str) -> str:
    """Lowercase, no accents, letters and digits only, single-spaced: «¡Abre Chrome!» → «abre chrome»."""
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return " ".join(re.findall(r"[^\W_]+", plain))


def phonetic(text: str) -> str:
    """How a Spanish mouth would say a written word, reduced to its sounds: equal for two spellings of
    the same sounds («chrome», «crome», «cromo», «crom» → «krom»), different otherwise. Not meant to be
    read (c stands for the «ch» sound; a final vowel goes, it is the one Spanish adds to an English name)."""
    return " ".join(_phonetic_word(w) for w in normalise(text).split())


def _phonetic_word(word: str) -> str:
    letters = list(word)
    sounds: list[str] = []
    at = 0
    while at < len(letters):
        this = letters[at]
        after = letters[at + 1] if at + 1 < len(letters) else ""
        after2 = letters[at + 2] if at + 2 < len(letters) else ""
        taken = 1
        if this == "h":
            pass  # silent: «hola» is «ola»
        elif this == "c" and after == "h":
            taken = 2
            sounds.append("c" if after2 in VOWELS and after2 else "k")  # «chrome»: /k/; «chico»: ch
        elif this == "c":
            sounds.append("s" if after and after in FRONT else "k")
        elif this == "q":
            sounds.append("k")
            if after == "u":
                taken = 2
        elif this == "z":
            sounds.append("s")
        elif this == "v":
            sounds.append("b")
        elif this == "w":
            sounds.append("u")
        elif this == "x":
            sounds.extend("ks")
        elif this == "p" and after == "h":
            taken = 2
            sounds.append("f")
        elif this == "s" and after == "h":
            taken = 2
            sounds.append("c")  # English /ʃ/ arrives as the nearest Spanish sound, «ch»
        elif this == "g" and after and after in FRONT:
            sounds.append("j")
        elif this == "g" and after == "u" and after2 and after2 in FRONT:
            taken = 2
            sounds.append("g")
        elif this == "g" and after == "u" and after2 and after2 in VOWELS:
            taken = 2
            sounds.append("u")  # «guasap» for WhatsApp, «guisqui» for whisky
        elif this == "l" and after == "l":
            taken = 2
            sounds.append("y")
        elif this == "y" and not (after and after in VOWELS):
            sounds.append("i")  # a y with no vowel after it is the vowel i: «spotify»
        elif this == "o" and after == "o":
            taken = 2
            sounds.append("u")  # English «oo» is said u: «google» as «gugel»
        elif this == "e" and after == "e":
            taken = 2
            sounds.append("i")  # and «ee» is said i: «tweet» as «tuit»
        else:
            sounds.append(this)
        at += taken
        if len(sounds) >= 2 and sounds[-1] == sounds[-2]:
            sounds.pop()  # double letters are one sound, whatever produced them
    result = "".join(sounds)
    # Spanish puts an e in front of a word-initial s + consonant: «espotifai» for «spotify».
    if len(result) >= 4 and result[0] == "e" and result[1] == "s" and result[2] not in VOWELS:
        result = result[1:]
    # The final vowel of a name is the one Spanish invents («crom», «crome», «cromo»).
    if len(result) >= 4 and result[-1] in VOWELS:
        result = result[:-1]
    return result


def edits(a: str, b: str) -> int:
    """Levenshtein distance; a big number once the lengths alone differ by more than two."""
    if abs(len(a) - len(b)) > 2:
        return 99
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        previous, row[0] = row[0], i + 1
        for j, cb in enumerate(b):
            substitute = previous + (ca != cb)
            previous = row[j + 1]
            row[j + 1] = min(substitute, row[j] + 1, row[j + 1] + 1)
    return row[len(b)]


def reaches(spoken: str, written: str) -> bool:
    """Whether a spoken word stands for a written one: equal, a prefix long enough to be meant,
    one slip in a long word (same first two letters, so «gmail» isn't «mail»), or the same sounds."""
    if spoken == written:
        return True
    if len(spoken) >= 4 and len(spoken) * 2 > len(written) and written.startswith(spoken):
        return True  # «calcul» is Calculator; «marca» isn't «marcadores»
    if len(spoken) >= 5 and len(written) >= 5 and spoken[:2] == written[:2] and edits(spoken, written) <= 1:
        return True
    sound = phonetic(spoken)
    return len(sound) >= 3 and sound == phonetic(written)


@dataclass
class Match:
    item: object
    name: str  # the name it was reached by
    score: float


def _name_score(spoken: list[str], name: str) -> float:
    """How well a spoken name answers to a written one, 0–1: every spoken word must reach a word
    of the name (so «gmail» never opens Mail), and the score is the share of the name's own
    words (its maker's aside) that were said: «chrome» for «Google Chrome» is 1, «studio» for
    «Visual Studio Code» a third. Exactly the whole name, a little above everything else."""
    written = normalise(name).split()
    if not spoken or not written:
        return 0.0
    if any(not any(reaches(s, w) for w in written) for s in spoken):
        return 0.0
    hits = [w for w in written if any(reaches(s, w) for s in spoken)]
    core = [w for w in written if w not in BRANDS and w not in STOP and not w.isdigit()] or written
    return len([w for w in hits if w in core]) / len(core)


def rank(spoken: list[str], candidates: list[tuple[object, list[str]]], least: float = 0.5) -> list[Match]:
    """The candidates a spoken name reaches, best first (the whole name said exactly first, then
    the most complete, then the shortest). Each candidate comes with the names it answers to (its
    name, its localized name, aliases); the best of them counts. Below «least» (half the name's
    words) it isn't it."""
    found = []
    for item, names in candidates:
        best = max(((_name_score(spoken, n), n) for n in names if n), default=(0.0, ""))
        if best[0] >= least:
            found.append(Match(item, best[1], best[0]))
    found.sort(key=lambda m: (-m.score, normalise(m.name) != " ".join(spoken), len(normalise(m.name))))
    return found


def rank_shortcuts(spoken: list[str], installed: list[str]) -> list[str]:
    """The installed shortcuts a spoken name means, closest first: whole name against whole name,
    word for word (a shortcut called «Modo» isn't found inside «Modo Trabajo Extra»), each word
    equal, one slip away or the same sounds; then the ones said by half their words at least."""
    scored = []
    for name in installed:
        written = normalise(name).split()
        if len(written) != len(spoken):
            continue
        if all(s == w or edits(s, w) <= 1 or phonetic(s) == phonetic(w) for s, w in zip(spoken, written)):
            scored.append((edits(" ".join(spoken), " ".join(written)), name))
    found = [name for _, name in sorted(scored)]
    # Said shorter («comprobar reuniones» for «Comprobar las reuniones restantes»): as an app's name,
    # by more than half its words («modo» alone isn't «Modo Trabajo»).
    return found + [m.item for m in rank(spoken, [(n, [n]) for n in installed], least=0.6) if m.item not in found]


# --- Files and folders (what Spotlight found, ranked) ---

@dataclass
class Found:
    path: str
    is_folder: bool

    @property
    def name(self) -> str:
        return re.split(r"[\\/]", self.path.rstrip("/\\"))[-1]  # Windows' paths too (C:\\Users\\…)


# Paths nobody means when they say a name out loud: caches, backups, a package manager's copy of
# the whole world, the inside of an application. Except the cloud folders, which are yours.
IGNORED = ("/Library/", "/.Trash/", "/node_modules/", "/.git/", "/.build/", "/.venv/", "/target/debug/",
           "/target/release/", "/Backups.backupdb/", ".app/")
YOURS = ("/Library/CloudStorage/", "/Library/Mobile Documents/")


def ignored(path: str) -> bool:
    return any(bad in path for bad in IGNORED) and not any(ok in path for ok in YOURS)


def _file_score(name: str, query: str) -> int:
    """3 exactly the name (its extension isn't said), 2 by its start, 1 containing every word, 0 not at all."""
    query = normalise(query)
    full = normalise(name)
    stem = normalise(name.rsplit(".", 1)[0] if "." in name[1:] else name)
    if not query:
        return 0
    if full == query or stem == query:
        return 3
    if full.startswith(query):
        return 2
    if full.find(query) >= 0 or all(w in full.split() or w in full for w in query.split()):
        return 1
    return 0


def depth(path: str) -> int:
    return path.count("/") + path.count("\\")


def rank_files(query: str, folder: bool, found: list[Found]) -> list[Found]:
    """What answers to the name, best first: the exact name beats a name that starts with it, which
    beats one that contains it; a folder when a folder was asked for; then the one nearer home."""
    scored = []
    for item in found:
        if ignored(item.path):
            continue
        score = _file_score(item.name, query)
        if not score:
            continue
        wanted = item.is_folder == folder
        scored.append((not wanted, -score, depth(item.path), item.path, item))
    return [item for *_, item in sorted(scored, key=lambda s: s[:4])]


# --- Windows ---

@dataclass
class Window:
    app: str
    title: str
    pid: int = 0


def window_score(spoken: list[str], window: Window) -> float:
    """The share of what was said that the window's title accounts for, its app's name as a
    fallback («the mail window» names no title, it names Mail)."""
    if not spoken:
        return 0.0
    written = normalise(window.title).split() + normalise(window.app).split()
    hits = sum(any(reaches(s, w) for w in written) for s in spoken)
    return hits / len(spoken)


def rank_windows(spoken: list[str], windows: list[Window]) -> list[Window]:
    """The windows that answer to the name, best first (the order they came in breaks ties: the
    frontmost app's first)."""
    scored = [(window_score(spoken, w), -i, w) for i, w in enumerate(windows)]
    return [w for score, _, w in sorted(scored, key=lambda s: (-s[0], -s[1])) if score >= 0.5]
