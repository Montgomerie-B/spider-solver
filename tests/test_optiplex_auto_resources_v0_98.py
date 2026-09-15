"""v0.98 AUTO hardware, calibration policy, portable campaign."""

from __future__ import annotations

import ast
from pathlib import Path

from spider.campaign_scheduler import run_pending_jobs
from spider.campaign_store import add_candidate, enqueue_job, load_campaign, new_campaign, record_throttle, save_campaign
from spider.hardware import HardwareSnapshot, detect_hardware, machine_id, memory_pressure
from spider.hardware_profile import build_profile, profile_mismatch
from spider.resource_policy import recommend_config
from spider.search_calibration import CalibrationResult

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "tools" / "campaign_gui.py"
HW = ROOT / "src" / "spider" / "hardware.py"
POL = ROOT / "src" / "spider" / "resource_policy.py"


def _optiplex() -> HardwareSnapshot:
    return HardwareSnapshot(
        hostname="optiplex",
        machine_id=machine_id("optiplex", 4, 8, 16 * 1024 ** 3),
        physical_cores=4,
        logical_cores=8,
        ram_total_bytes=16 * 1024 ** 3,
        ram_available_bytes=9 * 1024 ** 3,
        ram_percent=40.0,
        cpu_percent=15.0,
        arch="AMD64",
        disk_free_bytes=200 * 1024 ** 3,
    )


def test_auto_policy_is_conservative_on_16gb():
    snap = _optiplex()
    cfg = recommend_config(snap, measured_rss_mb=180.0, measured_unique_per_s=200.0)
    assert cfg.mode == "AUTO"
    assert cfg.workers == 1
    assert cfg.per_worker_rss_mb <= 2.5 * 1024 + 1
    assert 10.0 <= cfg.global_ram_limit_gb <= 12.5
    assert "disk speed unused" in cfg.notes
    src = POL.read_text(encoding="utf-8")
    assert "disk" in src.lower()
    assert "128" not in src or "Never assume 128" in src
    think = HardwareSnapshot(
        hostname="think",
        machine_id=machine_id("think", 16, 24, 128 * 1024 ** 3),
        physical_cores=16,
        logical_cores=24,
        ram_total_bytes=128 * 1024 ** 3,
        ram_available_bytes=100 * 1024 ** 3,
        ram_percent=20.0,
        cpu_percent=5.0,
        arch="AMD64",
        disk_free_bytes=500 * 1024 ** 3,
    )
    big = recommend_config(think, measured_rss_mb=180.0, measured_unique_per_s=400.0)
    assert big.workers >= 1
    assert big.global_ram_limit_gb > cfg.global_ram_limit_gb


def test_profile_mismatch_and_portable_campaign(tmp_path: Path):
    a = _optiplex()
    cal = CalibrationResult(15.0, 1000, 80, 2000, 66.0, 5.0, 120.0, None, "time limit")
    cfg = recommend_config(a, measured_rss_mb=120.0)
    prof = build_profile(a, cal, cfg)
    assert prof["disk_speed_used"] is False
    assert prof["mode"] == "AUTO"
    b = detect_hardware()
    # live machine id almost certainly differs from fake optiplex
    assert profile_mismatch(prof, b) is True
    assert profile_mismatch(None, b) is True
    folder = tmp_path / "camp"
    data = new_campaign()
    c = add_candidate(data, g=0, ordered_digest="", label="smoke")
    enqueue_job(data, c["id"], ceiling=186, time_s=1.5, max_unique=400)
    save_campaign(folder, data)
    loaded = load_campaign(folder)
    assert loaded["jobs"][0]["status"] == "pending"
    record_throttle(loaded, reason="test", workers_before=2, workers_after=1)
    assert loaded["throttle_events"]
    summary = run_pending_jobs(folder, cfg, live_workers=1)
    assert summary["finished"] >= 1
    done = load_campaign(folder)
    assert done["jobs"][0]["status"] in ("done", "failed")
    hw = HW.read_text(encoding="utf-8")
    assert "disk SPEED" in hw or "Disk SPEED" in hw or "Disk speed" in hw or "disk speed" in hw.lower()
    gui = GUI.read_text(encoding="utf-8")
    assert "Hardware mode:" in gui
    assert "Recalibrate" in gui
    assert "Advanced / Resources" in gui
    tree = ast.parse(gui)
    assert tree
    assert memory_pressure(_optiplex()) == "ok"
    high = HardwareSnapshot(**{**a.__dict__, "ram_available_bytes": int(0.5 * 1024 ** 3), "ram_percent": 95.0})
    assert memory_pressure(high) == "high"
