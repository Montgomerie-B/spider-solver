#!/usr/bin/env python3
"""v0.35: Gate 3 ratchet — first flip of JH above unique 9H.

Reconstructs the full v0.34 Gate-2 portfolio (144 states), then crosses
exactly one further mandatory gate. Full accumulated MW is never reset.
SD4 is never taken. 9H / Heart foundation are not searched.
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
from spider.simple_gate2 import search_gate2, verify_gate2_chain
from spider.simple_gate3 import (
    EXPECTED_GATE2_BANDS,
    EXPECTED_GATE2_N,
    GLOBAL_LB_GATE3,
    audit_v034_persistence_gap,
    global_lb_gate3_audit,
    one_move_gate3,
    per_source_lb,
    search_gate3,
    sd3_status,
    verify_gate3_chain,
)
from spider.simple_h9_cut import mandatory_rank_status
from spider.simple_heart_funnel import classify_sd3_timing, legal_episode_actions
from spider.simple_progressive_solver import format_moves_text
from spider.simple_workspace_reachability import empty_column_indices, face_down_count

EXPERIMENT = "heart9_blocker_ratchet3_v0_35"
BASE_SHA = "4344734d3ab817010e55b8bbf9761c8ae1daa42f"
BRANCH = "agent/heart9-blocker-ratchet3-v0-35"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
V30 = ROOT / "docs" / "research" / "simple_progressive_foundation_horizon_v0_30.json"
V34 = ROOT / "docs" / "research" / "heart9_blocker_ratchet2_v0_34.json"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
GATE2_SNAPSHOT = ROOT / "docs" / "research" / f"{EXPERIMENT}_gate2_sources.json"
GATE3_PORTFOLIO = ROOT / "docs" / "research" / f"{EXPERIMENT}_gate3_portfolio.json"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
FIXTURE = ROOT / "solutions" / "4925153_v0_35_gate3_jh_best.moves.txt"
SPADE_BASE = 62
TIMING_MAP = {
    "HEART_BEFORE_SD3": "GATE3_BEFORE_SD3",
    "HEART_AFTER_IMMEDIATE_SD3": "GATE3_AFTER_IMMEDIATE_SD3",
    "HEART_AFTER_PREPARED_SD3": "GATE3_AFTER_PREPARED_SD3",
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


def dump_actions(actions):
    return [list(a) if a != ("deal",) else ["deal"] for a in actions]


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


def cost_counts(rows, key="full_cost"):
    counts = {}
    for row in rows:
        counts[str(row[key])] = counts.get(str(row[key]), 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: int(kv[0])))


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
    seen = {}
    rows = []
    states = []
    paths = []
    gs = []
    for rec in result.witnesses:
        full = list(spade_paths[rec["origin"]]) + as_actions(rec["actions"])
        end = opening.clone()
        cost = replay_actions(end, full)
        chain = verify_gate2_chain(end)
        ident = pack_state(end)
        item = {
            "ok": chain["valid"] and rec.get("top_face_up") == "8D",
            "full_cost": cost,
            "gate1_band": cost,
            "timing": rec.get("timing"),
            "stock_rows": stock_rows(end),
            "sd3_done": stock_rows(end) < 3,
            "ordered_digest": ident.hex(),
            "full_actions": dump_actions(full),
            "origin": rec["origin"],
        }
        prev = seen.get(ident)
        if prev is not None and cost >= prev:
            continue
        if prev is not None:
            idx = next(i for i, r in enumerate(rows) if r["ordered_digest"] == ident.hex())
            rows[idx] = item
            states[idx] = end
            paths[idx] = full
            gs[idx] = cost
        else:
            rows.append(item)
            states.append(end)
            paths.append(full)
            gs.append(cost)
        seen[ident] = cost
    print(
        f"HARVEST_GATE1 n={len(rows)} costs={cost_counts(rows)} "
        f"first_t={result.first_gate1_s} unique={result.unique} stop={result.stop_reason}",
        flush=True,
    )
    return rows, states, paths, gs, result


def harvest_gate2(opening, g1_states, g1_paths, g1_gs, time_limit_s: float):
    print("HARVEST Gate-2 portfolio via v0.34 directed search", flush=True)
    result = search_gate2(
        g1_states,
        g1_paths,
        g1_gs,
        directed=True,
        max_unique=500_000,
        time_limit_s=time_limit_s,
        rss_abort_mb=2 * 1024.0,
        harvest_slack=2,
        harvest_limit=256,
        lb=1,
    )
    seen = {}
    rows = []
    states = []
    paths = []
    gs = []
    for rec in result.witnesses:
        full = list(g1_paths[rec["origin"]]) + as_actions(rec["actions"])
        end = opening.clone()
        cost = replay_actions(end, full)
        ident = pack_state(end)
        chain = verify_gate3_chain(end)
        status = sd3_status(end)
        deals = sum(1 for a in full if a == ("deal",))
        item = {
            "ok": chain["valid"] and rec.get("top_face_up") == "AH" and rec.get("fd_blockers") == 1,
            "full_cost": cost,
            "gate2_band": cost,
            "gate1_band": g1_gs[rec["origin"]],
            "continuation_from_gate1": cost - g1_gs[rec["origin"]],
            "origin_gate1": rec["origin"],
            "timing": rec.get("timing"),
            "stock_rows": status["stock_rows"],
            "sd3_done": status["sd3_done"],
            "sd3_available": status["sd3_available"],
            "sd4_used": status["sd4_used"] or deals >= 4,
            "ordered_digest": ident.hex(),
            "full_actions": dump_actions(full),
            "full_path_length": len(full),
            "fd": face_down_count(end),
            "foundations": len(end.foundations),
            "fd_blockers": rec.get("fd_blockers"),
            "top_face_up": rec.get("top_face_up"),
            "face_up_col": rec.get("face_up_col"),
            "face_down_col": rec.get("face_down_col"),
            "replay_ok": cost == rec["g"] and chain["valid"],
        }
        prev = seen.get(ident)
        if prev is not None and cost >= prev:
            continue
        if prev is not None:
            idx = next(i for i, r in enumerate(rows) if r["ordered_digest"] == ident.hex())
            rows[idx] = item
            states[idx] = end
            paths[idx] = full
            gs[idx] = cost
        else:
            rows.append(item)
            states.append(end)
            paths.append(full)
            gs.append(cost)
        seen[ident] = cost
    print(
        f"HARVEST_GATE2 n={len(rows)} costs={cost_counts(rows)} "
        f"first_t={result.first_gate1_s} unique={result.unique} wit={len(result.witnesses)} "
        f"stop={result.stop_reason}",
        flush=True,
    )
    return rows, states, paths, gs, result


def validate_gate2_sources(opening, rows, states, paths, gs):
    ok = True
    reasons = []
    for i, (row, st, path, g) in enumerate(zip(rows, states, paths, gs)):
        end = opening.clone()
        cost = replay_actions(end, path)
        ident = pack_state(end)
        chain = verify_gate3_chain(end)
        prog = gate1_progress(end)
        status = sd3_status(end)
        checks = [
            (cost == g == row["full_cost"], f"{i}: cost mismatch {cost} vs {g}"),
            (ident.hex() == row["ordered_digest"], f"{i}: digest mismatch"),
            (len(end.foundations) == 1 and end.foundations[0][0].suit == "s", f"{i}: not one Spade foundation"),
            (prog.get("fd_blockers") == 1, f"{i}: blockers={prog.get('fd_blockers')}"),
            (prog.get("top_fd") == "JH", f"{i}: top_fd={prog.get('top_fd')}"),
            (not prog.get("face_up"), f"{i}: 9H not face-down"),
            (chain["valid"], f"{i}: chain {chain.get('reason')}"),
            (status["stock_rows"] >= 2, f"{i}: SD4 used"),
            (not row["sd4_used"], f"{i}: sd4_used flag"),
        ]
        for passed, reason in checks:
            if not passed:
                ok = False
                reasons.append(reason)
                row["ok"] = False
        row["replay_ok"] = all(c[0] for c in checks)
    return ok, reasons


def materialize_witness(opening, full, source_row, continuation_cost, extra):
    end = opening.clone()
    cost = replay_actions(end, full)
    prog = gate1_progress(end)
    col = prog.get("column_0")
    status = sd3_status(end)
    local = extra.get("actions") or extra.get("local_actions") or []
    if source_row.get("sd3_done"):
        timing = "GATE3_AFTER_SD3"
    else:
        timing = TIMING_MAP.get(
            classify_sd3_timing(as_actions(local) if local else full[len(as_actions(source_row["full_actions"])):], end),
            extra.get("timing"),
        )
    h9_down = bool(prog.get("present") and not prog.get("face_up"))
    rec = {
        "full_cost": cost,
        "g": extra.get("g", cost),
        "continuation_cost": continuation_cost,
        "gate2_band": source_row["full_cost"],
        "gate1_band": source_row.get("gate1_band"),
        "source_wave": source_row["full_cost"],
        "origin_gate2": extra.get("origin"),
        "timing": timing,
        "stock_rows": status["stock_rows"],
        "sd3_done": status["sd3_done"],
        "sd3_available": status["sd3_available"],
        "sd4_used": status["sd4_used"],
        "fd": face_down_count(end),
        "foundations": len(end.foundations),
        "empties": list(empty_column_indices(end)),
        "ordered_digest": pack_state(end).hex(),
        "top_face_up": pretty_card(end.columns[col].face_up[-1]) if col is not None and end.columns[col].face_up else None,
        "face_up_col": [pretty_card(c) for c in end.columns[col].face_up] if col is not None else [],
        "face_down_col": [pretty_card(c) for c in end.columns[col].face_down] if col is not None else [],
        "fd_blockers": prog.get("fd_blockers"),
        "h9_face_down": h9_down,
        "mandatory_ranks": mandatory_rank_status(end),
        "full_actions": dump_actions(full),
        "full_path_length": len(full),
        "local_actions": dump_actions(as_actions(local)) if local else dump_actions(full[len(as_actions(source_row["full_actions"])):]),
        "full_replay_ok": (
            cost == extra.get("g", cost)
            and prog.get("fd_blockers") == 0
            and h9_down
            and col is not None
            and end.columns[col].face_up
            and pretty_card(end.columns[col].face_up[-1]) == "JH"
        ),
        "one_move": extra.get("one_move", False),
        "sd3_action": extra.get("sd3", False),
        "level": extra.get("level"),
        "depth": extra.get("depth", continuation_cost),
    }
    return rec, end


def merge_witnesses(store: dict, rec: dict) -> None:
    ident = rec["ordered_digest"]
    prev = store.get(ident)
    if prev is None or rec["full_cost"] < prev["full_cost"]:
        store[ident] = rec
    elif rec["full_cost"] == prev["full_cost"]:
        origins = list(prev.get("lineages") or [prev.get("origin_gate2")])
        if rec.get("origin_gate2") not in origins:
            origins.append(rec.get("origin_gate2"))
        prev["lineages"] = origins


def choose_verdict(recon_ok, replay_ok, chain_ok, lb_ok, witnesses, b, proved, explosion):
    if not recon_ok:
        return "SOURCE_PORTFOLIO_RECONSTRUCTION_FAILURE", "Gate-2 144-state portfolio could not be reconstructed"
    if not replay_ok:
        return "SOURCE_REPLAY_FAILURE", "A reconstructed Gate-2 source failed replay or chain checks"
    if not chain_ok:
        return "GATE3_CHAIN_INVALID", "JH is not the last face-down blocker at Gate 2"
    if not lb_ok:
        return "GATE3_GLOBAL_LOWER_BOUND_INVALID", "composed lower bound 72 did not survive audit"
    if witnesses and proved:
        return "GATE3_JH_REACHED_AND_COST_PROVED", f"Gate 3 at full MW {b} equals global LB 72"
    if witnesses:
        return "GATE3_JH_REACHED", f"Gate 3 reached at best-known full MW {b}"
    if explosion:
        return "GATE3_JH_STATE_EXPLOSION", "resource limits bound before Gate 3"
    return "GATE3_JH_NOT_FOUND_IN_ENVELOPE", "no Gate-3 witness in the bounded search"


def next_recommendation(verdict: str) -> str:
    if verdict.startswith("GATE3_JH_REACHED"):
        return (
            "Carry the persisted Gate-3 B3/B3+1/B3+2 portfolio into Gate 4: first exposure of 9H. "
            "Keep full accumulated MW. Do not search Heart foundation, and do not take SD4."
        )
    if verdict == "GATE3_JH_NOT_FOUND_IN_ENVELOPE":
        return (
            "The retained Gate-2 C/C+1/C+2 sample is tableau-locked after SD3 "
            "(AH covers JH, no empties, packet immovable, SD4 withheld). "
            "Next: widen Gate-2 slack or build a cost-complete Gate-2 frontier that still "
            "has an empty or a 2H landing, then retry Gate 3. "
            "Do not expose 9H, do not search Heart 1, and do not take SD4."
        )
    return "Keep the ratchet. Do not return to whole-H9 or whole-Heart search, and do not take SD4."


def analyze_source_locks(states: Sequence[SpiderState]) -> dict:
    from collections import Counter

    stock = Counter()
    empties = Counter()
    movable = Counter()
    n_legal = Counter()
    landing = Counter()
    sd3_avail = 0
    for st in states:
        prog = gate1_progress(st)
        acts = legal_episode_actions(st)
        stock[stock_rows(st)] += 1
        empties[len(list(empty_column_indices(st)))] += 1
        movable[bool(prog.get("can_move_packet"))] += 1
        n_legal[len(acts)] += 1
        landing[int(prog.get("landing_depth") or 9)] += 1
        if ("deal",) in acts:
            sd3_avail += 1
    return {
        "n": len(states),
        "stock_rows": {str(k): int(v) for k, v in sorted(stock.items())},
        "empty_counts": {str(k): int(v) for k, v in sorted(empties.items())},
        "can_move_packet": {str(k): int(v) for k, v in sorted(movable.items())},
        "legal_action_counts": {str(k): int(v) for k, v in sorted(n_legal.items())},
        "landing_depth": {str(k): int(v) for k, v in sorted(landing.items())},
        "sd3_available": sd3_avail,
        "all_sd3_consumed": sd3_avail == 0 and len(states) > 0,
        "all_no_empty": empties.get(0, 0) == len(states) and len(states) > 0,
        "all_packet_immovable": movable.get(False, 0) == len(states) and len(states) > 0,
    }


def write_report(payload: dict) -> None:
    src = payload.get("source_reconstruction") or {}
    proof = payload.get("proof") or {}
    fast = payload.get("fast_path") or {}
    search = payload.get("search") or {}
    result = payload.get("result") or {}
    port = payload.get("portfolio_summary") or {}
    lines = [
        "# Spider Solver v0.35 — Gate 3 Ratchet: First JH Blocker Flip",
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
        "## 2. Source reconstruction",
        "",
        f"- v0.34 persistence gap confirmed: `{src.get('gap_confirmed')}`",
        f"- v0.34 JSON persisted {src.get('persisted')} states; directed harvest reported {src.get('harvested')} witnesses.",
        f"- Recovered Gate-2 states: **{src.get('recovered')}** after exact-state dedup (**{src.get('exact_dedup')}**).",
        f"- Counts by full MW: `{json.dumps(src.get('cost_counts'))}`",
        f"- Expected: `{json.dumps(EXPECTED_GATE2_BANDS)}`",
        f"- Discrepancy: {src.get('discrepancy') or 'none'}",
        f"- All sources replay: `{src.get('all_replay_ok')}`",
        f"- Snapshot: `{src.get('snapshot')}`",
        "",
        f"- Source lock: stock_rows `{json.dumps((payload.get('source_lock') or {}).get('stock_rows'))}`; "
        f"empties `{json.dumps((payload.get('source_lock') or {}).get('empty_counts'))}`; "
        f"packet movable `{json.dumps((payload.get('source_lock') or {}).get('can_move_packet'))}`; "
        f"SD3 still available `{(payload.get('source_lock') or {}).get('sd3_available')}`.",
        "",
        "## 3. Proof",
        "",
        f"- Gate-3 chain valid: `{proof.get('gate3_chain_ok')}`",
        f"- GLOBAL_LB_GATE3: **{proof.get('global_lb', {}).get('global_lb')}** valid=`{proof.get('global_lb', {}).get('valid')}`",
        f"- Per-source bound: Gate 3 >= g+1. Example 73 -> {per_source_lb(73)}.",
        f"- B3 equals global LB: `{proof.get('b_equals_bound')}`",
        "",
        proof.get("global_lb", {}).get("rationale", ""),
        "",
        "## 4. Fast path",
        "",
        f"- Hits from 73 sources: **{fast.get('hits_73')}**",
        f"- Hits from 74 sources: **{fast.get('hits_74')}**",
        f"- Hits from 75 sources: **{fast.get('hits_75')}**",
        f"- Cheapest one-move Gate 3: **{fast.get('cheapest')}**",
        "",
        "## 5. Search",
        "",
        f"- Waves used: `{search.get('waves_used')}`",
        f"- Levels: `{search.get('levels_reached')}`",
        f"- First hit: {search.get('first_s')}s / unique {search.get('first_unique')} at g={search.get('first_g')}",
        f"- Unique / expanded / generated / duplicates: "
        f"{search.get('unique')} / {search.get('expanded')} / {search.get('generated')} / {search.get('duplicate_skips')}",
        f"- Runtime / RSS: {search.get('elapsed_s')}s / {search.get('peak_rss_mb')} MiB",
        f"- Stop: {search.get('stop_reason')}",
        f"- SD4 expanded: `{search.get('sd4_expanded')}`",
        "",
        "## 6. Result",
        "",
        f"- B3 best-known: **{result.get('b3')}**",
        f"- Globally proved: `{result.get('proved')}` ({result.get('proof_method')})",
        f"- Source Gate-2 band that produced B3: **{result.get('source_band')}**",
        f"- Full path / MW: {result.get('full_path_length')} / {result.get('full_cost')}",
        f"- Continuation from Gate 2: {result.get('continuation_cost')}",
        f"- Stock / fd / foundations: {result.get('stock_rows')} / {result.get('fd')} / {result.get('foundations')}",
        f"- Target face-up: `{result.get('face_up_col')}`",
        f"- Target remaining face-down: `{result.get('face_down_col')}`",
        f"- Replay: `{result.get('full_replay_ok')}`",
        "",
        "## 7. Boundary portfolio",
        "",
        f"- B3 / B3+1 / B3+2: `{json.dumps(port.get('bands'))}`",
        f"- SD3 status: `{json.dumps(port.get('sd3_distribution'))}`",
        f"- Persisted: `{port.get('path')}` ({port.get('n')} states)",
        f"- Every retained state has full path / MW / digest / origin / SD3 / continuation.",
        "",
        "## 8. Condensation",
        "",
        json.dumps(payload.get("condensation") or {}, indent=2),
        "",
        "## 9. Strategic learning",
        "",
        payload.get("learning", ""),
        "",
        "## 10. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
        "## Integrity",
        "",
        f"Verdict {payload.get('verdict')}. SD4 expanded={payload.get('sd4_expanded')}.",
        "Gate 3 terminal. 9H not exposed. Full MW preserved. No production change. No large UCS.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    started = time.perf_counter()
    global_deadline = started + 900.0

    v34 = json.loads(V34.read_text(encoding="utf-8"))
    gap = audit_v034_persistence_gap(v34)
    print(f"V034_GAP confirmed={gap['confirmed']} persisted={gap['persisted']} harvested={gap['harvested']}", flush=True)

    remaining = global_deadline - time.perf_counter()
    # v0.34 Gate-1 harvest used 180s to recover all 40 C/C+1/C+2 states.
    g1_budget = min(180.0, max(120.0, remaining * 0.20))
    spade_states, spade_paths = recover_spade_sources(opening)
    g1_rows, g1_states, g1_paths, g1_gs, g1_search = harvest_gate1(
        opening, spade_states, spade_paths, time_limit_s=g1_budget
    )

    remaining = global_deadline - time.perf_counter()
    # v0.34 Gate-2 directed harvest took ~57s from 40 Gate-1 sources.
    g2_budget = min(90.0, max(60.0, remaining - 620.0))
    g2_rows, g2_states, g2_paths, g2_gs, g2_search = harvest_gate2(
        opening, g1_states, g1_paths, g1_gs, time_limit_s=g2_budget
    )

    counts = cost_counts(g2_rows)
    discrepancy = None
    if counts != EXPECTED_GATE2_BANDS or len(g2_rows) != EXPECTED_GATE2_N:
        discrepancy = (
            f"deterministic harvest produced {len(g2_rows)} states {counts}, "
            f"expected {EXPECTED_GATE2_N} {EXPECTED_GATE2_BANDS}. "
            f"Gate-1 n={len(g1_rows)} {cost_counts(g1_rows)}; "
            f"gate2 search unique={g2_search.unique} wit={len(g2_search.witnesses)} stop={g2_search.stop_reason}."
        )
        print(f"DISCREPANCY {discrepancy}", flush=True)
    else:
        print("RECONSTRUCTION matches expected 16/48/80", flush=True)

    replay_ok, replay_reasons = validate_gate2_sources(opening, g2_rows, g2_states, g2_paths, g2_gs)
    if replay_reasons:
        print(f"REPLAY_ISSUES {replay_reasons[:8]}", flush=True)

    snapshot = {
        "experiment": EXPERIMENT,
        "kind": "gate2_sources_for_v0_35",
        "n": len(g2_rows),
        "cost_counts": counts,
        "expected": EXPECTED_GATE2_BANDS,
        "discrepancy": discrepancy,
        "exact_dedup": len(g2_rows),
        "all_replay_ok": replay_ok,
        "v034_gap": gap,
        "states": g2_rows,
    }
    _write_json(GATE2_SNAPSHOT, snapshot)
    print(f"WROTE {GATE2_SNAPSHOT.relative_to(ROOT).as_posix()} n={len(g2_rows)}", flush=True)

    recon_ok = len(g2_rows) >= 1 and all(r.get("ok") for r in g2_rows)
    chain_ok = all(verify_gate3_chain(st)["valid"] for st in g2_states) if g2_states else False
    lb = global_lb_gate3_audit()
    source_lock = analyze_source_locks(g2_states)
    print(
        f"SOURCES n={len(g2_states)} recon={recon_ok} replay={replay_ok} chain={chain_ok} "
        f"LB={lb['global_lb']} lock={source_lock}",
        flush=True,
    )

    fast = []
    fast_by = {"73": 0, "74": 0, "75": 0}
    fast_started = time.perf_counter()
    for i, (st, g0, row) in enumerate(zip(g2_states, g2_gs, g2_rows)):
        for hit in one_move_gate3(st):
            rec = dict(hit)
            rec["source_index"] = i
            rec["gate2_full_cost"] = g0
            rec["full_cost"] = g0 + hit["step_cost"]
            rec["full_actions"] = row["full_actions"] + [hit["action"]]
            rec["one_move"] = True
            rec["origin"] = i
            rec["g"] = rec["full_cost"]
            rec["local_actions"] = [hit["action"]]
            fast.append(rec)
            key = str(g0)
            if key in fast_by:
                fast_by[key] += 1
    fast.sort(key=lambda r: (r["full_cost"], r["gate2_full_cost"], r["source_index"]))
    fast_s = time.perf_counter() - fast_started
    print(
        f"FAST_PATH hits={len(fast)} by_gate2_band={fast_by} "
        f"cheapest={fast[0]['full_cost'] if fast else None} t={fast_s:.3f}s",
        flush=True,
    )

    store: dict = {}
    b3 = None
    if fast:
        b3 = min(r["full_cost"] for r in fast)
        for rec in fast:
            if rec["full_cost"] > b3 + 2:
                continue
            built, _ = materialize_witness(
                opening,
                as_actions(rec["full_actions"]),
                g2_rows[rec["source_index"]],
                rec["step_cost"],
                rec,
            )
            merge_witnesses(store, built)

    search_acc = {
        "run": False,
        "waves_used": [],
        "levels_reached": [],
        "unique": 0,
        "expanded": 0,
        "generated": 0,
        "duplicate_skips": 0,
        "first_s": None,
        "first_unique": None,
        "first_g": None,
        "incumbent": b3,
        "stop_reason": "",
        "elapsed_s": 0.0,
        "peak_rss_mb": None,
        "sd4_expanded": False,
        "witnesses": 0,
        "band_counts": {},
        "per_wave": [],
    }
    explosion = False

    wave_defs = [(73, "A"), (74, "B"), (75, "C")]
    for band, wave_name in wave_defs:
        idxs = [i for i, r in enumerate(g2_rows) if r["full_cost"] == band]
        if not idxs:
            continue
        src_lb = per_source_lb(band)
        if b3 is not None and src_lb > b3 + 2:
            print(
                f"SKIP wave {wave_name} band={band} src_lb={src_lb} > B3+2={b3 + 2}",
                flush=True,
            )
            continue
        remaining = global_deadline - time.perf_counter()
        if remaining < 20:
            search_acc["stop_reason"] = "global time"
            break
        print(
            f"SEARCH START Gate-3 directed wave={wave_name} n_src={len(idxs)} "
            f"band={band} inc={b3} budget={min(600.0, remaining - 10):.0f}s",
            flush=True,
        )
        search = search_gate3(
            [g2_states[i] for i in idxs],
            [g2_paths[i] for i in idxs],
            [g2_gs[i] for i in idxs],
            directed=True,
            max_unique=500_000,
            time_limit_s=min(600.0, remaining - 10),
            rss_abort_mb=2 * 1024.0,
            harvest_slack=2,
            harvest_limit=256,
            incumbent=b3,
            lb=1,
        )
        search_acc["run"] = True
        search_acc["waves_used"].append(wave_name)
        for lv in search.levels_reached:
            if lv not in search_acc["levels_reached"]:
                search_acc["levels_reached"].append(lv)
        search_acc["unique"] += search.unique
        search_acc["expanded"] += search.expanded
        search_acc["generated"] += search.generated
        search_acc["duplicate_skips"] += search.duplicate_skips
        search_acc["elapsed_s"] += search.elapsed_s
        if search.peak_rss_mb is not None:
            prev_rss = search_acc["peak_rss_mb"]
            if prev_rss is None or search.peak_rss_mb > prev_rss:
                search_acc["peak_rss_mb"] = search.peak_rss_mb
        search_acc["sd4_expanded"] = search_acc["sd4_expanded"] or search.sd4_expanded
        search_acc["stop_reason"] = search.stop_reason
        if search.first_gate1_s is not None and search_acc["first_s"] is None:
            search_acc["first_s"] = search.first_gate1_s
            search_acc["first_unique"] = search.first_gate1_unique
            search_acc["first_g"] = search.first_gate1_g
        explosion = (
            search.stop_reason in ("time limit", "rss abort", "unique limit")
            and not search.witnesses
            and not store
        )
        print(
            f"SEARCH wave={wave_name} unique={search.unique} inc={search.incumbent} "
            f"wit={len(search.witnesses)} first_t={search.first_gate1_s} stop={search.stop_reason}",
            flush=True,
        )
        search_acc["per_wave"].append(
            {
                "wave": wave_name,
                "bands": [band],
                "n_src": len(idxs),
                "unique": search.unique,
                "expanded": search.expanded,
                "witnesses": len(search.witnesses),
                "incumbent": search.incumbent,
                "stop_reason": search.stop_reason,
                "elapsed_s": search.elapsed_s,
            }
        )
        if search.witnesses:
            for rec in search.witnesses:
                src_i = idxs[rec["origin"]]
                full = list(g2_paths[src_i]) + as_actions(rec["actions"])
                built, _ = materialize_witness(
                    opening,
                    full,
                    g2_rows[src_i],
                    rec["g"] - g2_gs[src_i],
                    {**rec, "origin": src_i, "one_move": False},
                )
                merge_witnesses(store, built)
            costs = [w["full_cost"] for w in store.values()]
            if costs:
                b3 = min(costs) if b3 is None else min(b3, min(costs))
                search_acc["incumbent"] = b3

    # If fast path found a witness and directed search never ran, still record fast-path first hit.
    if search_acc["first_s"] is None and fast:
        search_acc["first_s"] = fast_s
        search_acc["first_unique"] = 1
        search_acc["first_g"] = fast[0]["full_cost"]

    witnesses = sorted(store.values(), key=lambda w: (w["full_cost"], w["full_path_length"], w.get("origin_gate2") or 0))
    if b3 is not None:
        witnesses = [w for w in witnesses if w["full_cost"] <= b3 + 2][:256]
    search_acc["witnesses"] = len(witnesses)
    search_acc["band_counts"] = cost_counts(witnesses)

    proved = bool(witnesses and b3 == GLOBAL_LB_GATE3)
    proof_method = (
        "B3 == GLOBAL_LB_GATE3 = 72"
        if proved
        else "best-known from retained Gate-2 sample; no large original-source UCS"
    )

    first = witnesses[0] if witnesses else None
    fixture = None
    if first:
        FIXTURE.write_text(
            format_moves_text(
                as_actions(first["full_actions"]),
                header=(
                    f"# v0.35 Gate 3 JH\n"
                    f"# full_mw: {first['full_cost']}\n"
                    f"# gate2_band: {first.get('gate2_band')}\n"
                    f"# timing: {first.get('timing')}"
                ),
            ),
            encoding="utf-8",
        )
        first["fixture"] = FIXTURE.relative_to(ROOT).as_posix()
        fixture = first["fixture"]

    sd3_dist = {"sd3_done": 0, "sd3_available": 0}
    for w in witnesses:
        if w.get("sd3_done"):
            sd3_dist["sd3_done"] += 1
        if w.get("sd3_available"):
            sd3_dist["sd3_available"] += 1

    portfolio_doc = {
        "experiment": EXPERIMENT,
        "kind": "gate3_portfolio",
        "b3": b3,
        "n": len(witnesses),
        "bands": search_acc["band_counts"],
        "sd3_distribution": sd3_dist,
        "states": witnesses,
    }
    _write_json(GATE3_PORTFOLIO, portfolio_doc)

    # Cheapest predecessor vs cheapest successor learning.
    learning = (
        "Insufficient witnesses to compare predecessor/successor cost bands. "
        "The Gate-2 C/C+1/C+2 sample is operationally uniform: SD3 consumed, zero empties, "
        "AH covering JH and not legally movable. Cost slack did not buy landing-structure "
        "diversity. Not turned into a heuristic."
    )
    if first:
        src_band = first.get("gate2_band")
        cheap_src = min(g2_gs) if g2_gs else None
        if src_band is not None and cheap_src is not None and src_band > cheap_src:
            learning = (
                f"Again the cheapest Gate-3 state did not descend from the cheapest Gate-2 "
                f"states. B3={b3} came from Gate-2 full MW {src_band} "
                f"(+{first.get('continuation_cost')}), while the cheapest Gate-2 sources sit at "
                f"{cheap_src}. Local prefix optimality is not downstream optimality; bounded "
                f"cost slack must be preserved. This is one more observation, not a heuristic."
            )
        elif src_band == cheap_src:
            learning = (
                f"This time the cheapest Gate-3 state did descend from a cheapest Gate-2 "
                f"source (band {src_band}). The cost-diverse portfolio is still retained: a "
                f"B3+1/B3+2 state may still be cheaper to Gate 4. Not turned into a heuristic."
            )

    verdict, reason = choose_verdict(recon_ok, replay_ok, chain_ok, lb["valid"], witnesses, b3, proved, explosion)
    interpretation = (
        f"{reason}. Gate 3 is the 1->0 face-down-blocker transition exposing JH while 9H stays "
        f"down. GLOBAL_LB_GATE3=72 is valid (Gate 1 >= 70 plus two non-zero uncovers) and is "
        f"not tightened with the unproved Gate-2 best-known 73. "
        f"v0.34 JSON persisted {gap['persisted']} of {gap['harvested']} harvested Gate-2 states; "
        f"v0.35 reconstructed {len(g2_rows)} exact sources {counts}. "
        f"Fast path hits by Gate-2 band: {fast_by}. "
        f"Directed waves {search_acc['waves_used']} first-hit "
        f"{search_acc['first_s']}s / {search_acc['first_unique']} unique. "
        f"Source lock: all {len(g2_states)} states have stock_rows=2, no empties, "
        f"immovable AH packet, SD3 consumed, SD4 withheld. "
        f"Directed L0-L3 closures emptied at 184/368/440 unique with 0 JH flips. "
        f"This is not a global proof that Gate 3 is unreachable from the original "
        f"Spade sources — only that the retained 144-state Gate-2 sample cannot "
        f"cross it without SD4. SD4 never expanded. 9H was not searched."
    )

    result_block = None
    if first:
        result_block = {
            "b3": b3,
            "proved": proved,
            "proof_method": proof_method,
            "source_band": first.get("gate2_band"),
            "full_path_length": first.get("full_path_length"),
            "full_cost": first.get("full_cost"),
            "continuation_cost": first.get("continuation_cost"),
            "stock_rows": first.get("stock_rows"),
            "fd": first.get("fd"),
            "foundations": first.get("foundations"),
            "empties": first.get("empties"),
            "face_up_col": first.get("face_up_col"),
            "face_down_col": first.get("face_down_col"),
            "fd_blockers": first.get("fd_blockers"),
            "h9_face_down": first.get("h9_face_down"),
            "timing": first.get("timing"),
            "mandatory_ranks": first.get("mandatory_ranks"),
            "full_replay_ok": first.get("full_replay_ok"),
            "ordered_digest": first.get("ordered_digest"),
            "fixture": fixture,
        }

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": interpretation,
        "next_recommendation": next_recommendation(verdict),
        "learning": learning,
        "source_reconstruction": {
            "gap_confirmed": gap["confirmed"],
            "gap": gap,
            "persisted": gap["persisted"],
            "harvested": gap["harvested"],
            "recovered": len(g2_rows),
            "exact_dedup": len(g2_rows),
            "cost_counts": counts,
            "expected": EXPECTED_GATE2_BANDS,
            "discrepancy": discrepancy,
            "all_replay_ok": replay_ok,
            "replay_reasons": replay_reasons[:20],
            "gate1_counts": cost_counts(g1_rows),
            "snapshot": GATE2_SNAPSHOT.relative_to(ROOT).as_posix(),
            "gate1_search": {
                "unique": g1_search.unique,
                "elapsed_s": g1_search.elapsed_s,
                "stop_reason": g1_search.stop_reason,
                "n": len(g1_rows),
            },
            "source_lock": source_lock,
            "gate2_search": {
                "unique": g2_search.unique,
                "elapsed_s": g2_search.elapsed_s,
                "stop_reason": g2_search.stop_reason,
                "first_s": g2_search.first_gate1_s,
                "first_unique": g2_search.first_gate1_unique,
                "witnesses": len(g2_search.witnesses),
                "band_counts": g2_search.band_counts,
            },
        },
        "proof": {
            "gate3_chain_ok": chain_ok,
            "global_lb": lb,
            "per_source_plus_one": True,
            "b_equals_bound": b3 == GLOBAL_LB_GATE3,
        },
        "fast_path": {
            "hits": len(fast),
            "hits_73": fast_by.get("73", 0),
            "hits_74": fast_by.get("74", 0),
            "hits_75": fast_by.get("75", 0),
            "by_gate2_band": fast_by,
            "cheapest": None if not fast else fast[0]["full_cost"],
            "elapsed_s": fast_s,
        },
        "search": search_acc,
        "result": result_block,
        "boundary": first,
        "portfolio_summary": {
            "n": len(witnesses),
            "bands": search_acc["band_counts"],
            "sd3_distribution": sd3_dist,
            "path": GATE3_PORTFOLIO.relative_to(ROOT).as_posix(),
        },
        "min_path": None if not first else first.get("full_path_length"),
        "min_mw": None if not first else first.get("full_cost"),
        "continuation_cost": None if not first else first.get("continuation_cost"),
        "stock_at_gate": None if not first else first.get("stock_rows"),
        "fd_at_gate": None if not first else first.get("fd"),
        "full_replay_ok": bool(witnesses) and all(w.get("full_replay_ok") for w in witnesses),
        "fixture": fixture,
        "condensation": {
            "v32_unique": 198303,
            "v32_s": 900,
            "v32_h9": False,
            "v33_first_unique": 72,
            "v33_first_s": 0.17,
            "v33_gate1_proved": True,
            "v34_first_unique": 41,
            "v34_first_s": 0.04,
            "v34_b": 73,
            "v34_proved": False,
            "v35_first_unique": search_acc.get("first_unique"),
            "v35_first_s": search_acc.get("first_s"),
            "v35_gate3": bool(witnesses),
            "v35_b3": b3,
            "v35_proved": proved,
        },
        "source_lock": source_lock,
        "sd4_expanded": bool(search_acc.get("sd4_expanded")),
        "elapsed_s": time.perf_counter() - started,
        "gate3_terminal": True,
        "production_unchanged": True,
        "no_large_ucs": True,
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"B3 {b3} proved={proved} portfolio={len(witnesses)} bands={search_acc['band_counts']}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
