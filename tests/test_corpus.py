"""The audio corpus (tests/corpus, docs/corpus.md): its manifest, its text and mixing helpers, how it
compares with the baseline; and, with the corpus in the cache and -m corpus, the pipeline itself
against the baseline."""

import json
import os

import numpy as np
import pytest

import corpus
import stt
from corpus import run

FOUND = corpus.manifest()
CASES = corpus.by_id(FOUND)


# --- Text ---

@pytest.mark.parametrize("text, expected", [
    ("¿Qué hora es?", "que hora es"),
    ("Mañana, a las ocho… ¡en punto!", "mañana a las ocho en punto"),
    ("It's  a well-known  fact.", "it s a well known fact"),
    ("", ""),
])
def test_normalising(text, expected):
    assert corpus.normalise(text) == expected


def test_word_error_rate():
    assert corpus.wer("que hora es", "¿Qué hora es?") == 0
    assert corpus.wer("que hora es", "que hora") == pytest.approx(100 / 3)
    assert corpus.wer("que hora es", "") == 100
    assert corpus.wer("", "gracias") == 100 and corpus.wer("", "") == 0
    assert corpus.corpus_wer([("a b c d", "a b c d"), ("a b", "a x")]) == pytest.approx(100 / 6, abs=0.01)


# --- Mixing ---

def tone(seconds=2.0, frequency=220.0, level=0.1):
    t = np.arange(int(seconds * corpus.RATE)) / corpus.RATE
    return (np.sin(2 * np.pi * frequency * t) * level * np.sqrt(2)).astype(np.float32)


def test_mixing_at_an_snr():
    rng = np.random.default_rng(1)
    speech, noise = tone(), (rng.standard_normal(corpus.RATE * 30) * 0.05).astype(np.float32)
    mixed = corpus.mix(speech, noise, 10.0)
    lead = int(corpus.LEAD_NOISE * corpus.RATE)
    assert len(mixed) == lead + len(speech) + int(corpus.TAIL * corpus.RATE)
    background = mixed[:lead]  # noise alone before the speech
    snr = 20 * np.log10(corpus.speech_level(speech) / corpus.rms(background))
    assert snr == pytest.approx(10.0, abs=0.5)


def test_padding_and_segments():
    padded = corpus.pad(tone(1.0))
    assert len(padded) == int((corpus.LEAD + 1.0 + corpus.TAIL) * corpus.RATE)
    assert not padded[:100].any() and not padded[-100:].any()
    noise = np.arange(10, dtype=np.float32)
    assert list(corpus.segment(noise, 0.0, 4 / corpus.RATE)) == [0, 1, 2, 3]
    assert len(corpus.segment(noise, 0.0, 1.0)) == corpus.RATE  # repeated to fill


