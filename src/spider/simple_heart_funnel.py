"""Research-only cost-aware Heart-1 funnel search.

g = corrected MobilityWare cost.  Exact pack_state identity.
SD3 is legal; SD4 is never expanded.  Target relevance is ordering only.
"""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import Action
from spider.packed_state import pack_state, unpack_state
from spider.rules import MW_RULES
from spider.simple_deal1_preview import stock_rows
from spider.simple_heart_backward import (
    JOIN_BREAK,
    LABEL_RANK,
    SD3_ACTION,
    action_allowed_at_level,
    annotate_action,
    build_dependency_map,
)
from spider.simple_progressive_solver import (
    _capture,
    _restore,
    _rss_mb,
    apply_action,
    classify_tier,
    is_deal,
    step_cost,
)
from spider.simple_workspace_reachability import engine_tableau_actions, face_down_count

HEART = "h"


def heart_foundation_count(state: SpiderState) -> int:
    return sum(1 for run in state.foundations if run and run[0].suit == HEART)


def foundation_suits(state: SpiderState) -> List[str]:
    return [run[0].suit for run in state.foundations if run]


def legal_episode_actions(state: SpiderState) -> List[Action]:
    """Tableau plus SD3.  SD4 (stock_rows==2) is withheld."""

    actions, _ = engine_tableau_actions(state)
    if stock_rows(state) == 3 and state.can_deal(MW_RULES):
        actions.append(("deal",))
    return actions


def classify_sd3_timing(local_actions: Sequence[Action], end: SpiderState) -> str:
    deals_local = [i for i, a in enumerate(local_actions) if a == ("deal",)]
    if not deals_local:
        return "HEART_BEFORE_SD3"
    if deals_local[0] == 0:
        return "HEART_AFTER_IMMEDIATE_SD3"
    return "HEART_AFTER_PREPARED_SD3"


@dataclass
class FunnelResult:
    unique: int = 0
    expanded: int = 0
    generated: int = 0
    duplicate_skips: int = 0
    cheaper_reopens: int = 0
    zero_cost_moves: int = 0
    max_depth: int = 0
    levels_reached: List[int] = field(default_factory=list)
    per_level: List[dict] = field(default_factory=list)
    elapsed_s: float = 0.0
    peak_rss_mb: Optional[float] = None
    stop_reason: str = ""
    incumbent: Optional[int] = None
    witnesses: List[dict] = field(default_factory=list)
    sd4_expanded: bool = False
    used_heuristic_prune: bool = False
    lower_bound: int = 0
    deal_expanded_as_sd3: bool = False
    all_legal_at_level3: bool = False


