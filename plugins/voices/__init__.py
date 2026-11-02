"""Voices: who is speaking. Each person's voice print (an embedding of a few sentences, made
on this Mac by a WeSpeaker model: ONNX, 26 MB, downloaded the first time), kept in
voices.json in your data folder.

- Learning a voice: «aprende mi voz» on a device → «¿Cómo te llamas?» → you read PHRASES it
  says, one by one → «Ya conozco tu voz, Suvi.» Once someone is known, only a known voice
  can start it («aprende una voz nueva»), or the Mac app (Settings → Voices).
- «voice_check» all (the default): once someone is known, it only listens to known voices:
  every sentence is checked before anything is done with it. A voice clearly unlike everyone
  (below UNCLEAR × «voice_match») is dropped (the log says so, with the score); one in between,
  not clear enough, isn't dropped: if what it said would do something (an action, the LLM),
  it asks («No he reconocido bien tu voz: ¿lo hago?», the plugin «confirmation») and does it on
  a «yes» from a recognised voice; a harmless skill (the time, «stop», «go to sleep») goes
  through, as «Ey, Eva» does. actions: only the «yes» that authorizes an action. off: never.
- Short sentences («sí», «para») say little about who: a clear match counts, a clear match
  with someone else is dropped, and in between they count as the person this conversation
  already recognised (with a longer sentence) — never as an unknown.
- It keeps each person's usual score per device (the median of the sentences accepted as
  theirs); when the recent ones stay clearly below it (DROP, over RECENT_SCORES sentences: another
  place for the microphone, a cold), it says once that their voice should be learnt again there
  (a notice; the Mac's Voices page and the admin page show it), until it recovers or is learnt.
- The LLM hears who is talking («(Suvi is talking.)»), with the first sentence of each, and what the
  plugin «memory» remembers about them (their own facts; the shared ones are in its instructions).
- «voice_adapt» (on by default): it keeps learning each voice from what that person says
  (only voice prints, never the audio): the last RECENT sentences it was sure of on each device (long, clearly
  theirs, nobody else close) make a «recent» print beside the one learnt, per device. That one is
  never touched: a recent print only counts when the voice is also near it (FLOOR), so it can't
  drift off to someone else. Off: the recent ones are deleted; learning a voice again, too.
"""

import asyncio
import json
import logging
import time
from collections import namedtuple

import numpy as np

import hub
import i18n
import installer
import kernel
import models
import options
import paths
import settings
import skills
import web
from aiohttp import web as http
from options import Option
from skills import Skill, skill
from text import words

log = logging.getLogger("voices")
FILE = paths.HOME / "voices.json"
MODEL = ("Wespeaker/wespeaker-voxceleb-resnet34-LM", "voxceleb_resnet34_LM.onnx")
RATE = 16000
SHORT = 1.2  # seconds: shorter sentences say little about who
MIN_SAMPLE = 1.5  # seconds of a phrase when learning a voice
PHRASES = 5
RECENT = 10  # sentences kept, per person and device, to adapt their print
SURE = 0.65  # how alike a sentence must be to be kept (well above voice_match)
LONG = 2.0  # seconds a sentence must last to be kept
APART = 0.15  # and how much nearer to them than to anyone else
FLOOR = 0.45  # a recent print counts only if the voice is also this near the learnt one
# Below this share of «voice_match» a voice is clearly a stranger's (0.30 with the default 0.5): dropped;
# between it and «voice_match», not clear: it asks before doing something, lets a harmless skill through.
UNCLEAR = 0.6
USUAL = 40  # scores kept per person and device, to know their usual one
ENOUGH = 10  # sentences before it judges a drop
RECENT_SCORES = 5  # the recent ones: a drop has to last, one bad sentence doesn't count
DROP = 0.15  # how far below the usual score the recent ones are when the print should be learnt again

options.add(Option("voice_check", "all", "what needs a known voice once someone's is learnt: all (it only listens "
                   "to known voices), actions (only the «yes» that authorizes one) or off", "security", "choice",
                   ["all", "actions", "off"], live=True))
options.add(Option("voice_adapt", True, "keep learning each voice from what that person says (only voice prints, "
                   "never the audio; off: what it learnt that way is deleted)", "security", "bool", live=True))
options.add(Option("voice_match", 0.5, "how alike a voice must be to a known one (0–1; higher: stricter)",
                   "security", "float", live=True))


# --- The people and their voice prints ---

