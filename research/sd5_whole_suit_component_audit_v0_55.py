#!/usr/bin/env python3
"""v0.55: whole-suit component assembly audit of the v0.53 post-SD5 universe.

Reuse 720 DEAL_NOW + 102,793 PREP_THEN_DEAL (103,513 total).
Audit only. No UCS, no descendant search, no pre-SD4, no Foundation 3,
no suit winner. Do NOT inspect the human solution.
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
from spider.simple_progressive_solver import _rss_mb, format_moves_text
from spider.simple_sd5_component_audit import (
    SUITS,
    audit_state,
    choose_verdict,
    harvest_component_portfolio,
    new_classes,
    pareto_prep,
    tally,
)
from spider.simple_sd5_resource_runway import (
    EXPECTED_PREP,
    GLOBAL_TIME_S,
    RSS_ABORT_MB,
    apply_sd5_frontier,
    load_v043_sources,
    reconstruct_prep,
)

EXPERIMENT = "sd5_whole_suit_component_audit_v0_55"
BASE_SHA = "0b01ef8819eea13bea34d65bdeba584a12a41ab1"
BRANCH = "agent/sd5-whole-suit-component-audit-v0-55"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
ATLAS = ROOT / "docs" / "research" / "sd5_component_topology_atlas_v0_55.json"
PORT = ROOT / "docs" / "research" / "sd5_component_aware_portfolio_v0_55.json"
F2_OUT = ROOT / "docs" / "research" / "foundation2_portfolio_v0_55.json"
F2_FIX = ROOT / "solutions" / "4925153_v0_55_component_foundation2.moves.txt"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _slim(rec: dict) -> dict:
    keys = (
        "g", "timing", "prep_depth", "prep_cost", "lineages", "origin",
        "ordered_digest", "symmetry_digest", "best_suit", "min_cover",
        "min_visible_cover", "min_fd_cards", "join_lb", "visible_n",
        "start_edges", "cond_longest", "cond_min_n", "longest", "k_len",
        "a_len", "gap", "joinable", "f2", "f2_suit", "full_actions",
        "by_suit", "portfolio_cat",
    )
    return {k: rec[k] for k in keys if k in rec}


def next_recommendation(verdict: str) -> str:
    if verdict == "PREP_CREATES_LOCAL_COMPONENT_FOUNDATION2":
        return "Search Foundation 2 from the local component-condensation witnesses. Do not retreat to pre-SD4 yet."
    if verdict == "PREP_CREATES_SUPERIOR_COMPONENT_TOPOLOGY":
        return (
            "Run one compact component-aware Foundation-2 search from the new portfolio. "
            "Do not resume Ace-tail excavation or the 103k UCS."
        )
    if verdict == "WHOLE_SUIT_AUDIT_SUPPORTS_PRE_SD4_RETREAT":
        return (
            "Retreat to pre-SD4. Both the Ace-ending runway model and the whole-suit "
            "component model failed to improve inside depth<=4 / MW<=4."
        )
    return "Keep the whole-suit component audit. Do not run descendant UCS."


def write_report(payload: dict) -> None:
    uni = payload.get("universe") or {}
    deal = payload.get("deal_now") or {}
    prep = payload.get("prep") or {}
    cmp_ = payload.get("comparison") or {}
    cond = payload.get("condensation") or {}
    f2 = payload.get("foundation2") or {}
    lines = [
        "# Spider Solver v0.55 — Whole-Suit Component Assembly Audit",
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
        "## 2. Universe",
        "",
        f"- Post-SD5: **{uni.get('n')}** / expected {EXPECTED_PREP} (match={uni.get('matches')})",
        f"- DEAL_NOW / PREP: **{uni.get('deal_now')}** / **{uni.get('prep')}**",
        f"- Replay: {uni.get('all_replay_ok')}",
        "",
        "## 3. DEAL_NOW component topology",
        "",
        "```json",
        json.dumps(deal, indent=2)[:5000],
        "```",
        "",
        "## 4. PREP component topology",
        "",
        "```json",
        json.dumps(prep, indent=2)[:5000],
        "```",
        "",
        "## 5. Direct condensation",
        "",
        "```json",
        json.dumps(cond, indent=2)[:2500],
        "```",
        "",
        "## 6. PREP vs DEAL_NOW",
        "",
        f"- New classes: `{cmp_.get('new_classes')}`",
        f"- Pareto-nondominated PREP: **{cmp_.get('pareto_n')}**",
        f"- Cheapest Pareto g: {cmp_.get('cheapest_g')}",
        f"- Suits: `{cmp_.get('suits')}`",
        "",
        "```json",
        json.dumps((cmp_.get("examples") or [])[:12], indent=2)[:3000],
        "```",
        "",
        "## 7. Foundation 2",
        "",
        f"- Local F2: **{f2.get('reached')}** n={f2.get('n')} cheapest={f2.get('cheapest')} suit={f2.get('suit')}",
        f"- Fixture: {f2.get('fixture')}",
        "",
        "## 8. Strategic interpretation",
        "",
        payload.get("strategic", ""),
        "",
        "No UCS. No descendant search. No pre-SD4. No weighted score. Production unchanged.",
        "",
        "## 9. Files",
        "",
        "```json",
        json.dumps(payload.get("files"), indent=2),
        "```",
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
    deadline = started + GLOBAL_TIME_S
    peak = _rss_mb()

    print("LOAD v0.43 SOURCES", flush=True)
    bundle = load_v043_sources(opening)
    print(f"SRC n={bundle['n']} ok={bundle['all_replay_ok']}", flush=True)
    print("PREP ENVELOPE", flush=True)
    prep = reconstruct_prep(bundle["states"])
    print(
        f"PREP n={prep['n']} match={prep['matches_v043']} timing={prep['timing']} t={prep['elapsed_s']:.1f}s",
        flush=True,
    )
    print("APPLY SD5", flush=True)
    frontier = apply_sd5_frontier(prep["candidates"])
    print(f"POST n={frontier['n']} timing={frontier['timing']}", flush=True)

    static_complete = True
    contract = False
    audited = []
    print(f"COMPONENT AUDIT n={len(frontier['states'])}", flush=True)
    for i, rec in enumerate(frontier["states"]):
        if time.perf_counter() >= deadline - 20:
            static_complete = False
            break
        rss = _rss_mb()
        if rss is not None and (peak is None or rss > peak):
            peak = rss
        if rss is not None and rss >= RSS_ABORT_MB:
            static_complete = False
            break
        row = audit_state(rec)
        if row.get("min_cover") is not None and row.get("join_lb") != row["min_cover"] - 1:
            contract = True
        audited.append(row)
        if (i + 1) % 5000 == 0:
            print(f"AUDIT {i+1}/{len(frontier['states'])} t={time.perf_counter()-started:.0f}s", flush=True)
    print(f"AUDIT done n={len(audited)} complete={static_complete} contract={contract}", flush=True)

    deal_now = [r for r in audited if r["timing"] == "DEAL_NOW"]
    prep_rows = [r for r in audited if r["timing"] != "DEAL_NOW"]
    deal_t = tally(deal_now)
    prep_t = tally(prep_rows)
    deal_by_suit = {s: tally(deal_now, suit=s) for s in SUITS}
    prep_by_suit = {s: tally(prep_rows, suit=s) for s in SUITS}
    reasons = new_classes(deal_t, prep_t)
    for s in SUITS:
        reasons.extend(f"{s}:{r}" for r in new_classes(deal_by_suit[s], prep_by_suit[s]))
    reasons = sorted(set(reasons))
    pareto = pareto_prep(deal_now, prep_rows)
    pareto.sort(key=lambda r: (r["g"], r.get("min_cover") is None, r.get("min_cover") or 99))
    f2_rows = [r for r in audited if r.get("f2")]
    f2_rows.sort(key=lambda r: r["g"])

    genuine = bool(reasons) or bool(pareto) or bool(f2_rows)
    port_rows = []
    if genuine:
        port_rows = harvest_component_portfolio(audited, limit=512)
        _write_json(
            PORT,
            {
                "experiment": EXPERIMENT,
                "n": len(port_rows),
                "categories": dict(Counter(r.get("portfolio_cat") for r in port_rows)),
                "suits": dict(Counter(r.get("best_suit") for r in port_rows)),
                "timing": dict(Counter(r.get("timing") for r in port_rows)),
                "states": [_slim(r) for r in port_rows],
            },
        )

    fixtures = {}
    if f2_rows:
        _write_json(F2_OUT, {"experiment": EXPERIMENT, "n": len(f2_rows), "states": [_slim(r) for r in f2_rows[:64]]})
        best = f2_rows[0]
        extra = as_actions(best.get("f2_path") or [])
        path = as_actions(best.get("full_actions") or []) + extra
        F2_FIX.parent.mkdir(parents=True, exist_ok=True)
        F2_FIX.write_text(format_moves_text(path, header="# v0.55 component Foundation 2\n"), encoding="utf-8")
        fixtures["path"] = F2_FIX.relative_to(ROOT).as_posix()
        end = opening.clone()
        cost = replay_actions(end, parse_moves_file(F2_FIX))
        print(f"FIXTURE mw={cost} fdn={len(end.foundations)} suits={foundation_suits(end)}", flush=True)

    atlas = {
        "experiment": EXPERIMENT,
        "n": len(audited),
        "static_complete": static_complete,
        "deal_now": deal_t,
        "prep": prep_t,
        "deal_now_by_suit": deal_by_suit,
        "prep_by_suit": prep_by_suit,
        "pareto_n": len(pareto),
        "new_classes": reasons,
        "condensation": {
            "deal_now_best_len": deal_t.get("best_cond_len"),
            "prep_best_len": prep_t.get("best_cond_len"),
            "deal_now_f2": deal_t.get("f2"),
            "prep_f2": prep_t.get("f2"),
        },
        "examples": [_slim(r) for r in pareto[:16]],
    }
    _write_json(ATLAS, atlas)

    payload_pre = {
        "all_replay_ok": bundle["all_replay_ok"] and prep["matches_v043"] and frontier["n"] == EXPECTED_PREP,
        "contract_fail": contract,
        "static_complete": static_complete,
        "f2": bool(f2_rows),
        "new_classes": reasons,
        "pareto_n": len(pareto),
    }
    verdict, reason = choose_verdict(payload_pre)
    prep_helps = verdict in (
        "PREP_CREATES_SUPERIOR_COMPONENT_TOPOLOGY",
        "PREP_CREATES_LOCAL_COMPONENT_FOUNDATION2",
    )
    strategic = (
        "v0.53 missed a meet-in-the-middle preparation advantage. PREP builds better whole-suit components."
        if prep_helps
        else "v0.53 did not miss a hidden whole-suit advantage. Both the Ace-ending runway and the "
        "K/A component topology fail to improve inside depth<=4 / MW<=4. Retreat to pre-SD4 is supported."
    )
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": (
            f"{reason}. n={len(audited)} deal_cover={deal_t.get('best_cover')} "
            f"prep_cover={prep_t.get('best_cover')} pareto={len(pareto)} F2={len(f2_rows)}. {strategic}"
        ),
        "strategic": strategic,
        "next_recommendation": next_recommendation(verdict),
        "all_replay_ok": payload_pre["all_replay_ok"],
        "static_complete": static_complete,
        "contract_fail": contract,
        "f2": bool(f2_rows),
        "universe": {
            "n": frontier["n"],
            "audited": len(audited),
            "matches": frontier["n"] == EXPECTED_PREP,
            "deal_now": len(deal_now),
            "prep": len(prep_rows),
            "all_replay_ok": payload_pre["all_replay_ok"],
            "prep_match_v043": prep["matches_v043"],
        },
        "deal_now": {**deal_t, "by_suit": deal_by_suit},
        "prep": {**prep_t, "by_suit": prep_by_suit},
        "condensation": atlas["condensation"],
        "comparison": {
            "new_classes": reasons,
            "pareto_n": len(pareto),
            "cheapest_g": None if not pareto else pareto[0]["g"],
            "suits": dict(Counter(r.get("best_suit") for r in pareto)),
            "examples": [_slim(r) for r in pareto[:12]],
        },
        "foundation2": {
            "reached": bool(f2_rows),
            "n": len(f2_rows),
            "cheapest": None if not f2_rows else f2_rows[0]["g"],
            "suit": None if not f2_rows else f2_rows[0].get("f2_suit"),
            "fixture": fixtures.get("path"),
        },
        "portfolio": {
            "created": bool(port_rows),
            "n": len(port_rows),
        },
        "files": {
            "report": REPORT.relative_to(ROOT).as_posix(),
            "result": RESULT.relative_to(ROOT).as_posix(),
            "atlas": ATLAS.relative_to(ROOT).as_posix(),
            "portfolio": PORT.relative_to(ROOT).as_posix() if PORT.exists() else None,
            "foundation2": F2_OUT.relative_to(ROOT).as_posix() if F2_OUT.exists() else None,
            "fixture": fixtures.get("path"),
        },
        "elapsed_s": time.perf_counter() - started,
        "peak_rss_mb": peak,
        "production_unchanged": True,
        "new_classes": reasons,
        "pareto_n": len(pareto),
    }
    payload["files"]["portfolio"] = PORT.relative_to(ROOT).as_posix() if PORT.exists() else None
    payload["files"]["foundation2"] = F2_OUT.relative_to(ROOT).as_posix() if F2_OUT.exists() else None
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
