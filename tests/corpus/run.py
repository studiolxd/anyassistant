"""Runs the server's own listening pipeline over the corpus, offline, and measures it; compares
the result with the baseline (baseline.json) and says what changed.

Each case's audio goes through an Ear (plugins/brain-transcriber/ear.py: the VAD, the noise
floor, the sentence ends) exactly as a device's microphone would send it (48 kHz PCM in 20 ms
chunks), and what the ear cuts goes to the speech engine, as when the assistant listens:

- transcription: the WER of what came out of the ear against the expected text, per engine
  installed here (parakeet and mlx-whisper on a Mac; faster-whisper and parakeet-onnx elsewhere),
  for clean speech per language and source, speech in noise per SNR, and speech in a room;
  and «phantom» sentences: noise-only cases that came out as text;
- sentence ends: with several values of «silence», how many sentences the ear made of each
  one-sentence case (one: right; more: cut in two; none: lost);
- voice activity in noise: false starts on noise-only cases (a sentence sent to the engine);
- who is speaking (the plugin «voices»): each Common Voice speaker learnt from two clips,
  judged on the other two; the accept and reject rates at «voice_match» and at its lower bound,
  and the equal error rate, to see where the default could be.

    bin/anyassistant corpus run [--limit N] [--engine NAME…] [--silence S…] [--json FILE]
    bin/anyassistant corpus baseline          # writes baseline.json from a full run
"""

import asyncio
import importlib
import json
import logging
import platform
import sys
import time
from importlib import metadata
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

import i18n
import kernel
import settings
import stt
from corpus import (BASELINE, LEAD, LEAD_NOISE, RATE, by_id, case_path, corpus_wer, folder, manifest, read_wav, wer)

kernel.load_all()
ear_module = importlib.import_module("plugins.brain_transcriber.ear")
Ear, NoiseFloor = ear_module.Ear, ear_module.NoiseFloor

SILENCES = (0.4, 0.6, 0.8, 1.0)  # the «silence» values tried (0.6: the default)
CHUNK = 960  # 20 ms at 48 kHz, what a device sends
# How much worse a metric may get before test_corpus fails (points of %, or a count).
TOLERANCE = {"wer": 2.0, "exact": 3.0, "one": 3.0, "false_starts": 2, "phantom": 2,
             "genuine_accepted": 2.0, "impostor_accepted": 1.0, "misidentified": 1.0, "eer": 1.0}
log = logging.getLogger("corpus")


class Listener:
    """An Ear fed a case as a device would send it, with an engine (or none: only how it cuts)."""

    name = "corpus"

    def __init__(self, engine=None, silence: float = ear_module.SILENCE):
        self.engine = engine
        self.segments: list[float] = []
        self.texts: list[str] = []
        self.ear = Ear(self, on_state=lambda state: None, on_heard=self._heard, silence=silence)

    def transcribe(self, audio: np.ndarray) -> str:  # as the ear's STT
        self.segments.append(len(audio) / RATE)
        return self.engine.transcribe(audio) if self.engine else "…"

    def _heard(self, text: str, timings: dict):
        self.texts.append(text)

    def listen(self, audio: np.ndarray) -> dict:
        """What the ear made of a 16 kHz case: the sentences it cut and the text that came out."""
        self.segments, self.texts = [], []
        self.ear._reset()
        self.ear.noise = NoiseFloor()  # a fresh room each time: cases don't depend on their order
        pcm = (np.clip(resample_poly(audio.astype(np.float64), 3, 1), -1, 1) * 32767).astype(np.int16)

        async def feed():
            for i in range(0, len(pcm), CHUNK):
                self.ear.hear(pcm[i:i + CHUNK])
            pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            if pending:
                await asyncio.gather(*pending)

        asyncio.run(feed())
        return {"segments": len(self.segments), "text": " ".join(self.texts)}


def selection(found: dict, limit: int | None = None) -> list[dict]:
    """The cases measured (not the impulse responses): with a limit, the first N of each kind (of
    Common Voice, the first N speakers with their four clips, so the voices can still be judged)."""
    chosen, counts = [], {}
    for case in found["cases"]:
        if case["kind"] == "rir":
            continue
        key = (case["kind"], case.get("source", ""), case.get("lang", ""), case.get("snr", ""))
        unit = case["speaker"] if case.get("source") == "common_voice" else case["id"]
        counts.setdefault(key, [])
        if unit not in counts[key]:
            counts[key].append(unit)
        if limit is None or counts[key].index(unit) < limit:
            chosen.append(case)
    return chosen


