"""Whisper on Windows and Linux: faster-whisper (CTranslate2), on the CPU (int8) or, with an
NVIDIA card and its CUDA libraries, on the GPU. Speech recognition, the fallback when Parakeet
drifts into another language (stt-parakeet-onnx) and the wake word's small Whisper.

Models by size name (downloaded once from Hugging Face): «small» by default on the CPU,
«large-v3-turbo» on a GPU; --stt-model chooses another (base, medium, large-v3…).
"""

import logging
import threading

import numpy as np

from stt import Transcriber, register

log = logging.getLogger("stt")
_models = {}
_loading = threading.Lock()


def gpu() -> bool:
    """Whether CTranslate2 sees an NVIDIA card."""
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def model(size: str):
    """A Whisper model, loaded once (several at a time: the STT one and the wake word's)."""
    with _loading:
        if size not in _models:
            from faster_whisper import WhisperModel

            loaded = None
            if gpu():
                try:
                    loaded = WhisperModel(size, device="cuda", compute_type="float16")
                except Exception as e:  # a card, but not its CUDA libraries (cuBLAS, cuDNN)
                    log.warning("whisper %s: no GPU (%r); on the CPU", size, e)
            _models[size] = loaded or WhisperModel(size, device="cpu", compute_type="int8")
        return _models[size]


def transcribe_fw(audio: np.ndarray, size: str, language: str, prompt: str | None = None) -> str:
    """Transcribes with a faster-whisper model (16 kHz float32 mono)."""
    segments, _ = model(size).transcribe(
        audio, language=language, beam_size=1,
        condition_on_previous_text=False,  # standalone sentences: it makes up less
        initial_prompt=prompt, vad_filter=False)
    return " ".join(s.text.strip() for s in segments).strip()


@register("faster-whisper")
class FasterWhisper(Transcriber):
    def __init__(self, language="en", model=None):
        super().__init__(language, model or ("large-v3-turbo" if gpu() else "small"))

    def transcribe(self, audio: np.ndarray) -> str:
        return transcribe_fw(audio, self.model, self.language)
