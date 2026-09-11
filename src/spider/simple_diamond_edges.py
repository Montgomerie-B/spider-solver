"""Research-only Diamond unique-core edge ratchet.

Mandatory pre-SD5 adjacency edges around unique 2D and 5D.
Tableau only. SD5 never expanded. Full accumulated MW is g.
"""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from spider.engine import SpiderState
from spider.metrics import Action
from spider.packed_state import pack_state, unpack_state
from spider.simple_current_horizon import occurrence_counts
from spider.simple_deal1_preview import stock_rows
from spider.simple_foundation_horizon import pretty_card
from spider.simple_foundation_race import (
    GOOD_PLAY,
    JOIN_BREAK,
    LANDING_SUPPORT,
    OTHER,
    PARK,
    TARGET_DIRECT,
    TARGET_JOIN,
    TARGET_UNCOVER,
    allowed_at_race_level,
    suit_foundation_count,
)
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

# below_rank -> top_rank in face_up (bottom-to-top): lower card has higher rank.
EDGES = {
    "A": (3, 2),  # 3D immediately below unique 2D
    "B": (2, 1),  # unique 2D immediately below AD
    "C": (6, 5),  # 6D immediately below unique 5D
    "D": (5, 4),  # unique 5D immediately below 4D
}
COST_CEILING = 90


def diamond_adjacent_pairs(state: SpiderState) -> Set[Tuple[int, int]]:
    """Engine orientation: face_up[i] is below face_up[i+1] (top). Descending ranks toward the top."""

    pairs: Set[Tuple[int, int]] = set()
    for column in state.columns:
        up = column.face_up
        for i in range(len(up) - 1):
            below, top = up[i], up[i + 1]
            if below.suit == "d" and top.suit == "d" and below.rank == top.rank + 1:
                pairs.add((below.rank, top.rank))
    return pairs


def satisfied_core_edges(state: SpiderState, *, baseline_d: int = 0) -> Set[str]:
    if suit_foundation_count(state, "d") > baseline_d:
        return set(EDGES)
    pairs = diamond_adjacent_pairs(state)
    return {name for name, pair in EDGES.items() if pair in pairs}


def edge_present(state: SpiderState, name: str, *, baseline_d: int = 0) -> bool:
    return name in satisfied_core_edges(state, baseline_d=baseline_d)


def diamond_components(state: SpiderState) -> List[dict]:
    out = []
    for col_i, column in enumerate(state.columns):
        up = column.face_up
        i = 0
        while i < len(up):
            if up[i].suit != "d":
                i += 1
                continue
            j = i + 1
            while j < len(up) and up[j].suit == "d" and up[j - 1].rank == up[j].rank + 1:
                j += 1
            run = up[i:j]
            if len(run) >= 2:
                movable = SpiderState.is_movable_run(column.face_up[-(len(up) - i) :]) if j == len(up) else False
                dests = 0
                if j == len(up):
                    k = len(up) - i
                    for action in engine_tableau_actions(state)[0]:
                        if action[0] == col_i and action[2] == k:
                            dests += 1
                out.append(
                    {
                        "column_1": col_i + 1,
                        "ranks": [pretty_card(c) for c in run],
                        "length": len(run),
                        "exposed": j == len(up),
                        "movable": dests > 0,
                    }
                )
            i = j
    return out


def edge_audit(state: SpiderState, name: str) -> dict:
    below, top = EDGES[name]
    sat = edge_present(state, name)
    below_occ = occurrence_counts(state, "d", below)
    top_occ = occurrence_counts(state, "d", top)
    legal_join = False
    if not sat:
        for t in top_occ["tableau"]:
            if not t.get("top"):
                continue
            tcol = t["column_0"]
            for b in below_occ["tableau"]:
                if not b.get("top"):
                    continue
                bcol = b["column_0"]
                if tcol != bcol and state.can_move(tcol, bcol, 1):
                    legal_join = True
    return {
        "name": name,
        "pair": f"{pretty_rank(below)}D->{pretty_rank(top)}D",
        "satisfied": sat,
        "below_count": below_occ["current_count"],
        "top_count": top_occ["current_count"],
        "below_exposed_top": sum(1 for o in below_occ["tableau"] if o.get("top")),
        "top_exposed_top": sum(1 for o in top_occ["tableau"] if o.get("top")),
        "legal_join_now": legal_join,
    }


def pretty_rank(rank: int) -> str:
    from spider.cards import rank_str

    return rank_str(rank)


def hot_columns_for_edge(state: SpiderState, name: str) -> Set[int]:
    below, top = EDGES[name]
    cols: Set[int] = set()
    for rank in (below, top):
        for occ in occurrence_counts(state, "d", rank)["tableau"]:
            cols.add(occ["column_0"])
    return cols


