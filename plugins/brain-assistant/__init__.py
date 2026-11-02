"""Phase 3: listens, transcribes, answers with an LLM plugin and says it out loud.

Each «Hey Jarvis» starts a new conversation in the LLM, which remembers it until
it falls asleep. The answer reaches the screen in pieces as it is generated
("text" messages with the same id and partial=True until the last one), and as
soon as a sentence is complete it is synthesized and played while the next one
arrives. While it speaks it doesn't listen; tapping the screen stops it.

The screen follows the voice: when a sentence starts playing on the device (its speaker's
play() says when: after what was already queued), {"type": "speaking", "id", "start", "end"}
tells it which characters of the answer's text it is saying (in UTF-16 code units, as JavaScript,
Kotlin and Swift's utf16 count them), so the captions scroll to them.
"""

import asyncio
import logging
import re
import time

import numpy as np

import events
import hub
import i18n
import settings
import skills
import tools
from audio import louder, normalize
import llm
import options
import tts
import web
from options import Option
from brain import register
from plugins.brain_transcriber import Transcriber, listening, volume
from llm import SILENCE
from llm import detail as llm_detail
import kernel
from text import words

log = logging.getLogger("assistant")

options.add(Option("conversations", 2, "how many devices can be in a conversation at once (each its own LLM: "
                   "with Claude, two processes each); 1: one at a time, the others fall asleep", "assistant", "int",
                   live=True))

# Seconds deaf after speaking (--echo-guard): the time its voice takes to reach the
# tablet, play and come back through the microphone, plus room echo. With 0.6 s on
# the tablet the last word leaked in («…anything else?» → «Anything else?»).
GUARD = 1.2
ECHO_MAX_WORDS = 5  # an echo is a short piece of what it just said
OWN_WORDS = 0.6  # heard while it spoke, this share of its own pairs of words: its echo
# An echo starts right after it stops speaking (after the guard); an answer of yours
# that repeats its words («Delete only the two promotional ones…?» → «Only the two
# promotional ones») usually starts later: only what starts within this margin counts.
ECHO_WINDOW = 2.5

END_OF_SENTENCE = re.compile(r"(?<=[.!?…;:])\s+|\n+")


def create(stt, model, voice=None, wake=None, ear=None, guard=GUARD):
    """The brain(speaker, send) factory that Session expects, with these engines. `model`: an LLM
    (every device shares it), or a Conversations (an LLM per device)."""

    def brain(speaker, send):
        return Assistant(stt, wake() if wake else None, model, voice, speaker, send, ear, guard)

    return brain


class Conversations:
    """An LLM per device, so two people in two rooms each have their own conversation. Made the
    first time a device needs one (Claude: its process and a spare, ~1.5 s), kept for the next
    times; at most «conversations» (each costs memory): beyond that, the one used longest ago
    is closed (its device, if it was in a conversation, falls asleep)."""

    def __init__(self, make, general: str = "claude"):
        self.make = make  # function(name) → a new LLM
        self.general = general  # the LLM of the devices without one of their own
        self.llms = {}  # device (or session id): LLM, the most recently used last

    def wanted(self, device: str | None) -> str:
        """The device's own LLM («usa Gemini aquí», the plugin «devices»), if it can be used; else
        the general one."""
        import llm as engines

        devices = kernel.module("devices")
        own = devices.llm_of(device) if devices and device else None
        return own if own and own in engines.available() else self.general

    def __call__(self, assistant):
        session = hub.of(assistant)
        key = (session.device or session.id) if session else "?"
        wanted = self.wanted(session.device if session else None)
        found = self.llms.pop(key, None)
        turn = getattr(assistant, "turn", None)
        busy = bool(turn and turn.locked())  # never in the middle of an answer
        if found is not None and getattr(found, "chosen", self.general) != wanted and not busy:
            log.info("%s: now %s", key, wanted)  # its LLM changed: from its next question
            asyncio.ensure_future(found.close())
            found = None
        if found is None:
            found = self.make(wanted)
            found.chosen = wanted
            found.device = session.device if session else None  # its tools act on this device
            log.info("a conversation of its own for %s with %s (%d now)", key, wanted, len(self.llms) + 1)
            self._room()
        self.llms[key] = found
        return found

    def _room(self):
        """Closes the ones beyond «conversations» (counting the new one): the oldest first."""
        most = max(1, settings.get("conversations") or 2)
        while len(self.llms) >= most:
            key, oldest = next(iter(self.llms.items()))
            del self.llms[key]
            session = hub.by_device(key) or hub.sessions.get(key)
            if session is not None and hub._awake(session):
                session.brain.ear.sleep_for("its conversation was closed: too many at once")
            asyncio.ensure_future(oldest.close())
            log.info("conversation of %s closed (at most %d)", key, most)

    async def close(self):
        for found in list(self.llms.values()):
            await found.close()
        self.llms.clear()


