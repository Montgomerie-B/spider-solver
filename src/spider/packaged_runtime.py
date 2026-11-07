"""Resource identity for Play Lab source checkouts and the Windows package.

Source mode keeps git blob checks for the pinned routes. A frozen executable
compares the bundled manifest and replays every route. It does not call git.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Optional

MANIFEST_RELATIVE = "resources/play_lab_manifest.json"
SCHEMA = "spider-play-lab-resources-1"
DEAL_ID = "4925153"

# Compact-kernel peak on this host was 2341.6 MB at 2,000,000 identities.
RETAINED_STATE_BYTES = 1300
IDENTITY_CAP = 2_000_000
MEASURED_PEAK_RSS_MB = 2341.6


def manifest_path(root: Path) -> Path:
    return Path(root) / MANIFEST_RELATIVE


def load_manifest(root: Path) -> dict:
    path = manifest_path(root)
    if not path.is_file():
        raise ValueError(f"Play Lab resource manifest is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA or payload.get("deal_id") != DEAL_ID:
        raise ValueError("Play Lab resource manifest is not the 4925153 package")
    return payload


def manifest_sha256(root: Path) -> str:
    return hashlib.sha256(manifest_path(root).read_bytes()).hexdigest()


def verify_manifest_files(root: Path) -> dict:
    """Reject a package whose bundled deal or routes do not match the manifest."""

    manifest = load_manifest(root)
    files = manifest.get("files") or {}
    if not files:
        raise ValueError("Play Lab resource manifest has no files")
    for relative, item in files.items():
        path = Path(root) / relative
        if not path.is_file():
            raise ValueError(f"bundled resource missing: {relative}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        expected = str(item.get("sha256") or "")
        if digest != expected:
            raise ValueError(f"resource hash mismatch: {relative}")
    return manifest


def packaged_source_fingerprint(root: Path) -> dict:
    """Identity recorded when git is not part of the runtime."""

    from spider.incumbent_suffix import SOURCE_FILES

    files = {}
    missing = []
    for relative in SOURCE_FILES:
        path = Path(root) / relative
        if path.is_file():
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            missing.append(relative)
    digest = manifest_sha256(root)
    return {
        "commit": f"packaged:{digest[:16]}",
        "dirty": False,
        "files_sha256": files,
        "runtime": "packaged",
        "manifest_sha256": digest,
        "missing_source_files": missing,
        "git_used": False,
    }


def runtime_identity(root: Path) -> dict:
    from spider.incumbent_suffix import source_fingerprint

    fingerprint = source_fingerprint(root)
    return {
        "runtime": "packaged" if getattr(sys, "frozen", False) else "source",
        "git_used": not getattr(sys, "frozen", False),
        "manifest_sha256": manifest_sha256(root),
        "fingerprint": fingerprint,
    }


def load_optimiser_routes(root: Path) -> tuple[list, dict]:
    """Replay the suffix sources and the accepted 140 route.

    Historical games stay suffix sources. The 140 route is the incumbent seed.
    """

    from spider.incumbent_suffix import (
        DEAL_ID as SUFFIX_DEAL,
        HISTORICAL_LABELS,
        OWN_ROUTES,
        VERIFIED_157_COST,
        VERIFIED_157_GIT_BLOB,
        VERIFIED_157_HASH16,
        VERIFIED_157_RELATIVE,
        authenticate_moves_path,
        load_authenticated_route,
    )
    from spider.research_actions import opening_from_deal

    if SUFFIX_DEAL != DEAL_ID:
        raise ValueError("optimiser deal does not match the suffix runner")
    repo = Path(root)
    manifest = verify_manifest_files(repo)
    seed = manifest["seed"]
    pinned = manifest["pinned_157"]
    opening = opening_from_deal(repo / "deals" / f"{DEAL_ID}.txt")
    routes = []
    for label, relative in OWN_ROUTES:
        if label not in HISTORICAL_LABELS:
            raise ValueError(f"unexpected historical route {label}")
        routes.append(load_authenticated_route(repo, label, relative))
    frozen = getattr(sys, "frozen", False)
    pinned_route = authenticate_moves_path(
        opening,
        repo / VERIFIED_157_RELATIVE,
        label="157",
        root=repo,
        expected_g=VERIFIED_157_COST,
        expected_hash16=VERIFIED_157_HASH16,
        expected_git_blob=None if frozen else VERIFIED_157_GIT_BLOB,
        git_relative=VERIFIED_157_RELATIVE,
    )
    if int(pinned_route["tableau_moves"]) != 152 or int(pinned_route["stock_deals"]) != 5:
        raise ValueError("157 route tableau or deal count does not match the accepted replay")
    if int(pinned_route["foundations"]) != 8:
        raise ValueError("157 route did not finish eight foundations")
    if pinned_route["path_hash16"] != pinned["action_hash16"]:
        raise ValueError("157 action hash does not match the resource manifest")
    routes.append(pinned_route)
    seed_route = authenticate_moves_path(
        opening,
        repo / seed["relative"],
        label=str(seed["label"]),
        root=repo,
        expected_g=int(seed["g"]),
        expected_hash16=str(seed["action_hash16"]),
        expected_git_blob=None if frozen else str(seed["git_blob"]),
        git_relative=str(seed["relative"]),
    )
    if int(seed_route["g"]) != 140 or seed_route["path_hash16"] != "34a94de8e6edfa4b":
        raise ValueError("140 seed did not replay to the accepted game")
    if int(seed_route["foundations"]) != 8:
        raise ValueError("140 seed did not finish eight foundations")
    routes.append(seed_route)
    return routes, {"opening": opening, "seed": seed_route, "manifest": manifest}


def verify_packaged_seed(root: Optional[Path] = None) -> int:
    """Replay the bundled 140 game. Exit 0 only when the hash matches."""

    from spider.app_paths import repo_root

    repo = Path(root) if root is not None else repo_root()
    routes, payload = load_optimiser_routes(repo)
    seed = payload["seed"]
    line = (
        "PACKAGED_SEED_OK "
        f"hash={seed['path_hash16']} g={seed['g']} "
        f"routes={len(routes)} runtime={'packaged' if getattr(sys, 'frozen', False) else 'source'}"
    )
    stream = sys.stdout
    if stream is not None:
        try:
            print(line, flush=True)
        except Exception:
            pass
    return 0


def resource_report(requested_rss_mb: float, max_unique: Optional[int] = None) -> dict:
    """Requested limits, the clamp this machine will enforce, and retained-state budget."""

    from spider.hardware import detect_hardware
    from spider.method_capture import clamp_rss_mb, probe_host_memory
    from spider.resource_policy import recommend_config

    host = probe_host_memory()
    snap = detect_hardware()
    recommended = recommend_config(
        snap, measured_rss_mb=MEASURED_PEAK_RSS_MB, workers_override=1
    )
    requested = float(requested_rss_mb)
    effective = clamp_rss_mb(requested, int(host.get("available_bytes") or 0), workers=1)
    fit = int((effective * 1024 * 1024) / RETAINED_STATE_BYTES) if effective > 0 else 1
    requested_unique = IDENTITY_CAP if max_unique is None else int(max_unique)
    if requested_unique < 1:
        raise ValueError("max unique must be positive")
    effective_unique = max(1, min(requested_unique, IDENTITY_CAP, max(1, fit)))
    return {
        "workers_requested": 1,
        "workers_effective": 1,
        "requested_rss_mb": requested,
        "effective_rss_mb": float(effective),
        "recommended_rss_mb": float(recommended.per_worker_rss_mb),
        "available_bytes": host.get("available_bytes"),
        "total_bytes": host.get("total_bytes"),
        "probe": host.get("probe"),
        "retained_state_bytes": RETAINED_STATE_BYTES,
        "retained_state_note": (
            "Measured compact-kernel peak was 2341.6 MB at 2,000,000 identities. "
            "The budget uses 1300 bytes per retained state and does not raise that cap."
        ),
        "requested_max_unique": requested_unique,
        "effective_max_unique": int(effective_unique),
        "identity_cap": IDENTITY_CAP,
        "recommendation_notes": recommended.notes,
    }
