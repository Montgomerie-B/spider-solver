"""Persistent campaign operations: GENERATE, TRANSITION_SD5, EVALUATE, DEEPEN.

Restartable at operation boundaries. A crash costs at most the active op.
In-memory TT is never persisted.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional


OP_GENERATE = "GENERATE"
OP_SD5 = "TRANSITION_SD5"
OP_FILTER = "FILTER"
OP_EVALUATE = "EVALUATE"
OP_DEEPEN = "DEEPEN"

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
STALE = "stale_recovered"
PENDING_PARTIAL = "pending_partial"
PAUSED_ERROR = "PAUSED_ERROR"


def enqueue_operation(campaign: dict, op_type: str, **params) -> dict:
    rec = {
        "id": str(uuid.uuid4()),
        "type": op_type,
        "status": PENDING,
        "params": params,
        "result": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": None,
        "finished_at": None,
        "step_id": params.get("step_id"),
    }
    campaign.setdefault("operations", []).append(rec)
    return rec


def recover_stale_operations(campaign: dict) -> int:
    n = 0
    for op in campaign.get("operations") or []:
        if op.get("status") == RUNNING:
            if op.get("member_job_ids"):
                op["status"] = PENDING_PARTIAL
            else:
                op["status"] = PENDING
            op["recovered_from"] = STALE
            op["started_at"] = None
            n += 1
    return n


def mark_running(op: dict) -> None:
    op["status"] = RUNNING
    op["started_at"] = datetime.now(timezone.utc).isoformat()


def mark_done(op: dict, result: Optional[dict] = None) -> None:
    op["status"] = DONE
    op["result"] = result
    op["finished_at"] = datetime.now(timezone.utc).isoformat()


def next_pending(campaign: dict) -> Optional[dict]:
    """Do not advance past a FAILED operation. PENDING_PARTIAL resumes first."""

    for op in campaign.get("operations") or []:
        if op.get("status") == FAILED:
            return None
        if op.get("status") in (PENDING, PENDING_PARTIAL):
            return op
    return None


def mark_failed(op: dict, result: Optional[dict] = None) -> None:
    op["status"] = FAILED
    op["result"] = result
    op["finished_at"] = datetime.now(timezone.utc).isoformat()


def mark_partial(op: dict, result: Optional[dict] = None) -> None:
    op["status"] = PENDING_PARTIAL
    op["result"] = result
    op["started_at"] = None


def retry_failed_operation(campaign: dict) -> Optional[dict]:
    """Reset the most recent FAILED operation and its failed member jobs only.

    Done/skipped members stay. Failure diagnostics go to retry_history.
    """

    op = None
    for rec in reversed(campaign.get("operations") or []):
        if rec.get("status") == FAILED:
            op = rec
            break
    if op is None:
        return None
    hist = {
        "retried_at": datetime.now(timezone.utc).isoformat(),
        "previous_status": op.get("status"),
        "previous_result": op.get("result"),
        "jobs": [],
    }
    member_ids = set(op.get("member_job_ids") or [])
    oid = op.get("id")
    reset = 0
    kept_done = 0
    kept_skipped = 0
    for job in campaign.get("jobs") or []:
        if job.get("id") not in member_ids and job.get("operation_id") != oid:
            continue
        st = str(job.get("status") or "")
        outcome = str(job.get("outcome") or "")
        if st in ("skipped_proof_dead", "skipped_known_closed"):
            kept_skipped += 1
            continue
        failed = st == "failed" or outcome == "FAILED_CONTRACT"
        if failed:
            hist["jobs"].append(
                {
                    "job_id": job.get("id"),
                    "status": st,
                    "outcome": outcome,
                    "exitcode": job.get("exitcode"),
                    "result": job.get("result"),
                }
            )
            job["status"] = PENDING
            job["outcome"] = None
            job["result"] = None
            job["exitcode"] = None
            reset += 1
            continue
        if st == "done":
            kept_done += 1
    op.setdefault("retry_history", []).append(hist)
    op["status"] = PENDING_PARTIAL if (member_ids or reset) else PENDING
    op["retried"] = True
    op["finished_at"] = None
    counts = {"reset": reset, "kept_done": kept_done, "kept_skipped": kept_skipped}
    op["retry_counts"] = counts
    ap = campaign.setdefault("autopilot", {})
    ap["state"] = "RUNNING"
    ap["retry_required"] = False
    return op


def has_failed_operation(campaign: dict) -> bool:
    return any(op.get("status") == FAILED for op in campaign.get("operations") or [])
