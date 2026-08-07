#!/usr/bin/env python3
"""
Convert individual per-word .m4a recordings to normalized .mp3 files.

USE THIS SCRIPT when you have SEPARATE audio files per word (e.g. WhatsApp
voice messages sent one-by-one).  For a single long recording, use splitter.py
instead.

Workflow:
  1. Sort .m4a files alphabetically — they must be in the same order as the
     CSV rows you want to map.  WhatsApp names files WA0028, WA0029 … so
     alphabetical order = recording order.
  2. Each file is mapped to one row in the CSV (starting from --start-row).
  3. ffmpeg converts each .m4a → .mp3 mono 96 kbps, loudness-normalised to
     -16 LUFS (EBU R128), matching the output format of splitter.py.
  4. Output filename = normalize_sango(csv_row["sango"]) + ".mp3"
     This MUST match the normalization used by the consuming application.

Usage:
  # Dry run — show mapping without converting
  python convert-individual-recordings.py <recordings_dir> top-50.csv \
      out/audio --dry-run

  # Convert rows 1–12 (the first 12 rows of the CSV)
  python convert-individual-recordings.py \
      "raw-recordings" top-50.csv \
      out/audio

  # Start from a different row (e.g. if recording started at word #13)
  python convert-individual-recordings.py <dir> top-50.csv <out> --start-row 13

Requires: ffmpeg on PATH.  Test with:  ffmpeg -version
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

# Windows console may default to cp1252 — force UTF-8 for Sango diacritics
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Normalization — MUST match audioService.ts::normalizeWord() exactly
# ---------------------------------------------------------------------------

def normalize_sango(text: str) -> str:
    """
    Convert a Sango word/phrase to a safe filename stem.
    Must match audioService.ts::normalizeWord() and splitter.py::normalize_sango().

    Examples:
        "bara âla"               → "bara_ala"
        "Singila"                → "singila"
        "balaó"                  → "balao"
        "Tongana nye?"           → "tongana_nye"
        "Mbi yeke séngé"         → "mbi_yeke_senge"
        "Mbi gbû gèrè ti âla"   → "mbi_gbu_gere_ti_ala"
        "parâ"                   → "para"
        "ôko"                    → "oko"
    """
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^\w\s-]", "", text)
    text = text.strip()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+$", "", text)
    return text


# ---------------------------------------------------------------------------
# ffmpeg conversion
# ---------------------------------------------------------------------------

def convert_file(input_path: Path, output_path: Path) -> bool:
    """
    Convert one audio file to mono 96 kbps MP3 with -16 LUFS loudness normalisation.
    Returns True on success, False on failure.
    """
    cmd = [
        "ffmpeg",
        "-y",              # Overwrite output if it already exists
        "-i", str(input_path),
        "-ac", "1",        # Mono
        "-b:a", "96k",     # 96 kbps
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",  # EBU R128 loudness norm
        str(output_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"  ✗  ffmpeg error:\n{result.stderr[-600:]}", file=sys.stderr)
            return False
        return True
    except FileNotFoundError:
        print(
            "✗  ffmpeg not found on PATH.\n"
            "   Install: https://ffmpeg.org/download.html\n"
            "   Windows (Chocolatey): choco install ffmpeg\n"
            "   Windows (Scoop):      scoop install ffmpeg",
            file=sys.stderr,
        )
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print(f"  ✗  ffmpeg timed out for {input_path.name}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert individual per-word .m4a recordings to named .mp3 files.",
    )
    parser.add_argument(
        "recordings_dir",
        help="Directory containing .m4a files (sorted alphabetically = recording order)",
    )
    parser.add_argument(
        "csv_file",
        help="Path to top-50.csv (columns: order,bucket,sango,french,english)",
    )
    parser.add_argument(
        "output_dir",
        help="Output directory for the converted MP3s",
    )
    parser.add_argument(
        "--start-row", type=int, default=1, metavar="N",
        help="First CSV row to map to (1-indexed, default: 1)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the mapping table without converting anything",
    )
    parser.add_argument(
        "--extensions", default="m4a,wav,mp3,ogg,aac",
        help="Comma-separated audio extensions to scan (default: m4a,wav,mp3,ogg,aac)",
    )

    args = parser.parse_args()

    recordings_dir = Path(args.recordings_dir)
    csv_file = Path(args.csv_file)
    output_dir = Path(args.output_dir)
    start_row = args.start_row - 1  # Convert to 0-indexed

    # --- Validate inputs ---------------------------------------------------
    if not recordings_dir.is_dir():
        print(f"✗  Recordings directory not found: {recordings_dir}", file=sys.stderr)
        return 1

    if not csv_file.is_file():
        print(f"✗  CSV file not found: {csv_file}", file=sys.stderr)
        return 1

    # --- Find audio files --------------------------------------------------
    extensions = {ext.strip().lstrip(".").lower() for ext in args.extensions.split(",")}
    audio_files: list[Path] = sorted(
        f for f in recordings_dir.iterdir()
        if f.suffix.lstrip(".").lower() in extensions
    )

    if not audio_files:
        print(
            f"✗  No audio files ({args.extensions}) found in {recordings_dir}",
            file=sys.stderr,
        )
        return 1

    # --- Read CSV rows -----------------------------------------------------
    with open(csv_file, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    available_rows = rows[start_row:]

    if len(audio_files) > len(available_rows):
        print(
            f"✗  More audio files ({len(audio_files)}) than CSV rows "
            f"available starting from row {args.start_row} "
            f"({len(available_rows)} rows left).",
            file=sys.stderr,
        )
        return 1

    # --- Build mapping table -----------------------------------------------
    pairs = list(zip(audio_files, available_rows))

    sep = "-" * 72
    print(f"\n{sep}")
    print("  RECORDING -> CSV MAPPING")
    print(sep)
    print(f"  {'File':<28}  {'Sango word':<22}  Output filename")
    print(sep)
    for audio_path, row in pairs:
        sango = row["sango"]
        stem = normalize_sango(sango)
        print(f"  {audio_path.name:<28}  {sango:<22}  {stem}.mp3")
    print(sep)
    print(f"\n  {len(pairs)} file(s) -> {output_dir}")

    if args.dry_run:
        print("\n  [DRY RUN] No files were converted.")
        print("  Remove --dry-run to proceed.\n")
        return 0

    # --- Confirm before converting -----------------------------------------
    print()
    confirm = input("  Proceed with conversion? [y/N] ").strip().lower()
    if confirm not in ("y", "yes"):
        print("  Aborted.")
        return 0

    # --- Convert -----------------------------------------------------------
    output_dir.mkdir(parents=True, exist_ok=True)
    success = 0
    failed = 0

    print()
    for audio_path, row in pairs:
        sango = row["sango"]
        stem = normalize_sango(sango)
        out_path = output_dir / f"{stem}.mp3"

        print(f"  --> {audio_path.name}  ->  {out_path.name} ", end="", flush=True)
        ok = convert_file(audio_path, out_path)
        if ok:
            size_kb = out_path.stat().st_size // 1024
            print(f"✓  ({size_kb} KB)")
            success += 1
        else:
            print("✗  FAILED")
            failed += 1

    # --- Summary -----------------------------------------------------------
    print(f"\n  Converted: {success}/{len(pairs)}", end="")
    if failed:
        print(f"  |  Failed: {failed}", end="")
    print()

    if success > 0:
        print()
        print("  Next steps:")
        print("  1. Spot-check a few files (play them).")
        print("  2. Regenerate the audio manifest:")
        print("       cd <repo_root> && python scripts/audio/gen-manifest.py")
        print("  3. Start the dev server to test:")
        print()

    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