def people() -> list[dict]:
    try:
        return json.loads(FILE.read_text())["people"]
    except (OSError, ValueError, KeyError):
        return []


def _save(found: list[dict]):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps({"people": found}))
    FILE.chmod(0o600)


def learn(name: str, prints: list[np.ndarray], device: str | None = None):
    """A person's voice print on a device (each microphone sounds different): the average of their
    phrases there. Learnt again on the same device, it replaces that one; on another, it is added
    (the same person, a print per device)."""
    mean = np.mean(prints, axis=0)
    mean = mean / np.linalg.norm(mean)
    found = people()
    person = next((p for p in found if p["name"].lower() == name.lower()), None)
    if person is None:
        person = {"name": name, "since": time.time(), "prints": {}}
        found.append(person)
    if "print" in person:  # before a print per device: the one it had, kept
        person.setdefault("prints", {})["?"] = person.pop("print")
    person.setdefault("prints", {})[device or "?"] = [round(float(x), 6) for x in mean]
    person.setdefault("learnt", {})[device or "?"] = time.time()  # when, there (each device's page lists them)
    person["recent"] = [r for r in person.get("recent", []) if r["near"] != (device or "?")]  # learnt anew
    person.get("usual", {}).pop(device or "?", None)  # its usual score there starts over (and any warning)
    person["samples"] = person.get("samples", 0) + len(prints)
    _save(found)
    log.info("voice learnt: %s on %s (%d phrases, %d devices)", name, device or "a device", len(prints),
             len(person["prints"]))


def prints_of(person: dict) -> list[np.ndarray]:
    """A person's voice prints: one per device it was learnt on (an old one: its single print)."""
    found = list(person.get("prints", {}).values()) or ([person["print"]] if "print" in person else [])
    return [np.array(p) for p in found]


def forget(name: str, device: str | None = None) -> bool:
    """Forgets a voice; with a device, only its print there (what it learnt elsewhere stays: the
    person is forgotten only if that was their last one). False if there was nothing to forget."""
    found = people()
    person = next((p for p in found if p["name"].lower() == name.lower()), None)
    if person is None:
        return False
    if device is not None:
        if device not in person.get("prints", {}):
            return False
        person["prints"].pop(device)
        person.get("learnt", {}).pop(device, None)
        person.get("usual", {}).pop(device, None)
        person["recent"] = [r for r in person.get("recent", []) if r["near"] != device]
        if person["prints"] or "print" in person:
            _save(found)
            log.info("voice forgotten on %s: %s", device, name)
            return True
    _save([p for p in found if p is not person])
    log.info("voice forgotten: %s", name)
    return True


def on(device: str) -> list[dict]:
    """The voices learnt on a device: their name and when (None: before it was kept)."""
    return [{"name": p["name"], "learnt": p.get("learnt", {}).get(device)}
            for p in people() if device in p.get("prints", {})]


def rename(name: str, to: str) -> bool:
    """A known voice called otherwise («Subi» → «Suvi»: the name as transcribed). If another voice
    already has that name, they are one person: merged (a print per device; the same device in both,
    their average). False if there is no such voice or the name is empty."""
    to = to.strip()
    found = people()
    person = next((p for p in found if p["name"].lower() == name.lower()), None)
    if person is None or not to:
        return False
    other = next((p for p in found if p is not person and p["name"].lower() == to.lower()), None)
    if other is None:
        person["name"] = to
    else:
        for old in (person, other):  # before a print per device: the one it had
            if "print" in old:
                old.setdefault("prints", {})["?"] = old.pop("print")
        prints = other.setdefault("prints", {})
        for device, mine in person.get("prints", {}).items():
            if device in prints:
                mean = (np.array(prints[device]) + np.array(mine)) / 2
                prints[device] = [round(float(x), 6) for x in mean / np.linalg.norm(mean)]
            else:
                prints[device] = mine
        other["samples"] = other.get("samples", 0) + person.get("samples", 0)
        other["recent"] = other.get("recent", []) + person.get("recent", [])
        other["since"] = min(other.get("since", time.time()), person.get("since", time.time()))
        other["name"] = to
        found.remove(person)
        log.info("voices: %s merged into %s", name, to)
    _save(found)
    return True


def checking() -> str:
    """What needs a known voice now: all, actions or off (off until someone is known)."""
    return settings.get("voice_check", "all") if people() else "off"


# --- The voice print ---

_model = None


