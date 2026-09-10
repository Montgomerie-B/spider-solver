#!/usr/bin/env python3
"""v0.11: Pass-1 vs Pass-2 from the v0.10 B_2_8_1 first-empty witness."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_state
from spider.simple_post_deal_audit import (
    canonical_root_children,
    census_legal_by_tier,
    describe_legal_actions,
    exposed_run_metrics,
    foundation_proximity,
)
from spider.simple_progressive_solver import (
    TT_MODE_FIRST_VISIT,
    apply_action,
    classify_tier,
    format_moves_text,
    ordered_actions,
    solve_progressive,
    step_cost,
)

EXPERIMENT = "simple_progressive_first_empty_pass2_v0_11"
BASE_SHA = "e3dc45f2432a206cd309f2d55d196ad8afcd8cb3"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
PREFIX_FIXTURE = ROOT / "solutions" / "4925153_simple_fd14_stock0_seed.moves.txt"
SEED_FIXTURE = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
FOUNDATION_ROUTE = ROOT / "solutions" / "4925153_simple_v0_11_first_foundation.moves.txt"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
CHECKPOINTS = ROOT / "research" / "results" / EXPERIMENT
PREFIX_HEX = (
    "53504b3101000000040a3a2c360835042302310b0d322913050915191b11282d0c2b1a2901"
    "0a0b1a010c3b2706153423323124162c1c2200081413121d071d223300062d242118341900"
    "070d0c2621393c37040c18360a2a280706050403020911033d17000612272a053801000d3d"
    "3c3b3a39383726081c251b3300071716352b140925"
)
ROOT_ACTION = (2, 8, 1)
LOCAL_DEPTH = 2000
PRIMARY_NODES = 250_000
PRIMARY_TIME = 600.0
SWEEP_NODES = 50_000
SWEEP_TIME = 180.0
EXTEND_NODES = 1_000_000
EXTEND_TIME = 1800.0
RSS_ABORT_MB = 10 * 1024.0
HARVEST_NODES = 80_000
HARVEST_TIME = 400.0


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def action_label(action) -> str:
    if action == ("deal",) or action == ["deal"]:
        return "deal"
    src, dst, k = action
    return f"({src},{dst},{k})"


def opening_state() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL_PATH)))


def load_prefix():
    opening = opening_state()
    prefix = parse_moves_file(PREFIX_FIXTURE)
    seed = opening.clone()
    cost = replay_actions(seed, prefix)
    digest = pack_state(seed).hex()
    ok = (
        digest == PREFIX_HEX
        and cost == 43
        and len(prefix) == 43
        and sum(len(col.face_down) for col in seed.columns) == 14
        and len(seed.stock) == 0
        and len(seed.foundations) == 0
    )
    return opening, prefix, seed, ok, cost


def snapshot_state(state: SpiderState, *, cost: int = 0, path_length: int = 0) -> dict:
    prox = foundation_proximity(state)
    return {
        "digest": pack_state(state).hex(),
        "cost": cost,
        "path_length": path_length,
        "fd": sum(len(col.face_down) for col in state.columns),
        "stock_rows": len(state.stock) // 10,
        "foundations": len(state.foundations),
        "empties": sum(1 for col in state.columns if col.is_empty()),
        "longest_run": prox["longest_exposed_same_suit_run"],
        "adjacencies": prox["exposed_same_suit_adjacencies"],
        "blocks": prox["movable_same_suit_blocks"],
        "complete_ka": prox["exposed_complete_ka_runs"],
        "proximity": prox,
    }


def replay_combined(opening: SpiderState, prefix: list, local_path: list) -> dict:
    combined = list(prefix) + list(local_path or [])
    end = opening.clone()
    try:
        paid = replay_actions(end, combined)
        snap = snapshot_state(end, cost=paid, path_length=len(combined))
        snap["ok"] = True
        return snap
    except (ValueError, AssertionError) as exc:
        return {"ok": False, "error": str(exc), "path_length": len(combined)}


def empty_usage_on_path(opening: SpiderState, actions: list) -> dict:
    state = opening.clone()
    into = []
    precedes = {
        "fd_reduction": False,
        "another_empty": False,
        "run_ge_10": False,
        "foundation": False,
    }
    prev = snapshot_state(state)
    for index, action in enumerate(actions):
        dest_empty = False
        tier = None
        if action != ("deal",):
            src, dst, k = action
            dest_empty = state.columns[dst].is_empty()
            tier = int(classify_tier(state, action))
        apply_action(state, action)
        now = snapshot_state(state)
        if dest_empty:
            rec = {
                "index": index,
                "action": ["deal"] if action == ("deal",) else list(action),
                "tier": tier,
                "fd_before": prev["fd"],
                "fd_after": now["fd"],
                "empties_before": prev["empties"],
                "empties_after": now["empties"],
                "run_before": prev["longest_run"],
                "run_after": now["longest_run"],
                "foundations_before": prev["foundations"],
                "foundations_after": now["foundations"],
            }
            into.append(rec)
            if now["fd"] < prev["fd"]:
                precedes["fd_reduction"] = True
            if now["empties"] > prev["empties"]:
                precedes["another_empty"] = True
            if now["longest_run"] >= 10 > prev["longest_run"]:
                precedes["run_ge_10"] = True
            if now["foundations"] > prev["foundations"]:
                precedes["foundation"] = True
        prev = now
    b_count = sum(1 for item in into if item.get("tier") == 1)
    c_count = sum(1 for item in into if item.get("tier") == 2)
    return {
        "moves_into_empty": len(into),
        "into_empty_b": b_count,
        "into_empty_c": c_count,
        "events": into[:40],
        "precedes_on_path": precedes,
    }


def event_directly_uses_empty(opening: SpiderState, prefix: list, local_path: list) -> dict:
    combined = list(prefix) + list(local_path or [])
    if not combined:
        return {"ok": False, "uses_empty": False}
    parent_actions = combined[:-1]
    last = combined[-1]
    state = opening.clone()
    try:
        if parent_actions:
            replay_actions(state, parent_actions)
        dest_empty = False
        tier = None
        if last != ("deal",):
            src, dst, k = last
            dest_empty = state.columns[dst].is_empty()
            tier = int(classify_tier(state, last))
        apply_action(state, last)
        return {
            "ok": True,
            "uses_empty": dest_empty,
            "tier": tier,
            "action": ["deal"] if last == ("deal",) else list(last),
        }
    except (ValueError, AssertionError) as exc:
        return {"ok": False, "error": str(exc), "uses_empty": False}


def summarize_census(rows: list[dict]) -> dict:
    counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    c_empty = 0
    c_join = 0
    ab_empty = 0
    ab_empty_actions = []
    for row in rows:
        name = row["tier_name"]
        counts[name] += 1
        if name == "C" and row["dest_is_empty"]:
            c_empty += 1
        if name == "C" and row["breaks_same_suit_join"]:
            c_join += 1
        if name in ("A", "B") and row["dest_is_empty"]:
            ab_empty += 1
            ab_empty_actions.append(row)
    return {
        "a": counts["A"],
        "b": counts["B"],
        "c": counts["C"],
        "d": counts["D"],
        "legal": len(rows),
        "tier_c_into_empty": c_empty,
        "tier_c_join_break": c_join,
        "ab_into_empty": ab_empty,
        "ab_into_empty_actions": ab_empty_actions,
        "actions": rows,
    }


def harvest_seed() -> dict:
    opening, prefix, fd14, ok, prefix_cost = load_prefix()
    if not ok:
        return {"ok": False, "error": "fd14 prefix failed", "verdict": "HARD_PROGRESS_SEED_REPRODUCTION_FAILED"}
    groups = canonical_root_children(fd14)
    match = next(
        (
            group
            for group in groups
            if tuple(group["representative"]) == ROOT_ACTION
        ),
        None,
    )
    if match is None:
        return {
            "ok": False,
            "error": "root action (2,8,1) not among fd14 children",
            "verdict": "HARD_PROGRESS_SEED_REPRODUCTION_FAILED",
        }
    child = fd14.clone()
    apply_action(child, ROOT_ACTION)
    print("HARVEST_START first_visit Pass1 stop_on_first_empty", flush=True)
    result = solve_progressive(
        child,
        max_nodes=HARVEST_NODES,
        time_limit_s=HARVEST_TIME,
        target_foundations=1,
        max_pass=1,
        start_pass=1,
        prep_ply=0,
        max_depth=LOCAL_DEPTH,
        depth_bands=(LOCAL_DEPTH,),
        enable_saturation=False,
        enable_audit=False,
        enable_best_reveal_deal_probe=False,
        enable_post_deal_audit=True,
        enable_band_local_saturation=False,
        tt_mode=TT_MODE_FIRST_VISIT,
        rss_abort_mb=RSS_ABORT_MB,
        stop_on_first_empty=True,
    )
    pda = result.post_deal_audit
    event = None
    if pda is not None:
        event = next((item for item in pda.progress_events if item["kind"] == "first_empty"), None)
    if event is None:
        return {
            "ok": False,
            "error": "first_empty event not recorded",
            "nodes": result.nodes,
            "stop_reason": result.stop_reason,
            "min_fd": result.min_face_down,
            "verdict": "HARD_PROGRESS_SEED_REPRODUCTION_FAILED",
        }
    local = list(event.get("path") or [])
    combined = list(prefix) + [ROOT_ACTION] + local
    replay = replay_combined(opening, prefix, [ROOT_ACTION] + local)
    expected = (
        replay.get("ok")
        and replay.get("fd") == 13
        and replay.get("stock_rows") == 0
        and replay.get("foundations") == 0
        and replay.get("empties") == 1
    )
    if not expected:
        return {
            "ok": False,
            "error": "first-empty replay did not match expected state",
            "replay": replay,
            "local_path_length": len(local),
            "nodes": result.nodes,
            "verdict": "HARD_PROGRESS_SEED_REPRODUCTION_FAILED",
        }
    header = "\n".join(
        [
            "# v0.11 seed: 4925153 fd-13 empty-1 first-empty witness",
            "# lineage: v0.10 B_2_8_1 first_empty",
            f"# primitive_moves: {len(combined)}",
            f"# mobilityware_moves: {replay['cost']}",
            f"# digest: {replay['digest']}",
            f"# fd: {replay['fd']}",
            f"# stock_rows: {replay['stock_rows']}",
            f"# foundations: {replay['foundations']}",
            f"# empties: {replay['empties']}",
            f"# longest_run: {replay['longest_run']}",
            f"# root_action: {action_label(ROOT_ACTION)}",
            f"# harvest_expansion: {event.get('expansion')}",
            f"# harvest_depth: {event.get('depth')}",
        ]
    )
    SEED_FIXTURE.write_text(format_moves_text(combined, header=header), encoding="utf-8")
    print(
        f"HARVEST_OK path={len(combined)} cost={replay['cost']} digest={replay['digest'][:16]}...",
        flush=True,
    )
    return {
        "ok": True,
        "digest": replay["digest"],
        "cost": replay["cost"],
        "path_length": len(combined),
        "fd": replay["fd"],
        "stock_rows": replay["stock_rows"],
        "foundations": replay["foundations"],
        "empties": replay["empties"],
        "longest_run": replay["longest_run"],
        "adjacencies": replay["adjacencies"],
        "blocks": replay["blocks"],
        "local_path_length": len(local),
        "harvest_expansion": event.get("expansion"),
        "harvest_depth": event.get("depth"),
        "harvest_nodes": result.nodes,
        "harvest_stop": result.stop_reason,
        "harvest_rss_mb": result.stats.peak_rss_mb,
        "root_action": list(ROOT_ACTION),
        "fixture": str(SEED_FIXTURE.relative_to(ROOT)).replace("\\", "/"),
        "replay": replay,
    }


def load_empty_seed():
    opening = opening_state()
    if not SEED_FIXTURE.exists():
        raise SystemExit("empty seed fixture missing")
    actions = parse_moves_file(SEED_FIXTURE)
    seed = opening.clone()
    cost = replay_actions(seed, actions)
    snap = snapshot_state(seed, cost=cost, path_length=len(actions))
    snap["ok"] = (
        snap["fd"] == 13
        and snap["stock_rows"] == 0
        and snap["foundations"] == 0
        and snap["empties"] == 1
        and snap["path_length"] == len(actions)
    )
    return opening, actions, seed, snap


def compact_arm(opening, prefix, result, *, name: str, forced_action=None) -> dict:
    pda = result.post_deal_audit
    events = []
    if pda is not None:
        for event in pda.progress_events:
            local = event.get("path") or []
            forced = [] if forced_action is None else [forced_action]
            replay = replay_combined(opening, prefix, forced + local)
            last = event_directly_uses_empty(opening, prefix, forced + local)
            events.append(
                {
                    "kind": event["kind"],
                    "expansion": event.get("expansion"),
                    "depth": event.get("depth"),
                    "cost": event.get("cost"),
                    "fd": event.get("fd"),
                    "empties": event.get("empties"),
                    "longest_run": event.get("longest_run"),
                    "adjacencies": event.get("adjacencies"),
                    "blocks": event.get("blocks"),
                    "foundations": event.get("foundations"),
                    "complete_ka": event.get("complete_ka"),
                    "path_length": len(local),
                    "combined_replay": replay,
                    "last_move_uses_empty": last,
                }
            )
    best_run = None if pda is None else pda.best_run_struct
    best_empty = None if pda is None else pda.best_empties_struct
    best_adj = None if pda is None else pda.best_adj_struct
    best_blocks = None if pda is None else pda.best_blocks_struct
    expanded = result.nodes
    unique = result.stats.unique_exact_states
    local_best = list(result.best_reveal_actions or [])
    forced = [] if forced_action is None else [forced_action]
    combined_best = replay_combined(opening, prefix, forced + local_best)
    path_usage = empty_usage_on_path(opening, list(prefix) + forced + local_best)
    fnd_path = list(result.first_foundation_actions or [])
    return {
        "name": name,
        "forced_action": None if forced_action is None else list(forced_action),
        "nodes": expanded,
        "generated": result.stats.states_generated,
        "unique": unique,
        "unique_ratio": unique / max(1, expanded),
        "first_visit_skips": result.stats.first_visit_skips,
        "path_cycles": result.stats.path_cycles,
        "duplicate_children": result.stats.duplicate_children,
        "inverses": result.stats.inverses,
        "tt_hits": result.stats.tt_hits,
        "tt_prunes": result.stats.tt_depth_prunes,
        "tt_reopens": result.stats.tt_reopens,
        "tt_mode": result.stats.tt_mode,
        "states_per_sec": result.states_per_sec,
        "peak_rss_mb": result.stats.peak_rss_mb,
        "max_depth": result.stats.max_depth,
        "stop_reason": result.stop_reason,
        "elapsed_s": result.elapsed_s,
        "min_fd": result.min_face_down,
        "max_foundations": result.max_foundations,
        "max_empties": None if best_empty is None else best_empty.get("empties"),
        "longest_run": None if best_run is None else best_run.get("longest_run"),
        "max_adjacencies": None if best_adj is None else best_adj.get("adjacencies"),
        "max_blocks": None if best_blocks is None else best_blocks.get("blocks"),
        "unique_at": dict(result.stats.unique_at),
        "considered_by_tier": list(result.stats.considered_by_tier),
        "expanded_by_tier": list(result.stats.expanded_by_tier),
        "empty_into_moves": result.stats.empty_into_moves,
        "empty_into_b": result.stats.empty_into_b,
        "empty_into_c": result.stats.empty_into_c,
        "empty_into_by_tier": list(result.stats.empty_into_by_tier),
        "first_empty_use_expansion": result.stats.first_empty_use_expansion,
        "first_empty_use_tier": result.stats.first_empty_use_tier,
        "first_empty_use_action": (
            None
            if result.stats.first_empty_use_action is None
            else (
                ["deal"]
                if result.stats.first_empty_use_action == ("deal",)
                else list(result.stats.first_empty_use_action)
            )
        ),
        "root_children_expanded": list(result.stats.root_children_expanded),
        "progress_events": events,
        "combined_best_replay": combined_best,
        "path_empty_usage": path_usage,
        "generic_replay_ok": result.replay_ok,
        "rss_abort": result.stats.rss_abort,
        "first_foundation_node": result.stats.first_foundation_node,
        "first_foundation_depth": result.stats.first_foundation_depth,
        "pass_reached": result.pass_reached,
        "_foundation_path": fnd_path,
        "_best_path": local_best,
    }


def run_search_arm(
    *,
    name: str,
    start_pass: int,
    max_pass: int,
    max_nodes: int,
    time_limit: float,
    forced_action=None,
) -> dict:
    opening, prefix, seed, snap = load_empty_seed()
    if not snap["ok"]:
        raise SystemExit("empty seed failed verification")
    start = seed.clone()
    if forced_action is not None:
        apply_action(start, forced_action)
    print(
        f"START {name} pass={start_pass}..{max_pass} nodes={max_nodes} first_visit=1",
        flush=True,
    )
    started = time.perf_counter()
    result = solve_progressive(
        start,
        max_nodes=max_nodes,
        time_limit_s=time_limit,
        target_foundations=1,
        max_pass=max_pass,
        start_pass=start_pass,
        prep_ply=0,
        max_depth=LOCAL_DEPTH,
        depth_bands=(LOCAL_DEPTH,),
        enable_saturation=False,
        enable_audit=False,
        enable_best_reveal_deal_probe=False,
        enable_post_deal_audit=True,
        enable_band_local_saturation=False,
        tt_mode=TT_MODE_FIRST_VISIT,
        rss_abort_mb=RSS_ABORT_MB,
    )
    payload = compact_arm(
        opening, prefix, result, name=name, forced_action=forced_action
    )
    payload["seed"] = {k: v for k, v in snap.items() if k != "proximity"}
    payload["elapsed_wall_s"] = time.perf_counter() - started
    print(
        f"DONE {name} nodes={payload['nodes']} unique={payload['unique']} "
        f"fd={payload['min_fd']} run={payload['longest_run']} empty={payload['max_empties']} "
        f"fnd={payload['max_foundations']} empty_into={payload['empty_into_moves']} "
        f"C_into={payload['empty_into_c']} depth={payload['max_depth']} "
        f"rss={payload['peak_rss_mb']} stop={payload['stop_reason']}",
        flush=True,
    )
    return payload


def drop_private(arm: dict) -> dict:
    out = dict(arm)
    out.pop("_foundation_path", None)
    out.pop("_best_path", None)
    return out


def hard_progress(arm: dict) -> bool:
    if (arm.get("max_foundations") or 0) >= 1:
        return True
    if (arm.get("min_fd") or 99) <= 12:
        return True
    if (arm.get("max_empties") or 0) >= 2:
        return True
    if (arm.get("longest_run") or 0) >= 10:
        return True
    return False


def soft_better(treatment: dict, control: dict) -> bool:
    return (
        (treatment.get("longest_run") or 0) > (control.get("longest_run") or 0)
        or (treatment.get("max_adjacencies") or 0) > (control.get("max_adjacencies") or 0)
        or (treatment.get("max_blocks") or 0) > (control.get("max_blocks") or 0)
    )


def causal_empty_c(arm: dict) -> bool:
    if not hard_progress(arm):
        return False
    for event in arm.get("progress_events") or []:
        kind = event.get("kind")
        if kind not in ("fd_le_12", "fd_le_11", "second_empty", "run_ge_10", "run_ge_11", "run_ge_12", "complete_ka_run", "first_foundation"):
            continue
        replay = event.get("combined_replay") or {}
        last = event.get("last_move_uses_empty") or {}
        if replay.get("ok") and last.get("uses_empty") and last.get("tier") == 2:
            return True
    return False


def choose_verdict(seed: dict, control: dict | None, treatment: dict | None, arms: list[dict]) -> tuple[str, str]:
    if not seed.get("ok"):
        return "HARD_PROGRESS_SEED_REPRODUCTION_FAILED", seed.get("error") or "seed failed"
    if control is None or treatment is None:
        return "INCONCLUSIVE", "missing control or treatment"
    if control.get("rss_abort") or treatment.get("rss_abort"):
        if not hard_progress(control) and not hard_progress(treatment):
            return "FIRST_VISIT_PASS2_MEMORY_EXPLOSION", "RSS abort before a meaningful comparison"
    if (control.get("max_foundations") or 0) >= 1 and (control.get("combined_best_replay") or {}).get("ok"):
        return "PASS1_FROM_HARD_SEED_ALREADY_PROGRESSIVE", "Pass-1 control itself reached a foundation"
    pass2_arms = [treatment] + [
        arm for arm in arms if arm is not control and arm.get("name") != "PASS1"
    ]
    if hard_progress(control) and not any((arm.get("max_foundations") or 0) >= 1 for arm in pass2_arms):
        return (
            "PASS1_FROM_HARD_SEED_ALREADY_PROGRESSIVE",
            "direct A+B from the empty seed already made new hard progress",
        )
    fnd_arm = next((arm for arm in pass2_arms if (arm.get("max_foundations") or 0) >= 1), None)
    if fnd_arm is not None:
        replay_ok = any(
            (event.get("kind") == "first_foundation" and (event.get("combined_replay") or {}).get("ok"))
            for event in fnd_arm.get("progress_events") or []
        ) or ((fnd_arm.get("combined_best_replay") or {}).get("foundations") or 0) >= 1
        if replay_ok:
            return "PASS2_REACHES_FIRST_FOUNDATION", "Pass-2 reached a replay-valid first foundation"
    sweep_hard = [arm for arm in arms if str(arm.get("name", "")).startswith("CROOT_") and hard_progress(arm)]
    if causal_empty_c(treatment) or any(causal_empty_c(arm) for arm in sweep_hard):
        return (
            "PASS2_EMPTY_WORKSPACE_IS_CAUSAL",
            "hard progress followed a replay-valid Tier-C use of the empty column",
        )
    if hard_progress(treatment) or sweep_hard:
        return "PASS2_IMPROVES_HARD_PROGRESS", "Pass-2 achieved fd<=12, a second empty, or run>=10"
    if soft_better(treatment, control):
        return (
            "PASS2_ONLY_IMPROVES_SOFT_STRUCTURE",
            "Pass-2 improved run/adjacency/block structure without harder state progress",
        )
    more_branching = (treatment.get("expanded_by_tier") or [0, 0, 0, 0])[2] > 0
    if more_branching:
        return (
            "PASS2_ADDS_BRANCHING_WITHOUT_PROGRESS",
            "A+B+C explored Tier-C alternatives but did not beat the Pass-1 control",
        )
    return "INCONCLUSIVE", "Pass-1 vs Pass-2 comparison was not decisive"


def next_recommendation(verdict: str) -> str:
    if verdict == "PASS2_REACHES_FIRST_FOUNDATION":
        return (
            "Keep first-visit research-only. Capture the first-foundation route and "
            "stop. Do not add Pass 3 or whole-deal integration."
        )
    if verdict == "PASS2_EMPTY_WORKSPACE_IS_CAUSAL":
        return (
            "Pass 2 used the empty workspace. Next: keep first-visit research-only "
            "and continue A+B+C from the new hard-progress witness; do not add Pass 3."
        )
    if verdict == "PASS2_IMPROVES_HARD_PROGRESS":
        return (
            "Pass 2 made harder progress from the empty seed. Next: inspect the "
            "replay-valid witness and continue first-visit A+B+C from that child; "
            "do not restore depth reopens."
        )
    if verdict == "PASS1_FROM_HARD_SEED_ALREADY_PROGRESSIVE":
        return (
            "A+B can still progress from the empty seed, so Tier C is not yet the "
            "proven bottleneck. Next: continue first-visit Pass 1 from the new "
            "hard-progress child before widening to Pass 2."
        )
    if verdict == "PASS2_ONLY_IMPROVES_SOFT_STRUCTURE":
        return (
            "Do not integrate Pass 2 and do not add Pass 3. Inspect the replay-valid "
            "run-9 empty-consuming witness and the binding depth-2000 ceiling: the "
            "remaining bottleneck is converting the first empty into a face-down "
            "uncover or a second empty, not granting permission to occupy the empty."
        )
    if verdict == "PASS2_ADDS_BRANCHING_WITHOUT_PROGRESS":
        return (
            "Enabling Tier C after the first empty did not convert workspace into "
            "harder progress. Next: do not add Pass 3; document the remaining "
            "bottleneck on the empty-rooted A+B plateau."
        )
    if verdict == "FIRST_VISIT_PASS2_MEMORY_EXPLOSION":
        return (
            "Do not enable Pass 2 in production. Next: measure unique-set memory "
            "of A+B+C first-visit before another widening experiment."
        )
    if verdict == "HARD_PROGRESS_SEED_REPRODUCTION_FAILED":
        return "Stop. Reproduce the v0.10 B_2_8_1 first-empty witness before another Pass-2 test."
    return "Reproduce the empty-seed Pass-1/Pass-2 comparison before changing tier policy."


def save_foundation_if_any(opening, prefix, arms: list[dict]) -> dict | None:
    for arm in arms:
        path = arm.get("_foundation_path") or []
        if not path or (arm.get("max_foundations") or 0) < 1:
            continue
        forced = arm.get("forced_action")
        extra = [] if forced is None else [tuple(forced)]
        combined = list(prefix) + extra + list(path)
        replay = replay_combined(opening, prefix, extra + list(path))
        if not replay.get("ok") or (replay.get("foundations") or 0) < 1:
            continue
        header = "\n".join(
            [
                "# v0.11 first-foundation route 4925153",
                f"# arm: {arm.get('name')}",
                f"# primitive_moves: {len(combined)}",
                f"# mobilityware_moves: {replay['cost']}",
                f"# digest: {replay['digest']}",
                f"# fd: {replay['fd']}",
                f"# foundations: {replay['foundations']}",
                f"# empties: {replay['empties']}",
            ]
        )
        FOUNDATION_ROUTE.write_text(format_moves_text(combined, header=header), encoding="utf-8")
        return {
            "arm": arm.get("name"),
            "fixture": str(FOUNDATION_ROUTE.relative_to(ROOT)).replace("\\", "/"),
            "replay": replay,
        }
    return None


def write_report(payload: dict) -> None:
    seed = payload.get("seed") or {}
    census = payload.get("census") or {}
    control = payload.get("pass1") or {}
    treatment = payload.get("pass2") or {}
    sweep = payload.get("c_root_sweep") or []
    lines = [
        "# Simple Progressive Search v0.11: First-Empty Pass-2 Workspace",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('note')}.",
        "",
        "FIRST_VISIT_EXACT remains research-only and has no proof authority.",
        "Production default remains DEPTH_AWARE_COVERAGE, start_pass=0, Pass-2 not integrated.",
        "",
        "## 2. Hard-progress seed",
        "",
        f"- ok={seed.get('ok')} digest `{seed.get('digest')}`",
        f"- path_length={seed.get('path_length')} cost={seed.get('cost')} "
        f"fd={seed.get('fd')} stock={seed.get('stock_rows')} fnd={seed.get('foundations')} "
        f"empties={seed.get('empties')} run={seed.get('longest_run')}",
        f"- harvest expansion={seed.get('harvest_expansion')} depth={seed.get('harvest_depth')}",
        f"- fixture `{seed.get('fixture')}`",
        "",
        "## 3. Root-action census at fd13/empty1",
        "",
        f"- A={census.get('a')} B={census.get('b')} C={census.get('c')} D={census.get('d')} "
        f"legal={census.get('legal')}",
        f"- Tier-C into empty={census.get('tier_c_into_empty')}",
        f"- Tier-C join-break={census.get('tier_c_join_break')}",
        f"- A/B into empty={census.get('ab_into_empty')}",
        "",
    ]
    for row in census.get("ab_into_empty_actions") or []:
        lines.append(
            f"- A/B empty-using action {row.get('action')} tier={row.get('tier_name')} "
            f"uncover={row.get('uncovers_face_down')} create_empty={row.get('creates_empty')}"
        )
    lines.extend(
        [
            "",
            "## 4. Pass-1 vs Pass-2",
            "",
            "| Metric | Pass 1 A+B | Pass 2 A+B+C |",
            "| --- | ---: | ---: |",
            f"| Expanded | {control.get('nodes')} | {treatment.get('nodes')} |",
            f"| Unique | {control.get('unique')} | {treatment.get('unique')} |",
            f"| States/sec | {control.get('states_per_sec')} | {treatment.get('states_per_sec')} |",
            f"| Min FD | {control.get('min_fd')} | {treatment.get('min_fd')} |",
            f"| Max empties | {control.get('max_empties')} | {treatment.get('max_empties')} |",
            f"| Longest run | {control.get('longest_run')} | {treatment.get('longest_run')} |",
            f"| Max adjacencies | {control.get('max_adjacencies')} | {treatment.get('max_adjacencies')} |",
            f"| Max movable blocks | {control.get('max_blocks')} | {treatment.get('max_blocks')} |",
            f"| Max foundations | {control.get('max_foundations')} | {treatment.get('max_foundations')} |",
            f"| Max depth | {control.get('max_depth')} | {treatment.get('max_depth')} |",
            f"| RSS | {control.get('peak_rss_mb')} | {treatment.get('peak_rss_mb')} |",
            "",
            "## 5. Empty-column usage",
            "",
            f"- Pass 1 into-empty={control.get('empty_into_moves')} B={control.get('empty_into_b')} "
            f"C={control.get('empty_into_c')} first_use_exp={control.get('first_empty_use_expansion')}",
            f"- Pass 2 into-empty={treatment.get('empty_into_moves')} B={treatment.get('empty_into_b')} "
            f"C={treatment.get('empty_into_c')} first_use_exp={treatment.get('first_empty_use_expansion')}",
            f"- Pass 2 considered_by_tier={treatment.get('considered_by_tier')} "
            f"expanded_by_tier={treatment.get('expanded_by_tier')}",
            "",
            "## 6. Hard-progress events",
            "",
        ]
    )
    for arm in [control, treatment, *(payload.get("c_root_sweep") or [])]:
        if not arm:
            continue
        events = arm.get("progress_events") or []
        if not events:
            lines.append(f"- {arm.get('name')}: none beyond seed structure.")
            continue
        for event in events:
            last = event.get("last_move_uses_empty") or {}
            lines.append(
                f"- {arm.get('name')} {event['kind']}: exp={event.get('expansion')} "
                f"depth={event.get('depth')} run={event.get('longest_run')} "
                f"fd={event.get('fd')} empty={event.get('empties')} "
                f"fnd={event.get('foundations')} replay={(event.get('combined_replay') or {}).get('ok')} "
                f"last_empty={last.get('uses_empty')} last_tier={last.get('tier')}"
            )
    root_cov = payload.get("root_c_coverage") or {}
    lines.extend(
        [
            "",
            "## 7. Root Tier-C coverage",
            "",
            f"- distinct C root children={root_cov.get('total')}",
            f"- expanded in Pass-2 DFS={root_cov.get('expanded')}",
            f"- unvisited={root_cov.get('unvisited')}",
            f"- sweep required={root_cov.get('sweep_required')}",
            "",
            "## 8. Forced C-root sweep",
            "",
        ]
    )
    if not sweep:
        lines.append("- not required or not run.")
    else:
        for arm in sweep:
            lines.append(
                f"- {arm.get('name')}: unique={arm.get('unique')} fd={arm.get('min_fd')} "
                f"empty={arm.get('max_empties')} run={arm.get('longest_run')} "
                f"fnd={arm.get('max_foundations')} stop={arm.get('stop_reason')}"
            )
    ext = payload.get("extension")
    lines.extend(["", "## 9. Optional extension", ""])
    if not ext:
        lines.append("- not triggered.")
    else:
        lines.append(
            f"- {ext.get('name')}: nodes={ext.get('nodes')} unique={ext.get('unique')} "
            f"fd={ext.get('min_fd')} run={ext.get('longest_run')} empty={ext.get('max_empties')} "
            f"fnd={ext.get('max_foundations')} stop={ext.get('stop_reason')}"
        )
    fnd = payload.get("foundation_route")
    lines.extend(["", "## 10. First foundation", ""])
    if not fnd:
        lines.append("- no foundation reached.")
    else:
        replay = fnd.get("replay") or {}
        lines.append(
            f"- arm={fnd.get('arm')} path={replay.get('path_length')} cost={replay.get('cost')} "
            f"fd={replay.get('fd')} fnd={replay.get('foundations')} fixture `{fnd.get('fixture')}`"
        )
    lines.extend(
        [
            "",
            "## 11. Exactly one next recommendation",
            "",
            payload.get("next_recommendation") or "",
            "",
            "## Integrity",
            "",
            payload.get("interpretation") or "",
            "",
            f"Base SHA `{payload.get('base_sha')}`. Deal `deals/4925153.txt`.",
            "Default TT remains depth-aware. first_visit is research-only and not proof-safe.",
            "Pass 2 is not integrated into production solve_progressive.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def interpret(payload: dict) -> str:
    seed = payload.get("seed") or {}
    control = payload.get("pass1") or {}
    treatment = payload.get("pass2") or {}
    return (
        f"Verdict {payload.get('verdict')}. Seed ok={seed.get('ok')} "
        f"digest={seed.get('digest')} path={seed.get('path_length')} cost={seed.get('cost')}. "
        f"Pass1 unique={control.get('unique')} fd={control.get('min_fd')} "
        f"empty={control.get('max_empties')} run={control.get('longest_run')} "
        f"fnd={control.get('max_foundations')}. "
        f"Pass2 unique={treatment.get('unique')} fd={treatment.get('min_fd')} "
        f"empty={treatment.get('max_empties')} run={treatment.get('longest_run')} "
        f"fnd={treatment.get('max_foundations')} C_exp={(treatment.get('expanded_by_tier') or [0,0,0,0])[2]}."
    )


def spawn_worker(args: list[str], out: Path) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONUNBUFFERED"] = "1"
    script = Path(__file__).resolve()
    cmd = [sys.executable, str(script), *args, "--out", str(out)]
    print(f"SPAWN {' '.join(args)}", flush=True)
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env)
    if proc.returncode != 0:
        raise SystemExit(f"worker failed {args} code={proc.returncode}")
    return json.loads(out.read_text(encoding="utf-8"))


def parent_main() -> int:
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    harvest_out = CHECKPOINTS / "seed.json"
    if SEED_FIXTURE.exists():
        opening, prefix, seed, snap = load_empty_seed()
        if snap["ok"]:
            seed_info = dict(snap)
            if harvest_out.exists():
                harvested = json.loads(harvest_out.read_text(encoding="utf-8"))
                for key, value in harvested.items():
                    if key not in ("replay", "proximity"):
                        seed_info.setdefault(key, value)
            seed_info["fixture"] = str(SEED_FIXTURE.relative_to(ROOT)).replace("\\", "/")
            seed_info["root_action"] = list(ROOT_ACTION)
            seed_info.update({k: snap[k] for k in snap if k != "proximity"})
            print("SEED_EXISTING_OK", flush=True)
        else:
            seed_info = spawn_worker(["--mode", "harvest"], harvest_out)
    else:
        seed_info = spawn_worker(["--mode", "harvest"], harvest_out)
    if not seed_info.get("ok"):
        payload = {
            "experiment": EXPERIMENT,
            "base_sha": BASE_SHA,
            "verdict": "HARD_PROGRESS_SEED_REPRODUCTION_FAILED",
            "note": seed_info.get("error") or "seed failed",
            "seed": seed_info,
            "next_recommendation": next_recommendation("HARD_PROGRESS_SEED_REPRODUCTION_FAILED"),
        }
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT HARD_PROGRESS_SEED_REPRODUCTION_FAILED", flush=True)
        return 1
    opening, prefix, seed, snap = load_empty_seed()
    rows = describe_legal_actions(seed)
    census = summarize_census(rows)
    _write_json(CHECKPOINTS / "census.json", census)
    print(
        f"CENSUS A={census['a']} B={census['b']} C={census['c']} D={census['d']} "
        f"C_empty={census['tier_c_into_empty']} C_join={census['tier_c_join_break']} "
        f"AB_empty={census['ab_into_empty']}",
        flush=True,
    )
    control = spawn_worker(
        ["--mode", "arm", "--arm", "PASS1", "--start-pass", "1", "--max-pass", "1"],
        CHECKPOINTS / "PASS1.json",
    )
    treatment = spawn_worker(
        ["--mode", "arm", "--arm", "PASS2", "--start-pass", "2", "--max-pass", "2"],
        CHECKPOINTS / "PASS2.json",
    )
    c_groups = [
        group
        for group in canonical_root_children(seed)
        if group["tier"] == 2
    ]
    expanded_digests = {
        item.get("digest") for item in treatment.get("root_children_expanded") or []
        if item.get("tier") == 2
    }
    unvisited = [group for group in c_groups if group["key_hex"] not in expanded_digests]
    root_c_coverage = {
        "total": len(c_groups),
        "expanded": len(c_groups) - len(unvisited),
        "unvisited": len(unvisited),
        "sweep_required": bool(unvisited),
        "expanded_actions": treatment.get("root_children_expanded") or [],
        "unvisited_actions": [
            {"action": list(group["representative"]), "digest": group["key_hex"]}
            for group in unvisited
        ],
    }
    sweep = []
    if unvisited:
        for group in unvisited:
            action = group["representative"]
            name = f"CROOT_{action[0]}_{action[1]}_{action[2]}"
            arm = spawn_worker(
                [
                    "--mode",
                    "arm",
                    "--arm",
                    name,
                    "--start-pass",
                    "2",
                    "--max-pass",
                    "2",
                    "--force",
                    f"{action[0]},{action[1]},{action[2]}",
                    "--nodes",
                    str(SWEEP_NODES),
                    "--time",
                    str(SWEEP_TIME),
                ],
                CHECKPOINTS / f"{name}.json",
            )
            sweep.append(arm)
            if (arm.get("max_foundations") or 0) >= 1:
                break
    extension = None
    candidates = [treatment, *sweep]
    qualifiers = [arm for arm in candidates if hard_progress(arm)]
    if qualifiers:
        qualifiers.sort(
            key=lambda arm: (
                -(arm.get("max_foundations") or 0),
                arm.get("min_fd") or 99,
                -(arm.get("max_empties") or 0),
                -(arm.get("longest_run") or 0),
            )
        )
        chosen = qualifiers[0]
        force_args = []
        if chosen.get("forced_action"):
            a, b, c = chosen["forced_action"]
            force_args = ["--force", f"{a},{b},{c}"]
        extension = spawn_worker(
            [
                "--mode",
                "arm",
                "--arm",
                chosen["name"] + "_EXT",
                "--start-pass",
                "2",
                "--max-pass",
                "2",
                *force_args,
                "--nodes",
                str(EXTEND_NODES),
                "--time",
                str(EXTEND_TIME),
            ],
            CHECKPOINTS / f"{chosen['name']}_EXT.json",
        )
    arms = [control, treatment, *sweep]
    if extension:
        arms.append(extension)
    foundation = save_foundation_if_any(opening, prefix, [control, treatment, *sweep] + ([extension] if extension else []))
    verdict, note = choose_verdict(seed_info, control, treatment, arms)
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "deal": "deals/4925153.txt",
        "seed": seed_info if "digest" in seed_info else snap,
        "census": {
            k: v for k, v in census.items() if k != "actions"
        },
        "census_actions": census["actions"],
        "pass1": drop_private(control),
        "pass2": drop_private(treatment),
        "root_c_coverage": root_c_coverage,
        "c_root_sweep": [drop_private(arm) for arm in sweep],
        "extension": None if extension is None else drop_private(extension),
        "foundation_route": foundation,
        "verdict": verdict,
        "note": note,
        "next_recommendation": next_recommendation(verdict),
    }
    payload["seed"] = {
        **{k: v for k, v in (payload["seed"] or {}).items() if k != "proximity"},
        "digest": snap["digest"],
        "cost": snap["cost"],
        "path_length": snap["path_length"],
        "fd": snap["fd"],
        "stock_rows": snap["stock_rows"],
        "foundations": snap["foundations"],
        "empties": snap["empties"],
        "longest_run": snap["longest_run"],
        "adjacencies": snap["adjacencies"],
        "blocks": snap["blocks"],
        "ok": True,
        "fixture": str(SEED_FIXTURE.relative_to(ROOT)).replace("\\", "/"),
        "root_action": list(ROOT_ACTION),
    }
    payload["interpretation"] = interpret(payload)
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"WROTE {RESULT}", flush=True)
    print(f"WROTE {REPORT}", flush=True)
    return 0


def worker_main(argv: list[str]) -> int:
    mode = None
    arm = None
    out = None
    start_pass = 1
    max_pass = 1
    nodes = PRIMARY_NODES
    limit = PRIMARY_TIME
    force = None
    i = 0
    while i < len(argv):
        if argv[i] == "--mode":
            mode = argv[i + 1]
            i += 2
            continue
        if argv[i] == "--arm":
            arm = argv[i + 1]
            i += 2
            continue
        if argv[i] == "--out":
            out = Path(argv[i + 1])
            i += 2
            continue
        if argv[i] == "--start-pass":
            start_pass = int(argv[i + 1])
            i += 2
            continue
        if argv[i] == "--max-pass":
            max_pass = int(argv[i + 1])
            i += 2
            continue
        if argv[i] == "--nodes":
            nodes = int(argv[i + 1])
            i += 2
            continue
        if argv[i] == "--time":
            limit = float(argv[i + 1])
            i += 2
            continue
        if argv[i] == "--force":
            parts = [int(p) for p in argv[i + 1].split(",")]
            force = (parts[0], parts[1], parts[2])
            i += 2
            continue
        i += 1
    if out is None:
        raise SystemExit("usage: --out PATH")
    if mode == "harvest":
        payload = harvest_seed()
        _write_json(out, payload)
        print(f"WROTE {out}", flush=True)
        return 0 if payload.get("ok") else 1
    if mode == "arm":
        if not arm:
            raise SystemExit("arm name required")
        payload = run_search_arm(
            name=arm,
            start_pass=start_pass,
            max_pass=max_pass,
            max_nodes=nodes,
            time_limit=limit,
            forced_action=force,
        )
        _write_json(out, drop_private(payload))
        print(f"WROTE {out}", flush=True)
        return 0
    raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    if "--mode" in sys.argv:
        raise SystemExit(worker_main(sys.argv[1:]))
    raise SystemExit(parent_main())
