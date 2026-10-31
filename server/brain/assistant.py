"""Phase 3: listens, transcribes, answers with an LLM plugin and says it out loud.

Each «Hey Jarvis» starts a new conversation in the LLM, which remembers it until
it falls asleep. The answer reaches the screen in pieces as it is generated
("text" messages with the same id and partial=True until the last one), and as
soon as a sentence is complete it is synthesized and played while the next one
arrives. While it speaks it doesn't listen; tapping the screen stops it.
"""

import asyncio
import logging
import os
import re
import signal
import time

import confirmation
import eyes
import i18n
import memory
import settings
import skills
import skins
import tools
from audio import alarm_tone, louder, normalize
from brain.transcriber import volume
from skills import interpreter, timers
from skills.parse import duration, tokens
from llm import SILENCE
from llm import detail as llm_detail
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


def camera_command(text: str) -> str | None:
    """«Activa la cámara» → "on"; «Turn off the camera» → "off": the camera on the screen."""
    heard = words(text)
    if not 0 < len(heard) <= 6 or not set(heard) & set(i18n.L.list("commands.camera")):
        return None
    if set(heard) & set(i18n.L.list("commands.camera_off")):  # before «on»: «turn off»
        return "off"
    if set(heard) & set(i18n.L.list("commands.camera_on")):
        return "on"
    return None


