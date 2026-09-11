"""Research-only SD4 Diamond operational cut: expose unique 2D and 5D.

Does not apply the Heart AH->2D parking macro.  SD4 legal, SD5 withheld.
DIAMOND_READY_CUT is 2D and 5D both face-up and unburied.
"""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from spider.engine import SpiderState
from spider.metrics import Action
from spider.packed_state import pack_state, unpack_state
from spider.rules import MW_RULES, deal_cost
from spider.simple_current_horizon import occurrence_counts
from spider.simple_deal1_preview import stock_rows
from spider.simple_foundation_horizon import pretty_card
from spider.simple_foundation_race import suit_foundation_count
from spider.simple_progressive_solver import _capture, _restore, _rss_mb, apply_action, step_cost
from spider.simple_sd4_horizon import EXPECTED_SD4, legal_sd4_episode_actions
from spider.simple_workspace_reachability import empty_column_indices, engine_tableau_actions, face_down_count

C9 = 8  # column 9
C4 = 3  # column 4


def unique_exposed_top(state: SpiderState, suit: str, rank: int) -> Optional[dict]:
    rec = occurrence_counts(state, suit, rank)
    if rec["current_count"] != 1 or not rec["tableau"]:
        return None
    occ = rec["tableau"][0]
    if occ.get("face_up") and occ.get("top") and not occ.get("face_up_above"):
        return occ
    return None


def is_diamond_ready(state: SpiderState) -> bool:
    """Unique current 2D and 5D are both face-up and unburied."""

    return unique_exposed_top(state, "d", 2) is not None and unique_exposed_top(state, "d", 5) is not None


def card_cover(state: SpiderState, suit: str, rank: int) -> dict:
    rec = occurrence_counts(state, suit, rank)
    if rec["current_count"] != 1 or not rec["tableau"]:
        return {"present": False, "current_count": rec["current_count"]}
    occ = rec["tableau"][0]
    return {
        "present": True,
        "current_count": rec["current_count"],
        "future_stock": rec["future_stock_count"],
        "column_0": occ["column_0"],
        "column_1": occ["column_1"],
        "face_up": occ["face_up"],
        "top": occ.get("top"),
        "face_up_above": occ.get("face_up_above") or [],
        "cards_above": occ.get("cards_above") or 0,
    }


def diamond_unique_ranks(state: SpiderState) -> List[str]:
    from spider.cards import rank_str

    hard = []
    for rank in range(1, 14):
        rec = occurrence_counts(state, "d", rank)
        if rec["hard"]:
            hard.append(rank_str(rank))
    return hard


def legal_dests_for_top(state: SpiderState, col: int) -> List[dict]:
    if not state.columns[col].face_up:
        return []
    top = pretty_card(state.columns[col].face_up[-1])
    out = []
    for action in engine_tableau_actions(state)[0]:
        src, dst, k = action
        if src != col or k != 1:
            continue
        dest_top = state.columns[dst].top()
        out.append(
            {
                "action": [src, dst, k],
                "src_1": src + 1,
                "dst_1": dst + 1,
                "moving": top,
                "onto": None if dest_top is None else pretty_card(dest_top),
                "empty": dest_top is None,
            }
        )
    return out


