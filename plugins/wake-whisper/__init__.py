"""Wake word with a small Whisper: works for any word.

Silero VAD cuts sentences; each one is transcribed with whisper-base (~140 ms on
an M4) and the word is searched among the first ones, comparing by how it sounds
(«Yarvis», «Harvis», «G&J Arbis»…). If the sentence goes on after the word
("Hey Jarvis, what time is it?"), it is left in heard_sentence to be
transcribed in full.
"""

import logging
import re
from difflib import SequenceMatcher

import numpy as np

import i18n
import settings
from text import words
from wake import RATE, WakeWord, register

log = logging.getLogger("wake")

WINDOW = 512
THRESHOLD_ON = 0.5
THRESHOLD_OFF = 0.35
SILENCE = 0.5  # shorter than the ear's: the word usually comes alone
MAXIMUM = 15
PRE_ROLL = 0.3
FIRST_WORDS = 3  # the word must be at the start ("…he told Jarvis…" doesn't count)
SIMILARITY = 0.85  # «ya veis» scores 0.83; the right ones, 1.00


def phonetic(word: str) -> str:
    """Roughly how it sounds: «Jarvis», «Yarvis», «Harvis» → «yarbis»/«arbis».

    Tuned to how Whisper writes «Jarvis» said with a Spanish accent; harmless for
    other languages.
    """
    for a, b in (("ll", "y"), ("j", "y"), ("g", "y"), ("v", "b"), ("h", ""), ("z", "s")):
        word = word.replace(a, b)
    return word


def similarity(candidate: str, key: str) -> float:
    """How close the key is to the candidate or to a piece of it («gellarby»)."""
    best = SequenceMatcher(None, candidate, key).ratio()
    for i in range(max(len(candidate) - len(key) + 1, 0)):
        best = max(best, SequenceMatcher(None, candidate[i : i + len(key)], key).ratio())
    return best


@register("whisper")
class WhisperWakeWord(WakeWord):
    def __init__(self, word=None, threshold=SIMILARITY, model="mlx-community/whisper-base-mlx"):
        super().__init__(word or settings.get("name", "Jarvis").lower(), threshold)
        import vad
        from plugins.stt_mlx_whisper import transcribe_mlx

        self._transcribe = transcribe_mlx
        self.model = model
        self.keys = words(self.word)
        self.phrase = f"Hey {self.word.title()}" if len(self.keys) == 1 else self.word.capitalize()
        # Without a prompt, whisper-base writes «Geri Yarvis», «gellarby»…; with the
        # exact phrase as the prompt it skips it (it thinks it was already said).
        self.prompt = i18n.L("wake.whisper_prompt", name=self.word.title())
        self.vad = vad.create()
        self.heard_sentence = None  # the whole audio if the sentence goes on after the word
        self.last_text = ""  # the last transcription, to tell its own voice from yours
        self.dubious = False  # the last wake-up may not have been for it
        self._reset()
        self._transcribe(np.zeros(RATE // 2, dtype=np.float32), self.model, i18n.L.stt_language)

    def _reset(self):
        self.pending = np.zeros(0, dtype=np.float32)
        self.pre_roll = []
        self.chunks = []
        self.speaking = False
        self.silence = 0.0
        self.vad.reset()

    def reset(self):
        self._reset()

    def listen(self, audio: np.ndarray) -> bool:
        self.pending = np.concatenate([self.pending, audio])
        heard = False
        while len(self.pending) >= WINDOW:
            window, self.pending = self.pending[:WINDOW], self.pending[WINDOW:]
            heard = self._window(window) or heard
        return heard

    def _window(self, window: np.ndarray) -> bool:
        probability = self.vad.probability(window)
        if not self.speaking:
            self.pre_roll = (self.pre_roll + [window])[-int(PRE_ROLL * RATE / WINDOW):]
            if probability >= THRESHOLD_ON:
                self.speaking = True
                self.chunks = list(self.pre_roll)
                self.silence = 0.0
            return False

        self.chunks.append(window)
        self.silence = self.silence + WINDOW / RATE if probability < THRESHOLD_OFF else 0.0
        if self.silence < SILENCE and len(self.chunks) * WINDOW / RATE < MAXIMUM:
            return False

        audio = np.concatenate(self.chunks)
        self.speaking = False
        self.chunks = []
        self.pre_roll = []
        return self._search(audio)

    def _position(self, found: list[str]) -> tuple[int, int] | None:
        """(index, number of words) of the wake word among the first words.

        Also tries joining one more word: Whisper sometimes splits it
        («G&J Arbis» → «j» + «arbis»). Only a short one (a letter or a syllable):
        joining whole words found «Jarvis» in «llama Jarvis», as the fourth word.
        """
        key = phonetic("".join(self.keys))
        n = len(self.keys)
        for i in range(min(FIRST_WORDS, len(found))):
            for span in (n, n + 1):
                if i + span > len(found):
                    break
                if span > n and len(found[i]) > 3:
                    continue
                if similarity(phonetic("".join(found[i : i + span])), key) >= self.threshold:
                    return i, span
        return None

    def strip(self, text: str) -> str:
        """«Hey Jarvis, what time is it?» → «what time is it?»"""
        tokens = list(re.finditer(r"\w+", text))
        position = self._position(["".join(words(t.group())) for t in tokens])
        if position is None:
            return text
        i, span = position
        return text[tokens[i + span - 1].end() :].lstrip(" ,.!:;-")

    def is_prompt(self, text: str) -> bool:
        """Whisper giving back its own prompt («El asistente se llama Jarvis.»), a piece
        of it or a variation («Strips se llama Jarvis.»): it does so with noise or a
        voice it doesn't understand. Recognized by the prompt's words right before the
        name («se llama»), which nobody says to wake it up. Only the name alone
        («Jarvis.») is not, since that is what you say."""
        found, prompt = words(text), words(self.prompt)
        if not found or found == self.keys:
            return False
        if f" {' '.join(found)} " in f" {' '.join(prompt)} ":
            return True
        n = len(self.keys)
        before = next((prompt[max(i - 2, 0):i] for i in range(len(prompt)) if prompt[i:i + n] == self.keys), [])
        return any(found[i:i + n] == self.keys and found[max(i - 2, 0):i] == before and before
                   for i in range(len(found)))

    def _search(self, audio: np.ndarray) -> bool:
        text = self._transcribe(audio, self.model, i18n.L.stt_language, self.prompt)
        self.last_text = text
        if self.is_prompt(text):
            log.debug("whisper gave back its prompt (noise?): «%s»", settings.private(text))
            return False
        found = words(text)
        position = self._position(found)
        if position is None:
            if text:
                log.info("no wake word: «%s»", settings.private(text))
            return False
        log.info("wake word in «%s»", settings.private(text))
        i, span = position
        # Dubious: the name not at the start, or in a long sentence («…se llama Jarvis, y…»).
        self.dubious = i >= 2 or len(found) > 12
        self.heard_sentence = audio if found[i + span :] else None
        return True
