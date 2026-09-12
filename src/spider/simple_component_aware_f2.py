"""Research-only v0.56 component-aware Foundation-2 search.

Compact multi-lane best-first search over v0.55 portfolio + DEAL_NOW
controls.  Shared exact TT is pack_post_stock_symmetry_state + cheapest g.
Lane keys order only.  Reuses v0.54 loaders and v0.55 descriptors.
"""

from __future__ import annotations

import heapq
import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from spider.metrics import Action
from spider.packed_state import pack_post_stock_symmetry_state, pack_state, unpack_state
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, dump_actions
from spider.simple_final_deal_timing import foundation_suits
from spider.simple_progressive_solver import _capture, _restore, _rss_mb, apply_action, step_cost
from spider.simple_resource_aware_f2 import (
    COST_CEILING,
    DEAL_NOW_PATH,
    EXPECTED_DEAL_NOW,
    HARVEST_LIMIT,
    HARVEST_SLACK,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    SUIT_NAMES,
    _replay_root,
    load_deal_now_roots,
    union_roots,
)
from spider.simple_sd5_component_audit import SUITS, INF, all_lane_metrics, suit_lane_key
from spider.simple_workspace_reachability import empty_column_indices, engine_tableau_actions, face_down_count

ROOT = Path(__file__).resolve().parents[2]
PORT_V055 = ROOT / "docs" / "research" / "sd5_component_aware_portfolio_v0_55.json"
LANES = ("cost", "s", "h", "d", "c", "work")


def load_v055_portfolio(opening) -> dict:
    raw = json.loads(PORT_V055.read_text(encoding="utf-8"))
    rows = list(raw.get("states") or [])
    fail = 0
    kept = []
    for rec in rows:
        timing = rec.get("timing") or "PREP_THEN_DEAL"
        item = _replay_root(opening, rec, timing=timing)
        if item is None:
            fail += 1
            continue
        item["category"] = rec.get("portfolio_cat")
        item["categories"] = [rec.get("portfolio_cat")] if rec.get("portfolio_cat") else []
        item["min_cover"] = rec.get("min_cover")
        item["by_suit"] = rec.get("by_suit")
        item["gap"] = rec.get("gap")
        item["cond_longest"] = rec.get("cond_longest")
        item["start_edges"] = rec.get("start_edges")
        kept.append(item)
    return {
        "raw": len(rows),
        "n": len(kept),
        "replay_fail": fail,
        "all_replay_ok": fail == 0 and bool(kept),
        "timing": dict(Counter(r["timing"] for r in kept)),
        "categories": dict(Counter(r.get("category") for r in kept)),
        "states": kept,
    }


def _n(v, default=INF) -> int:
    return default if v is None else int(v)


def workspace_key(metrics_by_suit: dict, fd: int, empties: int, g: int) -> tuple:
    covers = [_n((metrics_by_suit.get(s) or {}).get("cover")) for s in SUITS]
    edges = sum(int((metrics_by_suit.get(s) or {}).get("edges") or 0) for s in SUITS)
    return (-int(empties), int(fd), min(covers), -edges, int(g))


def _better_progress(old: Optional[dict], new: dict, g: int) -> bool:
    if old is None:
        return True
    a = (
        _n(new.get("cover")),
        _n(new.get("visible")),
        -int(new.get("edges") or 0),
        -int(new.get("cond_len") or 0),
        _n(new.get("gap")),
        _n(new.get("fd")),
        g,
    )
    b = (
        _n(old.get("cover")),
        _n(old.get("visible")),
        -int(old.get("edges") or 0),
        -int(old.get("cond_len") or 0),
        _n(old.get("gap")),
        _n(old.get("fd")),
        int(old.get("g") or INF),
    )
    return a < b


