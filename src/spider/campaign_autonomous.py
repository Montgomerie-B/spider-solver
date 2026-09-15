"""Autonomous deep local campaign manager.

Create g123, choose a profile, press Start, leave the machine alone.
Timeouts are budgets, never failure. Promotion tightens the ceiling.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from spider.campaign_expand import create_g123_campaign, enqueue_deepen, expand_node, expand_sd5_child
from spider.campaign_nodes import deepen_priority, get_node, status_unresolved
from spider.campaign_schedule import DEFAULT_ROUNDS, next_round_for_node
from spider.campaign_scheduler import run_pending_jobs
from spider.campaign_status import PROOF_DEAD
from spider.campaign_store import load_campaign, save_campaign
from spider.incumbent import production_ceiling
from spider.resource_policy import ResourceConfig

PROFILES = {
    "SCREEN": {
        "label": "Screen (60s)",
        "max_round": 1,
        "f2_time_s": 60.0,
        "f2_unique": 80_000,
        "generate_more": False,
        "max_jobs_per_wave": 64,
        "max_waves": 8,
    },
    "DEEP": {
        "label": "Deep (up to 2h)",
        "max_round": 4,
        "f2_time_s": 180.0,
        "f2_unique": 250_000,
        "generate_more": True,
        "max_jobs_per_wave": 32,
        "max_waves": 10_000,
    },
    "OVERNIGHT": {
        "label": "Overnight (up to 8h)",
        "max_round": 5,
        "f2_time_s": 180.0,
        "f2_unique": 250_000,
        "generate_more": True,
        "max_jobs_per_wave": 16,
        "max_waves": 10_000,
    },
    "UNTIL_STOPPED": {
        "label": "Until stopped",
        "max_round": 7,
        "f2_time_s": 180.0,
        "f2_unique": 250_000,
        "generate_more": True,
        "max_jobs_per_wave": 16,
        "max_waves": 10_000,
    },
    "SMOKE": {
        "label": "Build/test smoke",
        "max_round": 1,
        "f2_time_s": 4.0,
        "f2_unique": 4_000,
        "generate_more": False,
        "max_jobs_per_wave": 2,
        "max_waves": 2,
        "eval_unique": 400,
        "eval_time_s": 1.5,
    },
}


def _paused(folder: Path) -> bool:
    return (Path(folder) / "_pause").exists() or (Path(folder) / "_stop").exists()


def _proof_filter(campaign: dict) -> int:
    ceiling = int(campaign.get("production_ceiling") or production_ceiling())
    n = 0
    for node in campaign.get("nodes") or []:
        f = node.get("assembly_f")
        if f is None:
            continue
        if int(f) > ceiling:
            node.setdefault("proof", {})["proof_dead"] = True
            if node.get("status") != "SOLVED":
                node["status"] = PROOF_DEAD
                n += 1
        for cand in campaign.get("candidates") or []:
            if cand.get("id") == node.get("candidate_id") and cand.get("assembly_f") is None:
                cand["assembly_f"] = f
            if cand.get("id") == node.get("candidate_id"):
                cand["proof_dead"] = int(cand.get("assembly_f") or 0) > ceiling
    return n


def _f2_children(campaign: dict, g123_id: str) -> list:
    return [
        n
        for n in campaign.get("nodes") or []
        if n.get("kind") == "PRE_STOCK" and g123_id in (n.get("parent_ids") or [])
    ]


def _has_sd5_child(campaign: dict, parent_id: str) -> bool:
    return any(
        parent_id in (n.get("parent_ids") or []) and n.get("kind") == "STOCK_EMPTY"
        for n in campaign.get("nodes") or []
    )


def run_autonomous_campaign(
    campaign_dir: Path,
    cfg: ResourceConfig,
    *,
    profile: str = "DEEP",
    on_log: Optional[Callable[[str], None]] = None,
) -> dict:
    """Unattended hierarchical campaign. Does not run long stages during tests (use SMOKE)."""

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    spec = dict(PROFILES.get(profile) or PROFILES["DEEP"])
    data = load_campaign(campaign_dir)
    data["autonomous_profile"] = profile
    if not data.get("g123_id"):
        node = create_g123_campaign(data)
        log(f"Created g123 checkpoint {node['id'][:8]} g={node['g']}")
        save_campaign(campaign_dir, data)

    waves = 0
    jobs_run = 0
    generated = 0
    sd5 = 0
    while waves < int(spec["max_waves"]):
        if _paused(campaign_dir):
            log("PAUSE/STOP at campaign boundary")
            break
        data = load_campaign(campaign_dir)
        data["production_ceiling"] = int(data.get("production_ceiling") or production_ceiling())
        g123 = get_node(data, data.get("g123_id") or "")
        if g123 is None:
            g123 = create_g123_campaign(data)
        f2s = _f2_children(data, g123["id"])
        if not f2s:
            log(f"Generate F2 children t={spec['f2_time_s']}s")
            summary = expand_node(
                data,
                g123,
                time_s=float(spec["f2_time_s"]),
                max_unique=int(spec["f2_unique"]),
                suit="d",
            )
            generated += int(summary.get("n_children") or 0)
            save_campaign(campaign_dir, data)
            f2s = _f2_children(data, g123["id"])

        for pre in list(f2s):
            if not _has_sd5_child(data, pre["id"]):
                child = expand_sd5_child(data, pre)
                if child is not None:
                    sd5 += 1
        _proof_filter(data)
        save_campaign(campaign_dir, data)

        unresolved = [
            n
            for n in data.get("nodes") or []
            if n.get("kind") == "STOCK_EMPTY"
            and status_unresolved(n)
            and not (n.get("proof") or {}).get("proof_dead")
        ]
        unresolved.sort(key=deepen_priority)
        nq = 0
        max_unique = int(spec.get("eval_unique") or cfg.max_unique)
        for node in unresolved:
            if spec.get("eval_time_s") is not None:
                nxt = {"round": 1, "time_s": float(spec["eval_time_s"])}
            else:
                nxt = next_round_for_node(node)
            if int(nxt["round"]) > int(spec["max_round"]):
                continue
            if enqueue_deepen(data, node, time_s=float(nxt["time_s"]), max_unique=max_unique, round_n=int(nxt["round"])):
                nq += 1
                log(f"Queue {node['id'][:8]} round {nxt['round']} t={nxt['time_s']}s")
            if nq >= int(spec["max_jobs_per_wave"]):
                break
        save_campaign(campaign_dir, data)
        waves += 1
        if nq:
            summary = run_pending_jobs(campaign_dir, cfg, on_log=on_log)
            jobs_run += int(summary.get("finished") or 0)
            continue
        if spec.get("generate_more") and waves < int(spec["max_waves"]):
            log("No unresolved stock-empty work; generating more F2 children")
            expand_node(data, g123, time_s=float(spec["f2_time_s"]), max_unique=int(spec["f2_unique"]), suit="d")
            save_campaign(campaign_dir, data)
            continue
        log("Autonomous wave idle: nothing pending under this profile")
        break
    data = load_campaign(campaign_dir)
    return {
        "profile": profile,
        "waves": waves,
        "jobs_run": jobs_run,
        "f2_generated": generated,
        "sd5": sd5,
        "incumbent_g": data.get("incumbent_g"),
        "production_ceiling": data.get("production_ceiling"),
        "nodes": len(data.get("nodes") or []),
        "pending": sum(1 for j in data.get("jobs") or [] if j.get("status") == "pending"),
    }
