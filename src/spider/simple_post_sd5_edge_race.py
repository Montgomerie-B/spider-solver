"""Research-only v0.44 post-SD5 suit entry-edge race.

From DEAL_NOW roots only, race the four mandatory 2-A foundation edges.
Search identity is pack_post_stock_symmetry_state.  Target progress is not
canonical identity.  Tableau only.  Full accumulated MW is g.
"""

from __future__ import annotations

import heapq
import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import Action, replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state, unpack_state
from spider.simple_current_horizon import occurrence_counts
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, dump_actions, opening_state
from spider.simple_final_deal_timing import (
    deal_is_legal,
    foundation_suits,
    same_suit_components,
    verify_sd5_row,
)
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

ROOT = Path(__file__).resolve().parents[2]
V043_SOURCES = ROOT / "docs" / "research" / "final_deal_sources_v0_43.json"
SUITS = ("s", "h", "d", "c")
SUIT_NAMES = {"s": "Spades", "h": "Hearts", "d": "Diamonds", "c": "Clubs"}
COST_CEILING = 100
HARVEST_SLACK = 3
HARVEST_LIMIT = 128
MAX_UNIQUE = 150_000
TIME_LIMIT_S = 150.0
RSS_PER_MB = 1.5 * 1024.0
RSS_TOTAL_MB = 3 * 1024.0
PREVIEW_DEPTH = 5
EXPECTED_SOURCES = 720
LABEL_RANK = {
    TARGET_JOIN: 0,
    TARGET_UNCOVER: 1,
    TARGET_DIRECT: 2,
    LANDING_SUPPORT: 3,
    GOOD_PLAY: 4,
    PARK: 5,
    OTHER: 6,
    JOIN_BREAK: 7,
    "DEAL": 8,
}


def edge_2a_present(state: SpiderState, suit: str, *, baseline: int = 0) -> bool:
    if suit_foundation_count(state, suit) > baseline:
        return True
    for column in state.columns:
        up = column.face_up
        for i in range(len(up) - 1):
            below, top = up[i], up[i + 1]
            if below.suit == suit and top.suit == suit and below.rank == 2 and top.rank == 1:
                return True
    return False


def tail3_present(state: SpiderState, suit: str, *, baseline: int = 0) -> bool:
    if suit_foundation_count(state, suit) > baseline:
        return True
    for column in state.columns:
        up = column.face_up
        for i in range(len(up) - 2):
            a, b, c = up[i], up[i + 1], up[i + 2]
            if (
                a.suit == b.suit == c.suit == suit
                and a.rank == 3
                and b.rank == 2
                and c.rank == 1
            ):
                return True
    return False


def low_tail_length(state: SpiderState, suit: str) -> int:
    """Longest contiguous same-suit run ending in Ace.  A=1 ... K-A=13."""

    best = 0
    for column in state.columns:
        up = column.face_up
        for i, card in enumerate(up):
            if card.suit != suit or card.rank != 1:
                continue
            lo = i
            while lo > 0 and up[lo - 1].suit == suit and up[lo - 1].rank == up[lo].rank + 1:
                lo -= 1
            best = max(best, i - lo + 1)
    return best


def edge_2a_is_mandatory() -> str:
    return (
        "Any same-suit K-A foundation is a descending movable run and therefore "
        "contains the adjacent pair 2-A.  EDGE_2A is mandatory for that suit."
    )


def material_copy_counts(state: SpiderState) -> dict:
    out = {}
    for suit in SUITS:
        ranks = {}
        unique_all = True
        for rank in range(1, 14):
            rec = occurrence_counts(state, suit, rank)
            ranks[rank] = {
                "current": rec["current_count"],
                "tableau": rec["tableau_count"],
                "foundation": rec["foundation_count"],
            }
            remaining = rec["tableau_count"]
            expected_remaining = 1 if suit == "s" else 2
            if remaining != expected_remaining:
                unique_all = False
        out[suit] = {
            "name": SUIT_NAMES[suit],
            "foundations": suit_foundation_count(state, suit),
            "ace": ranks[1],
            "two": ranks[2],
            "all_ranks_tableau": {str(r): ranks[r]["tableau"] for r in range(1, 14)},
            "every_remaining_rank_unique": unique_all if suit == "s" else False,
            "every_rank_two_tableau": all(ranks[r]["tableau"] == 2 for r in range(1, 14)) if suit != "s" else False,
        }
    spade_unique = out["s"]["every_remaining_rank_unique"] and out["s"]["foundations"] == 1
    out["spade2_full_physical_chain_unique"] = spade_unique
    return out


