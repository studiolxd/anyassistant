"""Voices: who is speaking. Each person's voice print (an embedding of a few sentences, made
on this Mac by a WeSpeaker model: ONNX, 26 MB, downloaded the first time), kept in
voices.json in your data folder.

- Learning a voice: «aprende mi voz» on a device → «¿Cómo te llamas?» → you read PHRASES it
  says, one by one → «Ya conozco tu voz, Suvi.» Once someone is known, only a known voice
  can start it («aprende una voz nueva»), or the Mac app (Settings → Voices).
- «voice_check» all (the default): once someone is known, it only listens to known voices:
  every sentence is checked before anything is done with it; others are dropped (the log
  says so, with the score). actions: only the «yes» that authorizes an action. off: never.
- Short sentences («sí», «para») say little about who: a clear match counts, a clear match
  with someone else is dropped, and in between they count as the person this conversation
  already recognised (with a longer sentence) — never as an unknown.
- The LLM hears who is talking («(Suvi is talking.)»), with the first sentence of each.
"""

import asyncio
import json
import logging
import time

import numpy as np

import hub
import i18n
import options
import paths
import settings
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

options.add(Option("voice_check", "all", "what needs a known voice once someone's is learnt: all (it only listens "
                   "to known voices), actions (only the «yes» that authorizes one) or off", "security", "choice",
                   ["all", "actions", "off"], live=True))
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
    person["samples"] = person.get("samples", 0) + len(prints)
    _save(found)
    log.info("voice learnt: %s on %s (%d phrases, %d devices)", name, device or "a device", len(prints),
             len(person["prints"]))


def prints_of(person: dict) -> list[np.ndarray]:
    """A person's voice prints: one per device it was learnt on (an old one: its single print)."""
    found = list(person.get("prints", {}).values()) or ([person["print"]] if "print" in person else [])
    return [np.array(p) for p in found]


def forget(name: str) -> bool:
    found = people()
    kept = [p for p in found if p["name"].lower() != name.lower()]
    _save(kept)
    return len(kept) != len(found)


def checking() -> str:
    """What needs a known voice now: all, actions or off (off until someone is known)."""
    return settings.get("voice_check", "all") if people() else "off"


# --- The voice print ---

_model = None


def _session():
    global _model
    if _model is None:
        import onnxruntime
        from huggingface_hub import hf_hub_download

        _model = onnxruntime.InferenceSession(hf_hub_download(*MODEL), providers=["CPUExecutionProvider"])
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
    known = people()
    if not known:
        return None, 0.0
    heard = voice_print(audio)
    # Each person by their print closest to this voice (the one learnt with a microphone like this).
    scores = [(max(float(heard @ one) for one in prints_of(p)), p["name"]) for p in known if prints_of(p)]
    if not scores:
        return None, 0.0
    score, name = max(scores)
    return name, score


def judge(audio: np.ndarray, before: str | None) -> tuple[str | None, bool, str]:
    """(who, whether it counts, why): `before`, who this conversation already recognised."""
    match = settings.get("voice_match") or 0.5
    name, score = identify(audio)
    seconds = len(audio) / RATE
    if score >= match:
        return name, True, f"{name} ({score:.2f})"
    if seconds >= SHORT:
        return None, False, f"unknown voice (best {name}, {score:.2f}, {seconds:.1f} s)"
    if before and (name == before or score < match * 0.6):  # short and unclear: whoever was talking
        return before, True, f"short, as {before} ({score:.2f})"
    return None, False, f"short and unclear (best {name}, {score:.2f})"


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

    async def check():
        name, counts, why = await asyncio.get_running_loop().run_in_executor(
            None, judge, audio, getattr(assistant, "voice", None))
        if not counts:
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
        handle(text, timings)

    assistant.later(check())
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
        said = " ".join(words(text))
        if any(phrase in said for phrase in i18n.L.list("voices.learn")):
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


# --- For the Mac app: who is known; learning one on a device; forgetting ---



def _listing():
    now = time.time()
    for device in [d for d, p in progress.items() if p["step"] in ("done", "cancelled") and now - p["at"] > 60]:
        progress.pop(device)  # an ended one stays a minute, for the guide to say so
    return {"people": [{"name": p["name"], "samples": p.get("samples", 0), "since": p.get("since"),
                        "devices": len(prints_of(p))} for p in people()],
            "check": checking(), "learning": progress}


@web.route("GET", "/admin/voices")
async def _list(request):
    if not web.owner(request):  # this computer, or an admin's browser
        return http.json_response({}, status=403)
    return http.json_response(_listing())


@web.route("POST", "/admin/voices")
async def _change(request):
    """{"learn": device id, "name"?: «Ana»} starts it on that device; {"cancel": device id};
    {"forget": «Ana»}. Where each learning is: «learning» in the answer (GET too)."""
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
        session = hub.by_device(str(data["cancel"]))
        learning = getattr(session.brain, "learning", None) if session else None
        if learning is not None:
            learning.cancel()
    elif "forget" in data:
        forget(str(data["forget"]))
    return http.json_response(_listing())
