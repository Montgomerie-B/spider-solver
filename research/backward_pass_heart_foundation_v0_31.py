#!/usr/bin/env python3
"""v0.31: backward-pass Heart-1 foundation planner prototype.

SD4 is never taken.  Production solve_progressive is unchanged.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.packed_state import pack_state, permute_tableau_columns
from spider.simple_deal1_preview import stock_rows
from spider.simple_foundation_horizon import EXPECTED_SD5, material_horizon_audit, pretty_card
from spider.simple_heart_backward import build_dependency_map, future_stock_context
from spider.simple_heart_funnel import (
    cost_aware_heart_search,
    foundation_suits,
    heart_foundation_count,
    legal_episode_actions,
)
from spider.simple_legacy_fd13_alternatives import checkpoint_record, legal_tableau_count
from spider.simple_progressive_solver import apply_action, format_moves_text
from spider.simple_workspace_reachability import empty_column_indices, face_down_count, engine_tableau_actions

EXPERIMENT = "backward_pass_heart_foundation_v0_31"
BASE_SHA = "dc3a44f4974acd25b9dd539864d13e5bf4fe28ac"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
V30 = ROOT / "docs" / "research" / "simple_progressive_foundation_horizon_v0_30.json"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
FIXTURE = ROOT / "solutions" / "4925153_v0_31_heart_foundation.moves.txt"
TIMING_FIXTURES = {
    "HEART_BEFORE_SD3": ROOT / "solutions" / "4925153_v0_31_heart_before_sd3.moves.txt",
    "HEART_AFTER_IMMEDIATE_SD3": ROOT / "solutions" / "4925153_v0_31_heart_immediate_sd3.moves.txt",
    "HEART_AFTER_PREPARED_SD3": ROOT / "solutions" / "4925153_v0_31_heart_prepared_sd3.moves.txt",
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
            src, dst, k = item
            out.append((int(src), int(dst), int(k)))
    return out


def recover_spade_sources(opening: SpiderState):
    payload = json.loads(V30.read_text(encoding="utf-8"))
    exits = ((payload.get("groups") or {}).get("MIDDLE") or {}).get("foundation_exits") or []
    audited = []
    distinct = {}
    for index, rec in enumerate(exits):
        full = as_actions(rec["full_actions"])
        end = opening.clone()
        cost = replay_actions(end, full)
        suits = [run[0].suit for run in end.foundations if run]
        ok = (
            len(end.foundations) == 1
            and suits == ["s"]
            and stock_rows(end) == 3
            and sum(1 for a in full if a == ("deal",)) == 2
            and face_down_count(end) == 9
            and pack_state(end).hex() == rec["ordered_digest"]
        )
        cp = checkpoint_record(end, arm=f"spade_{index}", path_length=len(full), cost=cost, kind="SPADE1")
        audited.append(
            {
                "source_id": index,
                "ok": ok,
                "total_primitive_path": len(full),
                "mw_cost": cost,
                "deals": 2,
                "fd": cp["fd"],
                "stock_rows": stock_rows(end),
                "foundations": len(end.foundations),
                "foundation_suits": suits,
                "empties": list(empty_column_indices(end)),
                "legal_tableau": legal_tableau_count(end),
                "ordered_digest": pack_state(end).hex(),
                "full_actions": rec["full_actions"],
            }
        )
        print(
            f"SOURCE {index} ok={ok} path={len(full)} MW={cost} fd={cp['fd']} "
            f"empty={cp['empties']} legal={cp['legal_action_count']}",
            flush=True,
        )
        ident = pack_state(end)
        if ident not in distinct:
            distinct[ident] = {"state": end, "path": full, "source_id": index}
    return audited, distinct


def annotate_parks(opening: SpiderState, full_actions) -> list:
    walk = opening.clone()
    parks = []
    open_parks = {}
    for i, action in enumerate(full_actions):
        if action == ("deal",):
            apply_action(walk, action)
            continue
        src, dst, k = action
        dest_empty = walk.columns[dst].is_empty()
        src_up = len(walk.columns[src].face_up)
        apply_action(walk, action)
        if dest_empty:
            open_parks[dst] = {"creation_move": i, "src": src, "k": k, "whole_column": k == src_up}
        # resolution: a later move takes from a parked column onto a non-empty dest
        if src in open_parks and not dest_empty:
            rec = open_parks.pop(src)
            rec["resolved_move"] = i
            rec["lifetime"] = i - rec["creation_move"]
            rec["class"] = "SELF_LIQUIDATING" if rec["lifetime"] <= 4 else "GRACEFUL_RESOLUTION"
            rec["survived_sd3"] = False
            parks.append(rec)
    for col, rec in open_parks.items():
        rec["class"] = "UNRESOLVED_AT_TARGET"
        rec["lifetime"] = len(full_actions) - rec["creation_move"]
        parks.append(rec)
    return parks


def choose_verdict(horizon_ok, audit_ok, search, witnesses) -> tuple[str, str]:
    if not horizon_ok:
        return "BACKWARD_ANALYSIS_INCONSISTENT", "horizon map does not reproduce v0.30"
    if not audit_ok:
        return "SOURCE_REPLAY_FAILURE", "the four Spade-foundation sources could not be reconstructed"
    timings = {w["timing"] for w in witnesses}
    if len(timings) > 1:
        return "HEART_FOUNDATION_MULTIPLE_TIMINGS", f"Heart 1 found under timings {sorted(timings)}"
    if timings == {"HEART_BEFORE_SD3"}:
        return "HEART_FOUNDATION_BEFORE_SD3", "Heart 1 removed before SD3"
    if timings == {"HEART_AFTER_IMMEDIATE_SD3"}:
        return "HEART_FOUNDATION_AFTER_IMMEDIATE_SD3", "Heart 1 requires immediate SD3"
    if timings == {"HEART_AFTER_PREPARED_SD3"}:
        return "HEART_FOUNDATION_AFTER_PREPARED_SD3", "Heart 1 found after prepared SD3"
    if search.stop_reason in ("time limit", "rss abort", "unique limit"):
        return "HEART_TARGET_SEARCH_STATE_EXPLOSION", f"limits bound ({search.stop_reason}) before Heart 1"
    return "HEART_TARGET_NOT_FOUND_BEFORE_SD4", "explored funnel reached no Heart foundation before SD4"


def next_recommendation(verdict: str) -> str:
    if verdict.startswith("HEART_FOUNDATION"):
        return (
            "Heart 1 is FOUNDATION 2. Reassess remaining material horizons from that exact "
            "state. Do not automatically continue to Diamond. Do not take SD4 until the "
            "next target is chosen from the updated horizon."
        )
    if verdict == "HEART_TARGET_NOT_FOUND_BEFORE_SD4":
        return (
            "Heart 1 was not assembled before SD4 in the explored funnel. Next: either a "
            "wider exact search or a decision to take SD4 and re-select the target. "
            "Do not add a Heart heuristic to production."
        )
    if verdict == "HEART_TARGET_SEARCH_STATE_EXPLOSION":
        return "Keep the Heart-1 target and funnel; do not raise limits here and do not take SD4."
    if verdict == "SOURCE_REPLAY_FAILURE":
        return "Reconstruct the v0.30 Spade-1 sources before any Heart search."
    return "Keep the backward-pass foundation model. Do not revert to fd-count optimisation."


def write_report(payload: dict) -> None:
    h = payload.get("horizon") or {}
    fut = payload.get("future") or {}
    bw = payload.get("backward") or {}
    search = payload.get("search") or {}
    lines = [
        "# Spider Solver v0.31 — Backward-Pass Heart-1 Foundation Planner",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('verdict_reason', '')}",
        "",
        payload.get("interpretation", ""),
        "",
        f"- Branch: `{payload.get('branch')}`",
        f"- Base SHA: `{BASE_SHA}`",
        "- Target: first Heart foundation. SD4 never expanded.",
        "",
        "## 2. Horizon / target",
        "",
        f"- Remaining rows: SD3={fut.get('sd3')} SD4={fut.get('sd4')} SD5={fut.get('sd5')}",
        f"- Unlocks: {fut.get('unlocks')}",
        f"- Target: {fut.get('target')} — {fut.get('target_reason')}",
        f"- Opening horizon ok: {h.get('expected_ok')} SD5={h.get('sd5')}",
        "",
        "## 3. Backward pass",
        "",
        f"- hard obligations: {bw.get('hard_obligation_count')} alternative: {bw.get('alternative_obligation_count')}",
        f"- duplicate ranks: {((bw.get('copy_alternatives') or {}).get('ranks_with_duplicates'))}",
        f"- hard: {json.dumps((bw.get('obligations') or {}).get('hard') or [], indent=2)[:2500]}",
        f"- alternative copies: {json.dumps((bw.get('obligations') or {}).get('alternative') or [], indent=2)[:1500]}",
        f"- components: {json.dumps(bw.get('components') or [], indent=2)[:2000]}",
        f"- SD3 reception: {json.dumps(bw.get('sd3_reception') or {}, indent=2)[:2000]}",
        f"- admissible MW lower bound: {(bw.get('lower_bound') or {}).get('mw_lower_bound')} "
        f"{(bw.get('lower_bound') or {}).get('rationale')}",
        "",
        "## 4. Search",
        "",
        f"- levels={search.get('levels_reached')} unique={search.get('unique')} expanded={search.get('expanded')} "
        f"generated={search.get('generated')} dups={search.get('duplicate_skips')} reopens={search.get('cheaper_reopens')}",
        f"- zero_cost={search.get('zero_cost_moves')} max_depth={search.get('max_depth')} "
        f"stop={search.get('stop_reason')} incumbent={search.get('incumbent')}",
        f"- elapsed_s={search.get('elapsed_s')} rss_mb={search.get('peak_rss_mb')}",
        f"- per_level={search.get('per_level')}",
        f"- control={payload.get('control')}",
        "",
        "## 5. Result",
        "",
        f"- heart={payload.get('heart')} timing={payload.get('timing_classes')} "
        f"path={payload.get('min_path')} MW={payload.get('min_mw')} "
        f"before_sd3={payload.get('moves_before_sd3')} after_sd3={payload.get('moves_after_sd3')}",
        f"- stock={payload.get('stock_at_heart')} fd={payload.get('fd_at_heart')} "
        f"foundations={payload.get('foundations_removed')} classes={payload.get('heart_classes')} "
        f"replay={payload.get('full_replay_ok')} fixture={payload.get('fixture')}",
        "",
        "## 6. Post-hoc parks",
        "",
        json.dumps(payload.get("parks") or [], indent=2)[:4000],
        "",
        "## 7. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
        "## Integrity",
        "",
        f"Verdict {payload.get('verdict')}. SD4 expanded={search.get('sd4_expanded')}.",
        "No production change. No human-route guidance.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    started = time.perf_counter()
    horizon = material_horizon_audit(opening)
    print(f"HORIZON expected_ok={horizon['expected_ok']} sd5={horizon['sd5']}", flush=True)
    audited, distinct = recover_spade_sources(opening)
    audit_ok = len(distinct) == 4 and all(r["ok"] for r in audited)
    sources = [rec["state"] for rec in distinct.values()]
    origin_paths = [rec["path"] for rec in distinct.values()]
    future = future_stock_context(sources[0]) if sources else {}
    print(f"FUTURE SD3={future.get('sd3')} SD4={future.get('sd4')} SD5={future.get('sd5')}", flush=True)
    print(f"TARGET {future.get('target')} unlocks={future.get('unlocks')}", flush=True)
    sd3 = future.get("sd3_raw") or []
    maps = [build_dependency_map(src, sd3) for src in sources]
    backward = maps[0] if maps else {}
    print(
        f"BACKWARD occ={len(backward.get('occurrences') or [])} comps={len(backward.get('components') or [])} "
        f"hard={backward.get('hard_obligation_count')} alt={backward.get('alternative_obligation_count')} "
        f"lb={(backward.get('lower_bound') or {}).get('mw_lower_bound')}",
        flush=True,
    )
    if not horizon["expected_ok"] or not audit_ok:
        verdict, reason = choose_verdict(horizon["expected_ok"], audit_ok, type("X", (), {"stop_reason": ""})(), [])
        payload = {"experiment": EXPERIMENT, "verdict": verdict, "verdict_reason": reason, "horizon": {"expected_ok": horizon["expected_ok"], "sd5": horizon["sd5"]}}
        _write_json(RESULT, payload)
        write_report(payload)
        print(f"VERDICT {verdict}", flush=True)
        return payload

    remaining = 1800.0 - (time.perf_counter() - started)
    print("SEARCH START cost-aware Heart funnel SD3 legal SD4 forbidden", flush=True)
    search = cost_aware_heart_search(
        sources,
        origin_paths,
        sd3,
        max_unique_per_level=2_500_000,
        time_limit_s=max(1.0, remaining - 20),
        rss_abort_mb=3 * 1024.0,
    )
    print(
        f"SEARCH unique={search.unique} exp={search.expanded} gen={search.generated} "
        f"dups={search.duplicate_skips} reopen={search.cheaper_reopens} inc={search.incumbent} "
        f"levels={search.levels_reached} stop={search.stop_reason} elapsed={search.elapsed_s:.1f} "
        f"rss={search.peak_rss_mb} witnesses={len(search.witnesses)}",
        flush=True,
    )

    control = None
    remaining = 1800.0 - (time.perf_counter() - started)
    if search.witnesses and remaining > 5:
        print("CONTROL START neutral UCS cap 250k/300s", flush=True)
        control_search = cost_aware_heart_search(
            sources,
            origin_paths,
            sd3,
            max_unique_per_level=250_000,
            time_limit_s=min(300.0, remaining),
            rss_abort_mb=3 * 1024.0,
            start_level=3,
            max_level=3,
        )
        control = {
            "unique": control_search.unique,
            "expanded": control_search.expanded,
            "generated": control_search.generated,
            "incumbent": control_search.incumbent,
            "stop_reason": control_search.stop_reason,
            "witnesses": len(control_search.witnesses),
            "elapsed_s": control_search.elapsed_s,
            "heart": bool(control_search.witnesses),
        }
        print(f"CONTROL unique={control['unique']} inc={control['incumbent']} stop={control['stop_reason']}", flush=True)

    witnesses = []
    for rec in search.witnesses:
        full = list(origin_paths[rec["origin"]]) + as_actions(rec["actions"])
        end = opening.clone()
        try:
            cost = replay_actions(end, full)
            ok = True
        except (ValueError, AssertionError) as exc:
            cost = None
            ok = False
            rec["replay_error"] = str(exc)
        rec = dict(rec)
        rec["full_actions"] = [list(a) if a != ("deal",) else ["deal"] for a in full]
        rec["full_path_length"] = len(full)
        rec["full_cost"] = cost
        rec["full_replay_ok"] = ok and heart_foundation_count(end) >= 1
        rec["deals"] = sum(1 for a in full if a == ("deal",))
        rec["foundations_removed"] = foundation_suits(end) if ok else rec.get("foundation_suits")
        before = 0
        after = 0
        seen_deal = False
        local = as_actions(rec["actions"])
        for a in local:
            if a == ("deal",):
                seen_deal = True
                continue
            if seen_deal:
                after += 1
            else:
                before += 1
        rec["moves_before_sd3"] = before
        rec["moves_after_sd3"] = after
        witnesses.append(rec)

    first = None
    fixture = None
    parks = []
    if witnesses:
        first = min(witnesses, key=lambda r: (r["g"], r["depth"], r["origin"]))
        header = "\n".join(
            [
                "# v0.31 first Heart foundation",
                f"# timing: {first['timing']}",
                f"# origin: {first['origin']}",
                f"# g: {first['g']}",
            ]
        )
        FIXTURE.write_text(format_moves_text(as_actions(first["full_actions"]), header=header), encoding="utf-8")
        first["fixture"] = FIXTURE.relative_to(ROOT).as_posix()
        fixture = first["fixture"]
        parks = annotate_parks(opening, as_actions(first["full_actions"]))
        by_timing = {}
        for rec in witnesses:
            by_timing.setdefault(rec["timing"], rec)
        for timing, rec in by_timing.items():
            path = TIMING_FIXTURES.get(timing)
            if path is None:
                continue
            path.write_text(
                format_moves_text(as_actions(rec["full_actions"]), header=f"# v0.31 {timing}"),
                encoding="utf-8",
            )

    verdict, reason = choose_verdict(True, True, search, witnesses)
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": "agent/backward-pass-heart-foundation-v0-31",
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": reason,
        "next_recommendation": next_recommendation(verdict),
        "horizon": {
            "expected_ok": horizon["expected_ok"],
            "sd5": horizon["sd5"],
            "max_foundations_by_horizon": horizon["max_foundations_by_horizon"],
            "impossible_before_sd5": horizon["impossible_before_sd5"],
        },
        "future": future,
        "backward": {
            "occurrences": backward.get("occurrences"),
            "components": backward.get("components"),
            "copy_alternatives": backward.get("copy_alternatives"),
            "obligations": backward.get("obligations"),
            "sd3_reception": backward.get("sd3_reception"),
            "lower_bound": backward.get("lower_bound"),
            "hard_obligation_count": backward.get("hard_obligation_count"),
            "alternative_obligation_count": backward.get("alternative_obligation_count"),
        },
        "sources": audited,
        "search": {
            "unique": search.unique,
            "expanded": search.expanded,
            "generated": search.generated,
            "duplicate_skips": search.duplicate_skips,
            "cheaper_reopens": search.cheaper_reopens,
            "zero_cost_moves": search.zero_cost_moves,
            "max_depth": search.max_depth,
            "levels_reached": search.levels_reached,
            "per_level": search.per_level,
            "elapsed_s": search.elapsed_s,
            "peak_rss_mb": search.peak_rss_mb,
            "stop_reason": search.stop_reason,
            "incumbent": search.incumbent,
            "sd4_expanded": search.sd4_expanded,
            "used_heuristic_prune": search.used_heuristic_prune,
            "lower_bound": search.lower_bound,
            "deal_expanded_as_sd3": search.deal_expanded_as_sd3,
            "all_legal_at_level3": search.all_legal_at_level3,
            "identity": "pack_state",
        },
        "control": control,
        "heart": bool(witnesses),
        "timing_classes": sorted({w["timing"] for w in witnesses}),
        "min_path": None if not first else first["full_path_length"],
        "min_mw": None if not first else first["full_cost"],
        "moves_before_sd3": None if not first else first.get("moves_before_sd3"),
        "moves_after_sd3": None if not first else first.get("moves_after_sd3"),
        "stock_at_heart": None if not first else first.get("stock_rows"),
        "fd_at_heart": None if not first else first.get("fd"),
        "foundations_removed": None if not first else first.get("foundations_removed"),
        "heart_classes": len(witnesses),
        "full_replay_ok": bool(witnesses) and all(w.get("full_replay_ok") for w in witnesses),
        "fixture": fixture,
        "first_witness": first,
        "parks": parks,
        "elapsed_s": time.perf_counter() - started,
        "no_sd4": True,
        "production_unchanged": True,
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