def _session():
    global _model
    if _model is None:
        import onnxruntime

        path = models.fetch(MODEL[0]) / MODEL[1]  # pinned and checked (server/models.py)
        _model = onnxruntime.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    return _model


def fbank(wave: np.ndarray, bins: int = 80) -> np.ndarray:
    """Kaldi's log-mel filterbank, as WeSpeaker computes it (25/10 ms, Hamming, 512 FFT), with CMN."""
    wave = wave.astype(np.float64) * 32768
    length, shift = int(0.025 * RATE), int(0.010 * RATE)
    if len(wave) < length:
        wave = np.pad(wave, (0, length - len(wave)))
    count = 1 + (len(wave) - length) // shift
    frames = wave[np.arange(length)[None, :] + shift * np.arange(count)[:, None]]
    frames = frames - frames.mean(axis=1, keepdims=True)
    frames = np.concatenate([frames[:, :1] * 0.03, frames[:, 1:] - 0.97 * frames[:, :-1]], axis=1)
    power = np.abs(np.fft.rfft(frames * np.hamming(length), 512)) ** 2
    mel = lambda f: 1127 * np.log(1 + f / 700)  # noqa: E731
    centers = np.linspace(mel(20), mel(RATE / 2), bins + 2)
    freqs = mel(np.arange(257) * RATE / 512)
    banks = np.maximum(0, np.minimum((freqs - centers[:-2, None]) / (centers[1:-1, None] - centers[:-2, None]),
                                     (centers[2:, None] - freqs) / (centers[2:, None] - centers[1:-1, None])))
    feats = np.log(np.maximum(power @ banks.T, np.finfo(float).eps))
    return (feats - feats.mean(axis=0)).astype(np.float32)


def voice_print(audio: np.ndarray) -> np.ndarray:
    """16 kHz float audio → its voice print (normalized)."""
    found = _session().run(None, {"feats": fbank(audio)[None]})[0][0]
    return found / np.linalg.norm(found)


def identify(audio: np.ndarray) -> tuple[str | None, float]:
    """The known person it sounds most like, and how much (cosine, -1–1)."""
    found = ranked(voice_print(audio)) if people() else []
    return (found[0][1], found[0][0]) if found else (None, 0.0)


def ranked(heard: np.ndarray) -> list[tuple[float, str, str]]:
    """Everyone known, nearest first: (score, name, the device whose print is nearest). Each person
    by their print closest to this voice (the one learnt with a microphone like this), or its recent
    one if the voice is also near the learnt one (FLOOR)."""
    adapt = settings.get("voice_adapt", True)
    found = []
    for person in people():
        best = None
        for key, learnt in _prints(person).items():
            score = float(heard @ learnt)
            recent = _recent(person, key) if adapt and score >= FLOOR else None
            if recent is not None:
                score = max(score, float(heard @ recent))
            if best is None or score > best[0]:
                best = (score, person["name"], key)
        if best:
            found.append(best)
    return sorted(found, reverse=True)


def _prints(person: dict) -> dict[str, np.ndarray]:
    found = person.get("prints") or ({"?": person["print"]} if "print" in person else {})
    return {key: np.array(p) for key, p in found.items()}


def _recent(person: dict, key: str) -> np.ndarray | None:
    """The average of the sentences it kept of them near that device's print (None: none yet)."""
    kept = [np.array(r["print"]) for r in person.get("recent", []) if r["near"] == key]
    if not kept:
        return None
    mean = np.mean(kept, axis=0)
    return mean / np.linalg.norm(mean)


def adapt(audio: np.ndarray, name: str):
    """A sentence it accepted as `name`'s: kept (only its print) if it is sure of it."""
    if not settings.get("voice_adapt", True) or len(audio) / RATE < LONG:
        return
    heard = voice_print(audio)
    found = ranked(heard)
    if not found or found[0][1] != name or found[0][0] < SURE:
        return
    if len(found) > 1 and found[0][0] - found[1][0] < APART:  # someone else almost as near: not sure
        return
    everyone = people()
    person = next(p for p in everyone if p["name"] == name)
    near = found[0][2]
    kept = person.setdefault("recent", [])
    kept.append({"near": near, "print": [round(float(x), 6) for x in heard], "at": time.time()})
    there = [r for r in kept if r["near"] == near]
    person["recent"] = [r for r in kept if r["near"] != near] + there[-RECENT:]  # the last ones of each device
    _save(everyone)
    log.info("voice adapted: %s on %s (%.2f, %d recent there)", name, near, found[0][0], min(len(there), RECENT))


