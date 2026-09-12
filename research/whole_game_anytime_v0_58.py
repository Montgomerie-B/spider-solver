#!/usr/bin/env python3
"""v0.58: autonomous whole-game anytime baseline from the opening deal.

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

from spider.metrics import CANONICAL_MOBILITYWARE_MOVES, replay_actions
from spider.research_actions import face_down_count, is_deal, stock_rows
from spider.whole_game_anytime import (
    COST_CEILING,
    LANES,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    choose_verdict,
    opening_state,
    save_solution,
    search_whole_game,
)

EXPERIMENT = "whole_game_anytime_v0_58"
BASE_SHA = "58e29f86654bbb0ad6943923ad663222f999f50b"
BRANCH = "agent/whole-game-anytime-baseline-v0-58"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "whole_game_progress_v0_58.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_58.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_58.json"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
HIST_F1_G = 21
CANONICAL_G = CANONICAL_MOBILITYWARE_MOVES


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
    if verdict == "WHOLE_GAME_AUTONOMOUS_SOLVE":
        return "Stay on the whole-game path and begin move-count optimisation of autonomous solutions."
    if verdict == "WHOLE_GAME_REACHES_F2_OR_BEYOND":
        return "Stay on the whole-game path and improve the scheduler using the observed late-game bottleneck."
    if verdict == "WHOLE_GAME_REDISCOVERS_F1_ONLY":
        return "Stay on the whole-game path and improve cross-epoch/foundation coordination."
    if verdict == "WHOLE_GAME_PROGRESS_NO_FOUNDATION":
        return "Stay on the whole-game path and address early scheduler diversity and scoring performance."
    if verdict == "WHOLE_GAME_CONTRACT_FAILURE":
        return "Stop solver work until the contract failure is diagnosed; do not open a new excavation."
    return "Stay on the whole-game path and address early scheduler diversity/performance. Do not target the historical F1 path."


def write_report(payload: dict) -> None:
    f1 = (payload.get("foundations") or {}).get("first") or {}
    f1_1 = f1.get("1") or {}
    f2 = f1.get("2") or {}
    best = payload.get("best_state") or {}
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{payload.get('verdict')}`",
        "",
        payload.get("interpretation", ""),
        "",
        "## Envelope",
        "",
        f"- time: {SEARCH_TIME_S}s",
        f"- unique: {SEARCH_UNIQUE}",
        f"- RSS abort: {SEARCH_RSS_MB} MB",
        f"- cost ceiling: {COST_CEILING}",
        "",
        "## Identity",
        "",
        "SPK1 ordered `pack_state` while stock remains; SPS1 `pack_post_stock_symmetry_state` after stock is empty.",
        "",
        "## Lanes",
        "",
        ", ".join(LANES),
        "",
        "## Totals",
        "",
        f"- elapsed_s: {payload.get('elapsed_s')}",
        f"- peak_rss_mb: {payload.get('peak_rss_mb')}",
        f"- unique: {payload.get('unique')}",
        f"- expanded: {payload.get('expanded')}",
        f"- generated: {payload.get('generated')}",
        f"- duplicate_skips: {payload.get('duplicate_skips')}",
        f"- stale_skips: {payload.get('stale_skips')}",
        f"- states_per_s: {payload.get('states_per_s')}",
        f"- stop_reason: {payload.get('stop_reason')}",
        f"- min_g / max_g: {payload.get('min_g')} / {payload.get('max_g')}",
        f"- max_foundations: {payload.get('max_foundations')}",
        f"- min_face_down: {payload.get('min_face_down')}",
        "",
        "## Foundation milestones",
        "",
        f"- F1 first: {f1_1}",
        f"- F2 first: {f2}",
        "",
        "## Best state",
        "",
        json.dumps(best, indent=2, sort_keys=True),
        "",
        "## Solution",
        "",
        f"- solved: {payload.get('solved')}",
        f"- solution_g: {payload.get('solution_g')}",
        f"- replay_ok: {payload.get('replay_ok')}",
        "",
        "## After-the-run comparison (evaluation only)",
        "",
        f"- historical machine F1 g={HIST_F1_G}",
        f"- canonical complete trace g={CANONICAL_G}",
        "- v0.56 did not reach F2 from the post-SD5/F1 line",
        "- 119 is not the current optimisation target",
        "",
        "## Next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    opening_fd = face_down_count(opening)
    print(
        f"OPENING stock_rows={stock_rows(opening)} fd={opening_fd} "
        f"foundations={len(opening.foundations)}",
        flush=True,
    )
    t0 = time.perf_counter()
    res = search_whole_game()
    print(
        f"DONE stop={res.stop_reason} unique={res.unique} expanded={res.expanded} "
        f"max_f={res.max_foundations} solved={res.solved} t={res.elapsed_s:.1f}s",
        flush=True,
    )
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
        "min_live_g": res.min_live_g,
        "closed_g": res.closed_g,
        "incumbent": res.incumbent,
        "lanes": {
            "names": list(LANES),
            "pops": res.lane_pops,
            "expansions": res.lane_exp,
            "stale": res.lane_stale,
        },
        "envelope": {
            "time_s": SEARCH_TIME_S,
            "unique": SEARCH_UNIQUE,
            "rss_abort_mb": SEARCH_RSS_MB,
            "cost_ceiling": COST_CEILING,
        },
        "identity": "SPK1 while stock remains; SPS1 after stock empty",
        "solved": res.solved,
        "solution_g": res.solution_g,
        "replay_ok": res.replay_ok,
        "replay_g": res.replay_g,
        "accounting_fail": res.accounting_fail,
        "max_foundations": res.max_foundations,
        "min_face_down": res.min_face_down,
        "max_empty": res.max_empty,
        "opening_face_down": opening_fd,
        "opening_stock_rows": stock_rows(opening),
        "foundations": {
            "first": {str(k): v for k, v in sorted(res.foundations_first.items())},
            "cheap": {str(k): v for k, v in sorted(res.foundations_cheap.items())},
        },
        "epochs": {str(k): v for k, v in sorted(res.epochs.items())},
        "best_construction": res.best_construction,
        "best_state": res.best_state,
        "production_unchanged": True,
        "canonical_g_eval_only": CANONICAL_G,
        "historical_f1_g_eval_only": HIST_F1_G,
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
                    "n_actions": len(res.solution_actions),
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
            "foundations_first": payload.get("foundations", {}).get("first"),
            "foundations_cheap": payload.get("foundations", {}).get("cheap"),
            "epochs": payload.get("epochs"),
            "best_state": payload.get("best_state"),
            "max_foundations": payload.get("max_foundations"),
            "min_face_down": payload.get("min_face_down"),
            "stop_reason": payload.get("stop_reason"),
        },
    )
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"WROTE {RESULT}", flush=True)
    return payload


if __name__ == "__main__":
    main()