def languages(cases: list[dict]) -> list[str]:
    return sorted({c.get("lang", "es") for c in cases if c.get("lang")})


def machine() -> dict:
    versions = {}
    for package in ("parakeet-mlx", "mlx-whisper", "faster-whisper", "onnx-asr", "silero-vad", "onnxruntime", "torch"):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            pass
    return {"system": platform.system(), "machine": platform.machine(), "python": platform.python_version(),
            "packages": versions}


def measure(found: dict, engines: list[str], limit: int | None = None, silences=SILENCES, progress=print) -> dict:
    """Everything, per case; summarise() makes the numbers."""
    cases = selection(found, limit)
    audio = {c["id"]: read_wav(case_path(c["id"])) for c in cases}
    settings.active.clear()  # the defaults, not this computer's settings.json
    results = {"made": time.strftime("%Y-%m-%d %H:%M"), "machine": machine(), "cases": len(cases),
               "limit": limit, "engines": engines, "silences": [str(s) for s in silences],
               "segmentation": {}, "transcription": {}, "speakers": {}}

    for silence in silences:
        progress(f"sentence ends with silence {silence:g} s: {len(cases)} cases…")
        listener = Listener(None, silence)
        results["segmentation"][str(silence)] = {c["id"]: listener.listen(audio[c["id"]])["segments"] for c in cases}

    for name in engines:
        progress(f"{name}: loading…")
        made = {}
        for lang in languages(cases):
            made[lang] = stt.create(name, language=lang)
            made[lang].warm_up()
        listener = Listener()
        per_case = {}
        started = time.time()
        for n, case in enumerate(cases, 1):
            lang = case.get("lang", "es")
            i18n.use(lang)
            listener.engine = made[lang]
            heard = listener.listen(audio[case["id"]])
            per_case[case["id"]] = {"text": heard["text"], "segments": heard["segments"],
                                    "wer": round(wer(case.get("text", ""), heard["text"]), 2)}
            if n % 50 == 0:
                progress(f"  {n}/{len(cases)} ({time.time() - started:.0f} s)")
        i18n.use("en")
        results["transcription"][name] = per_case
        for engine in made.values():
            engine.unload()

    progress("who is speaking…")
    results["speakers"] = speakers(found, cases, audio, progress)
    results["summary"] = summarise(found, results)
    return results


# --- Who is speaking ---

def clip_of(case: dict, audio: np.ndarray, cases: dict) -> np.ndarray:
    """The sentence itself inside a case's audio (without the silence or noise around it)."""
    if case["kind"] == "speech":
        start = int(LEAD * RATE)
        length = int(case["seconds"] * RATE)
    elif case["kind"] == "mixed":
        start = int(LEAD_NOISE * RATE)
        length = int(cases[case["speech"]]["seconds"] * RATE)
    else:  # room
        start = int(LEAD * RATE)
        length = int(cases[case["speech"]]["seconds"] * RATE)
    return audio[start:start + length]


def speakers(found: dict, cases: list[dict], audio: dict, progress=print) -> dict:
    """Common Voice speakers: learnt from their first and third clips (the plugin's learn), judged
    on the second and fourth, clean, in noise and in rooms. For each trial, their own score, the
    scores of everyone else (impostors) and the plugin's verdict."""
    voices = kernel.load("voices")
    store = folder() / "voices.json"
    if store.exists():
        store.unlink()
    voices.FILE = store
    everyone = by_id(found)
    speech = [c for c in cases if c["kind"] == "speech" and str(c.get("speaker", "")).startswith("cv-")]
    enrolled = sorted({c["speaker"] for c in speech if c["id"].endswith(("-1", "-3"))})
    prints = {}
    for speaker in enrolled:
        clips = [c for c in speech if c["speaker"] == speaker and c["id"].endswith(("-1", "-3"))]
        prints[speaker] = [voices.voice_print(clip_of(c, audio[c["id"]], everyone)) for c in clips]
        voices.learn(speaker, prints[speaker])
    if not enrolled:
        return {"enrolled": 0, "trials": {}}
    trials = {}
    tested = [c for c in cases if str(c.get("speaker", "")).startswith("cv-") and c["speaker"] in prints
              and (c["kind"] != "speech" or c["id"].endswith(("-2", "-4")))]
    for n, case in enumerate(tested, 1):
        clip = clip_of(case, audio[case["id"]], everyone)
        heard = voices.voice_print(clip)
        scores = {name: score for score, name, _ in voices.ranked(heard)}
        verdict = voices.judge(clip, None)
        if verdict.counts:
            outcome = "accepted" if verdict.name == case["speaker"] else f"other:{verdict.name}"
        elif verdict.unclear:
            outcome = "unclear"
        else:
            outcome = "unknown"
        trials[case["id"]] = {
            "speaker": case["speaker"], "kind": case["kind"], "snr": case.get("snr"),
            "own": round(scores.get(case["speaker"], 0.0), 3),
            "others": [round(s, 3) for name, s in sorted(scores.items()) if name != case["speaker"]],
            "verdict": outcome,
        }
        if n % 50 == 0:
            progress(f"  {n}/{len(tested)}")
    store.unlink(missing_ok=True)
    return {"enrolled": len(enrolled), "match": voices.match(), "lower": voices.lower(), "trials": trials}


