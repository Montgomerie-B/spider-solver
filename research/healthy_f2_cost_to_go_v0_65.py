#!/usr/bin/env python3
"""v0.65: focused cost-to-go from the autonomous F2 at g=130.

Canonical 172 is evaluation only after search.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.healthy_f2 import (
    CANDIDATE_CEILING,
    F2_G,
    INCUMBENT_G,
    REMAINING_BUDGET,
    canonical_f2_snapshot,
    choose_f2_verdict,
    observe_deal,
    reconstruct_v064_f2,
    search_f2_continuation,
)
from spider.metrics import replay_actions
from spider.operational_policy import OP_HARVEST_CATS, OP_LANES
from spider.packed_state import unpack_state
from spider.research_actions import is_deal
from spider.solution_forensics import load_opening
from spider.whole_game_epoch_scheduler import (
    PORTFOLIO_WIDTH,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    save_solution,
)

EXPERIMENT = "healthy_f2_cost_to_go_v0_65"
BASE_SHA = "1a3fc6b30b3efdd66ff35f556df2485d39d008dd"
BRANCH = "agent/healthy-f2-cost-to-go-v0-65"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "healthy_f2_cost_to_go_progress_v0_65.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_65.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_65.json"


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


def slim_f(rec: dict) -> dict:
    if not rec:
        return {}
    return {
        k: rec.get(k)
        for k in (
            "g",
            "stock_rows",
            "face_down",
            "foundations",
            "foundation_suits",
            "empty_n",
            "n_ready",
            "cover",
            "best_ready_suit",
            "op_blockers",
            "k_min_blockers",
            "anchor_contention",
            "boundaries_total",
            "elapsed_s",
            "lineage",
        )
    }


def slim_epoch(ep: dict) -> dict:
    return {
        "stock_rows": ep.get("stock_rows"),
        "input_roots": ep.get("input_roots"),
        "lineage_roots": ep.get("lineage_roots"),
        "lineage_after_deal": ep.get("lineage_after_deal"),
        "unique": ep.get("unique"),
        "expanded": ep.get("expanded"),
        "generated": ep.get("generated"),
        "min_g": ep.get("min_g"),
        "max_g": ep.get("max_g"),
        "min_face_down": ep.get("min_face_down"),
        "max_foundations": ep.get("max_foundations"),
        "n_ready": ep.get("n_ready"),
        "lane_exp": ep.get("lane_exp"),
        "portfolio_cats": ep.get("portfolio_cats"),
        "after_deal_unique": ep.get("after_deal_unique"),
        "stop_reason": ep.get("stop_reason"),
        "elapsed_s": ep.get("elapsed_s"),
        "budget_left": None if ep.get("min_g") is None else CANDIDATE_CEILING - int(ep["min_g"]),
    }


def diagnose_limit(res, cheap: dict) -> str:
    f3 = cheap.get("3") or {}
    f3g = f3.get("g")
    post = next((ep for ep in res.epochs if ep.get("stock_rows") == 0), None)
    min_post = None if not post else post.get("min_g")
    max_f = int(res.max_foundations or 0)
    if f3g is not None and int(f3g) - F2_G <= 35:
        return "structure" if max_f < 8 else "structure"
    if max_f <= 2 and min_post is not None and int(min_post) <= F2_G + 5:
        return "coverage"
    if f3g is not None and int(f3g) >= 180:
        return "structure"
    if max_f <= 2 and res.stop_reason == "time limit":
        return "coverage"
    return "structure"


def next_recommendation(verdict: str) -> str:
    if verdict == "HEALTHY_F2_COST_IMPROVED":
        return "Promote the new autonomous incumbent and analyse the savings."
    if verdict == "HEALTHY_F2_CONVERTS_BUT_NOT_CHEAPER":
        return "Analyse the exact excess cost versus 198 before changing policy."
    if verdict == "HEALTHY_F2_COVERAGE_LIMITED":
        return "Change search allocation/algorithm rather than strategy. Do not copy 172."
    if verdict == "HEALTHY_F2_HEURISTIC_LIMITED":
        return "Use the F2 comparison to identify the missing ranking signal."
    if verdict == "HEALTHY_F2_STRUCTURE_LIMITED":
        return "Design one generic post-stock assembly/cost-to-go signal from the F2 comparison."
    if verdict == "HEALTHY_F2_PROVENANCE_FAILURE":
        return "Stop until the F2 path is stored with full_actions."
    return "Do not widen runtime. Do not copy canonical moves."


def write_report(p: dict) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("interpretation", ""),
        "",
        "## F2 reconstruction",
        "",
        json.dumps({k: (p.get("f2") or {}).get(k) for k in (
            "g", "stock_rows", "face_down", "foundations", "foundation_suits",
            "legal_tableau", "replay_ok", "n_actions", "n_deals",
        )}, indent=2, sort_keys=True),
        "",
        "## Continuation",
        "",
        json.dumps(
            {k: p.get(k) for k in (
                "elapsed_s", "unique", "expanded", "generated", "states_per_s",
                "stop_reason", "solution_g", "max_foundations", "min_face_down",
                "limit_mode",
            )},
            indent=2,
            sort_keys=True,
        ),
        "",
        "## Foundations",
        "",
        json.dumps(p.get("foundations"), indent=2, sort_keys=True)[:6000],
        "",
        "## Canonical F2 comparison",
        "",
        json.dumps(p.get("canonical_compare"), indent=2, sort_keys=True)[:6000],
        "",
        "## Next recommendation",
        "",
        p.get("next_recommendation", ""),
        "",
    ]
    REPORT.write_text("\n".join(str(x) for x in lines) + "\n", encoding="utf-8")


def main() -> dict:
    opening, _raw, _labels = load_opening()
    print("RECONSTRUCT v0.64 F2 from stored F1 prefix", flush=True)
    recon = reconstruct_v064_f2(opening)
    if not recon.get("ok"):
        payload = {
            "experiment": EXPERIMENT,
            "base_sha": BASE_SHA,
            "branch": BRANCH,
            "provenance_fail": True,
            "debug": recon.get("debug"),
            "verdict": "HEALTHY_F2_PROVENANCE_FAILURE",
            "interpretation": recon.get("reason"),
            "next_recommendation": next_recommendation("HEALTHY_F2_PROVENANCE_FAILURE"),
        }
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT HEALTHY_F2_PROVENANCE_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    snap = recon["snap"]
    print(
        f"F2 ok g={snap['g']} fd={snap['face_down']} rows={snap['stock_rows']} "
        f"F={snap['foundations']} suits={snap['foundation_suits']} actions={snap['n_actions']}",
        flush=True,
    )
    _write_json(
        PROG,
        {
            "f2_g": snap["g"],
            "f2_digest": snap["ordered_digest"],
            "reconstruct_s": recon.get("elapsed_s"),
            "reconstruct_stop": recon.get("stop_reason"),
        },
    )

    print("SEARCH F2 continuation ceiling=197 remaining=67 900s", flush=True)
    t0 = time.perf_counter()
    res = search_f2_continuation(opening=opening, recon=recon)
    print(
        f"DONE stop={res.stop_reason} unique={res.unique} expanded={res.expanded} "
        f"best={res.solution_g} maxF={res.max_foundations} minfd={res.min_face_down} t={res.elapsed_s:.1f}s",
        flush=True,
    )

    cheap = {str(k): slim_f(v) for k, v in sorted(res.foundations_cheap.items())}
    first = {str(k): slim_f(v) for k, v in sorted(res.foundations_first.items())}
    frontier = []
    for n, rec in sorted(res.foundations_cheap.items()):
        frontier.append(
            {
                "F": n,
                "min_g": rec.get("g"),
                "delta_from_f2": None if rec.get("g") is None else int(rec["g"]) - F2_G,
                "fd": rec.get("face_down"),
                "empty_n": rec.get("empty_n"),
                "rows": rec.get("stock_rows"),
                "suits": rec.get("foundation_suits"),
                "cover": rec.get("cover"),
                "boundaries": rec.get("boundaries_total"),
                "elapsed_s": rec.get("elapsed_s"),
            }
        )

    improved = (
        res.solved
        and res.replay_ok
        and res.solution_g is not None
        and int(res.solution_g) < INCUMBENT_G
        and res.solution_actions
    )
    replay_ok = bool(res.replay_ok)
    replay_g = res.replay_g
    if improved:
        save_solution(res.solution_actions, FIX, g=int(res.solution_g))
        end = opening.clone()
        replay_g = replay_actions(end, list(res.solution_actions))
        replay_ok = (
            replay_g == int(res.solution_g)
            and end.is_solved()
            and sum(1 for a in res.solution_actions if is_deal(a)) == 5
        )
        _write_json(
            META,
            {
                "g": res.solution_g,
                "prefix_g": F2_G,
                "replay_g": replay_g,
                "replay_ok": replay_ok,
                "path": str(FIX.relative_to(ROOT)).replace("\\", "/"),
                "branch": BRANCH,
                "base_sha": BASE_SHA,
            },
        )

    print("EVAL canonical F2 after search", flush=True)
    auto_state = unpack_state(bytes.fromhex(snap["ordered_digest"]))
    auto_deal = observe_deal(auto_state.clone(), F2_G)
    canon = canonical_f2_snapshot(opening)
    canon_state = unpack_state(bytes.fromhex(canon["ordered_digest"]))
    canon_deal = observe_deal(canon_state.clone(), canon["g"])

    diffs = []
    pairs = [
        ("legal_tableau", "mobility"),
        ("face_down", "excavation"),
        ("empty_n", "workspace"),
        ("same_suit_bonds", "bonds"),
        ("visible_components", "fragmentation"),
    ]
    for key, name in pairs:
        a, c = snap.get(key), canon.get(key)
        if isinstance(a, (int, float)) and isinstance(c, (int, float)):
            diffs.append(
                {
                    "name": name,
                    "auto": a,
                    "canon": c,
                    "delta_auto_minus_canon": a - c,
                    "policy_measures": name in ("excavation", "workspace", "mobility", "fragmentation"),
                    "genericity": "PLAUSIBLY_GENERAL",
                }
            )
    for suit in ("h", "c"):
        av = (snap.get("by_suit") or {}).get(suit) or {}
        cv = (canon.get("by_suit") or {}).get(suit) or {}
        for k in ("cover", "relevant_blockers", "k_len", "a_len", "gap", "anchor_contention"):
            a, c = av.get(k), cv.get(k)
            if a is None and c is None:
                continue
            diffs.append(
                {
                    "name": f"{suit}_{k}",
                    "auto": a,
                    "canon": c,
                    "policy_measures": True,
                    "genericity": "PLAUSIBLY_GENERAL",
                }
            )

    limit_mode = diagnose_limit(res, cheap)
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "policy_reads_canonical": False,
        "f2": snap,
        "f2_prefix_actions": recon["root"]["full_actions"],
        "f2_digest": snap["ordered_digest"],
        "reconstruct_s": recon.get("elapsed_s"),
        "reconstruct_stop": recon.get("stop_reason"),
        "envelope": {
            "time_s": SEARCH_TIME_S,
            "unique": SEARCH_UNIQUE,
            "rss_abort_mb": SEARCH_RSS_MB,
            "candidate_ceiling": CANDIDATE_CEILING,
            "remaining_budget": REMAINING_BUDGET,
            "prefix_g": F2_G,
            "portfolio_width": PORTFOLIO_WIDTH,
            "lanes": list(OP_LANES),
            "harvest_cats": list(OP_HARVEST_CATS),
        },
        "elapsed_s": res.elapsed_s,
        "wall_s": time.perf_counter() - t0,
        "peak_rss_mb": res.peak_rss_mb,
        "unique": res.unique,
        "expanded": res.expanded,
        "generated": res.generated,
        "stale_skips": res.stale_skips,
        "duplicate_skips": res.duplicate_skips,
        "states_per_s": res.states_per_s,
        "stop_reason": res.stop_reason,
        "min_g": res.min_g,
        "max_g": res.max_g,
        "lanes": {"names": list(OP_LANES), "pops": res.lane_pops, "expansions": res.lane_exp, "stale": res.lane_stale},
        "incumbent_g": INCUMBENT_G,
        "solved": res.solved,
        "solution_g": res.solution_g,
        "replay_ok": replay_ok,
        "replay_g": replay_g,
        "accounting_fail": res.accounting_fail,
        "max_foundations": res.max_foundations,
        "min_face_down": res.min_face_down,
        "foundations": {"first": first, "cheap": cheap},
        "frontier": frontier,
        "epochs": [slim_epoch(ep) for ep in res.epochs],
        "sd5": next((slim_epoch(ep) for ep in res.epochs if ep.get("stock_rows") == 1), None),
        "post_stock": next((slim_epoch(ep) for ep in res.epochs if ep.get("stock_rows") == 0), None),
        "f2_deal": auto_deal,
        "canonical_f2": canon,
        "canonical_deal": canon_deal,
        "canonical_compare": {
            "auto_g": snap["g"],
            "canon_g": canon["g"],
            "auto_fd": snap["face_down"],
            "canon_fd": canon["face_down"],
            "auto_rows": snap["stock_rows"],
            "canon_rows": canon["stock_rows"],
            "auto_F": snap["foundations"],
            "canon_F": canon["foundations"],
            "auto_suits": snap["foundation_suits"],
            "canon_suits": canon["foundation_suits"],
            "auto_legal": snap["legal_tableau"],
            "canon_legal": canon["legal_tableau"],
            "auto_boundaries": (snap.get("interference") or {}).get("boundaries_total"),
            "canon_boundaries": (canon.get("interference") or {}).get("boundaries_total"),
            "deal_auto": {k: auto_deal.get(k) for k in ("rank_ok", "same_suit_land", "mixed_block", "legal_after")},
            "deal_canon": {k: canon_deal.get(k) for k in ("rank_ok", "same_suit_land", "mixed_block", "legal_after")},
        },
        "structural_diffs": diffs,
        "limit_mode": limit_mode,
        "best_state": res.best_state,
        "best_readiness": res.best_readiness,
        "no_new_solution_if_not_improved": not improved,
    }
    if improved:
        payload["solution_file"] = str(FIX.relative_to(ROOT)).replace("\\", "/")
        payload["solution_actions"] = recon["root"]["full_actions"]  # placeholder overwritten below
        payload["solution_actions"] = [list(a) if a != ("deal",) else ["deal"] for a in res.solution_actions]
    verdict, interpretation = choose_f2_verdict(payload)
    payload["verdict"] = verdict
    payload["interpretation"] = interpretation
    payload["next_recommendation"] = next_recommendation(verdict)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    _write_json(
        PROG,
        {
            "f2_digest": payload.get("f2_digest"),
            "epochs": payload.get("epochs"),
            "foundations_cheap": cheap,
            "frontier": frontier,
            "solution_g": payload.get("solution_g"),
            "stop_reason": payload.get("stop_reason"),
        },
    )
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
