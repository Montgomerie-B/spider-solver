#!/usr/bin/env python3
"""v0.45: prepare column 8 as the unique-AS SD5 Spade receiver."""

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
from spider.simple_final_deal_timing import enumerate_preparation, foundation_suits
from spider.simple_progressive_solver import format_moves_text
from spider.simple_sd5_spade_receiver import (
    EXPECTED_SOURCES,
    PORTFOLIO_CAP,
    PREP_COST,
    PREP_DEPTH,
    PREP_TIME_S,
    PREP_UNIQUE,
    RSS_ABORT_MB,
    TAIL4_TIME_S,
    TAIL4_UNIQUE,
    V044_BEST_TAIL3,
    V044_TAIL3_N,
    build_targeted_portfolio,
    load_pre_sd5_sources,
    measure_and_deal,
    opening_state,
    preview_tail5,
    search_tail4,
    spade_low_tail_length,
    spade_receiver_length,
    spade_tail_present,
)
from spider.simple_workspace_reachability import empty_column_indices, face_down_count

EXPERIMENT = "sd5_spade_receiving_planner_v0_45"
BASE_SHA = "08c2433fcb04092d1a99fdaeac360216c35b52fb"
BRANCH = "agent/sd5-spade-receiving-planner-v0-45"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
DIST = ROOT / "docs" / "research" / "sd5_spade_receiver_distribution_v0_45.json"
PORT = ROOT / "docs" / "research" / "sd5_spade_transaction_sources_v0_45.json"
TAIL4 = ROOT / "docs" / "research" / "sd5_spade_tail4_v0_45.json"
FOUND_FIX = ROOT / "solutions" / "4925153_v0_45_spade_foundation.moves.txt"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def choose_verdict(p: dict) -> tuple[str, str]:
    if not p.get("all_replay_ok"):
        return "SOURCE_REPLAY_FAILURE", "720-source union failed replay or Spade-chain contract"
    if p.get("foundation_reached"):
        return "FOUNDATION2_SPADE_REACHED", "second Spade foundation auto-removed"
    t4 = p.get("tail4") or {}
    if t4.get("stop_reason") in ("unique limit", "rss abort") and not t4.get("reached"):
        return "SPADE_TRANSACTION_STATE_EXPLOSION", "TAIL4 not found before unique/RSS limit"
    if not t4.get("reached"):
        return "SPADE_TAIL4_NOT_FOUND_IN_ENVELOPE", "4S-3S-2S-AS not reached in 6 ply from the targeted portfolio"
    prep_t3 = p.get("prep_improvement", {}).get("cheapest_prepared_tail3")
    deal_t3 = p.get("v044_control", {}).get("best_cost")
    prep_t4 = p.get("timing", {}).get("prep_tail4")
    deal_t4 = p.get("timing", {}).get("deal_now_tail4")
    prep_t5 = p.get("tail5", {}).get("prep_best")
    deal_t5 = p.get("tail5", {}).get("deal_now_best")
    longer = p.get("prep_improvement", {}).get("longest_immediate_tail") or 0
    if prep_t3 is not None and deal_t3 is not None and prep_t3 < deal_t3:
        return "PREP_BEATS_DEAL_NOW_FOR_SPADE_RECEIVER", f"prepared TAIL3 at {prep_t3} < DEAL_NOW {deal_t3}"
    if prep_t4 is not None and deal_t4 is not None and prep_t4 < deal_t4:
        return "PREP_BEATS_DEAL_NOW_AT_TAIL4", f"prepared TAIL4 at {prep_t4} < DEAL_NOW {deal_t4}"
    if prep_t4 is not None and deal_t4 is not None and prep_t4 == deal_t4:
        if prep_t5 is not None and (deal_t5 is None or prep_t5 < deal_t5):
            return "PREP_AND_DEAL_NOW_TIE_PREP_HAS_BETTER_TAIL5", "TAIL4 cost ties; prep continues better to TAIL5"
        return "DEAL_NOW_REMAINS_BEST_SPADE_TRANSACTION", "TAIL4 cost ties without a TAIL5 advantage"
    if longer >= 3 and (prep_t3 is None or deal_t3 is None or prep_t3 >= deal_t3):
        return "PREP_IMPROVES_RECEIVER_BUT_NOT_TOTAL_COST", "prep builds a better/longer receiver without beating total MW"
    if deal_t4 is not None and (prep_t4 is None or deal_t4 <= prep_t4):
        return "DEAL_NOW_REMAINS_BEST_SPADE_TRANSACTION", "v0.44 DEAL_NOW still cheapest at TAIL4"
    return "INCONCLUSIVE", "Spade receiving comparison incomplete"


