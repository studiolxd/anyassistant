import numpy as np

from audio import normalize


def test_normalize_reaches_the_peak():
    out = normalize(np.array([0, 1000, -2000], dtype=np.int16))
    assert np.abs(out).max() == int(0.95 * 32767)
    assert out.dtype == np.int16


def test_normalize_leaves_silence_alone():
    assert normalize(np.zeros(10, dtype=np.int16)).tolist() == [0] * 10
    assert len(normalize(np.zeros(0, dtype=np.int16))) == 0