def cost_aware_heart_search(
    sources: Sequence[SpiderState],
    origin_paths: Sequence[Sequence[Action]],
    sd3: Sequence[Tuple[str, int]],
    *,
    max_unique_per_level: int = 2_500_000,
    time_limit_s: float = 1800.0,
    rss_abort_mb: float = 3 * 1024.0,
    start_level: int = 0,
    max_level: int = 3,
    incumbent: Optional[int] = None,
) -> FunnelResult:
    started = time.perf_counter()
    deadline = started + time_limit_s
    result = FunnelResult()
    peak = _rss_mb()

    def note_rss() -> bool:
        nonlocal peak
        rss = _rss_mb()
        if rss is not None and (peak is None or rss > peak):
            peak = rss
        return rss is not None and rss >= rss_abort_mb

    deps = [build_dependency_map(src, sd3) for src in sources]
    lbs = [d["lower_bound"]["mw_lower_bound"] for d in deps]
    result.lower_bound = min(lbs) if lbs else 0
    lb = result.lower_bound

    best_g: Dict[bytes, int] = {}
    parent: List[int] = []
    action_of: List[Action] = []
    depth_of: List[int] = []
    origin_of: List[int] = []
    g_of: List[int] = []
    ident_of: List[bytes] = []

    seq = 0
    heap: List[tuple] = []
    witnesses: Dict[bytes, dict] = {}
    current_incumbent = incumbent

    def reconstruct(node: int) -> List[Action]:
        path: List[Action] = []
        while node >= 0 and parent[node] >= 0:
            act = action_of[node]
            if act is not None:
                path.append(act)
            node = parent[node]
        path.reverse()
        return path

    for origin, src in enumerate(sources):
        ident = pack_state(src)
        if ident in best_g:
            continue
        best_g[ident] = 0
        ident_of.append(ident)
        parent.append(-1)
        action_of.append(None)  # type: ignore
        depth_of.append(0)
        origin_of.append(origin)
        g_of.append(0)
    result.unique = len(best_g)

    for level in range(start_level, max_level + 1):
        if time.perf_counter() >= deadline:
            result.stop_reason = "time limit"
            break
        if note_rss():
            result.stop_reason = "rss abort"
            break
        result.levels_reached.append(level)
        if level >= 3:
            result.all_legal_at_level3 = True
        level_unique = 0
        level_exp = 0
        level_gen = 0
        level_dups = 0
        level_reopen = 0
        heap = []
        seq = 0
        best_node: Dict[bytes, int] = {}
        for i, ident in enumerate(ident_of):
            if best_g.get(ident) == g_of[i]:
                best_node[ident] = i
        for ident, node in best_node.items():
            heapq.heappush(heap, (g_of[node], 9, 9, depth_of[node], seq, node, origin_of[node]))
            seq += 1
        seen_expand: Dict[bytes, int] = {}
        unique_at_level_start = result.unique
        unique_cap = max_unique_per_level
        levels_left = max_level - level + 1
        remaining_s = deadline - time.perf_counter()
        level_deadline = time.perf_counter() + max(45.0, remaining_s / max(1, levels_left))
        print(
            f"LEVEL {level} start unique={result.unique} heap={len(heap)} "
            f"level_budget_s={level_deadline - time.perf_counter():.0f}",
            flush=True,
        )
        while heap:
            now = time.perf_counter()
            if now >= deadline:
                result.stop_reason = "time limit"
                break
            if now >= level_deadline:
                result.stop_reason = ""
                break
            if (level_exp & 2047) == 0 and note_rss():
                result.stop_reason = "rss abort"
                break
            if (level_exp & 16383) == 0 and level_exp:
                print(
                    f"LEVEL {level} exp={level_exp} unique={result.unique} gen={result.generated} "
                    f"inc={current_incumbent} heap={len(heap)}",
                    flush=True,
                )
            g, _rel, _tier, depth, _seq, node, origin = heapq.heappop(heap)
            ident = ident_of[node]
            if g != g_of[node] or g != best_g.get(ident):
                continue
            if current_incumbent is not None and g + lb >= current_incumbent:
                continue
            if seen_expand.get(ident, 10**9) <= g:
                continue
            seen_expand[ident] = g
            state = unpack_state(ident)
            if heart_foundation_count(state) >= 1:
                continue
            actions = legal_episode_actions(state)
            level_exp += 1
            result.expanded += 1
            dep = deps[min(origin, len(deps) - 1)]
            for action in actions:
                is_sd3 = action == ("deal",)
                if is_sd3:
                    if stock_rows(state) != 3:
                        result.sd4_expanded = True
                        continue
                    result.deal_expanded_as_sd3 = True
                label = annotate_action(state, action, dep, sd3)
                tier_i = 0 if is_sd3 else int(classify_tier(state, action))
                if not action_allowed_at_level(label, tier_i, level, is_sd3):
                    continue
                cost = step_cost(state, action)
                if cost == 0:
                    result.zero_cost_moves += 1
                child_g = g + cost
                if current_incumbent is not None and child_g + lb >= current_incumbent:
                    continue
                cap = _capture(state, action)
                try:
                    apply_action(state, action)
                    level_gen += 1
                    result.generated += 1
                    if stock_rows(state) < 2:
                        result.sd4_expanded = True
                    child_ident = pack_state(state)
                    child_depth = depth + 1
                    result.max_depth = max(result.max_depth, child_depth)
                    prev = best_g.get(child_ident)
                    if prev is not None and child_g >= prev:
                        level_dups += 1
                        result.duplicate_skips += 1
                        continue
                    if prev is not None and child_g < prev:
                        level_reopen += 1
                        result.cheaper_reopens += 1
                    else:
                        result.unique += 1
                        level_unique += 1
                    if (result.unique - unique_at_level_start) >= unique_cap:
                        break
                    best_g[child_ident] = child_g
                    child_node = len(ident_of)
                    ident_of.append(child_ident)
                    parent.append(node)
                    action_of.append(action)
                    depth_of.append(child_depth)
                    origin_of.append(origin)
                    g_of.append(child_g)
                    if heart_foundation_count(state) >= 1:
                        local_path = reconstruct(child_node)
                        rec = {
                            "origin": origin,
                            "g": child_g,
                            "depth": child_depth,
                            "actions": [list(a) if a != ("deal",) else ["deal"] for a in local_path],
                            "timing": classify_sd3_timing(local_path, state),
                            "fd": face_down_count(state),
                            "stock_rows": stock_rows(state),
                            "foundations": len(state.foundations),
                            "foundation_suits": foundation_suits(state),
                            "empties": [i for i, c in enumerate(state.columns) if c.is_empty()],
                            "ordered_digest": child_ident.hex(),
                            "level": level,
                        }
                        if child_ident not in witnesses or child_g < witnesses[child_ident]["g"]:
                            witnesses[child_ident] = rec
                        if current_incumbent is None or child_g < current_incumbent:
                            current_incumbent = child_g
                            result.incumbent = child_g
                        continue
                    heapq.heappush(
                        heap,
                        (child_g, LABEL_RANK.get(label, 4), tier_i, child_depth, seq, child_node, origin),
                    )
                    seq += 1
                finally:
                    _restore(state, cap)
            if result.stop_reason in ("time limit", "rss abort"):
                break
        result.per_level.append(
            {
                "level": level,
                "unique_delta": level_unique,
                "expanded": level_exp,
                "generated": level_gen,
                "duplicate_skips": level_dups,
                "cheaper_reopens": level_reopen,
                "heap_empty": not heap,
                "incumbent": current_incumbent,
                "witnesses": len(witnesses),
            }
        )
        if result.stop_reason in ("time limit", "rss abort", "unique limit"):
            break
        if current_incumbent is not None:
            remaining = deadline - time.perf_counter()
            if remaining < 45:
                result.stop_reason = result.stop_reason or "incumbent held"
                break
        if level == max_level:
            result.stop_reason = result.stop_reason or ("frontier empty" if not heap else "max level")

    result.elapsed_s = time.perf_counter() - started
    result.peak_rss_mb = peak
    result.incumbent = current_incumbent
    if current_incumbent is not None:
        best = [w for w in witnesses.values() if w["g"] == current_incumbent]
        result.witnesses = sorted(best, key=lambda w: (w["g"], w["depth"], w["origin"]))
    else:
        result.witnesses = []
    if not result.stop_reason:
        result.stop_reason = "complete"
    return result
