"""Machine-independent incumbent promotion after a ceiling-feasible solve."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from spider.campaign_store import save_campaign
from spider.incumbent import production_ceiling, promote_incumbent
from spider.metrics import replay_actions
from spider.research_actions import as_actions, dump_actions, format_moves_text, is_deal
from spider.whole_game_anytime import opening_state


def reconstruct_and_replay(candidate: dict, result: dict) -> dict:
    prefix = as_actions(candidate.get("full_actions") or [])
    suffix = as_actions(result.get("terminal_actions") or [])
    if not prefix:
        return {"ok": False, "reason": "missing_prefix_ancestry"}
    if not suffix and not result.get("solved"):
        return {"ok": False, "reason": "missing_terminal_path"}
    full = list(prefix) + list(suffix)
    opening = opening_state()
    end = opening.clone()
    try:
        g = replay_actions(end, full)
    except Exception as exc:
        return {"ok": False, "reason": f"illegal:{exc}"}
    n_deal = sum(1 for a in full if is_deal(a))
    ok = (
        bool(end.is_solved())
        and g == int(result.get("terminal_g") or g)
        and n_deal == 5
        and len(end.foundations) == 8
        and not end.stock
        and all(c.is_empty() for c in end.columns)
    )
    return {
        "ok": bool(ok),
        "g": g,
        "n_deal": n_deal,
        "foundations": len(end.foundations),
        "solved": bool(end.is_solved()),
        "full_actions": dump_actions(full),
        "reason": None if ok else "replay_contract_failed",
    }


def reevaluate_proof_viability(campaign: dict) -> int:
    ceiling = int(campaign.get("production_ceiling") or production_ceiling())
    marked = 0
    by_id = {c.get("id"): c for c in campaign.get("candidates") or []}
    for cand in campaign.get("candidates") or []:
        f = cand.get("assembly_f")
        if f is None:
            continue
        dead = int(f) > ceiling
        if dead and not cand.get("proof_dead"):
            marked += 1
        cand["proof_dead"] = bool(dead)
    for job in campaign.get("jobs") or []:
        if job.get("status") != "pending":
            continue
        cand = by_id.get(job.get("candidate_id")) or {}
        if cand.get("proof_dead") and not cand.get("lower_g_reopening"):
            job["status"] = "skipped_proof_dead"
    return marked


def promote_if_solved(campaign: dict, candidate: dict, result: dict, *, folder: Optional[Path] = None) -> dict:
    if not result.get("solved") or result.get("terminal_g") is None:
        return {"promoted": False, "reason": "not_solved"}
    g = int(result["terminal_g"])
    ceiling = int(campaign.get("production_ceiling") or production_ceiling())
    if g > ceiling:
        return {"promoted": False, "reason": "above_ceiling", "g": g}
    replay = reconstruct_and_replay(candidate, result)
    if not replay.get("ok"):
        return {"promoted": False, "replay": replay, "reason": replay.get("reason")}
    campaign["incumbent_g"] = int(replay["g"])
    campaign["production_ceiling"] = int(replay["g"]) - 1
    sol = {
        "g": int(replay["g"]),
        "candidate_id": candidate.get("id"),
        "job_id": result.get("job_id"),
        "full_actions": replay.get("full_actions"),
        "n_deal": replay.get("n_deal"),
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "machine_independent": True,
    }
    campaign.setdefault("solutions", []).append(sol)
    campaign["incumbent"] = sol
    reevaluate_proof_viability(campaign)
    if folder is not None:
        dest = Path(folder) / "solutions"
        dest.mkdir(parents=True, exist_ok=True)
        moves_path = dest / f"incumbent_g{replay['g']}.moves"
        moves_path.write_text(
            format_moves_text(as_actions(replay.get("full_actions") or []), header=f"# incumbent g={replay['g']}\n"),
            encoding="utf-8",
        )
        save_campaign(folder, campaign)
        promote_incumbent(
            g=int(replay["g"]),
            moves_path=str(moves_path),
            source="campaign_promote",
        )
    else:
        promote_incumbent(
            g=int(replay["g"]),
            moves_path=f"solutions/incumbent_g{replay['g']}.moves",
            source="campaign_promote",
        )
    return {"promoted": True, "g": replay["g"], "ceiling": campaign["production_ceiling"], "replay": replay}