@dataclass
class LaneF2Result:
    unique: int = 0
    expanded: int = 0
    generated: int = 0
    duplicate_skips: int = 0
    stale_skips: int = 0
    elapsed_s: float = 0.0
    peak_rss_mb: Optional[float] = None
    stop_reason: str = ""
    incumbent: Optional[int] = None
    first_s: Optional[float] = None
    first_unique: Optional[int] = None
    first_g: Optional[int] = None
    first_suit: Optional[str] = None
    first_timing: Optional[str] = None
    first_category: Optional[str] = None
    first_root_g: Optional[int] = None
    min_g: Optional[int] = None
    max_g: Optional[int] = None
    min_live_g: Optional[int] = None
    closed_g: Optional[int] = None
    sd5_expanded: bool = False
    accounting_fail: bool = False
    lane_pops: Dict[str, int] = field(default_factory=dict)
    lane_exp: Dict[str, int] = field(default_factory=dict)
    lane_stale: Dict[str, int] = field(default_factory=dict)
    best_progress: Dict[str, dict] = field(default_factory=dict)
    witnesses: List[dict] = field(default_factory=list)


def search_component_aware_f2(
    roots: Sequence[dict],
    *,
    max_unique: int = SEARCH_UNIQUE,
    time_limit_s: float = SEARCH_TIME_S,
    rss_abort_mb: float = SEARCH_RSS_MB,
    cost_ceiling: int = COST_CEILING,
    harvest_slack: int = HARVEST_SLACK,
    harvest_limit: int = HARVEST_LIMIT,
) -> LaneF2Result:
    started = time.perf_counter()
    deadline = started + time_limit_s
    result = LaneF2Result(
        lane_pops={k: 0 for k in LANES},
        lane_exp={k: 0 for k in LANES},
        lane_stale={k: 0 for k in LANES},
    )
    peak = _rss_mb()
    ceiling = cost_ceiling
    current_incumbent: Optional[int] = None
    witnesses: Dict[bytes, dict] = {}
    baseline = 1

    best_g: Dict[bytes, int] = {}
    parent: List[int] = []
    action_of: List[Optional[Action]] = []
    origin_of: List[int] = []
    g_of: List[int] = []
    ident_ord_of: List[bytes] = []
    ident_sym_of: List[bytes] = []
    metrics_of: List[dict] = []

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

    def score_state(state) -> dict:
        by = all_lane_metrics(state)
        return {
            "by_suit": by,
            "fd": face_down_count(state),
            "empties": len(empty_column_indices(state)),
        }

    def push_all(node: int, g: int, scored: dict, seq_holder: List[int]) -> None:
        heapq.heappush(heaps["cost"], (g, seq_holder[0], node))
        seq_holder[0] += 1
        for suit in SUITS:
            heapq.heappush(
                heaps[suit],
                (*suit_lane_key(scored["by_suit"][suit], g), seq_holder[0], node),
            )
            seq_holder[0] += 1
        heapq.heappush(
            heaps["work"],
            (*workspace_key(scored["by_suit"], scored["fd"], scored["empties"], g), seq_holder[0], node),
        )
        seq_holder[0] += 1

    def note_progress(scored: dict, g: int) -> None:
        for suit in SUITS:
            m = dict(scored["by_suit"][suit])
            m["g"] = g
            if _better_progress(result.best_progress.get(suit), m, g):
                result.best_progress[suit] = m

    heaps: Dict[str, list] = {k: [] for k in LANES}
    seq_holder = [0]
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
        st0 = unpack_state(ident_ord)
        scored = score_state(st0)
        ident_sym_of.append(ident_sym)
        ident_ord_of.append(ident_ord)
        parent.append(-1)
        action_of.append(None)
        origin_of.append(origin)
        g_of.append(g0)
        metrics_of.append(scored)
        node = len(ident_sym_of) - 1
        if g0 <= ceiling:
            push_all(node, g0, scored, seq_holder)
        note_progress(scored, g0)
        result.min_g = g0 if result.min_g is None else min(result.min_g, g0)
        result.max_g = g0 if result.max_g is None else max(result.max_g, g0)
    result.unique = len(best_g)
    seen_expand: Dict[bytes, int] = {}
    print(f"CAF2 start unique={result.unique} sources={len(roots)} lanes={list(LANES)}", flush=True)

    lane_i = 0
    empty_streak = 0
    while empty_streak < len(LANES):
        now = time.perf_counter()
        if now >= deadline:
            result.stop_reason = "time limit"
            break
        if (result.expanded & 2047) == 0 and note_rss():
            result.stop_reason = "rss abort"
            break
        if result.expanded and result.expanded % 4096 == 0:
            print(
                f"CAF2 exp={result.expanded} unique={result.unique} inc={current_incumbent} "
                f"wit={len(witnesses)} live={ {k: len(heaps[k]) for k in LANES} }",
                flush=True,
            )
        lane = LANES[lane_i % len(LANES)]
        lane_i += 1
        heap = heaps[lane]
        if not heap:
            empty_streak += 1
            continue
        result.lane_pops[lane] += 1
        rec_t = heapq.heappop(heap)
        node = rec_t[-1]
        ident_sym = ident_sym_of[node]
        g = g_of[node]
        if g != best_g.get(ident_sym) or g > ceiling:
            result.stale_skips += 1
            result.lane_stale[lane] += 1
            empty_streak = 0
            continue
        if seen_expand.get(ident_sym, 10**9) <= g:
            result.stale_skips += 1
            result.lane_stale[lane] += 1
            empty_streak = 0
            continue
        empty_streak = 0
        seen_expand[ident_sym] = g
        state = unpack_state(ident_ord_of[node])
        if len(state.foundations) >= 2:
            continue
        if state.stock:
            result.sd5_expanded = True
        actions, _ = engine_tableau_actions(state)
        result.expanded += 1
        result.lane_exp[lane] += 1
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
                scored = score_state(state)
                child_node = len(ident_sym_of)
                ident_sym_of.append(child_sym)
                ident_ord_of.append(child_ord)
                parent.append(node)
                action_of.append(action)
                origin_of.append(origin_of[node])
                g_of.append(child_g)
                metrics_of.append(scored)
                result.min_g = child_g if result.min_g is None else min(result.min_g, child_g)
                result.max_g = child_g if result.max_g is None else max(result.max_g, child_g)
                note_progress(scored, child_g)
                nfound = len(state.foundations)
                if nfound > baseline:
                    if nfound != 2:
                        result.accounting_fail = True
                    src = roots[origin_of[node]]
                    suits = foundation_suits(state)
                    new_suit = suits[-1] if suits else None
                    rec_w = {
                        "origin": origin_of[node],
                        "g": child_g,
                        "root_g": int(src["g"]),
                        "continuation_mw": child_g - int(src["g"]),
                        "actions": dump_actions(reconstruct(child_node)),
                        "full_actions": dump_actions(as_actions(src["full_actions"]) + reconstruct(child_node)),
                        "final_action": dump_actions([action])[0],
                        "ordered_digest": child_ord.hex(),
                        "symmetry_digest": child_sym.hex(),
                        "suit": new_suit,
                        "suit_name": SUIT_NAMES.get(new_suit or "", new_suit),
                        "foundation_count": nfound,
                        "foundation_suits": suits,
                        "timing": src["timing"],
                        "category": src.get("category"),
                        "prep_depth": src.get("prep_depth"),
                        "prep_cost": src.get("prep_cost"),
                        "fd": face_down_count(state),
                        "empties": [i + 1 for i in empty_column_indices(state)],
                        "lane": lane,
                        "metrics": scored["by_suit"],
                    }
                    if child_sym not in witnesses or child_g < witnesses[child_sym]["g"]:
                        witnesses[child_sym] = rec_w
                    if result.first_s is None:
                        result.first_s = time.perf_counter() - started
                        result.first_unique = result.unique
                        result.first_g = child_g
                        result.first_suit = new_suit
                        result.first_timing = src["timing"]
                        result.first_category = src.get("category")
                        result.first_root_g = int(src["g"])
                        print(
                            f"FIRST_F2 g={child_g} suit={new_suit} timing={src['timing']} "
                            f"lane={lane} unique={result.unique} t={result.first_s:.2f}s",
                            flush=True,
                        )
                    if current_incumbent is None or child_g < current_incumbent:
                        current_incumbent = child_g
                        result.incumbent = child_g
                        ceiling = min(cost_ceiling, current_incumbent + harvest_slack)
                    continue
                push_all(child_node, child_g, scored, seq_holder)
            finally:
                _restore(state, cap)
        if result.stop_reason in ("unique limit", "time limit", "rss abort"):
            break
        live = []
        for k in LANES:
            while heaps[k] and (
                g_of[heaps[k][0][-1]] != best_g.get(ident_sym_of[heaps[k][0][-1]])
                or g_of[heaps[k][0][-1]] > ceiling
            ):
                heapq.heappop(heaps[k])
            if heaps[k]:
                live.append(g_of[heaps[k][0][-1]])
        if current_incumbent is not None and live and min(live) > current_incumbent + harvest_slack:
            result.stop_reason = "harvested"
            break
    if not result.stop_reason:
        result.stop_reason = "complete"
    live_g = []
    for k in LANES:
        if heaps[k]:
            live_g.append(g_of[heaps[k][0][-1]])
    if live_g:
        result.min_live_g = min(live_g)
        result.closed_g = min(live_g) - 1
    elif current_incumbent is not None:
        result.closed_g = current_incumbent + harvest_slack
    else:
        result.closed_g = ceiling
    f = current_incumbent
    kept: List[dict] = []
    if f is not None:
        eligible = [w for w in witnesses.values() if w["g"] <= f + harvest_slack]
        eligible.sort(key=lambda w: (w["g"], w.get("suit") or "", w.get("timing") or "", w["ordered_digest"]))
        buckets: Dict[tuple, List[dict]] = defaultdict(list)
        for w in eligible:
            buckets[(w.get("suit"), w.get("timing"), w["g"] - f)].append(w)
        seen = set()
        while len(kept) < harvest_limit:
            progressed = False
            for key in sorted(buckets, key=str):
                while buckets[key]:
                    w = buckets[key].pop(0)
                    if w["symmetry_digest"] in seen:
                        continue
                    seen.add(w["symmetry_digest"])
                    kept.append(w)
                    progressed = True
                    break
                if len(kept) >= harvest_limit:
                    break
            if not progressed:
                break
    result.witnesses = kept
    result.elapsed_s = time.perf_counter() - started
    result.peak_rss_mb = peak
    return result


def choose_verdict(p: dict) -> Tuple[str, str]:
    if not p.get("all_replay_ok"):
        return "CONTRACT_FAILURE", "root replay failed"
    if p.get("accounting_fail") or p.get("replay_fail"):
        return "CONTRACT_FAILURE", "Foundation-2 replay or accounting disagreed with the engine"
    if p.get("reached"):
        return "COMPONENT_AWARE_FOUNDATION2_REACHED", "replay-valid second foundation found"
    improved = p.get("topology_improved")
    stop = p.get("stop_reason")
    if improved:
        return "COMPONENT_AWARE_SEARCH_IMPROVES_TOPOLOGY_NO_F2", "no F2, but descendants beat v0.55 root component classes"
    if stop in ("unique limit", "rss abort"):
        return "COMPONENT_AWARE_SEARCH_STATE_EXPLOSION", "unique/RSS envelope exhausted without Foundation 2"
    return "COMPONENT_AWARE_FOUNDATION2_NOT_FOUND", "bounded experiment finished without F2 or a new topology class"
