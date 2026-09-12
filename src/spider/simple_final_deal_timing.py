"""Research-only v0.43 final-Deal timing pivot.

Compare DEAL_NOW vs <=4-action tableau preparation then SD5, then exact
post-stock-symmetric UCS for the first additional foundation (any suit).
Canonical identity is ordered pack_state before SD5 and
pack_post_stock_symmetry_state after stock is empty.
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
from spider.packed_state import pack_post_stock_symmetry_state, pack_state, unpack_state
from spider.rules import MW_RULES, deal_cost
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, dump_actions, opening_state
from spider.simple_foundation_horizon import EXPECTED_SD5, pretty_card, stock_deal_rows
from spider.simple_progressive_solver import (
    _capture,
    _restore,
    _rss_mb,
    apply_action,
    step_cost,
)
from spider.simple_workspace_reachability import empty_column_indices, engine_tableau_actions, face_down_count

ROOT = Path(__file__).resolve().parents[2]
DEAL_PATH = ROOT / "deals" / "4925153.txt"
PORT_DIAMOND_READY = ROOT / "docs" / "research" / "sd4_diamond_operational_cut_v0_39_portfolio.json"
PORT_HEART_H9 = ROOT / "docs" / "research" / "sd4_operational_horizon_pivot_v0_37_h9_portfolio.json"
PORT_MULTI_EDGE = ROOT / "docs" / "research" / "diamond_multi_edge_sources_v0_41.json"
LINEAGES = {
    "diamond_ready": PORT_DIAMOND_READY,
    "heart_h9": PORT_HEART_H9,
    "diamond_multi_edge": PORT_MULTI_EDGE,
}
PREP_DEPTH = 4
PREP_COST = 4
PREP_UNIQUE = 125_000
PREP_TIME_S = 150.0
COST_CEILING = 120
SEARCH_UNIQUE = 600_000
SEARCH_TIME_S = 600.0
RSS_ABORT_MB = 3 * 1024.0
HARVEST_SLACK = 3
HARVEST_LIMIT = 256
SUIT_NAMES = {"s": "Spades", "h": "Hearts", "d": "Diamonds", "c": "Clubs"}


def sd5_row(state: SpiderState) -> List[str]:
    rows = stock_deal_rows(state.stock)
    if not rows:
        return []
    return [pretty_card(c) for c in rows[0]]


def verify_sd5_row(state: SpiderState) -> dict:
    got = sd5_row(state)
    return {
        "engine": got,
        "expected": list(EXPECTED_SD5),
        "matches": got == list(EXPECTED_SD5),
        "stock_rows": stock_rows(state),
    }


def deal_is_legal(state: SpiderState) -> bool:
    return state.can_deal(MW_RULES) and stock_rows(state) == 1


def same_suit_components(state: SpiderState) -> List[dict]:
    out = []
    for col_i, column in enumerate(state.columns):
        up = column.face_up
        i = 0
        while i < len(up):
            j = i + 1
            while (
                j < len(up)
                and up[j].suit == up[i].suit
                and up[j - 1].rank == up[j].rank + 1
            ):
                j += 1
            run = up[i:j]
            if len(run) >= 2:
                out.append(
                    {
                        "column_1": col_i + 1,
                        "suit": run[0].suit,
                        "ranks": [pretty_card(c) for c in run],
                        "length": len(run),
                        "exposed": j == len(up),
                    }
                )
            i = j
    return out


def complete_ka_sequences(state: SpiderState) -> List[dict]:
    found = []
    for col_i, column in enumerate(state.columns):
        up = column.face_up
        if len(up) >= 13 and up[-13].rank == 13 and SpiderState.is_movable_run(up[-13:]):
            found.append(
                {
                    "column_1": col_i + 1,
                    "suit": up[-13].suit,
                    "ranks": [pretty_card(c) for c in up[-13:]],
                }
            )
    return found


def zero_cost_whole_column_moves(state: SpiderState) -> List[List[int]]:
    out = []
    for action in engine_tableau_actions(state)[0]:
        src, dst, k = action
        sc = state.columns[src]
        dc = state.columns[dst]
        if dc.is_empty() and k == len(sc.face_up) and not sc.face_down:
            out.append([src, dst, k])
    return out


def foundation_suits(state: SpiderState) -> List[str]:
    return [run[0].suit for run in state.foundations if run]


def receiving_telemetry(state: SpiderState) -> dict:
    comps = same_suit_components(state)
    longest = 0 if not comps else max(c["length"] for c in comps)
    actions, _ = engine_tableau_actions(state)
    return {
        "fd": face_down_count(state),
        "empties": list(empty_column_indices(state)),
        "foundations": len(state.foundations),
        "foundation_suits": foundation_suits(state),
        "stock_rows": stock_rows(state),
        "legal_moves": len(actions),
        "zero_cost_whole_column": zero_cost_whole_column_moves(state),
        "longest_same_suit": longest,
        "complete_ka": complete_ka_sequences(state),
        "components_by_suit": {
            suit: sum(1 for c in comps if c["suit"] == suit) for suit in SUIT_NAMES
        },
    }


def load_union(opening: Optional[SpiderState] = None) -> dict:
    opening = opening or opening_state()
    raw = 0
    replay_failures = 0
    seen: Dict[bytes, dict] = {}
    lineage_raw = Counter()
    for lineage, path in LINEAGES.items():
        payload = json.loads(path.read_text(encoding="utf-8"))
        for rec in payload.get("states") or []:
            raw += 1
            lineage_raw[lineage] += 1
            full = as_actions(rec.get("full_actions") or rec.get("actions") or [])
            end = opening.clone()
            try:
                cost = replay_actions(end, full)
            except Exception:
                replay_failures += 1
                continue
            ident = pack_state(end)
            legal = deal_is_legal(end)
            ok = (
                (rec.get("full_cost") is None or cost == rec.get("full_cost"))
                and (not rec.get("ordered_digest") or ident.hex() == rec.get("ordered_digest"))
                and len(end.foundations) == 1
                and end.foundations[0]
                and end.foundations[0][0].suit == "s"
                and stock_rows(end) == 1
                and legal
            )
            if not ok:
                replay_failures += 1
                continue
            item = {
                "ordered_digest": ident.hex(),
                "full_cost": cost,
                "full_actions": dump_actions(full),
                "lineages": [lineage],
                "replay_ok": True,
                "stock_rows": 1,
                "sd5_legal": True,
            }
            prev = seen.get(ident)
            if prev is None or cost < prev["full_cost"]:
                if prev is not None:
                    item["lineages"] = sorted(set(prev["lineages"]) | {lineage})
                seen[ident] = item
            else:
                prev["lineages"] = sorted(set(prev["lineages"]) | {lineage})
    kept = sorted(seen.values(), key=lambda r: (r["full_cost"], r["ordered_digest"]))
    overlap = raw - replay_failures - len(kept)
    return {
        "raw": raw,
        "replay_failures": replay_failures,
        "exact_unique": len(kept),
        "lineage_raw": dict(lineage_raw),
        "lineage_unique": dict(Counter(lin for r in kept for lin in r["lineages"])),
        "cost_counts": {str(k): int(v) for k, v in sorted(Counter(r["full_cost"] for r in kept).items())},
        "all_replay_ok": replay_failures == 0 and bool(kept),
        "overlap_dropped": overlap,
        "states": kept,
    }


def apply_sd5(state: SpiderState) -> dict:
    before_f = len(state.foundations)
    cost = apply_action(state, ("deal",))
    return {
        "deal_cost": cost,
        "auto_removed": len(state.foundations) - before_f,
        "stock_rows": stock_rows(state),
        "foundations": len(state.foundations),
    }


@dataclass
class PrepResult:
    unique: int = 0
    expanded: int = 0
    generated: int = 0
    duplicate_skips: int = 0
    elapsed_s: float = 0.0
    stop_reason: str = ""
    candidates: List[dict] = field(default_factory=list)
    sd5_expanded: bool = False
    peak_rss_mb: Optional[float] = None


def enumerate_preparation(
    sources: Sequence[SpiderState],
    origin_paths: Sequence[Sequence[Action]],
    source_g: Sequence[int],
    source_lineages: Sequence[Sequence[str]],
    *,
    max_unique: int = PREP_UNIQUE,
    time_limit_s: float = PREP_TIME_S,
    max_depth: int = PREP_DEPTH,
    max_cost: int = PREP_COST,
) -> PrepResult:
    started = time.perf_counter()
    deadline = started + time_limit_s
    result = PrepResult()
    peak = _rss_mb()
    best_g: Dict[bytes, int] = {}
    parent: List[int] = []
    action_of: List[Optional[Action]] = []
    depth_of: List[int] = []
    origin_of: List[int] = []
    g_of: List[int] = []
    ident_of: List[bytes] = []
    origin_g_of: List[int] = []

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
        if ident in best_g:
            if g0 < best_g[ident]:
                best_g[ident] = g0
                idx = ident_of.index(ident)
                g_of[idx] = g0
                origin_of[idx] = origin
                origin_g_of[idx] = g0
            continue
        best_g[ident] = g0
        ident_of.append(ident)
        parent.append(-1)
        action_of.append(None)
        depth_of.append(0)
        origin_of.append(origin)
        g_of.append(g0)
        origin_g_of.append(g0)
    result.unique = len(best_g)
    heap: List[tuple] = []
    seq = 0
    for i, ident in enumerate(ident_of):
        heapq.heappush(heap, (g_of[i], depth_of[i], seq, i))
        seq += 1
    seen_expand: Dict[bytes, int] = {}
    print(f"PREP start unique={result.unique} cap={max_unique}", flush=True)
    while heap:
        now = time.perf_counter()
        if now >= deadline:
            result.stop_reason = "time limit"
            break
        rss = _rss_mb()
        if rss is not None and (peak is None or rss > peak):
            peak = rss
        if (result.expanded & 4095) == 0 and result.expanded:
            print(
                f"PREP exp={result.expanded} unique={result.unique} heap={len(heap)}",
                flush=True,
            )
        g, depth, _, node = heapq.heappop(heap)
        ident = ident_of[node]
        if g != best_g.get(ident):
            continue
        if seen_expand.get(ident, 10**9) <= g:
            continue
        seen_expand[ident] = g
        if depth >= max_depth:
            continue
        state = unpack_state(ident)
        actions, _ = engine_tableau_actions(state)
        result.expanded += 1
        for action in actions:
            if action == ("deal",):
                result.sd5_expanded = True
                continue
            cost = step_cost(state, action)
            child_g = g + cost
            if child_g - origin_g_of[node] > max_cost:
                continue
            cap = _capture(state, action)
            try:
                apply_action(state, action)
                result.generated += 1
                child_ident = pack_state(state)
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
                depth_of.append(depth + 1)
                origin_of.append(origin_of[node])
                g_of.append(child_g)
                origin_g_of.append(origin_g_of[node])
                heapq.heappush(heap, (child_g, depth + 1, seq, child_node))
                seq += 1
            finally:
                _restore(state, cap)
        if result.stop_reason in ("unique limit", "time limit"):
            break
    if not result.stop_reason:
        result.stop_reason = "complete"
    # one candidate per exact pre-Deal pack_state at cheapest g
    best_node: Dict[bytes, int] = {}
    for i, ident in enumerate(ident_of):
        if best_g.get(ident) == g_of[i]:
            cur = best_node.get(ident)
            if cur is None or depth_of[i] < depth_of[cur]:
                best_node[ident] = i
    for ident, node in best_node.items():
        origin = origin_of[node]
        prep_actions = reconstruct(node)
        result.candidates.append(
            {
                "origin": origin,
                "g": g_of[node],
                "source_g": origin_g_of[node],
                "prep_depth": depth_of[node],
                "prep_cost": g_of[node] - origin_g_of[node],
                "prep_actions": dump_actions(prep_actions),
                "ordered_digest": ident.hex(),
                "lineages": list(source_lineages[origin]),
                "timing": "DEAL_NOW" if depth_of[node] == 0 else "PREP_THEN_DEAL",
                "full_actions_pre": dump_actions(list(origin_paths[origin]) + prep_actions),
            }
        )
    result.candidates.sort(key=lambda c: (c["g"], c["prep_depth"], c["ordered_digest"]))
    result.elapsed_s = time.perf_counter() - started
    result.peak_rss_mb = peak
    print(
        f"PREP done unique={result.unique} cand={len(result.candidates)} stop={result.stop_reason}",
        flush=True,
    )
    return result


def deal_preparation_candidates(
    opening: SpiderState,
    candidates: Sequence[dict],
) -> dict:
    """Apply SD5 once to each prep candidate; exact-dedup by post-stock symmetry."""

    before = 0
    classes: Dict[bytes, dict] = {}
    auto = 0
    illegal = 0
    for rec in candidates:
        before += 1
        end = opening.clone()
        full = as_actions(rec["full_actions_pre"])
        replay_actions(end, full)
        if not deal_is_legal(end):
            illegal += 1
            continue
        before_f = len(end.foundations)
        dcost = apply_action(end, ("deal",))
        if stock_rows(end) != 0:
            illegal += 1
            continue
        if len(end.foundations) > before_f:
            auto += 1
        g = rec["g"] + dcost
        ident_ord = pack_state(end)
        ident_sym = pack_post_stock_symmetry_state(end)
        child = {
            "g": g,
            "prep_depth": rec["prep_depth"],
            "prep_cost": rec["prep_cost"],
            "timing": rec["timing"],
            "lineages": rec["lineages"],
            "ordered_digest": ident_ord.hex(),
            "symmetry_digest": ident_sym.hex(),
            "full_actions": dump_actions(full + [("deal",)]),
            "origin": rec["origin"],
            "deal_cost": dcost,
            "auto_removed": len(end.foundations) - before_f,
            "foundations": len(end.foundations),
            "telemetry": receiving_telemetry(end),
        }
        prev = classes.get(ident_sym)
        if prev is None or g < prev["g"]:
            classes[ident_sym] = child
    kept = sorted(classes.values(), key=lambda r: (r["g"], r["prep_depth"], r["ordered_digest"]))
    return {
        "ordered_before_symmetry": before,
        "symmetry_classes": len(kept),
        "reduction": None if not before else round(before / max(1, len(kept)), 3),
        "auto_removed": auto,
        "illegal": illegal,
        "timing": dict(Counter(r["timing"] for r in kept)),
        "depth": dict(Counter(r["prep_depth"] for r in kept)),
        "cost_counts": {str(k): int(v) for k, v in sorted(Counter(r["g"] for r in kept).items())},
        "states": kept,
    }


@dataclass
class FoundationResult:
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
    first_suit: Optional[str] = None
    first_timing: Optional[str] = None
    first_lineages: List[str] = field(default_factory=list)
    sd5_expanded: bool = False
    used_suit_heuristic: bool = False
    witnesses: List[dict] = field(default_factory=list)
    exhausted_below_f: bool = False
    min_live_g: Optional[int] = None


def search_foundation2(
    children: Sequence[dict],
    opening: SpiderState,
    *,
    max_unique: int = SEARCH_UNIQUE,
    time_limit_s: float = SEARCH_TIME_S,
    rss_abort_mb: float = RSS_ABORT_MB,
    cost_ceiling: int = COST_CEILING,
    harvest_slack: int = HARVEST_SLACK,
    harvest_limit: int = HARVEST_LIMIT,
) -> FoundationResult:
    started = time.perf_counter()
    deadline = started + time_limit_s
    result = FoundationResult()
    peak = _rss_mb()
    ceiling = cost_ceiling
    current_incumbent: Optional[int] = None
    witnesses: Dict[bytes, dict] = {}
    baseline = 1

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

    def note_rss() -> bool:
        nonlocal peak
        rss = _rss_mb()
        if rss is not None and (peak is None or rss > peak):
            peak = rss
        return rss is not None and rss >= rss_abort_mb

    for origin, rec in enumerate(children):
        end = unpack_state(bytes.fromhex(rec["ordered_digest"]))
        ident_ord = pack_state(end)
        ident_sym = pack_post_stock_symmetry_state(end)
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
    result.unique = len(best_g)
    heap: List[tuple] = []
    seq = 0
    best_node: Dict[bytes, int] = {}
    for i, ident in enumerate(ident_sym_of):
        if best_g.get(ident) == g_of[i]:
            best_node[ident] = i
    for ident, node in best_node.items():
        if g_of[node] > ceiling:
            continue
        heapq.heappush(heap, (g_of[node], depth_of[node], seq, node))
        seq += 1
    seen_expand: Dict[bytes, int] = {}
    print(f"F2 start unique={result.unique} sources={len(children)} ceiling={ceiling}", flush=True)

    while heap:
        now = time.perf_counter()
        if now >= deadline:
            result.stop_reason = "time limit"
            break
        if (result.expanded & 2047) == 0 and note_rss():
            result.stop_reason = "rss abort"
            break
        if (result.expanded & 8191) == 0 and result.expanded:
            print(
                f"F2 exp={result.expanded} unique={result.unique} inc={current_incumbent} "
                f"wit={len(witnesses)} heap={len(heap)}",
                flush=True,
            )
        g, depth, _, node = heapq.heappop(heap)
        ident_sym = ident_sym_of[node]
        if g != best_g.get(ident_sym):
            continue
        if g > ceiling:
            continue
        if seen_expand.get(ident_sym, 10**9) <= g:
            continue
        seen_expand[ident_sym] = g
        state = unpack_state(ident_ord_of[node])
        if len(state.foundations) > baseline and depth > 0:
            continue
        if stock_rows(state) != 0:
            result.sd5_expanded = True
        actions, _ = engine_tableau_actions(state)
        result.expanded += 1
        # engine order only — no suit-specific ranking
        for action in actions:
            if action == ("deal",):
                result.sd5_expanded = True
                continue
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
                hit = len(state.foundations) > baseline
                if hit:
                    suit = foundation_suits(state)[-1] if state.foundations else None
                    src = children[origin_of[node]]
                    rec = {
                        "origin": origin_of[node],
                        "g": child_g,
                        "depth": depth + 1,
                        "actions": dump_actions(reconstruct(child_node)),
                        "ordered_digest": child_ord.hex(),
                        "symmetry_digest": child_sym.hex(),
                        "suit": suit,
                        "suit_name": SUIT_NAMES.get(suit or "", suit),
                        "timing": src["timing"],
                        "prep_depth": src["prep_depth"],
                        "prep_cost": src["prep_cost"],
                        "lineages": src["lineages"],
                        "foundations": len(state.foundations),
                        "foundation_suits": foundation_suits(state),
                    }
                    if child_sym not in witnesses or child_g < witnesses[child_sym]["g"]:
                        witnesses[child_sym] = rec
                    if result.first_s is None:
                        result.first_s = time.perf_counter() - started
                        result.first_unique = result.unique
                        result.first_g = child_g
                        result.first_suit = suit
                        result.first_timing = src["timing"]
                        result.first_lineages = list(src["lineages"])
                        print(
                            f"FIRST_F2 g={child_g} suit={suit} timing={src['timing']} "
                            f"unique={result.unique} t={result.first_s:.2f}s",
                            flush=True,
                        )
                    if current_incumbent is None or child_g < current_incumbent:
                        current_incumbent = child_g
                        result.incumbent = child_g
                        ceiling = min(cost_ceiling, current_incumbent + harvest_slack)
                    continue
                heapq.heappush(heap, (child_g, depth + 1, seq, child_node))
                seq += 1
            finally:
                _restore(state, cap)
        if result.stop_reason in ("unique limit", "time limit", "rss abort"):
            break
        if current_incumbent is not None and heap and heap[0][0] > current_incumbent + harvest_slack:
            result.stop_reason = "harvested"
            break

    if not result.stop_reason:
        result.stop_reason = "complete"
        result.exhausted_below_f = current_incumbent is not None
    if heap:
        result.min_live_g = heap[0][0]
        if current_incumbent is not None and heap[0][0] >= current_incumbent:
            result.exhausted_below_f = True
    f = current_incumbent
    kept = []
    if f is not None:
        eligible = [w for w in witnesses.values() if w["g"] <= f + harvest_slack]
        eligible.sort(key=lambda w: (w["g"], w.get("depth", 0), w.get("origin", 0), w.get("ordered_digest", "")))
        kept = eligible[:harvest_limit]
    result.witnesses = kept
    result.elapsed_s = time.perf_counter() - started
    result.peak_rss_mb = peak
    return result


def synthetic_columns(face_up_runs: Sequence[Sequence[Card]], *, stock_n: int = 0) -> SpiderState:
    cols = [Column([], list(run)) for run in face_up_runs]
    while len(cols) < 10:
        cols.append(Column([], []))
    stock = [Card("h", 3) for _ in range(stock_n)]
    return SpiderState(cols, stock)
