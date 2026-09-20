$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$playLabPreviousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path (Get-Location) "src"
    python -m PyInstaller --noconfirm --clean spider_play_lab.spec
    if ($LASTEXITCODE -ne 0) { throw "Play Lab build failed ($LASTEXITCODE)" }
} finally {
    $env:PYTHONPATH = $playLabPreviousPythonPath
}
Write-Host "Play Lab: dist/SpiderPlayLab/SpiderPlayLab.exe"
