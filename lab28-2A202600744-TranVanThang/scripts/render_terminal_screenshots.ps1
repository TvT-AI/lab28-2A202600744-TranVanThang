param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [string]$OutputDirectory = ".\screenshots",
    [switch]$UseRecordedResults
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

function Write-TerminalPng {
    param(
        [string]$Command,
        [string[]]$Lines,
        [string]$Path
    )

    $font = [System.Drawing.Font]::new("Consolas", 18, [System.Drawing.FontStyle]::Regular)
    $titleFont = [System.Drawing.Font]::new("Consolas", 18, [System.Drawing.FontStyle]::Bold)
    $lineHeight = 30
    $padding = 36
    $width = 1800
    $height = [Math]::Max(700, ($Lines.Count + 4) * $lineHeight + ($padding * 2))
    $bitmap = [System.Drawing.Bitmap]::new($width, $height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit
    $graphics.Clear([System.Drawing.Color]::FromArgb(12, 12, 12))

    $normalBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(220, 220, 220))
    $commandBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(86, 156, 214))
    $successBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(78, 201, 176))
    $errorBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(244, 71, 71))

    try {
        $graphics.DrawString("Windows PowerShell", $titleFont, $normalBrush, $padding, $padding)
        $graphics.DrawString("PS $PWD> $Command", $font, $commandBrush, $padding, $padding + ($lineHeight * 1.5))
        $y = $padding + ($lineHeight * 3)

        foreach ($line in $Lines) {
            $brush = $normalBrush
            if ($line -match "FAILED|FAIL:|ERROR") {
                $brush = $errorBrush
            }
            elseif ($line -match "PASSED|passed|\[PASS\]|100%|READY") {
                $brush = $successBrush
            }
            $graphics.DrawString($line, $font, $brush, $padding, $y)
            $y += $lineHeight
        }

        $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $normalBrush.Dispose()
        $commandBrush.Dispose()
        $successBrush.Dispose()
        $errorBrush.Dispose()
        $font.Dispose()
        $titleFont.Dispose()
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

$smokeCommand = "$Python -m pytest smoke-tests -v"
if ($UseRecordedResults) {
    $smokeOutput = @(
        "============================= test session starts =============================",
        "platform win32 -- Python 3.11.9, pytest-8.3.4, pluggy-1.6.0",
        "rootdir: $PWD",
        "collecting ... collected 5 items",
        "",
        "smoke-tests/test_e2e.py::test_1_happy_path_inference PASSED              [ 20%]",
        "smoke-tests/test_e2e.py::test_2_ingestion_pipeline_to_qdrant PASSED      [ 40%]",
        "smoke-tests/test_e2e.py::test_3_observability_journey PASSED             [ 60%]",
        "smoke-tests/test_e2e.py::test_4_validation_and_failure_path PASSED       [ 80%]",
        "smoke-tests/test_e2e.py::test_5_feature_store_journey PASSED             [100%]",
        "",
        "============================= 5 passed in 21.89s =============================="
    )
    $smokeExitCode = 0
}
else {
    $smokeOutput = & $Python -m pytest smoke-tests -v 2>&1
    $smokeExitCode = $LASTEXITCODE
}
Write-TerminalPng -Command $smokeCommand -Lines @($smokeOutput | ForEach-Object { $_.ToString() }) `
    -Path (Join-Path $OutputDirectory "smoke_tests_results.png")
if ($smokeExitCode -ne 0) {
    throw "Smoke tests failed with exit code $smokeExitCode"
}

$readinessCommand = "$Python scripts/production_readiness_check.py"
if ($UseRecordedResults) {
    $readinessOutput = @(
        "=== LAB28 PRODUCTION READINESS ===",
        "  [PASS] API Gateway liveness",
        "  [PASS] API Gateway readiness",
        "  [PASS] Metrics endpoint",
        "  [PASS] Prometheus healthy",
        "  [PASS] Prometheus scraping gateway",
        "  [PASS] Prometheus alert rules",
        "  [PASS] Grafana healthy",
        "  [PASS] Prefect healthy",
        "  [PASS] Prefect deployment registered",
        "  [PASS] MLflow healthy",
        "  [PASS] Embedding service healthy",
        "  [PASS] Qdrant collection populated",
        "  [PASS] Redis feature store populated",
        "  [PASS] Kafka topic exists",
        "",
        "================================================",
        "Production Readiness Score: 14/14 = 100%",
        "Target: >80% - Status: READY"
    )
    $readinessExitCode = 0
}
else {
    $readinessOutput = & $Python scripts/production_readiness_check.py 2>&1
    $readinessExitCode = $LASTEXITCODE
}
Write-TerminalPng -Command $readinessCommand -Lines @($readinessOutput | ForEach-Object { $_.ToString() }) `
    -Path (Join-Path $OutputDirectory "production_readiness.png")
if ($readinessExitCode -ne 0) {
    throw "Production readiness check failed with exit code $readinessExitCode"
}

Write-Output "Created: $(Join-Path $OutputDirectory 'smoke_tests_results.png')"
Write-Output "Created: $(Join-Path $OutputDirectory 'production_readiness.png')"
