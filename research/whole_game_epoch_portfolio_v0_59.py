#!/usr/bin/env python3
"""v0.59: material-horizon epoch-portfolio whole-game scheduler.

One policy, one main run. Terminal is state.is_solved() only.
Does not read the human solution or historical F1 path for search.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.metrics import CANONICAL_MOBILITYWARE_MOVES
from spider.research_actions import face_down_count, is_deal, stock_rows
from spider.structural_analysis import SUITS, next_foundation_material
from spider.whole_game_epoch_scheduler import (
    COST_CEILING,
    LANES,
    PORTFOLIO_WIDTH,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    choose_verdict,
    opening_state,
    save_solution,
    search_epoch_portfolio,
)

EXPERIMENT = "whole_game_epoch_portfolio_v0_59"
BASE_SHA = "1ce2721751300e5ac7ea5b97dfe9d364e3f052d8"
BRANCH = "agent/whole-game-epoch-portfolio-v0-59"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "whole_game_epoch_progress_v0_59.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_59.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_59.json"
V058 = ROOT / "docs" / "research" / "whole_game_anytime_v0_58.json"
HIST_F1_G = 21
CANONICAL_G = CANONICAL_MOBILITYWARE_MOVES
# Historical material-horizon audit (evaluation/regression only, not search).
HIST_FIRST_HORIZON = {"s": 2, "h": 2, "d": 4, "c": 5}


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


def next_recommendation(verdict: str) -> str:
    if verdict == "EPOCH_PORTFOLIO_AUTONOMOUS_SOLVE":
        return "Stay on the whole-game path and begin autonomous move-count optimisation."
    if verdict == "EPOCH_PORTFOLIO_REACHES_F2_OR_BEYOND":
        return "Stay on the whole-game scheduler and diagnose the later-game bottleneck."
    if verdict == "EPOCH_PORTFOLIO_REDISCOVERS_F1":
        return "Stay on the whole-game path and analyse why the F1 lineage fails to survive later epoch portfolios."
    if verdict == "EPOCH_PORTFOLIO_IMPROVES_READINESS_NO_FOUNDATION":
        return "Stay on the whole-game path and refine portfolio survival/search economics, not a target suit."
    if verdict == "EPOCH_PORTFOLIO_CONTRACT_FAILURE":
        return "Stop solver work until the contract failure is diagnosed."
    return "Reassess the whole-game search representation/algorithm rather than widening limits."


def write_report(payload: dict) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{payload.get('verdict')}`",
        "",
        payload.get("interpretation", ""),
        "",
        "## Envelope",
        "",
        f"- time {SEARCH_TIME_S}s, unique {SEARCH_UNIQUE}, RSS {SEARCH_RSS_MB} MB, MW <= {COST_CEILING}",
        f"- portfolio width {PORTFOLIO_WIDTH}",
        "",
        "## Independently derived opening horizons",
        "",
        json.dumps(payload.get("derived_horizons"), indent=2, sort_keys=True),
        "",
        "## Totals",
        "",
        json.dumps(
            {k: payload.get(k) for k in (
                "elapsed_s", "peak_rss_mb", "unique", "expanded", "generated",
                "duplicate_skips", "stale_skips", "states_per_s", "stop_reason",
                "max_foundations", "min_face_down", "solved",
            )},
            indent=2,
            sort_keys=True,
        ),
        "",
        "## Next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
    ]
    REPORT.write_text("\n".join(str(x) for x in lines) + "\n", encoding="utf-8")


def main() -> dict:
    opening = opening_state()
    derived = next_foundation_material(opening)
    derived_h = {s: derived["by_suit"][s]["deals_until_material"] for s in SUITS}
    print(
        f"OPENING fd={face_down_count(opening)} rows={stock_rows(opening)} "
        f"horizons={derived_h} ready={derived['ready_suits']}",
        flush=True,
    )
    t0 = time.perf_counter()
    res = search_epoch_portfolio()
    print(
        f"DONE stop={res.stop_reason} unique={res.unique} expanded={res.expanded} "
        f"max_f={res.max_foundations} solved={res.solved} t={res.elapsed_s:.1f}s",
        flush=True,
    )
    v058 = {}
    if V058.exists():
        v058 = json.loads(V058.read_text(encoding="utf-8"))
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
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
        "lanes": {"names": list(LANES), "pops": res.lane_pops, "expansions": res.lane_exp, "stale": res.lane_stale},
        "envelope": {
            "time_s": SEARCH_TIME_S,
            "unique": SEARCH_UNIQUE,
            "rss_abort_mb": SEARCH_RSS_MB,
            "cost_ceiling": COST_CEILING,
            "portfolio_width": PORTFOLIO_WIDTH,
        },
        "solved": res.solved,
        "solution_g": res.solution_g,
        "replay_ok": res.replay_ok,
        "replay_g": res.replay_g,
        "accounting_fail": res.accounting_fail,
        "deal_illegal": res.deal_illegal,
        "max_foundations": res.max_foundations,
        "min_face_down": res.min_face_down,
        "max_empty": res.max_empty,
        "opening_face_down": face_down_count(opening),
        "derived_horizons": derived_h,
        "historical_horizon_oracle": HIST_FIRST_HORIZON,
        "horizon_oracle_match": derived_h == HIST_FIRST_HORIZON,
        "foundations": {
            "first": {str(k): v for k, v in sorted(res.foundations_first.items())},
            "cheap": {str(k): v for k, v in sorted(res.foundations_cheap.items())},
        },
        "epochs": res.epochs,
        "best_state": res.best_state,
        "best_readiness": res.best_readiness,
        "v058_compare": {
            "unique": v058.get("unique"),
            "expanded": v058.get("expanded"),
            "generated": v058.get("generated"),
            "states_per_s": v058.get("states_per_s"),
            "max_foundations": v058.get("max_foundations"),
            "min_face_down": v058.get("min_face_down"),
            "stale_skips": v058.get("stale_skips"),
        },
        "canonical_g_eval_only": CANONICAL_G,
        "historical_f1_g_eval_only": HIST_F1_G,
        "production_unchanged": True,
    }
    if res.solved and res.solution_actions:
        deals = sum(1 for a in res.solution_actions if is_deal(a))
        payload["solution_tableau_moves"] = len(res.solution_actions) - deals
        payload["solution_deals"] = deals
        if res.replay_ok:
            save_solution(res.solution_actions, FIX, g=int(res.solution_g or 0))
            _write_json(
                META,
                {
                    "g": res.solution_g,
                    "replay_g": res.replay_g,
                    "replay_ok": True,
                    "tableau_moves": payload["solution_tableau_moves"],
                    "deals": deals,
                    "path": str(FIX.relative_to(ROOT)).replace("\\", "/"),
                },
            )
            payload["solution_file"] = str(FIX.relative_to(ROOT)).replace("\\", "/")
    verdict, interpretation = choose_verdict(payload)
    payload["verdict"] = verdict
    payload["interpretation"] = interpretation
    payload["next_recommendation"] = next_recommendation(verdict)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    _write_json(
        PROG,
        {
            "epochs": payload.get("epochs"),
            "foundations_first": payload.get("foundations", {}).get("first"),
            "best_readiness": payload.get("best_readiness"),
            "best_state": payload.get("best_state"),
            "derived_horizons": derived_h,
            "max_foundations": payload.get("max_foundations"),
            "stop_reason": payload.get("stop_reason"),
        },
    )
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"WROTE {RESULT}", flush=True)
    return payload


if __name__ == "__main__":
    main()