def annotate_edge_action(state: SpiderState, action, name: str, hot: Set[int]) -> str:
    if action == ("deal",):
        return "DEAL"
    src, dst, k = action
    src_col = state.columns[src]
    dst_col = state.columns[dst]
    run = src_col.face_up[-k:]
    head = run[0]
    dest_top = dst_col.top()
    below, top = EDGES[name]
    dest_empty = dst_col.is_empty()
    uncovers = k == len(src_col.face_up) and bool(src_col.face_down)
    join_break = False
    if k < len(src_col.face_up):
        left = src_col.face_up[-k - 1]
        h = src_col.face_up[-k]
        join_break = left.suit == h.suit and left.rank == h.rank + 1
    if (
        dest_top is not None
        and dest_top.suit == "d"
        and head.suit == "d"
        and dest_top.rank == below
        and head.rank == top
    ):
        return TARGET_JOIN
    if dest_top is not None and dest_top.suit == "d" and head.suit == "d" and dest_top.rank == head.rank + 1:
        return TARGET_JOIN
    if uncovers and src_col.face_down[-1].suit == "d":
        return TARGET_UNCOVER
    if src in hot or any(c.suit == "d" and c.rank in (below, top) for c in run):
        return TARGET_DIRECT
    if join_break:
        return JOIN_BREAK
    if int(classify_tier(state, action)) == int(Tier.A):
        return GOOD_PLAY
    if dest_empty:
        return PARK
    return OTHER


@dataclass
class EdgeResult:
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
    foundation_surprise: bool = False
    already_at_source: int = 0


def search_edge(
    sources: Sequence[SpiderState],
    origin_paths: Sequence[Sequence[Action]],
    source_g: Sequence[int],
    *,
    name: str,
    max_unique: int = 200_000,
    time_limit_s: float = 150.0,
    rss_abort_mb: float = 1.5 * 1024.0,
    cost_ceiling: int = COST_CEILING,
    harvest_slack: int = 2,
    harvest_limit: int = 128,
) -> EdgeResult:
    started = time.perf_counter()
    deadline = started + time_limit_s
    result = EdgeResult()
    peak = _rss_mb()
    baseline_d = suit_foundation_count(sources[0], "d") if sources else 0
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
        if edge_present(src, name, baseline_d=baseline_d):
            result.already_at_source += 1
            witnesses[ident] = {
                "origin": origin,
                "g": g0,
                "depth": 0,
                "actions": [],
                "ordered_digest": ident.hex(),
                "already": True,
                "foundation": suit_foundation_count(src, "d") > baseline_d,
                "edges": sorted(satisfied_core_edges(src, baseline_d=baseline_d)),
            }
            if current_incumbent is None or g0 < current_incumbent:
                current_incumbent = g0
                result.incumbent = g0
                result.first_s = 0.0
                result.first_unique = 1
                result.first_g = g0
    result.unique = len(best_g)
    print(
        f"EDGE_{name} start unique={result.unique} already={result.already_at_source} ceiling={ceiling}",
        flush=True,
    )

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
            if edge_present(st, name, baseline_d=baseline_d) and depth_of[node] > 0:
                continue
            heapq.heappush(heap, (g_of[node], depth_of[node], seq, node))
            seq += 1
        seen_expand: Dict[bytes, int] = {}
        remaining_s = deadline - time.perf_counter()
        levels_left = 4 - level
        level_deadline = time.perf_counter() + max(15.0, remaining_s / max(1, levels_left))
        print(
            f"EDGE_{name} L{level} unique={result.unique} heap={len(heap)} "
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
                    f"EDGE_{name} L{level} exp={result.expanded} unique={result.unique} "
                    f"inc={current_incumbent} wit={len(witnesses)} heap={len(heap)}",
                    flush=True,
                )
            _g, _d, _s, node = heapq.heappop(heap)
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
            parent_edges = satisfied_core_edges(state, baseline_d=baseline_d)
            if name in parent_edges and depth > 0:
                continue
            if stock_rows(state) < 1:
                result.sd5_expanded = True
            hot = hot_columns_for_edge(state, name)
            actions, _ = engine_tableau_actions(state)
            result.expanded += 1
            for action in actions:
                if action == ("deal",):
                    result.sd5_expanded = True
                    continue
                label = annotate_edge_action(state, action, name, hot)
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
                    child_edges = satisfied_core_edges(state, baseline_d=baseline_d)
                    foundation = suit_foundation_count(state, "d") > baseline_d
                    hit = name in child_edges and name not in parent_edges or foundation
                    if hit:
                        rec = {
                            "origin": origin_of[node],
                            "g": child_g,
                            "depth": child_depth,
                            "actions": [list(a) if a != ("deal",) else ["deal"] for a in reconstruct(child_node)],
                            "ordered_digest": child_ident.hex(),
                            "already": False,
                            "foundation": foundation,
                            "edges": sorted(child_edges),
                            "preserved": sorted(parent_edges & child_edges),
                            "broken": sorted(parent_edges - child_edges),
                            "created": sorted(child_edges - parent_edges),
                            "level": level,
                            "fd": face_down_count(state),
                            "empties": list(empty_column_indices(state)),
                            "stock_rows": stock_rows(state),
                        }
                        if child_ident not in witnesses or child_g < witnesses[child_ident]["g"]:
                            witnesses[child_ident] = rec
                        if foundation:
                            result.foundation_surprise = True
                        if result.first_s is None:
                            result.first_s = time.perf_counter() - started
                            result.first_unique = result.unique
                            result.first_g = child_g
                            print(
                                f"FIRST_EDGE_{name} g={child_g} unique={result.unique} "
                                f"t={result.first_s:.2f}s found={foundation}",
                                flush=True,
                            )
                        if current_incumbent is None or child_g < current_incumbent:
                            current_incumbent = child_g
                            result.incumbent = child_g
                            ceiling = min(cost_ceiling, current_incumbent + harvest_slack)
                        continue
                    heapq.heappush(heap, (child_g, child_depth, seq, child_node))
                    seq += 1
                finally:
                    _restore(state, cap)
            if result.stop_reason in ("unique limit", "time limit", "rss abort"):
                break
        if result.stop_reason in ("unique limit", "time limit", "rss abort"):
            break
        if current_incumbent is not None and len(witnesses) >= 16 and (deadline - time.perf_counter()) < 10:
            result.stop_reason = result.stop_reason or "harvested"
            break

    if not result.stop_reason:
        result.stop_reason = "complete"
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
    return result


