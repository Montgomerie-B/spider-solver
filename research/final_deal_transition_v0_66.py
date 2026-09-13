#!/usr/bin/env python3
"""v0.66: final-Deal transition-aware portfolio from the autonomous F2.

Canonical 172 is evaluation only after search.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal_preview import compact_preview, preview_next_deal
from spider.final_deal_transition import (
    CANDIDATE_CEILING,
    F2_G,
    INCUMBENT_G,
    TRANSITION_CATS,
    TRANSITION_HARVEST_CATS,
    V065_F3,
    V065_F4,
    V065_F5,
    V065_F6,
    choose_transition_verdict,
    reconstruct_v065_f2,
    search_transition_continuation,
    transition_share,
)
from spider.healthy_f2 import REMAINING_BUDGET, canonical_f2_snapshot, parse_stored_actions
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

EXPERIMENT = "final_deal_transition_v0_66"
BASE_SHA = "67becc47d919371671ecc664cbdd215d431d8761"
BRANCH = "agent/final-deal-transition-aware-v0-66"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "final_deal_transition_progress_v0_66.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_66.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_66.json"


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
            "legal_tableau",
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
        "deal_now_kept": ep.get("deal_now_kept"),
        "after_deal_unique": ep.get("after_deal_unique"),
        "stop_reason": ep.get("stop_reason"),
        "elapsed_s": ep.get("elapsed_s"),
        "alloc_s": ep.get("alloc_s"),
        "budget_left": None if ep.get("min_g") is None else CANDIDATE_CEILING - int(ep["min_g"]),
    }


def diagnose_limit(res, cheap: dict) -> str:
    f3 = cheap.get("3") or {}
    f3g = f3.get("g")
    post = next((ep for ep in res.epochs if ep.get("stock_rows") == 0), None)
    min_post = None if not post else post.get("min_g")
    max_f = int(res.max_foundations or 0)
    if max_f <= 2 and min_post is not None and int(min_post) <= F2_G + 5:
        return "coverage"
    if max_f <= 2 and res.stop_reason == "time limit":
        return "coverage"
    if f3g is not None and int(f3g) >= 180:
        return "structure"
    return "structure"


def next_recommendation(verdict: str) -> str:
    if verdict == "FINAL_DEAL_TRANSITION_COST_IMPROVED":
        return (
            "Promote the new autonomous incumbent and integrate the generic "
            "Deal-preview harvest carefully into whole-game optimisation."
        )
    if verdict == "FINAL_DEAL_TRANSITION_IMPROVES_CONVERSION":
        return (
            "Keep the F2 prefix. Next experiment is stock-empty assembly / cost-to-go "
            "on the improved post-SD5 states. Do not widen runtime."
        )
    if verdict == "FINAL_DEAL_TRANSITION_NO_USEFUL_STATE":
        return (
            "The g=130 F2 topology is already too damaged. Return earlier in the "
            "lineage and preserve consolidation before F2."
        )
    if verdict == "FINAL_DEAL_TRANSITION_SIGNAL_INVALID":
        return (
            "Drop reception/transition shaping and move directly to stock-empty "
            "structural assembly."
        )
    if verdict == "FINAL_DEAL_TRANSITION_COVERAGE_LIMITED":
        return "Do not widen runtime. Reallocate within the envelope or shrink portfolio width."
    if verdict == "FINAL_DEAL_TRANSITION_PROVENANCE_FAILURE":
        return "Stop until the v0.65 F2 prefix/digest verifies."
    if verdict == "FINAL_DEAL_TRANSITION_CONTRACT_FAILURE":
        return "Stop. Repair preview/search/accounting before any further experiment."
    return "Do not widen runtime. Do not copy canonical moves."


def assess_generality(p: dict) -> str:
    useful = bool(p.get("useful_transition"))
    if p.get("verdict") == "FINAL_DEAL_TRANSITION_SIGNAL_INVALID":
        return "WEAK_NOISY"
    if not useful:
        return "WEAK_AT_THIS_F2"
    if int((p.get("sd5") or {}).get("stock_rows") or 1) == 1:
        return "USEFUL_ONCE_EXCAVATION_MATURE_FINAL_DEAL"
    return "PLAUSIBLY_GENERAL"


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
        json.dumps(
            {k: (p.get("f2") or {}).get(k) for k in (
                "g", "stock_rows", "face_down", "foundations", "foundation_suits",
                "legal_tableau", "replay_ok", "n_actions", "n_deals",
            )},
            indent=2,
            sort_keys=True,
        ),
        "",
        "## Deal preview",
        "",
        json.dumps(p.get("immediate_deal") or {}, indent=2, sort_keys=True)[:4000],
        "",
        "## Portfolio",
        "",
        json.dumps(p.get("portfolio") or {}, indent=2, sort_keys=True)[:4000],
        "",
        "## Transition frontier",
        "",
        json.dumps(p.get("best_transition_roots") or [], indent=2, sort_keys=True)[:8000],
        "",
        "## Preparation vs benefit",
        "",
        json.dumps(p.get("prep_vs_benefit") or [], indent=2, sort_keys=True)[:8000],
        "",
        "## F3-F8 vs v0.65",
        "",
        json.dumps(p.get("frontier_vs_v065") or [], indent=2, sort_keys=True),
        "",
        "## Canonical preview (after search)",
        "",
        json.dumps(p.get("canonical_compare") or {}, indent=2, sort_keys=True)[:6000],
        "",
        "## Generality",
        "",
        p.get("generality", ""),
        "",
        "## Next recommendation",
        "",
        p.get("next_recommendation", ""),
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(str(x) for x in lines) + "\n", encoding="utf-8")


def _frontier(res) -> list:
    rows = []
    for n, rec in sorted(res.foundations_cheap.items()):
        rows.append(
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
                "legal": rec.get("legal_tableau"),
                "elapsed_s": rec.get("elapsed_s"),
            }
        )
    return rows


def _vs_v065(frontier: list) -> list:
    base = {3: V065_F3, 4: V065_F4, 5: V065_F5, 6: V065_F6, 7: None, 8: None}
    by_f = {int(r["F"]): r for r in frontier}
    out = []
    for f in range(3, 9):
        rec = by_f.get(f) or {}
        prev = base[f]
        g = rec.get("min_g")
        out.append(
            {
                "F": f,
                "v065_min_g": prev,
                "v066_min_g": g,
                "delta": None if g is None or prev is None else int(g) - int(prev),
                "fd": rec.get("fd"),
                "empty_n": rec.get("empty_n"),
                "boundaries": rec.get("boundaries"),
                "legal": rec.get("legal"),
                "elapsed_s": rec.get("elapsed_s"),
            }
        )
    return out


def main() -> dict:
    opening, _raw, _labels = load_opening()
    print("RECONSTRUCT v0.65 F2 from stored prefix", flush=True)
    recon = reconstruct_v065_f2(opening)
    if not recon.get("ok"):
        payload = {
            "experiment": EXPERIMENT,
            "base_sha": BASE_SHA,
            "branch": BRANCH,
            "provenance_fail": True,
            "debug": recon.get("debug") or recon.get("snap"),
            "verdict": "FINAL_DEAL_TRANSITION_PROVENANCE_FAILURE",
            "interpretation": recon.get("reason"),
            "next_recommendation": next_recommendation("FINAL_DEAL_TRANSITION_PROVENANCE_FAILURE"),
        }
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT FINAL_DEAL_TRANSITION_PROVENANCE_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    snap = recon["snap"]
    print(
        f"F2 ok g={snap['g']} fd={snap['face_down']} rows={snap['stock_rows']} "
        f"F={snap['foundations']} suits={snap['foundation_suits']} actions={snap['n_actions']}",
        flush=True,
    )
    f2_state = unpack_state(bytes.fromhex(snap["ordered_digest"]))
    control = preview_next_deal(f2_state, pre_g=F2_G, detail="full")
    print(
        f"PREFLIGHT immediate Deal rank_ok={control['rank_ok']} same_suit={control['same_suit']} "
        f"mixed={control['mixed']} legal {control['pre_legal']}->{control['legal_tableau']} "
        f"digest_ok={control['ok']}",
        flush=True,
    )
    clone = f2_state.clone()
    clone.deal()
    from spider.packed_state import pack_state

    assert control["post_digest"] == pack_state(clone).hex()
    assert pack_state(f2_state).hex() == snap["ordered_digest"]

    _write_json(
        PROG,
        {
            "f2_g": snap["g"],
            "f2_digest": snap["ordered_digest"],
            "immediate_deal": compact_preview(control),
            "phase": "preflight_ok",
        },
    )

    print("SEARCH F2 continuation transition-aware harvest ceiling=197 remaining=67 900s", flush=True)
    t0 = time.perf_counter()
    res = search_transition_continuation(opening=opening, recon=recon)
    print(
        f"DONE stop={res.stop_reason} unique={res.unique} expanded={res.expanded} "
        f"best={res.solution_g} maxF={res.max_foundations} minfd={res.min_face_down} t={res.elapsed_s:.1f}s",
        flush=True,
    )

    cheap = {str(k): slim_f(v) for k, v in sorted(res.foundations_cheap.items())}
    first = {str(k): slim_f(v) for k, v in sorted(res.foundations_first.items())}
    frontier = _frontier(res)
    vs = _vs_v065(frontier)
    tracker = getattr(res, "transition_tracker", None)
    selected = list(getattr(res, "transition_selected", None) or [])
    cat_counts = dict(getattr(res, "transition_cats", None) or {})
    sd5 = next((slim_epoch(ep) for ep in res.epochs if ep.get("stock_rows") == 1), None)
    if sd5 and sd5.get("portfolio_cats"):
        cat_counts = cat_counts or dict(sd5["portfolio_cats"])

    control_legal = int(control.get("legal_tableau") or 0)
    control_mixed = int(control.get("mixed") or 0)
    control_bounds = int(control.get("boundaries") or 0)
    prep_rows = []
    useful = False
    for row in selected:
        post = row.get("post") or {}
        prep = int(row.get("prep_delta_g") or 0)
        post_legal = post.get("legal_tableau")
        post_mixed = post.get("mixed")
        post_bounds = post.get("boundaries")
        legal_gain = None if post_legal is None else int(post_legal) - control_legal
        mixed_delta = None if post_mixed is None else control_mixed - int(post_mixed)
        bound_delta = None if post_bounds is None else control_bounds - int(post_bounds)
        modest = 0 < prep <= 20
        better = (legal_gain is not None and legal_gain >= 4) or (
            mixed_delta is not None and mixed_delta >= 2
        ) or (bound_delta is not None and bound_delta >= 4)
        if modest and better:
            useful = True
        prep_rows.append(
            {
                "cat": row.get("portfolio_cat"),
                "pre_g": (row.get("pre") or {}).get("g"),
                "prep_delta_g": prep,
                "post_g": post.get("post_g"),
                "post_legal": post_legal,
                "legal_gain_vs_control": legal_gain,
                "post_mixed": post_mixed,
                "mixed_improvement": mixed_delta,
                "post_boundaries": post_bounds,
                "boundary_improvement": bound_delta,
                "post_components": post.get("visible_components"),
                "rank_ok": post.get("rank_ok"),
                "same_suit": post.get("same_suit"),
                "best_suit": post.get("best_suit"),
            }
        )
    # also count tracker pool quality
    n_previewed = int(getattr(res, "n_previewed", 0) or 0)
    best_transition = sorted(
        [r for r in prep_rows if r.get("cat") in TRANSITION_CATS],
        key=lambda r: (
            -(r.get("legal_gain_vs_control") or -99),
            r.get("prep_delta_g") or 99,
        ),
    )[:12]
    if any((r.get("legal_gain_vs_control") or 0) >= 4 for r in best_transition):
        useful = True
    structure_improved = any(
        (r.get("legal_gain_vs_control") or 0) >= 4 or (r.get("boundary_improvement") or 0) >= 4
        for r in prep_rows
    )
    f3g = ((cheap.get("3") or {}).get("g"))
    f4g = ((cheap.get("4") or {}).get("g"))
    signal_invalid = bool(
        structure_improved
        and f3g is not None
        and int(f3g) > V065_F3
    )
    limit_mode = diagnose_limit(res, cheap)

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

    print("EVAL canonical F2 after search", flush=True)
    auto_state = unpack_state(bytes.fromhex(snap["ordered_digest"]))
    auto_deal = preview_next_deal(auto_state, pre_g=F2_G, detail="full")
    canon = canonical_f2_snapshot(opening)
    canon_state = unpack_state(bytes.fromhex(canon["ordered_digest"]))
    canon_deal = preview_next_deal(canon_state, pre_g=canon["g"], detail="full")

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
            "lanes": list(OP_LANES),
            "harvest_cats": list(TRANSITION_HARVEST_CATS),
            "base_harvest_cats": list(OP_HARVEST_CATS),
            "transition_cats": list(TRANSITION_CATS),
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
        "lanes": {
            "names": list(OP_LANES),
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
        "frontier_vs_v065": vs,
        "epochs": [slim_epoch(ep) for ep in res.epochs],
        "sd5": sd5,
        "post_stock": next((slim_epoch(ep) for ep in res.epochs if ep.get("stock_rows") == 0), None),
        "n_previewed": n_previewed,
        "immediate_deal": compact_preview(control),
        "immediate_deal_full": {
            "rank_ok": control.get("rank_ok"),
            "same_suit": control.get("same_suit"),
            "mixed": control.get("mixed"),
            "empty_land": control.get("empty_land"),
            "legal_before": control.get("pre_legal"),
            "legal_after": control.get("legal_tableau"),
            "boundaries": control.get("boundaries"),
            "components": control.get("visible_components"),
            "auto_foundations": control.get("auto_foundations"),
        },
        "portfolio": {
            "width": PORTFOLIO_WIDTH,
            "cats": cat_counts,
            "transition_share": transition_share(cat_counts, PORTFOLIO_WIDTH),
            "deal_now": cat_counts.get("deal_now"),
        },
        "transition_selected": selected[:64],
        "best_transition_roots": best_transition,
        "prep_vs_benefit": prep_rows[:64],
        "useful_transition": useful,
        "structure_improved": structure_improved,
        "signal_invalid": signal_invalid,
        "limit_mode": limit_mode,
        "canonical_f2": {
            k: canon.get(k)
            for k in (
                "g",
                "stock_rows",
                "face_down",
                "foundations",
                "foundation_suits",
                "legal_tableau",
                "visible_components",
                "empty_n",
            )
        },
        "canonical_deal": compact_preview(canon_deal),
        "canonical_compare": {
            "auto_pre_g": snap["g"],
            "canon_pre_g": canon["g"],
            "prep_delta": int(canon["g"]) - int(snap["g"]),
            "auto_rank_ok": auto_deal.get("rank_ok"),
            "canon_rank_ok": canon_deal.get("rank_ok"),
            "auto_same_suit": auto_deal.get("same_suit"),
            "canon_same_suit": canon_deal.get("same_suit"),
            "auto_mixed": auto_deal.get("mixed"),
            "canon_mixed": canon_deal.get("mixed"),
            "auto_post_legal": auto_deal.get("legal_tableau"),
            "canon_post_legal": canon_deal.get("legal_tableau"),
            "auto_post_boundaries": auto_deal.get("boundaries"),
            "canon_post_boundaries": canon_deal.get("boundaries"),
            "auto_post_components": auto_deal.get("visible_components"),
            "canon_post_components": canon_deal.get("visible_components"),
            "auto_post_best": auto_deal.get("best_suit"),
            "canon_post_best": canon_deal.get("best_suit"),
        },
        "best_state": slim_f(res.best_state or {}),
        "no_new_solution_if_not_improved": not improved,
    }
    if improved:
        payload["solution_file"] = str(FIX.relative_to(ROOT)).replace("\\", "/")
        payload["solution_actions"] = [
            list(a) if a != ("deal",) else ["deal"] for a in res.solution_actions
        ]
    verdict, interpretation = choose_transition_verdict(payload)
    payload["verdict"] = verdict
    payload["interpretation"] = interpretation
    payload["diagnosis"] = (
        "TRANSITION_SIGNAL_WRONG"
        if signal_invalid
        else "COVERAGE_LIMITED"
        if limit_mode == "coverage" and useful
        else "NO_USEFUL_TRANSITION_EXISTS"
        if not useful
        else "TRANSITION_IMPROVED_CONVERSION_NOT_ENOUGH"
    )
    payload["generality"] = assess_generality(payload)
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
            "frontier_vs_v065": vs,
            "portfolio": payload.get("portfolio"),
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