def locate_rank(state: SpiderState, suit: str, rank: int) -> List[dict]:
    rec = occurrence_counts(state, suit, rank)
    return [
        {
            "column_1": o.get("column_1"),
            "face_up": o.get("face_up"),
            "top": o.get("top"),
            "cards_above": o.get("cards_above"),
            "zone": o.get("zone"),
        }
        for o in rec["tableau"]
    ]


def immediate_2a_join(state: SpiderState, suit: str) -> bool:
    twos = occurrence_counts(state, suit, 2)["tableau"]
    aces = occurrence_counts(state, suit, 1)["tableau"]
    for t in twos:
        if not t.get("top"):
            continue
        tcol = t["column_0"]
        for a in aces:
            if not a.get("top"):
                continue
            acol = a["column_0"]
            if acol != tcol and state.can_move(acol, tcol, 1):
                return True
    return False


def source_edge_audit(state: SpiderState, suit: str, *, baseline: int) -> dict:
    return {
        "suit": suit,
        "edge_2a": edge_2a_present(state, suit, baseline=baseline),
        "aces": locate_rank(state, suit, 1),
        "twos": locate_rank(state, suit, 2),
        "ace_count": occurrence_counts(state, suit, 1)["current_count"],
        "two_count": occurrence_counts(state, suit, 2)["current_count"],
        "immediate_join": immediate_2a_join(state, suit),
        "low_tail": low_tail_length(state, suit),
        "components": [c for c in same_suit_components(state) if c["suit"] == suit],
    }


def load_deal_now_roots(opening: Optional[SpiderState] = None) -> dict:
    opening = opening or opening_state()
    payload = json.loads(V043_SOURCES.read_text(encoding="utf-8"))
    replay_failures = 0
    pre = []
    for rec in payload.get("states") or []:
        full = as_actions(rec.get("full_actions") or [])
        end = opening.clone()
        try:
            cost = replay_actions(end, full)
        except Exception:
            replay_failures += 1
            continue
        ident = pack_state(end)
        ok = (
            cost == rec.get("full_cost")
            and ident.hex() == rec.get("ordered_digest")
            and stock_rows(end) == 1
            and len(end.foundations) == 1
            and end.foundations[0][0].suit == "s"
            and deal_is_legal(end)
        )
        if not ok:
            replay_failures += 1
            continue
        pre.append(
            {
                "full_cost": cost,
                "full_actions": dump_actions(full),
                "lineages": rec.get("lineages") or [],
                "ordered_digest": ident.hex(),
            }
        )
    sd5_audit = None
    classes: Dict[bytes, dict] = {}
    auto = 0
    for rec in pre:
        end = opening.clone()
        replay_actions(end, as_actions(rec["full_actions"]))
        if sd5_audit is None:
            sd5_audit = verify_sd5_row(end)
            sd5_audit["deal_legal"] = deal_is_legal(end)
        before_f = len(end.foundations)
        dcost = apply_action(end, ("deal",))
        if stock_rows(end) != 0:
            replay_failures += 1
            continue
        if len(end.foundations) > before_f:
            auto += 1
        g = rec["full_cost"] + dcost
        ident_ord = pack_state(end)
        ident_sym = pack_post_stock_symmetry_state(end)
        item = {
            "g": g,
            "source_g": rec["full_cost"],
            "deal_cost": dcost,
            "lineages": rec["lineages"],
            "ordered_digest": ident_ord.hex(),
            "symmetry_digest": ident_sym.hex(),
            "full_actions": dump_actions(as_actions(rec["full_actions"]) + [("deal",)]),
            "foundations": len(end.foundations),
            "auto_removed": len(end.foundations) - before_f,
            "stock_rows": 0,
        }
        prev = classes.get(ident_sym)
        if prev is None or g < prev["g"]:
            if prev is not None:
                item["lineages"] = sorted(set(prev["lineages"]) | set(item["lineages"]))
            classes[ident_sym] = item
        else:
            prev["lineages"] = sorted(set(prev["lineages"]) | set(item["lineages"]))
    kept = sorted(classes.values(), key=lambda r: (r["g"], r["ordered_digest"]))
    return {
        "pre_sd5_n": len(pre),
        "pre_sd5_expected": EXPECTED_SOURCES,
        "replay_failures": replay_failures,
        "all_replay_ok": replay_failures == 0 and len(pre) == EXPECTED_SOURCES,
        "deal_now_ordered": len(pre),
        "symmetry_classes": len(kept),
        "auto_removed": auto,
        "sd5_audit": sd5_audit,
        "cost_counts": {str(k): int(v) for k, v in sorted(Counter(r["g"] for r in kept).items())},
        "lineage_counts": dict(Counter(lin for r in kept for lin in r["lineages"])),
        "states": kept,
    }


