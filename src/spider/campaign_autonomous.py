"""Autonomous deep local campaign manager.

G123_DIAMOND_DEEP is the first production Optiplex profile.
Timeouts are budgets. REPEAT 24H is an honest 24h job, not a fake 7-day stop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from spider.campaign_expand import (
    bulk_sd5,
    create_g123_campaign,
    enqueue_deepen,
    expand_node,
    proof_filter,
)
from spider.campaign_nodes import deepen_priority, get_node, status_unresolved
from spider.campaign_ops import (
    OP_DEEPEN,
    OP_EVALUATE,
    OP_FILTER,
    OP_GENERATE,
    OP_SD5,
    enqueue_operation,
    mark_done,
    mark_running,
    next_pending,
    recover_stale_operations,
)
from spider.campaign_scheduler import run_pending_jobs
from spider.campaign_store import load_campaign, save_campaign
from spider.f2_quality_frontier import HARVEST_UNIQUE
from spider.incumbent import production_ceiling
from spider.resource_policy import ResourceConfig

# Production G123 Diamond autopilot. Times are local research budgets.
G123_DIAMOND_DEEP_PLAN = (
    {"step_id": "G1", "type": OP_GENERATE, "suit": "d", "time_s": 180.0, "unique": HARVEST_UNIQUE},
    {"step_id": "T1", "type": OP_SD5},
    {"step_id": "F1", "type": OP_FILTER},
    {"step_id": "D1", "type": OP_EVALUATE, "time_s": 300.0, "scope": "all_live"},
    {"step_id": "G2", "type": OP_GENERATE, "suit": "d", "time_s": 1800.0, "unique": HARVEST_UNIQUE},
    {"step_id": "T2", "type": OP_SD5},
    {"step_id": "F2", "type": OP_FILTER},
    {"step_id": "D1b", "type": OP_EVALUATE, "time_s": 300.0, "scope": "new_live"},
    {"step_id": "D2", "type": OP_DEEPEN, "time_s": 1800.0, "scope": "unresolved"},
    {"step_id": "D3", "type": OP_DEEPEN, "time_s": 7200.0, "scope": "unresolved"},
    {"step_id": "D4", "type": OP_DEEPEN, "time_s": 28800.0, "scope": "unresolved"},
    {"step_id": "D5", "type": OP_DEEPEN, "time_s": 86400.0, "scope": "unresolved"},
    {"step_id": "D6", "type": OP_DEEPEN, "time_s": 86400.0, "scope": "unresolved", "repeat": True, "label": "REPEAT_24H"},
)

SMOKE_PLAN = (
    {"step_id": "G1", "type": OP_GENERATE, "suit": "d", "time_s": 4.0, "unique": 4000},
    {"step_id": "T1", "type": OP_SD5},
    {"step_id": "F1", "type": OP_FILTER},
    {"step_id": "D1", "type": OP_EVALUATE, "time_s": 1.5, "unique": 400, "scope": "all_live"},
    {"step_id": "D2", "type": OP_DEEPEN, "time_s": 1.5, "unique": 400, "scope": "unresolved"},
)

PROFILES = {
    "G123_DIAMOND_DEEP": {
        "label": "g123 Diamond deep (production)",
        "plan": G123_DIAMOND_DEEP_PLAN,
    },
    "SCREEN": {"label": "Screen", "plan": G123_DIAMOND_DEEP_PLAN[:4]},
    "DEEP": {"label": "Deep", "plan": G123_DIAMOND_DEEP_PLAN[:9]},
    "OVERNIGHT": {"label": "Overnight", "plan": G123_DIAMOND_DEEP_PLAN[:11]},
    "REPEAT_24H": {"label": "REPEAT 24H", "plan": G123_DIAMOND_DEEP_PLAN},
    "SMOKE": {"label": "Build/test smoke", "plan": SMOKE_PLAN},
}


def _paused(folder: Path) -> bool:
    return (Path(folder) / "_pause").exists() or (Path(folder) / "_stop").exists()


def campaign_stats(data: dict) -> dict:
    nodes = data.get("nodes") or []
    se = [n for n in nodes if n.get("kind") in ("STOCK_EMPTY", "SOLVED")]
    f2 = [n for n in nodes if n.get("kind") == "PRE_STOCK"]
    live = [n for n in se if not str(n.get("status") or "").startswith("PROOF_DEAD") and n.get("status") != "SOLVED"]
    unresolved = [n for n in se if status_unresolved(n)]
    by_budget = {}
    for n in unresolved:
        key = str(int(float(n.get("deepest_budget_s") or 0)))
        by_budget[key] = by_budget.get(key, 0) + 1
    hours = sum(float(n.get("total_search_s") or 0.0) for n in nodes) / 3600.0
    return {
        "n_f2": len(f2),
        "n_post_sd5": len(se),
        "proof_live": sum(1 for n in se if not str(n.get("status") or "").startswith("PROOF_DEAD") and n.get("status") != "EXHAUSTED"),
        "proof_dead": sum(1 for n in se if str(n.get("status") or "").startswith("PROOF_DEAD")),
        "unresolved": len(unresolved),
        "unresolved_by_budget": by_budget,
        "solved": sum(1 for n in se if n.get("status") == "SOLVED"),
        "exhausted": sum(1 for n in se if n.get("status") == "EXHAUSTED"),
        "search_hours": round(hours, 4),
        "incumbent_g": data.get("incumbent_g"),
        "production_ceiling": data.get("production_ceiling"),
    }


def _ensure_g123(data: dict, log) -> dict:
    if data.get("g123_id") and get_node(data, data["g123_id"]):
        return get_node(data, data["g123_id"])
    node = create_g123_campaign(data)
    log(f"Created g123 checkpoint {node['id'][:8]} g={node['g']}")
    return node


def _seed_plan(data: dict, plan) -> None:
    if any(op.get("step_id") for op in data.get("operations") or []):
        return
    for step in plan:
        enqueue_operation(data, step["type"], **{k: v for k, v in step.items() if k != "type"})


def _repeat_tail(data: dict, plan) -> None:
    last = plan[-1]
    if not last.get("repeat"):
        return
    pending = [o for o in data.get("operations") or [] if o.get("status") == "pending"]
    if pending:
        return
    running = [o for o in data.get("operations") or [] if o.get("status") == "running"]
    if running:
        return
    enqueue_operation(data, last["type"], **{k: v for k, v in last.items() if k != "type"})


def _live_stockempty(data: dict, *, only_new: bool = False) -> list:
    out = []
    for n in data.get("nodes") or []:
        if n.get("kind") != "STOCK_EMPTY":
            continue
        if str(n.get("status") or "").startswith("PROOF_DEAD"):
            continue
        if n.get("status") in ("EXHAUSTED", "SOLVED", "KNOWN_CLOSED"):
            continue
        if only_new and n.get("runs"):
            continue
        if status_unresolved(n) or n.get("status") in ("OPEN", None, ""):
            out.append(n)
    out.sort(key=deepen_priority)
    return out


def _execute_op(data: dict, op: dict, cfg: ResourceConfig, campaign_dir: Path, log) -> dict:
    typ = op.get("type")
    p = op.get("params") or {}
    if typ == OP_GENERATE:
        g123 = _ensure_g123(data, log)
        summary = expand_node(
            data,
            g123,
            time_s=float(p.get("time_s") or 180.0),
            max_unique=int(p.get("unique") or HARVEST_UNIQUE),
            suit=p.get("suit") or "d",
        )
        hist = summary.get("history") or {}
        n_f2 = hist.get("n_unique") or summary.get("n_children") or 0
        if float(p.get("time_s") or 0) >= 120 and int(n_f2) < 50:
            log(f"WARNING Diamond generation produced only {n_f2} unique F2s (v0.84/v0.100 reference ~279)")
        return summary
    if typ == OP_SD5:
        return bulk_sd5(data)
    if typ == OP_FILTER:
        return proof_filter(data)
    if typ in (OP_EVALUATE, OP_DEEPEN):
        time_s = float(p.get("time_s") or 300.0)
        unique = int(p.get("unique") or cfg.max_unique)
        scope = p.get("scope") or "unresolved"
        nodes = _live_stockempty(data, only_new=(scope == "new_live"))
        nq = 0
        for node in nodes:
            if typ == OP_EVALUATE and any(abs(float(r.get("time_s") or 0) - time_s) < 0.05 for r in node.get("runs") or []):
                continue
            if typ == OP_DEEPEN and float(node.get("deepest_budget_s") or 0) + 1e-6 >= time_s:
                continue
            if enqueue_deepen(data, node, time_s=time_s, max_unique=unique):
                nq += 1
        save_campaign(campaign_dir, data)
        finished = {"queued": nq, "finished": 0}
        if nq:
            summary = run_pending_jobs(campaign_dir, cfg, on_log=log)
            finished["finished"] = int(summary.get("finished") or 0)
        return finished
    return {"op": "noop"}


def run_autonomous_campaign(
    campaign_dir: Path,
    cfg: ResourceConfig,
    *,
    profile: str = "G123_DIAMOND_DEEP",
    on_log: Optional[Callable[[str], None]] = None,
    max_ops: Optional[int] = None,
) -> dict:
    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    spec = dict(PROFILES.get(profile) or PROFILES["G123_DIAMOND_DEEP"])
    plan = spec["plan"]
    data = load_campaign(campaign_dir)
    data["autonomous_profile"] = profile
    data.setdefault("autopilot", {})["profile"] = profile
    data["autopilot"]["state"] = "RUNNING"
    recover = recover_stale_operations(data)
    if recover:
        log(f"Recovered {recover} stale RUNNING operation(s)")
    _ensure_g123(data, log)
    _seed_plan(data, plan)
    save_campaign(campaign_dir, data)

    ran = 0
    while True:
        if _paused(campaign_dir):
            data = load_campaign(campaign_dir)
            data["autopilot"]["state"] = "PAUSED" if (Path(campaign_dir) / "_pause").exists() else "STOPPED"
            save_campaign(campaign_dir, data)
            log("PAUSE/STOP after current operation")
            break
        data = load_campaign(campaign_dir)
        recover_stale_operations(data)
        op = next_pending(data)
        if op is None:
            _repeat_tail(data, plan)
            save_campaign(campaign_dir, data)
            op = next_pending(data)
            if op is None:
                data["autopilot"]["state"] = "STOPPED"
                save_campaign(campaign_dir, data)
                log("Autopilot plan complete")
                break
        data["autopilot"]["current_op_id"] = op["id"]
        data["autopilot"]["current_type"] = op.get("type")
        data["autopilot"]["current_step"] = (op.get("params") or {}).get("step_id")
        mark_running(op)
        save_campaign(campaign_dir, data)
        log(f"OP {op.get('type')} {(op.get('params') or {}).get('step_id')}")
        try:
            result = _execute_op(data, op, cfg, campaign_dir, log)
            data = load_campaign(campaign_dir)
            for rec in data.get("operations") or []:
                if rec.get("id") == op["id"]:
                    mark_done(rec, result)
                    break
        except Exception as exc:
            data = load_campaign(campaign_dir)
            for rec in data.get("operations") or []:
                if rec.get("id") == op["id"]:
                    rec["status"] = "failed"
                    rec["result"] = {"error": str(exc)}
                    break
            log(f"OP failed: {exc}")
        data["autopilot"]["current_op_id"] = None
        save_campaign(campaign_dir, data)
        ran += 1
        if max_ops is not None and ran >= int(max_ops):
            break
    data = load_campaign(campaign_dir)
    stats = campaign_stats(data)
    return {
        "profile": profile,
        "ops_run": ran,
        "autopilot": data.get("autopilot"),
        "stats": stats,
        "incumbent_g": data.get("incumbent_g"),
        "production_ceiling": data.get("production_ceiling"),
        "nodes": len(data.get("nodes") or []),
        "operations": len(data.get("operations") or []),
        "f2_generated": stats.get("n_f2"),
        "sd5": stats.get("n_post_sd5"),
        "waves": ran,
    }