def llm_command(text: str) -> str | None:
    """«Use Claude», «Cambia a Hermes» → "claude", "hermes". A command, not for the LLM:
    Apple's model has no tools, so this is the way back from it."""
    heard = [w for w in words(text) if w not in words(settings.get("name", "Jarvis"))]
    if not 0 < len(heard) <= 5 or heard[0] not in i18n.L.list("commands.switch"):
        return None
    rest = heard[1:]
    for name, spoken in tools.LLM_NAMES.items():
        if any(w in spoken for w in rest) and all(w in spoken or len(w) <= 3 or w in i18n.L.list("commands.llm_words")
                                                 for w in rest):
            return name
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
        super().__init__(stt, wake, speaker, send, ear, deaf=self._deaf, on_interrupt=self._interrupt,
                         on_stop=self._stopped, busy=lambda: self.turn.locked() or bool(self.ringing))
        self.doubt = False  # the first sentence after a dubious wake-up
        self.ringing = None  # the timer, alarm or reminder ringing now
        self.toning_until = 0.0  # while its tone plays it still listens: a tone isn't speech
        self.rang = None  # the last one that rang, to snooze it
        self.guard = guard
        self.said = []  # words of the last thing it said, to recognize its echo
        self.saying = []  # words of what it is saying now (sentence by sentence)
        self.transcript = []  # (who, text) of this conversation, for memory
        self.llm = llm
        self.tts = tts
        self.turn = asyncio.Lock()  # one answer at a time, in order
        # Ids of the answers on screen: unique across restarts, or a new answer would
        # overwrite an old one the page still shows with the same id.
        self.number = int(time.time() * 1000)
        self.cut = 0  # number of the answer that was told to stop
        self.sentences = asyncio.Queue()  # (number, sentence); sentence None = end of answer
        if tts:
            asyncio.ensure_future(self._mouth())

    def _idle_state(self) -> str:
        """The resting state, or «question» if an action awaits your «yes» (the face shows it)."""
        if self.ringing:
            return "alarm"
        if confirmation.pending(settings.get("confirm_wait") or confirmation.WAIT):
            return "question"
        return self.ear.idle_state

    def _deaf(self) -> bool:
        if self.ringing:  # its tone isn't speech: it listens for «stop», «snooze» through it
            return self.speaker.speaking and time.time() > self.toning_until
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
        self.send_timers()
        asyncio.ensure_future(self.llm.new())

    def on_message(self, data: dict):
        super().on_message(data)
        if data.get("type") == "tap" and (self.ringing or settings.get("tap_to_stop", True) and (
                self.turn.locked() or self.speaker.speaking)):
            self.stop()

    def send_timers(self):
        self.send({"type": "timers", "items": timers.pending()})

    async def ring(self, item: dict):
        """A timer, alarm or reminder is due: it rings until stopped (or ring_seconds), saying what it is."""
        log.info("ringing: %s", item["kind"])
        self.ringing = self.rang = item
        if self.ear.wake and not self.ear.awake:
            self.ear._wake_up()  # so it hears «stop» or «snooze» without its name
        sentence = skills.ring_sentence(item)
        self.send({"type": "alarm", "label": item.get("label") or sentence})
        self._state("alarm")
        own = skins.sound(getattr(self, "skin", None) or settings.get("skin"), "alarm")  # the skin's, if it has one
        tone = louder(own if own is not None else alarm_tone(), volume())
        until = time.time() + (settings.get("ring_seconds") or 60)
        said = False
        while self.ringing is item and time.time() < until:
            self.toning_until = time.time() + len(tone) / 48000 + 0.1
            self.speaker.play(tone)
            await asyncio.sleep(len(tone) / 48000 + 0.3)
            if not said:
                said = True
                self._say(sentence)
                await asyncio.sleep(3)
            await asyncio.sleep(1.7)
        if self.ringing is item:  # nobody stopped it
            self._stop_ringing()

    def _stop_ringing(self):
        self.ringing = None
        self.send({"type": "alarm", "off": True})
        self._state(self._idle_state())

    def _state(self, state: str):
        # While ringing, the ear's «awake» or «listening» doesn't hide the alarm on the face.
        if self.ringing and state in ("awake", "listening", "asleep"):
            state = "alarm"
        super()._state(state)

    def _stops_ringing(self, text: str) -> bool:
        """«Para», «apaga la alarma», «vale», «cancélalo»…: words meant to stop it."""
        vocabulary = i18n.L.data["skills"]["words"]
        meant = set(i18n.L.list("commands.stop")) | set(i18n.L.list("commands.yes")) | set(i18n.L.list("commands.sleep"))
        meant |= set(vocabulary["cancel"]) | set(vocabulary["timer"]) | set(vocabulary["alarm"]) | set(vocabulary["reminder"])
        meant |= set(i18n.L.list("commands.camera_off"))  # «apaga»
        return bool(set(words(text)) & meant)

    def _stopped(self):
        """«Stop» said on its own: an alarm ringing, or an answer it is still thinking or saying."""
        if self.ringing or self.turn.locked() or self.speaker.speaking:
            self.stop()

    def _snooze(self, text: str) -> str:
        span = duration(tokens(text))
        seconds = span.value if span else (settings.get("snooze_minutes") or 5) * 60
        item = self.rang
        timers.add(item["kind"], time.time() + seconds, item.get("label", ""))
        self.stop()
        return i18n.L("speech.snoozed", duration=skills.spoken_duration(seconds))

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
        if self.ringing:
            self._stop_ringing()
        self._state(self._idle_state())

    def _woke_up(self):
        super()._woke_up()
        self.transcript = []
        self.detail = llm_detail()  # the one in this conversation's instructions
        self.doubt = bool(getattr(self.wake, "dubious", False))
        asyncio.ensure_future(self.llm.new())

    def _fell_asleep(self, by_command: bool):
        super()._fell_asleep(by_command)
        transcript, self.transcript = self.transcript, []
        asyncio.ensure_future(self._remember(transcript))

    async def _remember(self, transcript):
        """While it sleeps: what to keep from the conversation, and ready for the next one."""
        await memory.after_conversation(self.llm, transcript)
        await self.llm.prepare()

    def _heard(self, text: str, timings: dict):
        if self._is_echo(text, timings):
            log.info("echo dropped: «%s»", settings.private(text))
            return
        if self._confirm(text):
            # It was the answer to an approval the LLM itself asked for (Hermes): not a new message.
            Transcriber._heard(self, text, timings)
            return
        language, camera, model = language_command(text), camera_command(text), llm_command(text)
        command = (f"language:{language}" if language else f"camera:{camera}" if camera
                   else f"llm:{model}" if model else system_command(text))
        if command:
            Transcriber._heard(self, text, timings)  # shown on screen, but not sent to the LLM
            asyncio.ensure_future(self._command(command))
            return
        if self.rang and set(words(text)) & set(i18n.L.data["skills"]["words"]["snooze"]):
            Transcriber._heard(self, text, timings)
            self._say(self._snooze(text))
            return
        if self.ringing:
            if not self._stops_ringing(text):  # its own tone, transcribed («Kimbo.»): not a word for it
                log.info("ignored while ringing: «%s»", settings.private(text))
                return
            Transcriber._heard(self, text, timings)
            self.stop()
            return
        reply = skills.quick(text)  # time, timers, sums…: at once, without the LLM
        if reply:
            Transcriber._heard(self, text, timings)
            log.info("skill: «%s»", settings.private(reply))
            self._say(reply)
            return
        super()._heard(text, timings)
        self.transcript.append(("user", text))
        asyncio.ensure_future(self._interpret_or_answer(text))

    async def _interpret_or_answer(self, text: str):
        """Apple's model may still find a skill in it («avísame dentro de un rato largo…»); else, the LLM."""
        if interpreter.enabled() and skills.sounds_like_one(text):
            self._state("thinking")
            reply = await interpreter.interpret(text)
            if reply:
                self.transcript.pop()  # not a conversation for the LLM
                self._say(reply)
                return
        await self._answer(text)

    async def _command(self, command: str):
        if command == "reload":
            log.info("reloading tools")
            await self.llm.reload()
            self._say(i18n.L("speech.reloaded"))
        elif command.startswith("camera:"):
            on = command == "camera:on"
            log.info("camera on the screen: %s", "on" if on else "off")
            self.send({"type": "camera", "on": on})
            self._say(i18n.L("speech.camera_on" if on else "speech.camera_off"))
        elif command.startswith("llm:"):
            name = command.split(":")[1]
            why = tools.llm_ready(name)
            if name == settings.get("llm"):
                self._say(i18n.L("speech.llm_same", llm=name.capitalize()))
            elif why:
                log.info("can't switch to %s: %s", name, why)
                self._say(i18n.L("speech.llm_unavailable", llm=name.capitalize()))
            else:
                log.info("switching to %s", name)
                settings.save(llm=name, llm_model=None)
                await self._restart(i18n.L("speech.llm_changing", llm=name.capitalize()))
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
        if not confirmation.pending(settings.get("confirm_wait") or confirmation.WAIT):
            return False
        yes = is_yes(text)
        pending = confirmation.answer(yes, settings.get("confirm_valid") or confirmation.VALID)
        if yes:
            log.info("confirmed: %s", settings.private(pending.get("action", "")))
        else:
            log.info("not confirmed («%s»): %s", settings.private(text), settings.private(pending.get("action", "")))
        return bool(pending.get("consume"))

    async def _answer(self, text: str):
        async with self.turn:
            self.number += 1
            number = self.number
            message = {"type": "text", "author": "assistant", "id": number}
            image = eyes.capture()  # also for Claude's Read tool, if it decides to look
            if image and settings.get("read_photo", True) and eyes.wants_to_read(text):  # small text
                self._state("looking")
                image = await eyes.photo() or image
            look = image if image and (eyes.wants_to_look(text) or eyes.wants_to_read(text)) else None
            self.llm.on_tool = lambda name: self._looked() if name == "Read" and image else None
            if look:
                self._looked()
            else:
                self._state("thinking")
            self.saying = []
            start = time.time()
            first = None
            answer = rest = ""
            # Even if cut off, the whole answer is read: the plugin has to finish it.
            quiet = settings.get("ignore_others", True) is not False
            held = ""  # the start of the answer, until it is clear it isn't SILENCE
            async for piece in self.llm.answer(self._for_llm(text), image=look):
                if self.cut == number:
                    continue
                first = first or time.time() - start
                if quiet and held is not None:
                    held += piece
                    if SILENCE.startswith(held.strip()) or held.strip().startswith(SILENCE):
                        continue  # maybe «<silence>»: nothing shown or said yet
                    piece, held = held, None
                answer += piece
                self.send({**message, "text": answer, "partial": True})
                if self.tts:
                    sentences, rest = split(rest + piece)
                    for sentence in sentences:
                        self.sentences.put_nowait((number, sentence))
            if quiet and held is not None and held.strip().startswith(SILENCE):
                log.info("not for it: no answer")
                if self.transcript and self.transcript[-1][0] == "user":
                    self.transcript.pop()  # someone else's words: not for its memory either
                self._state(self._idle_state())
                return
            if quiet and held:  # a short answer that only looked like the start of it
                answer += held
                self.send({**message, "text": answer, "partial": True})
                rest += held
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
            self.transcript.append(("assistant", answer))
            if not self.tts and self.cut != number:
                self._state(self._idle_state())
            await self._apply_settings()

    async def _apply_settings(self):
        """After an answer (in which the LLM may have used its own tools): what changed in
        settings.json goes to the page now, or restarts the server when it can't change live."""
        changed = settings.refresh()
        if changed & ({"skin", "skin_options", "video"} | settings.SCREEN):
            self.send({"type": "config"})  # the page reads /config again
        asked, tools.requested = set(tools.requested), set()  # by its own tools, during the answer
        if changed - settings.LIVE or "restart" in asked:
            await self._restart(i18n.L("speech.restarting"))
        elif "reload" in asked:
            await self.llm.reload()

    def _for_llm(self, text: str) -> str:
        """The message for the LLM: with a doubt after a dubious wake-up, and the detail level if it changed."""
        text = self._with_detail(text)
        if self.doubt:
            self.doubt = False
            text = ("(It isn't clear this was said to you: unless it is a request or a question for you, "
                    f"answer {SILENCE}.)\n{text}")
        return text

    def _with_detail(self, text: str) -> str:
        """If the detail level changed mid-conversation, the LLM hears it with this message."""
        current = llm_detail()
        if current == getattr(self, "detail", current):
            return text
        self.detail = current
        return f"(From now on: {current})\n{text}"

    def _looked(self):
        """It looks through the camera: the face says so and the screen shows the photo."""
        self._state("looking")
        self.send({"type": "look", "at": time.time()})

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
            self.speaker.play(normalize(pcm, 0.95 * volume()))
            log.info("voice «%s» (%d ms)", settings.private(sentence), (time.time() - start) * 1000)
