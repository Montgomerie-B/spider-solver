"""Research-only v0.46 unique-4S blocker ratchet.

From immediate post-SD5 3S-2S-AS states, ratchet B4 (cards above unique 4S)
until UNIQUE_4S_EXPOSED.  Canonical identity is post-stock symmetry.
Blocker count is not identity.  Tableau only.  Full accumulated MW is g.
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
from spider.packed_state import pack_post_stock_symmetry_state, pack_state, permute_tableau_columns, unpack_state
from spider.simple_current_horizon import occurrence_counts
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, dump_actions, opening_state
from spider.simple_final_deal_timing import (
    PREP_COST,
    PREP_DEPTH,
    PREP_TIME_S,
    PREP_UNIQUE,
    enumerate_preparation,
    foundation_suits,
)
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
from spider.simple_sd5_spade_receiver import (
    load_pre_sd5_sources,
    spade_low_tail_length,
    spade_tail_present,
)
from spider.simple_workspace_reachability import empty_column_indices, engine_tableau_actions, face_down_count

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_TAIL3_RAW = 3520
COST_CEILING = 100
STAGE_UNIQUE = 120_000
GLOBAL_TIME_S = 450.0
RSS_ABORT_MB = 2.5 * 1024.0
HARVEST_SLACK = 3
HARVEST_LIMIT = 128
PREVIEW_DEPTH = 6
B4_REDUCE = "B4_REDUCE"
B4_LANDING = "B4_LANDING"
TARGET_JOIN = "TARGET_JOIN"
AB_QUALITY = "AB_QUALITY"
L0_LABELS = {B4_REDUCE, B4_LANDING, TARGET_JOIN, GOOD_PLAY}
L1_LABELS = L0_LABELS | {AB_QUALITY, PARK}


def locate_unique_spade(state: SpiderState, rank: int) -> Optional[dict]:
    rec = occurrence_counts(state, "s", rank)
    tab = rec["tableau"]
    if rec["tableau_count"] != 1 or not tab:
        return None
    o = tab[0]
    col = o["column_0"]
    column = state.columns[col]
    if o.get("face_up"):
        idx = o.get("up_index")
        if idx is None:
            idx = next(i for i, c in enumerate(column.face_up) if c.suit == "s" and c.rank == rank)
        above = [pretty_card(c) for c in column.face_up[idx + 1 :]]
        return {
            "column_0": col,
            "column_1": col + 1,
            "face_up": True,
            "up_index": idx,
            "top": idx == len(column.face_up) - 1,
            "b4" if rank == 4 else "cards_above": len(above),
            "cards_above": len(above),
            "above": above,
        }
    return {
        "column_0": col,
        "column_1": col + 1,
        "face_up": False,
        "top": False,
        "cards_above": o.get("cards_above") or 0,
        "above": o.get("face_up_above") or [],
    }


def b4_count(state: SpiderState) -> int:
    loc = locate_unique_spade(state, 4)
    if loc is None:
        return 10**9
    return int(loc["cards_above"])


def unique_4s_exposed(state: SpiderState) -> bool:
    loc = locate_unique_spade(state, 4)
    return bool(loc and loc.get("top") and loc.get("face_up") and loc["cards_above"] == 0)


def four_s_can_move(state: SpiderState) -> bool:
    loc = locate_unique_spade(state, 4)
    if not loc or not loc.get("face_up"):
        return False
    col = loc["column_0"]
    idx = loc["up_index"]
    k = len(state.columns[col].face_up) - idx
    if k <= 0:
        return False
    run = state.columns[col].face_up[-k:]
    if run[0].suit != "s" or run[0].rank != 4:
        return False
    if not SpiderState.is_movable_run(run):
        return False
    for action in engine_tableau_actions(state)[0]:
        if action[0] == col and action[2] == k:
            return True
    return False


def must_cross_b4_zero() -> str:
    return (
        "The remaining 4S is unique. Joining 3S-2S-AS onto it, or moving 4S first, "
        "requires 4S to be exposed/top. Every second-Spade path therefore crosses B4=0."
    )


def top_movable_k(state: SpiderState, col: int) -> int:
    up = state.columns[col].face_up
    if not up:
        return 0
    k = 1
    while k < len(up) and SpiderState.is_movable_run(up[-k - 1 :]):
        k += 1
    return k


def tail3_packet(state: SpiderState) -> Optional[dict]:
    for col_i, column in enumerate(state.columns):
        up = column.face_up
        for i in range(len(up) - 2):
            a, b, c = up[i], up[i + 1], up[i + 2]
            if a.suit == b.suit == c.suit == "s" and [a.rank, b.rank, c.rank] == [3, 2, 1]:
                k = len(up) - i
                intact_top = i + 3 == len(up)
                dests = []
                if intact_top and SpiderState.is_movable_run(up[-3:]):
                    for action in engine_tableau_actions(state)[0]:
                        if action[0] == col_i and action[2] == 3:
                            dests.append(action[1] + 1)
                return {
                    "column_1": col_i + 1,
                    "up_index": i,
                    "exposed": intact_top,
                    "dests": dests,
                }
    return None


def packet_dests(state: SpiderState, col: int, k: int) -> List[int]:
    out = []
    if k <= 0 or k > len(state.columns[col].face_up):
        return out
    if not SpiderState.is_movable_run(state.columns[col].face_up[-k:]):
        return out
    for action in engine_tableau_actions(state)[0]:
        if action[0] == col and action[2] == k:
            out.append(action[1] + 1)
    return out


def exposed_rank_dests(state: SpiderState, rank: int) -> List[int]:
    return [i + 1 for i, col in enumerate(state.columns) if col.top() and col.top().rank == rank]


def source_blocker_audit(state: SpiderState) -> dict:
    loc4 = locate_unique_spade(state, 4)
    t3 = tail3_packet(state)
    b4 = b4_count(state)
    above = loc4["above"] if loc4 else []
    col = loc4["column_0"] if loc4 else None
    k = top_movable_k(state, col) if col is not None else 0
    tail3_above = False
    if loc4 and t3 and t3["column_1"] == loc4["column_1"]:
        # 3S-2S-AS starts at higher index than 4S
        if loc4.get("face_up") and t3["up_index"] > loc4.get("up_index", -1):
            tail3_above = True
    as_col = locate_unique_spade(state, 1)
    two = locate_unique_spade(state, 2)
    three = locate_unique_spade(state, 3)
    dest_as = packet_dests(state, as_col["column_0"], 1) if as_col and as_col.get("top") else []
    dest_2a = packet_dests(state, two["column_0"], 2) if two and two.get("top") is False and as_col and as_col.get("column_0") == two.get("column_0") else []
    dest_t3 = t3["dests"] if t3 else []
    if two and as_col and two["column_0"] == as_col["column_0"] and as_col.get("top"):
        dest_2a = packet_dests(state, two["column_0"], 2)
    return {
        "column_1": None if loc4 is None else loc4["column_1"],
        "b4": b4,
        "above": above,
        "signature": tuple(above),
        "top_packet_k": k,
        "top_packet": [pretty_card(c) for c in state.columns[col].face_up[-k:]] if col is not None and k else [],
        "top_packet_dests": packet_dests(state, col, k) if col is not None else [],
        "tail3": t3,
        "tail3_above_4s": tail3_above,
        "dest_as": dest_as,
        "dest_2a": dest_2a,
        "dest_t3": dest_t3,
        "empties": list(empty_column_indices(state)),
        "rank4_dests": exposed_rank_dests(state, 4),
        "rank5_dests": exposed_rank_dests(state, 5),
        "rank6_dests": exposed_rank_dests(state, 6),
        "four_can_move": four_s_can_move(state),
        "loc_3s": None if not three else three["column_1"],
        "loc_2s": None if not two else two["column_1"],
        "loc_as": None if not as_col else as_col["column_1"],
    }


def reconstruct_tail3_sources(opening: Optional[SpiderState] = None) -> dict:
    opening = opening or opening_state()
    pre = load_pre_sd5_sources(opening)
    states, paths, gs, lins = [], [], [], []
    for rec in pre["states"]:
        end = opening.clone()
        replay_actions(end, as_actions(rec["full_actions"]))
        states.append(end)
        paths.append(as_actions(rec["full_actions"]))
        gs.append(int(rec["full_cost"]))
        lins.append(list(rec["lineages"]))
    prep = enumerate_preparation(
        states, paths, gs, lins, max_unique=PREP_UNIQUE, time_limit_s=PREP_TIME_S, max_depth=PREP_DEPTH, max_cost=PREP_COST
    )
    raw = 0
    replay_fail = 0
    uniqueness_fail = 0
    classes: Dict[bytes, dict] = {}
    for rec in prep.candidates:
        end = opening.clone()
        full_pre = as_actions(rec["full_actions_pre"])
        replay_actions(end, full_pre)
        apply_action(end, ("deal",))
        if stock_rows(end) != 0:
            replay_fail += 1
            continue
        if not spade_tail_present(end, 3):
            continue
        raw += 1
        g = rec["g"] + 1
        if (
            occurrence_counts(end, "s", 4)["tableau_count"] != 1
            or occurrence_counts(end, "s", 3)["tableau_count"] != 1
            or occurrence_counts(end, "s", 2)["tableau_count"] != 1
            or occurrence_counts(end, "s", 1)["tableau_count"] != 1
            or len(end.foundations) != 1
        ):
            uniqueness_fail += 1
            continue
        ident_ord = pack_state(end)
        ident_sym = pack_post_stock_symmetry_state(end)
        audit = source_blocker_audit(end)
        item = {
            "g": g,
            "timing": rec["timing"],
            "prep_depth": rec["prep_depth"],
            "prep_cost": rec["prep_cost"],
            "lineages": rec["lineages"],
            "ordered_digest": ident_ord.hex(),
            "symmetry_digest": ident_sym.hex(),
            "full_actions": dump_actions(full_pre + [("deal",)]),
            "b4": audit["b4"],
            "signature": list(audit["signature"]),
            "column_1": audit["column_1"],
            "tail3_above_4s": audit["tail3_above_4s"],
            "audit": audit,
        }
        prev = classes.get(ident_sym)
        if prev is None or g < prev["g"]:
            classes[ident_sym] = item
    kept = sorted(classes.values(), key=lambda r: (r["g"], r["b4"], r["ordered_digest"]))
    return {
        "pre_ok": pre["all_replay_ok"],
        "prep_n": len(prep.candidates),
        "raw_tail3": raw,
        "expected_raw": EXPECTED_TAIL3_RAW,
        "symmetry_unique": len(kept),
        "replay_fail": replay_fail,
        "uniqueness_fail": uniqueness_fail,
        "timing": dict(Counter(r["timing"] for r in kept)),
        "cost_counts": {str(k): int(v) for k, v in sorted(Counter(r["g"] for r in kept).items())},
        "b4_dist": {str(k): int(v) for k, v in sorted(Counter(r["b4"] for r in kept).items())},
        "signatures": {str(sig): int(c) for sig, c in Counter(tuple(r["signature"]) for r in kept).most_common(20)},
        "all_replay_ok": replay_fail == 0 and uniqueness_fail == 0 and raw == EXPECTED_TAIL3_RAW,
        "states": kept,
    }


def allowed_at_b4_level(label: str, tier: int, level: int) -> bool:
    if level >= 3:
        return True
    if level <= 0:
        return label in L0_LABELS
    if level == 1:
        return label in L1_LABELS or tier <= int(Tier.B)
    if level == 2:
        return label != JOIN_BREAK
    return True


def annotate_b4_action(state: SpiderState, action, loc4: dict) -> str:
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
    col4 = loc4["column_0"]
    b4 = loc4["cards_above"]
    if src == col4 and b4 > 0 and k <= b4:
        return B4_REDUCE
    pkt_k = top_movable_k(state, col4)
    need = None
    if pkt_k and not packet_dests(state, col4, pkt_k):
        need = src_col.face_up[-pkt_k].rank + 1 if src == col4 else state.columns[col4].face_up[-pkt_k].rank + 1
        need = state.columns[col4].face_up[-pkt_k].rank + 1
    if need is not None:
        if dest_empty and head.rank == 13:
            return B4_LANDING
        if dest_top is not None and dest_top.rank == need:
            return B4_LANDING
        if uncovers and src_col.face_down[-1].rank == need:
            return B4_LANDING
        creates_empty = k == len(src_col.face_up) and not src_col.face_down and not dest_empty
        if creates_empty:
            return B4_LANDING
    if dest_top is not None and dest_top.suit == "s" and head.suit == "s" and dest_top.rank == head.rank + 1:
        return TARGET_JOIN
    if any(c.suit == "s" for c in run):
        return AB_QUALITY
    if join_break:
        return JOIN_BREAK
    if int(classify_tier(state, action)) == int(Tier.A):
        return GOOD_PLAY
    if dest_empty:
        return PARK
    return OTHER


@dataclass
class StageResult:
    unique: int = 0
    expanded: int = 0
    generated: int = 0
    duplicate_skips: int = 0
    elapsed_s: float = 0.0
    peak_rss_mb: Optional[float] = None
    stop_reason: str = ""
    sd5_expanded: bool = False
    foundation_surprise: bool = False
    witnesses: List[dict] = field(default_factory=list)
    first_s: Optional[float] = None
    first_g: Optional[int] = None
    first_b4: Optional[int] = None


def search_b4_decrease(
    sources: Sequence[dict],
    opening: SpiderState,
    *,
    max_unique: int = STAGE_UNIQUE,
    time_limit_s: float = 120.0,
    rss_abort_mb: float = RSS_ABORT_MB,
    cost_ceiling: int = COST_CEILING,
) -> StageResult:
    started = time.perf_counter()
    deadline = started + time_limit_s
    result = StageResult()
    peak = _rss_mb()
    best_g: Dict[bytes, int] = {}
    parent: List[int] = []
    action_of: List[Optional[Action]] = []
    depth_of: List[int] = []
    origin_of: List[int] = []
    g_of: List[int] = []
    ident_ord_of: List[bytes] = []
    ident_sym_of: List[bytes] = []
    b4_origin_of: List[int] = []
    witnesses: Dict[bytes, dict] = {}
    current_incumbent: Optional[int] = None

    def reconstruct(node: int) -> List[Action]:
        path: List[Action] = []
        while node >= 0 and parent[node] >= 0:
            act = action_of[node]
            if act is not None:
                path.append(act)
            node = parent[node]
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
        b0 = b4_count(st0)
        if b0 <= 0:
            continue
        if ident_sym in best_g:
            if g0 < best_g[ident_sym]:
                best_g[ident_sym] = g0
                idx = ident_sym_of.index(ident_sym)
                g_of[idx] = g0
                origin_of[idx] = origin
                ident_ord_of[idx] = ident_ord
                b4_origin_of[idx] = b0
            continue
        best_g[ident_sym] = g0
        ident_sym_of.append(ident_sym)
        ident_ord_of.append(ident_ord)
        parent.append(-1)
        action_of.append(None)
        depth_of.append(0)
        origin_of.append(origin)
        g_of.append(g0)
        b4_origin_of.append(b0)
    result.unique = len(best_g)
    print(f"B4 stage start unique={result.unique} sources={len(sources)}", flush=True)

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
            if b4_count(st) < b4_origin_of[node] and depth_of[node] > 0:
                continue
            heapq.heappush(heap, (0, g_of[node], depth_of[node], seq, node))
            seq += 1
        seen_expand: Dict[bytes, int] = {}
        remaining_s = deadline - time.perf_counter()
        levels_left = 4 - level
        level_deadline = time.perf_counter() + max(10.0, remaining_s / max(1, levels_left))
        print(
            f"B4 L{level} unique={result.unique} heap={len(heap)} inc={current_incumbent} "
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
            if (result.expanded & 8191) == 0 and result.expanded:
                print(
                    f"B4 L{level} exp={result.expanded} unique={result.unique} inc={current_incumbent} "
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
            b_now = b4_count(state)
            b_src = b4_origin_of[node]
            if b_now < b_src and depth > 0:
                continue
            loc4 = locate_unique_spade(state, 4)
            if loc4 is None:
                continue
            if state.stock:
                result.sd5_expanded = True
            actions, _ = engine_tableau_actions(state)
            ranked = []
            for action in actions:
                if action == ("deal",):
                    result.sd5_expanded = True
                    continue
                label = annotate_b4_action(state, action, loc4)
                tier_i = int(classify_tier(state, action))
                if not allowed_at_b4_level(label, tier_i, level):
                    continue
                ranked.append((0 if label == B4_REDUCE else 1 if label == B4_LANDING else 2, action, label))
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
                        result.sd5_expanded = True
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
                    b4_origin_of.append(b_src)
                    child_b = b4_count(state)
                    foundation = suit_foundation_count(state, "s") > 1
                    hit = child_b < b_src or foundation
                    if hit:
                        src = sources[origin_of[node]]
                        rec = {
                            "origin": origin_of[node],
                            "g": child_g,
                            "depth": depth + 1,
                            "actions": dump_actions(reconstruct(child_node)),
                            "ordered_digest": child_ord.hex(),
                            "symmetry_digest": child_sym.hex(),
                            "b4_before": b_src,
                            "b4_after": 0 if foundation else child_b,
                            "label": label,
                            "timing": src.get("timing"),
                            "lineages": src.get("lineages"),
                            "foundation": foundation,
                            "tail3": bool(tail3_packet(state)),
                            "signature": list(locate_unique_spade(state, 4)["above"]) if locate_unique_spade(state, 4) else [],
                            "cards_removed": b_src - (0 if foundation else child_b),
                        }
                        if child_sym not in witnesses or child_g < witnesses[child_sym]["g"]:
                            witnesses[child_sym] = rec
                        if foundation:
                            result.foundation_surprise = True
                        if result.first_s is None:
                            result.first_s = time.perf_counter() - started
                            result.first_g = child_g
                            result.first_b4 = rec["b4_after"]
                            print(
                                f"FIRST_B4 {b_src}->{rec['b4_after']} g={child_g} unique={result.unique} "
                                f"t={result.first_s:.2f}s found={foundation}",
                                flush=True,
                            )
                        if current_incumbent is None or child_g < current_incumbent:
                            current_incumbent = child_g
                        continue
                    heapq.heappush(heap, (0 if label == B4_REDUCE else 1, child_g, depth + 1, seq, child_node))
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
    # harvest per achieved B4
    by_b: Dict[int, List[dict]] = defaultdict(list)
    for rec in witnesses.values():
        by_b[int(rec["b4_after"])].append(rec)
    kept = []
    for b, rows in sorted(by_b.items()):
        rows.sort(key=lambda w: (w["g"], w.get("depth", 0), w.get("origin", 0), w.get("ordered_digest", "")))
        g0 = rows[0]["g"]
        slack = [w for w in rows if w["g"] <= g0 + HARVEST_SLACK]
        # diversity round-robin
        buckets: Dict[tuple, List[dict]] = defaultdict(list)
        for w in slack:
            key = (w.get("timing"), w.get("tail3"), tuple(w.get("signature") or []), tuple(w.get("lineages") or []))
            buckets[key].append(w)
        picked = []
        seen = set()
        while len(picked) < HARVEST_LIMIT:
            progressed = False
            for key in sorted(buckets, key=str):
                while buckets[key]:
                    w = buckets[key].pop(0)
                    if w["symmetry_digest"] in seen:
                        continue
                    seen.add(w["symmetry_digest"])
                    picked.append(w)
                    progressed = True
                    break
                if len(picked) >= HARVEST_LIMIT:
                    break
            if not progressed:
                break
        kept.extend(picked[:HARVEST_LIMIT])
    result.witnesses = kept
    result.elapsed_s = time.perf_counter() - started
    result.peak_rss_mb = peak
    return result


def preview_tail4(
    state: SpiderState,
    g0: int,
    *,
    max_depth: int = PREVIEW_DEPTH,
    deadline: float,
    rss_abort_mb: float = RSS_ABORT_MB,
) -> dict:
    if spade_tail_present(state, 4):
        return {"status": "TAIL4_IMMEDIATE", "dead": False, "live": False, "unique": 1, "g": g0, "foundation": False}
    ident0 = pack_post_stock_symmetry_state(state)
    ord0 = pack_state(state)
    best = {ident0: g0}
    heap = [(g0, 0, 0, ident0, ord0)]
    seq = 0
    seen: Dict[bytes, int] = {}
    unique = 1
    live = False
    found = None
    foundation = None
    while heap:
        if time.perf_counter() >= deadline:
            live = True
            break
        rss = _rss_mb()
        if rss is not None and rss >= rss_abort_mb:
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
        actions, _ = engine_tableau_actions(st)
        for action in actions:
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
                if suit_foundation_count(st, "s") > 1:
                    foundation = {"g": child_g, "depth": depth + 1}
                    break
                if spade_tail_present(st, 4):
                    found = {"g": child_g, "depth": depth + 1, "ordered_digest": child_ord.hex()}
                    break
                seq += 1
                heapq.heappush(heap, (child_g, depth + 1, seq, child_sym, child_ord))
            finally:
                _restore(st, cap)
        if foundation or found:
            break
    if foundation:
        status = "FOUNDATION_2"
        dead = False
        live_flag = False
    elif found:
        status = "TAIL4_IMMEDIATE" if found["depth"] <= 1 else "TAIL4_WITHIN_6"
        dead = False
        live_flag = False
    elif live or heap:
        status = "LIVE_BEYOND_6"
        dead = False
        live_flag = True
    else:
        status = "EXACT_DEAD_TO_TAIL4"
        dead = True
        live_flag = False
    if live and status == "EXACT_DEAD_TO_TAIL4":
        status = "LIVE_BEYOND_6"
        dead = False
    return {"status": status, "dead": dead, "live": live_flag, "unique": unique, "hit": found, "foundation": foundation}


def synthetic_columns(face_up_runs: Sequence[Sequence[Card]], *, stock_n: int = 0, foundations=None) -> SpiderState:
    cols = [Column([], list(run)) for run in face_up_runs]
    while len(cols) < 10:
        cols.append(Column([], []))
    stock = [Card("h", 3) for _ in range(stock_n)]
    return SpiderState(cols, stock, foundations or [])
