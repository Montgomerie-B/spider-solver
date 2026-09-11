#!/usr/bin/env python3
"""v0.34: Gate 2 ratchet — first flip of AH above unique 9H.

Full accumulated MW cost is never reset.  SD4 never taken.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.packed_state import pack_state
from spider.simple_deal1_preview import stock_rows
from spider.simple_foundation_horizon import pretty_card
from spider.simple_gate1 import gate1_progress, search_gate1, verify_blocker_chain
from spider.simple_gate2 import (
    GLOBAL_LB_GATE2,
    global_lb_gate2_audit,
    one_move_gate2,
    search_gate2,
    verify_gate2_chain,
)
from spider.simple_h9_cut import mandatory_rank_status
from spider.simple_legacy_fd13_alternatives import legal_tableau_count
from spider.simple_progressive_solver import format_moves_text
from spider.simple_workspace_reachability import empty_column_indices, face_down_count

EXPERIMENT = "heart9_blocker_ratchet2_v0_34"
BASE_SHA = "35a3042c3afb44094f820519977f333459b0dbd3"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
V30 = ROOT / "docs" / "research" / "simple_progressive_foundation_horizon_v0_30.json"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
FIXTURE = ROOT / "solutions" / "4925153_v0_34_gate2_ah_best.moves.txt"
SPADE_BASE = 62
TIMING_MAP = {
    "HEART_BEFORE_SD3": "GATE2_BEFORE_SD3",
    "HEART_AFTER_IMMEDIATE_SD3": "GATE2_AFTER_IMMEDIATE_SD3",
    "HEART_AFTER_PREPARED_SD3": "GATE2_AFTER_PREPARED_SD3",
}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def opening_state() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL_PATH)))


def as_actions(raw):
    out = []
    for item in raw:
        if item == "deal" or item == ["deal"] or item == ("deal",):
            out.append(("deal",))
        else:
            out.append((int(item[0]), int(item[1]), int(item[2])))
    return out


def recover_spade_sources(opening: SpiderState):
    payload = json.loads(V30.read_text(encoding="utf-8"))
    exits = ((payload.get("groups") or {}).get("MIDDLE") or {}).get("foundation_exits") or []
    sources = []
    paths = []
    for rec in exits:
        full = as_actions(rec["full_actions"])
        end = opening.clone()
        cost = replay_actions(end, full)
        assert cost == SPADE_BASE
        sources.append(end)
        paths.append(full)
    return sources, paths


def harvest_gate1(opening, spade_sources, spade_paths, time_limit_s: float):
    print("HARVEST Gate-1 portfolio via v0.33 machinery", flush=True)
    result = search_gate1(
        spade_sources,
        spade_paths,
        directed=True,
        max_unique=500_000,
        time_limit_s=time_limit_s,
        rss_abort_mb=2 * 1024.0,
        harvest_slack=2,
        harvest_limit=256,
        lb=1,
    )
    portfolio = []
    seen = {}
    for rec in result.witnesses:
        full = list(spade_paths[rec["origin"]]) + as_actions(rec["actions"])
        end = opening.clone()
        cost = replay_actions(end, full)
        chain = verify_gate2_chain(end)
        prog = gate1_progress(end)
        ident = pack_state(end)
        item = {
            "ok": chain["valid"] and prog["fd_blockers"] == 2 and rec.get("top_face_up") == "8D",
            "full_cost": cost,
            "local_g": rec["g"],
            "gate1_band": cost,
            "timing": rec.get("timing"),
            "stock_rows": stock_rows(end),
            "sd3_done": stock_rows(end) < 3,
            "ordered_digest": ident.hex(),
            "full_actions": [list(a) if a != ("deal",) else ["deal"] for a in full],
            "origin": rec["origin"],
            "chain": chain,
        }
        prev = seen.get(ident)
        if prev is None or cost < prev:
            seen[ident] = cost
            portfolio.append((ident, item, end))
    # cheaper full cost dominates equal states
    best = {}
    states = []
    paths = []
    gs = []
    rows = []
    for ident, item, end in portfolio:
        if ident in best and item["full_cost"] >= best[ident]:
            continue
        best[ident] = item["full_cost"]
        states.append(end)
        paths.append(as_actions(item["full_actions"]))
        gs.append(item["full_cost"])
        rows.append(item)
    counts = {}
    for r in rows:
        counts[str(r["full_cost"])] = counts.get(str(r["full_cost"]), 0) + 1
    print(
        f"HARVEST n={len(rows)} costs={counts} first_t={result.first_gate1_s} unique={result.unique}",
        flush=True,
    )
    return rows, states, paths, gs, result


def choose_verdict(audit_ok, chain_ok, lb_ok, witnesses, b, proved, explosion):
    if not audit_ok:
        return "SOURCE_REPLAY_FAILURE", "Gate-1 portfolio could not be reconstructed"
    if not chain_ok:
        return "GATE2_CHAIN_INVALID", "AH is not the top face-down blocker at Gate 1"
    if not lb_ok:
        return "GATE2_GLOBAL_LOWER_BOUND_INVALID", "composed lower bound 71 did not survive audit"
    if witnesses and proved:
        return "GATE2_AH_REACHED_AND_COST_PROVED", f"Gate 2 at full MW {b} equals global LB 71 or UCS proof"
    if witnesses:
        return "GATE2_AH_REACHED", f"Gate 2 reached at best-known full MW {b}"
    if explosion:
        return "GATE2_AH_STATE_EXPLOSION", "resource limits bound before Gate 2"
    return "GATE2_AH_NOT_FOUND_IN_ENVELOPE", "no Gate-2 witness in the bounded search"


def next_recommendation(verdict: str) -> str:
    if verdict.startswith("GATE2_AH_REACHED"):
        return (
            "Carry the Gate-2 portfolio into Gate 3: first exposure of JH. "
            "Keep full accumulated MW. Do not jump to 9H or Heart 1, and do not take SD4."
        )
    return "Keep the ratchet. Do not return to whole-H9 or whole-Heart search."


def write_report(payload: dict) -> None:
    lines = [
        "# Spider Solver v0.34 — Gate 2 Ratchet: First AH Blocker Flip",
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
        "## 2. Sources",
        "",
        json.dumps(payload.get("sources") or {}, indent=2)[:2000],
        "",
        "## 3. Proof / fast path",
        "",
        json.dumps({"proof": payload.get("proof"), "fast_path": payload.get("fast_path")}, indent=2)[:4000],
        "",
        "## 4. Search",
        "",
        json.dumps(payload.get("search") or {}, indent=2)[:2500],
        "",
        "## 5. Optimality",
        "",
        json.dumps(payload.get("optimality") or {}, indent=2),
        "",
        "## 6. Boundary",
        "",
        json.dumps(payload.get("boundary") or {}, indent=2)[:2500],
        "",
        "## 7. Condensation",
        "",
        json.dumps(payload.get("condensation") or {}, indent=2),
        "",
        "## 8. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
        "## Integrity",
        "",
        f"Verdict {payload.get('verdict')}. SD4 expanded={payload.get('sd4_expanded')}.",
        "Gate 2 terminal. Full MW preserved. No production change.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    started = time.perf_counter()
    spade_states, spade_paths = recover_spade_sources(opening)
    remaining = 1500.0 - (time.perf_counter() - started)
    rows, states, paths, gs, harvest = harvest_gate1(
        opening, spade_states, spade_paths, time_limit_s=min(180.0, max(30.0, remaining / 4))
    )
    audit_ok = len(states) >= 1 and all(r["ok"] for r in rows)
    chain_ok = all(r["chain"]["valid"] for r in rows)
    lb = global_lb_gate2_audit()
    print(f"PORTFOLIO n={len(states)} chain={chain_ok} LB={lb['global_lb']}", flush=True)

    fast = []
    for i, (st, g0, row) in enumerate(zip(states, gs, rows)):
        for hit in one_move_gate2(st):
            rec = dict(hit)
            rec["source_index"] = i
            rec["gate1_full_cost"] = g0
            rec["full_cost"] = g0 + hit["step_cost"]
            rec["gate1_band"] = row["gate1_band"]
            rec["full_actions"] = row["full_actions"] + [hit["action"]]
            fast.append(rec)
    fast.sort(key=lambda r: (r["full_cost"], r["gate1_full_cost"], r["source_index"]))
    fast_by_band = {}
    for rec in fast:
        fast_by_band.setdefault(str(rec["gate1_full_cost"]), 0)
        fast_by_band[str(rec["gate1_full_cost"])] += 1
    print(f"FAST_PATH hits={len(fast)} by_gate1_band={fast_by_band} cheapest={fast[0]['full_cost'] if fast else None}", flush=True)

    witnesses = []
    search_out = {"run": False}
    explosion = False
    b = None
    proved = False
    proof_method = None

    if fast:
        # materialize cheapest and harvest one-move portfolio in B/B+1/B+2
        b = min(r["full_cost"] for r in fast)
        proved = b == GLOBAL_LB_GATE2
        proof_method = "GLOBAL_LB_GATE2 == one-move B" if proved else "one-move best-known from retained Gate-1 sample"
        seen = {}
        for rec in fast:
            if rec["full_cost"] > b + 2:
                continue
            ident = rec["ordered_digest"]
            if ident in seen and rec["full_cost"] >= seen[ident]:
                continue
            seen[ident] = rec["full_cost"]
            end = opening.clone()
            full = as_actions(rec["full_actions"])
            cost = replay_actions(end, full)
            prog = gate1_progress(end)
            witnesses.append(
                {
                    "full_cost": cost,
                    "g": cost,
                    "continuation_cost": rec["step_cost"],
                    "gate1_band": rec["gate1_full_cost"],
                    "timing": "GATE2_BEFORE_SD3" if rec["stock_rows"] == 3 else "GATE2_AFTER_SD3",
                    "stock_rows": rec["stock_rows"],
                    "fd": face_down_count(end),
                    "foundations": len(end.foundations),
                    "empties": list(empty_column_indices(end)),
                    "ordered_digest": ident,
                    "top_face_up": rec["top_face_up"],
                    "face_up_col": [pretty_card(c) for c in end.columns[prog["column_0"]].face_up] if prog.get("column_0") is not None else [],
                    "face_down_col": [pretty_card(c) for c in end.columns[prog["column_0"]].face_down] if prog.get("column_0") is not None else [],
                    "fd_blockers": prog["fd_blockers"],
                    "mandatory_ranks": mandatory_rank_status(end),
                    "full_actions": rec["full_actions"],
                    "full_path_length": len(full),
                    "full_replay_ok": prog["fd_blockers"] == 1 and rec["top_face_up"] == "AH",
                    "one_move": True,
                    "sd3_action": rec["sd3"],
                }
            )
        witnesses.sort(key=lambda w: (w["full_cost"], w["full_path_length"]))
        witnesses = witnesses[:256]

    remaining = 1500.0 - (time.perf_counter() - started)
    if (not witnesses or (b is not None and b > GLOBAL_LB_GATE2)) and remaining > 10 and states:
        print("SEARCH START Gate-2 directed full-g", flush=True)
        search = search_gate2(
            states,
            paths,
            gs,
            directed=True,
            max_unique=500_000,
            time_limit_s=min(600.0, remaining - 20),
            rss_abort_mb=2 * 1024.0,
            harvest_slack=2,
            harvest_limit=256,
            lb=1,
        )
        explosion = search.stop_reason in ("time limit", "rss abort", "unique limit") and not search.witnesses
        search_out = {
            "run": True,
            "levels_reached": search.levels_reached,
            "unique": search.unique,
            "expanded": search.expanded,
            "generated": search.generated,
            "duplicate_skips": search.duplicate_skips,
            "first_s": search.first_gate1_s,
            "first_unique": search.first_gate1_unique,
            "first_g": search.first_gate1_g,
            "incumbent": search.incumbent,
            "stop_reason": search.stop_reason,
            "elapsed_s": search.elapsed_s,
            "peak_rss_mb": search.peak_rss_mb,
            "sd4_expanded": search.sd4_expanded,
            "witnesses": len(search.witnesses),
            "band_counts": search.band_counts,
        }
        print(
            f"SEARCH unique={search.unique} inc={search.incumbent} wit={len(search.witnesses)} "
            f"first_t={search.first_gate1_s} stop={search.stop_reason}",
            flush=True,
        )
        if search.witnesses:
            rebuilt = []
            for rec in search.witnesses:
                full = list(paths[rec["origin"]]) + as_actions(rec["actions"])
                end = opening.clone()
                cost = replay_actions(end, full)
                rebuilt.append(
                    {
                        **rec,
                        "full_cost": cost,
                        "g": rec["g"],
                        "continuation_cost": rec["g"] - gs[rec["origin"]],
                        "gate1_band": gs[rec["origin"]],
                        "timing": TIMING_MAP.get(rec.get("timing"), rec.get("timing")),
                        "full_actions": [list(a) if a != ("deal",) else ["deal"] for a in full],
                        "full_path_length": len(full),
                        "full_replay_ok": rec.get("top_face_up") == "AH" and rec.get("fd_blockers") == 1,
                    }
                )
            if not witnesses or (search.incumbent is not None and (b is None or search.incumbent < b)):
                witnesses = rebuilt
                b = min(w["full_cost"] for w in witnesses)
            if b == GLOBAL_LB_GATE2:
                proved = True
                proof_method = "GLOBAL_LB_GATE2 == B from directed search"
            elif b > GLOBAL_LB_GATE2:
                proof_method = "best-known from Gate-1 sample pending original-source UCS"

    remaining = 1500.0 - (time.perf_counter() - started)
    ucs_out = {"run": False}
    if witnesses and b is not None and b > GLOBAL_LB_GATE2 and remaining > 10:
        print("UCS from original Spade-1 sources targeting Gate 2 cheaper than B", flush=True)
        ucs = search_gate2(
            spade_states,
            spade_paths,
            [SPADE_BASE] * len(spade_states),
            directed=False,
            max_unique=750_000,
            time_limit_s=min(700.0, remaining),
            rss_abort_mb=2 * 1024.0,
            start_level=3,
            max_level=3,
            incumbent=b,
            cheaper_only=True,
            harvest_slack=0,
            harvest_limit=64,
            lb=1,
        )
        cheaper = bool(ucs.incumbent is not None and ucs.incumbent < b)
        ucs_out = {
            "run": True,
            "unique": ucs.unique,
            "expanded": ucs.expanded,
            "generated": ucs.generated,
            "incumbent": ucs.incumbent,
            "cheaper": cheaper,
            "stop_reason": ucs.stop_reason,
            "elapsed_s": ucs.elapsed_s,
            "peak_rss_mb": ucs.peak_rss_mb,
            "sd4_expanded": ucs.sd4_expanded,
            "witnesses": len(ucs.witnesses),
        }
        print(
            f"UCS unique={ucs.unique} cheaper={cheaper} inc={ucs.incumbent} stop={ucs.stop_reason}",
            flush=True,
        )
        if cheaper and ucs.witnesses:
            rebuilt = []
            for rec in ucs.witnesses:
                full = list(spade_paths[rec["origin"]]) + as_actions(rec["actions"])
                end = opening.clone()
                cost = replay_actions(end, full)
                rebuilt.append(
                    {
                        **rec,
                        "full_cost": cost,
                        "continuation_cost": rec["g"] - SPADE_BASE,
                        "gate1_band": None,
                        "timing": TIMING_MAP.get(rec.get("timing"), rec.get("timing")),
                        "full_actions": [list(a) if a != ("deal",) else ["deal"] for a in full],
                        "full_path_length": len(full),
                        "full_replay_ok": rec.get("top_face_up") == "AH" and rec.get("fd_blockers") == 1,
                    }
                )
            witnesses = rebuilt
            b = min(w["full_cost"] for w in witnesses)
            proved = b == GLOBAL_LB_GATE2
            proof_method = "UCS from original Spade-1 sources found cheaper Gate 2"
        elif ucs.stop_reason in ("frontier empty", "complete", "max level"):
            proved = True
            proof_method = (
                "UCS from original Spade-1 sources: no Gate-2 with full MW < B; B is global min"
            )
        else:
            proved = False
            proof_method = f"UCS incomplete ({ucs.stop_reason}); B is best-known only"

    if witnesses and b == GLOBAL_LB_GATE2:
        proved = True
        proof_method = proof_method or "GLOBAL_LB_GATE2 == B"

    first = min(witnesses, key=lambda w: (w["full_cost"], w.get("full_path_length", 10**9))) if witnesses else None
    fixture = None
    if first:
        FIXTURE.write_text(
            format_moves_text(
                as_actions(first["full_actions"]),
                header=f"# v0.34 Gate 2 AH\n# full_mw: {first['full_cost']}\n# timing: {first.get('timing')}",
            ),
            encoding="utf-8",
        )
        first["fixture"] = FIXTURE.relative_to(ROOT).as_posix()
        fixture = first["fixture"]

    bands = {}
    for w in witnesses:
        bands[str(w["full_cost"])] = bands.get(str(w["full_cost"]), 0) + 1
    by_g1 = {}
    for w in witnesses:
        by_g1[str(w.get("gate1_band"))] = by_g1.get(str(w.get("gate1_band")), 0) + 1

    verdict, reason = choose_verdict(audit_ok, chain_ok, lb["valid"], witnesses, b, proved, explosion)
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": "agent/heart9-blocker-ratchet2-v0-34",
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": reason,
        "next_recommendation": next_recommendation(verdict),
        "sources": {
            "n": len(rows),
            "cost_counts": {k: sum(1 for r in rows if r["full_cost"] == int(k)) for k in sorted({r["full_cost"] for r in rows})},
            "exact_dedup": len(states),
            "all_ok": audit_ok,
        },
        "proof": {"gate2_chain_ok": chain_ok, "global_lb": lb, "b_equals_bound": b == GLOBAL_LB_GATE2},
        "fast_path": {
            "hits": len(fast),
            "by_gate1_band": fast_by_band,
            "cheapest": None if not fast else fast[0]["full_cost"],
        },
        "search": search_out,
        "optimality": {
            "b": b,
            "proved": proved,
            "method": proof_method,
            "ucs": ucs_out,
            "note": "B==71 is global via LB. B>71 needs original-source UCS to prove.",
        },
        "min_path": None if not first else first.get("full_path_length"),
        "min_mw": None if not first else first.get("full_cost"),
        "continuation_cost": None if not first else first.get("continuation_cost"),
        "stock_at_gate": None if not first else first.get("stock_rows"),
        "fd_at_gate": None if not first else first.get("fd"),
        "full_replay_ok": bool(witnesses) and all(w.get("full_replay_ok") for w in witnesses),
        "fixture": fixture,
        "boundary": first,
        "bands": bands,
        "by_gate1_band": by_g1,
        "portfolio": len(witnesses),
        "timings": sorted({w.get("timing") for w in witnesses if w.get("timing")}),
        "condensation": {
            "v32_unique": 198303,
            "v32_s": 900,
            "v32_h9": False,
            "v33_first_unique": 72,
            "v33_first_s": 0.17,
            "v34_first_unique": search_out.get("first_unique") if search_out.get("run") else (1 if fast else None),
            "v34_first_s": search_out.get("first_s") if search_out.get("run") else (0.0 if fast else None),
            "v34_gate2": bool(witnesses),
            "v34_b": b,
        },
        "sd4_expanded": bool((search_out or {}).get("sd4_expanded")),
        "elapsed_s": time.perf_counter() - started,
        "gate2_terminal": True,
        "production_unchanged": True,
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
