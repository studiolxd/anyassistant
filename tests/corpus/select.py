"""How the manifest (cases.json) was made: a fixed, seeded selection from each dataset, with the
hash of every file. Kept so the selection can be reproduced or grown; it isn't needed to use the
corpus (fetch.py downloads what this wrote).

It needs local copies of the two archives that can't be read in pieces (a plain tar's members
can, by byte range; a tar.gz can't): Common Voice's es_test_0.tar and FLEURS's dev.tar.gz for
es_419 and en_us, with their .tsv files; the rest it reads over HTTP by ranges, as fetch.py does.

    python -m corpus.select --common-voice-tar es_test_0.tar --common-voice-tsv test.tsv \
        --fleurs-es dev.tar.gz --fleurs-es-tsv dev.tsv --fleurs-en dev.tar.gz --fleurs-en-tsv dev.tsv \
        [--out cases.json]
"""

import csv
import hashlib
import io
import json
import random
import sys
import tarfile
import zipfile
from datetime import date
from pathlib import Path

from corpus import RATE, decode, normalise

SEED = 7
SPEAKERS = 60  # Common Voice speakers, 4 clips each (the most its test split has per speaker)
FLEURS_ES, FLEURS_EN, MLS = 40, 25, 20
LONGEST = 12.0  # seconds: the ear cuts a sentence at 15
SHORTEST = 1.5
NOISE_SECONDS = 6.0
MIXED_CV, MIXED_FLEURS_ES, MIXED_FLEURS_EN = 24, 8, 4
SNRS = (20, 10, 5)
ROOM_CV, ROOM_FLEURS_ES, ROOM_FLEURS_EN = 10, 6, 4

SOURCES = {
    "common_voice": {
        "title": "Mozilla Common Voice 17.0, Spanish, test split",
        "license": "CC0 1.0", "homepage": "https://commonvoice.mozilla.org/",
        "kind": "hf-tar", "repo": "fsicoli/common_voice_17_0", "revision": "8262c16bf297c87a9cd88c51997c4758ed7a8ba2",
        "archive": "audio/es/test/es_test_0.tar",
        "note": "a mirror on Hugging Face of the official release (CC0 allows it). The official download now "
                "needs an account at Mozilla Data Collective: fetch --common-voice FOLDER uses one instead.",
    },
    "fleurs": {
        "title": "FLEURS (Google), es_419 and en_us, dev split",
        "license": "CC BY 4.0", "homepage": "https://huggingface.co/datasets/google/fleurs",
        "kind": "hf-targz", "repo": "google/fleurs", "revision": "70bb2e84b976b7e960aa89f1c648e09c59f894dd",
        "archives": {"es": "data/es_419/audio/dev.tar.gz", "en": "data/en_us/audio/dev.tar.gz"},
    },
    "mls": {
        "title": "Multilingual LibriSpeech (Meta), Spanish, test split",
        "license": "CC BY 4.0", "homepage": "https://www.openslr.org/94/",
        "kind": "hf-parquet", "repo": "facebook/multilingual_librispeech",
        "revision": "2e83e61823b4c47dcbcb1980bb88601274127609", "archive": "spanish/test-00000-of-00001.parquet",
    },
    "musan": {
        "title": "MUSAN, noise portion",
        "license": "CC BY 4.0", "homepage": "https://www.openslr.org/17/",
        "kind": "hf-parquet", "repo": "corypaik/musan", "revision": "76f9882cfa4475efe11508ac9aa32722f84ca5b7",
        "archive": "noise/train-00000-of-00002.parquet",
        "note": "a mirror on Hugging Face in Parquet (the original is one 11 GB tar.gz).",
    },
    "demand": {
        "title": "DEMAND (Diverse Environments Multichannel Acoustic Noise Database), 16 kHz, channel 1",
        "license": "CC BY 4.0 (as Zenodo states; the authors' page says CC BY-SA)", "homepage": "https://zenodo.org/records/1227121",
        "kind": "zip", "url": "https://zenodo.org/records/1227121/files/{archive}",
    },
    "rirs": {
        "title": "Room impulse responses: OpenSLR SLR28 (RIRS_NOISES: simulated, and real ones from AIR and RWCP)",
        "license": "Apache 2.0", "homepage": "https://www.openslr.org/28/",
        "kind": "zip", "url": "https://www.openslr.org/resources/28/{archive}", "archive": "rirs_noises.zip",
    },
}

