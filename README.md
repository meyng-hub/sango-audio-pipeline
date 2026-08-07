# sango-audio-pipeline

Field toolchain for building a native-speaker pronunciation corpus for
**Sango** (ISO 639-3: `sag`) — the national language of the Central African
Republic — from nothing more than a phone, a quiet room, and `ffmpeg`.

This is the pipeline behind the audio work for
[`MEYNG/sango-vocabulary`](https://huggingface.co/datasets/MEYNG/sango-vocabulary)
(open trilingual Sango–French–English vocabulary, CC-BY-SA-4.0). It is
deliberately low-tech: no studio, no proprietary tools, no cloud dependency —
so that it can be replicated for any language in a similar zero-resource
situation (Gbaya, Banda, Yakoma, other creoles and lingua francas).

## Pipeline

```
word-list selection          gen-top-50-from-jsonl.py   vocabulary JSONL → recording queue CSV
        │
phone recording session      one continuous take, ~2 s silence between words
        │
split + normalize            splitter.py                ffmpeg silencedetect → one MP3 per word,
        │                                               96 kbps mono, −16 LUFS (EBU R128)
per-file conversion          convert-individual-recordings.py   for retakes / individual files
        │
validation                   validate-recordings.sh/.ps1        duration, clipping, voice presence
        │
manifest                     gen-manifest.py            audio-manifest.json for consuming apps
```

## Requirements

- Python 3.11+ (standard library only)
- [`ffmpeg`](https://ffmpeg.org) on `PATH` — check with `ffmpeg -version`

## Quickstart

```bash
# 1. Build the recording queue from the open dataset
#    (download vocabulary.jsonl from the MEYNG/sango-vocabulary dataset)
python gen-top-50-from-jsonl.py            # → top-50.csv (a ready-made copy is included)

# 2. Record: say each word in queue order, once, naturally,
#    with ~2 seconds of silence between words. One continuous take.
#    Phone voice-recorder quality (M4A) is sufficient.

# 3. Split the session into per-word MP3s (normalized to −16 LUFS)
python splitter.py recording-2026-04-20.m4a top-50.csv out/audio

# 4. Validate every clip (duration, clipping, voice presence)
./validate-recordings.sh out/audio         # or validate-recordings.ps1 on Windows

# 5. Generate the manifest
python gen-manifest.py --audio-dir out/audio
```

## Recording protocol (what actually works in the field)

- Quiet room, phone on airplane mode, no AC/fan.
- One continuous recording for the whole queue — don't stop between words.
- Misspoke? Just say the word again: the splitter keeps the **last** take
  before each 2-second silence gap.
- ~15 s per word including gaps → a 50-word session is ≈ 20–30 minutes.
- Before splitting: file plays, total duration is plausible, background
  noise is low, first seconds are silence/preamble (the splitter trims).

## Quality thresholds

Every published clip must pass:

| Check | Threshold |
|---|---|
| Duration | 0.5 – 5.0 s |
| Peak level | ≤ −1 dBTP (no clipping) |
| Voice presence | RMS ≥ −50 dB |
| Loudness | −16 LUFS integrated (EBU R128), applied at encode |
| Human review | pronunciation confirmed against the reference word |

## Consent comes first — publication is default-deny

No recording produced with this pipeline is published without a **signed
informed consent** from the speaker covering that exact set of recordings:
scope of use, permanent public release under an open licence, right of
withdrawal before publication, and anonymized speaker identification.
Speakers are paid for their time, not contingent on validation outcomes.

In our own use, this is enforced mechanically, not by memory: a CI gate
fails any change that would publish an audio file lacking a committed proof
of live consent. If you replicate this pipeline, replicate that property —
*"not exposed in the UI" is not the same as "not published."*

## Word list

`top-50.csv` (greetings, numbers, pronouns, question words, core verbs,
daily nouns) is derived from the
[`MEYNG/sango-vocabulary`](https://huggingface.co/datasets/MEYNG/sango-vocabulary)
dataset and is licensed **CC-BY-SA-4.0** like its source.

## Licence

- Code: **MIT** (see `LICENSE`)
- `top-50.csv` and any data derived from the vocabulary dataset: **CC-BY-SA-4.0**

## About

Built by [MEYNG](https://www.meyng.com) for [SangoAI](https://sangoai.sbs),
with the HCW association (Bangui, Central African Republic). Contact:
contact@meyng.com