def test_reverberation_keeps_the_level():
    speech = tone(1.0)
    rir = np.zeros(corpus.RATE // 4, np.float32)
    rir[0], rir[2000], rir[3000] = 1.0, 0.5, 0.3
    wet = corpus.reverberate(speech, rir)
    assert len(wet) == len(speech)
    assert corpus.speech_level(wet) == pytest.approx(corpus.speech_level(speech), rel=0.05)


def test_wav_round_trip(tmp_path):
    audio = tone(0.5)
    corpus.write_wav(tmp_path / "a.wav", audio)
    back = corpus.read_wav(tmp_path / "a.wav")
    assert np.abs(back - audio).max() < 1e-4
    assert np.abs(corpus.decode((tmp_path / "a.wav").read_bytes()) - audio).max() < 1e-4


# --- The manifest ---

def test_manifest_is_consistent():
    ids = [c["id"] for c in FOUND["cases"]]
    assert len(ids) == len(set(ids)) and len(ids) >= 400
    for case in FOUND["cases"]:
        kind = case["kind"]
        if kind in ("speech", "noise", "rir"):
            assert case["source"] in FOUND["sources"] and len(case["sha256"]) == 64 and case["file"]
        if kind == "speech":
            assert case["lang"] in ("es", "en") and case["text"] == corpus.normalise(case["text"]) and case["text"]
            assert 1.5 <= case["seconds"] <= 12
        if kind == "noise":
            assert case["seconds"] > 0
        if kind == "mixed":
            assert CASES[case["speech"]]["kind"] == "speech" and CASES[case["noise"]]["kind"] == "noise"
            assert case["text"] == CASES[case["speech"]]["text"] and case["snr"] in (20, 10, 5)
        if kind == "room":
            assert CASES[case["speech"]]["kind"] == "speech" and CASES[case["rir"]]["kind"] == "rir"
    for source in FOUND["sources"].values():
        assert source["title"] and source["license"] and source["homepage"]
    speakers = {c["speaker"] for c in FOUND["cases"] if c.get("source") == "common_voice"}
    assert len(speakers) >= 50 and all(sum(c.get("speaker") == s for c in FOUND["cases"] if c["kind"] == "speech") == 4
                                       for s in speakers)


def test_selection_with_a_limit():
    chosen = run.selection(FOUND, 2)
    assert all(c["kind"] != "rir" for c in chosen)
    assert sum(c.get("source") == "common_voice" for c in chosen) == 2 * 4  # 2 speakers, their 4 clips
    assert sum(c["kind"] == "mixed" and c["snr"] == 5 for c in chosen) == 2 * 2  # two languages
    assert len(run.selection(FOUND)) == sum(c["kind"] != "rir" for c in FOUND["cases"])


# --- Against the baseline ---

def results(wer_of: dict, segments: dict, trials: dict | None = None) -> dict:
    return {"transcription": {"parakeet": {k: {"text": "x" if w else CASES[k].get("text", ""), "segments": 1, "wer": w}
                                           for k, w in wer_of.items()}},
            "segmentation": {"0.6": segments},
            "speakers": {"match": 0.5, "lower": 0.3, "trials": trials or {}}}


SPEECH = [c["id"] for c in FOUND["cases"] if c.get("source") == "common_voice"][:4]
NOISE = [c["id"] for c in FOUND["cases"] if c["kind"] == "noise"][:2]


def test_summary_and_comparison():
    before = results({SPEECH[0]: 0, SPEECH[1]: 0, SPEECH[2]: 50, NOISE[0]: 0}, {SPEECH[0]: 1, SPEECH[1]: 1, NOISE[0]: 0},
                     {SPEECH[1]: {"speaker": "cv-01", "kind": "speech", "snr": None, "own": 0.7, "others": [0.1, 0.2],
                                  "verdict": "accepted"}})
    summary = run.summarise(FOUND, before)
    assert summary["transcription"]["parakeet"]["clean es"]["exact"] == pytest.approx(66.7)
    assert summary["segmentation"]["0.6"]["one"] == 100 and summary["vad"]["0.6"]["false_starts"] == 0
    assert summary["speakers"]["clean"]["genuine_accepted"] == 100 and summary["speakers"]["clean"]["impostor_dropped"] == 100
    # The same: nothing to say.
    same = run.compare(FOUND, before, before)
    assert same == {"problems": [], "changes": [], "flips": []}
    # A sentence now wrong, a false start on noise, a speaker now unclear: changes and flips, within tolerance or not.
    after = results({SPEECH[0]: 100, SPEECH[1]: 0, SPEECH[2]: 50, NOISE[0]: 0}, {SPEECH[0]: 1, SPEECH[1]: 2, NOISE[0]: 3},
                    {SPEECH[1]: {"speaker": "cv-01", "kind": "speech", "snr": None, "own": 0.4, "others": [0.1, 0.2],
                                 "verdict": "unclear"}})
    found = run.compare(FOUND, before, after)
    assert any("now wrong" in f for f in found["flips"]) and any("1 → 2 sentences" in f for f in found["flips"])
    assert any("accepted → unclear" in f for f in found["flips"])
    assert any(p.startswith("parakeet clean es wer") for p in found["problems"])
    assert any("false_starts: 0 → 3" in p for p in found["problems"])
    assert any("genuine_accepted: 100 → 0" in p for p in found["problems"])


def test_comparison_restricts_the_baseline_to_what_ran():
    before = results({SPEECH[0]: 0, SPEECH[1]: 100}, {SPEECH[0]: 1, SPEECH[1]: 0})
    after = results({SPEECH[0]: 0}, {SPEECH[0]: 1})  # a run with a limit: only the first case
    assert run.compare(FOUND, before, after)["problems"] == []
    assert run.compare(FOUND, before, after)["changes"] == []


def test_equal_error_rate():
    rate, threshold = run.eer([0.8, 0.7, 0.6], [0.1, 0.2, 0.3])
    assert rate == 0 and 0.3 < threshold <= 0.6
    rate, threshold = run.eer([0.8, 0.2], [0.1, 0.7])
    assert rate == 50


def test_baseline_matches_the_manifest():
    baseline = run.load_baseline()
    if not baseline:
        pytest.skip("no baseline yet")
    for engine, per_case in baseline["transcription"].items():
        assert set(per_case) <= set(CASES), engine
    for per_case in baseline["segmentation"].values():
        assert set(per_case) <= set(CASES)
    assert set(baseline["speakers"]["trials"]) <= set(CASES)


# --- The pipeline itself, with the corpus in the cache ---

@pytest.mark.corpus
def test_pipeline_against_the_baseline(capsys):
    """Runs the ear, the engines installed here and the voices over the corpus (CORPUS_LIMIT=N:
    the first N cases of each kind) and fails if a metric got clearly worse than the baseline."""
    if not corpus.ready(FOUND):
        pytest.skip("the corpus isn't in the cache: bin/anyassistant corpus fetch")
    limit = int(os.environ["CORPUS_LIMIT"]) if os.environ.get("CORPUS_LIMIT") else None
    engines = stt.available()
    found = run.measure(FOUND, engines, limit, progress=lambda m: None)
    baseline = run.load_baseline()
    with capsys.disabled():
        print("\n" + run.report(found["summary"]))
    if not baseline:
        pytest.skip("no baseline yet: bin/anyassistant corpus baseline")
    changes = run.compare(FOUND, baseline, found)
    with capsys.disabled():
        for line in changes["changes"] + changes["flips"]:
            print("  " + line)
    assert not changes["problems"], "\n".join(changes["problems"])
