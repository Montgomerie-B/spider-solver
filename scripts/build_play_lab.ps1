$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$playLabPreviousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path (Get-Location) "src"
    # Preserve the existing v0.103 package and any user-added solution files.
    python -m PyInstaller --noconfirm --clean --distpath dist/v0.104 spider_play_lab.spec
    if ($LASTEXITCODE -ne 0) { throw "Play Lab build failed ($LASTEXITCODE)" }
} finally {
    $env:PYTHONPATH = $playLabPreviousPythonPath
}
Write-Host "Play Lab: dist/v0.104/SpiderPlayLab/SpiderPlayLab.exe"
