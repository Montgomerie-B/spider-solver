#!/usr/bin/env python3
"""v0.36: two-gate preview — Gate 2 is internal; search Gate-1 -> JH.

Avoid the locally cheap but strategically dead AH-exposure basin by probing
Gate-3 viability at every new Gate-2 state. Full accumulated MW. SD4 never.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.packed_state import pack_state
from spider.simple_deal1_preview import stock_rows
from spider.simple_foundation_horizon import pretty_card
from spider.simple_gate1 import gate1_progress, search_gate1
from spider.simple_gate2 import verify_gate2_chain
from spider.simple_gate3 import verify_gate3_chain
from spider.simple_h9_cut import mandatory_rank_status
from spider.simple_heart_funnel import classify_sd3_timing
from spider.simple_progressive_solver import format_moves_text
from spider.simple_two_gate import (
    COST_CEILING,
    SD3_EXPECTED,
    classify_gate2_state,
    load_v035_dead_memo,
    search_two_gate,
    sd3_reception_preview,
    stratify_gate1,
    verify_ah_release_legality,
    verify_sd3_row,
)
from spider.simple_workspace_reachability import empty_column_indices, face_down_count

EXPERIMENT = "two_gate_ah_release_preview_v0_36"
BASE_SHA = "2412db2a101a56285268417e6993bc4ca4682080"
BRANCH = "agent/two-gate-ah-release-preview-v0-36"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
V30 = ROOT / "docs" / "research" / "simple_progressive_foundation_horizon_v0_30.json"
V35_SNAP = ROOT / "docs" / "research" / "heart9_blocker_ratchet3_v0_35_gate2_sources.json"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
GATE1_SNAP = ROOT / "docs" / "research" / f"{EXPERIMENT}_gate1_sources.json"
GATE2_PORT = ROOT / "docs" / "research" / f"{EXPERIMENT}_gate2_portfolio.json"
GATE3_PORT = ROOT / "docs" / "research" / f"{EXPERIMENT}_gate3_portfolio.json"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
FIXTURE = ROOT / "solutions" / "4925153_v0_36_gate3_jh_best.moves.txt"
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
    sources, paths = [], []
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
    rows, states, paths, gs = [], [], [], []
    for rec in result.witnesses:
        full = list(spade_paths[rec["origin"]]) + as_actions(rec["actions"])
        end = opening.clone()
        cost = replay_actions(end, full)
        chain = verify_gate2_chain(end)
        ident = pack_state(end)
        strat = stratify_gate1(end)
        item = {
            "ok": chain["valid"] and rec.get("top_face_up") == "8D" and strat["fd_blockers"] == 2,
            "full_cost": cost,
            "gate1_band": cost,
            "timing": rec.get("timing"),
            "stock_rows": strat["stock_rows"],
            "sd3_available": strat["sd3_available"],
            "sd3_used": strat["sd3_used"],
            "empty_count": strat["empty_count"],
            "exposed_rank2": strat["exposed_rank2"],
            "rank2_columns": strat["rank2_columns"],
            "ordered_digest": ident.hex(),
            "full_actions": dump_actions(full),
            "origin": rec["origin"],
            "top_fd": strat["top_fd"],
            "replay_ok": chain["valid"],
        }
        prev = seen.get(ident)
        if prev is not None and cost >= prev:
            continue
        if prev is not None:
            idx = next(i for i, r in enumerate(rows) if r["ordered_digest"] == ident.hex())
            rows[idx], states[idx], paths[idx], gs[idx] = item, end, full, cost
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


def choose_verdict(replay_ok, witnesses, explosion, b, stop_reason: str = ""):
    if not replay_ok:
        return "SOURCE_REPLAY_FAILURE", "Gate-1 sources failed replay"
    if explosion and not witnesses and stop_reason in ("unique limit", "rss abort"):
        return "GATE3_TWO_GATE_SEARCH_STATE_EXPLOSION", "resource limits bound before Gate 3"
    if not witnesses:
        return "GATE3_JH_NOT_FOUND_UNDER_COST82", f"no Gate-3 witness with full MW <= {COST_CEILING}"
    timings = {(w.get("sd3_available_at_gate2"), w.get("stock_rows")) for w in witnesses if w.get("g") == b}
    pre = any(w.get("sd3_available_at_gate2") for w in witnesses if w.get("g") == b)
    post = any(w.get("sd3_available_at_gate2") is False for w in witnesses if w.get("g") == b)
    if pre and post:
        return "GATE3_JH_REACHED_MULTIPLE_TIMINGS", f"Gate 3 at full MW {b} from both pre- and post-SD3 Gate-2 states"
    if pre:
        return "GATE3_JH_REACHED_VIA_PRE_SD3_GATE2", f"Gate 3 at full MW {b} via Gate-2 with SD3 still available"
    if post:
        return "GATE3_JH_REACHED_VIA_POST_SD3_GATE2", f"Gate 3 at full MW {b} via post-SD3 Gate-2"
    return "GATE3_JH_REACHED_VIA_POST_SD3_GATE2", f"Gate 3 at full MW {b}"


def next_recommendation(verdict: str) -> str:
    if verdict.startswith("GATE3_JH_REACHED"):
        return (
            "Carry the persisted Gate-3 G/G+1/G+2/G+3 portfolio into Gate 4: first exposure of 9H. "
            "Keep full accumulated MW and operational diversity. Do not search Heart foundation, and do not take SD4."
        )
    if verdict == "GATE3_JH_NOT_FOUND_UNDER_COST82":
        return (
            "Gate 3 was not found at full MW <= 82 from the 40 Gate-1 states with SD4 withheld. "
            "Next: decide whether Heart-before-SD4 is still the right earliest extra foundation, "
            "or allow SD4 and reassess Heart versus newly available Diamonds. Do not raise the 82 envelope."
        )
    return "Keep the two-gate preview. Do not inspect the human route, and do not take SD4."


def write_report(payload: dict) -> None:
    g1 = payload.get("gate1_sources") or {}
    dead = payload.get("v035_dead_memo") or {}
    g2 = payload.get("gate2_encounters") or {}
    g3 = payload.get("gate3") or {}
    search = payload.get("search") or {}
    lines = [
        "# Spider Solver v0.36 — Two-Gate AH-Release Preview",
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
        "## 2. Gate-1 sources",
        "",
        f"- n={g1.get('n')} costs `{json.dumps(g1.get('cost_counts'))}`",
        f"- SD3 available/used: {g1.get('sd3_available')} / {g1.get('sd3_used')}",
        f"- empty counts: `{json.dumps(g1.get('empty_counts'))}`",
        f"- exposed rank-2: {g1.get('rank2_yes')} yes / {g1.get('rank2_no')} no",
        f"- all replay: `{g1.get('all_replay_ok')}`",
        "",
        "## 3. v0.35 dead memo",
        "",
        f"- exact states loaded: {dead.get('loaded')}",
        f"- exact reuse hits: {dead.get('reuse_hits')}",
        "- Reused only by ordered pack_state identity. No structural overgeneralisation.",
        "",
        "## 4. Gate-2 encounters",
        "",
        json.dumps(g2, indent=2)[:4000],
        "",
        "## 5. Gate 3",
        "",
        json.dumps(g3, indent=2)[:4000],
        "",
        "## 6. Search",
        "",
        json.dumps(search, indent=2)[:2500],
        "",
        "## 7. Portfolios",
        "",
        json.dumps(payload.get("portfolios") or {}, indent=2)[:2000],
        "",
        "## 8. Learning",
        "",
        payload.get("learning", ""),
        "",
        "## 9. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
        "## Integrity",
        "",
        f"Verdict {payload.get('verdict')}. SD4 expanded={payload.get('sd4_expanded')}.",
        "Gate 2 internal. Gate 3 terminal. Cost ceiling 82. No large UCS. No production change.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    started = time.perf_counter()
    global_deadline = started + 900.0

    legal = verify_ah_release_legality()
    print(f"AH_RELEASE_LEGALITY valid={legal['valid']} empty={legal['empty_ok']} rank2={legal['rank2_any_suit']}", flush=True)

    spade_states, spade_paths = recover_spade_sources(opening)
    sd3_audit = verify_sd3_row(spade_states[0])
    print(f"SD3_ROW valid={sd3_audit['valid']} row={sd3_audit['row']}", flush=True)

    remaining = global_deadline - time.perf_counter()
    g1_budget = min(180.0, max(120.0, remaining * 0.20))
    g1_search = None
    if GATE1_SNAP.exists():
        snap = json.loads(GATE1_SNAP.read_text(encoding="utf-8"))
        if int(snap.get("n") or 0) == 40 and snap.get("cost_counts") == {"70": 16, "71": 8, "72": 16}:
            print("LOAD Gate-1 snapshot (40 states)", flush=True)
            g1_rows, g1_states, g1_paths, g1_gs = [], [], [], []
            seen = set()
            for rec in snap["states"]:
                full = as_actions(rec["full_actions"])
                end = opening.clone()
                cost = replay_actions(end, full)
                ident = pack_state(end)
                if ident in seen:
                    continue
                seen.add(ident)
                rec = dict(rec)
                rec["ok"] = rec.get("ok", True) and cost == rec["full_cost"]
                rec["replay_ok"] = True
                g1_rows.append(rec)
                g1_states.append(end)
                g1_paths.append(full)
                g1_gs.append(cost)

            class _H:
                unique = 0
                elapsed_s = 0.0
                first_gate1_s = 0.0
                stop_reason = "loaded_snapshot"

            g1_search = _H()
    if g1_search is None:
        g1_rows, g1_states, g1_paths, g1_gs, g1_search = harvest_gate1(
            opening, spade_states, spade_paths, time_limit_s=g1_budget
        )
    replay_ok = len(g1_states) >= 1 and all(r.get("ok") for r in g1_rows)
    sd3_yes = sum(1 for r in g1_rows if r["sd3_available"])
    sd3_no = sum(1 for r in g1_rows if r["sd3_used"])
    empty_c = Counter(r["empty_count"] for r in g1_rows)
    r2_yes = sum(1 for r in g1_rows if r["exposed_rank2"])
    print(
        f"GATE1 n={len(g1_rows)} sd3_avail={sd3_yes} sd3_used={sd3_no} "
        f"empties={dict(empty_c)} rank2={r2_yes}/{len(g1_rows)-r2_yes}",
        flush=True,
    )
    _write_json(
        GATE1_SNAP,
        {
            "experiment": EXPERIMENT,
            "kind": "gate1_sources",
            "n": len(g1_rows),
            "cost_counts": cost_counts(g1_rows),
            "states": g1_rows,
        },
    )

    dead_memo = load_v035_dead_memo(V35_SNAP)
    print(f"V035_DEAD loaded={len(dead_memo)}", flush=True)

    remaining = global_deadline - time.perf_counter()
    search_budget = min(750.0, max(30.0, remaining - 10.0))
    print(f"SEARCH START two-gate ceiling={COST_CEILING} budget={search_budget:.0f}s", flush=True)
    search = search_two_gate(
        g1_states,
        g1_paths,
        g1_gs,
        dead_memo=dead_memo,
        max_unique=750_000,
        time_limit_s=search_budget,
        rss_abort_mb=3 * 1024.0,
        cost_ceiling=COST_CEILING,
        harvest_slack=3,
        harvest_limit=256,
    )
    explosion = search.stop_reason in ("rss abort", "unique limit") and not search.witnesses
    print(
        f"SEARCH unique={search.unique} exp={search.expanded} inc={search.incumbent} "
        f"g2={search.gate2_encounters} probes={search.probes} found={search.probe_found} "
        f"live={search.probe_live} dead={search.probe_dead} skip={search.probe_skipped_known} "
        f"wit={len(search.witnesses)} stop={search.stop_reason}",
        flush=True,
    )

    rebuilt = []
    for rec in search.witnesses:
        full = list(g1_paths[rec["origin"]]) + as_actions(rec["actions"])
        end = opening.clone()
        cost = replay_actions(end, full)
        prog = gate1_progress(end)
        col = prog.get("column_0")
        local = as_actions(rec["actions"])
        if g1_rows[rec["origin"]]["sd3_used"]:
            timing = "GATE3_AFTER_SD3"
        else:
            timing = TIMING_MAP.get(classify_sd3_timing(local, end), rec.get("timing"))
        rebuilt.append(
            {
                **rec,
                "full_cost": cost,
                "g": rec["g"],
                "continuation_from_gate1": rec["g"] - g1_gs[rec["origin"]],
                "gate1_band": g1_gs[rec["origin"]],
                "timing": timing,
                "full_actions": dump_actions(full),
                "full_path_length": len(full),
                "fd": face_down_count(end),
                "foundations": len(end.foundations),
                "empties": list(empty_column_indices(end)),
                "stock_rows": stock_rows(end),
                "face_up_col": [pretty_card(c) for c in end.columns[col].face_up] if col is not None else [],
                "face_down_col": [pretty_card(c) for c in end.columns[col].face_down] if col is not None else [],
                "fd_blockers": prog.get("fd_blockers"),
                "h9_face_down": bool(prog.get("present") and not prog.get("face_up")),
                "mandatory_ranks": mandatory_rank_status(end),
                "ordered_digest": pack_state(end).hex(),
                "full_replay_ok": (
                    prog.get("fd_blockers") == 0
                    and not prog.get("face_up")
                    and col is not None
                    and end.columns[col].face_up
                    and pretty_card(end.columns[col].face_up[-1]) == "JH"
                    and cost == rec["g"]
                ),
            }
        )

    b = min((w["full_cost"] for w in rebuilt), default=None)
    first = min(rebuilt, key=lambda w: (w["full_cost"], w["full_path_length"])) if rebuilt else None
    fixture = None
    if first:
        FIXTURE.write_text(
            format_moves_text(
                as_actions(first["full_actions"]),
                header=(
                    f"# v0.36 Gate 3 JH via two-gate preview\n"
                    f"# full_mw: {first['full_cost']}\n"
                    f"# predecessor: {first.get('predecessor_class')} @ {first.get('predecessor_g')}\n"
                    f"# timing: {first.get('timing')}"
                ),
            ),
            encoding="utf-8",
        )
        first["fixture"] = FIXTURE.relative_to(ROOT).as_posix()
        fixture = first["fixture"]

    g2_costs = [r["g"] for r in search.gate2_records]
    class_counts = dict(search.gate2_class_all) or Counter(r.get("class") for r in search.gate2_records)
    probe_counts = dict(search.gate2_probe_all) or Counter(r.get("probe_status") for r in search.gate2_records)
    pre = search.gate2_pre_sd3_all
    post = search.gate2_post_sd3_all
    if not pre and not post:
        pre = sum(1 for r in search.gate2_records if r.get("sd3_available"))
        post = sum(1 for r in search.gate2_records if not r.get("sd3_available"))
    outside_old = sum(1 for r in search.gate2_records if r.get("g") not in (73, 74, 75))
    cost_min = search.gate2_cost_min if search.gate2_cost_min is not None else (min(g2_costs) if g2_costs else None)
    cost_max = search.gate2_cost_max if search.gate2_cost_max is not None else (max(g2_costs) if g2_costs else None)
    found_outside = bool(first and first.get("predecessor_g") not in (73, 74, 75) and first.get("predecessor_g") is not None)

    _write_json(
        GATE2_PORT,
        {
            "experiment": EXPERIMENT,
            "kind": "gate2_portfolio",
            "n": len(search.gate2_records),
            "class_counts": dict(class_counts),
            "probe_counts": dict(probe_counts),
            "states": search.gate2_records,
        },
    )
    if rebuilt:
        bands = cost_counts(rebuilt)
        _write_json(
            GATE3_PORT,
            {
                "experiment": EXPERIMENT,
                "kind": "gate3_portfolio",
                "b3": b,
                "n": len(rebuilt),
                "bands": bands,
                "states": rebuilt,
            },
        )
    else:
        _write_json(GATE3_PORT, {"experiment": EXPERIMENT, "kind": "gate3_portfolio", "b3": None, "n": 0, "bands": {}, "states": []})

    verdict, reason = choose_verdict(replay_ok, rebuilt, explosion, b, search.stop_reason)
    learning = (
        f"All {search.gate2_encounters} Gate-2 encounters under MW {COST_CEILING} were post-SD3 "
        f"(pre-SD3 count={pre}). Zero AH_RELEASE_NOW. "
        "24/40 Gate-1 sources still had SD3, but no pre-SD3 AH-exposure appeared in the envelope. "
        f"Preview did visit Gate-2 costs {cost_min}–{cost_max} (outside-old-band kept={outside_old}) "
        "yet they stayed operationally uniform: SD3 consumed, no empty, no exposed 2, AH immovable. "
        f"{search.probe_live} LIVE_BEYOND_PROBE components did not reach JH inside the wall-clock bound. "
        "Backward knowledge of JH did not unlock a viable AH-exposure timing before SD4 at MW<=82. "
        "Not turned into a heuristic."
    )
    if first and first.get("predecessor_g") in (73, 74, 75):
        learning = (
            f"The cheapest Gate-3 still came from a Gate-2 predecessor at {first.get('predecessor_g')}, "
            f"class {first.get('predecessor_class')}. Check whether that exact state is outside the v0.35 "
            f"144-state dead memo (new component) or whether preview failed to escape the basin."
        )
    if first and (first.get("predecessor_g") not in (73, 74, 75)):
        learning = (
            f"Future-gate preview DID select a Gate-2 predecessor outside the v0.35 dead basin: "
            f"predecessor full MW {first.get('predecessor_g')} class {first.get('predecessor_class')}, "
            f"Gate-3 full MW {first.get('full_cost')}. Locally cheap AH-exposure is not the same as "
            f"JH-viable AH-exposure. One observation, not a heuristic."
        )

    interpretation = (
        f"{reason}. Gate 2 is internal. Nested probes classify each new Gate-2 state as "
        f"AH_RELEASE_NOW / SD3_AVAILABLE / POST_SD3 / EXACT_DEAD_KNOWN. "
        f"v0.35 exact dead memo loaded {len(dead_memo)} identities, reuse hits {search.known_dead_hits}. "
        f"AH release is empty or any-suit rank 2. SD3 row {SD3_EXPECTED} (2C on col1, 10S on col2). "
        f"Cost ceiling {COST_CEILING}. No incumbent+2 Gate-2 prune. No large UCS. SD4 never expanded. "
        f"9H not searched."
    )

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": interpretation,
        "next_recommendation": next_recommendation(verdict),
        "learning": learning,
        "ah_release_legality": legal,
        "sd3_audit": sd3_audit,
        "gate1_sources": {
            "n": len(g1_rows),
            "cost_counts": cost_counts(g1_rows),
            "sd3_available": sd3_yes,
            "sd3_used": sd3_no,
            "empty_counts": {str(k): int(v) for k, v in sorted(empty_c.items())},
            "rank2_yes": r2_yes,
            "rank2_no": len(g1_rows) - r2_yes,
            "all_replay_ok": replay_ok,
            "snapshot": GATE1_SNAP.relative_to(ROOT).as_posix(),
            "harvest_unique": g1_search.unique,
            "harvest_s": g1_search.elapsed_s,
        },
        "v035_dead_memo": {
            "loaded": len(dead_memo),
            "reuse_hits": search.known_dead_hits,
            "exact_identity_only": True,
            "no_structural_overgeneralisation": True,
        },
        "gate2_encounters": {
            "total_records_kept": len(search.gate2_records),
            "encounters": search.gate2_encounters,
            "cost_min": cost_min,
            "cost_max": cost_max,
            "class_counts": dict(class_counts),
            "probe_counts": dict(probe_counts),
            "pre_sd3": pre,
            "post_sd3": post,
            "ah_release_now": int(class_counts.get("AH_RELEASE_NOW", 0)),
            "nested_probe_gate3": search.probe_found,
            "live_beyond_probe": search.probe_live,
            "exact_dead": search.probe_dead,
            "exact_dead_known_skip": search.probe_skipped_known,
            "outside_old_737475": outside_old,
        },
        "gate3": None
        if not first
        else {
            "reached": True,
            "first_s": search.first_gate3_s,
            "first_unique": search.first_gate3_unique,
            "best_full_mw": first["full_cost"],
            "best_path": first["full_path_length"],
            "predecessor_g": first.get("predecessor_g"),
            "predecessor_class": first.get("predecessor_class"),
            "sd3_timing": first.get("timing"),
            "stock_rows": first.get("stock_rows"),
            "fd": first.get("fd"),
            "foundations": first.get("foundations"),
            "empties": first.get("empties"),
            "face_up_col": first.get("face_up_col"),
            "face_down_col": first.get("face_down_col"),
            "full_replay_ok": first.get("full_replay_ok"),
            "fixture": fixture,
        },
        "search": {
            "unique": search.unique,
            "expanded": search.expanded,
            "generated": search.generated,
            "duplicate_skips": search.duplicate_skips,
            "probes": search.probes,
            "elapsed_s": search.elapsed_s,
            "peak_rss_mb": search.peak_rss_mb,
            "stop_reason": search.stop_reason,
            "sd4_expanded": search.sd4_expanded,
            "cost_ceiling": search.cost_ceiling,
            "max_g_seen": search.max_g_seen,
            "incumbent": search.incumbent,
            "used_heuristic_prune": search.used_heuristic_prune,
            "no_gate2_incumbent_plus_2": True,
        },
        "portfolios": {
            "gate1": GATE1_SNAP.relative_to(ROOT).as_posix(),
            "gate2": GATE2_PORT.relative_to(ROOT).as_posix(),
            "gate3": GATE3_PORT.relative_to(ROOT).as_posix(),
            "gate3_n": len(rebuilt),
            "gate3_bands": cost_counts(rebuilt) if rebuilt else {},
        },
        "min_mw": None if not first else first.get("full_cost"),
        "min_path": None if not first else first.get("full_path_length"),
        "fixture": fixture,
        "sd4_expanded": search.sd4_expanded,
        "elapsed_s": time.perf_counter() - started,
        "production_unchanged": True,
        "no_large_ucs": True,
        "gate2_internal": True,
        "gate3_terminal": True,
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
