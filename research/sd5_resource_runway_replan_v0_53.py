#!/usr/bin/env python3
"""v0.53: SD5 resource-runway replan over the v0.43 103k preparation envelope.

Do not seed UCS. Do not excavate a suit. Do not inspect the human solution.
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
from spider.packed_state import pack_post_stock_symmetry_state, pack_state
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, opening_state
from spider.simple_sd5_resource_runway import (
    EXPECTED_PREP,
    EXPECTED_SOURCES,
    GLOBAL_TIME_S,
    PORTFOLIO_LIMIT,
    RSS_ABORT_MB,
    SUPPORT_CHILD_CAP,
    SUITS,
    apply_sd5_frontier,
    audit_state,
    choose_verdict,
    harvest_portfolio,
    load_v043_sources,
    one_support_probe,
    pareto_prep_improvements,
    reconstruct_prep,
    support_probe_order,
    tally_group,
)
from spider.simple_progressive_solver import _rss_mb, format_moves_text

EXPERIMENT = "sd5_resource_runway_replan_v0_53"
BASE_SHA = "b1c93bd193221c5246e58d20f45244c89493c532"
BRANCH = "agent/sd5-resource-runway-replan-v0-53"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
ATLAS = ROOT / "docs" / "research" / "sd5_resource_runway_atlas_v0_53.json"
PORT = ROOT / "docs" / "research" / "sd5_resource_aware_portfolio_v0_53.json"
F2_OUT = ROOT / "docs" / "research" / "foundation2_portfolio_v0_53.json"
F2_FIX = ROOT / "solutions" / "4925153_v0_53_foundation2_local.moves.txt"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _slim(rec: dict) -> dict:
    keys = (
        "g", "timing", "prep_depth", "prep_cost", "lineages", "origin",
        "ordered_digest", "symmetry_digest", "best_suit", "direct_len",
        "support_len", "joins", "access", "min_depth", "f2", "f2_suit",
        "empty_now", "empty_in_one", "fd_reveal_in_one", "improved_support",
        "portfolio_cat", "full_actions", "by_suit", "fd",
    )
    return {k: rec[k] for k in keys if k in rec}


def next_recommendation(verdict: str) -> str:
    if verdict == "PREP_CREATES_FOUNDATION2_LOCAL_TRANSACTION":
        return "Search Foundation 2 from the local-transaction witnesses and the 512-state resource-aware portfolio. Do not resume Spade/Club/Diamond excavation."
    if verdict == "PREP_CREATES_SUPERIOR_SD5_RUNWAY":
        return "Search Foundation 2 from the resource-aware portfolio (not the raw 103k). Prefer NEXT_READY / NEXT_ONE_MOVE / longer-runway classes over DEAL_NOW controls."
    if verdict == "MULTIPLE_PREP_RUNWAY_CLASSES_VIABLE":
        return "Keep the mixed runway portfolio and search Foundation 2 from those distinct classes only. Do not collapse onto one suit."
    if verdict in ("JUST_IN_TIME_PREP_INSUFFICIENT", "DEAL_NOW_REMAINS_BEST_RESOURCE_TOPOLOGY"):
        return (
            "Just-in-time depth<=4 / MW<=4 SD5 prep does not create a self-propelling runway. "
            "Useful receiving structure must be established earlier than this window. "
            "Do not widen prep depth in a follow-on of this experiment; do not resume suit excavation."
        )
    if verdict == "SD5_RUNWAY_AUDIT_RESOURCE_LIMIT":
        return "Finish the direct-runway audit before any Foundation-2 search. Do not sample the 103k."
    return "Keep the resource-aware SD5 portfolio. Do not seed UCS over all 103k states."


def write_report(payload: dict) -> None:
    rec = payload.get("reconstruction") or {}
    deal = payload.get("deal_now") or {}
    prep = payload.get("prep") or {}
    cmp_ = payload.get("comparison") or {}
    sup = payload.get("one_support") or {}
    f2 = payload.get("foundation2") or {}
    port = payload.get("portfolio") or {}
    lines = [
        "# Spider Solver v0.53 — SD5 Resource-Runway Replan",
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
        "## 2. Reconstruction",
        "",
        f"- Pre-SD5 sources: **{rec.get('sources')}** / expected {EXPECTED_SOURCES} (replay_ok={rec.get('all_replay_ok')})",
        f"- Prep candidates: **{rec.get('prep_n')}** / expected {EXPECTED_PREP} (matches={rec.get('matches_v043')})",
        f"- Prep timing: `{rec.get('prep_timing')}` depth `{rec.get('prep_depth')}`",
        f"- Post-SD5 exact: **{rec.get('post_n')}** symmetry `{rec.get('symmetry_classes')}` reduction `{rec.get('reduction')}`",
        f"- Post-SD5 timing: `{rec.get('post_timing')}`",
        f"- SD5 row: `{rec.get('sd5_row')}` match={rec.get('sd5_match')}",
        "",
        "## 3. DEAL_NOW runway",
        "",
        "```json",
        json.dumps(deal, indent=2)[:4000],
        "```",
        "",
        "## 4. PREP_THEN_DEAL runway",
        "",
        "```json",
        json.dumps(prep, indent=2)[:4500],
        "```",
        "",
        "## 5. Direct comparison",
        "",
        f"- Prep classes absent from DEAL_NOW: `{cmp_.get('prep_only_classes')}`",
        f"- Pareto improvements: **{cmp_.get('n_improvements')}**",
        f"- Cheapest improvement g: {cmp_.get('cheapest_improvement_g')}",
        f"- Improvement suit distribution: `{cmp_.get('improvement_suits')}`",
        "",
        "```json",
        json.dumps((cmp_.get("examples") or [])[:12], indent=2)[:3500],
        "```",
        "",
        "## 6. One-support probe",
        "",
        "```json",
        json.dumps(sup, indent=2)[:2500],
        "```",
        "",
        "## 7. Foundation 2",
        "",
        f"- Local F2: **{f2.get('reached')}** n={f2.get('n')} cheapest={f2.get('cheapest')} suit={f2.get('suit')}",
        f"- Fixture: {f2.get('fixture')}",
        "",
        "## 8. Portfolio",
        "",
        "```json",
        json.dumps(port, indent=2)[:2500],
        "```",
        "",
        "## 9. Strategic interpretation",
        "",
        payload.get("strategic", ""),
        "",
        f"- Just-in-time prep helping: **{payload.get('prep_helps')}**",
        "",
        "No UCS over 103k. No suit excavation. No Foundation 3. Production unchanged.",
        "",
        "## 10. Files",
        "",
        "```json",
        json.dumps(payload.get("files"), indent=2),
        "```",
        "",
        "## 11. Exactly one next recommendation",
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
    print(
        f"SRC n={bundle['n']} raw={bundle['raw']} replay_ok={bundle['all_replay_ok']} "
        f"sd5={bundle.get('sd5')}",
        flush=True,
    )
    if not bundle["all_replay_ok"]:
        payload = {
            "experiment": EXPERIMENT,
            "branch": BRANCH,
            "verdict": "SOURCE_REPLAY_FAILURE",
            "verdict_reason": "v0.43 pre-SD5 sources failed replay",
            "all_replay_ok": False,
            "direct_complete": False,
            "elapsed_s": time.perf_counter() - started,
        }
        verdict, reason = choose_verdict(payload)
        payload["verdict"] = verdict
        payload["next_recommendation"] = next_recommendation(verdict)
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT", verdict, flush=True)
        return payload

    print("PREP ENVELOPE", flush=True)
    prep = reconstruct_prep(bundle["states"])
    print(
        f"PREP n={prep['n']} expected={EXPECTED_PREP} match={prep['matches_v043']} "
        f"timing={prep['timing']} depth={prep['depth']} stop={prep['stop_reason']} t={prep['elapsed_s']:.1f}s",
        flush=True,
    )

    print("APPLY SD5", flush=True)
    frontier = apply_sd5_frontier(prep["candidates"])
    print(
        f"POST n={frontier['n']} timing={frontier['timing']} reduction={frontier['reduction']} "
        f"illegal={frontier['illegal']}",
        flush=True,
    )

    print(f"DIRECT RUNWAY n={len(frontier['states'])}", flush=True)
    audited = []
    contract = False
    direct_complete = True
    for i, rec in enumerate(frontier["states"]):
        if time.perf_counter() >= deadline - 90:
            direct_complete = False
            break
        rss = _rss_mb()
        if rss is not None and (peak is None or rss > peak):
            peak = rss
        if rss is not None and rss >= RSS_ABORT_MB:
            direct_complete = False
            break
        row = audit_state(rec)
        contract = contract or bool(row.get("contract_fail"))
        audited.append(row)
        if (i + 1) % 5000 == 0:
            print(f"AUDIT {i+1}/{len(frontier['states'])} t={time.perf_counter()-started:.0f}s", flush=True)
    print(f"AUDIT done n={len(audited)} complete={direct_complete} contract={contract}", flush=True)

    qualifying = [r for r in audited if r.get("qualify_support")]
    support_meta = {
        "qualifying": len(qualifying),
        "examined": 0,
        "children": 0,
        "cap": SUPPORT_CHILD_CAP,
        "complete": False,
        "improved": 0,
        "best_examples": [],
    }
    remaining = deadline - time.perf_counter()
    if qualifying and remaining > 40 and direct_complete:
        print(f"ONE-SUPPORT qualifying={len(qualifying)} budget={remaining:.0f}s", flush=True)
        order = support_probe_order(qualifying)
        by_id = {r["symmetry_digest"]: r for r in audited}
        child_left = SUPPORT_CHILD_CAP
        examined = 0
        for rec in order:
            if time.perf_counter() >= deadline - 15 or child_left <= 0:
                break
            updated, used = one_support_probe(rec, child_budget=child_left)
            child_left -= used
            examined += 1
            by_id[rec["symmetry_digest"]] = updated
            if examined % 200 == 0:
                print(
                    f"SUPPORT exam={examined} children={SUPPORT_CHILD_CAP-child_left} "
                    f"imp={sum(1 for v in by_id.values() if v.get('improved_support'))}",
                    flush=True,
                )
        audited = list(by_id.values())
        support_meta["examined"] = examined
        support_meta["children"] = SUPPORT_CHILD_CAP - child_left
        support_meta["complete"] = examined >= len(qualifying) and child_left > 0
        support_meta["improved"] = sum(1 for r in audited if r.get("improved_support"))
        improved = [r for r in audited if r.get("improved_support")]
        improved.sort(key=lambda r: (r["g"], -int(r.get("support_len") or 0)))
        support_meta["best_examples"] = [_slim(r) for r in improved[:8]]
        print(
            f"SUPPORT done exam={examined}/{len(qualifying)} children={support_meta['children']} "
            f"complete={support_meta['complete']} improved={support_meta['improved']}",
            flush=True,
        )
    else:
        support_meta["complete"] = not qualifying

    deal_now = [r for r in audited if r["timing"] == "DEAL_NOW"]
    prep_rows = [r for r in audited if r["timing"] != "DEAL_NOW"]
    deal_tally = tally_group(deal_now)
    prep_tally = tally_group(prep_rows)
    prep_by_depth = {str(d): tally_group([r for r in prep_rows if r["prep_depth"] == d]) for d in range(1, 5)}
    prep_by_cost = {
        str(c): tally_group([r for r in prep_rows if r["prep_cost"] == c]) for c in sorted({r["prep_cost"] for r in prep_rows})
    }
    improvements = pareto_prep_improvements(deal_now, prep_rows)
    deal_access = set(deal_tally.get("access") or {})
    prep_access = set(prep_tally.get("access") or {})
    prep_only = sorted(prep_access - deal_access)

    f2_rows = [r for r in audited if r.get("f2")]
    f2_rows.sort(key=lambda r: (r["g"], r["ordered_digest"]))
    fixtures = {}
    if f2_rows:
        _write_json(F2_OUT, {"experiment": EXPERIMENT, "n": len(f2_rows), "states": [_slim(r) for r in f2_rows[:128]]})
        best = f2_rows[0]
        if best.get("full_actions"):
            extra = as_actions(best.get("f2_path") or [])
            path = as_actions(best["full_actions"]) + extra
            F2_FIX.parent.mkdir(parents=True, exist_ok=True)
            F2_FIX.write_text(format_moves_text(path, header="# v0.53 local Foundation 2\n"), encoding="utf-8")
            fixtures["path"] = F2_FIX.relative_to(ROOT).as_posix()
            end = opening.clone()
            cost = replay_actions(end, parse_moves_file(F2_FIX))
            print(f"FIXTURE mw={cost} fdn={len(end.foundations)}", flush=True)

    port_rows = harvest_portfolio(audited)
    _write_json(
        PORT,
        {
            "experiment": EXPERIMENT,
            "n": len(port_rows),
            "limit": PORTFOLIO_LIMIT,
            "categories": dict(Counter(r.get("portfolio_cat") for r in port_rows)),
            "suits": dict(Counter(r.get("best_suit") for r in port_rows)),
            "timing": dict(Counter(r.get("timing") for r in port_rows)),
            "mw": dict(Counter(r.get("g") for r in port_rows)),
            "states": [_slim(r) for r in port_rows],
        },
    )

    atlas = {
        "experiment": EXPERIMENT,
        "n": len(audited),
        "direct_complete": direct_complete,
        "timing": dict(Counter(r["timing"] for r in audited)),
        "deal_now": deal_tally,
        "prep": prep_tally,
        "prep_by_depth": prep_by_depth,
        "prep_by_cost": prep_by_cost,
        "improvements_n": len(improvements),
        "improvements": improvements[:64],
        "one_support": support_meta,
        "best_direct_examples": [_slim(r) for r in sorted(audited, key=lambda w: (-int(w.get("direct_len") or 0), w["g"]))[:16]],
    }
    _write_json(ATLAS, atlas)

    payload_pre = {
        "all_replay_ok": bundle["all_replay_ok"],
        "contract_fail": contract,
        "direct_complete": direct_complete,
        "f2": bool(f2_rows),
        "improvements": improvements,
        "deal_now": deal_tally,
        "prep": prep_tally,
    }
    verdict, reason = choose_verdict(payload_pre)
    prep_helps = verdict in (
        "PREP_CREATES_SUPERIOR_SD5_RUNWAY",
        "PREP_CREATES_FOUNDATION2_LOCAL_TRANSACTION",
        "MULTIPLE_PREP_RUNWAY_CLASSES_VIABLE",
    )
    strategic = (
        "Just-in-time depth<=4 / MW<=4 preparation produces post-Deal states whose resource topology "
        "is materially better than DEAL_NOW."
        if prep_helps
        else "Just-in-time depth<=4 / MW<=4 preparation does not create a self-propelling foundation runway. "
        "Useful SD5 receiving structure must be built earlier than this window."
    )
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": f"{reason}. sources={bundle['n']} prep={prep['n']} post={frontier['n']} "
        f"deal_now_best={deal_tally.get('best_direct')} prep_best={prep_tally.get('best_direct')} "
        f"improvements={len(improvements)} F2={len(f2_rows)}. {strategic}",
        "strategic": strategic,
        "prep_helps": prep_helps,
        "next_recommendation": next_recommendation(verdict),
        "all_replay_ok": bundle["all_replay_ok"],
        "contract_fail": contract,
        "direct_complete": direct_complete,
        "f2": bool(f2_rows),
        "reconstruction": {
            "sources": bundle["n"],
            "all_replay_ok": bundle["all_replay_ok"],
            "prep_n": prep["n"],
            "matches_v043": prep["matches_v043"],
            "prep_timing": prep["timing"],
            "prep_depth": prep["depth"],
            "prep_elapsed_s": prep["elapsed_s"],
            "post_n": frontier["n"],
            "symmetry_classes": frontier["symmetry_classes"],
            "reduction": frontier["reduction"],
            "post_timing": frontier["timing"],
            "post_depth": frontier["depth"],
            "post_cost": frontier["cost_counts"],
            "sd5_row": (bundle.get("sd5") or {}).get("engine"),
            "sd5_match": (bundle.get("sd5") or {}).get("matches"),
        },
        "deal_now": deal_tally,
        "prep": {**prep_tally, "by_depth": {k: {"n": v["n"], "best_direct": v["best_direct"], "next_ready": v["next_ready"], "next_one_move": v["next_one_move"]} for k, v in prep_by_depth.items()}},
        "comparison": {
            "prep_only_classes": prep_only,
            "n_improvements": len(improvements),
            "cheapest_improvement_g": None if not improvements else improvements[0]["g"],
            "improvement_suits": dict(Counter(w.get("suit") for w in improvements)),
            "examples": improvements[:16],
        },
        "one_support": support_meta,
        "foundation2": {
            "reached": bool(f2_rows),
            "n": len(f2_rows),
            "cheapest": None if not f2_rows else f2_rows[0]["g"],
            "suit": None if not f2_rows else f2_rows[0].get("f2_suit"),
            "fixture": fixtures.get("path"),
        },
        "portfolio": {
            "n": len(port_rows),
            "categories": dict(Counter(r.get("portfolio_cat") for r in port_rows)),
            "suits": dict(Counter(r.get("best_suit") for r in port_rows)),
            "timing": dict(Counter(r.get("timing") for r in port_rows)),
            "mw_bands": dict(Counter(r.get("g") for r in port_rows)),
        },
        "files": {
            "report": REPORT.relative_to(ROOT).as_posix(),
            "result": RESULT.relative_to(ROOT).as_posix(),
            "atlas": ATLAS.relative_to(ROOT).as_posix(),
            "portfolio": PORT.relative_to(ROOT).as_posix(),
            "foundation2": F2_OUT.relative_to(ROOT).as_posix() if F2_OUT.exists() else None,
            "fixture": fixtures.get("path"),
        },
        "elapsed_s": time.perf_counter() - started,
        "peak_rss_mb": peak,
        "production_unchanged": True,
        "improvements": improvements[:32],
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
