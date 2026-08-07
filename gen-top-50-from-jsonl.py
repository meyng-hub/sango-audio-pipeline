#!/usr/bin/env python3
"""
Generate top-50.csv (the recording queue) from the vocabulary JSONL.

Local, offline: reads vocabulary.jsonl — the data file of the open
MEYNG/sango-vocabulary dataset (HuggingFace, CC-BY-SA-4.0).

The JSONL is the ground truth — deduplicated, mojibake-clean, always in sync
with the HuggingFace dataset.

Usage:
    python gen-top-50-from-jsonl.py

Output:
    top-50.csv  (overwrites existing file)

Selection criteria:
    1. Greetings (all entries in category=greetings), up to 15
    2. Numbers 0-10 (matched by French text: zéro, un, deux, …, dix)
       — prefer difficulty=intermediate or beginner over advanced (dialect variants)
    3. Pronouns / essentials (category=essential): lo, ala, mo, Ein, Awe
    4. Questions  (category=questions): Okè, ndo
    5. Common verbs (category=verbs|actions): manger, boire, dormir, parler,
       voir, aller, venir, faire, savoir, donner, être
    6. Daily nouns (food, family, home, commerce, essential):
       eau, nourriture, maison, famille, enfant, homme, femme, argent

Total: capped at 50, duplicates removed by normalized sango text.
"""
from __future__ import annotations

import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

JSONL_PATH = Path("vocabulary.jsonl")
OUT_CSV    = Path("top-50.csv")
MAX        = 50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_sango(text: str) -> str:
    """
    Convert a Sango word/phrase to its audio filename stem.
    MUST stay in sync with:
      - scripts/audio/splitter.py::normalize_sango()
      - the consuming application's word normalization
    """
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^\w\s-]", "", text)
    text = text.strip()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+$", "", text)
    return text


def load_jsonl(path: Path) -> list[dict]:
    entries = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def pick_one_by_french(entries: list[dict], french_exact: str, difficulty_pref: list[str]) -> dict | None:
    """Return the best match for a French target, preferring lower-difficulty entries."""
    candidates = [e for e in entries if e.get("french", "").lower().strip() == french_exact.lower()]
    if not candidates:
        return None
    for diff in difficulty_pref:
        for c in candidates:
            if c.get("difficulty", "").lower() == diff:
                return c
    return candidates[0]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not JSONL_PATH.exists():
        sys.exit(f"ERROR: {JSONL_PATH} not found. Run from repo root.")

    entries = load_jsonl(JSONL_PATH)
    print(f"[jsonl] loaded {len(entries)} entries from {JSONL_PATH}")

    # Index by category for fast lookup
    by_cat: dict[str, list[dict]] = {}
    for e in entries:
        cat = e.get("category", "").lower()
        by_cat.setdefault(cat, []).append(e)

    queue: list[dict] = []
    seen_stems: set[str] = set()

    def add(entry: dict, bucket: str) -> bool:
        if len(queue) >= MAX:
            return False
        stem = normalize_sango(entry.get("sango", ""))
        if not stem or stem in seen_stems:
            return False
        seen_stems.add(stem)
        queue.append({
            "order": len(queue) + 1,
            "bucket": bucket,
            "sango": entry.get("sango", ""),
            "french": entry.get("french", ""),
            "english": entry.get("english", ""),
        })
        return True

    # ── 1. Greetings ─────────────────────────────────────────────────────────
    # Priority: beginner first, then intermediate
    greetings_priority = [
        "bara âla", "Singila", "balaó", "Ndzoni", "Goué nzoni",
        "Tongana nye?", "Mbi yeke séngé", "Yeke Sengué", "Mawa",
        "Mbi gbû gèrè ti âla", "Ye ayeke da apè", "iri tí mo nye ?",
        "Te kobe nzoni",
    ]
    # Try priority list first, then any remaining greetings
    greetings_by_sango = {e["sango"]: e for e in by_cat.get("greetings", [])}
    for s in greetings_priority:
        if s in greetings_by_sango:
            add(greetings_by_sango[s], "greeting")
    for e in by_cat.get("greetings", []):
        add(e, "greeting")

    # ── 2. Numbers 0-10 ──────────────────────────────────────────────────────
    num_targets = ["zéro", "un", "deux", "trois", "quatre", "cinq",
                   "six", "sept", "huit", "neuf", "dix"]
    # Prefer intermediate/beginner over advanced (advanced = dialect variants)
    for target in num_targets:
        entry = pick_one_by_french(entries, target, ["beginner", "intermediate", "advanced"])
        if entry:
            add(entry, "number")

    # ── 3. Pronouns / essential yes/no ───────────────────────────────────────
    essential_targets = ["Ein", "Awe", "lo", "ala", "mo"]
    essential_by_sango = {e["sango"]: e for e in by_cat.get("essential", [])}
    for s in essential_targets:
        if s in essential_by_sango:
            add(essential_by_sango[s], "essential")

    # ── 4. Questions ─────────────────────────────────────────────────────────
    question_targets = ["Okè", "ndo"]
    questions_by_sango = {e["sango"]: e for e in by_cat.get("questions", [])}
    for s in question_targets:
        if s in questions_by_sango:
            add(questions_by_sango[s], "question")

    # ── 5. Common verbs ──────────────────────────────────────────────────────
    verb_french_targets = [
        "manger", "boire", "dormir", "parler", "voir", "aller",
        "venir", "faire", "savoir", "donner", "être",
    ]
    verb_entries = by_cat.get("verbs", []) + by_cat.get("actions", [])
    for target in verb_french_targets:
        entry = pick_one_by_french(verb_entries, target, ["beginner", "intermediate", "advanced"])
        if entry:
            add(entry, "verb")

    # ── 6. Daily nouns ───────────────────────────────────────────────────────
    noun_french_targets = [
        "eau", "nourriture", "maison", "famille", "enfant",
        "homme", "femme", "argent",
    ]
    noun_entries = (
        by_cat.get("food", []) + by_cat.get("family", []) +
        by_cat.get("home", []) + by_cat.get("commerce", []) +
        by_cat.get("essential", []) + by_cat.get("noun", [])
    )
    for target in noun_french_targets:
        entry = pick_one_by_french(noun_entries, target, ["beginner", "intermediate", "advanced"])
        if entry:
            add(entry, "noun")

    # ── Write CSV ─────────────────────────────────────────────────────────────
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["order", "bucket", "sango", "french", "english"])
        writer.writeheader()
        for row in queue:
            writer.writerow(row)

    print(f"\n[OK] {len(queue)} entries written to {OUT_CSV}")
    print(f"     Normalized filename stems (first 10):")
    for row in queue[:10]:
        print(f"       {normalize_sango(row['sango']):<35}  ← {row['sango']}")
    print()
    print("Next steps:")
    print("  1. Review top-50.csv — check for any missing targets in [no match] warnings")
    print("  2. Record the session following scripts/audio/TUTORIAL.md")
    print(f"  3. python splitter.py <recording.m4a> {OUT_CSV} out/audio")
    print("  4. python scripts/audio/gen-manifest.py")
    print("  5. validate, obtain signed consent, then publish")


if __name__ == "__main__":
    main()
