"""Versioned .spidercampaign ZIP export/import. No hardware profile inside."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from spider.campaign_store import CAMPAIGN_FILE, load_campaign, save_campaign
from spider.campaign_worker import current_solver_sha
from spider.hardware import SOLVER_VERSION

FORMAT = "spidercampaign.v1"
SKIP_NAMES = {
    "hardware_profile.json",
    "_pause",
    "_stop",
    "_job_results",
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _collect_files(folder: Path, data: dict) -> dict:
    files = {CAMPAIGN_FILE: json.dumps(data, indent=2, sort_keys=True).encode("utf-8")}
    sol_dir = Path(folder) / "solutions"
    if sol_dir.exists():
        for path in sol_dir.iterdir():
            if path.is_file() and path.suffix.lower() in {".moves", ".json", ".txt"}:
                files[f"solutions/{path.name}"] = path.read_bytes()
    return files


def export_campaign(folder: Path, dest: Path, *, solver_sha: Optional[str] = None) -> Path:
    folder = Path(folder)
    dest = Path(dest)
    if dest.suffix.lower() != ".spidercampaign":
        dest = dest.with_suffix(".spidercampaign")
    data = load_campaign(folder)
    files = _collect_files(folder, data)
    manifest = {
        "format": FORMAT,
        "campaign_uuid": data.get("uuid"),
        "deal_id": data.get("deal_id") or "4925153",
        "rules_profile": data.get("rules_profile") or "mobilityware_unrestricted",
        "incumbent_g": data.get("incumbent_g"),
        "target_ceiling": data.get("production_ceiling"),
        "solver_version": SOLVER_VERSION,
        "solver_sha": solver_sha or current_solver_sha(),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "files": {name: _sha256_bytes(blob) for name, blob in files.items()},
    }
    man_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", man_bytes)
        for name, blob in files.items():
            zf.writestr(name, blob)
    return dest


def import_campaign(bundle: Path, dest_folder: Path) -> dict:
    bundle = Path(bundle)
    dest_folder = Path(dest_folder)
    with zipfile.ZipFile(bundle, "r") as zf:
        names = zf.namelist()
        if "manifest.json" not in names or CAMPAIGN_FILE not in names:
            raise ValueError("incomplete spidercampaign bundle")
        lowered = [n.lower() for n in names]
        if any(n.endswith("hardware_profile.json") for n in lowered):
            raise ValueError("bundle must not contain machine hardware_profile.json")
        man = json.loads(zf.read("manifest.json").decode("utf-8"))
        expected_files = man.get("files") or {}
        if not expected_files:
            raise ValueError("manifest missing file checksums")
        for name, expected in expected_files.items():
            if name not in names:
                raise ValueError(f"incomplete bundle: missing {name}")
            blob = zf.read(name)
            got = _sha256_bytes(blob)
            if got != expected:
                raise ValueError(f"checksum mismatch for {name}")
        campaign = json.loads(zf.read(CAMPAIGN_FILE).decode("utf-8"))
        dest_folder.mkdir(parents=True, exist_ok=True)
        for name in names:
            if name in ("manifest.json", CAMPAIGN_FILE):
                continue
            base = Path(name).name.lower()
            if base in SKIP_NAMES or name.startswith("_"):
                continue
            target = dest_folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))
    save_campaign(dest_folder, campaign)
    from spider.campaign_integrity import maybe_adopt_imported_incumbent

    campaign["_adopt"] = maybe_adopt_imported_incumbent(campaign, dest_folder)
    return campaign