RING_MAX = 30 * 60  # «until someone stops it» (ring_seconds 0) still ends: nobody may be home


def ring_for(seconds) -> float:
    """How long an alarm rings: ring_seconds; 0, until someone stops it (at most RING_MAX)."""
    if seconds is None or seconds == "":
        return 60
    seconds = float(seconds)
    return RING_MAX if seconds <= 0 else min(seconds, RING_MAX)


def utf16(text: str) -> int:
    """Its length as the screens count it (JavaScript, Kotlin): an emoji is two."""
    return len(text.encode("utf-16-le")) // 2


def split(text: str) -> tuple[list[str], str]:
    """Complete sentences and the unfinished rest: «Hi. How a» → (["Hi."], "How a")."""
    pieces = END_OF_SENTENCE.split(text)
    return [p.strip() for p in pieces[:-1] if p.strip()], pieces[-1]


@register("assistant")
class Assistant(Transcriber):
    @classmethod
    def create(cls, args):
        """Its engines from the settings: how it listens, the LLM (one per device: Conversations)
        and the voice."""
        engine, wake_factory, ear = listening(args)
        model = Conversations(lambda name: llm.create(name, model=args.llm_model if name == args.llm else None,
                                                      mcp=args.mcp), general=args.llm)
        log.info("LLM: %s (%s), a conversation per device", args.llm, args.llm_model or "default")
        voice = None
        if args.tts != "none":
            voice = tts.create(args.tts, voice=args.voice, rate=args.rate)
            log.info("voice: %s (%s)", voice.name, voice.voice)
            voice.warm_up()

            async def close_voice():
                voice.close()

            web.close_on_exit.append(close_voice)
        web.close_on_exit.append(model.close)
        return create(engine, model, voice, wake_factory, ear, args.echo_guard)

    def __init__(self, stt, wake, llm, tts, speaker, send, ear=None, guard=GUARD):
        super().__init__(stt, wake, speaker, send, ear, deaf=self._deaf, on_interrupt=self._interrupt,
                         busy=lambda: self.turn.locked() or bool(self.ringing), on_over=self._talked_over)
        self.ear.voice_may_wake = self._voice_may_wake
        self.doubt = False  # the first sentence after a dubious wake-up
        self.ringing = None  # the timer, alarm or reminder ringing now
        self.toning_until = 0.0  # while its tone plays it still listens: a tone isn't speech
        self.rang = None  # the last one that rang, to snooze it
        self.guard = guard
        self.said = []  # words of the last thing it said, to recognize its echo
        self.saying = []  # words of what it is saying now (sentence by sentence)
        self.transcript = []  # (who, text, the voice recognised) of this conversation, for memory
        self._llm = llm  # an LLM, or a Conversations that gives this device its own
        self.tts = tts
        self.turn = asyncio.Lock()  # one answer at a time, in order
        # Ids of the answers on screen: unique across restarts, or a new answer would
        # overwrite an old one the page still shows with the same id.
        self.number = int(time.time() * 1000)
        self.cut = 0  # number of the answer that was told to stop
        # (number, sentence[, where]); sentence None = end of answer; where: the sentence's first
        # character in the answer's text (UTF-16), for the screen («speaking»)
        self.sentences = asyncio.Queue()
        if tts:
            asyncio.ensure_future(self._mouth())

    @property
    def llm(self):
        """This device's LLM (its own conversation)."""
        return self._llm(self) if isinstance(self._llm, Conversations) else self._llm

    @llm.setter
    def llm(self, value):
        self._llm = value

    def _idle_state(self) -> str:
        """The resting state, or «question» if an action awaits your «yes» (the face shows it)."""
        if self.ringing:
            return "alarm"
        confirmation = kernel.module("confirmation")
        if confirmation and confirmation.waiting():
            return "question"
        return self.ear.idle_state

    def _voice_may_wake(self, audio) -> bool:
        """Its name said by a voice that isn't clearly another's (the plugin «voices»)."""
        voices = kernel.module("voices")
        return voices.may_wake(audio) if voices else True

    def _deaf(self) -> bool:
        if self.ringing:  # its tone isn't speech: it listens for «stop», «snooze» through it
            return self.speaker.speaking and time.time() > self.toning_until
        return self.speaker.speaking or time.time() - self.speaker.last_sound < self.guard

    def _is_echo(self, text: str, timings: dict) -> bool:
        """A short piece of what it just said (or is saying): its own voice leaking into the microphone."""
        heard = words(text)
        if timings.get("over") and self._own_words(heard):  # heard while it spoke: mostly its words
            return True
        # When the sentence started: now, minus the STT time and its duration.
        started = time.time() - timings.get("stt_ms", 0) / 1000 - timings.get("audio_s", 0)
        if started - self.speaker.last_sound > ECHO_WINDOW:
            return False
        if not 0 < len(heard) <= ECHO_MAX_WORDS:
            return False
        piece = f" {' '.join(heard)} "
        return piece in f" {' '.join(self.said)} " or piece in f" {' '.join(self.saying)} "

    def _own_words(self, heard: list) -> bool:
        """Longer than ECHO_MAX_WORDS and most of its pairs of words in a row (OWN_WORDS) are in
        what it is saying or just said: its echo, even not word for word (a device without echo
        cancellation hears all of it back). Pairs, not words: a question of yours may share words."""
        if len(heard) <= ECHO_MAX_WORDS:
            return False
        mine = {pair for said in (self.saying, self.said) for pair in zip(said, said[1:])}
        pairs = list(zip(heard, heard[1:]))
        return sum(pair in mine for pair in pairs) / len(pairs) >= OWN_WORDS

    def on_connect(self):
        super().on_connect()
        self.send_timers()
        if not isinstance(self._llm, Conversations):  # its own LLM is made when it first wakes
            if not hub.awake_elsewhere(self):  # one LLM for all: not another device's conversation
                asyncio.ensure_future(self.llm.new())

    def on_message(self, data: dict):
        super().on_message(data)
        if data.get("type") == "tap" and (self.ringing or settings.get("tap_to_stop", True) and (
                self.turn.locked() or self.speaker.speaking)):
            self.stop()

    def send_timers(self):
        alarms = kernel.module("skill-alarms")  # its timers, alarms and reminders, if it is there
        self.send({"type": "timers", "items": alarms.timers.pending() if alarms else []})

    async def ring(self, item: dict):
        """A timer, alarm or reminder is due: it rings until stopped (or ring_seconds). Only a reminder is
        also said (its text); a timer or an alarm is just its sound (words between rings only interrupt it)."""
        log.info("ringing: %s", item["kind"])
        self.ringing = self.rang = item
        self.ear.wake_up("alarm")  # so it hears «stop» or «snooze» without its name
        alarms = kernel.module("skill-alarms")
        sentence = alarms.ring_sentence(item) if alarms else ""
        self.send({"type": "alarm", "label": item.get("label") or sentence})
        self._state("alarm")
        pcm = alarms.alarm_sound(getattr(self, "theme", None) or settings.get("theme")) if alarms else None
        tone = louder(pcm, volume()) if pcm is not None else np.zeros(0, np.int16)
        until = time.time() + ring_for(settings.get("ring_seconds"))
        said = False
        while self.ringing is item and time.time() < until:
            self.toning_until = time.time() + len(tone) / 48000 + 0.1
            self.speaker.play(tone)
            await asyncio.sleep(len(tone) / 48000 + 0.3)
            if not said and item["kind"] == "reminder":
                said = True
                self._say(sentence)
                await asyncio.sleep(3)
            await asyncio.sleep(1.7)
        if self.ringing is item:  # nobody stopped it
            self._stop_ringing()

    def _stop_ringing(self):
        item, self.ringing = self.ringing, None
        self.send({"type": "alarm", "off": True})
        self._state(self._idle_state())
        for session in hub.all():  # ringing on several devices: stopped on one, it stops on all
            if item is not None and session.brain is not self and getattr(session.brain, "ringing", None) is item:
                session.brain._stop_ringing()

    def _state(self, state: str):
        # While ringing, the ear's «awake» or «listening» doesn't hide the alarm on the face.
        if self.ringing and state in ("awake", "listening", "asleep"):
            state = "alarm"
        self.shown = state
        super()._state(state)

    def hush(self):
        """«Stop» said on its own (skill-stop): an alarm ringing, or an answer it is still thinking or saying."""
        if self.ringing or self.turn.locked() or self.speaker.speaking:
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
        if self.ringing:
            item = self.ringing
            self._stop_ringing()
            events.emit("alarm_stopped", self, item)  # stopped by you, here (the morning summary…)
        self._state(self._idle_state())

    def _woke_up(self):
        super()._woke_up()
        self.told_where = ""  # a new conversation: where it is goes with its first message
        self.told_who = ""  # and who is talking (the plugin «voices»)
        self.voice = None  # who this conversation recognised
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
        await events.gather("asleep", self, transcript)  # memory…
        await self.llm.prepare()

    def _talked_over(self):
        """Someone talked over it while it spoke (listen_while_speaking), and not its echo: it stops
        at once, as «Jarvis, stop» without the name, before what was said is transcribed (even if
        it doesn't transcribe, it was a person); what was said, if anything, is answered."""
        if self.speaker.speaking or self.turn.locked():
            log.info("interrupted by voice (without its name)")
            self.stop()

    def _heard(self, text: str, timings: dict):
        # Learning a voice, you repeat what it just said («Di: …»): not its echo by its words (the
        # loudness, in the ear, still tells a real echo).
        if getattr(self, "learning", None) is None and self._is_echo(text, timings):
            log.info("echo dropped: «%s»", settings.private(text))
            return
        if timings.get("over"):
            self._talked_over()  # stopped already when the sentence ended; still speaking, now
        voices = kernel.module("voices")  # learning a voice, or only known voices count
        if voices and voices.screen(self, text, timings, getattr(self.ear, "last_audio", None), self._handle):
            return
        self._handle(text, timings)

    def _handle(self, text: str, timings: dict):
        self._timings = timings
        if skills.hear(text, self):  # time, timers, the camera, «speak English»…: without the LLM
            return
        super()._heard(text, timings)
        self.transcript.append(("user", text, getattr(self, "voice", None)))  # whose it is (the plugin «memory»)
        asyncio.ensure_future(self._interpret_or_answer(text))

    async def _interpret_or_answer(self, text: str):
        """Apple's model may still find a skill in it («avísame dentro de un rato largo…»); else, the LLM."""
        interpreter = kernel.module("interpreter")
        if interpreter and interpreter.enabled() and interpreter.sounds_like_one(text):
            self._state("thinking")
            reply = await interpreter.interpret(text)
            if reply:
                self.transcript.pop()  # not a conversation for the LLM
                self._say(reply)
                return
        await self._answer(text)

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
        web.stop(restart=True)

    # --- What skills may do (skills/) ---

    def show_heard(self, text: str):
        """What you said, on the screen (without sending it to the LLM)."""
        Transcriber._heard(self, text, getattr(self, "_timings", {}))

    def reply(self, text: str, sentence: str):
        """A skill's answer: what you said and what it says."""
        self.show_heard(text)
        log.info("skill: «%s»", settings.private(sentence))
        self._say(sentence)

    def say(self, sentence: str):
        self._say(sentence)

    def sleep(self, text: str):
        """«Go to sleep» (skill-sleep)."""
        self.ear.sleep(f"«{settings.private(text)}»")

    def later(self, coroutine):
        asyncio.ensure_future(coroutine)

    def restart(self, sentence: str):
        """Says it and restarts once it has said it."""
        asyncio.ensure_future(self._restart(sentence))

    def _say(self, text: str):
        """A fixed system sentence: to the screen and, if there is a voice, to the speaker."""
        self.number += 1
        self.send({"type": "text", "author": "assistant", "id": self.number, "text": text, "partial": False})
        if self.tts:
            self.sentences.put_nowait((self.number, text, 0))
            self.sentences.put_nowait((self.number, None))
        else:
            self._state(self._idle_state())

    async def _pieces(self, text: str, look):
        """The LLM's answer; if it can't answer (llm.Unavailable), plan B's (the plugin
        «llm-fallback»), saying so first, or why it couldn't."""
        try:
            async for piece in self.llm.answer(text, image=look):
                yield piece
        except llm.Unavailable as e:
            backup = kernel.module("llm-fallback")
            other = backup.instead(self.llm) if backup else None
            if other is None:
                yield e.sentence
                return
            log.warning("%s couldn't answer (%s): %s answers", self.llm.name, e.sentence, other.name)
            yield i18n.L("speech.fallback", name=self.llm.name.capitalize()) + " "
            try:
                async for piece in other.answer(text, image=None):
                    yield piece
            except llm.Unavailable as again:
                yield again.sentence

    async def _answer(self, text: str):
        async with self.turn:
            self.number += 1
            number = self.number
            message = {"type": "text", "author": "assistant", "id": number}
            eyes = kernel.module("eyes")
            image = eyes.capture() if eyes else None  # also for Claude's Read tool, if it decides to look
            if eyes and not image and (eyes.wants_to_look(text) or eyes.wants_to_read(text)):
                self._state("looking")  # no frames (the Mac's camera is off until shown): a photo now
                image = await eyes.photo()
            elif image and settings.get("read_photo", True) and eyes.wants_to_read(text):  # small text
                self._state("looking")
                image = await eyes.photo() or image
            look = image if image and (eyes.wants_to_look(text) or eyes.wants_to_read(text)) else None
            # It looks only if Claude opens the camera's image: Read also opens other files (a long
            # tool result Claude Code saved, like a list of invoices), which isn't looking.
            frame = str(eyes.FRAME) if eyes else None
            self.llm.on_tool = lambda name, arguments=None: self._looked() if (
                name == "Read" and image and frame and frame in str((arguments or {}).get("file_path", ""))) else None
            if look:
                self._looked()
            else:
                self._state("thinking")
            self.saying = []
            start = time.time()
            first = None
            answer = rest = ""
            said = 0  # where in the answer the next sentence is looked for (its place, for the screen)
            # Even if cut off, the whole answer is read: the plugin has to finish it.
            quiet = settings.get("ignore_others", True) is not False
            held = ""  # the start of the answer, until it is clear it isn't SILENCE
            async for piece in self._pieces(self._for_llm(text), look):
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
                        said = self._queue(number, sentence, answer, said)
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
                    self._queue(number, rest.strip(), answer, said)
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

    def _queue(self, number: int, sentence: str, answer: str, after: int) -> int:
        """A sentence to say, with where it is in the answer (from `after` on); returns where the
        next one is looked for."""
        at = answer.find(sentence, after)
        if at < 0:
            self.sentences.put_nowait((number, sentence))
            return after
        self.sentences.put_nowait((number, sentence, utf16(answer[:at])))  # as the screens count
        return at + len(sentence)

    def _speaking(self, number: int, sentence: str, at, starts):
        """The screen follows the voice: when this sentence starts playing on the device (`starts`,
        what its speaker's play() said; now if it can't tell), which characters of the answer it is."""
        if at is None:
            return
        message = {"type": "speaking", "id": number, "start": at, "end": at + utf16(sentence)}

        def tell():
            if number != self.cut:  # stopped meanwhile: it won't be said
                self.send(message)

        wait = starts - time.time() if isinstance(starts, (int, float)) else 0
        if wait > 0.01:
            asyncio.get_running_loop().call_later(wait, tell)
        else:
            tell()

    async def _apply_settings(self):
        """After an answer (in which the LLM may have used its own tools): what changed in
        settings.json goes to the page now, or restarts the server when it can't change live."""
        changed = settings.refresh()
        if changed & ({"theme", "theme_options", "video"} | settings.SCREEN):
            self.send({"type": "config"})  # the page reads /config again
        asked, tools.requested = set(tools.requested), set()  # by its own tools, during the answer
        if changed - settings.LIVE or "restart" in asked:
            await self._restart(i18n.L.text("speech.restarting", "Restarting."))
        elif "reload" in asked:
            await self.llm.reload()

    def _for_llm(self, text: str) -> str:
        """The message for the LLM: with a doubt after a dubious wake-up, the detail level if it changed,
        and where you're talking from (the plugin «devices») when the conversation starts or it changes."""
        text = self._with_who(self._with_where(self._with_detail(text)))
        if self.doubt:
            self.doubt = False
            text = ("(It isn't clear this was said to you: unless it is a request or a question for you, "
                    f"answer {SILENCE}.)\n{text}")
        return text

    def _with_who(self, text: str) -> str:
        """«(Suvi is talking.)»: with the first sentence, and when it changes (the plugin «voices»); with
        what it remembers about that person (the plugin «memory»: the instructions only have the shared
        notes, as they are written before it knows who is talking)."""
        voices = kernel.module("voices")
        who = voices.who(self) if voices else ""
        if not who or who == getattr(self, "told_who", ""):
            return text
        self.told_who = who
        memory = kernel.module("memory")
        notes = memory.about(getattr(self, "voice", None)) if memory else ""
        return f"{who}{notes}\n{text}"

    def _with_where(self, text: str) -> str:
        """«(You're talking through the device «iPad», in the room «dormitorio».)»: so «here» means
        something («la luz de aquí»), and a message to another device can say where it comes from."""
        devices = kernel.module("devices")
        where = devices.through(hub.of(self)) if devices else ""
        if not where or where == getattr(self, "told_where", ""):
            return text
        self.told_where = where
        return f"(The user is talking to you through {where}; «here» means there.)\n{text}"

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

    async def _still_thinking(self, number: int):
        """A sentence said («Un momento, lo miro») while the answer is still coming (the LLM, a
        tool): when it ends and nothing else is ready to say, the face thinks again, not a
        speaking mouth standing still."""
        await asyncio.sleep(0.2)
        while self.speaker.speaking:
            await asyncio.sleep(0.1)
        if (getattr(self, "shown", None) == "speaking" and self.turn.locked() and self.sentences.empty()
                and number != self.cut and number == self.number):
            self._state("thinking")

    async def _mouth(self):
        """Says the sentences in order as they arrive; synthesizes one while the previous plays."""
        loop = asyncio.get_running_loop()
        while True:
            number, sentence, *where = await self.sentences.get()
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
            starts = self.speaker.play(normalize(pcm, 0.95 * volume()))
            self._speaking(number, sentence, where[0] if where else None, starts)
            asyncio.ensure_future(self._still_thinking(number))
            log.info("voice «%s» (%d ms)", settings.private(sentence), (time.time() - start) * 1000)
