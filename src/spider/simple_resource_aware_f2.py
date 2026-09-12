"""Research-only v0.54 resource-aware post-SD5 Foundation-2 search.

Exact UCS from all 720 DEAL_NOW roots plus the v0.53 PREP_THEN_DEAL
portfolio members.  Identity is pack_post_stock_symmetry_state.
No suit target, no low-tail constraint, no Deal, no Foundation 3.
"""

from __future__ import annotations

import heapq
import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state, unpack_state
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, dump_actions, opening_state
from spider.simple_final_deal_timing import foundation_suits, same_suit_components
from spider.simple_progressive_solver import _capture, _restore, _rss_mb, apply_action, step_cost
from spider.simple_workspace_reachability import empty_column_indices, engine_tableau_actions, face_down_count

ROOT = Path(__file__).resolve().parents[2]
DEAL_NOW_PATH = ROOT / "docs" / "research" / "post_sd5_deal_now_roots_v0_44.json"
PORT_V053 = ROOT / "docs" / "research" / "sd5_resource_aware_portfolio_v0_53.json"
EXPECTED_DEAL_NOW = 720
EXPECTED_PREP_APPROX = 244
COST_CEILING = 110
SEARCH_UNIQUE = 600_000
SEARCH_TIME_S = 420.0
SEARCH_RSS_MB = 2.5 * 1024.0
HARVEST_SLACK = 3
HARVEST_LIMIT = 128
SUIT_NAMES = {"s": "Spades", "h": "Hearts", "d": "Diamonds", "c": "Clubs"}

RANK_F2 = 0
RANK_JOIN = 1
RANK_REVEAL = 2
RANK_EMPTY = 3
RANK_LONG = 4
RANK_OTHER = 5


def would_remove_foundation(state: SpiderState, action: Action) -> bool:
    if action == ("deal",):
        return False
    src, dst, k = action
    run = state.columns[src].face_up[-k:]
    combined = state.columns[dst].face_up + run
    if len(combined) < 13:
        return False
    tail = combined[-13:]
    return tail[0].rank == 13 and SpiderState.is_movable_run(tail)


def annotate_f2_order(state: SpiderState, action: Action) -> int:
    """Ordering only. Never legality."""

    if action == ("deal",):
        return 9
    if would_remove_foundation(state, action):
        return RANK_F2
    src, dst, k = action
    sc = state.columns[src]
    dc = state.columns[dst]
    run = sc.face_up[-k:]
    head = run[0]
    dest_top = dc.top()
    if dest_top is not None and dest_top.suit == head.suit and dest_top.rank == head.rank + 1:
        return RANK_JOIN
    if k == len(sc.face_up) and sc.face_down:
        return RANK_REVEAL
    if k == len(sc.face_up) and not sc.face_down:
        return RANK_EMPTY
    if k >= 3 and all(c.suit == head.suit for c in run):
        return RANK_LONG
    return RANK_OTHER


def _replay_root(opening: SpiderState, rec: dict, *, timing: str) -> Optional[dict]:
    end = opening.clone()
    try:
        cost = replay_actions(end, as_actions(rec["full_actions"]))
    except Exception:
        return None
    want = int(rec.get("g", rec.get("full_cost", -1)))
    ok = (
        cost == want
        and stock_rows(end) == 0
        and len(end.foundations) == 1
        and end.foundations[0][0].suit == "s"
        and (not rec.get("ordered_digest") or pack_state(end).hex() == rec["ordered_digest"])
    )
    if not ok:
        return None
    ident_ord = pack_state(end)
    ident_sym = pack_post_stock_symmetry_state(end)
    return {
        "g": cost,
        "timing": timing,
        "timings": [timing],
        "full_actions": dump_actions(as_actions(rec["full_actions"])),
        "ordered_digest": ident_ord.hex(),
        "symmetry_digest": ident_sym.hex(),
        "lineages": list(rec.get("lineages") or []),
        "category": rec.get("portfolio_cat"),
        "categories": [rec.get("portfolio_cat")] if rec.get("portfolio_cat") else [],
        "best_suit": rec.get("best_suit"),
        "direct_len": rec.get("direct_len"),
        "access": rec.get("access"),
        "prep_depth": rec.get("prep_depth", 0 if timing == "DEAL_NOW" else rec.get("prep_depth")),
        "prep_cost": rec.get("prep_cost", 0 if timing == "DEAL_NOW" else rec.get("prep_cost")),
        "empty_in_one": rec.get("empty_in_one"),
        "foundations": 1,
        "stock_rows": 0,
    }


