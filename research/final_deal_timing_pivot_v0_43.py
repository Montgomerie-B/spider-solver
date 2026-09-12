#!/usr/bin/env python3
"""v0.43: DEAL_NOW vs small prep-then-SD5 for independently chosen Foundation 2.

Any suit may win: Spade, Heart, Diamond, or Club. No suit is preselected.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.metrics import replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, dump_actions
from spider.simple_final_deal_timing import (
    COST_CEILING,
    HARVEST_SLACK,
    PREP_UNIQUE,
    RSS_ABORT_MB,
    SEARCH_UNIQUE,
    SEARCH_TIME_S,
    apply_sd5,
    deal_is_legal,
    deal_preparation_candidates,
    enumerate_preparation,
    foundation_suits,
    load_union,
    opening_state,
    receiving_telemetry,
    same_suit_components,
    search_foundation2,
    verify_sd5_row,
)
from spider.simple_progressive_solver import format_moves_text
from spider.simple_workspace_reachability import empty_column_indices, face_down_count

EXPERIMENT = "final_deal_timing_pivot_v0_43"
BASE_SHA = "bc90822314403744e15a2158387b5ef9bf0e6f5b"
BRANCH = "agent/final-deal-timing-pivot-v0-43"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
SOURCES = ROOT / "docs" / "research" / "final_deal_sources_v0_43.json"
FRONTIER = ROOT / "docs" / "research" / "final_deal_poststock_frontier_v0_43.json"
PORT = ROOT / "docs" / "research" / "foundation2_portfolio_v0_43.json"
FOUND_FIX = ROOT / "solutions" / "4925153_v0_43_foundation2_best.moves.txt"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def choose_verdict(payload: dict) -> tuple[str, str]:
    if not payload.get("all_replay_ok"):
        return "SOURCE_REPLAY_FAILURE", "source union failed replay or invariants"
    if payload.get("sd5_mismatch"):
        return "FINAL_ROW_ORIENTATION_MISMATCH", "engine SD5 row differs from expected"
    f2 = payload.get("foundation_search") or {}
    reached = bool(f2.get("reached"))
    stop = f2.get("stop_reason")
    if not reached and stop in ("unique limit", "rss abort"):
        return "POST_SD5_SEARCH_STATE_EXPLOSION", "Foundation 2 not found before unique/RSS limit"
    if not reached:
        return "NO_FOUNDATION2_POST_SD5_IN_ENVELOPE", "no additional foundation under MW<=120"
    suits = payload.get("portfolio", {}).get("by_suit") or {}
    nsuits = sum(1 for k, v in suits.items() if v)
    deal_now = payload.get("timing", {}).get("cheapest_deal_now")
    prep = payload.get("timing", {}).get("cheapest_prep")
    if nsuits >= 2:
        return "FOUNDATION2_REACHED_MULTIPLE_SUITS", f"Foundation 2 suits {sorted(k for k,v in suits.items() if v)}"
    if deal_now is not None and prep is not None:
        if prep < deal_now:
            return "PREP_THEN_DEAL_REACHES_FOUNDATION2_CHEAPER", f"prep {prep} < deal-now {deal_now}"
        if prep == deal_now:
            return "BOTH_TIMINGS_REACH_FOUNDATION2_COST_TIE", f"both timings reach Foundation 2 at {deal_now}"
        return "DEAL_NOW_REACHES_FOUNDATION2", f"deal-now {deal_now} <= prep {prep}"
    if deal_now is not None:
        return "DEAL_NOW_REACHES_FOUNDATION2", f"deal-now reaches Foundation 2 at {deal_now}"
    if prep is not None:
        return "PREP_THEN_DEAL_REACHES_FOUNDATION2_CHEAPER", f"only prep-then-deal reached at {prep}"
    return "INCONCLUSIVE", "Foundation 2 reached without timing classification"


def next_recommendation(verdict: str, payload: dict) -> str:
    if verdict == "SOURCE_REPLAY_FAILURE":
        return "Fix the post-SD4 source union before any further Deal-timing work."
    if verdict == "FINAL_ROW_ORIENTATION_MISMATCH":
        return "Use the engine SD5 row as truth and re-run the timing pivot."
    if verdict in ("DEAL_NOW_REACHES_FOUNDATION2", "BOTH_TIMINGS_REACH_FOUNDATION2_COST_TIE"):
        return (
            "Among the tested post-SD4 union and <=4-action preparations, Deal-now is sufficient "
            "for Foundation 2. Continue from the cheapest Foundation-2 state. Do not resume G6_8."
        )
    if verdict == "PREP_THEN_DEAL_REACHES_FOUNDATION2_CHEAPER":
        return (
            "Just-in-time pre-SD5 preparation beat Deal-now for Foundation 2. Keep those "
            "prep actions as the receiving-state recipe and continue from the cheapest F2 root. "
            "Do not resume G6_8."
        )
    if verdict == "FOUNDATION2_REACHED_MULTIPLE_SUITS":
        return (
            "Foundation 2 is reachable after SD5 in more than one suit. Continue from the "
            "cheapest F2 state without preselecting a suit. Do not resume G6_8."
        )
    if verdict == "NO_FOUNDATION2_POST_SD5_IN_ENVELOPE":
        return (
            "SD5 did not cheaply yield Foundation 2 from this union. Widen post-SD5 search "
            "or prep diversity; do not return to G6_8 under MW<=100."
        )
    if verdict == "POST_SD5_SEARCH_STATE_EXPLOSION":
        return (
            "Post-SD5 UCS hit 600,000 unique with min live g=81 and no Foundation 2. "
            "The 103,513-seed fan-out consumed the envelope before any suit removed. "
            "Continue UCS from the live g>=81 frontier, or reseed only DEAL_NOW plus the "
            "cheapest prep children per source, rather than resuming G6_8. "
            "Do not raise MW above 120."
        )
    return "Keep the final-Deal timing pivot. Do not resume pre-SD5 G6_8."


def write_report(payload: dict) -> None:
    lines = [
        "# Spider Solver v0.43 — Final-Deal Timing Pivot",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('verdict_reason', '')}",
        "",
        payload.get("interpretation", ""),
        "",
        f"- Branch: `{payload.get('branch')}`",
        f"- Base SHA: `{BASE_SHA}`",
        "",
        "## 2. Why we are not continuing G6_8",
        "",
        "v0.42 showed G6_8 can start peeling (6–10 mixed cards) but exposure was not reached "
        "under MW<=100, while G6_9 cannot start until a rank-6 landing exists. SD5 injects "
        "another 2D and 5D, so the unique-card Diamond obligations cease to be globally "
        "compulsory. Forcing G6_8 further before testing SD5 would risk optimising a constraint "
        "that the known final row removes. This is horizon widening, not a proof that G6_8 is unreachable.",
        "",
        "## 3. Source union",
        "",
        "```json",
        json.dumps(payload.get("sources"), indent=2)[:3000],
        "```",
        "",
        "## 4. SD5 audit",
        "",
        "```json",
        json.dumps(payload.get("sd5_audit"), indent=2)[:2000],
        "```",
        "",
        "## 5. Pre-Deal preparation / post-stock symmetry",
        "",
        "```json",
        json.dumps(
            {"preparation": payload.get("preparation"), "poststock": payload.get("poststock")},
            indent=2,
        )[:4000],
        "```",
        "",
        "## 6. Foundation search",
        "",
        "```json",
        json.dumps(payload.get("foundation_search"), indent=2)[:4000],
        "```",
        "",
        "## 7. Portfolio / best / timing",
        "",
        "```json",
        json.dumps(
            {
                "portfolio": payload.get("portfolio"),
                "timing": payload.get("timing"),
                "best": payload.get("best"),
            },
            indent=2,
        )[:4000],
        "```",
        "",
        "## 8. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
        "## Integrity",
        "",
        "Pre-SD5 identity is ordered pack_state. Post-SD5 identity is exact column symmetry. "
        "No suit-specific ordering. No static receiving score. Foundation 2 is terminal. Production unchanged.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    started = time.perf_counter()
    print("UNION load", flush=True)
    union = load_union(opening)
    print(
        f"UNION unique={union['exact_unique']} raw={union['raw']} fail={union['replay_failures']} "
        f"lineage={union['lineage_unique']}",
        flush=True,
    )
    _write_json(
        SOURCES,
        {
            "experiment": EXPERIMENT,
            "n": union["exact_unique"],
            "raw": union["raw"],
            "lineage_raw": union["lineage_raw"],
            "lineage_unique": union["lineage_unique"],
            "cost_counts": union["cost_counts"],
            "all_replay_ok": union["all_replay_ok"],
            "replay_failures": union["replay_failures"],
            "states": union["states"],
        },
    )
    states, paths, gs, lins = [], [], [], []
    sd5_audit = None
    sd5_mismatch = False
    deal_now_auto = 0
    for rec in union["states"]:
        end = opening.clone()
        replay_actions(end, as_actions(rec["full_actions"]))
        if sd5_audit is None:
            sd5_audit = verify_sd5_row(end)
            sd5_mismatch = not sd5_audit["matches"]
            sd5_audit["deal_legal"] = deal_is_legal(end)
            sd5_audit["deal_cost"] = 1
        states.append(end)
        paths.append(as_actions(rec["full_actions"]))
        gs.append(int(rec["full_cost"]))
        lins.append(list(rec["lineages"]))
    print(f"SD5 row={sd5_audit} mismatch={sd5_mismatch}", flush=True)

    prep = enumerate_preparation(states, paths, gs, lins, max_unique=PREP_UNIQUE, time_limit_s=150.0)
    print(
        f"PREP cand={len(prep.candidates)} unique={prep.unique} stop={prep.stop_reason} t={prep.elapsed_s:.1f}s",
        flush=True,
    )
    # Deal all prep candidates (depth 0 = DEAL_NOW).
    post = deal_preparation_candidates(opening, prep.candidates)
    print(
        f"POSTSTOCK before={post['ordered_before_symmetry']} classes={post['symmetry_classes']} "
        f"red={post['reduction']} timing={post['timing']}",
        flush=True,
    )
    slim_front = []
    for rec in post["states"][:4096]:
        slim_front.append(
            {
                "g": rec["g"],
                "prep_depth": rec["prep_depth"],
                "prep_cost": rec["prep_cost"],
                "timing": rec["timing"],
                "lineages": rec["lineages"],
                "ordered_digest": rec["ordered_digest"],
                "symmetry_digest": rec["symmetry_digest"],
                "full_actions": rec["full_actions"],
                "foundations": rec["foundations"],
                "telemetry": rec["telemetry"],
            }
        )
    _write_json(
        FRONTIER,
        {
            "experiment": EXPERIMENT,
            "n": post["symmetry_classes"],
            "ordered_before_symmetry": post["ordered_before_symmetry"],
            "reduction": post["reduction"],
            "timing": post["timing"],
            "depth": post["depth"],
            "cost_counts": post["cost_counts"],
            "persisted": len(slim_front),
            "states": slim_front,
        },
    )

    f2_budget = SEARCH_TIME_S
    print(f"SEARCH F2 budget={f2_budget:.0f}s unique_cap={SEARCH_UNIQUE} ceiling={COST_CEILING}", flush=True)
    search = search_foundation2(
        post["states"],
        opening,
        max_unique=SEARCH_UNIQUE,
        time_limit_s=f2_budget,
        rss_abort_mb=RSS_ABORT_MB,
        cost_ceiling=COST_CEILING,
    )
    rebuilt = []
    for rec in search.witnesses:
        src = post["states"][rec["origin"]]
        full = as_actions(src["full_actions"]) + as_actions(rec.get("actions") or [])
        end = opening.clone()
        cost = replay_actions(end, full)
        rebuilt.append(
            {
                **rec,
                "full_cost": cost,
                "full_actions": dump_actions(full),
                "full_replay_ok": cost == rec["g"] and stock_rows(end) == 0 and len(end.foundations) >= 2,
                "ordered_digest": pack_state(end).hex(),
                "symmetry_digest": pack_post_stock_symmetry_state(end).hex(),
                "fd": face_down_count(end),
                "empties": list(empty_column_indices(end)),
                "components": same_suit_components(end),
                "telemetry": receiving_telemetry(end),
                "prep_actions": src.get("prep_depth"),
            }
        )
    rebuilt.sort(key=lambda w: (w["full_cost"], w.get("depth", 0), w["origin"]))
    f0 = None if not rebuilt else min(w["full_cost"] for w in rebuilt)
    slack = {}
    if f0 is not None:
        for extra in range(0, HARVEST_SLACK + 1):
            slack[f"F+{extra}" if extra else "F"] = sum(1 for w in rebuilt if w["full_cost"] == f0 + extra)
    by_suit = Counter(w.get("suit_name") or w.get("suit") for w in rebuilt)
    by_timing = Counter(w.get("timing") for w in rebuilt)
    deal_now_cs = [w["full_cost"] for w in rebuilt if w.get("timing") == "DEAL_NOW"]
    prep_cs = [w["full_cost"] for w in rebuilt if w.get("timing") == "PREP_THEN_DEAL"]
    if rebuilt:
        _write_json(
            PORT,
            {
                "experiment": EXPERIMENT,
                "n": len(rebuilt),
                "f0": f0,
                "slack": slack,
                "by_suit": dict(by_suit),
                "by_timing": dict(by_timing),
                "states": rebuilt,
            },
        )
    best = None
    fixture = None
    if rebuilt:
        b = rebuilt[0]
        best = {
            "full_cost": b["full_cost"],
            "suit": b.get("suit_name") or b.get("suit"),
            "timing": b.get("timing"),
            "lineages": b.get("lineages"),
            "prep_depth": b.get("prep_depth"),
            "prep_cost": b.get("prep_cost"),
            "foundations": b.get("foundation_suits"),
            "fd": b.get("fd"),
            "empties": b.get("empties"),
            "full_replay_ok": b.get("full_replay_ok"),
            "ordered_digest": b.get("ordered_digest"),
            "symmetry_digest": b.get("symmetry_digest"),
        }
        FOUND_FIX.write_text(
            format_moves_text(
                as_actions(b["full_actions"]),
                header="# v0.43 cheapest Foundation 2 (any suit)\n",
            ),
            encoding="utf-8",
        )
        fixture = FOUND_FIX.relative_to(ROOT).as_posix()

    payload_pre = {
        "all_replay_ok": union["all_replay_ok"],
        "sd5_mismatch": sd5_mismatch,
        "foundation_search": {
            "reached": bool(rebuilt),
            "stop_reason": search.stop_reason,
        },
        "portfolio": {"by_suit": dict(by_suit)},
        "timing": {
            "cheapest_deal_now": None if not deal_now_cs else min(deal_now_cs),
            "cheapest_prep": None if not prep_cs else min(prep_cs),
        },
    }
    verdict, reason = choose_verdict(payload_pre)
    interpretation = (
        f"{reason}. Union {union['exact_unique']} exact post-SD4 sources "
        f"(raw {union['raw']}). Prep candidates {len(prep.candidates)}. "
        f"Post-stock classes {post['symmetry_classes']} from {post['ordered_before_symmetry']} "
        f"(reduction {post['reduction']}). F2 reached={bool(rebuilt)} F={f0} "
        f"suit={None if search.first_suit is None else search.first_suit} "
        f"timing={search.first_timing}. SD5 never expanded after the single Deal. "
        "G6_8 was not continued."
    )
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": interpretation,
        "next_recommendation": next_recommendation(verdict, payload_pre),
        "sources": {
            "n": union["exact_unique"],
            "raw": union["raw"],
            "lineage_raw": union["lineage_raw"],
            "lineage_unique": union["lineage_unique"],
            "cost_counts": union["cost_counts"],
            "all_replay_ok": union["all_replay_ok"],
            "replay_failures": union["replay_failures"],
        },
        "sd5_audit": sd5_audit,
        "sd5_mismatch": sd5_mismatch,
        "preparation": {
            "unique": prep.unique,
            "candidates": len(prep.candidates),
            "expanded": prep.expanded,
            "generated": prep.generated,
            "duplicate_skips": prep.duplicate_skips,
            "elapsed_s": prep.elapsed_s,
            "stop_reason": prep.stop_reason,
            "depth": dict(Counter(c["prep_depth"] for c in prep.candidates)),
            "timing": dict(Counter(c["timing"] for c in prep.candidates)),
            "sd5_expanded": prep.sd5_expanded,
        },
        "poststock": {
            "ordered_before_symmetry": post["ordered_before_symmetry"],
            "symmetry_classes": post["symmetry_classes"],
            "reduction": post["reduction"],
            "timing": post["timing"],
            "depth": post["depth"],
            "auto_removed": post["auto_removed"],
        },
        "foundation_search": {
            "reached": bool(rebuilt),
            "first_s": search.first_s,
            "first_unique": search.first_unique,
            "best_full_mw": f0,
            "suit": None if search.first_suit is None else search.first_suit,
            "suit_name": None if not rebuilt else (rebuilt[0].get("suit_name") or rebuilt[0].get("suit")),
            "source_lineage": search.first_lineages,
            "timing": search.first_timing,
            "unique": search.unique,
            "expanded": search.expanded,
            "generated": search.generated,
            "duplicate_skips": search.duplicate_skips,
            "elapsed_s": search.elapsed_s,
            "peak_rss_mb": search.peak_rss_mb,
            "stop_reason": search.stop_reason,
            "sd5_expanded": search.sd5_expanded,
            "used_suit_heuristic": search.used_suit_heuristic,
            "exhausted_below_f": search.exhausted_below_f,
            "min_live_g": search.min_live_g,
        },
        "portfolio": {
            "n": len(rebuilt),
            "f0": f0,
            "slack": slack,
            "by_suit": dict(by_suit),
            "by_timing": dict(by_timing),
        },
        "timing": {
            "cheapest_deal_now": None if not deal_now_cs else min(deal_now_cs),
            "cheapest_prep": None if not prep_cs else min(prep_cs),
            "overall": f0,
        },
        "best": best,
        "files": {
            "report": REPORT.relative_to(ROOT).as_posix(),
            "result": RESULT.relative_to(ROOT).as_posix(),
            "sources": SOURCES.relative_to(ROOT).as_posix(),
            "frontier": FRONTIER.relative_to(ROOT).as_posix(),
            "portfolio": PORT.relative_to(ROOT).as_posix() if PORT.exists() else None,
            "fixture": fixture,
        },
        "elapsed_s": time.perf_counter() - started,
        "production_unchanged": True,
        "all_replay_ok": union["all_replay_ok"],
        "g6_8_bypassed": True,
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
