"""Process-level campaign scheduler with a global memory guard.

Independent TTs. No shared transposition table. Disk speed unused.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys
from pathlib import Path
from typing import Callable, Optional

from spider.campaign_store import load_campaign, record_throttle, save_campaign
from spider.hardware import detect_hardware, memory_pressure
from spider.packed_state import pack_state, unpack_state
from spider.research_actions import tableau_actions
from spider.resource_policy import ResourceConfig
from spider.search_kernel import SearchLimits, run_search


def run_pending_jobs(
    campaign_dir: Path,
    cfg: ResourceConfig,
    *,
    on_log: Optional[Callable[[str], None]] = None,
    live_workers: Optional[int] = None,
) -> dict:
    """Run pending jobs with conservative process workers and a memory guard."""

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    src = str(Path(__file__).resolve().parents[1])
    os.environ["PYTHONPATH"] = src + os.pathsep + os.environ.get("PYTHONPATH", "")
    if src not in sys.path:
        sys.path.insert(0, src)
    data = load_campaign(campaign_dir)
    pending = [j for j in data.get("jobs") or [] if j.get("status") == "pending"]
    workers = max(1, int(live_workers if live_workers is not None else cfg.workers))
    ctx = mp.get_context("spawn")
    launched = 0
    finished = 0
    out_dir = Path(campaign_dir) / "_job_results"
    out_dir.mkdir(parents=True, exist_ok=True)

    cand_by_id = {c["id"]: c for c in data.get("candidates") or []}
    i = 0
    while i < len(pending):
        snap = detect_hardware()
        pressure = memory_pressure(snap)
        if pressure == "high":
            after = 1
            record_throttle(data, reason=f"memory_pressure {pressure} avail_gb={snap.ram_available_gb:.2f}", workers_before=workers, workers_after=after)
            workers = after
            log(f"THROTTLE memory pressure={pressure}; workers→{workers}")
            save_campaign(campaign_dir, data)
        batch = pending[i : i + workers]
        if not batch:
            break
        procs = []
        paths = []
        for job in batch:
            cand = cand_by_id.get(job["candidate_id"]) or {}
            payload = dict(job)
            payload["g"] = cand.get("g")
            payload["ordered_digest"] = cand.get("ordered_digest")
            outp = out_dir / f"{job['id']}.json"
            proc = ctx.Process(target=job_worker, args=(payload, str(outp), cfg.per_worker_rss_mb))
            proc.start()
            procs.append((proc, job, outp))
            launched += 1
            job["status"] = "running"
        save_campaign(campaign_dir, data)
        for proc, job, outp in procs:
            proc.join()
            result = {}
            if outp.exists():
                result = json.loads(outp.read_text(encoding="utf-8"))
            job["status"] = "done" if proc.exitcode == 0 else "failed"
            job["result"] = result
            job["exitcode"] = proc.exitcode
            finished += 1
            log(f"JOB {job['id'][:8]} {job['status']} unique={result.get('unique')} stop={result.get('stop_reason')}")
        save_campaign(campaign_dir, data)
        i += len(batch)
        # adapt workers at boundary
        snap = detect_hardware()
        if memory_pressure(snap) == "ok" and snap.ram_total_gb > 20 and workers < cfg.workers:
            workers = min(cfg.workers, workers + 1)
        elif memory_pressure(snap) != "ok":
            workers = 1
    return {"launched": launched, "finished": finished, "workers": workers, "pending_left": sum(1 for j in data.get("jobs") or [] if j.get("status") == "pending")}


def job_worker(job: dict, out_path: str, rss_abort_mb: float) -> None:
    digest = job.get("ordered_digest")
    cand_g = int(job.get("g") or 0)
    if digest:
        root = {"g": cand_g, "ordered_digest": digest, "symmetry_digest": digest}
        terminal = lambda st: st.is_solved()
        ceiling = int(job.get("ceiling") or 186)
    else:
        from spider.whole_game_anytime import opening_state

        opening = opening_state()
        packed = pack_state(opening).hex()
        root = {"g": 0, "ordered_digest": packed, "symmetry_digest": packed}
        terminal = lambda st: False
        ceiling = None
    kr = run_search(
        [root],
        limits=SearchLimits(
            max_unique=int(job.get("max_unique") or 80_000),
            time_limit_s=float(job.get("time_s") or 8.0),
            rss_abort_mb=float(rss_abort_mb),
            cost_ceiling=ceiling,
        ),
        identity_fn=pack_state,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=("cost", "reveal", "construction"),
        is_terminal=terminal,
        actions_fn=tableau_actions,
        lower_bound_fn=None,
        stop_on_first_terminal=bool(digest),
    )
    Path(out_path).write_text(
        json.dumps(
            {
                "job_id": job.get("id"),
                "status": "done",
                "unique": kr.unique,
                "expanded": kr.expanded,
                "generated": kr.generated,
                "elapsed_s": kr.elapsed_s,
                "peak_rss_mb": kr.peak_rss_mb,
                "stop_reason": kr.stop_reason,
                "first_g": kr.first_g,
                "solved": bool(kr.terminals),
            }
        ),
        encoding="utf-8",
    )