def continuation_lb_audit(state: SpiderState) -> dict:
    """SD4 is required (no current 2D). Covering cards of 5D after SD4 must leave."""

    reasons = []
    d2_now = occurrence_counts(state, "d", 2)
    if d2_now["current_count"] != 0:
        reasons.append("2D already current before SD4")
    if stock_rows(state) != 2:
        reasons.append("SD4 is not next")
    if deal_cost() < 1:
        reasons.append("deal_cost < 1")
    after = state.clone()
    apply_action(after, ("deal",))
    cover = card_cover(after, "d", 5)
    d2 = card_cover(after, "d", 2)
    n_above = int(cover.get("cards_above") or 0)
    costs = []
    if not d2.get("top"):
        reasons.append("2D is not top after SD4")
    if n_above < 1:
        reasons.append("5D already exposed after SD4")
    # Each card above 5D must leave in its own action if they are not one movable run
    # that includes exposing 5D (k would have to be all above, uncovering 5D which is already up).
    # Moving the entire face-up packet off 5D would move 5D too if 5D is in face_up.
    # So the above cards must leave without taking 5D: typically one-at-a-time from the top.
    lb = 1 + n_above  # deal + each covering face-up card
    # Verify top-of-5D-column leave costs >= 1
    if cover.get("present"):
        col = cover["column_0"]
        for action in engine_tableau_actions(after)[0]:
            if action[0] == col and action[2] == 1:
                costs.append(step_cost(after, action))
        if costs and min(costs) < 1:
            reasons.append(f"covering-card leave can be 0: {costs}")
        if not costs and n_above:
            reasons.append("covering card on 5D has no legal move")
            # LB still at least deal+1 if a later empty is created; withdraw if stuck
    valid = not reasons
    return {
        "valid": valid,
        "lb": lb if valid else None,
        "n_cover_after_sd4": n_above,
        "cover_after_sd4": cover.get("face_up_above"),
        "deal_cost": deal_cost(),
        "top_leave_costs": costs,
        "reasons": reasons,
        "rationale": (
            f"2D is absent before SD4, so Deal costs 1. After SD4, unique 5D has {n_above} "
            f"face-up card(s) above it; each must leave before 5D is unburied. "
            f"Local continuation LB = {1 + n_above}."
            if valid
            else "Lower bound withdrawn: " + "; ".join(reasons)
        ),
    }


def apply_actions(state: SpiderState, actions: Sequence[Action]) -> dict:
    step_costs = []
    fail = None
    total = 0
    for i, action in enumerate(actions):
        if action == ("deal",):
            legal = stock_rows(state) == 2 and state.can_deal(MW_RULES)
        else:
            legal = state.can_move(*action)
        if not legal:
            fail = {"index": i, "action": ["deal"] if action == ("deal",) else list(action)}
            break
        cost = step_cost(state, action)
        apply_action(state, action)
        total += cost
        step_costs.append(cost)
    return {
        "legal": fail is None,
        "failure": fail,
        "step_costs": step_costs,
        "continuation": total,
        "ready": is_diamond_ready(state) if fail is None else False,
        "ah_on_2d": _ah_on_2d(state),
        "h9_up": pretty_card(state.columns[1].face_up[-1]) == "9H" if state.columns[1].face_up else False,
    }


def _ah_on_2d(state: SpiderState) -> bool:
    c4 = state.columns[C4].face_up
    return len(c4) >= 2 and pretty_card(c4[-1]) == "AH" and pretty_card(c4[-2]) == "2D"


def enumerate_predicted_macros(state: SpiderState) -> List[dict]:
    """SD4 then legal clears of cards above 5D, keeping 2D exposed. No AH->2D."""

    variants = []
    if stock_rows(state) != 2:
        return variants
    after = state.clone()
    apply_action(after, ("deal",))
    cover = card_cover(after, "d", 5)
    if not cover.get("present"):
        return variants
    col = cover["column_0"]
    above = list(cover.get("face_up_above") or [])
    # One-move: top of 5D column leaves and 5D is then top.
    for dest in legal_dests_for_top(after, col):
        child = after.clone()
        action = tuple(dest["action"])
        apply_action(child, action)
        if is_diamond_ready(child) and not _ah_on_2d(child):
            variants.append(
                {
                    "kind": "sd4_then_one",
                    "actions": [("deal",), action],
                    "jh_dest": dest["onto"],
                    "moving": dest["moving"],
                    "ready": True,
                    "continuation": 1 + step_cost(after, action),
                    "ah_on_2d": False,
                }
            )
    # Two-move: JH (or top) then next card (4H) if present.
    if len(above) >= 1:
        for d1 in legal_dests_for_top(after, col):
            mid = after.clone()
            a1 = tuple(d1["action"])
            apply_action(mid, a1)
            if _ah_on_2d(mid):
                continue
            for d2 in legal_dests_for_top(mid, col):
                end = mid.clone()
                a2 = tuple(d2["action"])
                apply_action(end, a2)
                if is_diamond_ready(end) and not _ah_on_2d(end):
                    variants.append(
                        {
                            "kind": "sd4_then_two",
                            "actions": [("deal",), a1, a2],
                            "jh_dest": d1["onto"],
                            "four_dest": d2["onto"],
                            "moving": [d1["moving"], d2["moving"]],
                            "ready": True,
                            "continuation": 1 + step_cost(after, a1) + step_cost(mid, a2),
                            "ah_on_2d": False,
                        }
                    )
    return variants


