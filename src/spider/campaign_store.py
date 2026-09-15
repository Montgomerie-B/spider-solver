"""Portable campaign database. Not bound to the machine that created it."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from spider.campaign_schedule import DEFAULT_ROUNDS

CAMPAIGN_FILE = "campaign.json"


def campaign_path(folder: Path) -> Path:
    return Path(folder) / CAMPAIGN_FILE


def new_campaign(*, incumbent_g: int = 187, ceiling: int = 186, deal_id: str = "4925153") -> dict:
    return {
        "version": 1,
        "uuid": str(uuid.uuid4()),
        "deal_id": deal_id,
        "rules_profile": "mobilityware_unrestricted",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "incumbent_g": int(incumbent_g),
        "production_ceiling": int(ceiling),
        "created_host_note": "informational only; results remain valid on other machines",
        "scientific_worker": "LEAN_CONSEQUENCE",
        "schedule": [dict(r) for r in DEFAULT_ROUNDS],
        "current_round": 1,
        "candidates": [],
        "jobs": [],
        "runs": [],
        "imported_results": [],
        "throttle_events": [],
        "completed_work": [],
        "closed_registry": [],
        "solutions": [],
        "shared_folder": None,
    }


def load_campaign(folder: Path) -> dict:
    path = campaign_path(folder)
    if not path.exists():
        data = new_campaign()
        save_campaign(folder, data)
        return data
    return json.loads(path.read_text(encoding="utf-8"))


def save_campaign(folder: Path, data: dict) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = campaign_path(folder)
    tmp = path.with_suffix(".json.tmp")
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def add_candidate(
    data: dict,
    *,
    g: int,
    ordered_digest: str,
    label: Optional[str] = None,
    ident: Optional[str] = None,
    assembly_h: Optional[int] = None,
    assembly_f: Optional[int] = None,
    full_actions: Optional[list] = None,
    n_deal: Optional[int] = None,
    source_experiment: Optional[str] = None,
    source_candidate_id: Optional[str] = None,
    proof_dead: bool = False,
    pre_digest: Optional[str] = None,
    prefix_artefact: Optional[dict] = None,
    whole_game_identity: Optional[str] = None,
) -> dict:
    rec = {
        "id": str(uuid.uuid4()),
        "g": int(g),
        "ordered_digest": ordered_digest,
        "ident": ident or whole_game_identity,
        "whole_game_identity": whole_game_identity or ident,
        "assembly_h": assembly_h,
        "assembly_f": assembly_f if assembly_f is not None else (None if assembly_h is None else int(g) + int(assembly_h)),
        "full_actions": full_actions,
        "n_deal": n_deal,
        "source_experiment": source_experiment,
        "source_candidate_id": source_candidate_id,
        "proof_dead": bool(proof_dead),
        "pre_digest": pre_digest,
        "prefix_artefact": prefix_artefact,
        "label": label,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    data.setdefault("candidates", []).append(rec)
    return rec


def enqueue_job(data: dict, candidate_id: str, *, ceiling: int, time_s: float, max_unique: int, round_n: Optional[int] = None) -> dict:
    job = {
        "id": str(uuid.uuid4()),
        "candidate_id": candidate_id,
        "ceiling": int(ceiling),
        "time_s": float(time_s),
        "max_unique": int(max_unique),
        "round": round_n,
        "status": "pending",
        "result": None,
        "worker_host": None,
    }
    data.setdefault("jobs", []).append(job)
    return job


def record_run(data: dict, job: dict, result: dict) -> dict:
    rec = {
        "run_id": str(uuid.uuid4()),
        "job_id": job.get("id"),
        "candidate_id": job.get("candidate_id"),
        "ceiling": job.get("ceiling"),
        "result": result,
        "status": job.get("status") or result.get("status"),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "machine_id": result.get("machine_id") or job.get("worker_host"),
    }
    data.setdefault("runs", []).append(rec)
    data.setdefault("completed_work", []).append(
        {"job_id": rec["job_id"], "candidate_id": rec["candidate_id"], "run_id": rec["run_id"]}
    )
    return rec


def record_throttle(data: dict, *, reason: str, workers_before: int, workers_after: int) -> None:
    data.setdefault("throttle_events", []).append(
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "workers_before": workers_before,
            "workers_after": workers_after,
        }
    )
