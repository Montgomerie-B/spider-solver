"""Research-only v0.51 Club vs Diamond TAIL5_READY race.

From v0.50 TAIL4_PERSISTS states (visible 4-3-2-A), search the first
TAIL5_READY crossing, then join 4-3-2-A onto 5 with the generic low-tail
classifier.  Canonical identity is post-stock symmetry.  Do not search
Spades, Hearts, Foundation 3, or rank 7+.
"""

from __future__ import annotations

import heapq
import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state, unpack_state
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, dump_actions, opening_state
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
    classify_all_joins,
    classify_low_tail_transition,
    legal_tail_joins,
    must_cross_tail_ready,
    rank_cards,
    receiving_upper_run,
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
CLUB_T4 = ROOT / "docs" / "research" / "club_tail4_transition_v0_50.json"
DIA_T4 = ROOT / "docs" / "research" / "diamond_tail4_transition_v0_50.json"
EXPECTED_CLUB = 96
EXPECTED_DIA = 125
COST_CEILING = 100
SEARCH_UNIQUE = 160_000
SEARCH_TIME_S = 180.0
SEARCH_RSS_MB = 1.5 * 1024.0
HARVEST_LIMIT = 192
PREVIEW_DEPTH = 5
PREVIEW_UNIQUE = 800

READY_CREATE = "READY_CREATE"
EXPOSE_5 = "EXPOSE_5"
PACKET_MOBILISE = "PACKET_MOBILISE"
LANDING_SUPPORT = "LANDING_SUPPORT"
TARGET_JOIN = "TARGET_JOIN"
AB_QUALITY = "AB_QUALITY"

L0_LABELS = {READY_CREATE, EXPOSE_5, PACKET_MOBILISE, LANDING_SUPPORT, TARGET_JOIN, GOOD_PLAY}
L1_EXTRA = {AB_QUALITY, PARK}

LABEL_RANK = {
    READY_CREATE: 0,
    EXPOSE_5: 1,
    PACKET_MOBILISE: 2,
    LANDING_SUPPORT: 3,
    TARGET_JOIN: 4,
    GOOD_PLAY: 5,
    AB_QUALITY: 6,
    PARK: 7,
    OTHER: 8,
    JOIN_BREAK: 9,
    "DEAL": 10,
}


def tail5_ready(state: SpiderState, suit: str) -> bool:
    return tail_ready(state, suit, 5)


def tail5_present(state: SpiderState, suit: str) -> bool:
    return tail_present(state, suit, 5)


def tail6_ready(state: SpiderState, suit: str) -> bool:
    return tail_ready(state, suit, 6)


def tail6_present(state: SpiderState, suit: str) -> bool:
    return tail_present(state, suit, 6)


def tail4_present(state: SpiderState, suit: str) -> bool:
    return tail_present(state, suit, 4)


def source_category(state: SpiderState, suit: str) -> str:
    if tail5_ready(state, suit):
        return "TAIL5_READY_AT_SOURCE"
    packets = tail_packets(state, suit, 4)
    fives = rank_cards(state, suit, 5)
    pkt_ok = any(p["movable"] for p in packets)
    five_ok = any(t["top"] for t in fives)
    if not pkt_ok and not five_ok:
        return "BOTH_BLOCKED"
    if not pkt_ok:
        return "TAIL4_PACKET_BLOCKED"
    if not five_ok:
        return "FIVE_BLOCKED"
    return "BOTH_BLOCKED"


def allowed_at_tail5_level(label: str, tier: int, level: int) -> bool:
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


def annotate_tail5_action(state: SpiderState, action, suit: str, packets: List[dict], fives: List[dict]) -> str:
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
    exposes_5 = new_top is not None and new_top.suit == suit and new_top.rank == 5
    movable = any(p["movable"] for p in packets)
    five_top = any(t["top"] for t in fives)
    mobilises = False
    for p in packets:
        if p["column_0"] == src and not p["movable"] and k == p["cards_above"]:
            mobilises = True
    if (exposes_5 and movable) or (mobilises and five_top):
        return READY_CREATE
    if exposes_5:
        return EXPOSE_5
    if mobilises:
        return PACKET_MOBILISE
    if dest_top is not None and dest_top.suit == suit and head.suit == suit and dest_top.rank == head.rank + 1:
        return TARGET_JOIN
    hot = {p["column_0"] for p in packets} | {t["column_0"] for t in fives}
    if src in hot or dst in hot:
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