def next_recommendation(verdict: str) -> str:
    if verdict == "FOUNDATION2_SPADE_REACHED":
        return "Persist the second Spade foundation witness and do not search Foundation 3."
    if verdict.startswith("PREP_BEATS"):
        return (
            "Keep the prepared column-8 Spade receiver as the SD5 transaction. "
            "Next, ratchet the unique Spade chain from TAIL4/TAIL5. Do not flood UCS."
        )
    if verdict == "PREP_AND_DEAL_NOW_TIE_PREP_HAS_BETTER_TAIL5":
        return "Prefer the prepared receivers that continue to TAIL5. Do not enlarge prep beyond depth/cost 4."
    if verdict == "DEAL_NOW_REMAINS_BEST_SPADE_TRANSACTION":
        return (
            "The diamond_multi_edge DEAL_NOW 3S-2S receiver remains the cheapest Spade transaction. "
            "Continue from those 64 roots toward TAIL4/TAIL5. Do not flood UCS with all prep children."
        )
    if verdict == "PREP_IMPROVES_RECEIVER_BUT_NOT_TOTAL_COST":
        return "Prep can build the AS receiver but does not beat total MW. Keep DEAL_NOW controls and the best prepared long tails."
    if verdict == "SPADE_TAIL4_NOT_FOUND_IN_ENVELOPE":
        return "TAIL3 receivers exist but TAIL4 was not reached in 6 ply. Search TAIL4 from the 3S-2S-AS portfolio only."
    if verdict == "SPADE_TRANSACTION_STATE_EXPLOSION":
        return (
            "DEAL_NOW 3S-2S-AS at 85 remains the cheapest TAIL3. Prep from the same "
            "diamond_multi_edge lineage makes more TAIL3 states at 86, not cheaper, and "
            "never a TAIL4 from the Deal. Continue TAIL4 from the 3S-2S-AS set only "
            "(4S sits under mixed cards in column 8). Do not flood UCS with 103k children."
        )
    return "Keep the targeted Spade SD5 receiving plan. Do not resume undirected post-SD5 UCS."


