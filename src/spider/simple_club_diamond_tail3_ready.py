"""Research-only v0.49 Club vs Diamond TAIL3_READY race.

From the 720 DEAL_NOW post-SD5 roots, take every current 2C-AC / 2D-AD
state and search the first TAIL3_READY crossing:

    a movable same-suit 2-A packet AND an exposed matching rank-3
    exist simultaneously, so 2-A onto 3 is a legal one-move TAIL3.

Canonical identity is post-stock symmetry.  Suit progress, selected
physical cards, READY class, and history are not identity.  Tableau only.
Full accumulated MW is g.  Do not search Spades, Hearts, Foundation 2/3,
or rank 5+.
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
from spider.simple_current_horizon import current_tableau_occurrences
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
from spider.simple_post_sd5_edge_race import edge_2a_present, load_deal_now_roots, tail3_present
from spider.simple_progressive_solver import (
    Tier,
    _capture,
    _restore,
    _rss_mb,
    apply_action,
    classify_tier,
    step_cost,
)
from spider.simple_spade_final_access import harvest_rows
from spider.simple_workspace_reachability import empty_column_indices, engine_tableau_actions, face_down_count

ROOT = Path(__file__).resolve().parents[2]
V044_ROOTS = ROOT / "docs" / "research" / "post_sd5_deal_now_roots_v0_44.json"
EXPECTED_ROOTS = 720
COST_CEILING = 100
SEARCH_UNIQUE = 160_000
SEARCH_TIME_S = 180.0
SEARCH_RSS_MB = 1.5 * 1024.0
GLOBAL_TIME_S = 360.0
RSS_ABORT_MB = 2.5 * 1024.0
HARVEST_LIMIT = 192
PREVIEW_DEPTH = 5
PREVIEW_UNIQUE = 800
PREVIEW_TIME_S = 0.25

READY_CREATE = "READY_CREATE"
PACKET_MOBILISE = "PACKET_MOBILISE"
EXPOSE_3 = "EXPOSE_3"
LANDING_SUPPORT = "LANDING_SUPPORT"
TARGET_JOIN = "TARGET_JOIN"
AB_QUALITY = "AB_QUALITY"

L0_LABELS = {READY_CREATE, PACKET_MOBILISE, EXPOSE_3, LANDING_SUPPORT, TARGET_JOIN, GOOD_PLAY}
L1_EXTRA = {AB_QUALITY, PARK}

LABEL_RANK = {
    READY_CREATE: 0,
    PACKET_MOBILISE: 1,
    EXPOSE_3: 2,
    LANDING_SUPPORT: 3,
    TARGET_JOIN: 4,
    GOOD_PLAY: 5,
    AB_QUALITY: 6,
    PARK: 7,
    OTHER: 8,
    JOIN_BREAK: 9,
    "DEAL": 10,
}


def must_cross_tail3_ready() -> str:
    return (
        "The action which first creates 3-2-A must legally move a 2-A packet onto "
        "an exposed matching rank-3. Immediately before that action the state is "
        "TAIL3_READY. Every first 3-2-A trajectory therefore crosses TAIL3_READY."
    )


def must_cross_tail4_ready() -> str:
    return (
        "The action which first creates 4-3-2-A must legally move a 3-2-A packet onto "
        "an exposed matching rank-4. Immediately before that action the state is "
        "TAIL4_READY."
    )


def two_a_packets(state: SpiderState, suit: str) -> List[dict]:
    out = []
    actions, _ = engine_tableau_actions(state)
    for col, column in enumerate(state.columns):
        up = column.face_up
        for i in range(len(up) - 1):
            a, b = up[i], up[i + 1]
            if a.suit != suit or b.suit != suit or a.rank != 2 or b.rank != 1:
                continue
            above = [pretty_card(c) for c in up[i + 2 :]]
            exposed = not above
            run = up[i : i + 2]
            movable = exposed and SpiderState.is_movable_run(run)
            dests = [act[1] for act in actions if act[0] == col and act[2] == 2] if movable else []
            out.append(
                {
                    "column_0": col,
                    "column_1": col + 1,
                    "up_index": i,
                    "exposed": exposed,
                    "movable": movable,
                    "cards_above": len(above),
                    "above": above,
                    "dests_1": [d + 1 for d in dests],
                }
            )
    return out


def rank_cards(state: SpiderState, suit: str, rank: int) -> List[dict]:
    out = []
    actions, _ = engine_tableau_actions(state)
    for occ in current_tableau_occurrences(state, suit, rank):
        col = occ["column_0"]
        dests = []
        if occ.get("face_up") and not occ.get("top"):
            above_k = int(occ["cards_above"])
            up = state.columns[col].face_up
            run = up[-above_k:] if above_k else []
            if above_k and SpiderState.is_movable_run(run):
                dests = [act[1] + 1 for act in actions if act[0] == col and act[2] == above_k]
        if not occ.get("face_up"):
            n_up = len(state.columns[col].face_up)
            n_down_above = int(occ.get("face_down_blockers_above") or 0)
            if n_down_above == 0 and n_up and SpiderState.is_movable_run(state.columns[col].face_up):
                dests = [act[1] + 1 for act in actions if act[0] == col and act[2] == n_up]
        out.append(
            {
                "column_0": col,
                "column_1": occ["column_1"],
                "face_up": bool(occ.get("face_up")),
                "top": bool(occ.get("top")),
                "cards_above": int(occ.get("cards_above") or 0),
                "above": list(occ.get("face_up_above") or []),
                "one_move_exposable": bool(dests),
                "cover_dests_1": dests,
            }
        )
    return out


def tail3_ready(state: SpiderState, suit: str) -> bool:
    packets = two_a_packets(state, suit)
    threes = rank_cards(state, suit, 3)
    exposed_3_cols = {t["column_0"] for t in threes if t["top"]}
    for p in packets:
        if not p["movable"]:
            continue
        for dst in range(10):
            if dst == p["column_0"]:
                continue
            if dst not in exposed_3_cols:
                continue
            top = state.columns[dst].top()
            if top is None or top.suit != suit or top.rank != 3:
                continue
            if state.can_move(p["column_0"], dst, 2):
                return True
    return False


def tail3_already(state: SpiderState, suit: str) -> bool:
    return tail3_present(state, suit, baseline=0)


def tail4_present(state: SpiderState, suit: str) -> bool:
    for column in state.columns:
        up = column.face_up
        for i in range(len(up) - 3):
            a, b, c, d = up[i], up[i + 1], up[i + 2], up[i + 3]
            if a.suit == b.suit == c.suit == d.suit == suit and [a.rank, b.rank, c.rank, d.rank] == [4, 3, 2, 1]:
                return True
    return False


def tail3_packets(state: SpiderState, suit: str) -> List[dict]:
    out = []
    actions, _ = engine_tableau_actions(state)
    for col, column in enumerate(state.columns):
        up = column.face_up
        for i in range(len(up) - 2):
            a, b, c = up[i], up[i + 1], up[i + 2]
            if not (a.suit == b.suit == c.suit == suit and [a.rank, b.rank, c.rank] == [3, 2, 1]):
                continue
            above = up[i + 3 :]
            exposed = not above
            movable = exposed and SpiderState.is_movable_run(up[i : i + 3])
            dests = [act[1] for act in actions if act[0] == col and act[2] == 3] if movable else []
            out.append(
                {
                    "column_0": col,
                    "exposed": exposed,
                    "movable": movable,
                    "dests_1": [d + 1 for d in dests],
                }
            )
    return out


def tail4_ready(state: SpiderState, suit: str) -> bool:
    packets = tail3_packets(state, suit)
    fours = rank_cards(state, suit, 4)
    exposed_4 = {t["column_0"] for t in fours if t["top"]}
    for p in packets:
        if not p["movable"]:
            continue
        for dst in exposed_4:
            if dst == p["column_0"]:
                continue
            top = state.columns[dst].top()
            if top is None or top.suit != suit or top.rank != 4:
                continue
            if state.can_move(p["column_0"], dst, 3):
                return True
    return False


def obstacle_class(state: SpiderState, suit: str) -> str:
    if tail3_already(state, suit):
        return "TAIL3_ALREADY_PRESENT"
    if tail3_ready(state, suit):
        return "TAIL3_READY"
    packets = two_a_packets(state, suit)
    threes = rank_cards(state, suit, 3)
    pkt_ok = any(p["movable"] for p in packets)
    three_ok = any(t["top"] for t in threes)
    if pkt_ok and not three_ok:
        return "PACKET_READY_3_BLOCKED"
    if three_ok and not pkt_ok:
        return "PACKET_BLOCKED_3_READY"
    return "BOTH_BLOCKED"


def legal_tail3_joins(state: SpiderState, suit: str) -> List[Action]:
    out = []
    for p in two_a_packets(state, suit):
        if not p["movable"]:
            continue
        for dst in range(10):
            if dst == p["column_0"]:
                continue
            top = state.columns[dst].top()
            if top is None or top.suit != suit or top.rank != 3:
                continue
            if state.can_move(p["column_0"], dst, 2):
                out.append((p["column_0"], dst, 2))
    return out


def legal_tail4_joins(state: SpiderState, suit: str) -> List[Action]:
    out = []
    for p in tail3_packets(state, suit):
        if not p["movable"]:
            continue
        for dst in range(10):
            if dst == p["column_0"]:
                continue
            top = state.columns[dst].top()
            if top is None or top.suit != suit or top.rank != 4:
                continue
            if state.can_move(p["column_0"], dst, 3):
                out.append((p["column_0"], dst, 3))
    return out


def allowed_at_ready_level(label: str, tier: int, level: int) -> bool:
    if level >= 3:
        return True
    if level <= 0:
        return label in L0_LABELS
    if level == 1:
        return label in (L0_LABELS | L1_EXTRA) or tier <= int(Tier.B)
    if level == 2:
        return label != JOIN_BREAK
    return True


def _new_src_top(state: SpiderState, src: int, k: int):
    col = state.columns[src]
    if k < len(col.face_up):
        return col.face_up[-k - 1]
    if col.face_down:
        return col.face_down[-1]
    return None


def annotate_ready_action(state: SpiderState, action, suit: str, packets: List[dict], threes: List[dict]) -> str:
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
    new_top = _new_src_top(state, src, k)
    exposes_3 = new_top is not None and new_top.suit == suit and new_top.rank == 3
    movable_2a = any(p["movable"] for p in packets)
    exposed_3 = any(t["top"] for t in threes)
    mobilises = False
    for p in packets:
        if p["column_0"] == src and not p["movable"] and k == p["cards_above"]:
            mobilises = True
    if (exposes_3 and movable_2a) or (mobilises and exposed_3):
        return READY_CREATE
    if mobilises:
        return PACKET_MOBILISE
    if exposes_3:
        return EXPOSE_3
    if dest_top is not None and dest_top.suit == suit and head.suit == suit and dest_top.rank == head.rank + 1:
        return TARGET_JOIN
    hot_cols = {p["column_0"] for p in packets} | {t["column_0"] for t in threes}
    if src in hot_cols or dst in hot_cols:
        creates_empty = k == len(src_col.face_up) and not src_col.face_down
        if creates_empty or dest_empty:
            return LANDING_SUPPORT
        return LANDING_SUPPORT
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


def load_v044_deal_now_roots(opening: Optional[SpiderState] = None) -> dict:
    opening = opening or opening_state()
    raw = json.loads(V044_ROOTS.read_text(encoding="utf-8"))
    rows = list(raw.get("states") or [])
    fail = 0
    kept = []
    classes: Dict[bytes, dict] = {}
    for rec in rows:
        end = opening.clone()
        full = as_actions(rec["full_actions"])
        try:
            cost = replay_actions(end, full)
        except Exception:
            fail += 1
            continue
        ok = (
            cost == int(rec["g"])
            and stock_rows(end) == 0
            and len(end.foundations) == 1
            and end.foundations[0][0].suit == "s"
            and not end.stock
        )
        if not ok:
            fail += 1
            continue
        ident_ord = pack_state(end)
        ident_sym = pack_post_stock_symmetry_state(end)
        item = {
            "g": int(rec["g"]),
            "lineages": list(rec.get("lineages") or []),
            "full_actions": dump_actions(full),
            "ordered_digest": ident_ord.hex(),
            "symmetry_digest": ident_sym.hex(),
        }
        prev = classes.get(ident_sym)
        if prev is None or item["g"] < prev["g"]:
            classes[ident_sym] = item
        kept.append(item)
    unique = sorted(classes.values(), key=lambda r: (r["g"], r["ordered_digest"]))
    return {
        "raw": len(rows),
        "expected": EXPECTED_ROOTS,
        "replayed": len(kept),
        "symmetry_unique": len(unique),
        "replay_fail": fail,
        "all_replay_ok": fail == 0 and len(rows) == EXPECTED_ROOTS,
        "cost_counts": {str(k): int(v) for k, v in sorted(Counter(r["g"] for r in unique).items())},
        "states": unique,
        "reconstruct_n": None,
    }


def filter_2a_sources(roots: Sequence[dict], suit: str) -> dict:
    classes: Dict[bytes, dict] = {}
    raw = 0
    for rec in roots:
        st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
        if not edge_2a_present(st, suit, baseline=0):
            continue
        raw += 1
        ident = bytes.fromhex(rec["symmetry_digest"])
        prev = classes.get(ident)
        if prev is None or rec["g"] < prev["g"]:
            item = dict(rec)
            item["suit"] = suit
            item["obstacle"] = obstacle_class(st, suit)
            item["already_tail3"] = tail3_already(st, suit)
            item["already_ready"] = tail3_ready(st, suit)
            classes[ident] = item
    kept = sorted(classes.values(), key=lambda r: (r["g"], r["ordered_digest"]))
    return {
        "suit": suit,
        "raw": raw,
        "symmetry_unique": len(kept),
        "cost_counts": {str(k): int(v) for k, v in sorted(Counter(r["g"] for r in kept).items())},
        "obstacles": dict(Counter(r["obstacle"] for r in kept)),
        "already_ready": sum(1 for r in kept if r["already_ready"]),
        "already_tail3": sum(1 for r in kept if r["already_tail3"]),
        "states": kept,
    }


def structural_audit(sources: Sequence[dict], suit: str) -> dict:
    pkt_exposed = 0
    pkt_movable = 0
    pkt_buried = 0
    three_top = 0
    three_one_move = 0
    three_n = 0
    pkt_n = 0
    cats = Counter()
    for rec in sources:
        st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
        packets = two_a_packets(st, suit)
        threes = rank_cards(st, suit, 3)
        pkt_n += len(packets)
        three_n += len(threes)
        if any(p["exposed"] for p in packets):
            pkt_exposed += 1
        if any(p["movable"] for p in packets):
            pkt_movable += 1
        if packets and all(not p["exposed"] for p in packets):
            pkt_buried += 1
        if any(t["top"] for t in threes):
            three_top += 1
        if any(t["one_move_exposable"] for t in threes):
            three_one_move += 1
        cats[obstacle_class(st, suit)] += 1
    return {
        "suit": suit,
        "n": len(sources),
        "packets": pkt_n,
        "packet_exposed_sources": pkt_exposed,
        "packet_movable_sources": pkt_movable,
        "packet_all_buried_sources": pkt_buried,
        "rank3": three_n,
        "rank3_top_sources": three_top,
        "rank3_one_move_sources": three_one_move,
        "obstacles": dict(cats),
    }


def one_move_scan(sources: Sequence[dict], suit: str) -> dict:
    n_actions = 0
    ready_hits = []
    tail3_hits = []
    for origin, rec in enumerate(sources):
        st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
        g0 = int(rec["g"])
        if rec.get("already_ready") or tail3_ready(st, suit):
            continue
        for action in engine_tableau_actions(st)[0]:
            if action == ("deal",):
                continue
            n_actions += 1
            cost = step_cost(st, action)
            cap = _capture(st, action)
            try:
                apply_action(st, action)
                ready = tail3_ready(st, suit)
                t3 = tail3_already(st, suit)
                if not ready and not t3:
                    continue
                row = {
                    "origin": origin,
                    "g": g0 + cost,
                    "source_g": g0,
                    "depth": 1,
                    "actions": dump_actions([action]),
                    "full_actions": dump_actions(as_actions(rec["full_actions"]) + [action]),
                    "ordered_digest": pack_state(st).hex(),
                    "symmetry_digest": pack_post_stock_symmetry_state(st).hex(),
                    "ready": ready,
                    "tail3": t3,
                    "lineages": rec.get("lineages"),
                    "timing": rec.get("timing"),
                }
                if ready:
                    ready_hits.append(row)
                if t3:
                    tail3_hits.append(row)
            finally:
                _restore(st, cap)
    def _uniq(rows):
        by = {}
        for w in rows:
            prev = by.get(w["symmetry_digest"])
            if prev is None or w["g"] < prev["g"]:
                by[w["symmetry_digest"]] = w
        return sorted(by.values(), key=lambda w: (w["g"], w["origin"]))
    ru, tu = _uniq(ready_hits), _uniq(tail3_hits)
    return {
        "n_sources": len(sources),
        "n_actions": n_actions,
        "ready_n": len(ru),
        "tail3_n": len(tu),
        "ready_cheapest": None if not ru else ru[0]["g"],
        "tail3_cheapest": None if not tu else tu[0]["g"],
        "ready": ru,
        "tail3": tu,
    }


@dataclass
class ReadyResult:
    suit: str = ""
    unique: int = 0
    expanded: int = 0
    generated: int = 0
    duplicate_skips: int = 0
    elapsed_s: float = 0.0
    peak_rss_mb: Optional[float] = None
    stop_reason: str = ""
    deal_expanded: bool = False
    foundation_surprise: bool = False
    contract_fail: int = 0
    witnesses: List[dict] = field(default_factory=list)
    first_s: Optional[float] = None
    first_g: Optional[int] = None
    already: int = 0


def search_tail3_ready(
    sources: Sequence[dict],
    *,
    suit: str,
    max_unique: int = SEARCH_UNIQUE,
    time_limit_s: float = SEARCH_TIME_S,
    rss_abort_mb: float = SEARCH_RSS_MB,
    cost_ceiling: int = COST_CEILING,
) -> ReadyResult:
    started = time.perf_counter()
    deadline = started + time_limit_s
    result = ReadyResult(suit=suit)
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
    incumbent: Optional[int] = None

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
        if tail3_ready(st0, suit) or tail3_already(st0, suit):
            result.already += 1
            witnesses[ident_sym] = {
                "origin": origin,
                "g": g0,
                "source_g": g0,
                "depth": 0,
                "actions": [],
                "already": True,
                "ready": tail3_ready(st0, suit),
                "tail3": tail3_already(st0, suit),
                "ordered_digest": ident_ord.hex(),
                "symmetry_digest": ident_sym.hex(),
                "lineages": rec.get("lineages"),
                "obstacle": obstacle_class(st0, suit),
            }
            if incumbent is None or g0 < incumbent:
                incumbent = g0
                result.first_s = 0.0
                result.first_g = g0
    result.unique = len(best_g)
    print(f"{suit} READY start unique={result.unique} sources={len(sources)} already={result.already}", flush=True)

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
            if depth_of[node] > 0 and (tail3_ready(st, suit) or tail3_already(st, suit)):
                continue
            heapq.heappush(heap, (0, g_of[node], depth_of[node], seq, node))
            seq += 1
        seen_expand: Dict[bytes, int] = {}
        remaining_s = deadline - time.perf_counter()
        levels_left = 4 - level
        level_deadline = time.perf_counter() + max(10.0, remaining_s / max(1, levels_left))
        print(
            f"{suit} READY L{level} unique={result.unique} heap={len(heap)} inc={incumbent} "
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
            if result.expanded and result.expanded % 8192 == 0:
                print(
                    f"{suit} READY L{level} exp={result.expanded} unique={result.unique} inc={incumbent} "
                    f"wit={len(witnesses)} heap={len(heap)}",
                    flush=True,
                )
            _rk, _g, _d, _s, node = heapq.heappop(heap)
            ident_sym = ident_sym_of[node]
            g = g_of[node]
            depth = depth_of[node]
            if g != best_g.get(ident_sym) or g > cost_ceiling:
                continue
            if seen_expand.get(ident_sym, 10**9) <= g:
                continue
            seen_expand[ident_sym] = g
            state = unpack_state(ident_ord_of[node])
            if depth > 0 and (tail3_ready(state, suit) or tail3_already(state, suit)):
                continue
            if state.stock:
                result.deal_expanded = True
            packets = two_a_packets(state, suit)
            threes = rank_cards(state, suit, 3)
            parent_ready = tail3_ready(state, suit)
            actions, _ = engine_tableau_actions(state)
            ranked = []
            for action in actions:
                if action == ("deal",):
                    result.deal_expanded = True
                    continue
                label = annotate_ready_action(state, action, suit, packets, threes)
                tier_i = int(classify_tier(state, action))
                if not allowed_at_ready_level(label, tier_i, level):
                    continue
                ranked.append((LABEL_RANK.get(label, 8), action, label))
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
                    ready = tail3_ready(state, suit)
                    t3 = tail3_already(state, suit)
                    foundation = suit_foundation_count(state, suit) > 0
                    if t3 and not parent_ready and not tail3_already(unpack_state(ident_ord_of[node]), suit):
                        result.contract_fail += 1
                    if foundation:
                        result.foundation_surprise = True
                    if ready or t3 or foundation:
                        src = sources[origin_of[node]]
                        rec_w = {
                            "origin": origin_of[node],
                            "g": child_g,
                            "source_g": int(src["g"]),
                            "depth": depth + 1,
                            "actions": dump_actions(reconstruct(child_node)),
                            "ordered_digest": child_ord.hex(),
                            "symmetry_digest": child_sym.hex(),
                            "ready": ready,
                            "tail3": t3,
                            "foundation": foundation,
                            "label": label,
                            "lineages": src.get("lineages"),
                            "obstacle": obstacle_class(state, suit),
                            "fd": face_down_count(state),
                            "empties": [i + 1 for i in empty_column_indices(state)],
                        }
                        if child_sym not in witnesses or child_g < witnesses[child_sym]["g"]:
                            witnesses[child_sym] = rec_w
                        if result.first_s is None:
                            result.first_s = time.perf_counter() - started
                            result.first_g = child_g
                            print(
                                f"FIRST_{suit}_READY g={child_g} unique={result.unique} "
                                f"t={result.first_s:.2f}s ready={ready} tail3={t3}",
                                flush=True,
                            )
                        if incumbent is None or child_g < incumbent:
                            incumbent = child_g
                        continue
                    heapq.heappush(heap, (LABEL_RANK.get(label, 8), child_g, depth + 1, seq, child_node))
                    seq += 1
                finally:
                    _restore(state, cap)
            if result.stop_reason in ("unique limit", "time limit", "rss abort"):
                break
        if result.stop_reason in ("unique limit", "time limit", "rss abort"):
            break
        if witnesses and (deadline - time.perf_counter()) < 6:
            result.stop_reason = result.stop_reason or "harvested"
            break
    if not result.stop_reason:
        result.stop_reason = "complete"
    rows = [w for w in witnesses.values() if w.get("ready") or w.get("tail3")]
    kept = harvest_rows(
        rows,
        limit=HARVEST_LIMIT,
        keyfn=lambda w: (
            w.get("source_g"),
            tuple(w.get("lineages") or []),
            w.get("obstacle"),
            bool(w.get("already")),
            w.get("fd"),
            tuple(w.get("empties") or []),
        ),
    )
    result.witnesses = kept
    result.elapsed_s = time.perf_counter() - started
    result.peak_rss_mb = peak
    return result


def execute_tail3_joins(sources: Sequence[dict], ready_rows: Sequence[dict], suit: str, opening: SpiderState) -> List[dict]:
    hits = []
    for rec in ready_rows:
        st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
        g0 = int(rec["g"])
        full0 = as_actions(rec.get("full_actions") or [])
        if not full0:
            origin = rec.get("origin", 0)
            if 0 <= origin < len(sources):
                full0 = as_actions(sources[origin]["full_actions"]) + as_actions(rec.get("actions") or [])
        if tail3_already(st, suit):
            hits.append(
                {
                    **{k: rec.get(k) for k in ("origin", "source_g", "lineages")},
                    "g": g0,
                    "full_actions": dump_actions(full0),
                    "ordered_digest": rec["ordered_digest"],
                    "symmetry_digest": rec["symmetry_digest"],
                    "already": True,
                    "join": None,
                    "suit": suit,
                }
            )
            continue
        for action in legal_tail3_joins(st, suit):
            cost = step_cost(st, action)
            cap = _capture(st, action)
            try:
                apply_action(st, action)
                if tail3_already(st, suit):
                    hits.append(
                        {
                            "origin": rec.get("origin"),
                            "g": g0 + cost,
                            "source_g": rec.get("source_g"),
                            "full_actions": dump_actions(full0 + [action]),
                            "ordered_digest": pack_state(st).hex(),
                            "symmetry_digest": pack_post_stock_symmetry_state(st).hex(),
                            "already": False,
                            "join": dump_actions([action])[0],
                            "lineages": rec.get("lineages"),
                            "suit": suit,
                        }
                    )
            finally:
                _restore(st, cap)
    by = {}
    for w in hits:
        prev = by.get(w["symmetry_digest"])
        if prev is None or w["g"] < prev["g"]:
            by[w["symmetry_digest"]] = w
    return sorted(by.values(), key=lambda w: (w["g"], w.get("origin") or 0))


def preview_tail4_ready(state: SpiderState, g0: int, suit: str, *, max_depth: int = PREVIEW_DEPTH, deadline: float) -> dict:
    if tail4_ready(state, suit):
        return {"status": "TAIL4_READY_IMMEDIATE", "dead": False, "live": False, "g": g0, "unique": 1, "hit": {"g": g0, "depth": 0}}
    ident0 = pack_post_stock_symmetry_state(state)
    ord0 = pack_state(state)
    best = {ident0: g0}
    heap = [(g0, 0, 0, ident0, ord0)]
    seq = 0
    seen: Dict[bytes, int] = {}
    unique = 1
    live = False
    found = None
    while heap:
        if time.perf_counter() >= deadline:
            live = True
            break
        if unique >= PREVIEW_UNIQUE:
            live = True
            break
        g, depth, _, ident, ident_ord = heapq.heappop(heap)
        if g != best.get(ident):
            continue
        if seen.get(ident, 10**9) <= g:
            continue
        if depth >= max_depth:
            live = True
            continue
        seen[ident] = g
        st = unpack_state(ident_ord)
        for action in engine_tableau_actions(st)[0]:
            if action == ("deal",):
                continue
            cost = step_cost(st, action)
            cap = _capture(st, action)
            try:
                apply_action(st, action)
                child_ord = pack_state(st)
                child_sym = pack_post_stock_symmetry_state(st)
                child_g = g + cost
                prev = best.get(child_sym)
                if prev is not None and child_g >= prev:
                    continue
                best[child_sym] = child_g
                if prev is None:
                    unique += 1
                if tail4_ready(st, suit):
                    found = {"g": child_g, "depth": depth + 1, "ordered_digest": child_ord.hex()}
                    break
                seq += 1
                heapq.heappush(heap, (child_g, depth + 1, seq, child_sym, child_ord))
            finally:
                _restore(st, cap)
        if found:
            break
    if found:
        status = "TAIL4_READY_IMMEDIATE" if found["depth"] <= 1 else "TAIL4_READY_WITHIN_5"
        return {"status": status, "dead": False, "live": False, "unique": unique, "hit": found, "g": found["g"]}
    if live or heap:
        return {"status": "LIVE_BEYOND_5", "dead": False, "live": True, "unique": unique, "hit": None}
    return {"status": "EXACT_DEAD_TO_TAIL4_READY", "dead": True, "live": False, "unique": unique, "hit": None}


def optional_tail4_join(state: SpiderState, g0: int, suit: str) -> Optional[dict]:
    if not tail4_ready(state, suit):
        return None
    for action in legal_tail4_joins(state, suit):
        cost = step_cost(state, action)
        cap = _capture(state, action)
        try:
            apply_action(state, action)
            if tail4_present(state, suit):
                return {
                    "g": g0 + cost,
                    "join": dump_actions([action])[0],
                    "ordered_digest": pack_state(state).hex(),
                    "symmetry_digest": pack_post_stock_symmetry_state(state).hex(),
                }
        finally:
            _restore(state, cap)
    return None
