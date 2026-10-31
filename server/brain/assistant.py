"""Phase 3: listens, transcribes, answers with an LLM plugin and says it out loud.

Each «Hey Jarvis» starts a new conversation in the LLM, which remembers it until
it falls asleep. The answer reaches the screen in pieces as it is generated
("text" messages with the same id and partial=True until the last one), and as
soon as a sentence is complete it is synthesized and played while the next one
arrives. While it speaks it doesn't listen; tapping the screen stops it.
"""

import asyncio
import json
import logging
import os
import re
import signal
import time
from pathlib import Path

import i18n
import settings
from audio import normalize
from brain.transcriber import Transcriber
from text import words

log = logging.getLogger("assistant")

# Seconds deaf after speaking (--echo-guard): the time its voice takes to reach the
# tablet, play and come back through the microphone, plus room echo. With 0.6 s on
# the tablet the last word leaked in («…anything else?» → «Anything else?»).
GUARD = 1.2
ECHO_MAX_WORDS = 5  # an echo is a short piece of what it just said
# An echo starts right after it stops speaking (after the guard); an answer of yours
# that repeats its words («Delete only the two promotional ones…?» → «Only the two
# promotional ones») usually starts later: only what starts within this margin counts.
ECHO_WINDOW = 2.5

# Confirming actions that write: bin/jarvis-confirm records the pending one; if the
# user says «yes», this authorizes that same action for a while (--confirm-wait, --confirm-valid).
CONFIRM = Path(__file__).resolve().parents[2] / ".build" / "confirm"
END_OF_SENTENCE = re.compile(r"(?<=[.!?…;:])\s+|\n+")


def system_command(text: str) -> str | None:
    """«Reload the tools» → "reload"; «Restart» → "restart". Only short commands."""
    heard = words(text)
    if not 0 < len(heard) <= 5:
        return None
    if any(w.startswith(tuple(i18n.L.list("commands.reload"))) for w in heard):
        return "reload"
    if set(heard) & set(i18n.L.list("commands.restart")):
        return "restart"
    return None


def language_command(text: str) -> str | None:
    """«Speak Spanish», «Háblame en inglés» → "es", "en". Understood in any language.

    A verb of some locale's commands.language first, a language's name in some
    locale's «languages» and nothing else but short linking words («to», «en»…):
    «¿Quién habla inglés en Suiza?» or «Pasa el correo a inglés» are not commands.
    Any language because Parakeet may well write «Speak Spanish» while in Spanish.
    """
    heard = [w for w in words(text) if w not in words(settings.get("name", "Jarvis"))]
    if not 0 < len(heard) <= 6:
        return None
    locales = [i18n.Locale(code) for code in i18n.available()]
    if not any(heard[0] in locale.list("commands.language") for locale in locales):
        return None
    for locale in locales:
        for code, name in locale.data["languages"].items():
            name = words(name)
            for i in range(1, len(heard) - len(name) + 1):
                rest = heard[1:i] + heard[i + len(name):]
                if heard[i:i + len(name)] == name and code in i18n.available() and all(len(w) <= 3 for w in rest):
                    return code
    return None


def is_yes(text: str) -> bool:
    """«Yes», «Sure, do it»… but not «No, wait» nor long sentences."""
    heard = set(words(text))
    return (0 < len(heard) <= 6 and not heard & set(i18n.L.list("commands.no"))
            and bool(heard & set(i18n.L.list("commands.yes"))))


def create(stt, llm, tts=None, wake=None, ear=None, guard=GUARD):
    """Returns the brain(speaker, send) factory that Session expects."""

    def brain(speaker, send):
        return Assistant(stt, wake() if wake else None, llm, tts, speaker, send, ear, guard)

    return brain


def split(text: str) -> tuple[list[str], str]:
    """Complete sentences and the unfinished rest: «Hi. How a» → (["Hi."], "How a")."""
    pieces = END_OF_SENTENCE.split(text)
    return [p.strip() for p in pieces[:-1] if p.strip()], pieces[-1]


