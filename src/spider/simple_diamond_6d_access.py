"""Research-only v0.52 Diamond 6D access cut.

From v0.51 visible 5D-4D-3D-2D-AD states, search first D6_EXPOSED.
TAIL5 may split.  Canonical identity is post-stock symmetry.
Do not search TAIL6 until 6D is exposed.  Do not search Spades/Clubs/Hearts,
Foundation 3, or rank 8+.
"""

from __future__ import annotations

import heapq
import json
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from spider.cards import Card
from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state, unpack_state
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
from spider.simple_low_tail import (
    FOUNDATION_AUTO_REMOVED,
    LOW_TAIL_PERSISTS,
    classify_low_tail_transition,
    k_through_n,
    legal_tail_joins,
    rank_cards,
    receiving_upper_run,
    synthetic_columns,
    tail_packets,
    tail_present,
    tail_ready,
    tail_run,
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
from spider.simple_spade_final_access import harvest_rows
from spider.simple_workspace_reachability import empty_column_indices, engine_tableau_actions, face_down_count

ROOT = Path(__file__).resolve().parents[2]
V051_T5 = ROOT / "docs" / "research" / "diamond_tail5_v0_51.json"
EXPECTED_RAW = 199
COST_CEILING = 102
SEARCH_UNIQUE = 180_000
SEARCH_TIME_S = 240.0
SEARCH_RSS_MB = 2.0 * 1024.0
HARVEST_LIMIT = 192
PREVIEW4_UNIQUE = 800
PREVIEW5_UNIQUE = 800

D6_EXPOSE = "D6_EXPOSE"
UNBLOCK_6 = "UNBLOCK_6"
LANDING_SUPPORT = "LANDING_SUPPORT"
TARGET_JOIN = "TARGET_JOIN"
AB_QUALITY = "AB_QUALITY"

L0_LABELS = {D6_EXPOSE, UNBLOCK_6, LANDING_SUPPORT, TARGET_JOIN, GOOD_PLAY}
L1_EXTRA = {AB_QUALITY, PARK}

LABEL_RANK = {
    D6_EXPOSE: 0,
    UNBLOCK_6: 1,
    LANDING_SUPPORT: 2,
    TARGET_JOIN: 3,
    GOOD_PLAY: 4,
    AB_QUALITY: 5,
    PARK: 6,
    OTHER: 7,
    JOIN_BREAK: 8,
    "DEAL": 9,
}


def d6_exposed(state: SpiderState) -> bool:
    """True iff at least one physical 6D is face-up and top/exposed."""

    return any(t["top"] and t["face_up"] for t in rank_cards(state, "d", 6))


def receiving_upper_run_at(state: SpiderState, dst: int, up_index: int, suit: str, top_rank: int) -> dict:
    """Contiguous same-suit increasing ranks sitting under card `up_index`."""

    up = state.columns[dst].face_up
    if up_index < 0 or up_index >= len(up) or up[up_index].suit != suit or up[up_index].rank != top_rank:
        return {"length": 0, "ranks": [], "label": "none", "k_through": False, "top_rank": top_rank}
    ranks = [top_rank]
    i = up_index - 1
    expect = top_rank + 1
    while i >= 0 and expect <= 13 and up[i].suit == suit and up[i].rank == expect:
        ranks.append(expect)
        expect += 1
        i -= 1
    ranks.reverse()
    n = len(ranks)
    k_through = n == (13 - top_rank + 1) and ranks[0] == 13
    if n == 1:
        label = f"{top_rank} only"
    else:
        label = "-".join(str(r) if r <= 10 else {11: "J", 12: "Q", 13: "K"}[r] for r in ranks)
        if k_through:
            label = f"K_THROUGH_{top_rank}"
    return {
        "length": n,
        "ranks": ranks,
        "label": label,
        "k_through": k_through,
        "k_through_6": k_through and top_rank == 6,
        "cards": [pretty_card(c) for c in up[up_index - n + 1 : up_index + 1]],
        "dst_1": dst + 1,
        "top_rank": top_rank,
    }


def six_d_copies(state: SpiderState) -> List[dict]:
    """Audit both physical 6D copies. Neither copy is preferred a priori."""

    copies = rank_cards(state, "d", 6)
    for t in copies:
        col = state.columns[t["column_0"]]
        t["flip_required"] = not bool(t["face_up"])
        t["covering_packet"] = list(t.get("above") or [])
        t["covering_movable"] = bool(t.get("one_move_exposable"))
        t["covering_dests_1"] = list(t.get("cover_dests_1") or [])
        if t["face_up"]:
            up_index = len(col.face_up) - 1 - int(t["cards_above"])
            t["upper_run"] = receiving_upper_run_at(state, t["column_0"], up_index, "d", 6)
        else:
            t["upper_run"] = {"label": "face_down", "k_through": False, "length": 0, "ranks": []}
        t["k_through_6"] = bool(t["upper_run"].get("k_through"))
    return copies


def must_cross_d6_exposed() -> str:
    return (
        "The action which first creates 6D-5D-4D-3D-2D-AD must legally move a "
        "5D-4D-3D-2D-AD packet onto an exposed 6D. Immediately before that action "
        "at least one physical 6D is face-up and top: D6_EXPOSED."
    )


def source_category(state: SpiderState) -> str:
    copies = six_d_copies(state)
    if any(t["top"] and t["face_up"] for t in copies):
        return "D6_ALREADY_EXPOSED"
    if any(t["one_move_exposable"] for t in copies):
        return "D6_ONE_MOVE_EXPOSABLE"
    if copies and all(not t["face_up"] for t in copies):
        return "D6_FACE_DOWN"
    return "D6_MULTI_MOVE_ACCESS"


def min_6d_depth(state: SpiderState) -> int:
    copies = six_d_copies(state)
    if not copies:
        return 10**9
    return min(int(t["cards_above"]) for t in copies)


def allowed_at_d6_level(label: str, tier: int, level: int) -> bool:
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


def annotate_d6_action(state: SpiderState, action, copies: List[dict]) -> str:
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
    exposes = new_top is not None and new_top.suit == "d" and new_top.rank == 6
    six_cols = {t["column_0"] for t in copies}
    if exposes:
        return D6_EXPOSE
    if src in six_cols:
        return UNBLOCK_6
    if dest_top is not None and dest_top.suit == "d" and head.suit == "d" and dest_top.rank == head.rank + 1:
        return TARGET_JOIN
    if src in six_cols or dst in six_cols:
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


def load_tail5_sources(opening: Optional[SpiderState] = None) -> dict:
    opening = opening or opening_state()
    raw = json.loads(V051_T5.read_text(encoding="utf-8"))
    rows = [
        rec
        for rec in list(raw.get("states") or [])
        if rec.get("persist_name") == "TAIL5_PERSISTS"
        or rec.get("report_class") == "TAIL5_PERSISTS"
        or rec.get("class") in ("TAIL5_PERSISTS", "LOW_TAIL_PERSISTS")
    ]
    fail = 0
    classes: Dict[bytes, dict] = {}
    for rec in rows:
        end = opening.clone()
        try:
            cost = replay_actions(end, as_actions(rec["full_actions"]))
        except Exception:
            fail += 1
            continue
        ok = (
            cost == int(rec["g"])
            and stock_rows(end) == 0
            and len(end.foundations) == 1
            and end.foundations[0][0].suit == "s"
            and suit_foundation_count(end, "d") == 0
            and tail_present(end, "d", 5)
        )
        if not ok:
            fail += 1
            continue
        ident_ord = pack_state(end)
        ident_sym = pack_post_stock_symmetry_state(end)
        copies = six_d_copies(end)
        packets = tail_packets(end, "d", 5)
        item = {
            "g": int(rec["g"]),
            "source_g": rec.get("source_g"),
            "full_actions": dump_actions(as_actions(rec["full_actions"])),
            "ordered_digest": ident_ord.hex(),
            "symmetry_digest": ident_sym.hex(),
            "category": source_category(end),
            "min_depth": min_6d_depth(end),
            "already_exposed": d6_exposed(end),
            "tail5_movable": any(p["movable"] for p in packets),
            "tail5_exposed": any(p["exposed"] for p in packets),
            "used_cols_1": [t["column_1"] for t in copies if t["top"] and t["face_up"]],
            "copies": copies,
            "packets": packets,
        }
        prev = classes.get(ident_sym)
        if prev is None or item["g"] < prev["g"]:
            classes[ident_sym] = item
    kept = sorted(classes.values(), key=lambda r: (r["g"], r["ordered_digest"]))
    return {
        "raw": len(rows),
        "expected": EXPECTED_RAW,
        "replay_fail": fail,
        "all_replay_ok": fail == 0 and len(rows) == EXPECTED_RAW,
        "symmetry_unique": len(kept),
        "cost_counts": {str(k): int(v) for k, v in sorted(Counter(r["g"] for r in kept).items())},
        "categories": dict(Counter(r["category"] for r in kept)),
        "already_exposed": sum(1 for r in kept if r["already_exposed"]),
        "replay_count": len(rows) - fail,
        "states": kept,
    }


def structural_audit(sources: Sequence[dict]) -> dict:
    pkt_exp = pkt_mov = 0
    six_n = 0
    six_top = six_one = six_down = 0
    depths = Counter()
    uppers = Counter()
    k6 = 0
    cats = Counter()
    sigs = Counter()
    for rec in sources:
        st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
        packets = tail_packets(st, "d", 5)
        copies = six_d_copies(st)
        cats[source_category(st)] += 1
        if any(p["exposed"] for p in packets):
            pkt_exp += 1
        if any(p["movable"] for p in packets):
            pkt_mov += 1
        six_n += len(copies)
        if any(t["top"] and t["face_up"] for t in copies):
            six_top += 1
        if any(t["one_move_exposable"] for t in copies):
            six_one += 1
        if copies and all(not t["face_up"] for t in copies):
            six_down += 1
        for t in copies:
            depths[t["cards_above"]] += 1
            if t["top"] and t["face_up"]:
                uppers[t["upper_run"]["label"]] += 1
                if t["k_through_6"]:
                    k6 += 1
            sigs[(t["face_up"], t["cards_above"], tuple((t.get("above") or [])[:3]))] += 1
    return {
        "n": len(sources),
        "tail5_exposed_sources": pkt_exp,
        "tail5_movable_sources": pkt_mov,
        "six_n": six_n,
        "six_top_sources": six_top,
        "six_one_move_sources": six_one,
        "six_face_down_sources": six_down,
        "six_depth": {str(k): int(v) for k, v in sorted(depths.items())},
        "upper_runs": dict(uppers),
        "k_through_6": k6,
        "categories": dict(cats),
        "signatures": {str(k): int(v) for k, v in sigs.most_common(12)},
    }


def one_move_scan(sources: Sequence[dict]) -> dict:
    n_actions = 0
    hits = []
    f2 = []
    for origin, rec in enumerate(sources):
        st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
        g0 = int(rec["g"])
        before = len(st.foundations)
        for action in engine_tableau_actions(st)[0]:
            if action == ("deal",):
                continue
            n_actions += 1
            cost = step_cost(st, action)
            cap = _capture(st, action)
            try:
                apply_action(st, action)
                if len(st.foundations) > before:
                    f2.append({"origin": origin, "g": g0 + cost, "suits": [r[0].suit for r in st.foundations]})
                if rec.get("already_exposed"):
                    continue
                if d6_exposed(st):
                    copies = six_d_copies(st)
                    used = [t["column_1"] for t in copies if t["top"]]
                    hits.append(
                        {
                            "origin": origin,
                            "g": g0 + cost,
                            "source_g": g0,
                            "depth": 1,
                            "actions": dump_actions([action]),
                            "full_actions": dump_actions(as_actions(rec["full_actions"]) + [action]),
                            "ordered_digest": pack_state(st).hex(),
                            "symmetry_digest": pack_post_stock_symmetry_state(st).hex(),
                            "used_cols_1": used,
                            "tail5": any(p["movable"] for p in tail_packets(st, "d", 5)),
                            "min_depth_src": rec.get("min_depth"),
                            "fd": face_down_count(st),
                            "empties": [i + 1 for i in empty_column_indices(st)],
                            "upper_run": next((t["upper_run"]["label"] for t in copies if t["top"]), None),
                            "exposed": True,
                        }
                    )
            finally:
                _restore(st, cap)
    by = {}
    for w in hits:
        prev = by.get(w["symmetry_digest"])
        if prev is None or w["g"] < prev["g"]:
            by[w["symmetry_digest"]] = w
    kept = sorted(by.values(), key=lambda w: (w["g"], w["origin"]))
    return {
        "n_actions": n_actions,
        "hit_n": len(kept),
        "cheapest": None if not kept else kept[0]["g"],
        "f2_n": len(f2),
        "hits": kept,
        "f2": f2,
    }


@dataclass
class D6Result:
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
    f2_hits: List[dict] = field(default_factory=list)
    first_s: Optional[float] = None
    first_g: Optional[int] = None
    already: int = 0


def search_d6_exposed(
    sources: Sequence[dict],
    *,
    max_unique: int = SEARCH_UNIQUE,
    time_limit_s: float = SEARCH_TIME_S,
    rss_abort_mb: float = SEARCH_RSS_MB,
    cost_ceiling: int = COST_CEILING,
) -> D6Result:
    started = time.perf_counter()
    deadline = started + time_limit_s
    result = D6Result()
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
        if d6_exposed(st0):
            result.already += 1
            copies = six_d_copies(st0)
            witnesses[ident_sym] = {
                "origin": origin,
                "g": g0,
                "source_g": g0,
                "depth": 0,
                "actions": [],
                "already": True,
                "exposed": True,
                "used_cols_1": [t["column_1"] for t in copies if t["top"]],
                "tail5": any(p["movable"] for p in tail_packets(st0, "d", 5)),
                "ordered_digest": ident_ord.hex(),
                "symmetry_digest": ident_sym.hex(),
                "min_depth_src": rec.get("min_depth"),
                "fd": face_down_count(st0),
                "empties": [i + 1 for i in empty_column_indices(st0)],
                "upper_run": next((t["upper_run"]["label"] for t in copies if t["top"]), None),
            }
            if incumbent is None or g0 < incumbent:
                incumbent = g0
                result.first_s = 0.0
                result.first_g = g0
    result.unique = len(best_g)
    print(f"D6 start unique={result.unique} already={result.already}", flush=True)

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
            if d6_exposed(st):
                continue
            heapq.heappush(heap, (0, g_of[node], depth_of[node], seq, node))
            seq += 1
        seen_expand: Dict[bytes, int] = {}
        remaining_s = deadline - time.perf_counter()
        levels_left = 4 - level
        level_deadline = time.perf_counter() + max(12.0, remaining_s / max(1, levels_left))
        print(
            f"D6 L{level} unique={result.unique} heap={len(heap)} inc={incumbent} "
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
                    f"D6 L{level} exp={result.expanded} unique={result.unique} inc={incumbent} "
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
            if d6_exposed(state):
                continue
            if state.stock:
                result.deal_expanded = True
            copies = six_d_copies(state)
            before_n = len(state.foundations)
            actions, _ = engine_tableau_actions(state)
            ranked = []
            for action in actions:
                if action == ("deal",):
                    result.deal_expanded = True
                    continue
                label = annotate_d6_action(state, action, copies)
                tier_i = int(classify_tier(state, action))
                if not allowed_at_d6_level(label, tier_i, level):
                    continue
                ranked.append((LABEL_RANK.get(label, 7), action, label))
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
                    exposed = d6_exposed(state)
                    f2 = len(state.foundations) > before_n
                    if f2:
                        result.foundation_surprise = True
                        src = sources[origin_of[node]]
                        result.f2_hits.append(
                            {
                                "origin": origin_of[node],
                                "g": child_g,
                                "actions": dump_actions(reconstruct(child_node)),
                                "full_actions": dump_actions(as_actions(src["full_actions"]) + reconstruct(child_node)),
                                "ordered_digest": child_ord.hex(),
                                "symmetry_digest": child_sym.hex(),
                                "suits": [r[0].suit for r in state.foundations],
                            }
                        )
                    if exposed or f2:
                        src = sources[origin_of[node]]
                        child_copies = six_d_copies(state)
                        used = [t["column_1"] for t in child_copies if t["top"]]
                        rec_w = {
                            "origin": origin_of[node],
                            "g": child_g,
                            "source_g": int(src["g"]),
                            "depth": depth + 1,
                            "actions": dump_actions(reconstruct(child_node)),
                            "ordered_digest": child_ord.hex(),
                            "symmetry_digest": child_sym.hex(),
                            "exposed": exposed,
                            "foundation": f2,
                            "used_cols_1": used,
                            "tail5": any(p["movable"] for p in tail_packets(state, "d", 5)),
                            "min_depth_src": src.get("min_depth"),
                            "label": label,
                            "fd": face_down_count(state),
                            "empties": [i + 1 for i in empty_column_indices(state)],
                            "upper_run": next((t["upper_run"]["label"] for t in child_copies if t["top"]), None),
                        }
                        if child_sym not in witnesses or child_g < witnesses[child_sym]["g"]:
                            witnesses[child_sym] = rec_w
                        if result.first_s is None:
                            result.first_s = time.perf_counter() - started
                            result.first_g = child_g
                            print(
                                f"FIRST_D6 g={child_g} unique={result.unique} t={result.first_s:.2f}s "
                                f"exp={exposed} f2={f2}",
                                flush=True,
                            )
                        if incumbent is None or child_g < incumbent:
                            incumbent = child_g
                        continue
                    heapq.heappush(heap, (LABEL_RANK.get(label, 7), child_g, depth + 1, seq, child_node))
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
    rows = [w for w in witnesses.values() if w.get("exposed")]
    kept = harvest_d6_portfolio(rows, limit=HARVEST_LIMIT)
    result.witnesses = kept
    result.elapsed_s = time.perf_counter() - started
    result.peak_rss_mb = peak
    return result


def harvest_d6_portfolio(rows: Sequence[dict], *, limit: int = HARVEST_LIMIT) -> List[dict]:
    """Retain E6..E6+3 with diversity across both physical 6D copies."""

    return harvest_rows(
        list(rows),
        limit=limit,
        keyfn=lambda w: (
            tuple(w.get("used_cols_1") or []),
            w.get("source_g"),
            w.get("tail5"),
            w.get("min_depth_src"),
            w.get("fd"),
            tuple(w.get("empties") or []),
            w.get("upper_run"),
        ),
    )


def reconstruct_ready_preview(rec: dict, *, target_k: int, max_depth: int, max_unique: int) -> dict:
    st0 = unpack_state(bytes.fromhex(rec["ordered_digest"]))
    g0 = int(rec["g"])
    prefix = as_actions(rec.get("full_actions") or [])
    if tail_ready(st0, "d", target_k):
        return {
            "status": "READY_AT_SOURCE" if target_k != 6 else "TAIL6_READY_AT_EXPOSURE",
            "g": g0,
            "depth": 0,
            "actions": [],
            "full_actions": dump_actions(prefix),
            "ordered_digest": rec["ordered_digest"],
            "symmetry_digest": rec["symmetry_digest"],
            "source_g": g0,
        }
    ident0 = pack_post_stock_symmetry_state(st0)
    ord0 = pack_state(st0)
    best = {ident0: g0}
    parent: Dict[bytes, Optional[bytes]] = {ident0: None}
    action_of: Dict[bytes, Optional[Action]] = {ident0: None}
    ord_of = {ident0: ord0}
    heap = [(g0, 0, 0, ident0)]
    seq = 0
    seen: Dict[bytes, int] = {}
    unique = 1
    live = False
    found = None
    while heap:
        if unique >= max_unique:
            live = True
            break
        g, depth, _, ident = heapq.heappop(heap)
        if g != best.get(ident) or seen.get(ident, 10**9) <= g:
            continue
        if depth >= max_depth:
            live = True
            continue
        seen[ident] = g
        st = unpack_state(ord_of[ident])
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
                parent[child_sym] = ident
                action_of[child_sym] = action
                ord_of[child_sym] = child_ord
                if prev is None:
                    unique += 1
                if tail_ready(st, "d", target_k):
                    found = {"g": child_g, "depth": depth + 1, "sym": child_sym}
                    break
                seq += 1
                heapq.heappush(heap, (child_g, depth + 1, seq, child_sym))
            finally:
                _restore(st, cap)
        if found:
            break
    if found:
        path: List[Action] = []
        cur = found["sym"]
        while parent.get(cur) is not None:
            act = action_of[cur]
            if act is not None:
                path.append(act)
            cur = parent[cur]
        path.reverse()
        if target_k == 6:
            status = "TAIL6_READY_AT_EXPOSURE" if found["depth"] == 0 else "TAIL6_READY_WITHIN_4"
        else:
            status = "READY_AT_SOURCE" if found["depth"] == 0 else "READY_WITHIN_5"
        return {
            "status": status,
            "g": found["g"],
            "depth": found["depth"],
            "actions": dump_actions(path),
            "full_actions": dump_actions(prefix + path),
            "ordered_digest": ord_of[found["sym"]].hex(),
            "symmetry_digest": found["sym"].hex(),
            "source_g": g0,
        }
    if live or heap:
        status = "LIVE_BEYOND_4" if target_k == 6 else "LIVE_BEYOND_5"
        return {"status": status, "g": None, "depth": None, "actions": [], "source_g": g0}
    status = "EXACT_DEAD_TO_TAIL6_READY" if target_k == 6 else "EXACT_DEAD_TO_TAIL7_READY"
    return {"status": status, "g": None, "depth": None, "actions": [], "source_g": g0}
