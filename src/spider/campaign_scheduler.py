"""Process-level campaign scheduler with a global memory guard.

Independent TTs. No shared transposition table. Disk speed unused.
Real jobs use the calibrated lean consequence worker only.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys
from pathlib import Path
from typing import Callable, Optional

from spider.campaign_integrity import job_payload_from_node, refilter_graph, sync_candidate_from_node, validate_node_ancestry
from spider.campaign_nodes import get_node, record_node_run
from spider.campaign_promote import promote_if_solved
from spider.campaign_status import FAILED_CONTRACT, classify_outcome
from spider.campaign_store import load_campaign, record_run, record_throttle, save_campaign
from spider.campaign_worker import WORKER_MODE, current_solver_sha, job_worker
from spider.hardware import detect_hardware, memory_pressure
from spider.incumbent import production_ceiling
from spider.resource_policy import ResourceConfig


def run_pending_jobs(
    campaign_dir: Path,
    cfg: ResourceConfig,
    *,
    on_log: Optional[Callable[[str], None]] = None,
    live_workers: Optional[int] = None,
    operation_id: Optional[str] = None,
) -> dict:
    """Run pending jobs. If operation_id is set, only that operation's members run."""

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    src = str(Path(__file__).resolve().parents[1])
    os.environ["PYTHONPATH"] = src + os.pathsep + os.environ.get("PYTHONPATH", "")
    if src not in sys.path:
        sys.path.insert(0, src)
    data = load_campaign(campaign_dir)

    def pending_jobs():
        out = []
        for j in data.get("jobs") or []:
            if j.get("status") != "pending":
                continue
            if operation_id is not None and j.get("operation_id") != operation_id:
                continue
            out.append(j)
        return out

    pending = pending_jobs()
    workers = max(1, int(live_workers if live_workers is not None else cfg.workers))
    ctx = mp.get_context("spawn")
    launched = 0
    finished = 0
    failed = 0
    out_dir = Path(campaign_dir) / "_job_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    sha = current_solver_sha()
    snap0 = detect_hardware()
    paused = False

    cand_by_id = {c["id"]: c for c in data.get("candidates") or []}
    i = 0
    while i < len(pending):
        snap = detect_hardware()
        pressure = memory_pressure(snap)
        if pressure == "high":
            after = 1
            record_throttle(data, reason=f"memory_pressure {pressure} avail_gb={snap.ram_available_gb:.2f}", workers_before=workers, workers_after=after)
            workers = after
            log(f"THROTTLE memory pressure={pressure}; workers={workers}")
            save_campaign(campaign_dir, data)
        if (Path(campaign_dir) / "_pause").exists() or (Path(campaign_dir) / "_stop").exists():
            log("PAUSE/STOP after current job boundary")
            paused = True
            break
        batch = pending[i : i + workers]
        if not batch:
            break
        procs = []
        for job in batch:
            node = get_node(data, job.get("node_id") or "") if job.get("node_id") else None
            if node is None:
                for n in data.get("nodes") or []:
                    if n.get("candidate_id") == job.get("candidate_id"):
                        node = n
                        break
            cand = cand_by_id.get(job["candidate_id"]) or {}
            if node is not None:
                sync_candidate_from_node(data, node)
                cand = cand_by_id.get(job["candidate_id"]) or cand
                if str(node.get("status") or "").startswith("PROOF_DEAD"):
                    job["status"] = "skipped_proof_dead"
                    continue
                chk = validate_node_ancestry(node)
                if not chk.get("ok"):
                    job["status"] = "failed"
                    job["outcome"] = FAILED_CONTRACT
                    job["result"] = chk
                    failed += 1
                    log(f"JOB {str(job['id'])[:8]} FAILED_CONTRACT ancestry {chk.get('reason')}")
                    continue
                payload = job_payload_from_node(node, job)
            else:
                if cand.get("proof_dead") and not cand.get("lower_g_reopening"):
                    job["status"] = "skipped_proof_dead"
                    continue
                if cand.get("known_closed") and not cand.get("lower_g_reopening"):
                    job["status"] = "skipped_known_closed"
                    continue
                payload = dict(job)
                payload["g"] = cand.get("g")
                payload["ordered_digest"] = cand.get("ordered_digest")
                payload["ident"] = cand.get("ident") or cand.get("whole_game_identity")
                payload["assembly_h"] = cand.get("assembly_h")
                payload["full_actions"] = cand.get("full_actions")
            payload["worker_mode"] = WORKER_MODE
            payload["solver_sha"] = sha
            payload["machine_id"] = snap0.machine_id
            payload["max_unique"] = int(job.get("max_unique") or cfg.max_unique)
            outp = out_dir / f"{job['id']}.json"
            proc = ctx.Process(target=job_worker, args=(payload, str(outp), cfg.per_worker_rss_mb))
            proc.start()
            procs.append((proc, job, outp, cand, node))
            launched += 1
            job["status"] = "running"
            job["worker_host"] = snap0.machine_id
        save_campaign(campaign_dir, data)
        for proc, job, outp, cand, node in procs:
            proc.join()
            result = {}
            missing = not outp.exists()
            if not missing:
                try:
                    result = json.loads(outp.read_text(encoding="utf-8"))
                except Exception as exc:
                    result = {"status": "failed", "error": f"unreadable:{exc}"}
                    missing = True
            crash = proc.exitcode != 0 or missing or result.get("status") == "failed"
            if crash:
                job["status"] = "failed"
                outcome = FAILED_CONTRACT
                result["outcome"] = FAILED_CONTRACT
                result["contract_fail"] = True
                if proc.exitcode != 0:
                    result["error"] = result.get("error") or f"exitcode={proc.exitcode}"
                if missing:
                    result["error"] = result.get("error") or "missing_result"
                failed += 1
            else:
                job["status"] = "done"
                outcome = classify_outcome(
                    result,
                    ceiling=int(job.get("ceiling") or data.get("production_ceiling") or production_ceiling()),
                    assembly_f=(node or cand).get("assembly_f") if isinstance(node or cand, dict) else None,
                )
            result["outcome"] = outcome
            job["outcome"] = outcome
            job["result"] = result
            job["exitcode"] = proc.exitcode
            record_run(data, job, result)
            target_node = node
            if target_node is None:
                for n in data.get("nodes") or []:
                    if n.get("candidate_id") == job.get("candidate_id") or n.get("id") == job.get("node_id"):
                        target_node = n
                        break
            if target_node is not None:
                record_node_run(target_node, {**result, "time_s": job.get("time_s"), "outcome": outcome})
            if result.get("solved") and not crash:
                src = node or cand
                promo = promote_if_solved(data, src, result, folder=campaign_dir)
                log(f"PROMOTE {promo}")
                cand_by_id = {c["id"]: c for c in data.get("candidates") or []}
            finished += 1
            log(
                f"JOB {str(job['id'])[:8]} {job['status']} outcome={outcome} "
                f"unique={result.get('unique')} stop={result.get('stop_reason')} mode={WORKER_MODE}"
            )
        save_campaign(campaign_dir, data)
        if paused:
            break
        pending = pending_jobs()
        i = 0
        snap = detect_hardware()
        if memory_pressure(snap) == "ok" and snap.ram_total_gb > 20 and workers < cfg.workers:
            workers = min(cfg.workers, workers + 1)
        elif memory_pressure(snap) != "ok":
            workers = 1
    pending_left = pending_jobs()
    return {
        "launched": launched,
        "finished": finished,
        "failed": failed,
        "paused": paused,
        "workers": workers,
        "worker_mode": WORKER_MODE,
        "pending_left": len(pending_left),
        "operation_id": operation_id,
    }