def drop_recent():
    """«voice_adapt» off: what it learnt from what people said, deleted."""
    everyone = people()
    if any(p.get("recent") for p in everyone):
        for person in everyone:
            person.pop("recent", None)
        _save(everyone)
        log.info("voice adaptation off: recent prints deleted")


# Who it sounds like, whether the sentence counts and why; its score and length; and «unclear»: long
# enough to tell, like someone known, but not enough (between the lower bound and «voice_match»).
Verdict = namedtuple("Verdict", "name counts why score seconds unclear")


def match() -> float:
    return settings.get("voice_match") or 0.5


def lower() -> float:
    """Below this a voice is clearly nobody known's."""
    return match() * UNCLEAR


def judge(audio: np.ndarray, before: str | None) -> Verdict:
    """(who, whether it counts, why, …): `before`, who this conversation already recognised."""
    wanted = match()
    name, score = identify(audio)
    seconds = len(audio) / RATE
    if score >= wanted:
        return Verdict(name, True, f"{name} ({score:.2f})", score, seconds, False)
    if seconds >= SHORT:
        if score >= lower():
            return Verdict(name, False, f"unclear voice (best {name}, {score:.2f}, {seconds:.1f} s)", score, seconds, True)
        return Verdict(None, False, f"unknown voice (best {name}, {score:.2f}, {seconds:.1f} s)", score, seconds, False)
    if before and (name == before or score < lower()):  # short and unclear: whoever was talking
        return Verdict(before, True, f"short, as {before} ({score:.2f})", score, seconds, False)
    return Verdict(None, False, f"short and unclear (best {name}, {score:.2f})", score, seconds, False)


def stranger(audio: np.ndarray) -> tuple[bool, str]:
    """Whether the voice is clearly nobody known's (below the lower bound), and why."""
    name, score = identify(audio)
    return score < lower(), f"best {name}, {score:.2f}"


def may_wake(audio: np.ndarray) -> bool:
    """«Ey, Eva» said by whom: with «voice_check» all and someone known, only a voice that isn't
    clearly a stranger's wakes it. Its name is short (under a second: its print says less), so it
    only refuses a voice clearly unlike everyone known (below UNCLEAR × «voice_match»); what is said
    after it is checked as always."""
    if checking() != "all":
        return True
    unknown, why = stranger(audio)
    if unknown:
        log.info("not woken: unknown voice (%s)", why)
        return False
    return True


# --- Each person's usual score per device: when it drops, their print there should be learnt again ---

def usual_of(person: dict, device: str | None) -> dict:
    return person.setdefault("usual", {}).setdefault(device or "?", {"scores": [], "warned": False})


def track(assistant, name: str, device: str | None, score: float):
    """A sentence accepted as `name`'s on that device, with its score: kept (the last USUAL). When the
    recent ones stay DROP below their usual one, it tells them once to learn their voice again there;
    once they recover (or learn it again), it may tell them again some day."""
    everyone = people()
    person = next((p for p in everyone if p["name"] == name), None)
    if person is None:
        return
    usual = usual_of(person, device)
    usual["scores"] = (usual["scores"] + [round(float(score), 3)])[-USUAL:]
    scores = usual["scores"]
    if len(scores) >= ENOUGH:
        typical, recent = float(np.median(scores)), float(np.median(scores[-RECENT_SCORES:]))
        if not usual["warned"] and recent <= typical - DROP:
            usual["warned"] = True
            log.info("%s on %s: usual score %.2f, lately %.2f: their voice should be learnt again there",
                     name, device or "?", typical, recent)
            _warn(assistant, name, device)
        elif usual["warned"] and recent > typical - DROP / 2:
            usual["warned"] = False
            log.info("%s on %s: their score is back (%.2f)", name, device or "?", recent)
    _save(everyone)


def _warn(assistant, name: str, device: str | None):
    """«Conviene volver a aprender tu voz en …»: a notice (the plugin «notices»), when it is a good moment."""
    notices = kernel_module("notices")
    text = i18n.L("speech.voice_relearn", name=name, device=device_name(device))
    if notices is None:
        log.info("no notices: not said «%s»", settings.private(text))
        return
    assistant.later(notices.tell(text))