def load_tail4_persists(path: Path, opening: SpiderState, suit: str, expected: int) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = [t for t in (raw.get("transitions") or []) if t.get("class") == "TAIL4_PERSISTS"]
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
            and suit_foundation_count(end, suit) == 0
            and tail4_present(end, suit)
        )
        if not ok:
            fail += 1
            continue
        ident_ord = pack_state(end)
        ident_sym = pack_post_stock_symmetry_state(end)
        item = {
            "g": int(rec["g"]),
            "source_g": rec.get("source_g"),
            "full_actions": dump_actions(as_actions(rec["full_actions"])),
            "ordered_digest": ident_ord.hex(),
            "symmetry_digest": ident_sym.hex(),
            "suit": suit,
            "category": source_category(end, suit),
            "already_ready": tail5_ready(end, suit),
        }
        prev = classes.get(ident_sym)
        if prev is None or item["g"] < prev["g"]:
            classes[ident_sym] = item
    kept = sorted(classes.values(), key=lambda r: (r["g"], r["ordered_digest"]))
    return {
        "raw": len(rows),
        "expected": expected,
        "replay_fail": fail,
        "all_replay_ok": fail == 0 and len(rows) == expected,
        "symmetry_unique": len(kept),
        "cost_counts": {str(k): int(v) for k, v in sorted(Counter(r["g"] for r in kept).items())},
        "categories": dict(Counter(r["category"] for r in kept)),
        "already_ready": sum(1 for r in kept if r["already_ready"]),
        "states": kept,
    }


def structural_audit(sources: Sequence[dict], suit: str) -> dict:
    pkt_exp = pkt_mov = pkt_bur = 0
    five_top = five_one = 0
    five_n = 0
    depths = Counter()
    uppers = Counter()
    k5 = 0
    cats = Counter()
    for rec in sources:
        st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
        packets = tail_packets(st, suit, 4)
        fives = rank_cards(st, suit, 5)
        cats[source_category(st, suit)] += 1
        if any(p["exposed"] for p in packets):
            pkt_exp += 1
        if any(p["movable"] for p in packets):
            pkt_mov += 1
        if packets and all(not p["exposed"] for p in packets):
            pkt_bur += 1
        five_n += len(fives)
        if any(t["top"] for t in fives):
            five_top += 1
        if any(t["one_move_exposable"] for t in fives):
            five_one += 1
        for t in fives:
            depths[t["cards_above"]] += 1
            if t["top"]:
                ur = receiving_upper_run(st, t["column_0"], suit, 5)
                uppers[ur["label"]] += 1
                if ur.get("k_through"):
                    k5 += 1
    return {
        "suit": suit,
        "n": len(sources),
        "tail4_exposed_sources": pkt_exp,
        "tail4_movable_sources": pkt_mov,
        "tail4_buried_sources": pkt_bur,
        "five_n": five_n,
        "five_top_sources": five_top,
        "five_one_move_sources": five_one,
        "five_depth": {str(k): int(v) for k, v in sorted(depths.items())},
        "upper_runs": dict(uppers),
        "k_through_5": k5,
        "categories": dict(cats),
    }


