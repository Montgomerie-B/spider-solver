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
            op["status"] = PENDING
            op["recovered_from"] = STALE
            op["started_at"] = None
            n += 1
    if n:
        ap = campaign.setdefault("autopilot", {})
        if ap.get("state") == "RUNNING":
            ap["state"] = "RUNNING"
    return n


def mark_running(op: dict) -> None:
    op["status"] = RUNNING
    op["started_at"] = datetime.now(timezone.utc).isoformat()


def mark_done(op: dict, result: Optional[dict] = None) -> None:
    op["status"] = DONE
    op["result"] = result
    op["finished_at"] = datetime.now(timezone.utc).isoformat()


def next_pending(campaign: dict) -> Optional[dict]:
    for op in campaign.get("operations") or []:
        if op.get("status") == PENDING:
            return op
    return None
