"""Research-only equal-envelope foundation race: Heart 1 vs Diamond 1.

Tableau only.  SD5 is never expanded.  Full accumulated MW is the search g.
Target labels are witness-finding priorities, not legality.
"""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set

from spider.engine import SpiderState
from spider.metrics import Action
from spider.packed_state import pack_state, unpack_state
from spider.simple_current_horizon import backward_map, occurrence_counts
from spider.simple_deal1_preview import stock_rows
from spider.simple_foundation_horizon import pretty_card
from spider.simple_h9_cut import GOOD_PLAY, JOIN_BREAK, OTHER, PARK, allowed_at_level
from spider.simple_progressive_solver import (
    Tier,
    _capture,
    _restore,
    _rss_mb,
    apply_action,
    classify_tier,
    step_cost,
)
from spider.simple_workspace_reachability import empty_column_indices, engine_tableau_actions, face_down_count

TARGET_JOIN = "TARGET_JOIN"
TARGET_DIRECT = "TARGET_DIRECT"
TARGET_UNCOVER = "TARGET_UNCOVER"
LANDING_SUPPORT = "TARGET_LANDING"
COST_CEILING = 100


def suit_foundation_count(state: SpiderState, suit: str) -> int:
    return sum(1 for run in state.foundations if run and run[0].suit == suit)


def unique_target_columns(state: SpiderState, suit: str) -> Set[int]:
    cols: Set[int] = set()
    for rank in range(1, 14):
        rec = occurrence_counts(state, suit, rank)
        if rec["current_count"] != 1:
            continue
        for occ in rec["tableau"]:
            cols.add(occ["column_0"])
    return cols


def annotate_race_action(state: SpiderState, action, suit: str, hot: Set[int]) -> str:
    if action == ("deal",):
        return "DEAL"
    src, dst, k = action
    src_col = state.columns[src]
    dst_col = state.columns[dst]
    dest_empty = dst_col.is_empty()
    run = src_col.face_up[-k:]
    uncovers = k == len(src_col.face_up) and bool(src_col.face_down)
    join_break = False
    if k < len(src_col.face_up):
        left = src_col.face_up[-k - 1]
        head = src_col.face_up[-k]
        join_break = left.suit == head.suit and left.rank == head.rank + 1
    head = run[0]
    dest_top = dst_col.top()
    if dest_top is not None and dest_top.suit == suit and head.suit == suit and dest_top.rank == head.rank + 1:
        return TARGET_JOIN
    if uncovers and src_col.face_down[-1].suit == suit:
        return TARGET_UNCOVER
    if src in hot or any(c.suit == suit for c in run):
        return TARGET_DIRECT
    if src in hot or dst in hot:
        need = None
        if src in hot and src_col.face_up:
            pkt = 1
            while pkt < len(src_col.face_up) and SpiderState.is_movable_run(src_col.face_up[-pkt - 1 :]):
                pkt += 1
            need = src_col.face_up[-pkt].rank + 1
        creates_empty = k == len(src_col.face_up) and not src_col.face_down and not dest_empty
        exposes_need = uncovers and need is not None and src_col.face_down[-1].rank == need
        places_need = need is not None and head.rank == need
        if creates_empty or exposes_need or places_need or dest_empty and head.rank == 13:
            return LANDING_SUPPORT
    if join_break:
        return JOIN_BREAK
    if int(classify_tier(state, action)) == int(Tier.A):
        return GOOD_PLAY
    if dest_empty:
        return PARK
    return OTHER


def allowed_at_race_level(label: str, tier: int, level: int) -> bool:
    if level >= 3:
        return True
    if level <= 0:
        return label in (TARGET_JOIN, TARGET_DIRECT, TARGET_UNCOVER, LANDING_SUPPORT, GOOD_PLAY)
    if level == 1:
        return label in (TARGET_JOIN, TARGET_DIRECT, TARGET_UNCOVER, LANDING_SUPPORT, GOOD_PLAY) or tier <= int(Tier.B)
    if level == 2:
        return label != JOIN_BREAK
    return True


def _priority(label: str, g: int, depth: int, seq: int, node: int, hot_uncover: int, joins: int):
    rank = {
        TARGET_JOIN: 0,
        TARGET_UNCOVER: 1,
        TARGET_DIRECT: 2,
        LANDING_SUPPORT: 3,
        GOOD_PLAY: 4,
        PARK: 5,
        OTHER: 6,
        JOIN_BREAK: 7,
        "DEAL": 9,
    }.get(label, 6)
    return (rank, hot_uncover, -joins, g, depth, seq, node)


