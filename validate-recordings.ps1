# Validate Recorded Audio Files (PowerShell version)
# Checks coverage, file sizes, and quality

param(
    [string]$RecordingsDir = "recordings"
)

Write-Host "🔍 Validating Audio Recordings" -ForegroundColor Cyan
Write-Host "===============================" -ForegroundColor Cyan
Write-Host ""

$vocabFile = "sango_words_for_recording.txt"

if (-not (Test-Path $RecordingsDir)) {
    Write-Host "❌ Recordings directory not found: $RecordingsDir" -ForegroundColor Red
    Write-Host "Usage: .\validate-recordings.ps1 [recordings_directory]"
    exit 1
}

if (-not (Test-Path $vocabFile)) {
    Write-Host "❌ Vocabulary file not found: $vocabFile" -ForegroundColor Red
    Write-Host "Run: .\extract-vocabulary-list.ps1 first"
    exit 1
}

Write-Host "📂 Checking recordings in: $RecordingsDir"
Write-Host ""

# Count expected vs actual
$expectedWords = Get-Content $vocabFile
$expected = $expectedWords.Count
$actualFiles = Get-ChildItem -Path $RecordingsDir -Filter "*.mp3" -File
$actual = $actualFiles.Count

Write-Host "📊 Coverage:"
Write-Host "   Expected: $expected words"
Write-Host "   Found:    $actual audio files"

if ($expected -gt 0) {
    $coverage = [math]::Round(($actual / $expected) * 100, 1)
    Write-Host "   Coverage: $coverage%"
} else {
    $coverage = 0
    Write-Host "   Coverage: 0%"
}
Write-Host ""

# Check for missing files
Write-Host "🔎 Checking for missing recordings..."
$missingCount = 0

foreach ($word in $expectedWords) {
    # Normalize filename (lowercase, spaces to underscores)
    $filename = $word.ToLower() -replace ' ', '_'
    $filepath = Join-Path $RecordingsDir "$filename.mp3"

    if (-not (Test-Path $filepath)) {
        Write-Host "   ❌ Missing: $filename.mp3 (word: $word)" -ForegroundColor Red
        $missingCount++
    }
}

if ($missingCount -eq 0) {
    Write-Host "   ✅ All words have recordings!" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "   ⚠️  Missing: $missingCount recordings" -ForegroundColor Yellow
}
Write-Host ""

# Check file sizes
Write-Host "📏 Checking file sizes..."
$tooSmall = 0
$tooLarge = 0

foreach ($file in $actualFiles) {
    $size = $file.Length

    if ($size -lt 10000) {
        Write-Host "   ⚠️  Too small (<10KB): $($file.Name) ($size bytes)" -ForegroundColor Yellow
        $tooSmall++
    } elseif ($size -gt 100000) {
        Write-Host "   ⚠️  Too large (>100KB): $($file.Name) ($size bytes)" -ForegroundColor Yellow
        $tooLarge++
    }
}

if ($tooSmall -eq 0 -and $tooLarge -eq 0) {
    Write-Host "   ✅ All file sizes in normal range (10-100KB)" -ForegroundColor Green
}
Write-Host ""

# Check audio duration (requires ffprobe)
$ffprobeExists = Get-Command ffprobe -ErrorAction SilentlyContinue

if ($ffprobeExists) {
    Write-Host "⏱️  Checking audio durations..."
    $tooShort = 0
    $tooLong = 0

    $sampleFiles = $actualFiles | Select-Object -First 20

    foreach ($file in $sampleFiles) {
        try {
            $duration = & ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 $file.FullName 2>$null

            if ($duration) {
                $dur = [double]$duration
                if ($dur -lt 0.5) {
                    Write-Host "   ⚠️  Too short (<0.5s): $($file.Name) (${dur}s)" -ForegroundColor Yellow
                    $tooShort++
                } elseif ($dur -gt 5.0) {
                    Write-Host "   ⚠️  Too long (>5s): $($file.Name) (${dur}s)" -ForegroundColor Yellow
                    $tooLong++
                }
            }
        } catch {
            # Skip files that can't be analyzed
        }
    }

    if ($tooShort -eq 0 -and $tooLong -eq 0) {
        Write-Host "   ✅ Sample durations look good (0.5-5 seconds)" -ForegroundColor Green
    }
} else {
    Write-Host "⚠️  ffprobe not installed - skipping duration check" -ForegroundColor Yellow
    Write-Host "   Install: choco install ffmpeg (Windows) or download from ffmpeg.org"
}
Write-Host ""

# Summary
Write-Host "===============================" -ForegroundColor Cyan
Write-Host "📋 Validation Summary" -ForegroundColor Cyan
Write-Host "===============================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Coverage:        $coverage% ($actual/$expected)"
Write-Host "Missing files:   $missingCount"
Write-Host ""

if ($coverage -ge 95) {
    Write-Host "✅ Ready for upload! Coverage is excellent." -ForegroundColor Green
    Write-Host ""
    Write-Host "Next step:"
    Write-Host "  .\upload-all-audio.ps1 $RecordingsDir"
} elseif ($coverage -ge 80) {
    Write-Host "⚠️  Good coverage, but some files missing." -ForegroundColor Yellow
    Write-Host "   Consider recording the missing $missingCount words."
} else {
    Write-Host "❌ Low coverage - need more recordings" -ForegroundColor Red
    Write-Host "   $missingCount words still need to be recorded."
}
Write-Host ""