def one_move_scan(sources: Sequence[dict], suit: str) -> dict:
    n_actions = 0
    ready_hits = []
    f2_hits = []
    for origin, rec in enumerate(sources):
        st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
        g0 = int(rec["g"])
        if rec.get("already_ready"):
            continue
        before_t = suit_foundation_count(st, suit)
        for action in engine_tableau_actions(st)[0]:
            if action == ("deal",):
                continue
            n_actions += 1
            cost = step_cost(st, action)
            cap = _capture(st, action)
            try:
                apply_action(st, action)
                if suit_foundation_count(st, suit) > before_t:
                    f2_hits.append({"origin": origin, "g": g0 + cost, "source_g": g0})
                    continue
                if tail5_ready(st, suit):
                    ready_hits.append(
                        {
                            "origin": origin,
                            "g": g0 + cost,
                            "source_g": g0,
                            "depth": 1,
                            "actions": dump_actions([action]),
                            "full_actions": dump_actions(as_actions(rec["full_actions"]) + [action]),
                            "ordered_digest": pack_state(st).hex(),
                            "symmetry_digest": pack_post_stock_symmetry_state(st).hex(),
                        }
                    )
            finally:
                _restore(st, cap)
    by = {}
    for w in ready_hits:
        prev = by.get(w["symmetry_digest"])
        if prev is None or w["g"] < prev["g"]:
            by[w["symmetry_digest"]] = w
    kept = sorted(by.values(), key=lambda w: (w["g"], w["origin"]))
    return {
        "n_actions": n_actions,
        "ready_n": len(kept),
        "ready_cheapest": None if not kept else kept[0]["g"],
        "f2_n": len(f2_hits),
        "ready": kept,
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
    f2_hits: List[dict] = field(default_factory=list)


def search_tail5_ready(
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
        if tail5_ready(st0, suit):
            result.already += 1
            witnesses[ident_sym] = {
                "origin": origin,
                "g": g0,
                "source_g": g0,
                "depth": 0,
                "actions": [],
                "already": True,
                "ready": True,
                "ordered_digest": ident_ord.hex(),
                "symmetry_digest": ident_sym.hex(),
            }
            if incumbent is None or g0 < incumbent:
                incumbent = g0
                result.first_s = 0.0
                result.first_g = g0
    result.unique = len(best_g)
    print(f"{suit} TAIL5 start unique={result.unique} already={result.already}", flush=True)

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
            if tail5_ready(st, suit):
                continue
            heapq.heappush(heap, (0, g_of[node], depth_of[node], seq, node))
            seq += 1
        seen_expand: Dict[bytes, int] = {}
        remaining_s = deadline - time.perf_counter()
        levels_left = 4 - level
        level_deadline = time.perf_counter() + max(10.0, remaining_s / max(1, levels_left))
        print(
            f"{suit} TAIL5 L{level} unique={result.unique} heap={len(heap)} inc={incumbent} "
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
                    f"{suit} TAIL5 L{level} exp={result.expanded} unique={result.unique} inc={incumbent} "
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
            if tail5_ready(state, suit):
                continue
            if state.stock:
                result.deal_expanded = True
            packets = tail_packets(state, suit, 4)
            fives = rank_cards(state, suit, 5)
            parent_ready = tail5_ready(state, suit)
            before_t = suit_foundation_count(state, suit)
            actions, _ = engine_tableau_actions(state)
            ranked = []
            for action in actions:
                if action == ("deal",):
                    result.deal_expanded = True
                    continue
                label = annotate_tail5_action(state, action, suit, packets, fives)
                tier_i = int(classify_tier(state, action))
                if not allowed_at_tail5_level(label, tier_i, level):
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
                    ready = tail5_ready(state, suit)
                    t5 = tail5_present(state, suit)
                    f2 = suit_foundation_count(state, suit) > before_t
                    if t5 and not parent_ready:
                        result.contract_fail += 1
                    if f2:
                        result.foundation_surprise = True
                        result.f2_hits.append(
                            {
                                "origin": origin_of[node],
                                "g": child_g,
                                "actions": dump_actions(reconstruct(child_node)),
                                "ordered_digest": child_ord.hex(),
                                "symmetry_digest": child_sym.hex(),
                            }
                        )
                    if ready or f2:
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
                            "foundation": f2,
                            "label": label,
                        }
                        if child_sym not in witnesses or child_g < witnesses[child_sym]["g"]:
                            witnesses[child_sym] = rec_w
                        if result.first_s is None:
                            result.first_s = time.perf_counter() - started
                            result.first_g = child_g
                            print(
                                f"FIRST_{suit}_TAIL5 g={child_g} unique={result.unique} "
                                f"t={result.first_s:.2f}s ready={ready} f2={f2}",
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
    rows = [w for w in witnesses.values() if w.get("ready")]
    kept = harvest_rows(
        rows,
        limit=HARVEST_LIMIT,
        keyfn=lambda w: (w.get("source_g"), w.get("depth"), bool(w.get("already")), w.get("label")),
    )
    result.witnesses = kept
    result.elapsed_s = time.perf_counter() - started
    result.peak_rss_mb = peak
    return result


def execute_tail5_joins(sources: Sequence[dict], ready_rows: Sequence[dict], suit: str) -> List[dict]:
    hits = []
    for rec in ready_rows:
        st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
        g0 = int(rec["g"])
        full0 = as_actions(rec.get("full_actions") or [])
        if not full0:
            origin = rec.get("origin", 0)
            if 0 <= origin < len(sources):
                full0 = as_actions(sources[origin]["full_actions"]) + as_actions(rec.get("actions") or [])
        for action in legal_tail_joins(st, suit, 5):
            hit = classify_low_tail_transition(st, g0, suit, action, packet_head_rank=4)
            hit["source_g"] = rec.get("source_g", g0)
            hit["full_actions"] = dump_actions(full0 + [action])
            hit["suit"] = suit
            hit["report_class"] = "TAIL5_PERSISTS" if hit["class"] == LOW_TAIL_PERSISTS else hit["class"]
            hits.append(hit)
    by = {}
    for w in hits:
        prev = by.get(w["symmetry_digest"])
        if prev is None or w["g"] < prev["g"]:
            by[w["symmetry_digest"]] = w
    return sorted(by.values(), key=lambda w: (w["g"], w.get("source_g") or 0))


def reconstruct_tail6_preview(rec: dict, suit: str) -> dict:
    st0 = unpack_state(bytes.fromhex(rec["ordered_digest"]))
    g0 = int(rec["g"])
    prefix = as_actions(rec["full_actions"])
    if tail6_ready(st0, suit):
        return {
            "status": "READY_AT_SOURCE",
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
        if unique >= PREVIEW_UNIQUE:
            live = True
            break
        g, depth, _, ident = heapq.heappop(heap)
        if g != best.get(ident) or seen.get(ident, 10**9) <= g:
            continue
        if depth >= PREVIEW_DEPTH:
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
                if tail6_ready(st, suit):
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
        return {"status": "LIVE_BEYOND_5", "g": None, "depth": None, "actions": [], "source_g": g0}
    return {"status": "EXACT_DEAD_TO_TAIL6_READY", "g": None, "depth": None, "actions": [], "source_g": g0}