@dataclass
class CutResult:
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
    sd5_expanded: bool = False
    max_depth: int = 0
    witnesses: List[dict] = field(default_factory=list)
    ah_on_2d_generated: int = 0


def search_diamond_ready(  # SD4 may occur immediately or after tableau preparation.
    sources: Sequence[SpiderState],
    origin_paths: Sequence[Sequence[Action]],
    source_g: Sequence[int],
    *,
    max_depth: int = 8,
    max_unique: int = 250_000,
    time_limit_s: float = 300.0,
    rss_abort_mb: float = 2 * 1024.0,
    harvest_slack: int = 3,
    harvest_limit: int = 256,
) -> CutResult:
    started = time.perf_counter()
    deadline = started + time_limit_s
    result = CutResult()
    peak = _rss_mb()
    best_g: Dict[bytes, int] = {}
    parent: List[int] = []
    action_of: List[Optional[Action]] = []
    depth_of: List[int] = []
    origin_of: List[int] = []
    g_of: List[int] = []
    ident_of: List[bytes] = []
    witnesses: Dict[bytes, dict] = {}
    current_incumbent: Optional[int] = None
    ceiling = 10**9

    def note_rss() -> bool:
        nonlocal peak
        rss = _rss_mb()
        if rss is not None and (peak is None or rss > peak):
            peak = rss
        return rss is not None and rss >= rss_abort_mb

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
        g0 = int(source_g[origin])
        if ident in best_g:
            if g0 < best_g[ident]:
                best_g[ident] = g0
                idx = ident_of.index(ident)
                g_of[idx] = g0
                origin_of[idx] = origin
            continue
        best_g[ident] = g0
        ident_of.append(ident)
        parent.append(-1)
        action_of.append(None)
        depth_of.append(0)
        origin_of.append(origin)
        g_of.append(g0)
    result.unique = len(best_g)
    heap: List[tuple] = []
    seq = 0
    for node in range(len(ident_of)):
        heapq.heappush(heap, (g_of[node], depth_of[node], seq, node))
        seq += 1
    seen_expand: Dict[bytes, int] = {}
    print(f"DREADY start unique={result.unique} depth<={max_depth}", flush=True)

    while heap:
        if time.perf_counter() >= deadline:
            result.stop_reason = "time limit"
            break
        if (result.expanded & 2047) == 0 and note_rss():
            result.stop_reason = "rss abort"
            break
        g, depth, _, node = heapq.heappop(heap)
        ident = ident_of[node]
        if g != best_g.get(ident):
            continue
        if seen_expand.get(ident, 10**9) <= g:
            continue
        if depth >= max_depth:
            continue
        if current_incumbent is not None and g > current_incumbent + harvest_slack:
            continue
        seen_expand[ident] = g
        state = unpack_state(ident)
        if is_diamond_ready(state):
            continue
        result.expanded += 1
        for action in legal_sd4_episode_actions(state):
            if action == ("deal",) and stock_rows(state) != 2:
                result.sd5_expanded = True
                continue
            cost = step_cost(state, action)
            child_g = g + cost
            if current_incumbent is not None and child_g > current_incumbent + harvest_slack:
                continue
            cap = _capture(state, action)
            try:
                apply_action(state, action)
                result.generated += 1
                if stock_rows(state) < 1:
                    result.sd5_expanded = True
                if _ah_on_2d(state):
                    result.ah_on_2d_generated += 1
                child_ident = pack_state(state)
                child_depth = depth + 1
                result.max_depth = max(result.max_depth, child_depth)
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
                depth_of.append(child_depth)
                origin_of.append(origin_of[node])
                g_of.append(child_g)
                if is_diamond_ready(state):
                    rec = {
                        "origin": origin_of[node],
                        "g": child_g,
                        "depth": child_depth,
                        "continuation": child_g - source_g[origin_of[node]],
                        "actions": [list(a) if a != ("deal",) else ["deal"] for a in reconstruct(child_node)],
                        "ordered_digest": child_ident.hex(),
                        "ah_on_2d": _ah_on_2d(state),
                        "stock_rows": stock_rows(state),
                    }
                    if child_ident not in witnesses or child_g < witnesses[child_ident]["g"]:
                        witnesses[child_ident] = rec
                    if result.first_s is None:
                        result.first_s = time.perf_counter() - started
                        result.first_unique = result.unique
                        result.first_g = child_g
                        print(
                            f"FIRST_DREADY g={child_g} depth={child_depth} unique={result.unique} "
                            f"t={result.first_s:.3f}s",
                            flush=True,
                        )
                    if current_incumbent is None or child_g < current_incumbent:
                        current_incumbent = child_g
                        result.incumbent = child_g
                    continue
                heapq.heappush(heap, (child_g, child_depth, seq, child_node))
                seq += 1
            finally:
                _restore(state, cap)
        if result.stop_reason in ("unique limit", "time limit", "rss abort"):
            break
        if current_incumbent is not None and len(witnesses) >= 64 and (deadline - time.perf_counter()) < 20:
            result.stop_reason = "harvested"
            break

    if not result.stop_reason:
        result.stop_reason = "frontier empty" if not heap else "complete"
    c = current_incumbent
    kept = []
    if c is not None:
        for rec in witnesses.values():
            if rec["g"] <= c + harvest_slack:
                kept.append(rec)
        kept.sort(key=lambda w: (w["g"], w["depth"], w["origin"]))
        kept = kept[:harvest_limit]
    result.witnesses = kept
    result.elapsed_s = time.perf_counter() - started
    result.peak_rss_mb = peak
    return result


