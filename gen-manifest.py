#!/usr/bin/env python3
"""
Generate an audio manifest (JSON) from a directory of per-word MP3 files.

The manifest lists every available recording by its normalized Sango stem
(e.g. `bara_ala`, `singila`) so a consuming application can preload the
available set without probing for each file individually.

Usage:
    python gen-manifest.py [--audio-dir out/audio] [--out audio-manifest.json] [--url-prefix /audio/vocab]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audio-dir", default="out/audio", type=Path,
                    help="Directory containing {word}.mp3 files")
    ap.add_argument("--out", default="audio-manifest.json", type=Path,
                    help="Manifest path to write")
    ap.add_argument("--url-prefix", default="/audio/vocab",
                    help="URL prefix the files will be served under")
    args = ap.parse_args()

    if not args.audio_dir.exists():
        # Don't hard-exit — write an empty manifest so automation doesn't
        # fail before any recordings have been added.
        print(f"WARNING: {args.audio_dir} does not exist — writing empty manifest")
        words: list[str] = []
    else:
        words = sorted(p.stem for p in args.audio_dir.glob("*.mp3"))
        if not words:
            print(f"WARNING: no .mp3 files found under {args.audio_dir} — writing empty manifest")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "version": 2,
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "count": len(words),
                # "words" — normalized Sango text stems (e.g. "bara_ala")
                # Each stem corresponds to:  {url_prefix}/{stem}.mp3
                "words": words,
                "cdn_path": args.url_prefix,
            },
            fh,
            indent=2,
            ensure_ascii=False,
        )

    print(f"[OK] wrote {args.out}")
    print(f"     version=2, count={len(words)}")
    if words:
        print(f"     first 5: {words[:5]}")
        print(f"     URLs served as: {args.url_prefix}/{{word}}.mp3")
    else:
        print("     (empty — no recordings yet)")
        print(f"     Add MP3 files to {args.audio_dir}/ then rerun to populate")


if __name__ == "__main__":
    main()