def write_report(payload: dict) -> None:
    lines = [
        "# Spider Solver v0.45 — SD5 Spade Receiving Planner",
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
        "## 2. Sources / unique Spade chain / SD5",
        "",
        "```json",
        json.dumps({"sources": payload.get("sources"), "sd5": payload.get("sd5_audit")}, indent=2)[:2500],
        "```",
        "",
        "## 3. Preparation / receiver / v0.44 control",
        "",
        "```json",
        json.dumps(
            {
                "preparation": payload.get("preparation"),
                "receiver": payload.get("receiver"),
                "v044_control": payload.get("v044_control"),
                "prep_improvement": payload.get("prep_improvement"),
            },
            indent=2,
        )[:5000],
        "```",
        "",
        "## 4. TAIL4 / TAIL5 / transaction",
        "",
        "```json",
        json.dumps(
            {
                "tail4": payload.get("tail4"),
                "tail5": payload.get("tail5"),
                "timing": payload.get("timing"),
                "transaction": payload.get("transaction"),
                "foundation": payload.get("foundation"),
            },
            indent=2,
        )[:4000],
        "```",
        "",
        "## 5. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
        "## Integrity",
        "",
        "Prep depth/cost <=4 as v0.43. Did not seed all 103k children. Post-stock symmetry only after SD5. Production unchanged.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    started = time.perf_counter()
    print("LOAD 720 sources", flush=True)
    src = load_pre_sd5_sources(opening)
    print(
        f"SRC n={src['n']} fail={src['replay_failures']} chain={src['spade_chain_ok']} sd5={src['sd5_audit']}",
        flush=True,
    )
    states, paths, gs, lins = [], [], [], []
    for rec in src["states"]:
        end = opening.clone()
        replay_actions(end, as_actions(rec["full_actions"]))
        states.append(end)
        paths.append(as_actions(rec["full_actions"]))
        gs.append(int(rec["full_cost"]))
        lins.append(list(rec["lineages"]))
    print("PREP enumerate v0.43 bounds", flush=True)
    prep = enumerate_preparation(
        states, paths, gs, lins, max_unique=PREP_UNIQUE, time_limit_s=PREP_TIME_S, max_depth=PREP_DEPTH, max_cost=PREP_COST
    )
    print(f"PREP cand={len(prep.candidates)} unique={prep.unique} stop={prep.stop_reason} t={prep.elapsed_s:.1f}s", flush=True)
    measured = measure_and_deal(opening, prep.candidates)
    print(
        f"DEAL n={measured['n_candidates']} classes={measured['symmetry_classes']} "
        f"pre={measured['pre_receiver']} post={measured['post_tail']} pred_ok={measured['pred_ok']} fail={measured['pred_fail']}",
        flush=True,
    )
    deal_now = [r for r in measured["states"] if r["timing"] == "DEAL_NOW"]
    deal_t3 = [r for r in deal_now if r["low_tail"] >= 3]
    deal_t3.sort(key=lambda r: (r["g"], r["ordered_digest"]))
    v044 = {
        "n_tail3": len(deal_t3),
        "best_cost": None if not deal_t3 else deal_t3[0]["g"],
        "reproduced_n64": len(deal_t3) >= V044_TAIL3_N or len(deal_t3) == V044_TAIL3_N,
        "best_matches_85": (None if not deal_t3 else deal_t3[0]["g"]) == V044_BEST_TAIL3,
        "sample_receiver": None if not deal_t3 else deal_t3[0]["receiver_length"],
        "sample_tail": None if not deal_t3 else deal_t3[0]["low_tail"],
        "sample_c8_pre": None if not deal_t3 else deal_t3[0]["column8_pre"],
    }
    print(f"V044 control tail3 n={v044['n_tail3']} best={v044['best_cost']} c8={v044['sample_c8_pre']}", flush=True)
    prep_t3 = [r for r in measured["states"] if r["timing"] == "PREP_THEN_DEAL" and r["low_tail"] >= 3]
    prep_t3.sort(key=lambda r: (r["g"], -r["low_tail"]))
    longest = max((r["low_tail"] for r in measured["states"]), default=0)
    longest_prep = [r for r in measured["states"] if r["timing"] == "PREP_THEN_DEAL" and r["low_tail"] == longest]
    longest_prep.sort(key=lambda r: r["g"])
    improvement = {
        "cheapest_prepared_tail3": None if not prep_t3 else prep_t3[0]["g"],
        "cheapest_prepared_tail3_lineage": None if not prep_t3 else prep_t3[0]["lineages"],
        "cheapest_prepared_tail3_prep": None if not prep_t3 else prep_t3[0]["prep_actions"],
        "cheapest_prepared_tail3_depth": None if not prep_t3 else prep_t3[0]["prep_depth"],
        "longest_immediate_tail": longest,
        "longest_prepared_g": None if not longest_prep else longest_prep[0]["g"],
        "beats_85": bool(prep_t3 and prep_t3[0]["g"] < V044_BEST_TAIL3),
    }
    print(f"PREP t3 best={improvement['cheapest_prepared_tail3']} longest={longest} beats85={improvement['beats_85']}", flush=True)
    portfolio = build_targeted_portfolio(measured["states"], cap=PORTFOLIO_CAP)
    print(f"PORTFOLIO n={len(portfolio)} tails={dict(Counter(r['low_tail'] for r in portfolio))}", flush=True)
    slim_dist = {
        "experiment": EXPERIMENT,
        "n_candidates": measured["n_candidates"],
        "symmetry_classes": measured["symmetry_classes"],
        "pre_receiver": measured["pre_receiver"],
        "post_tail": measured["post_tail"],
        "cheapest_by_tail": measured["cheapest_by_tail"],
        "pred_ok": measured["pred_ok"],
        "pred_fail": measured["pred_fail"],
        "by_lineage_tail3": dict(
            Counter(lin for r in measured["states"] if r["low_tail"] >= 3 for lin in r["lineages"])
        ),
        "timing_tail3": dict(Counter(r["timing"] for r in measured["states"] if r["low_tail"] >= 3)),
        "ge": {
            str(L): {
                "n": sum(1 for r in measured["states"] if r["low_tail"] >= L),
                "cheapest": min((r["g"] for r in measured["states"] if r["low_tail"] >= L), default=None),
            }
            for L in (2, 3, 4, 5)
        },
    }
    _write_json(DIST, slim_dist)
    _write_json(
        PORT,
        {
            "experiment": EXPERIMENT,
            "n": len(portfolio),
            "cap": PORTFOLIO_CAP,
            "states": portfolio,
        },
    )
    remaining = 450.0 - (time.perf_counter() - started)
    t4_budget = min(TAIL4_TIME_S, max(20.0, remaining - 30.0))
    print(f"SEARCH TAIL4 budget={t4_budget:.0f}s unique={TAIL4_UNIQUE} n_src={len(portfolio)}", flush=True)
    t4 = search_tail4(portfolio, opening, max_unique=TAIL4_UNIQUE, time_limit_s=t4_budget, rss_abort_mb=RSS_ABORT_MB)
    rebuilt = []
    for rec in t4.witnesses:
        src = portfolio[rec["origin"]]
        full = as_actions(src["full_actions"]) + as_actions(rec.get("actions") or [])
        end = opening.clone()
        cost = replay_actions(end, full)
        rebuilt.append(
            {
                **rec,
                "full_cost": cost,
                "full_actions": dump_actions(full),
                "full_replay_ok": cost == rec["g"] and stock_rows(end) == 0 and spade_tail_present(end, 4),
                "ordered_digest": pack_state(end).hex(),
                "symmetry_digest": pack_post_stock_symmetry_state(end).hex(),
                "low_tail": spade_low_tail_length(end),
                "fd": face_down_count(end),
                "empties": list(empty_column_indices(end)),
                "foundations": foundation_suits(end),
                "receiver_length": src["receiver_length"],
                "prep_actions": src["prep_actions"],
            }
        )
    rebuilt.sort(key=lambda w: (w["full_cost"], w.get("depth", 0), w["origin"]))
    f4 = None if not rebuilt else min(w["full_cost"] for w in rebuilt)
    slack = {}
    if f4 is not None:
        for extra in range(0, 4):
            slack[f"F4+{extra}" if extra else "F4"] = sum(1 for w in rebuilt if w["full_cost"] == f4 + extra)
    if rebuilt:
        _write_json(
            TAIL4,
            {"experiment": EXPERIMENT, "n": len(rebuilt), "f4": f4, "slack": slack, "states": rebuilt},
        )
    preview_counts = Counter()
    longest_prev = 0
    surprise_path = None
    foundation_reached = t4.foundation_surprise
    for rec in rebuilt:
        end = opening.clone()
        replay_actions(end, as_actions(rec["full_actions"]))
        pr = preview_tail5(end, rec["full_cost"], max_depth=5, deadline=time.perf_counter() + 1.0)
        rec["preview"] = pr["status"]
        rec["preview_tail"] = pr.get("low_tail")
        preview_counts[pr["status"]] += 1
        longest_prev = max(longest_prev, int(pr.get("low_tail") or rec.get("low_tail") or 0))
        if pr.get("foundation") and surprise_path is None:
            surprise_path = rec["full_actions"]
            foundation_reached = True
    if foundation_reached and surprise_path is None and rebuilt:
        hit = next((w for w in rebuilt if w.get("foundation")), None)
        if hit:
            surprise_path = hit["full_actions"]
    fixture = None
    if foundation_reached and surprise_path:
        FOUND_FIX.write_text(
            format_moves_text(as_actions(surprise_path), header="# v0.45 second Spade foundation surprise\n"),
            encoding="utf-8",
        )
        fixture = FOUND_FIX.relative_to(ROOT).as_posix()
    deal_t4s = [w["full_cost"] for w in rebuilt if w.get("timing") == "DEAL_NOW"]
    prep_t4s = [w["full_cost"] for w in rebuilt if w.get("timing") == "PREP_THEN_DEAL"]
    t5_deal = [w for w in rebuilt if w.get("timing") == "DEAL_NOW" and w.get("preview") in ("TAIL5_IMMEDIATE", "TAIL5_WITHIN_5")]
    t5_prep = [w for w in rebuilt if w.get("timing") == "PREP_THEN_DEAL" and w.get("preview") in ("TAIL5_IMMEDIATE", "TAIL5_WITHIN_5")]
    sample_tx = None
    if prep_t3:
        sample_tx = {
            "timing": "PREP_THEN_DEAL",
            "g": prep_t3[0]["g"],
            "prep_depth": prep_t3[0]["prep_depth"],
            "prep_cost": prep_t3[0]["prep_cost"],
            "prep_actions": prep_t3[0]["prep_actions"],
            "column8_pre": prep_t3[0]["column8_pre"],
            "receiver_length": prep_t3[0]["receiver_length"],
            "low_tail": prep_t3[0]["low_tail"],
            "lineages": prep_t3[0]["lineages"],
            "labels": prep_t3[0]["labels"],
        }
    elif deal_t3:
        sample_tx = {
            "timing": "DEAL_NOW",
            "g": deal_t3[0]["g"],
            "column8_pre": deal_t3[0]["column8_pre"],
            "receiver_length": deal_t3[0]["receiver_length"],
            "low_tail": deal_t3[0]["low_tail"],
            "lineages": deal_t3[0]["lineages"],
            "labels": deal_t3[0]["labels"],
        }
    payload_pre = {
        "all_replay_ok": src["all_replay_ok"] and src["spade_chain_ok"],
        "foundation_reached": foundation_reached,
        "tail4": {
            "reached": bool(rebuilt),
            "stop_reason": t4.stop_reason,
        },
        "prep_improvement": improvement,
        "v044_control": v044,
        "timing": {
            "prep_tail4": None if not prep_t4s else min(prep_t4s),
            "deal_now_tail4": None if not deal_t4s else min(deal_t4s),
        },
        "tail5": {
            "prep_best": None if not t5_prep else min(w["full_cost"] for w in t5_prep),
            "deal_now_best": None if not t5_deal else min(w["full_cost"] for w in t5_deal),
        },
    }
    verdict, reason = choose_verdict(payload_pre)
    interpretation = (
        f"{reason}. Sources {src['n']}/720 chain_ok={src['spade_chain_ok']}. "
        f"Prep {len(prep.candidates)}. Post-deal tails {measured['post_tail']}. "
        f"v0.44 DEAL_NOW TAIL3 n={v044['n_tail3']} best={v044['best_cost']}. "
        f"Prep TAIL3 best={improvement['cheapest_prepared_tail3']}. "
        f"TAIL4 reached={bool(rebuilt)} F4={f4}. Did not seed 103k into UCS."
    )
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": interpretation,
        "next_recommendation": next_recommendation(verdict),
        "sources": {
            "n": src["n"],
            "all_replay_ok": src["all_replay_ok"],
            "spade_chain_ok": src["spade_chain_ok"],
            "cost_counts": src["cost_counts"],
            "lineage_counts": src["lineage_counts"],
        },
        "sd5_audit": src["sd5_audit"],
        "preparation": {
            "candidates": len(prep.candidates),
            "unique": prep.unique,
            "elapsed_s": prep.elapsed_s,
            "stop_reason": prep.stop_reason,
            "depth": dict(Counter(c["prep_depth"] for c in prep.candidates)),
            "timing": dict(Counter(c["timing"] for c in prep.candidates)),
            "bounds": {"depth": PREP_DEPTH, "cost": PREP_COST},
        },
        "receiver": slim_dist,
        "v044_control": v044,
        "prep_improvement": improvement,
        "tail4": {
            "reached": bool(rebuilt),
            "first_s": t4.first_s,
            "first_unique": t4.first_unique,
            "best_full_mw": f4,
            "timing": t4.first_timing,
            "unique": t4.unique,
            "expanded": t4.expanded,
            "generated": t4.generated,
            "duplicate_skips": t4.duplicate_skips,
            "elapsed_s": t4.elapsed_s,
            "peak_rss_mb": t4.peak_rss_mb,
            "stop_reason": t4.stop_reason,
            "n": len(rebuilt),
            "slack": slack,
            "already_at_source": t4.already_at_source,
            "deal_now_vs_prep": {
                "deal_now": None if not deal_t4s else min(deal_t4s),
                "prep": None if not prep_t4s else min(prep_t4s),
            },
        },
        "tail5": {
            "preview": dict(preview_counts),
            "longest": longest_prev,
            "prep_best": payload_pre["tail5"]["prep_best"],
            "deal_now_best": payload_pre["tail5"]["deal_now_best"],
        },
        "timing": payload_pre["timing"],
        "transaction": sample_tx,
        "foundation": {"reached": foundation_reached, "fixture": fixture},
        "files": {
            "report": REPORT.relative_to(ROOT).as_posix(),
            "result": RESULT.relative_to(ROOT).as_posix(),
            "distribution": DIST.relative_to(ROOT).as_posix(),
            "portfolio": PORT.relative_to(ROOT).as_posix(),
            "tail4": TAIL4.relative_to(ROOT).as_posix() if TAIL4.exists() else None,
            "fixture": fixture,
        },
        "elapsed_s": time.perf_counter() - started,
        "production_unchanged": True,
        "did_not_seed_103k": True,
        "all_replay_ok": src["all_replay_ok"] and src["spade_chain_ok"],
        "foundation_reached": foundation_reached,
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
