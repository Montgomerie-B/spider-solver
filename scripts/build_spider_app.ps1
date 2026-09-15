# One-folder PyInstaller build. Output is not committed.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONPATH = Join-Path (Get-Location) "src"
python -c "import sys; sys.path.insert(0,'src'); sys.path.insert(0,'.'); import spider.campaign_worker; import spider.consequence_search; print('entrypoint-ok')"
python -m PyInstaller --noconfirm --clean spider_campaign.spec
Write-Host "Build output: dist/SpiderCampaign (do not commit)"
