# optiplex_auto_resources_v0_98

AUTO hardware mode for the Optiplex-first campaign runner.

Base: `48be90500a4681108f0e35236bcfe1607869c266`
Branch: `agent/optiplex-auto-resources-v0-98`

## Target machine

Dell Optiplex: Windows, ~16 GB RAM, older i7, **HDD**. Disk speed is never a search input. Long local analytical time is cheap.

The same application should later copy unchanged to a ThinkCentre (~128 GB) and pick up more workers after Recalibrate.

## AUTO behaviour

At startup the GUI detects cores, RAM, architecture, utilisation, and free disk capacity.

First run (or hardware mismatch) offers a ~15 s representative kernel calibration measuring unique/s, expansions/s, and peak RSS.

Persisted locally (`%LOCALAPPDATA%\SpiderSolver\hardware_profile.json`), not inside the portable campaign database.

Conservative 16 GB defaults:

* workers = **1**
* per-worker RSS cap ≈ **2.5 GB**
* global campaign RAM limit ≈ **11 GB**
* max_unique ≈ 300k

A campaign-level memory guard refuses extra jobs and records throttle events when available RAM is low. Workers are processes with independent TTs.

## Portable campaign

`campaigns/<name>/campaign.json` holds candidates, jobs, results, incumbent. Copy it (and/or the app) to another PC. On launch a machine-id mismatch offers Recalibrate; completed work stays valid.

## Acceptance (Optiplex)

1. Install Python + `pip install -r requirements.txt`
2. `run_campaign_gui.bat`
3. Calibrate when prompted (~15 s)
4. Create smoke jobs
5. Start / Resume
6. Close, reopen, resume
7. Leave running unattended

ThinkCentre is a later scale-up, not a v0.98 gate.