def probe_diamond_foundation(state: SpiderState, g0: int, *, max_depth: int = 8, deadline: float, rss_abort_mb: float) -> dict:
    ident0 = pack_state(state)
    best = {ident0: g0}
    heap = [(g0, 0, 0, ident0)]
    seq = 0
    seen: Dict[bytes, int] = {}
    unique = 1
    expanded = 0
    live = False
    found = None
    visited: Set[bytes] = {ident0}
    while heap:
        if time.perf_counter() >= deadline:
            live = True
            break
        rss = _rss_mb()
        if rss is not None and rss >= rss_abort_mb:
            live = True
            break
        g, depth, _, ident = heapq.heappop(heap)
        if g != best.get(ident):
            continue
        if seen.get(ident, 10**9) <= g:
            continue
        if depth >= max_depth:
            live = True
            continue
        seen[ident] = g
        st = unpack_state(ident)
        if stock_rows(st) < 1:
            continue
        expanded += 1
        actions, _ = engine_tableau_actions(st)
        for action in actions:
            cost = step_cost(st, action)
            cap = _capture(st, action)
            try:
                apply_action(st, action)
                child_ident = pack_state(st)
                child_g = g + cost
                prev = best.get(child_ident)
                if prev is not None and child_g >= prev:
                    continue
                best[child_ident] = child_g
                visited.add(child_ident)
                if prev is None:
                    unique += 1
                if suit_foundation_count(st, "d") >= 1:
                    found = {"g": child_g, "depth": depth + 1, "digest": child_ident.hex()}
                    break
                seq += 1
                heapq.heappush(heap, (child_g, depth + 1, seq, child_ident))
            finally:
                _restore(st, cap)
        if found:
            break
    if found:
        status = "FOUNDATION_WITHIN_8"
        dead = False
        live_flag = False
    elif live or heap:
        status = "LIVE_BEYOND_8"
        dead = False
        live_flag = True
    else:
        status = "EXACT_DEAD"
        dead = True
        live_flag = False
    return {
        "status": status,
        "found": bool(found),
        "dead": dead,
        "live": live_flag,
        "hit": found,
        "unique": unique,
        "expanded": expanded,
    }