class Assistant(Transcriber):
    def __init__(self, stt, wake, llm, tts, speaker, send, ear=None, guard=GUARD):
        super().__init__(stt, wake, speaker, send, ear, deaf=self._deaf, on_interrupt=self._interrupt)
        self.guard = guard
        self.said = []  # words of the last thing it said, to recognize its echo
        self.saying = []  # words of what it is saying now (sentence by sentence)
        self.llm = llm
        self.tts = tts
        self.turn = asyncio.Lock()  # one answer at a time, in order
        self.number = 0
        self.cut = 0  # number of the answer that was told to stop
        self.sentences = asyncio.Queue()  # (number, sentence); sentence None = end of answer
        if tts:
            asyncio.ensure_future(self._mouth())

    def _idle_state(self) -> str:
        """The resting state, or «question» if an action awaits your «yes» (the face shows it)."""
        try:
            pending = json.loads((CONFIRM / "pending.json").read_text())
            if time.time() - pending.get("at", 0) < settings.get("confirm_wait", 120):
                return "question"
        except (OSError, ValueError):
            pass
        return self.ear.idle_state

    def _deaf(self) -> bool:
        return self.speaker.speaking or time.time() - self.speaker.last_sound < self.guard

    def _is_echo(self, text: str, timings: dict) -> bool:
        """A short piece of what it just said: its own voice leaking into the microphone."""
        # When the sentence started: now, minus the STT time and its duration.
        started = time.time() - timings.get("stt_ms", 0) / 1000 - timings.get("audio_s", 0)
        if started - self.speaker.last_sound > ECHO_WINDOW:
            return False
        heard = words(text)
        return 0 < len(heard) <= ECHO_MAX_WORDS and f" {' '.join(heard)} " in f" {' '.join(self.said)} "

    def on_connect(self):
        super().on_connect()
        asyncio.ensure_future(self.llm.new())

    def on_message(self, data: dict):
        if data.get("type") == "tap" and (self.turn.locked() or self.speaker.speaking):
            self.stop()

    def _interrupt(self, text: str) -> bool:
        """The wake word heard while it speaks: stop, unless it was its own voice saying its name."""
        heard = words(text)
        if heard and sum(w in self.saying for w in heard) / len(heard) >= 0.6:
            log.info("its own voice, not an interruption: «%s»", settings.private(text))
            return False
        self.stop()
        return True

    def stop(self):
        log.info("stopped")
        self.cut = self.number
        self.speaker.stop()
        self._state(self._idle_state())

    def _woke_up(self):
        super()._woke_up()
        asyncio.ensure_future(self.llm.new())

    def _heard(self, text: str, timings: dict):
        if self._is_echo(text, timings):
            log.info("echo dropped: «%s»", settings.private(text))
            return
        if self._confirm(text):
            # It was the answer to an approval the LLM itself asked for (Hermes): not a new message.
            Transcriber._heard(self, text, timings)
            return
        language = language_command(text)
        command = f"language:{language}" if language else system_command(text)
        if command:
            Transcriber._heard(self, text, timings)  # shown on screen, but not sent to the LLM
            asyncio.ensure_future(self._command(command))
            return
        super()._heard(text, timings)
        asyncio.ensure_future(self._answer(text))

    async def _command(self, command: str):
        if command == "reload":
            log.info("reloading tools")
            await self.llm.reload()
            self._say(i18n.L("speech.reloaded"))
        elif command.startswith("language:"):
            code = command.split(":")[1]
            name = i18n.L.data["languages"].get(code, code)
            if code == i18n.L.code:
                self._say(i18n.L("speech.language_same", language=name))
                return
            log.info("switching to %s", code)
            settings.save(language=code)
            await self._restart(i18n.L("speech.language_changing", language=name))
        else:
            await self._restart(i18n.L("speech.restarting"))

    async def _restart(self, sentence: str):
        log.info("restarting the server")
        self._say(sentence)
        await asyncio.sleep(1)  # time to synthesize it and start
        quiet = 0
        for _ in range(120):  # until everything is said (quiet for a while: there are gaps between sentences)
            quiet = quiet + 1 if self.sentences.empty() and not self.speaker.speaking else 0
            if quiet >= 3:
                break
            await asyncio.sleep(0.25)
        os.kill(os.getpid(), signal.SIGHUP)  # main.py treats it as «restart»

    def _say(self, text: str):
        """A fixed system sentence: to the screen and, if there is a voice, to the speaker."""
        self.number += 1
        self.send({"type": "text", "author": "assistant", "id": self.number, "text": text, "partial": False})
        if self.tts:
            self.sentences.put_nowait((self.number, text))
            self.sentences.put_nowait((self.number, None))
        else:
            self._state(self._idle_state())

    def _confirm(self, text: str) -> bool:
        """If an action awaits the user's «yes», authorizes or cancels it.

        Returns True if the sentence was only for that and must not go to the LLM
        («consume»: approvals the plugin resolves itself, like Hermes's).
        """
        pending_json = CONFIRM / "pending.json"
        try:
            pending = json.loads(pending_json.read_text())
        except (OSError, ValueError):
            return False
        if time.time() - pending.get("at", 0) > settings.get("confirm_wait", 120):
            pending_json.unlink(missing_ok=True)
            return False
        if is_yes(text):
            (CONFIRM / "confirmed.json").write_text(
                json.dumps({"signature": pending["signature"], "until": time.time() + settings.get("confirm_valid", 60)})
            )
            log.info("confirmed: %s", settings.private(pending.get("action", "")))
        else:
            log.info("not confirmed («%s»): %s", settings.private(text), settings.private(pending.get("action", "")))
        pending_json.unlink(missing_ok=True)
        return bool(pending.get("consume"))

    async def _answer(self, text: str):
        async with self.turn:
            self.number += 1
            number = self.number
            message = {"type": "text", "author": "assistant", "id": number}
            self._state("thinking")
            self.saying = []
            start = time.time()
            first = None
            answer = rest = ""
            # Even if cut off, the whole answer is read: the plugin has to finish it.
            async for piece in self.llm.answer(text):
                if self.cut == number:
                    continue
                first = first or time.time() - start
                answer += piece
                self.send({**message, "text": answer, "partial": True})
                if self.tts:
                    sentences, rest = split(rest + piece)
                    for sentence in sentences:
                        self.sentences.put_nowait((number, sentence))
            if self.tts:
                if rest.strip():
                    self.sentences.put_nowait((number, rest.strip()))
                self.sentences.put_nowait((number, None))
            timings = {
                "llm_first_ms": round((first or 0) * 1000),
                "llm_ms": round((time.time() - start) * 1000),
            }
            self.send({**message, "text": answer, "partial": False, "timings": timings})
            log.info("«%s» %s", settings.private(answer), timings)
            self.said = words(answer)
            if not self.tts and self.cut != number:
                self._state(self._idle_state())
            await self._apply_settings()

    async def _apply_settings(self):
        """After an answer (in which the LLM may have used bin/settings): what changed in
        settings.json goes to the page now, or restarts the server when it can't change live."""
        changed = settings.refresh()
        if changed & {"face", "video"}:
            self.send({"type": "config"})  # the page reads /config again
        if changed - settings.LIVE:
            await self._restart(i18n.L("speech.restarting"))

    async def _mouth(self):
        """Says the sentences in order as they arrive; synthesizes one while the previous plays."""
        loop = asyncio.get_running_loop()
        while True:
            number, sentence = await self.sentences.get()
            if number == self.cut:
                continue
            if sentence is None:  # end of the answer: wait until it finishes playing
                while self.speaker.speaking and number != self.cut:
                    await asyncio.sleep(0.05)
                if number != self.cut:
                    self._state(self._idle_state())
                continue
            start = time.time()
            pcm = await loop.run_in_executor(None, self.tts.synthesize, sentence)
            if number == self.cut:
                continue
            if not self.speaker.speaking:
                self._state("speaking")
            self.saying += words(sentence)
            self.speaker.play(normalize(pcm))
            log.info("voice «%s» (%d ms)", settings.private(sentence), (time.time() - start) * 1000)
