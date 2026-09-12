#!/usr/bin/env python3
"""v0.54: exact Foundation-2 search from condensed resource-aware post-SD5 roots.

All 720 DEAL_NOW plus v0.53 PREP_THEN_DEAL portfolio. No suit target.
No rank-by-rank excavation. No Deal. No Foundation 3.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.metrics import parse_moves_file, replay_actions
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, opening_state
from spider.simple_final_deal_timing import foundation_suits
from spider.simple_progressive_solver import format_moves_text
from spider.simple_resource_aware_f2 import (
    COST_CEILING,
    EXPECTED_DEAL_NOW,
    HARVEST_LIMIT,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    choose_verdict,
    load_deal_now_roots,
    load_prep_roots,
    search_foundation2,
    union_roots,
)

EXPERIMENT = "resource_aware_foundation2_search_v0_54"
BASE_SHA = "4e48a9ed30a47ea77dadbde432da4eeff7f3179e"
BRANCH = "agent/resource-aware-foundation2-search-v0-54"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
ROOTS_OUT = ROOT / "docs" / "research" / "resource_aware_foundation2_roots_v0_54.json"
PORT_OUT = ROOT / "docs" / "research" / "foundation2_portfolio_v0_54.json"
FIX = ROOT / "solutions" / "4925153_v0_54_foundation2.moves.txt"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
V043_UNIQUE = 600_000
V043_ROOTS = 103_513
V043_MIN_LIVE = 81


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _slim_root(rec: dict) -> dict:
    keys = (
        "g", "timing", "timings", "full_actions", "ordered_digest", "symmetry_digest",
        "lineages", "category", "categories", "best_suit", "direct_len", "access",
        "prep_depth", "prep_cost", "empty_in_one",
    )
    return {k: rec[k] for k in keys if k in rec}


def _slim_wit(rec: dict) -> dict:
    keys = (
        "g", "root_g", "continuation_mw", "depth", "suit", "suit_name", "timing",
        "timings", "category", "categories", "lineages", "prep_depth", "prep_cost",
        "fd", "empties", "components", "full_actions", "final_action",
        "ordered_digest", "symmetry_digest", "foundation_count", "foundation_suits",
    )
    return {k: rec[k] for k in keys if k in rec}


def next_recommendation(verdict: str) -> str:
    if verdict.startswith("FOUNDATION2_REACHED"):
        return (
            "Replan from the Foundation-2 portfolio. Do not resume Spade/Club/Diamond "
            "rank-by-rank excavation. Do not search Foundation 3 until this frontier is used."
        )
    if verdict == "RESOURCE_AWARE_SEARCH_STATE_EXPLOSION":
        return (
            "Condensed-root UCS still exploded before Foundation 2. Retreat to pre-SD4 "
            "receiving structure rather than widening MW or reseeding the 103k."
        )
    if verdict == "RESOURCE_AWARE_FOUNDATION2_NOT_FOUND":
        return (
            "No Foundation 2 from DEAL_NOW plus the resource-aware PREP portfolio. "
            "It is now justified to retreat to pre-SD4 rather than another post-SD5 suit tunnel."
        )
    return "Keep the condensed-root Foundation-2 search. Do not resume rank-by-rank excavation."


def write_report(payload: dict) -> None:
    roots = payload.get("roots") or {}
    search = payload.get("search") or {}
    port = payload.get("portfolio") or {}
    replay = payload.get("replay") or {}
    cmp_ = payload.get("vs_v043") or {}
    lines = [
        "# Spider Solver v0.54 — Resource-Aware Foundation-2 Search",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('verdict_reason', '')}",
        "",
        payload.get("interpretation", ""),
        "",
        f"- Branch: `{payload.get('branch')}`",
        f"- Base SHA: `{BASE_SHA}`",
        f"- Elapsed: {payload.get('elapsed_s')}s",
        "",
        "## 2. Roots",
        "",
        f"- DEAL_NOW raw: **{roots.get('raw_deal_now')}** (expected {EXPECTED_DEAL_NOW})",
        f"- PREP raw: **{roots.get('raw_prep')}**",
        f"- Combined raw: **{roots.get('combined_raw')}**",
        f"- Exact unique: **{roots.get('symmetry_unique')}**",
        f"- Convergences: {roots.get('convergences')}",
        f"- MW: `{roots.get('cost_counts')}`",
        f"- Timing: `{roots.get('timing')}`",
        f"- PREP categories: `{roots.get('prep_categories')}`",
        "",
        "## 3. Search",
        "",
        "```json",
        json.dumps(search, indent=2)[:4500],
        "```",
        "",
        "## 4. Foundation portfolio",
        "",
        "```json",
        json.dumps(port, indent=2)[:3500],
        "```",
        "",
        "## 5. Replay",
        "",
        "```json",
        json.dumps(replay, indent=2)[:2000],
        "```",
        "",
        "## 6. Comparison to v0.43",
        "",
        "```json",
        json.dumps(cmp_, indent=2)[:2000],
        "```",
        "",
        "## 7. Strategic interpretation",
        "",
        payload.get("strategic", ""),
        "",
        "No suit target. No low-tail constraint. No Deal. No Foundation 3. Production unchanged.",
        "",
        "## 8. Files",
        "",
        "```json",
        json.dumps(payload.get("files"), indent=2),
        "```",
        "",
        "## 9. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    started = time.perf_counter()

    print("LOAD DEAL_NOW", flush=True)
    deal = load_deal_now_roots(opening)
    print(
        f"DEAL_NOW n={deal['n']} raw={deal['raw']} ok={deal['all_replay_ok']} costs={deal['cost_counts']}",
        flush=True,
    )
    print("LOAD PREP", flush=True)
    prep = load_prep_roots(opening)
    print(
        f"PREP n={prep['n']} raw={prep['raw']} ok={prep['all_replay_ok']} cats={prep['categories']}",
        flush=True,
    )
    union = union_roots(deal["states"], prep["states"])
    print(
        f"UNION raw={union['combined_raw']} unique={union['symmetry_unique']} "
        f"conv={union['convergences']} timing={union['timing']}",
        flush=True,
    )
    _write_json(
        ROOTS_OUT,
        {
            "experiment": EXPERIMENT,
            "n": union["symmetry_unique"],
            "raw_deal_now": union["raw_deal_now"],
            "raw_prep": union["raw_prep"],
            "combined_raw": union["combined_raw"],
            "convergences": union["convergences"],
            "cost_counts": union["cost_counts"],
            "timing": union["timing"],
            "prep_categories": union["prep_categories"],
            "states": [_slim_root(r) for r in union["states"]],
        },
    )

    all_ok = deal["all_replay_ok"] and prep["all_replay_ok"]
    search_meta = {
        "attempted": False,
        "reached": False,
        "unique": 0,
        "expanded": 0,
        "generated": 0,
        "duplicate_skips": 0,
        "elapsed_s": 0.0,
        "peak_rss_mb": None,
        "stop_reason": "skipped",
        "first_s": None,
        "first_unique": None,
        "first_g": None,
        "first_suit": None,
        "first_timing": None,
        "first_root_g": None,
        "continuation_mw": None,
        "min_live_g": None,
        "closed_g": None,
        "incumbent": None,
        "sd5_expanded": False,
        "accounting_fail": False,
    }
    witnesses: list = []
    replay_info = {}
    if all_ok:
        print(
            f"SEARCH F2 n={union['symmetry_unique']} ceiling={COST_CEILING} "
            f"unique_cap={SEARCH_UNIQUE} t={SEARCH_TIME_S}s",
            flush=True,
        )
        res = search_foundation2(
            union["states"],
            max_unique=SEARCH_UNIQUE,
            time_limit_s=SEARCH_TIME_S,
            rss_abort_mb=SEARCH_RSS_MB,
            cost_ceiling=COST_CEILING,
        )
        search_meta.update(
            {
                "attempted": True,
                "reached": bool(res.witnesses),
                "unique": res.unique,
                "expanded": res.expanded,
                "generated": res.generated,
                "duplicate_skips": res.duplicate_skips,
                "elapsed_s": res.elapsed_s,
                "peak_rss_mb": res.peak_rss_mb,
                "stop_reason": res.stop_reason,
                "first_s": res.first_s,
                "first_unique": res.first_unique,
                "first_g": res.first_g,
                "first_suit": res.first_suit,
                "first_timing": res.first_timing,
                "first_root_g": res.first_root_g,
                "continuation_mw": res.first_continuation,
                "final_action": res.first_action,
                "min_live_g": res.min_live_g,
                "closed_g": res.closed_g,
                "incumbent": res.incumbent,
                "sd5_expanded": res.sd5_expanded,
                "accounting_fail": res.accounting_fail,
            }
        )
        witnesses = list(res.witnesses)
        print(
            f"SEARCH stop={res.stop_reason} unique={res.unique} exp={res.expanded} "
            f"inc={res.incumbent} live={res.min_live_g} closed={res.closed_g} "
            f"wit={len(witnesses)} t={res.elapsed_s:.1f}s rss={res.peak_rss_mb}",
            flush=True,
        )

    if witnesses:
        f = min(w["g"] for w in witnesses)
        bands = dict(Counter(w["g"] - f for w in witnesses))
        _write_json(
            PORT_OUT,
            {
                "experiment": EXPERIMENT,
                "n": len(witnesses),
                "cheapest": f,
                "bands": {f"F+{k}": v for k, v in sorted(bands.items())},
                "suits": dict(Counter(w.get("suit") for w in witnesses)),
                "timing": dict(Counter(w.get("timing") for w in witnesses)),
                "states": [_slim_wit(w) for w in witnesses],
            },
        )
        best = min(witnesses, key=lambda w: (w["g"], w["ordered_digest"]))
        FIX.parent.mkdir(parents=True, exist_ok=True)
        FIX.write_text(
            format_moves_text(as_actions(best["full_actions"]), header="# v0.54 Foundation 2\n"),
            encoding="utf-8",
        )
        end = opening.clone()
        cost = replay_actions(end, parse_moves_file(FIX))
        replay_info = {
            "fixture": FIX.relative_to(ROOT).as_posix(),
            "mw": cost,
            "g": best["g"],
            "match": cost == best["g"],
            "stock": stock_rows(end),
            "foundations": len(end.foundations),
            "suits": foundation_suits(end),
            "legal": stock_rows(end) == 0 and len(end.foundations) == 2 and cost == best["g"],
        }
        print(f"FIXTURE mw={cost} fdn={len(end.foundations)} suits={replay_info['suits']}", flush=True)
        if not replay_info["legal"] or len(end.foundations) != 2:
            search_meta["accounting_fail"] = True

    timings = sorted({w.get("timing") for w in witnesses if w.get("timing")})
    payload_pre = {
        "all_replay_ok": all_ok,
        "accounting_fail": bool(search_meta.get("accounting_fail")),
        "reached": bool(witnesses),
        "first_timing": search_meta.get("first_timing"),
        "witness_timings": timings,
        "stop_reason": search_meta.get("stop_reason"),
        "search_attempted": search_meta.get("attempted"),
    }
    verdict, reason = choose_verdict(payload_pre)
    reached = bool(witnesses)
    condensation_helped = reached or (
        search_meta.get("min_live_g") is not None and search_meta["min_live_g"] > V043_MIN_LIVE
    )
    prep_helped = search_meta.get("first_timing") == "PREP_THEN_DEAL" or (
        "PREP_THEN_DEAL" in timings and "DEAL_NOW" in timings
    )
    if reached:
        strategic = (
            "Consequence-based root condensation made exact late-game search produce Foundation 2. "
            + (
                "PREP supplied a downstream continuation that the local runway metric missed."
                if prep_helped
                else "The first witness is DEAL_NOW, so v0.53 JIT prep was not required for this hit."
            )
        )
    else:
        strategic = (
            "Even with ~1k resource-aware roots instead of 103k, Foundation 2 was not reached. "
            "Retreating to pre-SD4 receiving structure is now the justified next horizon, "
            "not another post-SD5 suit excavation."
        )
    vs = {
        "v043_roots": V043_ROOTS,
        "v054_roots": union["symmetry_unique"],
        "root_reduction": None if not union["symmetry_unique"] else round(V043_ROOTS / union["symmetry_unique"], 1),
        "v043_unique_budget": V043_UNIQUE,
        "v054_unique": search_meta.get("unique"),
        "v043_min_live_g": V043_MIN_LIVE,
        "v054_min_live_g": search_meta.get("min_live_g"),
        "v054_closed_g": search_meta.get("closed_g"),
        "v054_first_g": search_meta.get("first_g"),
        "seeds_as_pct_of_unique": None
        if not search_meta.get("unique")
        else round(100.0 * union["symmetry_unique"] / max(1, search_meta["unique"]), 2),
    }
    port_summary = {
        "n": len(witnesses),
        "bands": dict(Counter(w["g"] - min((x["g"] for x in witnesses), default=0) for w in witnesses)) if witnesses else {},
        "suits": dict(Counter(w.get("suit") for w in witnesses)),
        "timing": dict(Counter(w.get("timing") for w in witnesses)),
        "fd": dict(Counter(w.get("fd") for w in witnesses)),
        "empty_n": dict(Counter(len(w.get("empties") or []) for w in witnesses)),
    }
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": (
            f"{reason}. roots={union['symmetry_unique']} unique={search_meta.get('unique')} "
            f"F2={search_meta.get('first_g')} suit={search_meta.get('first_suit')} "
            f"timing={search_meta.get('first_timing')} live={search_meta.get('min_live_g')}. {strategic}"
        ),
        "strategic": strategic,
        "prep_helped": prep_helped,
        "condensation_helped": condensation_helped,
        "next_recommendation": next_recommendation(verdict),
        "all_replay_ok": all_ok,
        "roots": {
            "raw_deal_now": union["raw_deal_now"],
            "raw_prep": union["raw_prep"],
            "combined_raw": union["combined_raw"],
            "symmetry_unique": union["symmetry_unique"],
            "convergences": union["convergences"],
            "cost_counts": union["cost_counts"],
            "timing": union["timing"],
            "prep_categories": union["prep_categories"],
            "deal_replay_ok": deal["all_replay_ok"],
            "prep_replay_ok": prep["all_replay_ok"],
        },
        "search": search_meta,
        "portfolio": port_summary,
        "replay": replay_info,
        "vs_v043": vs,
        "files": {
            "report": REPORT.relative_to(ROOT).as_posix(),
            "result": RESULT.relative_to(ROOT).as_posix(),
            "roots": ROOTS_OUT.relative_to(ROOT).as_posix(),
            "portfolio": PORT_OUT.relative_to(ROOT).as_posix() if PORT_OUT.exists() else None,
            "fixture": FIX.relative_to(ROOT).as_posix() if FIX.exists() else None,
        },
        "elapsed_s": time.perf_counter() - started,
        "production_unchanged": True,
        "reached": reached,
        "accounting_fail": search_meta.get("accounting_fail"),
        "first_timing": search_meta.get("first_timing"),
        "witness_timings": timings,
        "stop_reason": search_meta.get("stop_reason"),
        "search_attempted": search_meta.get("attempted"),
    }
    payload["files"]["portfolio"] = PORT_OUT.relative_to(ROOT).as_posix() if PORT_OUT.exists() else None
    payload["files"]["fixture"] = FIX.relative_to(ROOT).as_posix() if FIX.exists() else None
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