def load_deal_now_roots(opening: Optional[SpiderState] = None) -> dict:
    opening = opening or opening_state()
    raw = json.loads(DEAL_NOW_PATH.read_text(encoding="utf-8"))
    rows = list(raw.get("states") or [])
    fail = 0
    kept = []
    for rec in rows:
        item = _replay_root(opening, rec, timing="DEAL_NOW")
        if item is None:
            fail += 1
            continue
        item["prep_depth"] = 0
        item["prep_cost"] = 0
        kept.append(item)
    return {
        "raw": len(rows),
        "expected": EXPECTED_DEAL_NOW,
        "n": len(kept),
        "replay_fail": fail,
        "all_replay_ok": fail == 0 and len(rows) == EXPECTED_DEAL_NOW,
        "cost_counts": {str(k): int(v) for k, v in sorted(Counter(r["g"] for r in kept).items())},
        "states": kept,
    }


def load_prep_roots(opening: Optional[SpiderState] = None) -> dict:
    opening = opening or opening_state()
    raw = json.loads(PORT_V053.read_text(encoding="utf-8"))
    rows = [r for r in list(raw.get("states") or []) if r.get("timing") == "PREP_THEN_DEAL"]
    fail = 0
    kept = []
    for rec in rows:
        item = _replay_root(opening, rec, timing="PREP_THEN_DEAL")
        if item is None:
            fail += 1
            continue
        kept.append(item)
    return {
        "raw": len(rows),
        "expected_approx": EXPECTED_PREP_APPROX,
        "n": len(kept),
        "replay_fail": fail,
        "all_replay_ok": fail == 0 and bool(kept),
        "categories": dict(Counter(r.get("category") for r in kept)),
        "cost_counts": {str(k): int(v) for k, v in sorted(Counter(r["g"] for r in kept).items())},
        "states": kept,
    }


def union_roots(deal_now: Sequence[dict], prep: Sequence[dict]) -> dict:
    classes: Dict[bytes, dict] = {}
    convergences = 0
    for rec in list(deal_now) + list(prep):
        ident = bytes.fromhex(rec["symmetry_digest"])
        prev = classes.get(ident)
        if prev is None:
            item = dict(rec)
            item["timings"] = list(rec.get("timings") or [rec["timing"]])
            item["categories"] = list(rec.get("categories") or [])
            item["lineages"] = list(rec.get("lineages") or [])
            classes[ident] = item
            continue
        timings = sorted(set(prev["timings"]) | set(rec.get("timings") or [rec["timing"]]))
        if rec["timing"] != prev["timing"] or (len(timings) > 1):
            convergences += 1
        if rec["g"] < prev["g"]:
            item = dict(rec)
            item["timings"] = timings
            item["categories"] = sorted(set((prev.get("categories") or []) + (rec.get("categories") or [])))
            item["lineages"] = sorted(set((prev.get("lineages") or []) + (rec.get("lineages") or [])))
            item["timing"] = "MULTIPLE" if len(timings) > 1 else rec["timing"]
            classes[ident] = item
        else:
            prev["timings"] = timings
            prev["categories"] = sorted(set((prev.get("categories") or []) + (rec.get("categories") or [])))
            prev["lineages"] = sorted(set((prev.get("lineages") or []) + (rec.get("lineages") or [])))
            if len(timings) > 1:
                prev["timing"] = "MULTIPLE"
    kept = sorted(classes.values(), key=lambda r: (r["g"], r["ordered_digest"]))
    return {
        "raw_deal_now": len(deal_now),
        "raw_prep": len(prep),
        "combined_raw": len(deal_now) + len(prep),
        "symmetry_unique": len(kept),
        "convergences": convergences,
        "cost_counts": {str(k): int(v) for k, v in sorted(Counter(r["g"] for r in kept).items())},
        "timing": dict(Counter(r["timing"] for r in kept)),
        "prep_categories": dict(Counter(c for r in kept if r["timing"] != "DEAL_NOW" for c in (r.get("categories") or []))),
        "states": kept,
    }


