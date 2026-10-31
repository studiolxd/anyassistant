import numpy as np

from audio import RATE, beep, normalize


def test_normalize_reaches_the_peak():
    out = normalize(np.array([0, 1000, -2000], dtype=np.int16))
    assert np.abs(out).max() == int(0.95 * 32767)
    assert out.dtype == np.int16


def test_normalize_leaves_silence_alone():
    assert normalize(np.zeros(10, dtype=np.int16)).tolist() == [0] * 10
    assert len(normalize(np.zeros(0, dtype=np.int16))) == 0


def test_beep_is_two_short_notes_without_clicks():
    sound = beep()
    assert len(sound) == 2 * int(0.09 * RATE)
    assert abs(int(sound[0])) < 100 and abs(int(sound[-1])) < 100


def test_falling_beep_is_the_rising_one_reversed_in_pitch():
    half = int(0.09 * RATE)
    assert np.array_equal(beep()[:half], beep(falling=True)[half:])