def device_name(device: str | None) -> str:
    """«iPad (cocina)», from the plugin «devices»; else what it has."""
    devices = kernel_module("devices")
    return devices.describe(device) if devices else (device or "a device")


def relearn(person: dict) -> list[str]:
    """The devices where their voice should be learnt again, by name."""
    return [device_name(None if d == "?" else d) for d, u in person.get("usual", {}).items() if u.get("warned")]


# --- In the assistant: every sentence (or only the «yes»), before it is handled ---

def screen(assistant, text: str, timings: dict, audio, handle) -> bool:
    """Takes the sentence if it has to: learning a voice, or checking who it is (in the background,
    then `handle(text, timings)` if it counts). False: handle it as usual."""
    learning = getattr(assistant, "learning", None)
    if learning is not None:
        learning.heard(text, audio)
        return True
    mode = checking()
    if mode == "off" or audio is None:
        return False
    if mode == "actions":
        confirmation = kernel_module("confirmation")
        if not (confirmation and confirmation.waiting() and confirmation.is_yes(text)):
            return False

    if mode == "all" and skills.harmless(text):
        # «Apágate», «para», «¿qué hora es?» are harmless (and often short: their print says less): as
        # «Ey, Eva», only a voice clearly unlike everyone known is refused.
        unknown, why = stranger(audio)
        if not unknown:
            return False
        log.info("not for it: harmless, but an unknown voice (%s) «%s»", why, settings.private(text))
        assistant._state(assistant._idle_state())
        return True

    session = hub.of(assistant)
    device = session.device if session else None

    async def check():
        verdict = await asyncio.get_running_loop().run_in_executor(
            None, judge, audio, getattr(assistant, "voice", None))
        name, counts, why = verdict.name, verdict.counts, verdict.why
        if not counts:
            if mode == "all" and verdict.unclear and _ask(assistant, text, timings, verdict):
                return
            log.info("not for it: %s «%s»", why, settings.private(text))
            if mode == "actions":  # a «yes» from an unknown voice: refused, and said so
                confirmation = kernel_module("confirmation")
                if confirmation:
                    confirmation.answer(i18n.L.list("commands.no")[0])  # cancels the waiting action
                assistant.say(i18n.L("speech.voice_refused"))
            else:
                assistant._state(assistant._idle_state())
            return
        log.info("voice: %s", why)
        assistant.voice = name
        if verdict.seconds >= SHORT:  # long enough to say something about them: their usual score
            track(assistant, name, device, verdict.score)
        if not _answered(assistant, text, name, handle):
            handle(text, timings)
        if settings.get("voice_adapt", True):
            await asyncio.get_running_loop().run_in_executor(None, adapt, audio, name)
        else:
            drop_recent()

    assistant.later(check())
    return True


def _ask(assistant, text: str, timings: dict, verdict: Verdict) -> bool:
    """A voice not clear enough said something that would do something (an action, the LLM): instead of
    dropping it, it asks whether to do it («¿lo hago?», the plugin «confirmation»: the face shows the
    question), and does it on a «yes» from a recognised voice (_answered). False if it can't ask: no
    confirmation plugin, or a question already waiting (then it is dropped, as before)."""
    confirmation = kernel_module("confirmation")
    if confirmation is None or confirmation.waiting():
        return False
    sign = confirmation.ask_about(f"voice: {text}")  # an earlier one nobody answered has expired: replaced
    assistant.unclear = {"text": text, "timings": timings, "sign": sign, "name": verdict.name, "score": verdict.score}
    log.info("unclear voice (%s): asking «%s»", verdict.why, settings.private(text))
    assistant.show_heard(text)
    assistant.say(i18n.L("speech.voice_unclear"))
    return True


def _answered(assistant, text: str, name: str, handle) -> bool:
    """A recognised voice answered the question about an unclear one: «yes» does what was said (as
    that voice), anything else cancels it. False if nothing was waiting (or it expired): as usual."""
    asked, assistant.unclear = getattr(assistant, "unclear", None), None
    confirmation = kernel_module("confirmation")
    if asked is None or confirmation is None or not confirmation.waiting_for(asked["sign"]):
        return False
    yes = confirmation.is_yes(text)
    confirmation.answer(text)  # resolved: confirmed (nobody else will use it) or cancelled
    assistant.show_heard(text)
    if yes:
        log.info("unclear voice: %s said yes to «%s»", name, settings.private(asked["text"]))
        handle(asked["text"], asked["timings"])
    return True


