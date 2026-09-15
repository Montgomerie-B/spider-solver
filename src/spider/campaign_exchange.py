"""Immutable shared-folder result packages. Local live DB + shared exchange artefacts.

Never put an actively-written campaign database on a synchronised share
and allow multiple machines to mutate it concurrently.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from spider.campaign_store import load_campaign, record_run, save_campaign
from spider.hardware import SOLVER_VERSION, detect_hardware


def _sha(obj: dict) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def publish_result(shared: Path, campaign: dict, job: dict, *, machine_id: Optional[str] = None) -> Path:
    """Write an immutable result package. Never overwrite an existing file."""

    shared = Path(shared)
    uuid = campaign.get("uuid") or "unknown"
    mid = machine_id or detect_hardware().machine_id.replace("|", "_")
    job_id = job.get("id") or "job"
    result = job.get("result") or {}
    cand = next((c for c in campaign.get("candidates") or [] if c.get("id") == job.get("candidate_id")), None) or {}
    pkg = {
        "campaign_uuid": uuid,
        "candidate_id": job.get("candidate_id"),
        "job_id": job_id,
        "starting_g": result.get("starting_g") if result.get("starting_g") is not None else cand.get("g"),
        "starting_identity": cand.get("ident") or cand.get("whole_game_identity") or result.get("identity"),
        "ceiling": job.get("ceiling"),
        "solver_version": SOLVER_VERSION,
        "solver_sha": result.get("solver_sha"),
        "resource_envelope": {
            "time_s": job.get("time_s"),
            "max_unique": job.get("max_unique") or result.get("max_unique"),
            "rss_cap_mb": result.get("rss_cap_mb"),
        },
        "result": result,
        "status": job.get("status"),
        "scientific_counters": {
            "unique": result.get("unique"),
            "expanded": result.get("expanded"),
            "generated": result.get("generated"),
            "duplicate_skips": result.get("duplicate_skips"),
            "stale_skips": result.get("stale_skips"),
            "lower_bound_calls": result.get("lower_bound_calls"),
            "lower_bound_prunes": result.get("lower_bound_prunes"),
            "lane_exp": result.get("lane_exp"),
            "max_foundations": result.get("max_foundations"),
        },
        "milestones": {
            "first_F": result.get("first_F"),
            "cheap_F": result.get("cheap_F"),
            "minf_F": result.get("minf_F"),
        },
        "terminal": {
            "g": result.get("terminal_g"),
            "s": result.get("terminal_s"),
            "actions": result.get("terminal_actions"),
            "ref": result.get("terminal_ref"),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "machine_id": mid,
    }
    pkg["checksum"] = _sha({k: v for k, v in pkg.items() if k != "checksum"})
    dest_dir = shared / "exchange" / str(uuid) / mid
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{job_id}.json"
    if dest.exists():
        alt = dest_dir / f"{job_id}.{pkg['checksum'][:12]}.json"
        dest = alt
        if dest.exists():
            return dest
    dest.write_text(json.dumps(pkg, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return dest


def ingest_results(shared: Path, campaign_dir: Path) -> dict:
    shared = Path(shared)
    data = load_campaign(campaign_dir)
    uuid = data.get("uuid")
    seen = {r.get("content_hash") for r in data.get("imported_results") or []}
    seen |= {r.get("job_id") for r in data.get("imported_results") or []}
    added = 0
    skipped = 0
    conflicts = 0
    redundant = 0
    root = shared / "exchange" / str(uuid)
    if not root.exists():
        return {"added": 0, "skipped": 0, "conflicts": 0, "redundant": 0}
    cand_by_id = {c.get("id"): c for c in data.get("candidates") or []}
    for path in root.rglob("*.json"):
        pkg = json.loads(path.read_text(encoding="utf-8"))
        chk = pkg.get("checksum")
        body = {k: v for k, v in pkg.items() if k != "checksum"}
        if chk != _sha(body):
            skipped += 1
            continue
        h = chk or pkg.get("job_id")
        if h in seen or pkg.get("job_id") in seen:
            skipped += 1
            continue
        existing = [
            j
            for j in (data.get("jobs") or []) + (data.get("runs") or [])
            if j.get("candidate_id") == pkg.get("candidate_id")
            and j.get("ceiling") == pkg.get("ceiling")
            and isinstance(j.get("result"), dict)
            and j.get("result")
        ]
        rec = {
            "job_id": pkg.get("job_id"),
            "candidate_id": pkg.get("candidate_id"),
            "ceiling": pkg.get("ceiling"),
            "result": pkg.get("result"),
            "machine_id": pkg.get("machine_id"),
            "content_hash": chk,
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "provenance_only": True,
        }
        if existing:
            prev_res = existing[0].get("result") or {}
            new_res = pkg.get("result") or {}
            same = (
                prev_res.get("stop_reason") == new_res.get("stop_reason")
                and prev_res.get("unique") == new_res.get("unique")
                and prev_res.get("ceiling") == new_res.get("ceiling")
                and (prev_res.get("solver_sha") or pkg.get("solver_sha")) == (new_res.get("solver_sha") or pkg.get("solver_sha"))
            )
            if same:
                rec["audit"] = "redundantly_completed"
                redundant += 1
            else:
                rec["audit"] = "result_differs"
                conflicts += 1
        data.setdefault("imported_results", []).append(rec)
        record_run(
            data,
            {"id": pkg.get("job_id"), "candidate_id": pkg.get("candidate_id"), "ceiling": pkg.get("ceiling"), "status": "imported", "worker_host": pkg.get("machine_id")},
            pkg.get("result") or rec,
        )
        if rec.get("candidate_id") in cand_by_id and (pkg.get("result") or {}).get("solved"):
            cand_by_id[rec["candidate_id"]]["imported_solved"] = True
        seen.add(h)
        seen.add(pkg.get("job_id"))
        added += 1
    save_campaign(campaign_dir, data)
    return {"added": added, "skipped": skipped, "conflicts": conflicts, "redundant": redundant}