def eer(genuine: list[float], impostor: list[float]) -> tuple[float, float]:
    """The equal error rate (%) and the threshold where false accepts equal false rejects."""
    if not genuine or not impostor:
        return 0.0, 0.0
    genuine, impostor = np.sort(genuine), np.sort(impostor)
    best = None
    for threshold in np.unique(np.concatenate([genuine, impostor])):
        far = 100.0 * np.mean(impostor >= threshold)
        frr = 100.0 * np.mean(genuine < threshold)
        gap = abs(far - frr)
        if best is None or gap < best[0]:
            best = (gap, float(threshold), (far + frr) / 2)
    return round(best[2], 2), round(best[1], 3)


# --- The numbers ---

def percent(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def summarise(found: dict, results: dict) -> dict:
    """The metrics from the per-case results (of a baseline too, restricted to some cases)."""
    cases = by_id(found)
    summary: dict = {"transcription": {}, "segmentation": {}, "vad": {}, "speakers": {}}

    for engine, per_case in results.get("transcription", {}).items():
        groups: dict = {}
        for case_id, got in per_case.items():
            case = cases.get(case_id)
            if case is None:
                continue
            keys = []
            if case["kind"] == "speech":
                keys += [f"clean {case['lang']}", f"{case['source']} {case['lang']}"]
            elif case["kind"] == "mixed":
                keys += [f"noise {case['snr']} dB"]
            elif case["kind"] == "room":
                keys += ["room"]
            for key in keys:
                groups.setdefault(key, []).append((case.get("text", ""), got["text"]))
        metrics = {}
        for key, pairs in sorted(groups.items()):
            metrics[key] = {"wer": corpus_wer(pairs), "exact": percent(sum(wer(r, h) == 0 for r, h in pairs), len(pairs)),
                            "cases": len(pairs)}
        noise = [got for case_id, got in per_case.items() if cases.get(case_id, {}).get("kind") == "noise"]
        metrics["phantom"] = {"sentences": sum(1 for got in noise if got["text"].strip()), "cases": len(noise)}
        summary["transcription"][engine] = metrics

    for silence, per_case in results.get("segmentation", {}).items():
        speech = {k: v for k, v in per_case.items() if cases.get(k, {}).get("kind") in ("speech", "mixed", "room")}
        noise = {k: v for k, v in per_case.items() if cases.get(k, {}).get("kind") == "noise"}
        minutes = sum(cases[k]["seconds"] for k in noise) / 60
        summary["segmentation"][silence] = {
            "one": percent(sum(v == 1 for v in speech.values()), len(speech)),
            "split": percent(sum(v > 1 for v in speech.values()), len(speech)),
            "missed": percent(sum(v == 0 for v in speech.values()), len(speech)),
            "cases": len(speech),
        }
        summary["vad"][silence] = {"false_starts": sum(noise.values()), "cases": len(noise),
                                   "per_minute": round(sum(noise.values()) / minutes, 2) if minutes else 0.0}

    trials = results.get("speakers", {}).get("trials", {})
    match = results.get("speakers", {}).get("match", 0.5)
    lower = results.get("speakers", {}).get("lower", 0.3)
    by_kind: dict = {}
    for trial in trials.values():
        key = "clean" if trial["kind"] == "speech" else (f"noise {trial['snr']} dB" if trial["kind"] == "mixed" else "room")
        by_kind.setdefault(key, []).append(trial)
    for key, found_trials in sorted(by_kind.items()):
        own = [t["own"] for t in found_trials]
        others = [s for t in found_trials for s in t["others"]]
        rate, threshold = eer(own, others)
        verdicts = [t["verdict"] for t in found_trials]
        summary["speakers"][key] = {
            "trials": len(found_trials), "impostor_trials": len(others),
            "genuine_accepted": percent(sum(s >= match for s in own), len(own)),
            "genuine_unclear": percent(sum(lower <= s < match for s in own), len(own)),
            "genuine_dropped": percent(sum(s < lower for s in own), len(own)),
            "impostor_accepted": percent(sum(s >= match for s in others), len(others)),
            "impostor_unclear": percent(sum(lower <= s < match for s in others), len(others)),
            "impostor_dropped": percent(sum(s < lower for s in others), len(others)),
            "misidentified": percent(sum(v.startswith("other:") for v in verdicts), len(verdicts)),
            "eer": rate, "eer_threshold": threshold,
            "genuine_median": round(float(np.median(own)), 3) if own else 0.0,
            "impostor_max_median": round(float(np.median([max(t["others"]) for t in found_trials if t["others"]])), 3)
            if any(t["others"] for t in found_trials) else 0.0,
        }
    return summary


# --- Against the baseline ---

def restrict(baseline: dict, results: dict) -> dict:
    """The baseline's per-case results, only for the cases and engines the results have."""
    kept = {"transcription": {}, "segmentation": {}, "speakers": {"trials": {}}}
    for engine, per_case in results.get("transcription", {}).items():
        if engine in baseline.get("transcription", {}):
            kept["transcription"][engine] = {k: v for k, v in baseline["transcription"][engine].items() if k in per_case}
    for silence, per_case in results.get("segmentation", {}).items():
        if silence in baseline.get("segmentation", {}):
            kept["segmentation"][silence] = {k: v for k, v in baseline["segmentation"][silence].items() if k in per_case}
    trials = results.get("speakers", {}).get("trials", {})
    old = baseline.get("speakers", {})
    kept["speakers"] = {**{k: v for k, v in old.items() if k != "trials"},
                        "trials": {k: v for k, v in old.get("trials", {}).items() if k in trials}}
    return kept


def compare(found: dict, baseline: dict, results: dict) -> dict:
    """What got worse beyond the tolerance (problems), every metric that moved (changes) and the
    cases that flipped (flips), comparing like with like."""
    old = summarise(found, restrict(baseline, results))
    new = summarise(found, results)
    problems, changes, flips = [], [], []

    def check(label, metric, before, after, higher_is_worse):
        if before is None or after is None or before == after:
            return
        changes.append(f"{label} {metric}: {before:g} → {after:g}")
        worse = after - before if higher_is_worse else before - after
        if metric in TOLERANCE and worse > TOLERANCE[metric]:
            problems.append(f"{label} {metric}: {before:g} → {after:g} (tolerance {TOLERANCE[metric]:g})")

    for engine, metrics in new["transcription"].items():
        was = old["transcription"].get(engine)
        if was is None:
            changes.append(f"{engine}: no baseline here")
            continue
        for key, values in metrics.items():
            if key == "phantom":
                check(f"{engine} phantom", "phantom", was.get(key, {}).get("sentences"), values["sentences"], True)
                continue
            check(f"{engine} {key}", "wer", was.get(key, {}).get("wer"), values["wer"], True)
            check(f"{engine} {key}", "exact", was.get(key, {}).get("exact"), values["exact"], False)
        for case_id, got in results["transcription"][engine].items():
            before = baseline["transcription"].get(engine, {}).get(case_id)
            if before and (before["wer"] == 0) != (got["wer"] == 0):
                flips.append(f"{engine} {case_id}: {'now wrong' if got['wer'] else 'now right'} "
                             f"(WER {before['wer']:g} → {got['wer']:g}): «{before['text']}» → «{got['text']}»")
    for silence, values in new["segmentation"].items():
        was = old["segmentation"].get(silence)
        if was is None:
            continue
        check(f"silence {silence}", "one", was["one"], values["one"], False)
        check(f"silence {silence} noise", "false_starts", old["vad"][silence]["false_starts"],
              new["vad"][silence]["false_starts"], True)
        for case_id, got in results["segmentation"][silence].items():
            before = baseline["segmentation"].get(silence, {}).get(case_id)
            if before is not None and before != got:
                flips.append(f"silence {silence} {case_id}: {before} → {got} sentences")
    for key, values in new["speakers"].items():
        was = old["speakers"].get(key)
        if was is None:
            continue
        for metric, higher_is_worse in (("genuine_accepted", False), ("impostor_accepted", True),
                                        ("misidentified", True), ("eer", True), ("genuine_dropped", True),
                                        ("impostor_dropped", False)):
            check(f"speakers {key}", metric, was.get(metric), values.get(metric), higher_is_worse)
    for trial_id, trial in results.get("speakers", {}).get("trials", {}).items():
        before = baseline.get("speakers", {}).get("trials", {}).get(trial_id)
        if before and before["verdict"] != trial["verdict"]:
            flips.append(f"speaker {trial_id}: {before['verdict']} → {trial['verdict']} (own {before['own']:g} → {trial['own']:g})")
    return {"problems": problems, "changes": changes, "flips": flips}


# --- Reports ---

def report(summary: dict) -> str:
    lines = []
    for engine, metrics in summary.get("transcription", {}).items():
        lines.append(f"{engine}:")
        for key, values in metrics.items():
            if key == "phantom":
                lines.append(f"  phantom sentences from noise: {values['sentences']} of {values['cases']} cases")
            else:
                lines.append(f"  {key:<16} WER {values['wer']:5.1f} %   exact {values['exact']:5.1f} %   ({values['cases']} cases)")
    if summary.get("segmentation"):
        lines.append("sentence ends (speech cases: one sentence expected) and false starts (noise-only):")
        for silence, values in summary["segmentation"].items():
            vad = summary["vad"][silence]
            lines.append(f"  silence {silence} s: one {values['one']:5.1f} %  split {values['split']:4.1f} %  "
                         f"missed {values['missed']:4.1f} %  ({values['cases']} cases); false starts {vad['false_starts']} "
                         f"in {vad['cases']} noise cases ({vad['per_minute']:g}/min)")
    if summary.get("speakers"):
        lines.append("who is speaking (voice_match and its lower bound):")
        for key, values in summary["speakers"].items():
            lines.append(f"  {key:<12} genuine accepted {values['genuine_accepted']:5.1f} %  unclear {values['genuine_unclear']:4.1f} %  "
                         f"dropped {values['genuine_dropped']:4.1f} %  |  impostors accepted {values['impostor_accepted']:4.1f} %  "
                         f"unclear {values['impostor_unclear']:4.1f} %  dropped {values['impostor_dropped']:4.1f} %  |  "
                         f"misidentified {values['misidentified']:4.1f} %  EER {values['eer']:4.1f} % at {values['eer_threshold']:.2f}  "
                         f"({values['trials']} trials, {values['impostor_trials']} impostor scores)")
    return "\n".join(lines)


def load_baseline(path: Path = BASELINE) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save(results: dict, path: Path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=0)
        f.write("\n")


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.WARNING)
    args = list(argv)
    command = args.pop(0) if args and not args[0].startswith("-") else "run"
    limit, engines, silences, out = None, [], [], None
    while args:
        arg = args.pop(0)
        if arg == "--limit" and args:
            limit = int(args.pop(0))
        elif arg == "--engine" and args:
            engines.append(args.pop(0))
        elif arg == "--silence" and args:
            silences.append(float(args.pop(0)))
        elif arg == "--json" and args:
            out = Path(args.pop(0))
        else:
            print(__doc__)
            return 2
    found = manifest()
    from corpus import missing

    lost = missing(found)
    if lost:
        print(f"the corpus isn't in the cache ({len(lost)} cases missing): bin/anyassistant corpus fetch first")
        return 1
    engines = engines or stt.available()
    results = measure(found, engines, limit, tuple(silences) or SILENCES)
    print(report(results["summary"]))
    if command == "baseline":
        if limit:
            print("a baseline needs the whole corpus: no --limit")
            return 2
        save(results, BASELINE)
        print(f"baseline written: {BASELINE}")
        return 0
    if out:
        save(results, out)
    baseline = load_baseline()
    if baseline:
        found_changes = compare(found, baseline, results)
        print("\nagainst the baseline:")
        for line in found_changes["changes"] or ["  nothing moved"]:
            print("  " + line)
        if found_changes["flips"]:
            print("cases that flipped:")
            for line in found_changes["flips"]:
                print("  " + line)
        if found_changes["problems"]:
            print("WORSE than the baseline:")
            for line in found_changes["problems"]:
                print("  " + line)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
