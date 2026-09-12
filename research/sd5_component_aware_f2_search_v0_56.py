#!/usr/bin/env python3
"""v0.56: component-aware multi-lane Foundation-2 search.

v0.55 portfolio + all DEAL_NOW controls. Shared exact TT. No UCS dump,
no pre-SD4, no Foundation 3, no suit hard-coding.
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
from spider.simple_component_aware_f2 import (
    COST_CEILING,
    LANES,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    choose_verdict,
    load_deal_now_roots,
    load_v055_portfolio,
    search_component_aware_f2,
    union_roots,
)
from spider.simple_sd5_component_audit import INF, SUITS

EXPERIMENT = "sd5_component_aware_f2_search_v0_56"
BASE_SHA = "7385aeac594fdff7312aa8d0180763646ef82f70"
BRANCH = "agent/sd5-component-aware-f2-search-v0-56"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "sd5_component_aware_f2_progress_v0_56.json"
FIX = ROOT / "solutions" / "4925153_v0_56_foundation2.moves.txt"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
V054_UNIQUE = 600_000
V054_MIN_LIVE = 83
V054_CLOSED = 82


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _n(v):
    return INF if v is None else int(v)


def topology_improved(root_best: dict, desc_best: dict) -> dict:
    reasons = []
    for suit in SUITS:
        r = root_best.get(suit) or {}
        d = desc_best.get(suit) or {}
        if d and _n(d.get("cover")) < _n(r.get("cover")):
            reasons.append(f"{suit}:cover {_n(r.get('cover'))}->{_n(d.get('cover'))}")
        if d and int(d.get("edges") or 0) > int(r.get("edges") or 0):
            reasons.append(f"{suit}:edges {r.get('edges')}->{d.get('edges')}")
        if d and int(d.get("cond_len") or 0) > int(r.get("cond_len") or 0):
            reasons.append(f"{suit}:cond {r.get('cond_len')}->{d.get('cond_len')}")
        if d.get("gap") is not None and r.get("gap") is not None and int(d["gap"]) < int(r["gap"]):
            reasons.append(f"{suit}:gap {r.get('gap')}->{d.get('gap')}")
    return {"improved": bool(reasons), "reasons": reasons}


def next_recommendation(verdict: str) -> str:
    if verdict == "COMPONENT_AWARE_FOUNDATION2_REACHED":
        return (
            "Preserve the Foundation-2 witness and fold component-lane scheduling plus "
            "exact post-stock TT into the common search kernel. Then start repository consolidation."
        )
    return (
        "The shallow post-SD5 preparation/component-search line has had its authorised final test. "
        "Consolidate the research search kernel before any further strategic experiment."
    )


def write_report(payload: dict) -> None:
    lines = [
        "# Spider Solver v0.56 — Component-Aware Foundation-2 Search",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('verdict_reason', '')}",
        "",
        payload.get("interpretation", ""),
        "",
        f"- Branch: `{payload.get('branch')}`",
        f"- Base SHA: `{BASE_SHA}`",
        f"- Envelope: MW<={COST_CEILING}, unique {SEARCH_UNIQUE}, {SEARCH_TIME_S}s, {SEARCH_RSS_MB} MB RSS",
        "",
        "## 2. Roots",
        "",
        "```json",
        json.dumps(payload.get("roots"), indent=2)[:2500],
        "```",
        "",
        "## 3. Search",
        "",
        "```json",
        json.dumps(payload.get("search"), indent=2)[:4000],
        "```",
        "",
        "## 4. Per-lane coverage",
        "",
        "```json",
        json.dumps(payload.get("lanes"), indent=2)[:2500],
        "```",
        "",
        "## 5. Component progress by suit",
        "",
        "```json",
        json.dumps(payload.get("progress"), indent=2)[:3500],
        "```",
        "",
        "## 6. Foundation 2 / replay",
        "",
        "```json",
        json.dumps({"foundation2": payload.get("foundation2"), "replay": payload.get("replay")}, indent=2)[:2500],
        "```",
        "",
        "## 7. vs v0.54",
        "",
        "```json",
        json.dumps(payload.get("vs_v054"), indent=2)[:2000],
        "```",
        "",
        "## 8. Strategic interpretation",
        "",
        payload.get("strategic", ""),
        "",
        "No pre-SD4. No Foundation 3. No Ace-tail/6D/4S excavation. Production unchanged.",
        "",
        "## 9. Files",
        "",
        json.dumps(payload.get("files"), indent=2),
        "",
        "## 10. Exactly one next recommendation",
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
    print(f"DEAL_NOW n={deal['n']} ok={deal['all_replay_ok']}", flush=True)
    print("LOAD v0.55 PORTFOLIO", flush=True)
    port = load_v055_portfolio(opening)
    print(f"PORT n={port['n']} ok={port['all_replay_ok']} timing={port['timing']}", flush=True)
    union = union_roots(deal["states"], port["states"])
    print(
        f"UNION raw={union['combined_raw']} unique={union['symmetry_unique']} conv={union['convergences']}",
        flush=True,
    )
    all_ok = deal["all_replay_ok"] and port["all_replay_ok"]
    root_best = {}
    for rec in union["states"]:
        st = None
        from spider.packed_state import unpack_state
        from spider.simple_sd5_component_audit import lane_suit_metrics

        st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
        for suit in SUITS:
            m = lane_suit_metrics(st, suit)
            m["g"] = rec["g"]
            prev = root_best.get(suit)
            if prev is None or (
                _n(m.get("cover")),
                -int(m.get("edges") or 0),
                -int(m.get("cond_len") or 0),
                _n(m.get("gap")),
                rec["g"],
            ) < (
                _n(prev.get("cover")),
                -int(prev.get("edges") or 0),
                -int(prev.get("cond_len") or 0),
                _n(prev.get("gap")),
                int(prev.get("g") or INF),
            ):
                root_best[suit] = m

    search_meta = {"attempted": False}
    witnesses: list = []
    replay_info = {}
    progress = {}
    topo = {"improved": False, "reasons": []}
    res = None
    if all_ok:
        print("SEARCH component-aware F2", flush=True)
        res = search_component_aware_f2(union["states"])
        search_meta = {
            "attempted": True,
            "unique": res.unique,
            "expanded": res.expanded,
            "generated": res.generated,
            "duplicate_skips": res.duplicate_skips,
            "stale_skips": res.stale_skips,
            "elapsed_s": res.elapsed_s,
            "peak_rss_mb": res.peak_rss_mb,
            "stop_reason": res.stop_reason,
            "min_g": res.min_g,
            "max_g": res.max_g,
            "min_live_g": res.min_live_g,
            "closed_g": res.closed_g,
            "incumbent": res.incumbent,
            "first_s": res.first_s,
            "first_unique": res.first_unique,
            "first_g": res.first_g,
            "first_suit": res.first_suit,
            "first_timing": res.first_timing,
            "first_category": res.first_category,
            "sd5_expanded": res.sd5_expanded,
            "accounting_fail": res.accounting_fail,
        }
        witnesses = list(res.witnesses)
        progress = {s: res.best_progress.get(s) for s in SUITS}
        topo = topology_improved(root_best, progress)
        print(
            f"SEARCH stop={res.stop_reason} unique={res.unique} exp={res.expanded} "
            f"inc={res.incumbent} live={res.min_live_g} t={res.elapsed_s:.1f}s",
            flush=True,
        )

    replay_fail = False
    if witnesses:
        best = min(witnesses, key=lambda w: (w["g"], w["ordered_digest"]))
        FIX.parent.mkdir(parents=True, exist_ok=True)
        FIX.write_text(
            format_moves_text(as_actions(best["full_actions"]), header="# v0.56 Foundation 2\n"),
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
        replay_fail = not replay_info["legal"]
        print(f"FIXTURE legal={replay_info['legal']} mw={cost} fdn={len(end.foundations)}", flush=True)

    payload_pre = {
        "all_replay_ok": all_ok,
        "accounting_fail": bool(search_meta.get("accounting_fail")),
        "replay_fail": replay_fail,
        "reached": bool(witnesses) and not replay_fail,
        "topology_improved": topo.get("improved"),
        "stop_reason": search_meta.get("stop_reason"),
    }
    verdict, reason = choose_verdict(payload_pre)
    if verdict == "COMPONENT_AWARE_FOUNDATION2_REACHED":
        strategic = (
            "Component-aware lanes produced a replay-valid Foundation 2. "
            "The generic mechanism is multi-lane scheduling over exact post-stock TT, "
            "not a suit-specific ratchet."
        )
    elif topo.get("improved"):
        strategic = (
            "The authorised post-SD5 component search compressed structure further than the "
            "v0.55 roots but still did not remove a second foundation. The shallow line is exhausted."
        )
    else:
        strategic = (
            "Component-aware search neither found Foundation 2 nor a new operational topology class. "
            "The shallow post-SD5 preparation/component line has now had its authorised final test."
        )
    vs = {
        "v054_unique": V054_UNIQUE,
        "v056_unique": search_meta.get("unique"),
        "v054_min_live_g": V054_MIN_LIVE,
        "v054_closed_g": V054_CLOSED,
        "v056_min_live_g": search_meta.get("min_live_g"),
        "v056_closed_g": search_meta.get("closed_g"),
        "v054_f2": False,
        "v056_f2": bool(witnesses) and not replay_fail,
        "v056_time_s": search_meta.get("elapsed_s"),
        "v056_rss_mb": search_meta.get("peak_rss_mb"),
    }
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": f"{reason}. unique={search_meta.get('unique')} F2={search_meta.get('first_g')} "
        f"suit={search_meta.get('first_suit')} timing={search_meta.get('first_timing')}. {strategic}",
        "strategic": strategic,
        "next_recommendation": next_recommendation(verdict),
        "all_replay_ok": all_ok,
        "roots": {
            "deal_now_raw": deal["n"],
            "portfolio_raw": port["n"],
            "portfolio_timing": port.get("timing"),
            "portfolio_categories": port.get("categories"),
            "combined_raw": union["combined_raw"],
            "symmetry_unique": union["symmetry_unique"],
            "convergences": union["convergences"],
            "timing": union["timing"],
            "deal_replay_ok": deal["all_replay_ok"],
            "port_replay_ok": port["all_replay_ok"],
        },
        "search": search_meta,
        "lanes": {
            "names": list(LANES),
            "pops": None if res is None else res.lane_pops,
            "expansions": None if res is None else res.lane_exp,
            "stale": None if res is None else res.lane_stale,
        },
        "progress": {
            "roots": root_best,
            "descendants": progress,
            "improved": topo,
        },
        "foundation2": {
            "reached": bool(witnesses) and not replay_fail,
            "n": len(witnesses),
            "first_g": search_meta.get("first_g"),
            "best_g": None if not witnesses else min(w["g"] for w in witnesses),
            "suit": search_meta.get("first_suit"),
            "timing": search_meta.get("first_timing"),
            "category": search_meta.get("first_category"),
            "origin_timings": dict(Counter(w.get("timing") for w in witnesses)),
        },
        "replay": replay_info,
        "vs_v054": vs,
        "files": {
            "report": REPORT.relative_to(ROOT).as_posix(),
            "result": RESULT.relative_to(ROOT).as_posix(),
            "progress": PROG.relative_to(ROOT).as_posix(),
            "fixture": FIX.relative_to(ROOT).as_posix() if FIX.exists() else None,
        },
        "elapsed_s": time.perf_counter() - started,
        "production_unchanged": True,
        "reached": payload_pre["reached"],
        "accounting_fail": search_meta.get("accounting_fail"),
        "replay_fail": replay_fail,
        "topology_improved": topo.get("improved"),
        "stop_reason": search_meta.get("stop_reason"),
    }
    _write_json(RESULT, payload)
    _write_json(
        PROG,
        {
            "experiment": EXPERIMENT,
            "roots": root_best,
            "descendants": progress,
            "lanes": payload["lanes"],
            "witnesses": [
                {k: w[k] for k in w if k not in ("full_actions", "actions", "metrics")}
                for w in witnesses[:128]
            ],
        },
    )
    payload["files"]["fixture"] = FIX.relative_to(ROOT).as_posix() if FIX.exists() else None
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