@dataclass
class F2Result:
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
    first_root_g: Optional[int] = None
    first_continuation: Optional[int] = None
    first_action: Optional[list] = None
    sd5_expanded: bool = False
    witnesses: List[dict] = field(default_factory=list)
    min_live_g: Optional[int] = None
    closed_g: Optional[int] = None
    accounting_fail: bool = False


def search_foundation2(
    roots: Sequence[dict],
    *,
    max_unique: int = SEARCH_UNIQUE,
    time_limit_s: float = SEARCH_TIME_S,
    rss_abort_mb: float = SEARCH_RSS_MB,
    cost_ceiling: int = COST_CEILING,
    harvest_slack: int = HARVEST_SLACK,
    harvest_limit: int = HARVEST_LIMIT,
) -> F2Result:
    started = time.perf_counter()
    deadline = started + time_limit_s
    result = F2Result()
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
        heapq.heappush(heap, (g_of[node], 0, seq, node))
        seq += 1
    seen_expand: Dict[bytes, int] = {}
    print(
        f"F2 start unique={result.unique} sources={len(roots)} ceiling={ceiling}",
        flush=True,
    )

    while heap:
        now = time.perf_counter()
        if now >= deadline:
            result.stop_reason = "time limit"
            break
        if (result.expanded & 2047) == 0 and note_rss():
            result.stop_reason = "rss abort"
            break
        if result.expanded and result.expanded % 8192 == 0:
            print(
                f"F2 exp={result.expanded} unique={result.unique} inc={current_incumbent} "
                f"wit={len(witnesses)} heap={len(heap)} live_g={heap[0][0] if heap else None}",
                flush=True,
            )
        g, _rk, _s, node = heapq.heappop(heap)
        ident_sym = ident_sym_of[node]
        if g != best_g.get(ident_sym) or g > ceiling:
            continue
        if seen_expand.get(ident_sym, 10**9) <= g:
            continue
        seen_expand[ident_sym] = g
        state = unpack_state(ident_ord_of[node])
        if len(state.foundations) > baseline:
            continue
        if state.stock:
            result.sd5_expanded = True
        actions, _ = engine_tableau_actions(state)
        ranked = []
        for action in actions:
            if action == ("deal",):
                result.sd5_expanded = True
                continue
            ranked.append((annotate_f2_order(state, action), action))
        ranked.sort(key=lambda t: (t[0], t[1]))
        result.expanded += 1
        for rank, action in ranked:
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
                depth_of.append(depth_of[node] + 1)
                origin_of.append(origin_of[node])
                g_of.append(child_g)
                hit = len(state.foundations) > baseline
                if hit:
                    if len(state.foundations) != 2:
                        result.accounting_fail = True
                    src = roots[origin_of[node]]
                    suits = foundation_suits(state)
                    new_suit = suits[-1] if suits else None
                    rec_w = {
                        "origin": origin_of[node],
                        "g": child_g,
                        "root_g": int(src["g"]),
                        "continuation_mw": child_g - int(src["g"]),
                        "depth": depth_of[node] + 1,
                        "actions": dump_actions(reconstruct(child_node)),
                        "full_actions": dump_actions(as_actions(src["full_actions"]) + reconstruct(child_node)),
                        "final_action": dump_actions([action])[0],
                        "ordered_digest": child_ord.hex(),
                        "symmetry_digest": child_sym.hex(),
                        "suit": new_suit,
                        "suit_name": SUIT_NAMES.get(new_suit or "", new_suit),
                        "foundation_count": len(state.foundations),
                        "foundation_suits": suits,
                        "timing": src["timing"],
                        "timings": list(src.get("timings") or [src["timing"]]),
                        "category": src.get("category"),
                        "categories": list(src.get("categories") or []),
                        "lineages": list(src.get("lineages") or []),
                        "prep_depth": src.get("prep_depth"),
                        "prep_cost": src.get("prep_cost"),
                        "fd": face_down_count(state),
                        "empties": [i + 1 for i in empty_column_indices(state)],
                        "components": same_suit_components(state),
                    }
                    if child_sym not in witnesses or child_g < witnesses[child_sym]["g"]:
                        witnesses[child_sym] = rec_w
                    if result.first_s is None:
                        result.first_s = time.perf_counter() - started
                        result.first_unique = result.unique
                        result.first_g = child_g
                        result.first_suit = new_suit
                        result.first_timing = src["timing"]
                        result.first_root_g = int(src["g"])
                        result.first_continuation = child_g - int(src["g"])
                        result.first_action = dump_actions([action])[0]
                        print(
                            f"FIRST_F2 g={child_g} suit={new_suit} timing={src['timing']} "
                            f"root_g={src['g']} unique={result.unique} t={result.first_s:.2f}s",
                            flush=True,
                        )
                    if current_incumbent is None or child_g < current_incumbent:
                        current_incumbent = child_g
                        result.incumbent = child_g
                        ceiling = min(cost_ceiling, current_incumbent + harvest_slack)
                    continue
                heapq.heappush(heap, (child_g, rank, seq, child_node))
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
    if heap:
        result.min_live_g = heap[0][0]
        result.closed_g = heap[0][0] - 1
    elif current_incumbent is not None:
        result.closed_g = current_incumbent + harvest_slack
        result.min_live_g = None
    else:
        result.closed_g = ceiling
        result.min_live_g = None
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
        return "SOURCE_REPLAY_FAILURE", "DEAL_NOW or PREP roots failed replay"
    if p.get("accounting_fail"):
        return "FOUNDATION_ACCOUNTING_CONTRACT_FAILURE", "engine foundation count was not exactly 2"
    if p.get("reached"):
        timings = set(p.get("witness_timings") or [])
        timings.discard("MULTIPLE")
        if "DEAL_NOW" in timings and "PREP_THEN_DEAL" in timings:
            return "FOUNDATION2_REACHED_FROM_MULTIPLE_ORIGINS", "Foundation 2 from both DEAL_NOW and PREP roots"
        if p.get("first_timing") == "PREP_THEN_DEAL" or timings == {"PREP_THEN_DEAL"}:
            return "FOUNDATION2_REACHED_FROM_PREP", "first Foundation 2 descended from a resource-aware PREP root"
        return "FOUNDATION2_REACHED_FROM_DEAL_NOW", "first Foundation 2 descended from a DEAL_NOW root"
    stop = p.get("stop_reason")
    if stop in ("unique limit", "rss abort"):
        return "RESOURCE_AWARE_SEARCH_STATE_EXPLOSION", "Foundation 2 not found before unique/RSS limit"
    if stop in ("time limit", "complete", "harvested") or p.get("search_attempted"):
        return "RESOURCE_AWARE_FOUNDATION2_NOT_FOUND", "no Foundation 2 inside MW<=110 from the condensed root union"
    return "INCONCLUSIVE", "resource-aware Foundation-2 search finished without a classified outcome"
