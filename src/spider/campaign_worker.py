"""Scientific campaign worker: exact lean consequence search.

v0.98 called generic run_search with pack_state / three lanes / no bound.
That is not the calibrated evaluator. This module is the correction.
Every real stock-empty job calls run_stockempty_consequence directly.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.assembly_policy import COMPLETION_LANES
from spider.consequence_search import MinimalConsequenceObserver, run_stockempty_consequence
from spider.hardware import SOLVER_VERSION
from spider.incumbent import production_ceiling
from spider.packed_state import pack_whole_game_identity, unpack_state
from spider.research_actions import dump_actions
from spider.tactical_integration import strategic_lane_keys


WORKER_MODE = "LEAN_CONSEQUENCE"


def current_solver_sha() -> Optional[str]:
    try:
        root = Path(__file__).resolve().parents[2]
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return out.decode("utf-8").strip()
    except Exception:
        return None


def _slim_store(store: dict) -> dict:
    out = {}
    for k, rec in sorted((store or {}).items()):
        out[str(k)] = {
            "g": rec.get("g"),
            "h": rec.get("h"),
            "f": rec.get("f"),
            "elapsed_s": rec.get("elapsed_s"),
            "ident": rec.get("ident"),
            "foundations": rec.get("foundations"),
        }
    return out


def scientific_result_fields() -> tuple:
    return (
        "solver_sha",
        "solver_version",
        "candidate_id",
        "starting_g",
        "starting_h",
        "starting_f",
        "ceiling",
        "elapsed_s",
        "max_unique",
        "rss_cap_mb",
        "unique",
        "expanded",
        "generated",
        "duplicate_skips",
        "stale_skips",
        "lower_bound_calls",
        "lower_bound_prunes",
        "lane_exp",
        "max_foundations",
        "first_F",
        "cheap_F",
        "minf_F",
        "terminal_g",
        "terminal_s",
        "stop_reason",
        "machine_id",
        "timestamp",
    )


def run_lean_job(job: dict, *, rss_abort_mb: float, trace: bool = False) -> dict:
    """In-process lean search. Same semantics as run_stockempty_consequence."""

    digest = job.get("ordered_digest")
    if not digest:
        raise ValueError("scientific lean jobs require ordered_digest")
    g = int(job.get("g") or 0)
    ceiling = int(job.get("ceiling") or production_ceiling())
    obs = MinimalConsequenceObserver(trace=bool(trace or job.get("trace")))
    root = {
        "g": g,
        "ordered_digest": digest,
        "ident": job.get("ident") or job.get("whole_game_identity"),
    }
    kr = run_stockempty_consequence(
        [root],
        ceiling=ceiling,
        time_limit_s=float(job.get("time_s") or 8.0),
        max_unique=int(job.get("max_unique") or 80_000),
        rss_abort_mb=float(rss_abort_mb),
        stop_on_first_terminal=True if job.get("stop_on_first_terminal", True) else False,
        observer=obs,
        lower_bound_fn=stock_empty_assembly_h,
        lane_names=COMPLETION_LANES,
        lane_keys_fn=strategic_lane_keys,
        identity_fn=pack_whole_game_identity,
    )
    st = unpack_state(bytes.fromhex(digest))
    h = int(job.get("assembly_h") or stock_empty_assembly_h(st, g))
    f = g + h
    terminal_actions = None
    terminal_ref = None
    if kr.terminals:
        t = kr.terminals[0]
        terminal_ref = {"node": t.get("node"), "ident": t.get("ident"), "g": t.get("g"), "store": t.get("store")}
        try:
            terminal_actions = dump_actions(kr.reconstruct(int(t["node"])))
        except Exception:
            terminal_actions = None
    return {
        "job_id": job.get("id"),
        "candidate_id": job.get("candidate_id"),
        "status": "done",
        "worker_mode": WORKER_MODE,
        "solver_version": SOLVER_VERSION,
        "solver_sha": job.get("solver_sha") or current_solver_sha(),
        "starting_g": g,
        "starting_h": h,
        "starting_f": f,
        "ceiling": ceiling,
        "time_s": job.get("time_s"),
        "wall_time_s": kr.elapsed_s,
        "max_unique": job.get("max_unique"),
        "rss_cap_mb": rss_abort_mb,
        "unique": kr.unique,
        "expanded": kr.expanded,
        "generated": kr.generated,
        "duplicate_skips": kr.duplicate_skips,
        "stale_skips": kr.stale_skips,
        "lower_bound_calls": kr.lower_bound_calls,
        "lower_bound_prunes": kr.lower_bound_prunes,
        "lane_exp": dict(kr.lane_exp or {}),
        "horizon_exp": int((kr.lane_exp or {}).get("horizon") or 0),
        "max_foundations": obs.max_F,
        "first_F": _slim_store(obs.first_F),
        "cheap_F": _slim_store(obs.cheap_F),
        "minf_F": _slim_store(obs.minf_F),
        "terminal_g": kr.first_g,
        "terminal_s": kr.first_s,
        "terminal_actions": terminal_actions,
        "terminal_ref": terminal_ref,
        "stop_reason": kr.stop_reason,
        "solved": bool(kr.terminals),
        "elapsed_s": kr.elapsed_s,
        "peak_rss_mb": kr.peak_rss_mb,
        "trace_hash": obs.trace_hex() if obs.trace_enabled else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "machine_id": job.get("machine_id"),
        "no_deal": True,
        "identity": "pack_whole_game_identity",
        "lanes": list(COMPLETION_LANES),
        "scientific_validity_depends_on_machine": False,
    }


def job_worker(job: dict, out_path: str, rss_abort_mb: float) -> None:
    """Spawned process entry. Independent TT. Lean evaluator only for real jobs."""

    try:
        result = run_lean_job(job, rss_abort_mb=rss_abort_mb, trace=bool(job.get("trace")))
    except Exception as exc:
        result = {
            "job_id": job.get("id"),
            "candidate_id": job.get("candidate_id"),
            "status": "failed",
            "worker_mode": WORKER_MODE,
            "error": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    Path(out_path).write_text(json.dumps(result), encoding="utf-8")
