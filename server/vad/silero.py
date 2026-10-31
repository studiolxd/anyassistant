"""Silero VAD (PyTorch): small and accurate, the default."""

from vad import RATE, VAD, register


@register("silero")
class Silero(VAD):
    def __init__(self):
        import torch
        from silero_vad import load_silero_vad

        # One thread is enough for 32 ms windows; with every core it competes with the
        # WebRTC loop and, with the Mac busy, Chrome considered the connection lost.
        torch.set_num_threads(1)
        self._torch = torch
        self._model = load_silero_vad()

    def probability(self, window):
        return self._model(self._torch.from_numpy(window), RATE).item()

    def reset(self):
        self._model.reset_states()
