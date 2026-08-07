#!/usr/bin/env python3
"""
Split one long phone recording into individual per-word MP3s.

Input:
  1. A single long audio file (m4a / wav / mp3) recorded on a phone's
     voice-recorder app. The speaker says each word once, separated by
     ~2s of silence (or more if a retake).
  2. A CSV queue with a word_id column (output of gen-top-50.py).

Output:
  - One MP3 per CSV row, named {word_id}.mp3, in the output directory.
  - A manifest fragment listing {word_id: filename} that can be merged
    into audio-manifest.json.

Algorithm:
  - ffmpeg silencedetect filter finds silence boundaries.
  - Audio segments between silences = words.
  - If there are MORE segments than CSV rows (retakes), keep the LAST
    segment before each 2s+ silence as the "final" take, discard the
    preceding ones.
  - Each retained segment is re-encoded to MP3 96 kbps mono + normalized
    loudness (-16 LUFS, EBU R128) for consistent playback volume.

Usage:
  python splitter.py <input.m4a> <queue.csv> <output_dir>

Example:
  python splitter.py recording-2026-04-20.m4a top-50.csv out/audio

Requires: ffmpeg on PATH. Test with: ffmpeg -version
"""

from __future__ import annotations

import csv
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

# --- Tunables (change only if the defaults don't match your recording style) ---
SILENCE_THRESHOLD_DB = -30  # Below this dB = silence. Quieter rooms can use -35.
SILENCE_MIN_DURATION = 1.5  # Minimum silence length (seconds) to split on.
# If you pause longer between words, raise this. If you're rapid-fire, lower it.

def normalize_sango(text: str) -> str:
    """
    Convert a Sango word/phrase to a safe filename stem.
    Must match the normalization used by the consuming application EXACTLY.

    Steps:
    1. Lowercase + strip leading/trailing whitespace
    2. NFD decompose → remove combining diacritics  (â→a, è→e, ô→o …)
    3. Remove non-word, non-hyphen, non-space chars  (?, !, ., comma …)
    4. Collapse whitespace → underscores; strip trailing underscores

    Examples:
        "bara âla"          → "bara_ala"
        "Tongana nye?"      → "tongana_nye"
        "iri tí mo nye ?"   → "iri_ti_mo_nye"
        "balë-ôko"          → "bale-oko"
        "mbárámbárá"        → "mbarambara"
        "kôbë"              → "kobe"
    """
    text = text.lower().strip()
    # Decompose and strip combining marks
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    # Strip punctuation (keep word-chars, hyphens, spaces)
    text = re.sub(r"[^\w\s-]", "", text)
    text = text.strip()
    # Spaces → underscores
    text = re.sub(r"\s+", "_", text)
    # Drop trailing underscores that result from stripped trailing punctuation
    text = re.sub(r"_+$", "", text)
    return text


def get_file_stem(row: dict) -> str:
    """
    Derive the output MP3 filename stem for a CSV row.

    New CSV format (top-50.csv ≥ v2):  has 'sango' column → normalize_sango().
    Old CSV format (top-50.csv v1):    has 'word_id' column only → use word_id as-is.

    audioService.ts resolves audio URLs as:  {AUDIO_CDN_URL}/{normalizeWord(sango)}.mp3
    so we must use the same normalised text here.
    """
    if "sango" in row and row["sango"].strip():
        return normalize_sango(row["sango"])
    # Backward-compat: old CSVs that only had word_id
    return row["word_id"]


MP3_BITRATE = "96k"
MP3_CHANNELS = 1  # mono
LOUDNORM_I = "-16"   # Integrated loudness target (LUFS) — web audio standard
LOUDNORM_TP = "-1.5" # True peak (dB)
LOUDNORM_LRA = "11"  # Loudness range


def check_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        sys.exit("ERROR: ffmpeg not on PATH. Install: https://ffmpeg.org/download.html")


