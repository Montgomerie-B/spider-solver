"""Research-only v0.48 Spade 5S landing-resource cut.

From the retained B4=2 frontier (cover 10D, 5S), manufacture LAND5_READY:

    exposed rank-6 exists  OR  empty column exists.

That is the first legal destination for the physical blocker 5S sitting on
the unique-4S column.  Canonical identity is post-stock symmetry.
Resource type, history, B4, and intent are not identity.  Tableau only.
Full accumulated MW is g.  Do not search TAIL4.  Do not search Foundation 2.
Do not search Foundation 3.  Do not move 5S in the primary search.
Successful exposure stops immediately.
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
from spider.engine import Column, SpiderState
from spider.metrics import Action, replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state, unpack_state
from spider.simple_current_horizon import SUITS, current_tableau_occurrences
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, dump_actions, opening_state
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
from spider.simple_spade_4s_ratchet import b4_count, locate_unique_spade, unique_4s_exposed
from spider.simple_spade_final_access import (
    COVER_ABOVE,
    NEXT_BLOCKER,
    TOP_BLOCKER,
    dest_kind,
    exposed_rank_columns,
    five_s_moves,
    five_s_requires_six_or_empty,
    harvest_rows,
    load_b42_sources,
    packet_dests,
    ten_d_moves,
    ten_d_requires_jack_or_empty,
)
from spider.simple_workspace_reachability import empty_column_indices, engine_tableau_actions, face_down_count

ROOT = Path(__file__).resolve().parents[2]
HARD_LB = 92
COST_CEILING = 100
SEARCH_UNIQUE = 160_000
SEARCH_TIME_S = 300.0
SEARCH_RSS_MB = 2.0 * 1024.0
GLOBAL_TIME_S = 400.0
RSS_ABORT_MB = 2.5 * 1024.0
HARVEST_SLACK = 3
HARVEST_LIMIT = 192

LAND5_CREATE = "LAND5_CREATE"
EXPOSE_6 = "EXPOSE_6"
EMPTY_COL = "EMPTY_COL"
UNBLOCK_6 = "UNBLOCK_6"
CLEARABLE = "CLEARABLE"
PRESERVE_J = "PRESERVE_J"
TARGET_JOIN = "TARGET_JOIN"
AB_QUALITY = "AB_QUALITY"

L0_LABELS = {LAND5_CREATE, EXPOSE_6, EMPTY_COL, UNBLOCK_6, CLEARABLE, GOOD_PLAY}
L1_EXTRA = {AB_QUALITY, PARK, PRESERVE_J, TARGET_JOIN}

LABEL_RANK = {
    LAND5_CREATE: 0,
    EXPOSE_6: 1,
    EMPTY_COL: 2,
    UNBLOCK_6: 3,
    CLEARABLE: 4,
    PRESERVE_J: 5,
    TARGET_JOIN: 6,
    GOOD_PLAY: 7,
    AB_QUALITY: 8,
    PARK: 9,
    OTHER: 10,
    JOIN_BREAK: 11,
    "DEAL": 12,
}


def exposure_lower_bound(source_g: int) -> int:
    """Support (>=1) + 5S (>=1) + 10D (>=1) while 4S remains behind."""

    return int(source_g) + 3


def retained_frontier_hard_lb() -> int:
    return HARD_LB


def land5_ready(state: SpiderState) -> bool:
    return bool(empty_column_indices(state)) or bool(exposed_rank_columns(state, 6))


def land5_kind(state: SpiderState) -> str:
    six = bool(exposed_rank_columns(state, 6))
    empty = bool(empty_column_indices(state))
    if six and empty:
        return "SIX_AND_EMPTY_READY"
    if six:
        return "SIX_READY"
    if empty:
        return "EMPTY_READY"
    return "NOT_READY"


def jack_ready(state: SpiderState) -> bool:
    return bool(exposed_rank_columns(state, 11))


def physical_blocker_5s(state: SpiderState) -> Optional[dict]:
    loc = locate_unique_spade(state, 4)
    if loc is None:
        return None
    col = loc["column_0"]
    up = state.columns[col].face_up
    if not up or pretty_card(up[-1]) != TOP_BLOCKER:
        return None
    return {
        "column_0": col,
        "column_1": col + 1,
        "card": TOP_BLOCKER,
        "above_4s": list(loc.get("above") or []),
    }


def must_cross_land5() -> str:
    return (
        "A 5S tableau move is legal only onto an exposed rank-6 or an empty. "
        "Every trajectory that moves this physical 5S must first reach LAND5_READY."
    )


def top_movable_k(state: SpiderState, col: int) -> int:
    up = state.columns[col].face_up
    if not up:
        return 0
    k = 1
    while k < len(up) and SpiderState.is_movable_run(up[-k - 1 :]):
        k += 1
    return k


def _new_src_top(state: SpiderState, src: int, k: int):
    col = state.columns[src]
    if k < len(col.face_up):
        return col.face_up[-k - 1]
    if col.face_down:
        return col.face_down[-1]
    return None


def rank_occurrences(state: SpiderState, rank: int) -> List[dict]:
    out: List[dict] = []
    for suit in SUITS:
        for occ in current_tableau_occurrences(state, suit, rank):
            col = occ["column_0"]
            k = top_movable_k(state, col)
            dests = packet_dests(state, col, k) if k else []
            packet = [pretty_card(c) for c in state.columns[col].face_up[-k:]] if k else []
            need = None
            if k and not dests:
                head = state.columns[col].face_up[-k]
                need = head.rank + 1
            one_move = False
            if occ.get("face_up") and not occ.get("top"):
                above_k = int(occ["cards_above"])
                run = state.columns[col].face_up[-above_k:] if above_k else []
                if above_k and SpiderState.is_movable_run(run) and packet_dests(state, col, above_k):
                    one_move = True
            elif not occ.get("face_up"):
                n_up = len(state.columns[col].face_up)
                n_down_above = int(occ.get("face_down_blockers_above") or 0)
                if n_down_above == 0 and n_up and SpiderState.is_movable_run(state.columns[col].face_up) and packet_dests(state, col, n_up):
                    one_move = True
            out.append(
                {
                    "suit": suit,
                    "card": _rank_card(suit, rank),
                    "column_1": occ["column_1"],
                    "face_up": bool(occ.get("face_up")),
                    "top": bool(occ.get("top")),
                    "cards_above": int(occ.get("cards_above") or 0),
                    "above": list(occ.get("face_up_above") or []),
                    "top_packet_k": k,
                    "top_packet": packet,
                    "packet_movable": bool(dests),
                    "packet_dests_1": [d + 1 for d in dests],
                    "need_rank": need,
                    "one_move_exposable": one_move,
                }
            )
    return out


def _rank_card(suit: str, rank: int) -> str:
    from spider.cards import rank_str

    return f"{rank_str(rank)}{suit.upper()}"


def empty_column_candidates(state: SpiderState) -> List[dict]:
    out = []
    for i, col in enumerate(state.columns):
        if col.is_empty():
            out.append(
                {
                    "column_1": i + 1,
                    "empty": True,
                    "fd": 0,
                    "fu": 0,
                    "one_move_clearable": False,
                }
            )
            continue
        k = top_movable_k(state, i)
        dests = packet_dests(state, i, k) if k else []
        whole_up = k == len(col.face_up) and bool(dests)
        creates_empty = whole_up and not col.face_down
        need = None
        if k and not dests:
            need = col.face_up[-k].rank + 1
        out.append(
            {
                "column_1": i + 1,
                "empty": False,
                "fd": len(col.face_down),
                "fu": len(col.face_up),
                "top": pretty_card(col.top()) if col.top() else None,
                "top_packet_k": k,
                "packet_movable": bool(dests),
                "whole_exposed_can_leave": whole_up,
                "creates_empty": creates_empty,
                "one_move_clearable": creates_empty,
                "need_rank": need,
            }
        )
    return out


def first_support_zero_cost_possible(state: SpiderState) -> bool:
    if empty_column_indices(state):
        for action in engine_tableau_actions(state)[0]:
            if step_cost(state, action) == 0:
                return True
        return False
    for action in engine_tableau_actions(state)[0]:
        if step_cost(state, action) == 0:
            return True
    return False


def blocker_move_costs_one(state: SpiderState, action: Action) -> bool:
    if action == ("deal",):
        return False
    loc = locate_unique_spade(state, 4)
    if loc is None or unique_4s_exposed(state):
        return False
    src, _dst, k = action
    if src != loc["column_0"]:
        return False
    return step_cost(state, action) == 1 and k >= 1


def allowed_at_land5_level(label: str, tier: int, level: int) -> bool:
    if level >= 3:
        return True
    if level <= 0:
        return label in L0_LABELS
    if level == 1:
        return label in (L0_LABELS | L1_EXTRA) or tier <= int(Tier.B)
    if level == 2:
        return label != JOIN_BREAK
    return True


def annotate_land5_action(state: SpiderState, action) -> str:
    if action == ("deal",):
        return "DEAL"
    src, dst, k = action
    src_col = state.columns[src]
    dst_col = state.columns[dst]
    run = src_col.face_up[-k:]
    head = run[0]
    dest_top = dst_col.top()
    dest_empty = dst_col.is_empty()
    join_break = False
    if k < len(src_col.face_up):
        left = src_col.face_up[-k - 1]
        h = src_col.face_up[-k]
        join_break = left.suit == h.suit and left.rank == h.rank + 1
    creates_empty = k == len(src_col.face_up) and not src_col.face_down
    new_top = _new_src_top(state, src, k)
    exposes_6 = new_top is not None and new_top.rank == 6
    exposes_j = new_top is not None and new_top.rank == 11
    parks_6 = dest_empty and head.rank == 6
    if exposes_6 or parks_6 or creates_empty:
        return LAND5_CREATE
    # Nearest buried face-up 6: peeling from its column is UNBLOCK_6.
    min_above = None
    unblock_cols = set()
    for col_i, col in enumerate(state.columns):
        up = col.face_up
        for u_i, card in enumerate(up):
            if card.rank != 6 or u_i == len(up) - 1:
                continue
            above = len(up) - 1 - u_i
            if min_above is None or above < min_above:
                min_above = above
                unblock_cols = {col_i}
            elif above == min_above:
                unblock_cols.add(col_i)
    if src in unblock_cols:
        return UNBLOCK_6
    if k == len(src_col.face_up) and not dest_empty:
        return CLEARABLE
    if exposes_j or (dest_empty and head.rank == 11):
        return PRESERVE_J
    if dest_top is not None and dest_top.suit == head.suit and dest_top.rank == head.rank + 1:
        return TARGET_JOIN
    if join_break:
        return JOIN_BREAK
    if int(classify_tier(state, action)) == int(Tier.A):
        return GOOD_PLAY
    if int(classify_tier(state, action)) <= int(Tier.B):
        return AB_QUALITY
    if dest_empty:
        return PARK
    return OTHER


def synthetic_columns(face_up_runs: Sequence[Sequence[Card]], *, stock_n: int = 0, foundations=None) -> SpiderState:
    cols = [Column([], list(run)) for run in face_up_runs]
    while len(cols) < 10:
        cols.append(Column([], []))
    stock = [Card("h", 3) for _ in range(stock_n)]
    return SpiderState(cols, stock, foundations or [])


def load_land5_sources(opening: Optional[SpiderState] = None) -> dict:
    bundle = load_b42_sources(opening)
    extra_fail = 0
    for rec in bundle["states"]:
        st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
        if land5_ready(st) or jack_ready(st) or empty_column_indices(st) or exposed_rank_columns(st, 6):
            extra_fail += 1
        rec["source_g"] = rec["g"]
    bundle["land5_absent"] = extra_fail == 0
    bundle["extra_fail"] = extra_fail
    bundle["all_replay_ok"] = bundle["all_replay_ok"] and extra_fail == 0
    return bundle


def structural_resource_audit(sources: Sequence[dict]) -> dict:
    six_depth = Counter()
    six_one_move = 0
    six_n = 0
    six_face_down = 0
    six_sigs = Counter()
    jack_depth = Counter()
    jack_top = 0
    jack_n = 0
    jack_one_with_land5 = 0
    empty_one_move = 0
    fd0_cols = Counter()
    need_ranks = Counter()
    samples = []
    for rec in sources:
        st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
        sixes = rank_occurrences(st, 6)
        jacks = rank_occurrences(st, 11)
        empties = empty_column_candidates(st)
        six_n += len(sixes)
        for s in sixes:
            six_depth[s["cards_above"]] += 1
            if not s["face_up"]:
                six_face_down += 1
            if s["one_move_exposable"]:
                six_one_move += 1
            sig = (s["suit"], s["cards_above"], s["face_up"], tuple(s["above"][:4]))
            six_sigs[str(sig)] += 1
            if s["need_rank"]:
                need_ranks[s["need_rank"]] += 1
        jack_n += len(jacks)
        for j in jacks:
            jack_depth[j["cards_above"]] += 1
            if j["top"]:
                jack_top += 1
        for e in empties:
            if e.get("fd") == 0 and not e.get("empty"):
                fd0_cols[e["fu"]] += 1
            if e.get("one_move_clearable"):
                empty_one_move += 1
        if len(samples) < 4:
            samples.append(
                {
                    "g": rec["g"],
                    "timing": rec.get("timing"),
                    "sixes": sixes,
                    "jacks": jacks,
                    "empties": [e for e in empties if not e.get("empty")],
                }
            )
    return {
        "n_sources": len(sources),
        "rank6": {
            "occurrences": six_n,
            "per_source": six_n / max(1, len(sources)),
            "depth": {str(k): int(v) for k, v in sorted(six_depth.items())},
            "face_down": six_face_down,
            "one_move_exposable": six_one_move,
            "signatures": dict(six_sigs.most_common(24)),
            "need_ranks": {str(k): int(v) for k, v in sorted(need_ranks.items())},
        },
        "empty": {
            "one_move_clearable": empty_one_move,
            "fd0_face_up_lens": {str(k): int(v) for k, v in sorted(fd0_cols.items())},
        },
        "jack": {
            "occurrences": jack_n,
            "depth": {str(k): int(v) for k, v in sorted(jack_depth.items())},
            "already_top": jack_top,
        },
        "samples": samples,
    }


def one_move_fast_path(sources: Sequence[dict]) -> dict:
    hits: List[dict] = []
    n_actions = 0
    for origin, rec in enumerate(sources):
        st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
        g0 = int(rec["g"])
        for action in engine_tableau_actions(st)[0]:
            if action == ("deal",):
                continue
            n_actions += 1
            cost = step_cost(st, action)
            cap = _capture(st, action)
            try:
                apply_action(st, action)
                if not land5_ready(st):
                    continue
                kind = land5_kind(st)
                child_g = g0 + cost
                blocker = physical_blocker_5s(st)
                hits.append(
                    {
                        "origin": origin,
                        "g": child_g,
                        "source_g": g0,
                        "depth": 1,
                        "actions": dump_actions([action]),
                        "full_actions": dump_actions(as_actions(rec["full_actions"]) + [action]),
                        "ordered_digest": pack_state(st).hex(),
                        "symmetry_digest": pack_post_stock_symmetry_state(st).hex(),
                        "kind": kind,
                        "jack_ready": jack_ready(st),
                        "timing": rec.get("timing"),
                        "lineages": rec.get("lineages"),
                        "fast_path": True,
                        "land5": True,
                        "five_s_can_move": bool(five_s_moves(st)),
                        "blocker_col_1": None if blocker is None else blocker["column_1"],
                        "fd": face_down_count(st),
                        "empties": [i + 1 for i in empty_column_indices(st)],
                        "rank6": [i + 1 for i in exposed_rank_columns(st, 6)],
                        "jacks": [i + 1 for i in exposed_rank_columns(st, 11)],
                    }
                )
            finally:
                _restore(st, cap)
    by: Dict[str, dict] = {}
    for w in hits:
        prev = by.get(w["symmetry_digest"])
        if prev is None or w["g"] < prev["g"]:
            by[w["symmetry_digest"]] = w
    kept = sorted(by.values(), key=lambda w: (w["g"], w["origin"]))
    kinds = Counter(w["kind"] for w in kept)
    return {
        "n_sources": len(sources),
        "n_actions": n_actions,
        "n_hits_raw": len(hits),
        "n_unique": len(kept),
        "kinds": dict(kinds),
        "jack_ready": sum(1 for w in kept if w["jack_ready"]),
        "cheapest": None if not kept else min(w["g"] for w in kept),
        "from_89": None if not any(w["source_g"] == 89 for w in kept) else min(w["g"] for w in kept if w["source_g"] == 89),
        "from_90": None if not any(w["source_g"] == 90 for w in kept) else min(w["g"] for w in kept if w["source_g"] == 90),
        "mw90_from_89": sum(1 for w in kept if w["source_g"] == 89 and w["g"] == 90),
        "witnesses": kept,
    }


@dataclass
class Land5Result:
    unique: int = 0
    expanded: int = 0
    generated: int = 0
    duplicate_skips: int = 0
    elapsed_s: float = 0.0
    peak_rss_mb: Optional[float] = None
    stop_reason: str = ""
    deal_expanded: bool = False
    foundation_surprise: bool = False
    witnesses: List[dict] = field(default_factory=list)
    first_s: Optional[float] = None
    first_g: Optional[int] = None
    first_kind: Optional[str] = None
    contract_fail: int = 0


def search_land5(
    sources: Sequence[dict],
    *,
    max_unique: int = SEARCH_UNIQUE,
    time_limit_s: float = SEARCH_TIME_S,
    rss_abort_mb: float = SEARCH_RSS_MB,
    cost_ceiling: int = COST_CEILING,
) -> Land5Result:
    started = time.perf_counter()
    deadline = started + time_limit_s
    result = Land5Result()
    peak = _rss_mb()
    best_g: Dict[bytes, int] = {}
    parent: List[int] = []
    action_of: List[Optional[Action]] = []
    depth_of: List[int] = []
    origin_of: List[int] = []
    g_of: List[int] = []
    ident_ord_of: List[bytes] = []
    ident_sym_of: List[bytes] = []
    witnesses: Dict[bytes, dict] = {}
    current_incumbent: Optional[int] = None

    def reconstruct(node: int) -> List[Action]:
        path: List[Action] = []
        cur = node
        while cur >= 0 and parent[cur] >= 0:
            act = action_of[cur]
            if act is not None:
                path.append(act)
            cur = parent[cur]
        path.reverse()
        return path

    def note_rss() -> bool:
        nonlocal peak
        rss = _rss_mb()
        if rss is not None and (peak is None or rss > peak):
            peak = rss
        return rss is not None and rss >= rss_abort_mb

    order = sorted(range(len(sources)), key=lambda i: (int(sources[i]["g"]), sources[i]["ordered_digest"]))
    for origin in order:
        rec = sources[origin]
        ident_ord = bytes.fromhex(rec["ordered_digest"])
        ident_sym = bytes.fromhex(rec["symmetry_digest"])
        g0 = int(rec["g"])
        st0 = unpack_state(ident_ord)
        if land5_ready(st0):
            continue
        if ident_sym in best_g:
            if g0 < best_g[ident_sym]:
                best_g[ident_sym] = g0
                idx = ident_sym_of.index(ident_sym)
                g_of[idx] = g0
                origin_of[idx] = origin
                ident_ord_of[idx] = ident_ord
            continue
        best_g[ident_sym] = g0
        ident_sym_of.append(ident_sym)
        ident_ord_of.append(ident_ord)
        parent.append(-1)
        action_of.append(None)
        depth_of.append(0)
        origin_of.append(origin)
        g_of.append(g0)
    result.unique = len(best_g)
    print(f"LAND5 start unique={result.unique} sources={len(sources)}", flush=True)

    for level in range(0, 4):
        if time.perf_counter() >= deadline:
            result.stop_reason = "time limit"
            break
        if note_rss():
            result.stop_reason = "rss abort"
            break
        heap: List[tuple] = []
        seq = 0
        best_node: Dict[bytes, int] = {}
        for i, ident in enumerate(ident_sym_of):
            if best_g.get(ident) == g_of[i]:
                best_node[ident] = i
        for ident, node in best_node.items():
            if g_of[node] > cost_ceiling:
                continue
            st = unpack_state(ident_ord_of[node])
            if land5_ready(st) and depth_of[node] > 0:
                continue
            heapq.heappush(heap, (0, g_of[node], depth_of[node], seq, node))
            seq += 1
        seen_expand: Dict[bytes, int] = {}
        remaining_s = deadline - time.perf_counter()
        levels_left = 4 - level
        level_deadline = time.perf_counter() + max(12.0, remaining_s / max(1, levels_left))
        print(
            f"LAND5 L{level} unique={result.unique} heap={len(heap)} inc={current_incumbent} "
            f"wit={len(witnesses)} budget={level_deadline - time.perf_counter():.0f}s",
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
            if result.expanded and (result.expanded & 8191) == 0 and result.expanded not in seen_expand:
                print(
                    f"LAND5 L{level} exp={result.expanded} unique={result.unique} inc={current_incumbent} "
                    f"wit={len(witnesses)} heap={len(heap)}",
                    flush=True,
                )
            _rk, _g, _d, _s, node = heapq.heappop(heap)
            ident_sym = ident_sym_of[node]
            g = g_of[node]
            depth = depth_of[node]
            if g != best_g.get(ident_sym):
                continue
            if g > cost_ceiling:
                continue
            if seen_expand.get(ident_sym, 10**9) <= g:
                continue
            seen_expand[ident_sym] = g
            state = unpack_state(ident_ord_of[node])
            if land5_ready(state) and depth > 0:
                continue
            if state.stock:
                result.deal_expanded = True
            blocker = physical_blocker_5s(state)
            actions, _ = engine_tableau_actions(state)
            ranked = []
            for action in actions:
                if action == ("deal",):
                    result.deal_expanded = True
                    continue
                if blocker is not None and action[0] == blocker["column_0"] and pretty_card(state.columns[action[0]].face_up[-1]) == TOP_BLOCKER:
                    # Do not move 5S in the primary search.
                    if five_s_requires_six_or_empty(state, action):
                        result.contract_fail += 1
                    continue
                label = annotate_land5_action(state, action)
                tier_i = int(classify_tier(state, action))
                if not allowed_at_land5_level(label, tier_i, level):
                    continue
                ranked.append((LABEL_RANK.get(label, 10), action, label))
            ranked.sort(key=lambda t: (t[0], t[1]))
            result.expanded += 1
            for _p, action, label in ranked:
                cost = step_cost(state, action)
                child_g = g + cost
                if child_g > cost_ceiling:
                    continue
                cap = _capture(state, action)
                try:
                    apply_action(state, action)
                    result.generated += 1
                    if state.stock:
                        result.deal_expanded = True
                    child_ord = pack_state(state)
                    child_sym = pack_post_stock_symmetry_state(state)
                    prev = best_g.get(child_sym)
                    if prev is not None and child_g >= prev:
                        result.duplicate_skips += 1
                        continue
                    if prev is None:
                        result.unique += 1
                    if result.unique >= max_unique:
                        result.stop_reason = "unique limit"
                        break
                    best_g[child_sym] = child_g
                    child_node = len(ident_sym_of)
                    ident_sym_of.append(child_sym)
                    ident_ord_of.append(child_ord)
                    parent.append(node)
                    action_of.append(action)
                    depth_of.append(depth + 1)
                    origin_of.append(origin_of[node])
                    g_of.append(child_g)
                    ready = land5_ready(state)
                    foundation = suit_foundation_count(state, "s") > 1
                    if foundation:
                        result.foundation_surprise = True
                    if ready or foundation:
                        src = sources[origin_of[node]]
                        kind = land5_kind(state)
                        rec_w = {
                            "origin": origin_of[node],
                            "g": child_g,
                            "source_g": int(src["g"]),
                            "depth": depth + 1,
                            "actions": dump_actions(reconstruct(child_node)),
                            "ordered_digest": child_ord.hex(),
                            "symmetry_digest": child_sym.hex(),
                            "kind": kind,
                            "jack_ready": jack_ready(state),
                            "label": label,
                            "timing": src.get("timing"),
                            "lineages": src.get("lineages"),
                            "foundation": foundation,
                            "land5": ready,
                            "five_s_can_move": bool(five_s_moves(state)),
                            "fd": face_down_count(state),
                            "empties": [i + 1 for i in empty_column_indices(state)],
                            "rank6": [i + 1 for i in exposed_rank_columns(state, 6)],
                            "jacks": [i + 1 for i in exposed_rank_columns(state, 11)],
                            "rank6_cards": [s["card"] for s in rank_occurrences(state, 6) if s["top"]],
                        }
                        if child_sym not in witnesses or child_g < witnesses[child_sym]["g"]:
                            witnesses[child_sym] = rec_w
                        if result.first_s is None:
                            result.first_s = time.perf_counter() - started
                            result.first_g = child_g
                            result.first_kind = kind
                            print(
                                f"FIRST_LAND5 {kind} g={child_g} unique={result.unique} "
                                f"t={result.first_s:.2f}s src_g={src['g']}",
                                flush=True,
                            )
                        if current_incumbent is None or child_g < current_incumbent:
                            current_incumbent = child_g
                        continue
                    heapq.heappush(heap, (LABEL_RANK.get(label, 10), child_g, depth + 1, seq, child_node))
                    seq += 1
                finally:
                    _restore(state, cap)
            if result.stop_reason in ("unique limit", "time limit", "rss abort"):
                break
        if result.stop_reason in ("unique limit", "time limit", "rss abort"):
            break
        if witnesses and (deadline - time.perf_counter()) < 8:
            result.stop_reason = result.stop_reason or "harvested"
            break
    if not result.stop_reason:
        result.stop_reason = "complete"
    rows = [w for w in witnesses.values() if w.get("land5")]
    kept = harvest_rows(
        rows,
        limit=HARVEST_LIMIT,
        keyfn=lambda w: (
            w.get("kind"),
            bool(w.get("jack_ready")),
            w.get("source_g"),
            w.get("timing"),
            tuple(w.get("rank6_cards") or []),
            tuple(w.get("empties") or []),
            w.get("fd"),
        ),
    )
    result.witnesses = kept
    result.elapsed_s = time.perf_counter() - started
    result.peak_rss_mb = peak
    return result


def gate2_class(state: SpiderState) -> str:
    j = jack_ready(state)
    e = bool(empty_column_indices(state))
    if j and e:
        return "BOTH_READY"
    if j:
        return "JACK_READY"
    if e:
        return "EMPTY_READY"
    return "GATE2_BLOCKED"


def _full_from_land5(rec: dict, sources: Sequence[dict]) -> List[Action]:
    full = as_actions(rec.get("full_actions") or [])
    if full:
        return full
    origin = rec.get("origin", 0)
    if 0 <= origin < len(sources):
        return as_actions(sources[origin]["full_actions"]) + as_actions(rec.get("actions") or [])
    return as_actions(rec.get("actions") or [])


def _uniq_rows(rows: Sequence[dict]) -> List[dict]:
    by: Dict[str, dict] = {}
    for w in rows:
        prev = by.get(w["symmetry_digest"])
        if prev is None or w["g"] < prev["g"]:
            by[w["symmetry_digest"]] = w
    return sorted(by.values(), key=lambda w: (w["g"], w.get("source_g", 0)))


def _best_from(rows: Sequence[dict], source_g: int):
    hit = [w for w in rows if w.get("source_g") == source_g]
    if not hit:
        return None
    return min(w["g"] for w in hit)


def preview_5s_10d(sources: Sequence[dict], land5_rows: Sequence[dict], opening: SpiderState) -> dict:
    """Tiny continuation: 5S, optional one support, 10D. No broader search."""

    del opening
    n_5s = 0
    dests: Counter = Counter()
    g2: Counter = Counter()
    immediate: List[dict] = []
    one_support: List[dict] = []
    blocked = 0
    contract_fail = 0
    for rec in land5_rows:
        st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
        if not land5_ready(st):
            contract_fail += 1
            continue
        moves5 = five_s_moves(st)
        if not moves5:
            contract_fail += 1
            continue
        g0 = int(rec["g"])
        src_full = _full_from_land5(rec, sources)
        for a1 in moves5:
            if not five_s_requires_six_or_empty(st, a1):
                continue
            n_5s += 1
            land5k = dest_kind(st, a1[1])
            dests[land5k] += 1
            c1 = step_cost(st, a1)
            cap1 = _capture(st, a1)
            try:
                apply_action(st, a1)
                if b4_count(st) != 1:
                    continue
                loc = locate_unique_spade(st, 4)
                if loc is None or pretty_card(st.columns[loc["column_0"]].face_up[-1]) != NEXT_BLOCKER:
                    continue
                cls = gate2_class(st)
                g2[cls] += 1
                exposed_now = False
                for a2 in ten_d_moves(st):
                    if not ten_d_requires_jack_or_empty(st, a2):
                        continue
                    land10 = dest_kind(st, a2[1])
                    c2 = step_cost(st, a2)
                    cap2 = _capture(st, a2)
                    try:
                        apply_action(st, a2)
                        if unique_4s_exposed(st):
                            exposed_now = True
                            immediate.append(
                                {
                                    "g": g0 + c1 + c2,
                                    "source_g": rec.get("source_g"),
                                    "land5_g": g0,
                                    "actions": dump_actions(as_actions(rec.get("actions") or []) + [a1, a2]),
                                    "full_actions": dump_actions(src_full + [a1, a2]),
                                    "ordered_digest": pack_state(st).hex(),
                                    "symmetry_digest": pack_post_stock_symmetry_state(st).hex(),
                                    "landing_5s": land5k,
                                    "landing_10d": land10,
                                    "class": "EXPOSURE_IMMEDIATE_FROM_RESOURCE",
                                    "timing": rec.get("timing"),
                                    "lb_matched": (g0 + c1 + c2) == HARD_LB,
                                    "exposed": True,
                                    "fd": face_down_count(st),
                                    "empties": [i + 1 for i in empty_column_indices(st)],
                                }
                            )
                    finally:
                        _restore(st, cap2)
                if exposed_now:
                    continue
                if cls != "GATE2_BLOCKED":
                    blocked += 1
                    continue
                blocked += 1
                for support in engine_tableau_actions(st)[0]:
                    if support == ("deal",):
                        continue
                    cs = step_cost(st, support)
                    cap_s = _capture(st, support)
                    try:
                        apply_action(st, support)
                        if b4_count(st) != 1:
                            continue
                        loc2 = locate_unique_spade(st, 4)
                        if loc2 is None or pretty_card(st.columns[loc2["column_0"]].face_up[-1]) != NEXT_BLOCKER:
                            continue
                        for a2 in ten_d_moves(st):
                            if not ten_d_requires_jack_or_empty(st, a2):
                                continue
                            c2 = step_cost(st, a2)
                            cap2 = _capture(st, a2)
                            try:
                                apply_action(st, a2)
                                if unique_4s_exposed(st):
                                    one_support.append(
                                        {
                                            "g": g0 + c1 + cs + c2,
                                            "source_g": rec.get("source_g"),
                                            "land5_g": g0,
                                            "actions": dump_actions(as_actions(rec.get("actions") or []) + [a1, support, a2]),
                                            "full_actions": dump_actions(src_full + [a1, support, a2]),
                                            "ordered_digest": pack_state(st).hex(),
                                            "symmetry_digest": pack_post_stock_symmetry_state(st).hex(),
                                            "class": "EXPOSURE_ONE_SUPPORT_FROM_RESOURCE",
                                            "timing": rec.get("timing"),
                                            "lb_matched": False,
                                            "exposed": True,
                                            "fd": face_down_count(st),
                                            "empties": [i + 1 for i in empty_column_indices(st)],
                                        }
                                    )
                            finally:
                                _restore(st, cap2)
                    finally:
                        _restore(st, cap_s)
            finally:
                _restore(st, cap1)
    imm = _uniq_rows(immediate)
    one = _uniq_rows(one_support)
    cheapest = None
    if imm:
        cheapest = min(w["g"] for w in imm)
    if one:
        c_one = min(w["g"] for w in one)
        cheapest = c_one if cheapest is None else min(cheapest, c_one)
    return {
        "n_land5": len(land5_rows),
        "n_5s_releases": n_5s,
        "destinations": dict(dests),
        "gate2": dict(g2),
        "contract_fail": contract_fail,
        "immediate_n": len(imm),
        "one_support_n": len(one),
        "blocked": blocked,
        "cheapest_exposure": cheapest,
        "mw92_n": sum(1 for w in imm if w.get("lb_matched")),
        "from_89": _best_from(imm + one, 89),
        "from_90": _best_from(imm + one, 90),
        "immediate": imm[:128],
        "one_support": one[:128],
    }
