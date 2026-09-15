# Optiplex acceptance checklist for v0.100.
# The Grok Build host is NOT the Dell Optiplex. Run this on the actual Optiplex.
# ASCII-only for Windows PowerShell 5.1.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONPATH = Join-Path (Get-Location) "src"

Write-Host "=== Optiplex acceptance v0.100 ==="
Write-Host "1. App launch (python tools/campaign_gui.py or dist/SpiderCampaign/SpiderCampaign.exe)"
python -c "import ast; ast.parse(open('tools/campaign_gui.py',encoding='utf-8').read()); print('GUI parse OK')"
Write-Host "2. Hardware detection"
python -c "import sys; sys.path.insert(0,'src'); from spider.hardware import detect_hardware; s=detect_hardware(); print(s.as_dict())"
Write-Host "3. Recalibrate in GUI (~15s) if hardware profile mismatches"
Write-Host "4. Scientific tests"
python -m pytest -q tests/test_scientific_campaign_portability_v0_99.py::test_worker_is_lean_and_equivalent tests/test_hierarchical_deep_campaign_v0_100.py --tb=short
Write-Host "5. Create Known g123 Campaign"
Write-Host "6. Generate Children (F2 harvest); persist full_actions"
Write-Host "7. Exact SD5 on an F2 child"
Write-Host "8. Evaluate / Deepen Selected on post-SD5 STOCK_EMPTY nodes"
Write-Host "9. Treat time-limit outcomes as UNRESOLVED_TIME, never dead"
Write-Host "10. Pause after current job, close, reopen, Resume"
Write-Host "11. Export Campaign and Import into a new folder; graph/ancestry intact"
Write-Host "Do not claim Optiplex acceptance until these steps are actually run on the Dell Optiplex."
