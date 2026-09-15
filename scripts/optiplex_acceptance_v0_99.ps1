# Optiplex acceptance checklist for v0.99.
# The Grok Build host is NOT the Dell Optiplex. Run this on the actual Optiplex.
# ASCII-only for Windows PowerShell 5.1.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONPATH = Join-Path (Get-Location) "src"

Write-Host "=== Optiplex acceptance v0.99 ==="
Write-Host "1. App launch (python tools/campaign_gui.py or dist/SpiderCampaign/SpiderCampaign.exe)"
python -c "import ast; ast.parse(open('tools/campaign_gui.py',encoding='utf-8').read()); print('GUI parse OK')"
Write-Host "2. Hardware detection"
python -c "import sys; sys.path.insert(0,'src'); from spider.hardware import detect_hardware; s=detect_hardware(); print(s.as_dict())"
Write-Host "3. Optional: Recalibrate in GUI (~15s) then confirm AUTO workers/RSS/global RAM"
Write-Host "4. CONTROL_187 scientific calibration (lean worker equivalence)"
python -m pytest -q tests/test_scientific_campaign_portability_v0_99.py::test_worker_is_lean_and_equivalent --tb=short
Write-Host "5. Create/import v0.84 campaign in GUI (Import v0.84 F2s)"
Write-Host "6. Run 2-3 short jobs (Start), then Pause after current job"
Write-Host "7. Close the app"
Write-Host "8. Reopen the same campaign folder"
Write-Host "9. Resume - completed work must not be re-queued"
Write-Host "10. Export Campaign to a .spidercampaign file"
Write-Host "11. Import that file into a NEW local folder"
Write-Host "12. Verify completed jobs/results/ancestry intact; hardware_profile.json is NOT in the bundle"
Write-Host "Do not claim Optiplex acceptance until these steps are actually run on the Dell Optiplex."
