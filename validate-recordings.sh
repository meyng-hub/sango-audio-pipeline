#!/bin/bash

# Validate Recorded Audio Files
# Checks coverage, file sizes, and quality

set -e

RECORDINGS_DIR="${1:-recordings}"
VOCAB_FILE="sango_words_for_recording.txt"

echo "🔍 Validating Audio Recordings"
echo "==============================="
echo ""

if [ ! -d "$RECORDINGS_DIR" ]; then
    echo "❌ Recordings directory not found: $RECORDINGS_DIR"
    echo "Usage: $0 [recordings_directory]"
    exit 1
fi

if [ ! -f "$VOCAB_FILE" ]; then
    echo "❌ Vocabulary file not found: $VOCAB_FILE"
    echo "Run: ./extract-vocabulary-list.sh first"
    exit 1
fi

echo "📂 Checking recordings in: $RECORDINGS_DIR"
echo ""

# Count expected vs actual
EXPECTED=$(wc -l < "$VOCAB_FILE")
ACTUAL=$(find "$RECORDINGS_DIR" -name "*.mp3" | wc -l)

echo "📊 Coverage:"
echo "   Expected: $EXPECTED words"
echo "   Found:    $ACTUAL audio files"

COVERAGE=$(echo "scale=1; $ACTUAL / $EXPECTED * 100" | bc)
echo "   Coverage: $COVERAGE%"
echo ""

# Check for missing files
echo "🔎 Checking for missing recordings..."
MISSING_COUNT=0

while read word; do
    # Normalize filename (lowercase, spaces to underscores)
    filename=$(echo "$word" | tr '[:upper:]' '[:lower:]' | tr ' ' '_')

    if [ ! -f "$RECORDINGS_DIR/${filename}.mp3" ]; then
        echo "   ❌ Missing: ${filename}.mp3 (word: $word)"
        ((MISSING_COUNT++))
    fi
done < "$VOCAB_FILE"

if [ $MISSING_COUNT -eq 0 ]; then
    echo "   ✅ All words have recordings!"
else
    echo ""
    echo "   ⚠️  Missing: $MISSING_COUNT recordings"
fi
echo ""

# Check file sizes
echo "📏 Checking file sizes..."
TOO_SMALL=0
TOO_LARGE=0

find "$RECORDINGS_DIR" -name "*.mp3" | while read file; do
    SIZE=$(stat -f%z "$file" 2>/dev/null || stat -c%s "$file" 2>/dev/null)

    if [ $SIZE -lt 10000 ]; then
        echo "   ⚠️  Too small (<10KB): $(basename "$file") ($SIZE bytes)"
        ((TOO_SMALL++))
    elif [ $SIZE -gt 100000 ]; then
        echo "   ⚠️  Too large (>100KB): $(basename "$file") ($SIZE bytes)"
        ((TOO_LARGE++))
    fi
done

if [ $TOO_SMALL -eq 0 ] && [ $TOO_LARGE -eq 0 ]; then
    echo "   ✅ All file sizes in normal range (10-100KB)"
fi
echo ""

# Check audio duration (requires ffprobe)
if command -v ffprobe &> /dev/null; then
    echo "⏱️  Checking audio durations..."
    TOO_SHORT=0
    TOO_LONG=0

    find "$RECORDINGS_DIR" -name "*.mp3" | head -20 | while read file; do
        DURATION=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$file" 2>/dev/null)

        if [ ! -z "$DURATION" ]; then
            if (( $(echo "$DURATION < 0.5" | bc -l) )); then
                echo "   ⚠️  Too short (<0.5s): $(basename "$file") (${DURATION}s)"
                ((TOO_SHORT++))
            elif (( $(echo "$DURATION > 5.0" | bc -l) )); then
                echo "   ⚠️  Too long (>5s): $(basename "$file") (${DURATION}s)"
                ((TOO_LONG++))
            fi
        fi
    done

    if [ $TOO_SHORT -eq 0 ] && [ $TOO_LONG -eq 0 ]; then
        echo "   ✅ Sample durations look good (0.5-5 seconds)"
    fi
else
    echo "⚠️  ffprobe not installed - skipping duration check"
    echo "   Install: brew install ffmpeg (Mac) or apt-get install ffmpeg (Linux)"
fi
echo ""

# Summary
echo "==============================="
echo "📋 Validation Summary"
echo "==============================="
echo ""
echo "Coverage:        $COVERAGE% ($ACTUAL/$EXPECTED)"
echo "Missing files:   $MISSING_COUNT"
echo ""

if [ $COVERAGE -ge 95 ]; then
    echo "✅ Ready for upload! Coverage is excellent."
    echo ""
    echo "Next step:"
    echo "  ./upload-all-audio.sh $RECORDINGS_DIR"
elif [ $COVERAGE -ge 80 ]; then
    echo "⚠️  Good coverage, but some files missing."
    echo "   Consider recording the missing $MISSING_COUNT words."
else
    echo "❌ Low coverage - need more recordings"
    echo "   $MISSING_COUNT words still need to be recorded."
fi
echo ""
