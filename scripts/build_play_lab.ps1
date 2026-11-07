$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$playLabPreviousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path (Get-Location) "src"
    # A new folder leaves dist/SpiderPlayLab, dist/v0.104, dist/v0.105, and any user-added files in place.
    # The Windows "python" app-execution alias is not an interpreter. The py launcher is.
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -3 -m PyInstaller --noconfirm --clean --distpath dist/v0.106 spider_play_lab.spec
    } else {
        python -m PyInstaller --noconfirm --clean --distpath dist/v0.106 spider_play_lab.spec
    }
    if ($LASTEXITCODE -ne 0) { throw "Play Lab build failed ($LASTEXITCODE)" }
} finally {
    $env:PYTHONPATH = $playLabPreviousPythonPath
}
Write-Host "Play Lab: dist/v0.106/SpiderPlayLab/SpiderPlayLab.exe"