def kernel_module(name: str):
    import kernel

    return kernel.module(name)


def who(assistant) -> str:
    """For the LLM: who is talking, when known."""
    name = getattr(assistant, "voice", None)
    return f"({name} is talking.)" if name else ""


# --- Learning a voice ---

# Where each learning is (by device), for the app's and the admin page's guide: the phrase to
# read, which one it is, whether it has to be said again; kept a while once it ends.
progress: dict[str, dict] = {}


class Learning:
    """«¿Cómo te llamas?», then PHRASES phrases read out loud; their voice prints, averaged."""

    def __init__(self, assistant, name: str | None = None):
        self.assistant, self.name, self.prints, self.asked = assistant, name, [], 0
        session = hub.of(assistant)
        self.device = session.device if session else None
        assistant.learning = self
        if name:
            self._next()
        else:
            self._show("name")
            assistant.say(i18n.L("speech.voice_name"))

    def _show(self, step: str, again: bool = False):
        """Its step, for the guide: name, phrase, done or cancelled."""
        if not self.device:
            return
        phrases = i18n.L.list("voices.phrases")
        progress[self.device] = {"step": step, "name": self.name or "", "again": again, "number": self.asked + 1,
                                 "total": PHRASES, "phrase": phrases[self.asked % len(phrases)] if step == "phrase" else "",
                                 "at": time.time()}

    def _next(self, again: bool = False):
        phrases = i18n.L.list("voices.phrases")
        self._show("phrase", again)
        self.assistant.say(i18n.L("speech.voice_read", phrase=phrases[self.asked % len(phrases)]))

    def cancel(self):
        self.assistant.learning = None
        self._show("cancelled")
        self.assistant.say(i18n.L("speech.voice_cancelled"))

    def heard(self, text: str, audio):
        assistant = self.assistant
        assistant.show_heard(text)
        found = words(text)
        if found and set(found) & set(i18n.L.list("commands.stop")) and len(found) <= 2:
            self.cancel()
            return
        if self.name is None:
            self.name = _name(text)
            if not self.name:
                assistant.say(i18n.L("speech.voice_name"))
                return
            assistant.say(i18n.L("speech.voice_start", name=self.name, count=PHRASES))
            self._next()
            return
        if audio is None or len(audio) / RATE < MIN_SAMPLE:
            assistant.say(i18n.L("speech.voice_again"))
            self._next(again=True)
            return
        assistant.later(self._print(audio))

    async def _print(self, audio):
        self.prints.append(await asyncio.get_running_loop().run_in_executor(None, voice_print, audio))
        self.asked += 1
        if len(self.prints) < PHRASES:
            self._next()
            return
        learn(self.name, self.prints, self.device)
        self.assistant.learning = None
        self.assistant.voice = self.name
        self._show("done")
        self.assistant.say(i18n.L("speech.voice_learnt", name=self.name))


def _name(text: str) -> str:
    """«Me llamo Suvi», «soy Suvi», «Suvi» → «Suvi»."""
    found = text.strip().rstrip(".!?¡¿").split()
    lead = {w.lower() for w in i18n.L.list("voices.name_lead")}
    while found and found[0].lower().strip(",") in lead:
        found.pop(0)
    return " ".join(w.strip(",") for w in found[:3]).strip().title()


def start(assistant, name: str | None = None):
    """Starts learning a voice on that device (it wakes up so it hears the answers)."""
    assistant.ear.wake_up("learning a voice")
    Learning(assistant, name)


@skill
class LearnVoice(Skill):
    order = -3  # before anything else
    local = False

    def hear(self, text: str, assistant) -> bool:
        found = words(text)
        said = " ".join(found)
        # «aprende mi voz» and its variants («apréndeme voz», «registra mi voz»): a short sentence with a
        # word for learning and the word for voice (as transcribed: «aprendeme», «vos»…)
        loose = len(found) <= 5 and any(w.startswith(tuple(i18n.L.list("voices.learn_verbs"))) for w in found) \
            and any(w in i18n.L.list("voices.voice_words") for w in found)
        if loose or any(phrase in said for phrase in i18n.L.list("voices.learn")):
            assistant.show_heard(text)
            start(assistant)
            return True
        if any(phrase in said for phrase in i18n.L.list("voices.forget")) and getattr(assistant, "voice", None):
            assistant.show_heard(text)
            forget(assistant.voice)
            assistant.say(i18n.L("speech.voice_forgotten", name=assistant.voice))
            assistant.voice = None
            return True
        return False