DEMAND_ROOMS = {"kitchen": "DKITCHEN", "living": "DLIVING", "meeting": "OMEETING"}
DEMAND_STARTS = (30.0, 120.0, 210.0)
RIRS = {
    "small": "RIRS_NOISES/simulated_rirs/smallroom/Room001/Room001-00001.wav",
    "medium": "RIRS_NOISES/simulated_rirs/mediumroom/Room001/Room001-00001.wav",
    "large": "RIRS_NOISES/simulated_rirs/largeroom/Room001/Room001-00001.wav",
    "office": "RIRS_NOISES/real_rirs_isotropic_noises/air_type1_air_binaural_office_0_1.wav",
    "lecture": "RIRS_NOISES/real_rirs_isotropic_noises/air_type1_air_binaural_lecture_0_1.wav",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def seconds(data: bytes, name: str) -> float:
    return round(len(decode(data, name)) / RATE, 2)


def log(message: str):
    print(message, file=sys.stderr, flush=True)


def common_voice(tar_path: Path, tsv_path: Path, rng: random.Random) -> list[dict]:
    rows = list(csv.DictReader(open(tsv_path, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE))
    by_speaker: dict = {}
    for row in rows:
        by_speaker.setdefault(row["client_id"], []).append(row)
    candidates = sorted(s for s, clips in by_speaker.items() if len(clips) == 4)
    rng.shuffle(candidates)
    members = {}
    with tarfile.open(tar_path) as tar:
        for member in tar:
            if member.isfile():
                members[Path(member.name).name] = (member.offset_data, member.size)
        cases = []
        taken = 0
        for speaker in candidates:
            if taken >= SPEAKERS:
                break
            clips = sorted(by_speaker[speaker], key=lambda r: r["path"])
            found = []
            for row in clips:
                if row["path"] not in members:
                    break
                offset, size = members[row["path"]]
                tar.fileobj.seek(offset)
                data = tar.fileobj.read(size)
                length = seconds(data, row["path"])
                if not SHORTEST <= length <= LONGEST or not normalise(row["sentence"]):
                    break
                found.append({"row": row, "offset": offset, "size": size, "sha256": sha256(data), "seconds": length})
            if len(found) < 4:
                continue
            taken += 1
            for n, clip in enumerate(found, 1):
                row = clip["row"]
                cases.append({
                    "id": f"cv-es-{taken:02d}-{n}", "kind": "speech", "source": "common_voice", "lang": "es",
                    "file": row["path"], "offset": clip["offset"], "size": clip["size"], "sha256": clip["sha256"],
                    "seconds": clip["seconds"], "speaker": f"cv-{taken:02d}", "speaker_id": row["client_id"][:16],
                    "text": normalise(row["sentence"]),
                    **({"gender": row["gender"]} if row.get("gender") else {}),
                    **({"accent": row["accents"].split(":")[0]} if row.get("accents") else {}),
                })
            log(f"common voice: speaker {taken}/{SPEAKERS}")
    return cases


def fleurs(tar_path: Path, tsv_path: Path, lang: str, wanted: int, archive: str) -> list[dict]:
    texts = {}
    for line in open(tsv_path, encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 4:
            texts[parts[1]] = parts[3]  # the file and its normalised transcription
    cases = []
    with tarfile.open(tar_path, "r:gz") as tar:
        for member in tar:
            if len(cases) >= wanted:
                break
            name = Path(member.name).name
            if not member.isfile() or name not in texts or not normalise(texts[name]):
                continue
            data = tar.extractfile(member).read()
            length = seconds(data, name)
            if not SHORTEST <= length <= LONGEST:
                continue
            cases.append({
                "id": f"fl-{lang}-{len(cases) + 1:02d}", "kind": "speech", "source": "fleurs", "lang": lang,
                "archive": archive, "file": name, "sha256": sha256(data), "seconds": length,
                "text": normalise(texts[name]),
            })
    log(f"fleurs {lang}: {len(cases)}")
    return cases


def mls(rng: random.Random) -> list[dict]:
    import pyarrow.parquet as pq

    from corpus.fetch import buffered, source_url

    file = pq.ParquetFile(buffered(source_url(SOURCES["mls"])))
    cases = []
    for group in range(min(2, file.metadata.num_row_groups)):
        table = file.read_row_group(group, columns=["audio", "transcript", "audio_duration", "speaker_id", "id"])
        rows = table.to_pylist()
        short = [n for n, r in enumerate(rows) if r["audio_duration"] <= LONGEST and normalise(r["transcript"])]
        rng.shuffle(short)
        per_speaker: dict = {}
        for n in sorted(short[:MLS]):
            r = rows[n]
            per_speaker[r["speaker_id"]] = per_speaker.get(r["speaker_id"], 0) + 1
            cases.append({
                "id": f"mls-es-{len(cases) + 1:02d}", "kind": "speech", "source": "mls", "lang": "es",
                "file": Path(r["audio"]["path"] or r["id"]).name, "row_group": group, "row": n,
                "sha256": sha256(r["audio"]["bytes"]), "seconds": round(r["audio_duration"], 2),
                "speaker": f"mls-{r['speaker_id']}", "text": normalise(r["transcript"]),
            })
            if len(cases) >= MLS:
                break
        if len(cases) >= MLS:
            break
    log(f"mls: {len(cases)}")
    return cases


def musan(rng: random.Random, wanted: int = 10) -> list[dict]:
    import pyarrow.parquet as pq

    from corpus.fetch import buffered, source_url

    file = pq.ParquetFile(buffered(source_url(SOURCES["musan"])))
    table = file.read_row_group(0, columns=["audio", "path", "source"])
    rows = table.to_pylist()
    order = list(range(len(rows)))
    rng.shuffle(order)
    cases = []
    for n in order:
        r = rows[n]
        audio = decode(r["audio"]["bytes"], r["path"])
        length = len(audio) / RATE
        if length < NOISE_SECONDS * 2:
            continue
        start = round(rng.uniform(0, length - NOISE_SECONDS), 1)
        cases.append({
            "id": f"noise-musan-{len(cases) + 1:02d}", "kind": "noise", "source": "musan",
            "file": Path(r["path"]).name, "row_group": 0, "row": n, "sha256": sha256(r["audio"]["bytes"]),
            "start": start, "seconds": NOISE_SECONDS, "origin": r.get("source") or "",
        })
        if len(cases) >= wanted:
            break
    log(f"musan: {len(cases)}")
    return cases


def demand() -> list[dict]:
    from corpus.fetch import buffered, source_url

    cases = []
    for room, code in DEMAND_ROOMS.items():
        archive = f"{code}_16k.zip"
        with zipfile.ZipFile(buffered(source_url(SOURCES["demand"], archive))) as z:
            member = f"{code}/ch01.wav"
            data = z.read(member)
        digest = sha256(data)
        for n, start in enumerate(DEMAND_STARTS, 1):
            cases.append({"id": f"noise-{room}-{n}", "kind": "noise", "source": "demand", "archive": archive,
                          "member": member, "file": f"{code}-ch01.wav", "sha256": digest, "start": start,
                          "seconds": NOISE_SECONDS})
        cases.append({"id": f"noise-{room}-long", "kind": "noise", "source": "demand", "archive": archive,
                      "member": member, "file": f"{code}-ch01.wav", "sha256": digest, "start": 240.0, "seconds": 20.0})
        log(f"demand: {room}")
    return cases


def rirs() -> list[dict]:
    from corpus.fetch import buffered, source_url

    cases = []
    with zipfile.ZipFile(buffered(source_url(SOURCES["rirs"]))) as z:
        for room, member in RIRS.items():
            data = z.read(member)
            cases.append({"id": f"rir-{room}", "kind": "rir", "source": "rirs", "member": member,
                          "file": Path(member).name, "sha256": sha256(data)})
    log(f"rirs: {len(cases)}")
    return cases


def mixed(speech: list[dict], noises: list[dict], rng: random.Random) -> list[dict]:
    """Each chosen speech clip over every SNR, with a noise picked in turn (the same noise for all
    of a clip's SNRs, so they compare)."""
    cases = []
    for n, clip in enumerate(speech):
        noise = noises[n % len(noises)]
        for snr in SNRS:
            cases.append({"id": f"mix-{clip['id']}-{noise['id'].removeprefix('noise-')}-{snr}db", "kind": "mixed",
                          "lang": clip["lang"], "speech": clip["id"], "noise": noise["id"], "snr": snr,
                          "text": clip["text"], **({"speaker": clip["speaker"]} if "speaker" in clip else {})})
    return cases


def rooms(speech: list[dict], impulses: list[dict]) -> list[dict]:
    cases = []
    for n, clip in enumerate(speech):
        rir = impulses[n % len(impulses)]
        cases.append({"id": f"room-{clip['id']}-{rir['id'].removeprefix('rir-')}", "kind": "room", "lang": clip["lang"],
                      "speech": clip["id"], "rir": rir["id"], "text": clip["text"],
                      **({"speaker": clip["speaker"]} if "speaker" in clip else {})})
    return cases


def select(args: dict) -> dict:
    rng = random.Random(SEED)
    cv = common_voice(args["common_voice_tar"], args["common_voice_tsv"], rng)
    fl_es = fleurs(args["fleurs_es"], args["fleurs_es_tsv"], "es", FLEURS_ES, SOURCES["fleurs"]["archives"]["es"])
    fl_en = fleurs(args["fleurs_en"], args["fleurs_en_tsv"], "en", FLEURS_EN, SOURCES["fleurs"]["archives"]["en"])
    long = mls(rng)
    noises = musan(rng) + demand()
    impulses = rirs()
    # The clips mixed with noise and rooms: one per Common Voice speaker (their second clip), the
    # first FLEURS sentences; noises in turn, so every room and SNR is heard with several voices.
    second = [c for c in cv if c["id"].endswith("-2")]
    short_noises = [n for n in noises if n["seconds"] == NOISE_SECONDS or n["source"] == "demand"]
    for_mix = second[:MIXED_CV] + fl_es[:MIXED_FLEURS_ES] + fl_en[:MIXED_FLEURS_EN]
    for_rooms = second[MIXED_CV:MIXED_CV + ROOM_CV] + fl_es[MIXED_FLEURS_ES:MIXED_FLEURS_ES + ROOM_FLEURS_ES] \
        + fl_en[MIXED_FLEURS_EN:MIXED_FLEURS_EN + ROOM_FLEURS_EN]
    cases = cv + fl_es + fl_en + long + noises + impulses + mixed(for_mix, short_noises, rng) + rooms(for_rooms, impulses)
    return {
        "format": 1, "made": date.today().isoformat(), "seed": SEED,
        "normalisation": "lowercase, no punctuation, no accents (ñ kept), words separated by one space (corpus.normalise)",
        "sources": SOURCES, "cases": cases,
    }


def main(argv: list[str]) -> int:
    args = {"out": Path(__file__).with_name("cases.json")}
    keys = {"--common-voice-tar": "common_voice_tar", "--common-voice-tsv": "common_voice_tsv", "--fleurs-es": "fleurs_es",
            "--fleurs-es-tsv": "fleurs_es_tsv", "--fleurs-en": "fleurs_en", "--fleurs-en-tsv": "fleurs_en_tsv", "--out": "out"}
    rest = list(argv)
    while rest:
        flag = rest.pop(0)
        if flag in keys and rest:
            args[keys[flag]] = Path(rest.pop(0))
        else:
            print(__doc__)
            return 2
    if any(k not in args for k in keys.values()):
        print(__doc__)
        return 2
    found = select(args)
    with open(args["out"], "w", encoding="utf-8") as f:
        json.dump(found, f, ensure_ascii=False, indent=1)
        f.write("\n")
    kinds: dict = {}
    for c in found["cases"]:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    print(f"{len(found['cases'])} cases: {kinds} → {args['out']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
