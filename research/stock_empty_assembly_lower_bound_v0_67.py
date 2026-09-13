#!/usr/bin/env python3
"""v0.67: admissible stock-empty assembly cost-to-go from the autonomous F2.

Canonical 172 is evaluation only after search.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.assembly_lower_bound import assembly_bound_detail, assembly_lb
from spider.assembly_policy import (
    CANDIDATE_CEILING,
    COMPLETION_LANES,
    V066_F3,
    V066_F4,
    V066_F5,
    V066_F6,
    V066_F7,
    choose_assembly_verdict,
    search_assembly_continuation,
)
from spider.deal_preview import compact_preview, preview_next_deal
from spider.final_deal_transition import (
    F2_G,
    INCUMBENT_G,
    TRANSITION_HARVEST_CATS,
    reconstruct_v065_f2,
    transition_share,
)
from spider.healthy_f2 import REMAINING_BUDGET, canonical_f2_snapshot, parse_stored_actions
from spider.metrics import parse_moves_file, replay_actions
from spider.operational_policy import OP_HARVEST_CATS, OP_LANES
from spider.packed_state import pack_state, unpack_state
from spider.research_actions import apply_action, is_deal, step_cost, stock_rows
from spider.solution_forensics import load_opening
from spider.whole_game_epoch_scheduler import (
    PORTFOLIO_WIDTH,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    save_solution,
)

EXPERIMENT = "stock_empty_assembly_lower_bound_v0_67"
BASE_SHA = "9551e0cfe6e87d6627995fe14db79ca67243e6ae"
BRANCH = "agent/stock-empty-assembly-lower-bound-v0-67"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "stock_empty_assembly_progress_v0_67.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_67.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_67.json"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
INCUMBENT = ROOT / "solutions" / "4925153_autonomous_v0_59.moves"


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
    by = rec.get("assembly_by_suit") or {}
    return {
        "g": rec.get("g"),
        "stock_rows": rec.get("stock_rows"),
        "face_down": rec.get("face_down"),
        "foundations": rec.get("foundations"),
        "foundation_suits": rec.get("foundation_suits"),
        "empty_n": rec.get("empty_n"),
        "legal_tableau": rec.get("legal_tableau"),
        "boundaries_total": rec.get("boundaries_total"),
        "best_ready_suit": rec.get("best_ready_suit"),
        "cover": rec.get("cover"),
        "assembly_h": rec.get("assembly_h"),
        "assembly_f": rec.get("assembly_f"),
        "assembly_slack": rec.get("assembly_slack"),
        "assembly_u": rec.get("assembly_u"),
        "copies_remaining": rec.get("copies_remaining"),
        "assembly_by_suit": by,
        "elapsed_s": rec.get("elapsed_s"),
        "lineage": rec.get("lineage"),
    }


def slim_epoch(ep: dict) -> dict:
    return {
        "stock_rows": ep.get("stock_rows"),
        "input_roots": ep.get("input_roots"),
        "unique": ep.get("unique"),
        "expanded": ep.get("expanded"),
        "generated": ep.get("generated"),
        "min_g": ep.get("min_g"),
        "max_g": ep.get("max_g"),
        "max_foundations": ep.get("max_foundations"),
        "min_face_down": ep.get("min_face_down"),
        "lane_exp": ep.get("lane_exp"),
        "portfolio_cats": ep.get("portfolio_cats"),
        "deal_now_kept": ep.get("deal_now_kept"),
        "after_deal_unique": ep.get("after_deal_unique"),
        "lower_bound_prunes": ep.get("lower_bound_prunes"),
        "lower_bound_calls": ep.get("lower_bound_calls"),
        "lower_bound_s": ep.get("lower_bound_s"),
        "min_h": ep.get("min_h"),
        "max_h": ep.get("max_h"),
        "min_f": ep.get("min_f"),
        "prunes_by_F": ep.get("prunes_by_F"),
        "stop_reason": ep.get("stop_reason"),
        "elapsed_s": ep.get("elapsed_s"),
        "alloc_s": ep.get("alloc_s"),
    }


def route_bound_scan(opening, actions, total_g) -> dict:
    st = opening.clone()
    g = 0
    n = 0
    violations = 0
    max_h = 0
    min_slack = None
    first_empty_g = None
    for action in actions:
        if stock_rows(st) == 0:
            if first_empty_g is None:
                first_empty_g = g
            h = assembly_lb(st)
            remain = int(total_g) - g
            n += 1
            max_h = max(max_h, h)
            if h > remain:
                violations += 1
            slack = remain - h
            min_slack = slack if min_slack is None else min(min_slack, slack)
        cost = 1 if is_deal(action) else step_cost(st, action)
        apply_action(st, action)
        g += cost
    return {
        "n_stock_empty_states": n,
        "violations": violations,
        "max_h": max_h,
        "min_slack": min_slack,
        "first_empty_g": first_empty_g,
        "terminal_g": g,
        "admissible_on_route": violations == 0,
    }


def next_recommendation(verdict: str) -> str:
    if verdict == "ASSEMBLY_BOUND_COST_IMPROVED":
        return "Promote the new autonomous incumbent and return to whole-game optimisation."
    if verdict == "ASSEMBLY_BOUND_FINDS_F8_AT_CEILING":
        return "Inspect the F8 accounting; do not widen runtime."
    if verdict == "ASSEMBLY_BOUND_IMPROVES_COMPLETION_FRONTIER":
        return (
            "Strengthen the admissible stock-empty lower bound or add a non-admissible "
            "secondary assembly heuristic. Do not widen runtime."
        )
    if verdict == "ASSEMBLY_BOUND_PRUNES_DEAD_ENDS_NO_SOLUTION":
        return (
            "Recover v0.66 Deal-preview performance before further strategy changes. "
            "Do not widen runtime."
        )
    if verdict == "ASSEMBLY_BOUND_TOO_WEAK":
        return "Investigate a stronger duplicate-aware/disjoint assembly lower bound."
    if verdict == "ASSEMBLY_BOUND_INVALID":
        return "Remove proof-pruning immediately. Retain telemetry only."
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
            "legal_tableau", "replay_ok", "n_actions",
        )}, indent=2, sort_keys=True),
        "",
        "## Envelope and bound performance",
        "",
        json.dumps(p.get("envelope") or {}, indent=2, sort_keys=True),
        "",
        json.dumps(p.get("bound_perf") or {}, indent=2, sort_keys=True),
        "",
        "## Portfolio (v0.66 harvest frozen)",
        "",
        json.dumps(p.get("portfolio") or {}, indent=2, sort_keys=True)[:4000],
        "",
        "## F3-F8 with h/f/slack",
        "",
        json.dumps(p.get("frontier_vs_v066") or [], indent=2, sort_keys=True),
        "",
        "## v0.66 F7 infeasibility",
        "",
        json.dumps(p.get("v066_milestones") or {}, indent=2, sort_keys=True)[:4000],
        "",
        "## Canonical stock-empty bound (after search)",
        "",
        json.dumps(p.get("canonical_route_bound") or {}, indent=2, sort_keys=True),
        "",
        "## Next recommendation",
        "",
        p.get("next_recommendation", ""),
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(str(x) for x in lines) + "\n", encoding="utf-8")


def main() -> dict:
    opening, _raw, _labels = load_opening()
    print("RECONSTRUCT v0.65/v0.66 F2 from stored prefix", flush=True)
    recon = reconstruct_v065_f2(opening)
    if not recon.get("ok"):
        payload = {
            "experiment": EXPERIMENT,
            "base_sha": BASE_SHA,
            "branch": BRANCH,
            "provenance_fail": True,
            "verdict": "ASSEMBLY_BOUND_CONTRACT_FAILURE",
            "interpretation": recon.get("reason"),
            "next_recommendation": next_recommendation("ASSEMBLY_BOUND_CONTRACT_FAILURE"),
        }
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT ASSEMBLY_BOUND_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    snap = recon["snap"]
    print(
        f"F2 ok g={snap['g']} fd={snap['face_down']} rows={snap['stock_rows']} "
        f"F={snap['foundations']} digest={snap['ordered_digest'][:24]}",
        flush=True,
    )
    f2_state = unpack_state(bytes.fromhex(snap["ordered_digest"]))
    assert pack_state(f2_state).hex() == snap["ordered_digest"]
    assert assembly_lb(f2_state) == 0

    _write_json(PROG, {"f2_g": snap["g"], "f2_digest": snap["ordered_digest"], "phase": "preflight_ok"})

    print("SEARCH F2 continuation assembly-lb COMPLETION ceiling=197 900s", flush=True)
    t0 = time.perf_counter()
    res = search_assembly_continuation(opening=opening, recon=recon)
    print(
        f"DONE stop={res.stop_reason} unique={res.unique} expanded={res.expanded} "
        f"best={res.solution_g} maxF={res.max_foundations} prunes={res.lower_bound_prunes} "
        f"t={res.elapsed_s:.1f}s",
        flush=True,
    )

    cheap = {str(k): slim_f(v) for k, v in sorted(res.foundations_cheap.items())}
    first = {str(k): slim_f(v) for k, v in sorted(res.foundations_first.items())}
    frontier = []
    vs = []
    base = {3: V066_F3, 4: V066_F4, 5: V066_F5, 6: V066_F6, 7: V066_F7, 8: None}
    for n, rec in sorted(res.foundations_cheap.items()):
        g = rec.get("g")
        h = rec.get("assembly_h")
        if h is None and rec.get("ordered_digest") and int(rec.get("stock_rows") or 0) == 0:
            st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
            info = assembly_bound_detail(st)
            h = info["h"]
            rec = dict(rec)
            rec["assembly_h"] = h
            rec["assembly_f"] = int(g) + h
            rec["assembly_slack"] = CANDIDATE_CEILING - (int(g) + h)
            rec["assembly_by_suit"] = {
                suit: {"m": row.get("m"), "u": row.get("u"), "suit_lb": row.get("suit_lb")}
                for suit, row in info["by_suit"].items()
            }
            cheap[str(n)] = slim_f(rec)
        fval = rec.get("assembly_f")
        slack = rec.get("assembly_slack")
        row = {
            "F": n,
            "g": g,
            "h": h,
            "f": fval,
            "slack": slack,
            "fd": rec.get("face_down"),
            "empty_n": rec.get("empty_n"),
            "legal": rec.get("legal_tableau"),
            "boundaries": rec.get("boundaries_total"),
            "best_suit": rec.get("best_ready_suit"),
            "copies_remaining": rec.get("copies_remaining"),
            "by_suit": rec.get("assembly_by_suit"),
            "elapsed_s": rec.get("elapsed_s"),
            "proof_infeasible": None if slack is None else int(slack) < 0,
        }
        frontier.append(row)
        prev = base.get(int(n))
        vs.append(
            {
                "F": n,
                "v066_min_g": prev,
                "v067_min_g": g,
                "delta": None if g is None or prev is None else int(g) - int(prev),
                "h": h,
                "f": fval,
                "slack": slack,
                "proof_infeasible": row["proof_infeasible"],
            }
        )

    cat_counts = dict(getattr(res, "transition_cats", None) or {})
    sd5 = next((slim_epoch(ep) for ep in res.epochs if ep.get("stock_rows") == 1), None)
    post = next((slim_epoch(ep) for ep in res.epochs if ep.get("stock_rows") == 0), None)
    if sd5 and sd5.get("portfolio_cats"):
        cat_counts = cat_counts or dict(sd5["portfolio_cats"])

    generated = int(res.generated or 0)
    prunes = int(res.lower_bound_prunes or 0)
    post_gen = int((post or {}).get("generated") or 0)
    post_prunes = int((post or {}).get("lower_bound_prunes") or 0)
    frac = 0.0 if post_gen <= 0 else post_prunes / float(post_gen)

    f7 = next((r for r in frontier if int(r["F"]) == 7), None)
    f6 = next((r for r in frontier if int(r["F"]) == 6), None)
    v066_f7 = {
        "reported_g": V066_F7,
        "reported_cover": 4,
        "synthetic_u4_m1_h": 3,
        "synthetic_f": 199,
        "synthetic_slack": 197 - 199,
        "proof_infeasible_under_197": True,
        "reconstructable_from_v066_json": False,
        "note": "v0.66 slim artefacts dropped full_actions/digest; cover=4 implies u>=4, h>=3, f>=199.",
    }
    if f7 and f7.get("h") is not None:
        v066_f7["v067_observed_f7"] = f7

    completion_improved = False
    if f7 and f7.get("g") is not None and int(f7["g"]) < V066_F7:
        completion_improved = True
    if any(int(r["F"]) == 8 for r in frontier):
        completion_improved = True
    if f7 and f7.get("slack") is not None and int(f7["slack"]) >= 0:
        completion_improved = True

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
            and len(end.foundations) == 8
            and not end.stock
            and all(c.is_empty() for c in end.columns)
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

    print("EVAL canonical F2 and stock-empty bound after search", flush=True)
    canon = canonical_f2_snapshot(opening)
    canon_state = unpack_state(bytes.fromhex(canon["ordered_digest"]))
    canon_deal = preview_next_deal(canon_state, pre_g=canon["g"], detail="full")
    auto_deal = preview_next_deal(f2_state, pre_g=F2_G, detail="full")
    canon_actions = parse_moves_file(CANON)
    inc_actions = parse_moves_file(INCUMBENT)
    canon_scan = route_bound_scan(opening, canon_actions, 172)
    auto_scan = route_bound_scan(opening, inc_actions, 198)

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "policy_reads_canonical": False,
        "f2": snap,
        "f2_prefix_actions": recon["root"]["full_actions"],
        "f2_digest": snap["ordered_digest"],
        "envelope": {
            "time_s": SEARCH_TIME_S,
            "unique": SEARCH_UNIQUE,
            "rss_abort_mb": SEARCH_RSS_MB,
            "candidate_ceiling": CANDIDATE_CEILING,
            "remaining_budget": REMAINING_BUDGET,
            "prefix_g": F2_G,
            "portfolio_width": PORTFOLIO_WIDTH,
            "lanes": list(COMPLETION_LANES),
            "base_lanes": list(OP_LANES),
            "harvest_cats": list(TRANSITION_HARVEST_CATS),
            "base_harvest_cats": list(OP_HARVEST_CATS),
        },
        "elapsed_s": res.elapsed_s,
        "wall_s": time.perf_counter() - t0,
        "peak_rss_mb": res.peak_rss_mb,
        "unique": res.unique,
        "expanded": res.expanded,
        "generated": res.generated,
        "states_per_s": res.states_per_s,
        "stop_reason": res.stop_reason,
        "min_g": res.min_g,
        "max_g": res.max_g,
        "lanes": {
            "names": list(COMPLETION_LANES),
            "pops": res.lane_pops,
            "expansions": res.lane_exp,
            "stale": res.lane_stale,
        },
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
        "frontier_vs_v066": vs,
        "epochs": [slim_epoch(ep) for ep in res.epochs],
        "sd5": sd5,
        "post_stock": post,
        "n_previewed": getattr(res, "n_previewed", 0),
        "portfolio": {
            "width": PORTFOLIO_WIDTH,
            "cats": cat_counts,
            "transition_share": transition_share(cat_counts, PORTFOLIO_WIDTH),
            "deal_now": cat_counts.get("deal_now"),
            "frozen_v066": True,
        },
        "bound_perf": {
            "calls": res.lower_bound_calls,
            "seconds": res.lower_bound_s,
            "avg_us": None
            if not res.lower_bound_calls
            else 1e6 * float(res.lower_bound_s) / float(res.lower_bound_calls),
            "prunes": prunes,
            "generated": generated,
            "post_stock_generated": post_gen,
            "post_stock_prunes": post_prunes,
            "post_stock_prune_fraction": frac,
            "min_h": res.min_h,
            "max_h": res.max_h,
            "min_f": res.min_f,
            "prunes_by_F": dict(res.prunes_by_F or {}),
            "v066_exp_per_s": 12.1,
            "v067_exp_per_s": res.states_per_s,
        },
        "v066_milestones": {
            "f7": v066_f7,
            "f6": f6,
            "f7_now": f7,
        },
        "completion_frontier_improved": completion_improved,
        "lower_bound_prunes": prunes,
        "generated": generated,
        "immediate_deal": compact_preview(auto_deal),
        "canonical_f2": {
            k: canon.get(k)
            for k in (
                "g",
                "stock_rows",
                "face_down",
                "foundations",
                "legal_tableau",
            )
        },
        "canonical_deal": compact_preview(canon_deal),
        "canonical_route_bound": canon_scan,
        "autonomous_198_route_bound": auto_scan,
        "bound_invalid": (not canon_scan["admissible_on_route"]) or (not auto_scan["admissible_on_route"]),
        "no_new_solution_if_not_improved": not improved,
    }
    if improved:
        payload["solution_file"] = str(FIX.relative_to(ROOT)).replace("\\", "/")
        payload["solution_actions"] = [
            list(a) if a != ("deal",) else ["deal"] for a in res.solution_actions
        ]
    verdict, interpretation = choose_assembly_verdict(payload)
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
            "frontier_vs_v066": vs,
            "bound_perf": payload.get("bound_perf"),
            "solution_g": payload.get("solution_g"),
            "stop_reason": payload.get("stop_reason"),
            "verdict": verdict,
        },
    )
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