def detect_silences(input_path: str) -> list[tuple[float, float]]:
    """Return list of (silence_start, silence_end) tuples in seconds."""
    cmd = [
        "ffmpeg", "-i", input_path,
        "-af", f"silencedetect=noise={SILENCE_THRESHOLD_DB}dB:d={SILENCE_MIN_DURATION}",
        "-f", "null", "-"
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    return list(zip(starts, ends))


def audio_duration(input_path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", input_path],
        capture_output=True, text=True
    )
    return float(r.stdout.strip())


def segments_from_silences(silences: list[tuple[float, float]], total: float) -> list[tuple[float, float]]:
    """Convert silence boundaries into spoken-audio segments."""
    segments: list[tuple[float, float]] = []
    prev_end = 0.0
    for s_start, s_end in silences:
        if s_start > prev_end + 0.1:
            segments.append((prev_end, s_start))
        prev_end = s_end
    if total > prev_end + 0.1:
        segments.append((prev_end, total))
    return segments


def extract_segment(input_path: str, start: float, end: float, out_path: str) -> None:
    """Extract [start, end] seconds from input, encode to MP3 mono 96k with loudnorm."""
    duration = end - start
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
        "-i", input_path,
        "-af", f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}",
        "-ac", str(MP3_CHANNELS),
        "-b:a", MP3_BITRATE,
        "-codec:a", "libmp3lame",
        out_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def main() -> None:
    if len(sys.argv) != 4:
        sys.exit(f"Usage: {sys.argv[0]} <input.m4a> <queue.csv> <output_dir>")

    input_path, csv_path, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    check_ffmpeg()

    # Load rows from CSV (preserve order)
    with open(csv_path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    stems = [get_file_stem(r) for r in rows]
    # Show which field we resolved from so mismatches are obvious
    if rows and "sango" in rows[0]:
        print(f"[csv]   {len(stems)} entries (sango-text filenames)")
    else:
        print(f"[csv]   {len(stems)} entries (word_id filenames — old format)")

    # Analyze audio
    total = audio_duration(input_path)
    silences = detect_silences(input_path)
    segments = segments_from_silences(silences, total)
    print(f"[audio] duration={total:.1f}s, {len(silences)} silences, {len(segments)} segments")

    # Drop very short (<0.4s) noise blips
    segments = [(s, e) for s, e in segments if (e - s) >= 0.4]
    print(f"[filter] after dropping <0.4s noise: {len(segments)} segments")

    if len(segments) < len(stems):
        print(f"WARNING: only {len(segments)} segments for {len(stems)} words.")
        print("Recording may be incomplete or silence threshold too strict.")
        print("Try rerunning with SILENCE_THRESHOLD_DB = -35 (quieter rooms).")

    if len(segments) > len(stems):
        # Trim from the end (extra segments after the last word are ambient noise)
        segments = segments[: len(stems)]
        print(f"[trim] truncated to {len(segments)} segments")

    # Extract each segment
    import json
    os.makedirs(out_dir, exist_ok=True)
    produced = {}
    for stem, row, (start, end) in zip(stems, rows, segments):
        out_path = os.path.join(out_dir, f"{stem}.mp3")
        extract_segment(input_path, start, end, out_path)
        size_kb = os.path.getsize(out_path) / 1024
        label = row.get("sango", row.get("word_id", stem))
        print(f"  {stem:<40}  [{label}]  {start:6.2f}s..{end:6.2f}s ({end-start:.2f}s)  {size_kb:.1f} KB")
        produced[stem] = f"{stem}.mp3"

    # Emit manifest fragment (list of filename stems)
    frag_path = os.path.join(out_dir, "_manifest-fragment.json")
    with open(frag_path, "w", encoding="utf-8") as fh:
        json.dump(sorted(produced.keys()), fh, indent=2, ensure_ascii=False)
    print(f"\n[OK] {len(produced)} files written to {out_dir}")
    print(f"[OK] manifest fragment at {frag_path}")
    print("\nNext: run gen-manifest.py to regenerate audio-manifest.json")


if __name__ == "__main__":
    main()