@dataclass
class RaceResult:
    unique: int = 0
    expanded: int = 0
    generated: int = 0
    duplicate_skips: int = 0
    elapsed_s: float = 0.0
    peak_rss_mb: Optional[float] = None
    stop_reason: str = ""
    incumbent: Optional[int] = None
    first_s: Optional[float] = None
    first_unique: Optional[int] = None
    first_g: Optional[int] = None
    sd5_expanded: bool = False
    levels_reached: List[int] = field(default_factory=list)
    witnesses: List[dict] = field(default_factory=list)
    used_heuristic_prune: bool = False
    max_depth: int = 0
    classification: str = "BOUNDED_MISS"
    live_frontier: int = 0


def search_foundation(
    sources: Sequence[SpiderState],
    origin_paths: Sequence[Sequence[Action]],
    source_g: Sequence[int],
    *,
    suit: str,
    max_unique: int = 500_000,
    time_limit_s: float = 450.0,
    rss_abort_mb: float = 2 * 1024.0,
    cost_ceiling: int = COST_CEILING,
    harvest_slack: int = 3,
    harvest_limit: int = 128,
    start_foundations: Optional[int] = None,
) -> RaceResult:
    started = time.perf_counter()
    deadline = started + time_limit_s
    result = RaceResult()
    peak = _rss_mb()
    baseline = start_foundations
    if baseline is None and sources:
        baseline = suit_foundation_count(sources[0], suit)
    ceiling = cost_ceiling
    current_incumbent: Optional[int] = None
    witnesses: Dict[bytes, dict] = {}

    def note_rss() -> bool:
        nonlocal peak
        rss = _rss_mb()
        if rss is not None and (peak is None or rss > peak):
            peak = rss
        return rss is not None and rss >= rss_abort_mb

    best_g: Dict[bytes, int] = {}
    parent: List[int] = []
    action_of: List[Optional[Action]] = []
    depth_of: List[int] = []
    origin_of: List[int] = []
    g_of: List[int] = []
    ident_of: List[bytes] = []

    def reconstruct(node: int) -> List[Action]:
        path: List[Action] = []
        while node >= 0 and parent[node] >= 0:
            act = action_of[node]
            if act is not None:
                path.append(act)
            node = parent[node]
        path.reverse()
        return path

    for origin, src in enumerate(sources):
        ident = pack_state(src)
        g0 = int(source_g[origin])
        if ident in best_g:
            if g0 < best_g[ident]:
                best_g[ident] = g0
                idx = ident_of.index(ident)
                g_of[idx] = g0
                origin_of[idx] = origin
            continue
        best_g[ident] = g0
        ident_of.append(ident)
        parent.append(-1)
        action_of.append(None)
        depth_of.append(0)
        origin_of.append(origin)
        g_of.append(g0)
    result.unique = len(best_g)
    print(f"RACE_{suit.upper()} start unique={result.unique} ceiling={ceiling}", flush=True)

    for level in range(0, 4):
        if time.perf_counter() >= deadline:
            result.stop_reason = "time limit"
            break
        if note_rss():
            result.stop_reason = "rss abort"
            break
        result.levels_reached.append(level)
        heap: List[tuple] = []
        seq = 0
        best_node: Dict[bytes, int] = {}
        for i, ident in enumerate(ident_of):
            if best_g.get(ident) == g_of[i]:
                best_node[ident] = i
        for ident, node in best_node.items():
            if g_of[node] > ceiling:
                continue
            st = unpack_state(ident)
            if suit_foundation_count(st, suit) > (baseline or 0):
                continue
            hot = unique_target_columns(st, suit)
            heapq.heappush(heap, _priority(GOOD_PLAY, g_of[node], depth_of[node], seq, node, 0, 0))
            seq += 1
        seen_expand: Dict[bytes, int] = {}
        remaining_s = deadline - time.perf_counter()
        levels_left = 4 - level
        level_deadline = time.perf_counter() + max(20.0, remaining_s / max(1, levels_left))
        print(
            f"RACE_{suit.upper()} L{level} unique={result.unique} heap={len(heap)} "
            f"budget_s={level_deadline - time.perf_counter():.0f} inc={current_incumbent}",
            flush=True,
        )
        while heap:
            now = time.perf_counter()
            if now >= deadline:
                result.stop_reason = "time limit"
                break
            if now >= level_deadline:
                break
            if (result.expanded & 2047) == 0 and note_rss():
                result.stop_reason = "rss abort"
                break
            if (result.expanded & 8191) == 0 and result.expanded:
                print(
                    f"RACE_{suit.upper()} L{level} exp={result.expanded} unique={result.unique} "
                    f"inc={current_incumbent} wit={len(witnesses)} heap={len(heap)}",
                    flush=True,
                )
            *_, node = heapq.heappop(heap)
            ident = ident_of[node]
            g = g_of[node]
            depth = depth_of[node]
            if g != best_g.get(ident):
                continue
            if g > ceiling:
                continue
            if seen_expand.get(ident, 10**9) <= g:
                continue
            seen_expand[ident] = g
            state = unpack_state(ident)
            if suit_foundation_count(state, suit) > (baseline or 0):
                continue
            if stock_rows(state) < 1:
                result.sd5_expanded = True
            hot = unique_target_columns(state, suit)
            actions, _ = engine_tableau_actions(state)
            result.expanded += 1
            for action in actions:
                if action == ("deal",):
                    result.sd5_expanded = True
                    continue
                label = annotate_race_action(state, action, suit, hot)
                tier_i = int(classify_tier(state, action))
                if not allowed_at_race_level(label, tier_i, level):
                    continue
                cost = step_cost(state, action)
                child_g = g + cost
                if child_g > ceiling:
                    continue
                cap = _capture(state, action)
                try:
                    apply_action(state, action)
                    result.generated += 1
                    if stock_rows(state) < 1:
                        result.sd5_expanded = True
                    child_ident = pack_state(state)
                    child_depth = depth + 1
                    result.max_depth = max(result.max_depth, child_depth)
                    prev = best_g.get(child_ident)
                    if prev is not None and child_g >= prev:
                        result.duplicate_skips += 1
                        continue
                    if prev is None:
                        result.unique += 1
                    if result.unique >= max_unique:
                        result.stop_reason = "unique limit"
                        break
                    best_g[child_ident] = child_g
                    child_node = len(ident_of)
                    ident_of.append(child_ident)
                    parent.append(node)
                    action_of.append(action)
                    depth_of.append(child_depth)
                    origin_of.append(origin_of[node])
                    g_of.append(child_g)
                    if suit_foundation_count(state, suit) > (baseline or 0):
                        rec = {
                            "origin": origin_of[node],
                            "g": child_g,
                            "depth": child_depth,
                            "actions": [list(a) if a != ("deal",) else ["deal"] for a in reconstruct(child_node)],
                            "ordered_digest": child_ident.hex(),
                            "fd": face_down_count(state),
                            "foundations": len(state.foundations),
                            "foundation_suits": [run[0].suit for run in state.foundations if run],
                            "empties": list(empty_column_indices(state)),
                            "stock_rows": stock_rows(state),
                            "level": level,
                        }
                        if child_ident not in witnesses or child_g < witnesses[child_ident]["g"]:
                            witnesses[child_ident] = rec
                        if result.first_s is None:
                            result.first_s = time.perf_counter() - started
                            result.first_unique = result.unique
                            result.first_g = child_g
                            print(
                                f"FIRST_{suit.upper()} g={child_g} unique={result.unique} "
                                f"t={result.first_s:.2f}s",
                                flush=True,
                            )
                        if current_incumbent is None or child_g < current_incumbent:
                            current_incumbent = child_g
                            result.incumbent = child_g
                            ceiling = min(cost_ceiling, current_incumbent + harvest_slack)
                        continue
                    child_hot = unique_target_columns(state, suit)
                    joins = sum(1 for c in same_suit_len(state, suit))
                    heapq.heappush(
                        heap,
                        _priority(label, child_g, child_depth, seq, child_node, 9 - len(child_hot), joins),
                    )
                    seq += 1
                finally:
                    _restore(state, cap)
            if result.stop_reason in ("unique limit", "time limit", "rss abort"):
                break
        result.live_frontier = len(heap)
        if result.stop_reason in ("unique limit", "time limit", "rss abort"):
            break
        if current_incumbent is not None and len(witnesses) >= 16 and (deadline - time.perf_counter()) < 15:
            result.stop_reason = result.stop_reason or "harvested"
            break

    if not result.stop_reason:
        result.stop_reason = "frontier empty" if result.live_frontier == 0 else "max level"
    c = current_incumbent
    kept = []
    if c is not None:
        for rec in witnesses.values():
            if rec["g"] <= c + harvest_slack:
                kept.append(rec)
        kept.sort(key=lambda w: (w["g"], w["depth"], w["origin"]))
        kept = kept[:harvest_limit]
    result.witnesses = kept
    result.elapsed_s = time.perf_counter() - started
    result.peak_rss_mb = peak
    if kept:
        result.classification = "FOUNDATION_REACHED"
    elif result.stop_reason in ("unique limit", "rss abort") or (
        result.stop_reason == "time limit" and result.unique > 50_000
    ):
        result.classification = "STATE_EXPLOSION"
    elif result.stop_reason == "frontier empty" and not kept:
        # Cost ceiling still applies: this is exhaustion of the MW<=ceiling
        # tableau component, not a proof that no foundation exists at any cost.
        result.classification = "BOUNDED_MISS"
    else:
        result.classification = "BOUNDED_MISS"
    return result


def same_suit_len(state: SpiderState, suit: str) -> List[int]:
    from spider.simple_current_horizon import same_suit_components

    return [c["length"] for c in same_suit_components(state, suit)]
