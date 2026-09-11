"""Research-only perfect-information Deal-1 preview.

Phase 1 enumerates pre-Deal tableau candidates without expanding Deal.
Phase 2 applies the real engine Deal virtually to each candidate.
Phase 3 searches the distinct post-Deal children with Deal 2 forbidden.

No Deal heuristic.  Production ``solve_progressive`` is not imported.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.packed_state import pack_state, unpack_state
from spider.rules import MW_RULES, MobilityWareRules
from spider.simple_legacy_fd13_alternatives import legal_tableau_count, reveal_target_from_transition
from spider.simple_post_deal_audit import census_legal_by_tier, exposed_run_metrics
from spider.simple_progressive_solver import _capture, _restore, _rss_mb, apply_action
from spider.simple_workspace_reachability import (
    _metrics,
    empty_column_indices,
    engine_tableau_actions,
    face_down_count,
    reconstruct_actions,
)

BEFORE_DEAL = "BEFORE_DEAL"
DEAL_NOW = "DEAL_NOW"
PREPARE_THEN_DEAL = "PREPARE_THEN_DEAL"


def stock_rows(state: SpiderState) -> int:
    return len(state.stock) // 10


def next_stock_row(state: SpiderState) -> List[Tuple[str, int]]:
    if len(state.stock) < 10:
        return []
    return [(c.suit, int(c.rank)) for c in state.stock[-10:]]


def card_pair(card) -> List:
    return [card.suit, int(card.rank)]


def snapshot_metrics(state: SpiderState) -> dict:
    runs = exposed_run_metrics(state)
    census = census_legal_by_tier(state)
    return {
        "fd": face_down_count(state),
        "foundations": len(state.foundations),
        "stock_rows": stock_rows(state),
        "empties": list(empty_column_indices(state)),
        "empty_count": len(empty_column_indices(state)),
        "longest_run": runs["longest_exposed_same_suit_run"],
        "adjacencies": runs["exposed_same_suit_adjacencies"],
        "movable_blocks": runs["movable_same_suit_blocks"],
        "legal_tableau": census["legal_tableau"],
        "deal_legal": bool(census["deal_legal"]),
        "census": {
            "a": census["a"],
            "b": census["b"],
            "c": census["c"],
            "d": census["d"],
            "tableau_a": census["tableau_a"],
            "tableau_b": census["tableau_b"],
            "tableau_c": census["tableau_c"],
            "tableau_d": census["tableau_d"],
        },
        "ordered_digest": pack_state(state).hex(),
    }


def deal_reception_telemetry(before: SpiderState, after: SpiderState, row: Sequence[Tuple[str, int]]) -> dict:
    same_suit = 0
    mixed = 0
    onto_empty = 0
    by_column = []
    for index, (suit, rank) in enumerate(row):
        pre = before.columns[index]
        empty = pre.is_empty()
        top = None if empty or not pre.face_up else pre.face_up[-1]
        join = None
        if empty:
            onto_empty += 1
            join = "empty"
        elif top is not None and top.rank == rank + 1:
            if top.suit == suit:
                same_suit += 1
                join = "same_suit"
            else:
                mixed += 1
                join = "mixed"
        by_column.append(
            {
                "column_0": index,
                "card": [suit, rank],
                "onto_empty": empty,
                "prev_top": None if top is None else card_pair(top),
                "join": join,
            }
        )
    after_m = _metrics(after)
    return {
        "incoming": [list(item) for item in row],
        "same_suit_joins": same_suit,
        "mixed_suit_joins": mixed,
        "onto_empty": onto_empty,
        "by_column": by_column,
        "post_legal_tableau": legal_tableau_count(after),
        "post_longest_run": after_m["longest_run"],
        "post_adjacencies": after_m["adjacencies"],
        "post_blocks": after_m["blocks"],
        "post_empties": list(after_m["empties"]),
        "post_fd": after_m["fd"],
        "post_foundations": after_m["foundations"],
        "post_stock_rows": stock_rows(after),
        "post_ordered_digest": pack_state(after).hex(),
    }


def episode_actions(state: SpiderState, *, dealt: bool, rules: MobilityWareRules = MW_RULES) -> List[Action]:
    """Engine-legal actions permitted in the current episode phase.

    Deal remains engine-legal after the first Deal; this filter only withholds
    Deal 2 from the bounded preview.  Tableau moves are never dropped.
    """

    actions, _ = engine_tableau_actions(state, rules=rules)
    if not dealt and state.can_deal(rules=rules):
        # Phase 1 withholds Deal from expansion; callers pass dealt=True to omit it.
        pass
    return actions


@dataclass
class TableauLayerResult:
    unique: int
    generated: int
    duplicate_skips: int
    expanded: int
    completed_expanded_depth: int
    completed_generated_depth: int
    expansion_order: List[int]
    elapsed_s: float
    peak_rss_mb: Optional[float]
    stop_reason: str
    min_fd: int
    max_foundations: int
    progress_edges: int
    progress: List[dict] = field(default_factory=list)
    domain_violations: int = 0
    classifier_surprises: int = 0
    keys: List[bytes] = field(default_factory=list)
    parent: List[int] = field(default_factory=list)
    src_a: List[int] = field(default_factory=list)
    dst_a: List[int] = field(default_factory=list)
    k_a: List[int] = field(default_factory=list)
    depth_of: List[int] = field(default_factory=list)
    origin_of: List[int] = field(default_factory=list)
    layers: List[dict] = field(default_factory=list)
    source_count: int = 1
    unique_sources: int = 1
    cross_origin_dups: int = 0
    empty0: int = 0
    empty1: int = 0
    empty_ge2: int = 0
    max_run: int = 0
    max_adjacencies: int = 0
    max_blocks: int = 0
    zero_legal_tableau: int = 0
    legal_count_hist: Dict[int, int] = field(default_factory=dict)
    fresh_tt: bool = True
    all_legal_tableau: bool = True
    heuristic: bool = False
    deal_expanded: bool = False
    first_fd_depth: Dict[int, int] = field(default_factory=dict)
    progress_fd_at_most: Optional[int] = None
    progress_foundations_at_least: Optional[int] = None


def tableau_layer_bfs(
    sources: Sequence[SpiderState],
    *,
    origin_paths: Optional[Sequence[Sequence[Action]]] = None,
    max_depth: int = 8,
    max_unique: int = 500_000,
    time_limit_s: float = 600.0,
    rss_abort_mb: float = 2 * 1024.0,
    rules: MobilityWareRules = MW_RULES,
    checkpoints: Sequence[int] = (4, 8),
    identity_fn=None,
    expand_progress: bool = False,
    stop_after_progress_layer: bool = False,
    require_stock_rows: Optional[int] = None,
    progress_fd_at_most: Optional[int] = None,
    progress_foundations_at_least: Optional[int] = None,
) -> TableauLayerResult:
    """Layered BFS of tableau moves only.  Deal is never expanded.

    ``stop_after_progress_layer`` finishes the parent layer that first
    generated hard-progress children, then stops.

    By default hard progress is any fd drop below the source fd.  When
    ``progress_fd_at_most`` is set, only fd at or below that threshold
    (or a new foundation) counts; intermediate fd drops still enqueue.
    When ``progress_foundations_at_least`` is set, only foundation count
    at or above that threshold counts; fd drops are telemetry only.
    """

    if identity_fn is None:
        identity_fn = pack_state
    if not sources:
        raise ValueError("sources is empty")
    source_states = list(sources)
    source_paths = [list(p) for p in (origin_paths if origin_paths is not None else [[] for _ in source_states])]
    started = time.perf_counter()
    ids: Dict[bytes, int] = {}
    keys: List[bytes] = []
    parent: List[int] = []
    src_a: List[int] = []
    dst_a: List[int] = []
    k_a: List[int] = []
    depth_of: List[int] = []
    origin_of: List[int] = []

    def add_node(concrete, ident, parent_id, src, dst, k, depth, origin) -> int:
        node = len(keys)
        ids[ident] = node
        keys.append(concrete)
        parent.append(parent_id)
        src_a.append(src)
        dst_a.append(dst)
        k_a.append(k)
        depth_of.append(depth)
        origin_of.append(origin)
        return node

    layer0: List[int] = []
    cross_origin_dups = 0
    empty0 = empty1 = empty_ge2 = 0
    max_run = max_adjacencies = max_blocks = 0
    zero_legal_tableau = 0
    legal_count_hist: Dict[int, int] = {}
    for origin_id, source in enumerate(source_states):
        ident = identity_fn(source)
        if ident in ids:
            cross_origin_dups += 1
            continue
        metrics = _metrics(source)
        n_empty = len(metrics["empties"])
        empty0 += int(n_empty == 0)
        empty1 += int(n_empty == 1)
        empty_ge2 += int(n_empty >= 2)
        max_run = max(max_run, metrics["longest_run"])
        max_adjacencies = max(max_adjacencies, metrics["adjacencies"])
        max_blocks = max(max_blocks, metrics["blocks"])
        layer0.append(add_node(pack_state(source), ident, -1, -1, -1, -1, 0, origin_id))

    generated = 0
    duplicate_skips = 0
    expanded = 0
    progress_edges = 0
    progress: Dict[bytes, dict] = {}
    classifier_surprises = 0
    domain_violations = 0
    expansion_order: List[int] = []
    layer_reports: List[dict] = []
    min_fd = 10**9
    max_foundations = 0
    peak_rss = _rss_mb()
    stop_reason = "max depth"
    layers: List[List[int]] = [layer0]
    last_expanded = -1
    last_generated = 0
    deadline = started + time_limit_s
    incomplete = False
    start_fd = face_down_count(source_states[0])
    start_fnd = len(source_states[0].foundations)
    progress_depth: Optional[int] = None
    first_fd_depth: Dict[int, int] = {}

    def note_fd(fd: int, depth: int) -> None:
        prev = first_fd_depth.get(fd)
        if prev is None or depth < prev:
            first_fd_depth[fd] = depth

    def is_hard_progress(fd: int, foundations: int) -> bool:
        if progress_foundations_at_least is not None:
            return foundations >= progress_foundations_at_least
        if foundations > start_fnd:
            return True
        if progress_fd_at_most is not None:
            return fd <= progress_fd_at_most
        return fd < start_fd

    for source in source_states:
        src_fd = face_down_count(source)
        note_fd(src_fd, 0)
        min_fd = min(min_fd, src_fd)
        max_foundations = max(max_foundations, len(source.foundations))

    def note_rss() -> bool:
        nonlocal peak_rss
        rss = _rss_mb()
        if rss is not None and (peak_rss is None or rss > peak_rss):
            peak_rss = rss
        return rss_abort_mb is not None and rss is not None and rss >= rss_abort_mb

    for depth in range(0, max_depth):
        if time.perf_counter() >= deadline:
            stop_reason = "time limit"
            incomplete = True
            break
        if note_rss():
            stop_reason = "rss abort"
            incomplete = True
            break
        if depth >= len(layers) or not layers[depth]:
            stop_reason = "frontier empty"
            break
        expansion_order.append(depth)
        frontier = layers[depth]
        next_ids: List[int] = []
        gen_here = 0
        dups_here = 0
        progress_here = 0
        for node in frontier:
            if time.perf_counter() >= deadline:
                stop_reason = "time limit"
                incomplete = True
                break
            if (len(keys) & 2047) == 0 and note_rss():
                stop_reason = "rss abort"
                incomplete = True
                break
            state = unpack_state(keys[node])
            metrics = _metrics(state)
            min_fd = min(min_fd, metrics["fd"])
            max_foundations = max(max_foundations, metrics["foundations"])
            if not expand_progress and is_hard_progress(metrics["fd"], metrics["foundations"]):
                continue
            expanded += 1
            actions, surprises = engine_tableau_actions(state, rules=rules)
            classifier_surprises += len(surprises)
            n_legal = len(actions)
            legal_count_hist[n_legal] = legal_count_hist.get(n_legal, 0) + 1
            if n_legal == 0:
                zero_legal_tableau += 1
            for action in actions:
                if action == ("deal",):
                    domain_violations += 1
                    continue
                src, dst, k = action  # type: ignore[misc]
                snap = _capture(state, action)
                try:
                    apply_action(state, action, rules=rules)
                    generated += 1
                    gen_here += 1
                    child_m = _metrics(state)
                    min_fd = min(min_fd, child_m["fd"])
                    max_foundations = max(max_foundations, child_m["foundations"])
                    note_fd(child_m["fd"], depth + 1)
                    ident = identity_fn(state)
                    is_progress = is_hard_progress(child_m["fd"], child_m["foundations"])
                    if require_stock_rows is not None and stock_rows(state) != require_stock_rows:
                        domain_violations += 1
                        continue
                    if is_progress:
                        progress_edges += 1
                        progress_here += 1
                        child_depth = depth + 1
                        if progress_depth is None:
                            progress_depth = child_depth
                        if child_depth == progress_depth and ident not in progress:
                            local = reconstruct_actions(node, parent, src_a, dst_a, k_a) + [action]
                            progress[ident] = {
                                "ordered_digest": pack_state(state).hex(),
                                "identity": ident.hex(),
                                "actions": [list(a) for a in local],
                                "depth": child_depth,
                                "origin": origin_of[node],
                                "fd": child_m["fd"],
                                "foundations": child_m["foundations"],
                                "empties": list(child_m["empties"]),
                                "longest_run": child_m["longest_run"],
                                "adjacencies": child_m["adjacencies"],
                                "movable_blocks": child_m["blocks"],
                                "legal_action_count": legal_tableau_count(state),
                                "stock_rows": stock_rows(state),
                                "foundation_suits": [run[0].suit for run in state.foundations if run],
                                "hits": 1,
                            }
                        elif ident in progress:
                            progress[ident]["hits"] += 1
                        if not expand_progress:
                            continue
                    if ident in ids:
                        duplicate_skips += 1
                        dups_here += 1
                        if origin_of[ids[ident]] != origin_of[node]:
                            cross_origin_dups += 1
                        continue
                    if len(keys) >= max_unique:
                        stop_reason = "unique limit"
                        incomplete = True
                        break
                    n_empty = len(child_m["empties"])
                    empty0 += int(n_empty == 0)
                    empty1 += int(n_empty == 1)
                    empty_ge2 += int(n_empty >= 2)
                    max_run = max(max_run, child_m["longest_run"])
                    max_adjacencies = max(max_adjacencies, child_m["adjacencies"])
                    max_blocks = max(max_blocks, child_m["blocks"])
                    next_ids.append(
                        add_node(
                            pack_state(state),
                            ident,
                            node,
                            src,
                            dst,
                            k,
                            depth + 1,
                            origin_of[node],
                        )
                    )
                finally:
                    _restore(state, snap)
            if incomplete:
                break
        layer_reports.append(
            {
                "depth": depth,
                "frontier_size": len(frontier),
                "cumulative_unique": len(keys),
                "generated_successors": gen_here,
                "exact_duplicate_skips": dups_here,
                "progress_edges": progress_here,
                "progress_classes": len(progress),
                "min_fd": min_fd,
                "origins_represented": len({origin_of[i] for i in frontier}),
                "expanded": not incomplete,
            }
        )
        if incomplete:
            last_generated = max(last_generated, depth + 1)
            break
        last_expanded = depth
        if stop_after_progress_layer and progress_depth is not None and progress_depth == depth + 1:
            last_generated = depth + 1
            stop_reason = "progress layer complete"
            break
        if next_ids:
            layers.append(next_ids)
            last_generated = depth + 1
        else:
            stop_reason = "frontier empty"
            break
        if depth + 1 in checkpoints:
            print(
                f"CHECKPOINT tableau_depth={depth + 1} unique={len(keys)} frontier={len(next_ids)} "
                f"progress={len(progress)} min_fd={min_fd}",
                flush=True,
            )
        if depth + 1 >= max_depth:
            stop_reason = "max depth"
            break

    elapsed = time.perf_counter() - started
    for rec in progress.values():
        origin = rec["origin"]
        walk = source_states[origin].clone()
        try:
            rec["local_cost"] = replay_actions(walk, [tuple(a) for a in rec["actions"]])
            rec["replay_ok"] = True
        except (ValueError, AssertionError) as exc:
            rec["local_cost"] = None
            rec["replay_ok"] = False
            rec["replay_error"] = str(exc)

    return TableauLayerResult(
        unique=len(keys),
        generated=generated,
        duplicate_skips=duplicate_skips,
        expanded=expanded,
        completed_expanded_depth=last_expanded,
        completed_generated_depth=last_generated,
        expansion_order=expansion_order,
        elapsed_s=elapsed,
        peak_rss_mb=peak_rss if peak_rss is not None else _rss_mb(),
        stop_reason=stop_reason,
        min_fd=min_fd if min_fd < 10**9 else face_down_count(source_states[0]),
        max_foundations=max_foundations,
        progress_edges=progress_edges,
        progress=list(progress.values()),
        domain_violations=domain_violations,
        classifier_surprises=classifier_surprises,
        keys=keys,
        parent=parent,
        src_a=src_a,
        dst_a=dst_a,
        k_a=k_a,
        depth_of=depth_of,
        origin_of=origin_of,
        layers=layer_reports,
        source_count=len(source_states),
        unique_sources=len(layer0),
        cross_origin_dups=cross_origin_dups,
        empty0=empty0,
        empty1=empty1,
        empty_ge2=empty_ge2,
        max_run=max_run,
        max_adjacencies=max_adjacencies,
        max_blocks=max_blocks,
        zero_legal_tableau=zero_legal_tableau,
        legal_count_hist=legal_count_hist,
        first_fd_depth=first_fd_depth,
        progress_fd_at_most=progress_fd_at_most,
        progress_foundations_at_least=progress_foundations_at_least,
    )


def virtual_deal_candidates(
    root: SpiderState,
    phase1: TableauLayerResult,
    *,
    known_row: Sequence[Tuple[str, int]],
    rules: MobilityWareRules = MW_RULES,
) -> dict:
    """Apply engine Deal to every Phase-1 candidate without mutating them."""

    children: Dict[bytes, dict] = {}
    telemetry_sum = {
        "same_suit_joins": 0,
        "mixed_suit_joins": 0,
        "onto_empty": 0,
        "pre_empty_ge1": 0,
        "n": 0,
    }
    control_digest = None
    mutated = False
    root_before = pack_state(root)
    for node, concrete in enumerate(phase1.keys):
        pre = unpack_state(concrete)
        if pack_state(pre) != concrete:
            mutated = True
        if face_down_count(pre) < 14 or len(pre.foundations) >= 1:
            continue
        if not pre.can_deal(rules=rules):
            continue
        pre_m = _metrics(pre)
        child = pre.clone()
        apply_action(child, ("deal",), rules=rules)
        ident = pack_state(child)
        recp = deal_reception_telemetry(pre, child, known_row)
        telemetry_sum["same_suit_joins"] += recp["same_suit_joins"]
        telemetry_sum["mixed_suit_joins"] += recp["mixed_suit_joins"]
        telemetry_sum["onto_empty"] += recp["onto_empty"]
        telemetry_sum["pre_empty_ge1"] += int(len(pre_m["empties"]) >= 1)
        telemetry_sum["n"] += 1
        depth = phase1.depth_of[node]
        if ident not in children:
            local = reconstruct_actions(node, phase1.parent, phase1.src_a, phase1.dst_a, phase1.k_a)
            children[ident] = {
                "post_ordered_digest": ident.hex(),
                "pre_ordered_digest": concrete.hex(),
                "pre_depth": depth,
                "pre_actions": [list(a) for a in local],
                "pre_empties": list(pre_m["empties"]),
                "pre_longest_run": pre_m["longest_run"],
                "pre_adjacencies": pre_m["adjacencies"],
                "pre_blocks": pre_m["blocks"],
                "pre_legal_tableau": legal_tableau_count(pre),
                "reception": recp,
                "is_deal_now": depth == 0,
                "origins": 1,
                "min_pre_depth": depth,
            }
        else:
            children[ident]["origins"] += 1
            if depth < children[ident]["min_pre_depth"]:
                children[ident]["min_pre_depth"] = depth
                children[ident]["pre_depth"] = depth
                children[ident]["pre_actions"] = [
                    list(a)
                    for a in reconstruct_actions(node, phase1.parent, phase1.src_a, phase1.dst_a, phase1.k_a)
                ]
                children[ident]["is_deal_now"] = depth == 0
        if depth == 0:
            control_digest = ident.hex()
    if pack_state(root) != root_before:
        mutated = True
    return {
        "n_candidates_dealt": telemetry_sum["n"],
        "n_distinct_children": len(children),
        "control_post_digest": control_digest,
        "root_unmutated": not mutated,
        "join_totals": telemetry_sum,
        "children": list(children.values()),
    }


def classify_timing(pre_depth: int) -> str:
    if pre_depth <= 0:
        return DEAL_NOW
    return PREPARE_THEN_DEAL