def annotate_2a_action(state: SpiderState, action, suit: str) -> str:
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
    if (
        dest_top is not None
        and dest_top.suit == suit
        and dest_top.rank == 2
        and head.suit == suit
        and head.rank == 1
    ):
        return TARGET_JOIN
    if dest_top is not None and dest_top.suit == suit and head.suit == suit and dest_top.rank == head.rank + 1:
        if dest_top.rank in (2, 3) or head.rank in (1, 2, 3):
            return TARGET_JOIN
        return TARGET_DIRECT
    if uncovers:
        flipped = src_col.face_down[-1]
        if flipped.suit == suit and flipped.rank in (1, 2, 3):
            return TARGET_UNCOVER
    if any(c.suit == suit and c.rank in (1, 2, 3) for c in run):
        return TARGET_DIRECT
    hot = False
    for rank in (1, 2):
        for o in occurrence_counts(state, suit, rank)["tableau"]:
            if o.get("column_0") in (src, dst):
                hot = True
    if hot:
        need = None
        if src_col.face_up:
            pkt = 1
            while pkt < len(src_col.face_up) and SpiderState.is_movable_run(src_col.face_up[-pkt - 1 :]):
                pkt += 1
            need = src_col.face_up[-pkt].rank + 1
        creates_empty = k == len(src_col.face_up) and not src_col.face_down and not dest_empty
        exposes_need = uncovers and need is not None and src_col.face_down[-1].rank == need
        if creates_empty or exposes_need or (dest_empty and head.rank == 13):
            return LANDING_SUPPORT
        return LANDING_SUPPORT
    if join_break:
        return JOIN_BREAK
    if int(classify_tier(state, action)) == int(Tier.A):
        return GOOD_PLAY
    if dest_empty:
        return PARK
    return OTHER


@dataclass
class EdgeResult:
    suit: str = ""
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
    first_lineages: List[str] = field(default_factory=list)
    sd5_expanded: bool = False
    used_heuristic_prune: bool = False
    used_prep_states: bool = False
    foundation_surprise: bool = False
    already_at_source: int = 0
    levels_reached: List[int] = field(default_factory=list)
    witnesses: List[dict] = field(default_factory=list)


