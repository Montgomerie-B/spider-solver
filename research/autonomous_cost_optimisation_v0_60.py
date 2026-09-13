#!/usr/bin/env python3
"""v0.60: incumbent-aware autonomous whole-game cost optimisation.

Optimises the v0.59 machine solution. Does not read the human canonical
trace for search policy. One policy, one main run.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.autonomous_cost import (
    COST_LANES,
    choose_cost_verdict,
    epoch_savings_table,
    load_machine_incumbent,
    replay_solution_trace,
    search_cost_optimisation,
)
from spider.metrics import CANONICAL_MOBILITYWARE_MOVES
from spider.research_actions import is_deal
from spider.whole_game_epoch_scheduler import (
    PORTFOLIO_WIDTH,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    save_solution,
)
from spider.whole_game_anytime import opening_state

EXPERIMENT = "autonomous_cost_optimisation_v0_60"
BASE_SHA = "b2c3806013bbfcde56e2958c78bdcc65d3ec62da"
BRANCH = "agent/autonomous-cost-optimisation-v0-60"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "autonomous_cost_progress_v0_60.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_60.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_60.json"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _jsonable(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def next_recommendation(verdict: str, best) -> str:
    if verdict == "AUTONOMOUS_COST_IMPROVED":
        return "Stay on autonomous whole-game cost optimisation and diagnose which epochs produced the saving before choosing the next mechanism."
    if verdict == "AUTONOMOUS_OPTIMISATION_CONTRACT_FAILURE":
        return "Stop solver work until the contract failure is diagnosed."
    return "Do not widen the envelope yet. Use epoch-cost and portfolio telemetry to decide whether the bottleneck is early investment, portfolio cost blindness, lineage loss, rehandling, or late completion."


def write_report(payload: dict) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{payload.get('verdict')}`",
        "",
        payload.get("interpretation", ""),
        "",
        "## Incumbent",
        "",
        json.dumps(payload.get("incumbent"), indent=2, sort_keys=True),
        "",
        "## Prefix costs",
        "",
        json.dumps(payload.get("incumbent_prefix"), indent=2, sort_keys=True),
        "",
        "## Totals",
        "",
        json.dumps(
            {k: payload.get(k) for k in (
                "elapsed_s", "unique", "expanded", "generated", "states_per_s",
                "stop_reason", "solution_g", "improvement", "candidate_ceiling",
            )},
            indent=2,
            sort_keys=True,
        ),
        "",
        "## Epoch savings",
        "",
        json.dumps(payload.get("epoch_savings"), indent=2, sort_keys=True),
        "",
        "## Next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
    ]
    REPORT.write_text("\n".join(str(x) for x in lines) + "\n", encoding="utf-8")


def main() -> dict:
    opening = opening_state()
    inc = load_machine_incumbent(opening)
    print(
        f"INCUMBENT g={inc['g']} deals={inc['deals']} zeros={inc['zero_cost_total']} "
        f"prefixes={inc['exit_g_by_rows']}",
        flush=True,
    )
    t0 = time.perf_counter()
    res = search_cost_optimisation(opening=opening, incumbent_trace=inc)
    print(
        f"DONE stop={res.stop_reason} unique={res.unique} expanded={res.expanded} "
        f"best={res.solution_g} t={res.elapsed_s:.1f}s",
        flush=True,
    )
    cand_trace = None
    if res.solved and res.replay_ok and res.solution_actions:
        cand_trace = replay_solution_trace(opening, res.solution_actions)
    improvement = None
    if res.solution_g is not None:
        improvement = int(inc["g"]) - int(res.solution_g)
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "incumbent": {
            "g": inc["g"],
            "deals": inc["deals"],
            "tableau_commands": inc["tableau_commands"],
            "zero_cost_total": inc["zero_cost_total"],
            "path": "solutions/4925153_autonomous_v0_59.moves",
        },
        "incumbent_prefix": inc["exit_g_by_rows"],
        "incumbent_enter": inc["prefix_g_by_rows"],
        "incumbent_epochs": [
            {
                "stock_rows": ep["stock_rows"],
                "enter_g": ep["enter_g"],
                "exit_g": ep["exit_g"],
                "paid_increment": ep["paid_increment"],
                "zero_cost": ep["zero_cost"],
                "tableau_n": ep["tableau_n"],
                "fd_delta": ep["fd_delta"],
                "foundations_before": ep["foundations_before"],
                "exit_foundations": ep["exit_foundations"],
            }
            for ep in inc["epochs"]
        ],
        "elapsed_s": res.elapsed_s,
        "wall_s": time.perf_counter() - t0,
        "peak_rss_mb": res.peak_rss_mb,
        "unique": res.unique,
        "expanded": res.expanded,
        "generated": res.generated,
        "duplicate_skips": res.duplicate_skips,
        "stale_skips": res.stale_skips,
        "states_per_s": res.states_per_s,
        "stop_reason": res.stop_reason,
        "min_g": res.min_g,
        "max_g": res.max_g,
        "lanes": {"names": list(COST_LANES), "pops": res.lane_pops, "expansions": res.lane_exp, "stale": res.lane_stale},
        "envelope": {
            "time_s": SEARCH_TIME_S,
            "unique": SEARCH_UNIQUE,
            "rss_abort_mb": SEARCH_RSS_MB,
            "candidate_ceiling_initial": inc["g"] - 1,
            "portfolio_width": PORTFOLIO_WIDTH,
            "harvest_slack": -1,
            "remaining_deal_bound": True,
        },
        "class_displaced": res.class_displaced,
        "incumbent_injected": res.incumbent_injected,
        "incumbent_survived": res.incumbent_survived,
        "candidate_ceiling": res.candidate_ceiling,
        "incumbent_g": inc["g"],
        "solved": res.solved,
        "solution_g": res.solution_g,
        "replay_ok": res.replay_ok,
        "replay_g": res.replay_g,
        "improvement": improvement,
        "accounting_fail": res.accounting_fail,
        "max_foundations": res.max_foundations,
        "min_face_down": res.min_face_down,
        "foundations": {
            "first": {str(k): v for k, v in sorted(res.foundations_first.items())},
            "cheap": {str(k): v for k, v in sorted(res.foundations_cheap.items())},
        },
        "epochs": res.epochs,
        "epoch_savings": epoch_savings_table(inc, cand_trace),
        "best_state": res.best_state,
        "best_readiness": res.best_readiness,
        "canonical_g_eval_only": CANONICAL_MOBILITYWARE_MOVES,
        "production_unchanged": True,
    }
    if (
        res.solved
        and res.replay_ok
        and res.solution_g is not None
        and int(res.solution_g) < int(inc["g"])
        and res.solution_actions
    ):
        deals = sum(1 for a in res.solution_actions if is_deal(a))
        payload["solution_tableau_moves"] = len(res.solution_actions) - deals
        payload["solution_deals"] = deals
        payload["solution_explicit"] = len(res.solution_actions)
        save_solution(res.solution_actions, FIX, g=int(res.solution_g))
        _write_json(
            META,
            {
                "g": res.solution_g,
                "previous_incumbent": inc["g"],
                "improvement": improvement,
                "replay_g": res.replay_g,
                "replay_ok": True,
                "tableau_moves": payload["solution_tableau_moves"],
                "deals": deals,
                "explicit_actions": len(res.solution_actions),
                "path": str(FIX.relative_to(ROOT)).replace("\\", "/"),
                "branch": BRANCH,
                "base_sha": BASE_SHA,
                "autonomous_provenance": "v0.59 machine incumbent corridor, not the human trace",
            },
        )
        payload["solution_file"] = str(FIX.relative_to(ROOT)).replace("\\", "/")
    verdict, interpretation = choose_cost_verdict(payload)
    payload["verdict"] = verdict
    payload["interpretation"] = interpretation
    payload["next_recommendation"] = next_recommendation(verdict, res.solution_g)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    _write_json(
        PROG,
        {
            "incumbent_prefix": payload.get("incumbent_prefix"),
            "epochs": payload.get("epochs"),
            "foundations_cheap": payload.get("foundations", {}).get("cheap"),
            "epoch_savings": payload.get("epoch_savings"),
            "solution_g": payload.get("solution_g"),
            "stop_reason": payload.get("stop_reason"),
        },
    )
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"WROTE {RESULT}", flush=True)
    return payload


if __name__ == "__main__":
    main()