def cancel(device: str):
    """Stops the learning going on in that device, if any."""
    session = hub.by_device(device)
    learning = getattr(session.brain, "learning", None) if session else None
    if learning is not None:
        learning.cancel()


# --- The installer: your voice, right after installing (on this computer's own device) ---

def guide(device: str) -> dict | None:
    """Where the learning on that device is, as the installer's window shows a «device» step."""
    found = progress.get(device)
    if not found:
        return None
    step = found["step"]
    if step == "name":
        return {"state": "running", "title": i18n.L("voices.guide.name"), "text": "",
                "detail": i18n.L("voices.guide.name_detail"), "fraction": 0}
    if step == "phrase":
        return {"state": "running", "title": i18n.L("voices.guide.phrase", number=found["number"], total=found["total"]),
                "text": found["phrase"], "detail": i18n.L("voices.guide.again" if found["again"] else "voices.guide.read"),
                "fraction": (found["number"] - 1) / found["total"]}
    if step == "done":
        return {"state": "done", "title": "", "text": i18n.L("voices.guide.done", name=found["name"]), "detail": "",
                "fraction": 1}
    return {"state": "cancelled", "title": "", "text": i18n.L("voices.guide.cancelled"), "detail": "", "fraction": None}


@installer.device("voice", "Your voice", order=95,
                  help="Read a few phrases out loud so it knows your voice. From then on, it only listens to the "
                       "voices it knows.",
                  action="Register my voice", later="Later, ask for it on a device: «learn my voice».",
                  when=lambda: not people(), follow=guide, cancel=cancel)
def _register(session):
    start(session.brain)


# --- For the Mac app: who is known; learning one on a device; forgetting ---



def _tidy():
    now = time.time()
    for device in [d for d, p in progress.items() if p["step"] in ("done", "cancelled") and now - p["at"] > 60]:
        progress.pop(device)  # an ended one stays a minute, for the guide to say so


def learning(device: str) -> dict | None:
    """The learning going on (or just ended) on a device: its step, name, phrase…; None if none."""
    _tidy()
    return progress.get(device)


def _listing():
    _tidy()
    memory = kernel.module("memory")
    return {"people": [{"name": p["name"], "samples": p.get("samples", 0), "since": p.get("since"),
                        "devices": len(prints_of(p)), "relearn": relearn(p),
                        "facts": memory.count(p["name"]) if memory else 0} for p in people()],
            "check": checking(), "learning": progress}


@web.route("GET", "/admin/voices")
async def _list(request):
    if not web.owner(request):  # this computer, or an admin's browser
        return http.json_response({}, status=403)
    return http.json_response(_listing())


@web.route("POST", "/admin/voices")
async def _change(request):
    """{"learn": device id, "name"?: «Ana»} starts it on that device; {"cancel": device id};
    {"rename": «Subi», "to": «Suvi»} (and what the plugin «memory» remembers of them);
    {"forget": «Ana», "memory"?: "delete"} (delete: what the plugin «memory» remembers of them too; else it
    stays under their name); {"forget": «Ana», "device": id}: only their print on that device (a device's
    page). Where each learning is: «learning» in the answer (GET too)."""
    if not web.owner(request):  # this computer, or an admin's browser
        return http.json_response({}, status=403)
    data = await request.json()
    if "learn" in data:
        session = hub.by_device(data["learn"])
        if session is None or not hasattr(session.brain, "say"):
            return http.json_response({"error": "that device isn't connected"}, status=400)
        token = hub.here.set(session)
        try:
            start(session.brain, (data.get("name") or "").strip() or None)
        finally:
            hub.here.reset(token)
    elif "cancel" in data:
        cancel(str(data["cancel"]))
    elif "rename" in data:
        old, to = str(data["rename"]), str(data.get("to") or "").strip()
        if not rename(old, to):
            return http.json_response({"error": "no such voice, or an empty name", **_listing()}, status=400)
        memory = kernel.module("memory")
        if memory:
            memory.rename_person(old, to)  # what it remembers of them goes with the name
    elif "forget" in data and data.get("device"):
        forget(str(data["forget"]), str(data["device"]))
    elif "forget" in data:
        forget(str(data["forget"]))
        memory = kernel.module("memory")
        if data.get("memory") == "delete" and memory:
            memory.forget_person(str(data["forget"]))
    return http.json_response(_listing())