def search_edge_2a(
    roots: Sequence[dict],
    opening: SpiderState,
    *,
    suit: str,
    max_unique: int = MAX_UNIQUE,
    time_limit_s: float = TIME_LIMIT_S,
    rss_abort_mb: float = RSS_PER_MB,
    cost_ceiling: int = COST_CEILING,
    harvest_slack: int = HARVEST_SLACK,
    harvest_limit: int = HARVEST_LIMIT,
) -> EdgeResult:
    started = time.perf_counter()
    deadline = started + time_limit_s
    result = EdgeResult(suit=suit)
    peak = _rss_mb()
    baseline = 1 if suit == "s" else 0
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
    ident_ord_of: List[bytes] = []
    ident_sym_of: List[bytes] = []

    def reconstruct(node: int) -> List[Action]:
        path: List[Action] = []
        while node >= 0 and parent[node] >= 0:
            act = action_of[node]
            if act is not None:
                path.append(act)
            node = parent[node]
        path.reverse()
        return path

    order = sorted(range(len(roots)), key=lambda i: (int(roots[i]["g"]), roots[i]["ordered_digest"]))
    for origin in order:
        rec = roots[origin]
        ident_ord = bytes.fromhex(rec["ordered_digest"])
        ident_sym = bytes.fromhex(rec["symmetry_digest"])
        g0 = int(rec["g"])
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
        st0 = unpack_state(ident_ord)
        if edge_2a_present(st0, suit, baseline=baseline):
            result.already_at_source += 1
            witnesses[ident_sym] = {
                "origin": origin,
                "g": g0,
                "depth": 0,
                "actions": [],
                "already": True,
                "foundation": suit_foundation_count(st0, suit) > baseline,
                "ordered_digest": ident_ord.hex(),
                "symmetry_digest": ident_sym.hex(),
                "lineages": rec["lineages"],
                "low_tail": low_tail_length(st0, suit),
            }
            if current_incumbent is None or g0 < current_incumbent:
                current_incumbent = g0
                result.incumbent = g0
                result.first_s = 0.0
                result.first_unique = 1
                result.first_g = g0
                result.first_lineages = list(rec["lineages"])
    result.unique = len(best_g)
    print(
        f"EDGE_{suit} start unique={result.unique} already={result.already_at_source} ceiling={ceiling}",
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
        for i, ident in enumerate(ident_sym_of):
            if best_g.get(ident) == g_of[i]:
                best_node[ident] = i
        for ident, node in best_node.items():
            if g_of[node] > ceiling:
                continue
            st = unpack_state(ident_ord_of[node])
            if edge_2a_present(st, suit, baseline=baseline) and depth_of[node] > 0:
                continue
            heapq.heappush(heap, (0, g_of[node], depth_of[node], seq, node))
            seq += 1
        seen_expand: Dict[bytes, int] = {}
        remaining_s = deadline - time.perf_counter()
        levels_left = 4 - level
        level_deadline = time.perf_counter() + max(12.0, remaining_s / max(1, levels_left))
        print(
            f"EDGE_{suit} L{level} unique={result.unique} heap={len(heap)} "
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
                    f"EDGE_{suit} L{level} exp={result.expanded} unique={result.unique} "
                    f"inc={current_incumbent} wit={len(witnesses)} heap={len(heap)}",
                    flush=True,
                )
            _rk, _g, _d, _s, node = heapq.heappop(heap)
            ident_sym = ident_sym_of[node]
            g = g_of[node]
            depth = depth_of[node]
            if g != best_g.get(ident_sym):
                continue
            if g > ceiling:
                continue
            if seen_expand.get(ident_sym, 10**9) <= g:
                continue
            seen_expand[ident_sym] = g
            state = unpack_state(ident_ord_of[node])
            if edge_2a_present(state, suit, baseline=baseline) and depth > 0:
                continue
            if state.stock:
                result.sd5_expanded = True
            actions, _ = engine_tableau_actions(state)
            ranked = []
            for action in actions:
                if action == ("deal",):
                    result.sd5_expanded = True
                    continue
                label = annotate_2a_action(state, action, suit)
                tier_i = int(classify_tier(state, action))
                if not allowed_at_race_level(label, tier_i, level):
                    continue
                ranked.append((LABEL_RANK.get(label, 9), action, label))
            ranked.sort(key=lambda t: (t[0], t[1]))
            result.expanded += 1
            parent_hit = edge_2a_present(state, suit, baseline=baseline)
            for _lab, action, label in ranked:
                cost = step_cost(state, action)
                child_g = g + cost
                if child_g > ceiling:
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
                    foundation = suit_foundation_count(state, suit) > baseline
                    hit = (edge_2a_present(state, suit, baseline=baseline) and not parent_hit) or foundation
                    if hit:
                        src = roots[origin_of[node]]
                        rec = {
                            "origin": origin_of[node],
                            "g": child_g,
                            "depth": depth + 1,
                            "actions": dump_actions(reconstruct(child_node)),
                            "ordered_digest": child_ord.hex(),
                            "symmetry_digest": child_sym.hex(),
                            "already": False,
                            "foundation": foundation,
                            "lineages": src["lineages"],
                            "label": label,
                            "level": level,
                            "low_tail": low_tail_length(state, suit),
                            "tail3": tail3_present(state, suit, baseline=baseline),
                            "fd": face_down_count(state),
                            "empties": list(empty_column_indices(state)),
                            "pairing": _pairing(state, suit),
                        }
                        if child_sym not in witnesses or child_g < witnesses[child_sym]["g"]:
                            witnesses[child_sym] = rec
                        if foundation:
                            result.foundation_surprise = True
                        if result.first_s is None:
                            result.first_s = time.perf_counter() - started
                            result.first_unique = result.unique
                            result.first_g = child_g
                            result.first_lineages = list(src["lineages"])
                            print(
                                f"FIRST_2A_{suit} g={child_g} unique={result.unique} "
                                f"t={result.first_s:.2f}s found={foundation}",
                                flush=True,
                            )
                        if current_incumbent is None or child_g < current_incumbent:
                            current_incumbent = child_g
                            result.incumbent = child_g
                            ceiling = min(cost_ceiling, current_incumbent + harvest_slack)
                        continue
                    heapq.heappush(
                        heap,
                        (LABEL_RANK.get(label, 9), child_g, depth + 1, seq, child_node),
                    )
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
    e0 = current_incumbent
    kept = []
    if e0 is not None:
        eligible = [w for w in witnesses.values() if w["g"] <= e0 + harvest_slack]
        kept = harvest_diverse(eligible, harvest_limit)
    result.witnesses = kept
    result.elapsed_s = time.perf_counter() - started
    result.peak_rss_mb = peak
    return result


def _pairing(state: SpiderState, suit: str) -> List[str]:
    out = []
    for column in state.columns:
        up = column.face_up
        for i in range(len(up) - 1):
            if up[i].suit == suit and up[i + 1].suit == suit and up[i].rank == 2 and up[i + 1].rank == 1:
                out.append(f"{pretty_card(up[i])}-{pretty_card(up[i + 1])}@c{state.columns.index(column)+1}")
    return out


def harvest_diverse(records: Sequence[dict], limit: int) -> List[dict]:
    ordered = sorted(records, key=lambda w: (w["g"], w.get("depth", 0), w.get("origin", 0), w.get("ordered_digest", "")))
    if len(ordered) <= limit:
        return list(ordered)
    buckets: Dict[tuple, List[dict]] = defaultdict(list)
    for rec in ordered:
        key = (
            tuple(rec.get("lineages") or []),
            tuple(rec.get("pairing") or []),
            tuple(rec.get("empties") or []),
            rec.get("low_tail"),
            rec.get("fd"),
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
                digest = rec.get("symmetry_digest")
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


def preview_tail3(
    state: SpiderState,
    suit: str,
    g0: int,
    *,
    max_depth: int = PREVIEW_DEPTH,
    deadline: float,
    rss_abort_mb: float = RSS_PER_MB,
    baseline: int = 0,
) -> dict:
    if tail3_present(state, suit, baseline=baseline):
        return {
            "status": "TAIL3_IMMEDIATE",
            "dead": False,
            "live": False,
            "unique": 1,
            "low_tail": low_tail_length(state, suit),
            "foundation": False,
            "max_depth": max_depth,
        }
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
    best_tail = low_tail_length(state, suit)
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
                child_depth = depth + 1
                best_tail = max(best_tail, low_tail_length(st, suit))
                if suit_foundation_count(st, suit) > baseline:
                    foundation = {"g": child_g, "depth": child_depth, "ordered_digest": child_ord.hex()}
                    break
                if tail3_present(st, suit, baseline=baseline):
                    found = {
                        "g": child_g,
                        "depth": child_depth,
                        "ordered_digest": child_ord.hex(),
                        "low_tail": low_tail_length(st, suit),
                    }
                    break
                seq += 1
                heapq.heappush(heap, (child_g, child_depth, seq, child_sym, child_ord))
            finally:
                _restore(st, cap)
        if foundation or found:
            break
    if foundation:
        status = "FOUNDATION_2_SURPRISE"
        dead = False
        live_flag = False
    elif found:
        status = "TAIL3_IMMEDIATE" if found["depth"] <= 1 else "TAIL3_WITHIN_5"
        dead = False
        live_flag = False
    elif live or heap:
        status = "LIVE_BEYOND_5"
        dead = False
        live_flag = True
    else:
        status = "EXACT_DEAD_TO_TAIL3"
        dead = True
        live_flag = False
    if live and status == "EXACT_DEAD_TO_TAIL3":
        status = "LIVE_BEYOND_5"
        dead = False
    return {
        "status": status,
        "dead": dead,
        "live": live_flag,
        "unique": unique,
        "hit": found,
        "foundation": foundation,
        "low_tail": best_tail,
        "max_depth": max_depth,
    }


def synthetic_columns(face_up_runs: Sequence[Sequence[Card]], *, stock_n: int = 0, foundations=None) -> SpiderState:
    cols = [Column([], list(run)) for run in face_up_runs]
    while len(cols) < 10:
        cols.append(Column([], []))
    stock = [Card("h", 3) for _ in range(stock_n)]
    return SpiderState(cols, stock, foundations or [])
