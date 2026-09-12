"""Research-only v0.42 Diamond 6D exposure gateway.

Two physical current 6D copies are tracked separately (G6_8, G6_9).
Canonical identity remains ordered pack_state; physical location is
search bookkeeping only.  Tableau only.  SD5 never expanded.
Full accumulated MW is g.
"""

from __future__ import annotations

import heapq
import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import Action, replay_actions
from spider.packed_state import pack_state, unpack_state
from spider.simple_current_horizon import occurrence_counts
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import (
    AB_QUALITY,
    D_JOIN,
    LOWER_TAIL_RANKS,
    as_actions,
    category_from_edges,
    dump_actions,
    heart_telemetry,
    lower_tail_present,
    opening_state,
    source_invariants,
    unique_five_d,
)
from spider.simple_diamond_edges import diamond_adjacent_pairs, satisfied_core_edges
from spider.simple_foundation_horizon import pretty_card
from spider.simple_foundation_race import (
    GOOD_PLAY,
    JOIN_BREAK,
    OTHER,
    PARK,
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

ROOT = Path(__file__).resolve().parents[2]
DEAL_PATH = ROOT / "deals" / "4925153.txt"
V041_SOURCES = ROOT / "docs" / "research" / "diamond_multi_edge_sources_v0_41.json"
COST_CEILING = 100
HARVEST_SLACK = 3
HARVEST_LIMIT = 192
MAX_UNIQUE = 175_000
TIME_LIMIT_S = 225.0
GLOBAL_TIME_S = 450.0
RSS_PER_MB = 2 * 1024.0
RSS_TOTAL_MB = 3 * 1024.0
PREVIEW_DEPTH = 6
EXPECTED_N = 208
EXPECTED_CATEGORIES = {"B+D": 128, "A+B": 32, "A+B+D": 40, "A+D": 8}
LOWER_TAIL_HEAD = ("5D", "4D", "3D", "2D", "AD")

G6_CLEAR = "G6_CLEAR"
G6_LANDING = "G6_LANDING"
LABEL_RANK = {
    G6_CLEAR: 0,
    G6_LANDING: 1,
    D_JOIN: 2,
    GOOD_PLAY: 3,
    AB_QUALITY: 4,
    PARK: 5,
    OTHER: 6,
    JOIN_BREAK: 7,
    "DEAL": 8,
}
L0_LABELS = {G6_CLEAR, G6_LANDING, D_JOIN, GOOD_PLAY}
L1_LABELS = L0_LABELS | {AB_QUALITY, PARK}


def card_loc(col: int, zone: str, idx: int) -> Tuple[int, str, int]:
    return (int(col), str(zone), int(idx))


def loc_column(loc: Tuple[int, str, int]) -> int:
    return loc[0]


def loc_is_top(state: SpiderState, loc: Tuple[int, str, int]) -> bool:
    col, zone, idx = loc
    if zone != "up":
        return False
    up = state.columns[col].face_up
    return bool(up) and idx == len(up) - 1 and up[idx].suit == "d" and up[idx].rank == 6


def loc_card(state: SpiderState, loc: Tuple[int, str, int]):
    col, zone, idx = loc
    column = state.columns[col]
    seq = column.face_up if zone == "up" else column.face_down
    if 0 <= idx < len(seq):
        return seq[idx]
    return None


def cards_above(state: SpiderState, loc: Tuple[int, str, int]) -> int:
    col, zone, idx = loc
    column = state.columns[col]
    if zone == "down":
        return (len(column.face_down) - 1 - idx) + len(column.face_up)
    return max(0, len(column.face_up) - 1 - idx)


def find_six_d_locs(state: SpiderState) -> List[Tuple[int, str, int]]:
    out = []
    for col_i, column in enumerate(state.columns):
        for i, card in enumerate(column.face_down):
            if card.suit == "d" and card.rank == 6:
                out.append(card_loc(col_i, "down", i))
        for i, card in enumerate(column.face_up):
            if card.suit == "d" and card.rank == 6:
                out.append(card_loc(col_i, "up", i))
    return out


def identify_source_g6(state: SpiderState) -> dict:
    """Bind G6_8 / G6_9 to the physical 6D copies currently in columns 8 and 9."""

    found = {}
    for name, col_1 in (("G6_8", 8), ("G6_9", 9)):
        col_i = col_1 - 1
        column = state.columns[col_i]
        hit = None
        for i, card in enumerate(column.face_up):
            if card.suit == "d" and card.rank == 6:
                hit = card_loc(col_i, "up", i)
                break
        if hit is None:
            for i, card in enumerate(column.face_down):
                if card.suit == "d" and card.rank == 6:
                    hit = card_loc(col_i, "down", i)
                    break
        found[name] = hit
    return found


def follow_loc(state: SpiderState, loc: Tuple[int, str, int], action: Action) -> Optional[Tuple[int, str, int]]:
    """Update a physical-card location through one engine action.  None if founded."""

    if action == ("deal",):
        col, zone, idx = loc
        if zone == "up":
            return loc
        return loc
    src, dst, k = action
    col, zone, idx = loc
    src_col = state.columns[src]
    dst_col = state.columns[dst]
    n_src_up = len(src_col.face_up)
    n_dst_up = len(dst_col.face_up)
    n_src_down = len(src_col.face_down)
    run_start = n_src_up - k
    new = loc
    if zone == "up" and col == src:
        if idx >= run_start:
            new = card_loc(dst, "up", n_dst_up + (idx - run_start))
        else:
            new = loc
    elif zone == "down" and col == src:
        new = loc
    elif col == dst:
        new = loc
    will_flip = k == n_src_up and n_src_down > 0
    if will_flip and new[0] == src and new[1] == "down" and new[2] == n_src_down - 1:
        new = card_loc(src, "up", 0)
    if new[0] == dst and new[1] == "up":
        hypo = list(dst_col.face_up) + list(src_col.face_up[-k:])
        if len(hypo) >= 13 and hypo[-13].rank == 13 and SpiderState.is_movable_run(hypo[-13:]):
            if new[2] >= len(hypo) - 13:
                return None
    return new


def exposed_6d_can_receive_rank5(state: SpiderState, loc: Tuple[int, str, int]) -> bool:
    if not loc_is_top(state, loc):
        return False
    top = state.columns[loc[0]].top()
    return top is not None and top.rank == 6


def g6_any(state: SpiderState) -> bool:
    return any(loc_is_top(state, loc) for loc in find_six_d_locs(state))


def future_c_requires_exposed_6d() -> str:
    return (
        "Engine can_move requires dest.top.rank == head.rank + 1.  A 5D-headed "
        "packet can land only on an exposed/top 6.  Every later 6D-5D join "
        "therefore crosses G6_ANY."
    )


def top_movable_k(state: SpiderState, col: int) -> int:
    up = state.columns[col].face_up
    if not up:
        return 0
    k = 1
    while k < len(up) and SpiderState.is_movable_run(up[-k - 1 :]):
        k += 1
    return k


def covering_packet(state: SpiderState, loc: Tuple[int, str, int]) -> dict:
    col = loc[0]
    column = state.columns[col]
    above_n = cards_above(state, loc)
    k = top_movable_k(state, col)
    packet = [pretty_card(c) for c in column.face_up[-k:]] if k else []
    dests = []
    if k:
        for action in engine_tableau_actions(state)[0]:
            if action[0] == col and action[2] == k:
                dests.append(action[1] + 1)
    need = None
    if packet and not dests:
        need = column.face_up[-k].rank + 1
    return {
        "k": k,
        "cards": packet,
        "legal_dest_columns_1": dests,
        "movable": bool(dests),
        "need_rank": need,
        "cards_above": above_n,
        "empties": list(empty_column_indices(state)),
    }


def diamond_component_at(state: SpiderState, loc: Tuple[int, str, int]) -> List[str]:
    if loc[1] != "up":
        return [pretty_card(loc_card(state, loc))] if loc_card(state, loc) else []
    up = state.columns[loc[0]].face_up
    i = loc[2]
    lo = i
    while lo > 0 and up[lo - 1].suit == "d" and up[lo - 1].rank == up[lo].rank + 1:
        lo -= 1
    hi = i + 1
    while hi < len(up) and up[hi].suit == "d" and up[hi - 1].rank == up[hi].rank + 1:
        hi += 1
    return [pretty_card(c) for c in up[lo:hi]]


def blocker_audit(state: SpiderState, loc: Tuple[int, str, int], *, name: str) -> dict:
    col = loc[0]
    column = state.columns[col]
    above = []
    if loc[1] == "up":
        above = [pretty_card(c) for c in column.face_up[loc[2] + 1 :]]
    else:
        above = [pretty_card(c) for c in column.face_down[loc[2] + 1 :]] + [pretty_card(c) for c in column.face_up]
    cover = covering_packet(state, loc)
    joins_in_cover = 0
    seq = column.face_up[loc[2] + 1 :] if loc[1] == "up" else column.face_up
    for i in range(len(seq) - 1):
        if seq[i].suit == seq[i + 1].suit and seq[i].rank == seq[i + 1].rank + 1:
            joins_in_cover += 1
    five = unique_five_d(state)
    edges = sorted(satisfied_core_edges(state))
    would_break = []
    if cover["k"] and loc[1] == "up":
        # moving the top packet off this column may break D if 5D-4D is the top packet here
        head = column.face_up[-cover["k"]]
        if "D" in edges and head.suit == "d" and head.rank == 5:
            would_break.append("D")
        if "B" in edges and head.suit == "d" and head.rank == 2:
            would_break.append("B")
        if "A" in edges and head.suit == "d" and head.rank == 3:
            would_break.append("A")
    return {
        "name": name,
        "column_1": col + 1,
        "zone": loc[1],
        "up_index": loc[2] if loc[1] == "up" else None,
        "top": loc_is_top(state, loc),
        "face_up": loc[1] == "up",
        "cards_above": cards_above(state, loc),
        "face_up_above": above if loc[1] == "up" else [],
        "face_down_involved": loc[1] == "down" or bool(column.face_down),
        "face_down_count": len(column.face_down),
        "component": diamond_component_at(state, loc),
        "has_7d_6d": diamond_component_at(state, loc)[:2] == ["7D", "6D"],
        "covering_packet": cover,
        "same_suit_joins_in_cover": joins_in_cover,
        "would_break_edges": would_break,
        "five_d_accessible": bool(five.get("can_move_now") or five.get("top") or five.get("exposed")),
        "legal_receive_rank5": exposed_6d_can_receive_rank5(state, loc),
        "edges": edges,
    }


def allowed_at_g6_level(label: str, tier: int, level: int) -> bool:
    """Widening only.  G6_ANY is not a local prune of unrelated legal moves."""

    if level >= 3:
        return True
    if level <= 0:
        return label in L0_LABELS
    if level == 1:
        return label in L1_LABELS
    if level == 2:
        return label != JOIN_BREAK
    return True


def annotate_g6_action(state: SpiderState, action, loc: Tuple[int, str, int]) -> str:
    if action == ("deal",):
        return "DEAL"
    src, dst, k = action
    src_col = state.columns[src]
    dst_col = state.columns[dst]
    run = src_col.face_up[-k:]
    head = run[0]
    dest_top = dst_col.top()
    dest_empty = dst_col.is_empty()
    uncovers = k == len(src_col.face_up) and bool(src_col.face_down)
    join_break = False
    if k < len(src_col.face_up):
        left = src_col.face_up[-k - 1]
        h = src_col.face_up[-k]
        join_break = left.suit == h.suit and left.rank == h.rank + 1
    target_col = loc[0]
    cover = covering_packet(state, loc)
    above = cards_above(state, loc)
    if src == target_col and above > 0:
        if k == cover["k"] or (loc[1] == "up" and k == above):
            return G6_CLEAR
        if k <= above:
            return G6_CLEAR
    if cover["need_rank"] is not None:
        need = cover["need_rank"]
        places_need = dest_top is None and False
        if dest_empty and head.rank == 13:
            return G6_LANDING
        if dest_top is not None and dest_top.rank == need:
            return G6_LANDING
        if uncovers and src_col.face_down[-1].rank == need:
            return G6_LANDING
        creates_empty = k == len(src_col.face_up) and not src_col.face_down and not dest_empty
        if creates_empty:
            return G6_LANDING
        if dest_top is not None and head.rank == need:
            return G6_LANDING
    if dest_top is not None and dest_top.suit == "d" and head.suit == "d" and dest_top.rank == head.rank + 1:
        return D_JOIN
    if any(c.suit == "d" and c.rank in (3, 2, 1) for c in run) or (
        dest_top is not None and dest_top.suit == "d" and dest_top.rank in (3, 2)
    ):
        return AB_QUALITY
    if join_break:
        return JOIN_BREAK
    if int(classify_tier(state, action)) == int(Tier.A):
        return GOOD_PLAY
    if dest_empty:
        return PARK
    return OTHER


def five_headed_ranks(state: SpiderState) -> List[str]:
    five = unique_five_d(state)
    return list(five.get("headed_packet") or [])


def lower_tail_packet_movable_onto(state: SpiderState, dest_loc: Tuple[int, str, int]) -> bool:
    if not loc_is_top(state, dest_loc):
        return False
    five = unique_five_d(state)
    if tuple(five.get("headed_packet") or []) != LOWER_TAIL_HEAD:
        return False
    k = five.get("headed_k")
    src = None
    for col_i, column in enumerate(state.columns):
        for i, card in enumerate(column.face_up):
            if card.suit == "d" and card.rank == 5:
                src = col_i
                break
        if src is not None:
            break
    if src is None or k is None or src == dest_loc[0]:
        return False
    return state.can_move(src, dest_loc[0], int(k))


def c_join_immediate(state: SpiderState, dest_loc: Tuple[int, str, int]) -> bool:
    if not loc_is_top(state, dest_loc):
        return False
    five = unique_five_d(state)
    k = five.get("headed_k")
    if not k:
        return False
    src = None
    for col_i, column in enumerate(state.columns):
        for card in column.face_up:
            if card.suit == "d" and card.rank == 5:
                src = col_i
                break
        if src is not None:
            break
    if src is None or src == dest_loc[0]:
        return False
    return state.can_move(src, dest_loc[0], int(k))


def load_v041_sources(opening: Optional[SpiderState] = None) -> dict:
    opening = opening or opening_state()
    payload = json.loads(V041_SOURCES.read_text(encoding="utf-8"))
    seen: Dict[bytes, dict] = {}
    replay_failures = 0
    rows = []
    for rec in payload.get("states") or []:
        full = as_actions(rec.get("full_actions") or [])
        end = opening.clone()
        try:
            cost = replay_actions(end, full)
        except Exception:
            replay_failures += 1
            continue
        ident = pack_state(end)
        inv = source_invariants(end)
        sixes = find_six_d_locs(end)
        ok = (
            cost == rec.get("full_cost")
            and ident.hex() == rec.get("ordered_digest")
            and inv["ok"]
            and len(sixes) == 2
            and all(loc[1] == "up" for loc in sixes)
        )
        if not ok:
            replay_failures += 1
            continue
        ids = identify_source_g6(end)
        if ids.get("G6_8") is None or ids.get("G6_9") is None:
            replay_failures += 1
            continue
        edges = sorted(satisfied_core_edges(end))
        item = {
            "ordered_digest": ident.hex(),
            "full_cost": cost,
            "full_actions": dump_actions(full),
            "category": category_from_edges(edges),
            "edges_now": edges,
            "replay_ok": True,
            "invariants": inv,
            "g6": ids,
            "lower_tail_head": five_headed_ranks(end) == list(LOWER_TAIL_HEAD),
            "heart": heart_telemetry(end),
        }
        prev = seen.get(ident)
        if prev is None or cost < prev["full_cost"]:
            seen[ident] = item
    kept = sorted(seen.values(), key=lambda r: (r["full_cost"], r["ordered_digest"]))
    cats = Counter(r["category"] for r in kept)
    return {
        "n": len(kept),
        "expected_n": EXPECTED_N,
        "replay_failures": replay_failures,
        "all_replay_ok": replay_failures == 0 and len(kept) == EXPECTED_N,
        "categories": dict(cats),
        "states": kept,
    }


@dataclass
class ExposureResult:
    target: str = ""
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
    first_origin: Optional[int] = None
    first_category: Optional[str] = None
    sd5_expanded: bool = False
    levels_reached: List[int] = field(default_factory=list)
    witnesses: List[dict] = field(default_factory=list)
    used_heuristic_prune: bool = False
    foundation_surprise: bool = False
    already_at_source: int = 0


def search_exposure(
    sources: Sequence[SpiderState],
    origin_paths: Sequence[Sequence[Action]],
    source_g: Sequence[int],
    source_categories: Sequence[str],
    source_locs: Sequence[Tuple[int, str, int]],
    *,
    target: str,
    max_unique: int = MAX_UNIQUE,
    time_limit_s: float = TIME_LIMIT_S,
    rss_abort_mb: float = RSS_PER_MB,
    cost_ceiling: int = COST_CEILING,
    harvest_slack: int = HARVEST_SLACK,
    harvest_limit: int = HARVEST_LIMIT,
) -> ExposureResult:
    started = time.perf_counter()
    deadline = started + time_limit_s
    result = ExposureResult(target=target)
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
    loc_of: List[Tuple[int, str, int]] = []

    def reconstruct(node: int) -> List[Action]:
        path: List[Action] = []
        while node >= 0 and parent[node] >= 0:
            act = action_of[node]
            if act is not None:
                path.append(act)
            node = parent[node]
        path.reverse()
        return path

    order = sorted(range(len(sources)), key=lambda i: (int(source_g[i]), pack_state(sources[i])))
    for origin in order:
        src = sources[origin]
        ident = pack_state(src)
        g0 = int(source_g[origin])
        loc0 = source_locs[origin]
        if ident in best_g:
            if g0 < best_g[ident]:
                best_g[ident] = g0
                idx = ident_of.index(ident)
                g_of[idx] = g0
                origin_of[idx] = origin
                loc_of[idx] = loc0
            continue
        best_g[ident] = g0
        ident_of.append(ident)
        parent.append(-1)
        action_of.append(None)
        depth_of.append(0)
        origin_of.append(origin)
        g_of.append(g0)
        loc_of.append(loc0)
        if loc_is_top(src, loc0):
            result.already_at_source += 1
            witnesses[ident] = {
                "origin": origin,
                "g": g0,
                "depth": 0,
                "actions": [],
                "ordered_digest": ident.hex(),
                "already": True,
                "foundation": False,
                "loc": list(loc0),
                "source_category": source_categories[origin],
                "edges": sorted(satisfied_core_edges(src, baseline_d=baseline_d)),
                "target": target,
            }
            if current_incumbent is None or g0 < current_incumbent:
                current_incumbent = g0
                result.incumbent = g0
                result.first_s = 0.0
                result.first_unique = 1
                result.first_g = g0
                result.first_origin = origin
                result.first_category = source_categories[origin]
    result.unique = len(best_g)
    print(
        f"{target} start unique={result.unique} already={result.already_at_source} ceiling={ceiling}",
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
            if loc_is_top(st, loc_of[node]) and depth_of[node] > 0:
                continue
            above = cards_above(st, loc_of[node])
            heapq.heappush(heap, (above, g_of[node], depth_of[node], seq, node))
            seq += 1
        seen_expand: Dict[bytes, int] = {}
        remaining_s = deadline - time.perf_counter()
        levels_left = 4 - level
        level_deadline = time.perf_counter() + max(15.0, remaining_s / max(1, levels_left))
        print(
            f"{target} L{level} unique={result.unique} heap={len(heap)} "
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
                    f"{target} L{level} exp={result.expanded} unique={result.unique} "
                    f"inc={current_incumbent} wit={len(witnesses)} heap={len(heap)}",
                    flush=True,
                )
            _ab, _g, _d, _s, node = heapq.heappop(heap)
            ident = ident_of[node]
            g = g_of[node]
            depth = depth_of[node]
            loc = loc_of[node]
            if g != best_g.get(ident):
                continue
            if g > ceiling:
                continue
            if seen_expand.get(ident, 10**9) <= g:
                continue
            seen_expand[ident] = g
            state = unpack_state(ident)
            if loc_is_top(state, loc) and depth > 0:
                continue
            if stock_rows(state) < 1:
                result.sd5_expanded = True
            actions, _ = engine_tableau_actions(state)
            ranked = []
            for action in actions:
                if action == ("deal",):
                    result.sd5_expanded = True
                    continue
                label = annotate_g6_action(state, action, loc)
                tier_i = int(classify_tier(state, action))
                if not allowed_at_g6_level(label, tier_i, level):
                    continue
                ranked.append((LABEL_RANK.get(label, 9), action, label))
            ranked.sort(key=lambda t: (t[0], t[1]))
            result.expanded += 1
            parent_edges = satisfied_core_edges(state, baseline_d=baseline_d)
            for _rk, action, label in ranked:
                cost = step_cost(state, action)
                child_g = g + cost
                if child_g > ceiling:
                    continue
                child_loc = follow_loc(state, loc, action)
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
                    if child_loc is None:
                        result.foundation_surprise = True
                        if prev is None:
                            result.unique += 1
                        best_g[child_ident] = child_g
                        rec = {
                            "origin": origin_of[node],
                            "g": child_g,
                            "depth": child_depth,
                            "actions": dump_actions(reconstruct(node) + [action]),
                            "ordered_digest": child_ident.hex(),
                            "already": False,
                            "foundation": True,
                            "loc": None,
                            "source_category": source_categories[origin_of[node]],
                            "edges": sorted(satisfied_core_edges(state, baseline_d=baseline_d)),
                            "target": target,
                            "label": label,
                            "level": level,
                        }
                        witnesses[child_ident] = rec
                        continue
                    card = loc_card(state, child_loc)
                    if card is None or card.suit != "d" or card.rank != 6:
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
                    loc_of.append(child_loc)
                    foundation = suit_foundation_count(state, "d") > baseline_d
                    if foundation:
                        result.foundation_surprise = True
                    hit = loc_is_top(state, child_loc)
                    if hit:
                        rec = {
                            "origin": origin_of[node],
                            "g": child_g,
                            "depth": child_depth,
                            "actions": dump_actions(reconstruct(child_node)),
                            "ordered_digest": child_ident.hex(),
                            "already": False,
                            "foundation": foundation,
                            "loc": list(child_loc),
                            "column_1": child_loc[0] + 1,
                            "legal_receive_rank5": exposed_6d_can_receive_rank5(state, child_loc),
                            "source_category": source_categories[origin_of[node]],
                            "edges": sorted(satisfied_core_edges(state, baseline_d=baseline_d)),
                            "preserved": sorted(parent_edges & satisfied_core_edges(state, baseline_d=baseline_d)),
                            "broken": sorted(parent_edges - satisfied_core_edges(state, baseline_d=baseline_d)),
                            "created": sorted(satisfied_core_edges(state, baseline_d=baseline_d) - parent_edges),
                            "target": target,
                            "label": label,
                            "level": level,
                            "five_packet": five_headed_ranks(state),
                            "c_immediate": c_join_immediate(state, child_loc),
                            "lower_tail_immediate": lower_tail_packet_movable_onto(state, child_loc),
                            "stock_rows": stock_rows(state),
                            "fd": face_down_count(state),
                            "empties": list(empty_column_indices(state)),
                        }
                        if child_ident not in witnesses or child_g < witnesses[child_ident]["g"]:
                            witnesses[child_ident] = rec
                        if result.first_s is None:
                            result.first_s = time.perf_counter() - started
                            result.first_unique = result.unique
                            result.first_g = child_g
                            result.first_origin = origin_of[node]
                            result.first_category = source_categories[origin_of[node]]
                            print(
                                f"FIRST_{target} g={child_g} unique={result.unique} "
                                f"t={result.first_s:.2f}s cat={result.first_category}",
                                flush=True,
                            )
                        if current_incumbent is None or child_g < current_incumbent:
                            current_incumbent = child_g
                            result.incumbent = child_g
                            ceiling = min(cost_ceiling, current_incumbent + harvest_slack)
                        continue
                    child_above = cards_above(state, child_loc)
                    heapq.heappush(
                        heap,
                        (child_above, child_g, child_depth, seq, child_node),
                    )
                    seq += 1
                finally:
                    _restore(state, cap)
            if result.stop_reason in ("unique limit", "time limit", "rss abort"):
                break
        if result.stop_reason in ("unique limit", "time limit", "rss abort"):
            break
        if current_incumbent is not None and len(witnesses) >= 16 and (deadline - time.perf_counter()) < 12:
            result.stop_reason = result.stop_reason or "harvested"
            break

    if not result.stop_reason:
        result.stop_reason = "complete"
    e0 = current_incumbent
    kept = []
    if e0 is not None:
        eligible = [rec for rec in witnesses.values() if rec["g"] <= e0 + harvest_slack]
        kept = harvest_diverse(eligible, harvest_limit)
    result.witnesses = kept
    result.elapsed_s = time.perf_counter() - started
    result.peak_rss_mb = peak
    return result


def harvest_diverse(records: Sequence[dict], limit: int) -> List[dict]:
    ordered = sorted(
        records,
        key=lambda w: (w["g"], w.get("depth", 0), w.get("origin", 0), w.get("ordered_digest", "")),
    )
    if len(ordered) <= limit:
        return list(ordered)
    buckets: Dict[tuple, List[dict]] = defaultdict(list)
    for rec in ordered:
        key = (
            rec.get("source_category"),
            tuple(rec.get("edges") or []),
            tuple(rec.get("five_packet") or []),
            bool(rec.get("c_immediate")),
            bool(rec.get("lower_tail_immediate")),
            rec.get("target"),
        )
        buckets[key].append(rec)
    out: List[dict] = []
    seen = set()
    while len(out) < limit:
        progressed = False
        for key in sorted(buckets, key=lambda k: str(k)):
            bucket = buckets[key]
            while bucket:
                rec = bucket.pop(0)
                digest = rec.get("ordered_digest")
                if digest in seen:
                    continue
                seen.add(digest)
                out.append(rec)
                progressed = True
                break
            if len(out) >= limit:
                break
        if not progressed:
            break
    return out


def preview_c(
    state: SpiderState,
    dest_loc: Tuple[int, str, int],
    g0: int,
    *,
    max_depth: int = PREVIEW_DEPTH,
    deadline: float,
    rss_abort_mb: float = RSS_PER_MB,
    baseline_d: int = 0,
) -> dict:
    ident0 = pack_state(state)
    loc0 = dest_loc
    best = {ident0: g0}
    heap = [(g0, 0, 0, ident0, loc0)]
    seq = 0
    seen: Dict[bytes, int] = {}
    unique = 1
    live = False
    found = None
    foundation = None
    immediate = c_join_immediate(state, dest_loc)
    tail_now = lower_tail_packet_movable_onto(state, dest_loc)
    if immediate:
        return {
            "status": "LOWER_TAIL_IMMEDIATE" if tail_now else "C_IMMEDIATE",
            "dead": False,
            "live": False,
            "unique": 1,
            "g": g0,
            "depth": 0,
            "lower_tail": tail_now,
            "foundation": None,
            "max_depth": max_depth,
        }
    while heap:
        if time.perf_counter() >= deadline:
            live = True
            break
        rss = _rss_mb()
        if rss is not None and rss >= rss_abort_mb:
            live = True
            break
        g, depth, _, ident, loc = heapq.heappop(heap)
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
            if action == ("deal",):
                continue
            cost = step_cost(st, action)
            child_loc = follow_loc(st, loc, action)
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
                child_depth = depth + 1
                if suit_foundation_count(st, "d") > baseline_d:
                    foundation = {"g": child_g, "depth": child_depth, "ordered_digest": child_ident.hex()}
                    break
                child_edges = satisfied_core_edges(st, baseline_d=baseline_d)
                if "C" in child_edges:
                    found = {
                        "g": child_g,
                        "depth": child_depth,
                        "ordered_digest": child_ident.hex(),
                        "edges": sorted(child_edges),
                        "lower_tail": lower_tail_present(st),
                    }
                    break
                if child_loc is None:
                    continue
                seq += 1
                heapq.heappush(heap, (child_g, child_depth, seq, child_ident, child_loc))
            finally:
                _restore(st, cap)
        if foundation or found:
            break
    if foundation:
        status = "FOUNDATION_2"
        dead = False
        live_flag = False
    elif found:
        status = "C_WITHIN_6"
        dead = False
        live_flag = False
    elif live or heap:
        status = "LIVE_BEYOND_6"
        dead = False
        live_flag = True
    else:
        status = "EXACT_DEAD_TO_C"
        dead = True
        live_flag = False
    if live and status == "EXACT_DEAD_TO_C":
        status = "LIVE_BEYOND_6"
        dead = False
    return {
        "status": status,
        "dead": dead,
        "live": live_flag,
        "unique": unique,
        "hit": found,
        "foundation": foundation,
        "max_depth": max_depth,
        "lower_tail": bool(found and found.get("lower_tail")),
    }


def synthetic_columns(face_up_runs: Sequence[Sequence[Card]], *, stock_n: int = 10) -> SpiderState:
    cols = [Column([], list(run)) for run in face_up_runs]
    while len(cols) < 10:
        cols.append(Column([], []))
    stock = [Card("h", 3) for _ in range(stock_n)]
    return SpiderState(cols, stock)