def preview_other_edges(
    state: SpiderState,
    g0: int,
    have: Set[str],
    *,
    max_depth: int = 4,
    deadline: float,
    rss_abort_mb: float,
    baseline_d: int = 0,
) -> dict:
    want = set(EDGES) - have
    if not want:
        return {"status": "SECOND_EDGE_WITHIN_4", "new_edges": [], "unique": 1, "found": False}
    ident0 = pack_state(state)
    best = {ident0: g0}
    heap = [(g0, 0, 0, ident0)]
    seq = 0
    seen: Dict[bytes, int] = {}
    unique = 1
    live = False
    found = None
    while heap:
        if time.perf_counter() >= deadline:
            live = True
            break
        rss = _rss_mb()
        if rss is not None and rss >= rss_abort_mb:
            live = True
            break
        g, depth, _, ident = heapq.heappop(heap)
        if g != best.get(ident):
            continue
        if seen.get(ident, 10**9) <= g:
            continue
        if depth >= max_depth:
            live = True
            continue
        seen[ident] = g
        st = unpack_state(ident)
        actions, _ = engine_tableau_actions(st)
        for action in actions:
            cost = step_cost(st, action)
            cap = _capture(st, action)
            try:
                apply_action(st, action)
                child_ident = pack_state(st)
                child_g = g + cost
                prev = best.get(child_ident)
                if prev is not None and child_g >= prev:
                    continue
                best[child_ident] = child_g
                if prev is None:
                    unique += 1
                child_edges = satisfied_core_edges(st, baseline_d=baseline_d)
                new = sorted(child_edges - have)
                if suit_foundation_count(st, "d") > baseline_d:
                    found = {"g": child_g, "depth": depth + 1, "new_edges": sorted(set(EDGES) - have), "foundation": True}
                    break
                if any(e in want for e in new):
                    found = {"g": child_g, "depth": depth + 1, "new_edges": [e for e in new if e in want], "foundation": False}
                    break
                seq += 1
                heapq.heappush(heap, (child_g, depth + 1, seq, child_ident))
            finally:
                _restore(st, cap)
        if found:
            break
    if found:
        status = "SECOND_EDGE_WITHIN_4"
        dead = False
        live_flag = False
    elif live or heap:
        status = "LIVE_BEYOND_4"
        dead = False
        live_flag = True
    else:
        status = "EXACT_DEAD_TO_OTHER_CORE_EDGE"
        dead = True
        live_flag = False
    return {
        "status": status,
        "found": bool(found),
        "dead": dead,
        "live": live_flag,
        "hit": found,
        "unique": unique,
        "new_edges": None if not found else found.get("new_edges"),
        "foundation": bool(found and found.get("foundation")),
    }
