"""Research-only shallow layered reachability for workspace transactions.

Breadth/layer order by primitive depth.  Exact canonical identity.  First
encounter of a state is its minimum depth; later same/deeper encounters
are skipped.  Permits A+B+C only.

Not imported by ``solve_progressive``.  Not a production solver.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.packed_state import pack_state, unpack_state
from spider.rules import MW_RULES, MobilityWareRules
from spider.simple_post_deal_audit import exposed_run_metrics
from spider.simple_progressive_solver import (
    Tier,
    _capture,
    _restore,
    _rss_mb,
    apply_action,
    classify_tier,
    enumerate_actions,
    step_cost,
)

MAX_TIER = int(Tier.C)
CHECKPOINT_DEPTHS = (4, 8, 12, 16, 20)


def empty_column_indices(state: SpiderState) -> Tuple[int, ...]:
    return tuple(index for index, col in enumerate(state.columns) if col.is_empty())


def empty_transition_events(
    before: Sequence[int],
    after: Sequence[int],
    *,
    dest_was_empty: bool,
    source_became_empty: bool,
) -> List[str]:
    """Observational empty-lifecycle events for one parent→child move."""

    before_t = tuple(before)
    after_t = tuple(after)
    events: List[str] = []
    if dest_was_empty and source_became_empty and set(after_t) != set(before_t):
        events.append("EMPTY_TRANSFERRED")
    if len(before_t) >= 1 and len(after_t) == 0:
        events.append("EMPTY_CONSUMED")
    if len(before_t) == 0 and len(after_t) >= 1:
        events.append("EMPTY_RECREATED")
    if len(after_t) >= 2 and len(before_t) < 2:
        events.append("SECOND_EMPTY")
    return events


def first_empty_use_on_path(
    seed: SpiderState, actions: Sequence[Action]
) -> Optional[dict]:
    """First move into an empty column along ``actions`` from ``seed``."""

    state = seed.clone()
    prefix_tiers: List[int] = []
    for index, action in enumerate(actions):
        if action == ("deal",):
            apply_action(state, action)
            prefix_tiers.append(int(classify_tier(state, action)))
            continue
        src, dst, k = action  # type: ignore[misc]
        dest_was_empty = state.columns[dst].is_empty()
        source_becomes_empty = k == len(state.columns[src].face_up) and not state.columns[src].face_down
        tier = int(classify_tier(state, action))
        if dest_was_empty:
            after_src_empty = source_becomes_empty
            return {
                "depth": index + 1,
                "tier": tier,
                "tier_name": "ABCD"[tier],
                "action": list(action),
                "empty_column": dst,
                "immediate": index == 0,
                "after_ab_setup": index > 0 and all(t <= int(Tier.B) for t in prefix_tiers),
                "after_c_rework": any(t == int(Tier.C) for t in prefix_tiers),
                "consumed": dest_was_empty and not after_src_empty,
                "transferred": dest_was_empty and after_src_empty,
            }
        apply_action(state, action)
        prefix_tiers.append(tier)
    return None


def _metrics(state: SpiderState) -> dict:
    runs = exposed_run_metrics(state)
    return {
        "fd": sum(len(col.face_down) for col in state.columns),
        "foundations": len(state.foundations),
        "empties": empty_column_indices(state),
        "longest_run": runs["longest_exposed_same_suit_run"],
        "adjacencies": runs["exposed_same_suit_adjacencies"],
        "blocks": runs["movable_same_suit_blocks"],
    }


def _workspace_fingerprint(path_events: Sequence[str], first_use: Optional[dict]) -> tuple:
    return (
        "EMPTY_CONSUMED" in path_events,
        "EMPTY_TRANSFERRED" in path_events,
        "EMPTY_RECREATED" in path_events,
        "SECOND_EMPTY" in path_events,
        None if first_use is None else first_use.get("depth"),
        None if first_use is None else first_use.get("tier"),
    )


@dataclass
class LayeredReachabilityResult:
    completed_generated_depth: int
    completed_expanded_depth: int
    unique: int
    generated: int
    duplicate_skips: int
    path_cycle_skips: int
    min_fd: int
    max_foundations: int
    max_run: int
    max_empties: int
    elapsed_s: float
    peak_rss_mb: Optional[float]
    stop_reason: str
    layers: List[dict] = field(default_factory=list)
    expansion_order: List[int] = field(default_factory=list)
    first_depth: Dict[str, int] = field(default_factory=dict)
    witnesses: Dict[str, dict] = field(default_factory=dict)
    fd12_same_depth: List[dict] = field(default_factory=list)
    initial_empty: Tuple[int, ...] = ()
    processing_log: List[dict] = field(default_factory=list)
    root_digest: str = ""
    fresh_tt: bool = True
    imported_keys: int = 0
    source_count: int = 1
    collected: List[dict] = field(default_factory=list)
    collected_fd: Optional[int] = None
    collected_depth: Optional[int] = None
    collected_complete: bool = False
    collect_partial: bool = False
    depth_expanded_frac: Optional[dict] = None
    cross_origin_dups: int = 0
    origin_paths: List[list] = field(default_factory=list)
    stream_discarded: int = 0
    keys_before_stream: int = 0
    last_layer_generated: int = 0
    last_layer_duplicates: int = 0
    visited_hex: List[str] = field(default_factory=list)
    skipped_expand_parents: int = 0
    parent_fd_counts: Dict[int, int] = field(default_factory=dict)


def face_down_count(state: SpiderState) -> int:
    return sum(len(col.face_down) for col in state.columns)


def fd_trace(seed: SpiderState, actions: Sequence[Action]) -> List[int]:
    """Face-down count after 0, 1, ... len(actions) primitives."""

    state = seed.clone()
    out = [face_down_count(state)]
    for action in actions:
        apply_action(state, action)
        out.append(face_down_count(state))
    return out


def first_fd_leq_depth(trace: Sequence[int], target: int = 11) -> Optional[int]:
    """1-based primitive depth of first fd <= target, or None."""

    for index, fd in enumerate(trace):
        if fd <= target:
            return index
    return None


def classify_first_crossing(trace: Sequence[int], *, target: int = 11) -> str:
    """TRUE_FIRST_CROSSING_DEPTH10, POST_REVEAL_DEPTH10, or INVALID_OR_REPLAY_FAILURE."""

    if len(trace) != 11:
        return "INVALID_OR_REPLAY_FAILURE"
    first = first_fd_leq_depth(trace, target)
    parent_fd = trace[9]
    child_fd = trace[10]
    if first is None:
        return "INVALID_OR_REPLAY_FAILURE"
    if first <= 9:
        return "POST_REVEAL_DEPTH10"
    if first == 10 and parent_fd == target + 1 and child_fd == target:
        return "TRUE_FIRST_CROSSING_DEPTH10"
    return "INVALID_OR_REPLAY_FAILURE"


def is_hard_progress(
    *,
    start_fd: int,
    start_foundations: int,
    fd: int,
    foundations: int,
    empties: int = 0,
    longest_run: int = 0,
    adjacencies: int = 0,
    blocks: int = 0,
) -> bool:
    """Ratchet trigger.  Empties/runs/adjacencies/blocks are ignored."""

    del empties, longest_run, adjacencies, blocks
    return fd < start_fd or foundations > start_foundations


def reconstruct_actions(
    node: int, parent: Sequence[int], src: Sequence[int], dst: Sequence[int], k: Sequence[int]
) -> List[Action]:
    out: List[Action] = []
    current = node
    while parent[current] >= 0:
        out.append((src[current], dst[current], k[current]))
        current = parent[current]
    out.reverse()
    return out


def layered_reachability(
    seed: Optional[SpiderState] = None,
    *,
    sources: Optional[Sequence[SpiderState]] = None,
    origin_paths: Optional[Sequence[Sequence[Action]]] = None,
    max_depth: int = 20,
    max_unique: int = 1_000_000,
    time_limit_s: float = 1800.0,
    rss_abort_mb: float = 8 * 1024.0,
    rules: MobilityWareRules = MW_RULES,
    checkpoints: Sequence[int] = CHECKPOINT_DEPTHS,
    stop_fd: Optional[int] = None,
    collect_fd: Optional[int] = None,
    collect_exact_depth: Optional[int] = None,
    stream_last: bool = False,
    expand_only_fd: Optional[int] = None,
    include_visited_hex: bool = False,
) -> LayeredReachabilityResult:
    """BFS by primitive depth.  Expands depths 0 .. max_depth-1 (states at max_depth known).

    Each call allocates a fresh exact first-visit table.  There is no parameter
    to import a previous visited set.  ``stop_fd`` stops at the first child
    with face-down count <= that value (research harvest only).
    ``collect_fd`` records every min-depth match and does not stop on the first.
    ``collect_exact_depth`` restricts collection to first-seen states at that
    primitive depth.  ``stream_last`` inspects the final generated depth without
    retaining non-candidate children as a future frontier.
    ``sources`` starts a multi-source frontier; later exact states collapse once.
    """

    started = time.perf_counter()
    if sources is None:
        if seed is None:
            raise ValueError("seed or sources required")
        source_states: List[SpiderState] = [seed]
        source_paths: List[List[Action]] = [[]]
    else:
        source_states = list(sources)
        if not source_states:
            raise ValueError("sources is empty")
        source_paths = [list(p) for p in (origin_paths if origin_paths is not None else [[] for _ in source_states])]
        if len(source_paths) != len(source_states):
            source_paths = [list(p) for p in source_paths] + [
                [] for _ in range(len(source_states) - len(source_paths))
            ]
        if seed is None:
            seed = source_states[0]
    root_metrics = _metrics(source_states[0])
    initial_empty = root_metrics["empties"]
    ids: Dict[bytes, int] = {}
    keys: List[bytes] = []
    parent: List[int] = []
    src_a: List[int] = []
    dst_a: List[int] = []
    k_a: List[int] = []
    depth_of: List[int] = []
    fd_of: List[int] = []
    origin: List[int] = []
    multiplicity: Dict[bytes, int] = {}
    source_node: List[int] = []
    min_fd = 10**9
    max_foundations = 0
    max_run = 0
    max_empties = 0
    layer0: List[int] = []
    for origin_id, source in enumerate(source_states):
        key = pack_state(source)
        if key in ids:
            multiplicity[key] = multiplicity.get(key, 1) + 1
            continue
        node = len(keys)
        ids[key] = node
        keys.append(key)
        parent.append(-1)
        src_a.append(-1)
        dst_a.append(-1)
        k_a.append(-1)
        depth_of.append(0)
        metrics = _metrics(source)
        fd_of.append(metrics["fd"])
        origin.append(origin_id)
        multiplicity[key] = 1
        source_node.append(node)
        layer0.append(node)
        min_fd = min(min_fd, metrics["fd"])
        max_foundations = max(max_foundations, metrics["foundations"])
        max_run = max(max_run, metrics["longest_run"])
        max_empties = max(max_empties, len(metrics["empties"]))
    root_key = keys[0]
    fnd_of = [0] * len(keys)
    run_of = [0] * len(keys)
    empty_count_of = [0] * len(keys)
    empty_mask_of = [0] * len(keys)
    ever_zero = [False] * len(keys)
    path_events: List[List[str]] = [[] for _ in keys]
    for node, source in zip(layer0, (source_states[origin[n]] for n in layer0)):
        metrics = _metrics(source)
        fnd_of[node] = metrics["foundations"]
        run_of[node] = metrics["longest_run"]
        empties = metrics["empties"]
        empty_count_of[node] = len(empties)
        empty_mask_of[node] = sum(1 << i for i in empties)
        ever_zero[node] = len(empties) == 0
    layers: List[List[int]] = [layer0]
    expansion_order: List[int] = []
    processing_log: List[dict] = []
    layer_reports: List[dict] = []
    generated = 0
    duplicate_skips = 0
    cross_origin_dups = 0
    collect_nodes: List[int] = []
    collect_depth: Optional[int] = None
    stream_discarded = 0
    keys_before_stream = 0
    last_layer_generated = 0
    last_layer_duplicates = 0
    skipped_expand_parents = 0
    parent_fd_counts: Dict[int, int] = {}
    peak_rss = _rss_mb()
    stop_reason = "max depth"
    witnesses: Dict[str, dict] = {}
    first_depth: Dict[str, int] = {}
    fd12_same_depth: List[dict] = []
    fd12_depth: Optional[int] = None
    fd12_fingerprints = set()

    def note_rss() -> bool:
        nonlocal peak_rss
        rss = _rss_mb()
        if rss is not None and (peak_rss is None or rss > peak_rss):
            peak_rss = rss
        return rss_abort_mb is not None and rss is not None and rss >= rss_abort_mb

    def snapshot_witness(node: int, kind: str, extra: Optional[dict] = None) -> dict:
        actions = reconstruct_actions(node, parent, src_a, dst_a, k_a)
        empties = tuple(i for i in range(10) if empty_mask_of[node] & (1 << i))
        payload = {
            "kind": kind,
            "node": node,
            "depth": depth_of[node],
            "actions": [list(action) for action in actions],
            "fd": fd_of[node],
            "foundations": fnd_of[node],
            "longest_run": run_of[node],
            "empties": list(empties),
            "empty_count": empty_count_of[node],
            "path_events": list(path_events[node]),
        }
        if extra:
            payload.update(extra)
        return payload

    def record_kind(kind: str, node: int) -> None:
        nonlocal fd12_depth
        if kind not in first_depth:
            first_depth[kind] = depth_of[node]
            witnesses[kind] = snapshot_witness(node, kind)
        if kind == "fd_le_12":
            if fd12_depth is None:
                fd12_depth = depth_of[node]
            if depth_of[node] == fd12_depth:
                first_use = None
                actions = reconstruct_actions(node, parent, src_a, dst_a, k_a)
                first_use = first_empty_use_on_path(source_states[origin[node]], actions)
                fingerprint = _workspace_fingerprint(path_events[node], first_use)
                if fingerprint not in fd12_fingerprints:
                    fd12_fingerprints.add(fingerprint)
                    item = snapshot_witness(node, "fd_le_12")
                    item["first_empty_use"] = first_use
                    item["fingerprint"] = list(fingerprint)
                    fd12_same_depth.append(item)

    def finish_layer_report(depth: int, expanded: bool, gen: int, dups: int, by_tier: List[int], n_zero: int, n_one: int, n_two: int) -> None:
        frontier = layers[depth]
        layer_reports.append(
            {
                "depth": depth,
                "frontier_size": len(frontier),
                "cumulative_unique": len(keys),
                "generated_successors": gen,
                "exact_duplicate_skips": dups,
                "path_cycle_skips": 0,
                "a_children": by_tier[0],
                "b_children": by_tier[1],
                "c_children": by_tier[2],
                "states_empty_0": n_zero,
                "states_empty_1": n_one,
                "states_empty_ge2": n_two,
                "min_fd": min((fd_of[i] for i in frontier), default=min_fd),
                "max_foundations": max((fnd_of[i] for i in frontier), default=max_foundations),
                "max_run": max((run_of[i] for i in frontier), default=max_run),
                "expanded": expanded,
                "origins_represented": len({origin[i] for i in frontier}) if origin else 1,
            }
        )

    deadline = started + time_limit_s
    last_generated = 0
    last_expanded = -1
    found_foundation = False
    found_target_fd = False
    incomplete_frac: Optional[dict] = None

    for depth in range(0, max_depth):
        if found_foundation or found_target_fd:
            break
        if time.perf_counter() >= deadline:
            stop_reason = "time limit"
            break
        if note_rss():
            stop_reason = "rss abort"
            break
        if depth >= len(layers) or not layers[depth]:
            stop_reason = "frontier empty"
            break
        expansion_order.append(depth)
        frontier = layers[depth]
        streaming = stream_last and depth == max_depth - 1
        if streaming:
            keys_before_stream = len(keys)
            parent_fd_counts = {}
            for index in frontier:
                fdv = fd_of[index]
                parent_fd_counts[fdv] = parent_fd_counts.get(fdv, 0) + 1
        gen_here = 0
        dups_here = 0
        by_tier = [0, 0, 0, 0]
        next_ids: List[int] = []
        processing_log.append({"depth": depth, "expanding": len(frontier), "unique_before": len(keys)})
        incomplete = False
        processed = 0
        for node in frontier:
            processed += 1
            if found_foundation or found_target_fd:
                break
            if time.perf_counter() >= deadline:
                stop_reason = "time limit"
                incomplete = True
                break
            if (len(keys) & 2047) == 0 and note_rss():
                stop_reason = "rss abort"
                incomplete = True
                break
            if streaming and expand_only_fd is not None and fd_of[node] != expand_only_fd:
                skipped_expand_parents += 1
                continue
            state = unpack_state(keys[node])
            parent_empties = empty_column_indices(state)
            for action in enumerate_actions(state, rules=rules):
                if action == ("deal",):
                    continue
                tier = int(classify_tier(state, action))
                if tier > MAX_TIER:
                    continue
                src, dst, k = action  # type: ignore[misc]
                dest_was_empty = state.columns[dst].is_empty()
                source_becomes_empty = (
                    k == len(state.columns[src].face_up) and not state.columns[src].face_down
                )
                snap = _capture(state, action)
                try:
                    apply_action(state, action, rules=rules)
                    generated += 1
                    gen_here += 1
                    by_tier[tier] += 1
                    child_key = pack_state(state)
                    if streaming:
                        last_layer_generated += 1
                    if child_key in ids:
                        duplicate_skips += 1
                        dups_here += 1
                        if streaming:
                            last_layer_duplicates += 1
                        multiplicity[child_key] = multiplicity.get(child_key, 1) + 1
                        if origin[ids[child_key]] != origin[node]:
                            cross_origin_dups += 1
                        continue
                    child_empties = empty_column_indices(state)
                    child_metrics = _metrics(state)
                    if streaming:
                        keep = (
                            child_metrics["foundations"] >= 1
                            or child_metrics["fd"] <= 10
                            or (
                                collect_fd is not None
                                and child_metrics["fd"] == collect_fd
                                and (
                                    collect_exact_depth is None
                                    or depth + 1 == collect_exact_depth
                                )
                            )
                        )
                        if not keep:
                            stream_discarded += 1
                            continue
                    if len(keys) >= max_unique:
                        stop_reason = "unique limit"
                        incomplete = True
                        break
                    events = empty_transition_events(
                        parent_empties,
                        child_empties,
                        dest_was_empty=dest_was_empty,
                        source_became_empty=source_becomes_empty,
                    )
                    child_id = len(keys)
                    ids[child_key] = child_id
                    keys.append(child_key)
                    parent.append(node)
                    src_a.append(src)
                    dst_a.append(dst)
                    k_a.append(k)
                    depth_of.append(depth + 1)
                    fd_of.append(child_metrics["fd"])
                    origin.append(origin[node])
                    multiplicity[child_key] = 1
                    fnd_of.append(child_metrics["foundations"])
                    run_of.append(child_metrics["longest_run"])
                    empty_count_of.append(len(child_empties))
                    empty_mask_of.append(sum(1 << i for i in child_empties))
                    child_ever_zero = ever_zero[node] or len(child_empties) == 0
                    ever_zero.append(child_ever_zero)
                    path_events.append(path_events[node] + events)
                    if not streaming:
                        next_ids.append(child_id)
                    if collect_fd is not None:
                        match_fd = (
                            child_metrics["fd"] == collect_fd
                            if collect_exact_depth is not None
                            else child_metrics["fd"] <= collect_fd
                        )
                        if match_fd:
                            if collect_exact_depth is not None:
                                if depth + 1 == collect_exact_depth:
                                    collect_depth = collect_exact_depth
                                    collect_nodes.append(child_id)
                            else:
                                if collect_depth is None:
                                    collect_depth = depth + 1
                                if depth + 1 == collect_depth:
                                    collect_nodes.append(child_id)
                    min_fd = min(min_fd, child_metrics["fd"])
                    max_foundations = max(max_foundations, child_metrics["foundations"])
                    max_run = max(max_run, child_metrics["longest_run"])
                    max_empties = max(max_empties, len(child_empties))
                    if "EMPTY_TRANSFERRED" in events:
                        record_kind("empty_transferred", child_id)
                    if "EMPTY_CONSUMED" in events:
                        record_kind("empty_consumed", child_id)
                    if "EMPTY_RECREATED" in events:
                        record_kind("empty_recreated", child_id)
                    if "SECOND_EMPTY" in events:
                        record_kind("second_empty", child_id)
                    if child_metrics["longest_run"] >= 10:
                        record_kind("run_ge_10", child_id)
                    if child_metrics["fd"] <= 12:
                        record_kind("fd_le_12", child_id)
                    if child_metrics["fd"] <= 11:
                        record_kind("fd_le_11", child_id)
                    if child_metrics["fd"] <= 10:
                        record_kind("fd_le_10", child_id)
                    if child_metrics["fd"] <= 9:
                        record_kind("fd_le_9", child_id)
                    if child_metrics["foundations"] >= 1:
                        record_kind("foundation", child_id)
                        found_foundation = True
                        stop_reason = "foundation"
                        break
                    if stop_fd is not None and child_metrics["fd"] <= stop_fd:
                        found_target_fd = True
                        stop_reason = f"fd <= {stop_fd}"
                        break
                finally:
                    _restore(state, snap)
            if incomplete:
                break
        # occupancy of THIS depth's frontier (already known)
        n_zero = sum(1 for i in frontier if empty_count_of[i] == 0)
        n_one = sum(1 for i in frontier if empty_count_of[i] == 1)
        n_two = sum(1 for i in frontier if empty_count_of[i] >= 2)
        finish_layer_report(
            depth,
            expanded=not incomplete and not found_foundation and not found_target_fd,
            gen=gen_here,
            dups=dups_here,
            by_tier=by_tier,
            n_zero=n_zero,
            n_one=n_one,
            n_two=n_two,
        )
        if next_ids and depth + 1 == len(layers):
            layers.append(next_ids)
        if found_foundation or found_target_fd:
            last_generated = max(last_generated, depth + 1)
            break
        if incomplete:
            incomplete_frac = {
                "depth": depth,
                "processed": processed,
                "frontier": len(frontier),
            }
            break
        last_expanded = depth
        if streaming:
            last_generated = depth + 1
            stop_reason = "max depth"
            print(
                f"CHECKPOINT depth={depth + 1} unique={len(keys)} streamed={last_layer_generated} "
                f"discarded={stream_discarded} candidates={len(collect_nodes)} "
                f"min_fd={min_fd} run={max_run} fnd={max_foundations}",
                flush=True,
            )
            break
        if next_ids:
            last_generated = depth + 1
        else:
            stop_reason = "frontier empty"
            break
        if depth + 1 in checkpoints:
            print(
                f"CHECKPOINT depth={depth + 1} unique={len(keys)} frontier={len(next_ids)} "
                f"min_fd={min_fd} run={max_run} fnd={max_foundations} empties={max_empties}",
                flush=True,
            )
        if found_foundation or found_target_fd:
            break

    # If we generated max_depth but did not expand it, still report occupancy of that frontier.
    if last_generated == max_depth and last_generated < len(layers) and last_generated not in {r["depth"] for r in layer_reports}:
        frontier = layers[last_generated]
        n_zero = sum(1 for i in frontier if empty_count_of[i] == 0)
        n_one = sum(1 for i in frontier if empty_count_of[i] == 1)
        n_two = sum(1 for i in frontier if empty_count_of[i] >= 2)
        finish_layer_report(
            last_generated,
            expanded=False,
            gen=0,
            dups=0,
            by_tier=[0, 0, 0, 0],
            n_zero=n_zero,
            n_one=n_one,
            n_two=n_two,
        )

    # Enrich stored witnesses with first-empty-use and local cost.
    for kind, witness in list(witnesses.items()):
        node = witness["node"]
        actions: List[Action] = reconstruct_actions(node, parent, src_a, dst_a, k_a)
        root = source_states[origin[node]]
        witness["origin"] = origin[node]
        witness["first_empty_use"] = first_empty_use_on_path(root, actions)
        local_state = root.clone()
        try:
            witness["local_cost"] = replay_actions(local_state, actions)
            witness["adjacencies"] = _metrics(local_state)["adjacencies"]
            witness["blocks"] = _metrics(local_state)["blocks"]
            seq = [list(empty_column_indices(root))]
            walk = root.clone()
            for action in actions:
                apply_action(walk, action)
                seq.append(list(empty_column_indices(walk)))
            witness["empty_sequence"] = seq
        except (ValueError, AssertionError) as exc:
            witness["local_cost"] = None
            witness["replay_error"] = str(exc)
        witness.pop("node", None)

    collected: List[dict] = []
    collect_complete = False
    if collect_fd is not None:
        if collect_exact_depth is None and collect_depth is None:
            for index, fdv in enumerate(fd_of):
                if fdv <= collect_fd:
                    collect_depth = (
                        depth_of[index]
                        if collect_depth is None
                        else min(collect_depth, depth_of[index])
                    )
            if collect_depth is not None:
                collect_nodes = [
                    index
                    for index in range(len(keys))
                    if depth_of[index] == collect_depth and fd_of[index] <= collect_fd
                ]
        seen_collect = set()
        for node in collect_nodes:
            digest = keys[node].hex()
            if digest in seen_collect:
                continue
            seen_collect.add(digest)
            empties = tuple(i for i in range(10) if empty_mask_of[node] & (1 << i))
            collected.append(
                {
                    "digest": digest,
                    "depth": depth_of[node],
                    "fd": fd_of[node],
                    "foundations": fnd_of[node],
                    "longest_run": run_of[node],
                    "empties": list(empties),
                    "actions": [list(act) for act in reconstruct_actions(node, parent, src_a, dst_a, k_a)],
                    "hits": multiplicity.get(keys[node], 1),
                    "origin": origin[node],
                    "parent_fd": None if parent[node] < 0 else fd_of[parent[node]],
                    "parent_digest": None if parent[node] < 0 else keys[parent[node]].hex(),
                }
            )
        if collect_exact_depth is not None:
            collect_complete = incomplete_frac is None and last_expanded >= collect_exact_depth - 1
        else:
            collect_complete = (
                collect_depth is not None
                and last_generated >= collect_depth
                and incomplete_frac is None
                and not found_target_fd
            )

    for item in fd12_same_depth:
        item.pop("node", None)

    elapsed = time.perf_counter() - started
    if found_foundation:
        stop_reason = "foundation"
    elif found_target_fd and stop_fd is not None:
        stop_reason = f"fd <= {stop_fd}"
    elif last_generated >= max_depth and stop_reason == "max depth":
        stop_reason = "max depth"

    return LayeredReachabilityResult(
        completed_generated_depth=last_generated,
        completed_expanded_depth=last_expanded,
        unique=len(keys),
        generated=generated,
        duplicate_skips=duplicate_skips,
        path_cycle_skips=0,
        min_fd=min_fd,
        max_foundations=max_foundations,
        max_run=max_run,
        max_empties=max_empties,
        elapsed_s=elapsed,
        peak_rss_mb=peak_rss if peak_rss is not None else _rss_mb(),
        stop_reason=stop_reason,
        layers=layer_reports,
        expansion_order=expansion_order,
        first_depth=first_depth,
        witnesses=witnesses,
        fd12_same_depth=fd12_same_depth,
        initial_empty=initial_empty,
        processing_log=processing_log,
        root_digest=root_key.hex() if len(source_states) == 1 else "multi",
        fresh_tt=True,
        imported_keys=0,
        source_count=len(source_states),
        collected=collected,
        collected_fd=collect_fd,
        collected_depth=collect_depth,
        collected_complete=collect_complete,
        collect_partial=bool(collect_fd is not None and not collect_complete),
        depth_expanded_frac=incomplete_frac,
        cross_origin_dups=cross_origin_dups,
        origin_paths=[list(p) for p in source_paths],
        stream_discarded=stream_discarded,
        keys_before_stream=keys_before_stream,
        last_layer_generated=last_layer_generated,
        last_layer_duplicates=last_layer_duplicates,
        visited_hex=[k.hex() for k in keys] if include_visited_hex else [],
        skipped_expand_parents=skipped_expand_parents,
        parent_fd_counts=parent_fd_counts,
    )
