"""Persisted machine-local hardware profile. Campaign data stays portable."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from spider.hardware import SOLVER_VERSION, HardwareSnapshot, detect_hardware
from spider.resource_policy import ResourceConfig, recommend_config
from spider.search_calibration import CalibrationResult, calibrate_search, maybe_second_worker_probe

PROFILE_NAME = "hardware_profile.json"


def profile_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "SpiderSolver" / PROFILE_NAME
    return Path.home() / ".spider-solver" / PROFILE_NAME


def load_profile(path: Optional[Path] = None) -> Optional[dict]:
    p = path or profile_path()
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_profile(data: dict, path: Optional[Path] = None) -> Path:
    p = path or profile_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(p)
    return p


def profile_mismatch(profile: Optional[dict], snap: HardwareSnapshot) -> bool:
    if not profile:
        return True
    return str(profile.get("machine_id") or "") != snap.machine_id


def build_profile(snap: HardwareSnapshot, cal: CalibrationResult, cfg: ResourceConfig) -> dict:
    return {
        "machine_id": snap.machine_id,
        "hostname": snap.hostname,
        "physical_cores": snap.physical_cores,
        "logical_cores": snap.logical_cores,
        "ram_total_gb": round(snap.ram_total_gb, 2),
        "arch": snap.arch,
        "unique_per_s": round(cal.unique_per_s, 2),
        "expanded_per_s": round(cal.expanded_per_s, 2),
        "peak_rss_mb": cal.peak_rss_mb,
        "workers": cfg.workers,
        "per_worker_rss_mb": cfg.per_worker_rss_mb,
        "global_ram_limit_gb": cfg.global_ram_limit_gb,
        "max_unique": cfg.max_unique,
        "calibrated_at": datetime.now(timezone.utc).isoformat(),
        "solver_version": SOLVER_VERSION,
        "mode": "AUTO",
        "disk_speed_used": False,
        "calibration": cal.as_dict(),
        "hardware": snap.as_dict(),
        "config": cfg.as_dict(),
    }


def calibrate_and_save(*, time_s: float = 15.0, path: Optional[Path] = None) -> dict:
    snap = detect_hardware()
    cal = calibrate_search(time_s=time_s)
    cal.second_worker = maybe_second_worker_probe(snap, cal)
    cfg = recommend_config(snap, measured_rss_mb=cal.peak_rss_mb, measured_unique_per_s=cal.unique_per_s)
    profile = build_profile(snap, cal, cfg)
    save_profile(profile, path)
    return profile
