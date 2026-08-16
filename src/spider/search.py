"""Bounded search primitives for Spider optimization."""

from __future__ import annotations

import heapq
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .deal_analysis import DealAnalysis
from .engine import SpiderState
from .hash import TranspositionTable, zobrist
from .heuristics import (
    card_exposure_value,
    finisher_heuristic,
    lower_bound_mw,
)
from .metrics import Action
from .move_lifecycle import (
    BoundedCompensatingBenefit,
    PlacementClass,
    assess_tableau_move,
    with_bounded_compensation,
)
from .rules import deal_cost, mw_move_cost

Move = Tuple[int, int, int]

_history: Dict[Move, int] = {}
_killer_moves: Dict[int, List[Move]] = {}


def clear_search_caches() -> None:
    _history.clear()
    _killer_moves.clear()


def dominance_filter(state: SpiderState, moves: List[Move]) -> List[Move]:
    lm = state.last_move
    if not lm or lm == ("deal",):
        return moves
    if isinstance(lm[0], str):
        return moves
    s_last, d_last, k_last, flipped, removed = lm
    pruned = []
    for s, d, k in moves:
        if s == d_last and d == s_last and k == k_last and not flipped and not removed:
            continue
        pruned.append((s, d, k))
    return pruned


def step_cost(state: SpiderState, move: Move) -> int:
    src, dst, k = move
    src_col = state.columns[src]
    dst_col = state.columns[dst]
    return mw_move_cost(
        cards_moved=k,
        source_face_up_count=len(src_col.face_up),
        dest_was_empty=dst_col.is_empty(),
        source_face_down_count=len(src_col.face_down),
    )


def order_moves(
    state: SpiderState,
    moves: List[Move],
    depth: int,
    jitter: float = 0.0,
    plan: "DealAnalysis" = None,
    round_index: int = 0,
) -> List[Move]:
    """Order moves with local bonuses (killers, same-suit, reveal, to-empty, length, history, jitter).

    When plan (the rich DealAnalysis with global suit clearance / exposure priorities)
    is provided, extra bonus is given to reveals of high plan-value cards (critical for
    early-eligible suits) and to same-suit builds on priority suits. This lets the
    pre-deal beam "plan towards exposing the right cards" per the upfront human-style
    reverse-engineering of the full stock.

    Permanent-move lifecycle is an ordering-only tie-break. A mixed-suit park
    receives an override bonus only when a one-ply bounded simulation finds
    more newly available zero-cost exits than its estimated rehandling debt and
    the park itself has a concrete exit route. This never prunes proof search.
    """
    killers = _killer_moves.get(depth, [])
    killer_set = set(killers)
    current_free = sum(
        step_cost(state, move) == 0 for move in state.enumerate_moves()
    )
    scored = []
    for src, dst, k in moves:
        src_col = state.columns[src]
        dst_col = state.columns[dst]
        run = src_col.face_up[-k:]
        lifecycle = assess_tableau_move(
            state, (src, dst, k), discover_exit=False
        )
        score = 0.0
        if (src, dst, k) in killer_set:
            score -= 5
        top = dst_col.top()
        same_suit_bonus = 3
        if plan is not None and top is not None and top.suit == run[0].suit:
            # extra if this suit is priority/early eligible in the global plan
            elig = plan.eligible_suits_by_round[round_index] if round_index < len(plan.eligible_suits_by_round) else set()
            pri = set(plan.priority_clearance_order[:2]) if plan.priority_clearance_order else set()
            if top.suit in (elig | pri):
                same_suit_bonus += 2
            score -= same_suit_bonus
        elif top and top.suit == run[0].suit:
            score -= 3
        if len(src_col.face_up) == k and src_col.face_down:
            reveal_bonus = 2
            if plan is not None:
                revealed = src_col.face_down[-1]
                reveal_bonus += card_exposure_value(revealed, plan, round_index)
            score -= reveal_bonus
        # Bounded compensation for a mixed park. Count only newly available
        # zero-cost exits and subtract explicit rehandling debt.
        enable_bonus = 0.0
        if lifecycle.placement_class == PlacementClass.MIXED_SUIT_PARK:
            try:
                lifecycle = assess_tableau_move(state, (src, dst, k))
                st = state.clone()
                st.move(src, dst, k)
                new_free = sum(
                    step_cost(st, move) == 0 for move in st.enumerate_moves()
                )
                expected_saving = float(max(0, new_free - current_free))
                if expected_saving > lifecycle.estimated_rehandling_cost:
                    lifecycle = with_bounded_compensation(
                        lifecycle,
                        BoundedCompensatingBenefit(
                            expected_saving=expected_saving,
                            evidence=(
                                "one-ply simulation creates "
                                f"{int(expected_saving)} additional zero-cost exits"
                            ),
                            override_reason=(
                                "bounded zero-cost exit saving exceeds park "
                                "rehandling debt"
                            ),
                        ),
                    )
                    if lifecycle.can_override_permanent_join:
                        enable_bonus = (
                            expected_saving
                            - lifecycle.estimated_rehandling_cost
                        )
            except Exception:
                pass
        score -= enable_bonus

        # Direct space-work reduction bonus: reward moves (especially parks from fd-bearing columns)
        # that lower the total visible face-up on columns that still have face-down. This is the
        # "clear the visible to create the gold spaces" signal the human uses; now reinforced in
        # move ordering (on top of the -4*sw in deal_aware heap priority and the sw term in best_deal_key).
        try:
            if src_col.face_down:  # moving a run off a column that can still yield a new space
                sw_before = sum(len(c.face_up) for c in state.columns if c.face_down)
                st = state.clone()
                st.move(src, dst, k)
                sw_after = sum(len(c.face_up) for c in st.columns if c.face_down)
                if sw_after < sw_before:
                    reduction = sw_before - sw_after
                    score -= min(reduction, 20) * 2.5  # v35: much stronger sw-reduction ordering (min 20 * 2.5) to more aggressively promote moves (incl catalytic parks) that net reduce visible work on fd columns. Complements the early budget boost and -30*sw heap for canon r0/r1 pre paths.
        except Exception:
            pass

        score -= min(k, 3)
        if top is None:
            score -= 2
        score -= _history.get((src, dst, k), 0)
        if jitter > 0:
            score -= random.random() * jitter
        scored.append((score, lifecycle.ordering_key(), src, dst, k))
    scored.sort()
    return [(s, d, k) for _, _lifecycle, s, d, k in scored]


def note_progress(depth: int, move: Move) -> None:
    _history[move] = _history.get(move, 0) + 1
    km = _killer_moves.get(depth, [])
    if move not in km:
        _killer_moves[depth] = ([move] + km)[:4]


@dataclass
class SearchResult:
    solved: bool
    actions: List[Action]
    mw_cost: int
    nodes: int
    seconds: float


def apply_move_on_clone(state: SpiderState, move: Move) -> Tuple[SpiderState, int]:
    st = state.clone()
    cost = st.move(*move)
    return st, cost


@dataclass
class SolverProgress:
    """Callbacks / stats for long-running optimization."""
    best_cost: int = 9999
    attempts: int = 0
    total_nodes: int = 0
    on_improvement: Optional[Callable[[int, List[Action]], None]] = None
    on_attempt_done: Optional[Callable[[bool, int, int], None]] = None


def bounded_ucs(
    root: SpiderState,
    *,
    upper_bound: int,
    max_nodes: int = 2_000_000,
    time_limit: float | None = None,
    progress: bool = False,
) -> SearchResult:
    """Uniform-cost search on MW move cost until win or budget exhausted."""
    start = time.time()
    tt = TranspositionTable()
    pq: List[Tuple[int, int, int, SpiderState, List[Action]]] = []
    uid = 0
    heapq.heappush(pq, (0, -len(root.foundations), uid, root.clone(), []))
    nodes = 0
    best_foundations = 0

    while pq and nodes < max_nodes:
        if time_limit is not None and time.time() - start >= time_limit:
            break
        g, neg_f, _, state, path = heapq.heappop(pq)
        f = -neg_f
        if f > best_foundations:
            best_foundations = f
            if progress:
                print(f"[ucs] foundations={f} g={g} nodes={nodes}")
        if state.is_solved():
            return SearchResult(True, path, g, nodes, time.time() - start)
        if g >= upper_bound:
            continue
        if tt.seen_worse_or_equal(state, g):
            continue
        tt.store(state, g)

        moves = dominance_filter(state, state.enumerate_moves())
        moves = order_moves(state, moves, len(path))
        for m in moves:
            if not state.can_move(*m):
                continue
            step = step_cost(state, m)
            ng = g + step
            if ng >= upper_bound:
                continue
            st, _ = apply_move_on_clone(state, m)
            nodes += 1
            uid += 1
            heapq.heappush(pq, (ng, -len(st.foundations), uid, st, path + [m]))

        if len(state.stock) >= 10:
            nd = g + deal_cost()
            if nd < upper_bound:
                st = state.clone()
                st.deal()
                nodes += 1
                uid += 1
                heapq.heappush(pq, (nd, -len(st.foundations), uid, st, path + [("deal",)]))

    return SearchResult(False, [], 9999, nodes, time.time() - start)


def bounded_finisher(
    root: SpiderState,
    *,
    upper_bound: int,
    time_limit: float = 6.0,
    beam_width: int = 900,
    max_nodes: int = 300_000,
    jitter: float = 0.0,
    progress: bool = False,
) -> SearchResult:
    """Best-first search on MW cost (no deals) for endgame."""
    start = time.time()
    tt = TranspositionTable()
    frontier: List[Tuple[Tuple, int, int, int, SpiderState, List[Move]]] = []
    uid = 0
    heapq.heappush(
        frontier,
        ((0, finisher_heuristic(root)), 0, uid, 0, root.clone(), []),
    )
    nodes = 0
    best_foundations = 0

    while frontier and nodes < max_nodes:
        if time.time() - start >= time_limit:
            break
        key, g, _, depth, state, path = heapq.heappop(frontier)
        if len(state.foundations) > best_foundations:
            best_foundations = len(state.foundations)
            if progress:
                print(f"[finisher] foundations={best_foundations} g={g} nodes={nodes}")
        if state.is_solved():
            actions: List[Action] = list(path)
            return SearchResult(True, actions, g, nodes, time.time() - start)
        if g >= upper_bound:
            continue
        if tt.seen_worse_or_equal(state, g):
            continue
        tt.store(state, g)

        moves = dominance_filter(state, state.enumerate_moves())
        moves = order_moves(state, moves, depth, jitter=jitter)
        for m in moves:
            step = step_cost(state, m)
            ng = g + step
            if ng >= upper_bound:
                continue
            st, _ = apply_move_on_clone(state, m)
            nodes += 1
            lm = st.last_move
            if lm and isinstance(lm, tuple) and len(lm) >= 5 and (lm[3] or lm[4]):
                note_progress(depth, m)
            uid += 1
            heapq.heappush(
                frontier,
                ((ng, finisher_heuristic(st)), ng, uid, depth + 1, st, path + [m]),
            )

        if len(frontier) > beam_width:
            frontier = frontier[:beam_width]

    if frontier:
        _, g, _, _, st, path = frontier[0]
        if st.is_solved():
            return SearchResult(True, list(path), g, nodes, time.time() - start)
    return SearchResult(False, [], 9999, nodes, time.time() - start)


def ida_star(
    root: SpiderState,
    *,
    upper_bound: int,
    max_iterations: int = 200,
) -> SearchResult:
    """IDA* on MW cost with admissible lower bound."""
    start = time.time()
    nodes = 0

    def search(limit: int, state: SpiderState, g: int, path: List[Action]) -> SearchResult | str:
        nonlocal nodes
        h = lower_bound_mw(state)
        if g + h >= upper_bound:
            return "bound"
        if g > limit:
            return "limit"
        if state.is_solved():
            return SearchResult(True, path, g, nodes, time.time() - start)

        min_overflow = 9999
        moves = order_moves(state, dominance_filter(state, state.enumerate_moves()), len(path))
        for m in moves:
            step = step_cost(state, m)
            ng = g + step
            if ng > limit:
                min_overflow = min(min_overflow, ng)
                continue
            st, _ = apply_move_on_clone(state, m)
            nodes += 1
            r = search(limit, st, ng, path + [m])
            if isinstance(r, SearchResult):
                return r
            if r == "limit":
                min_overflow = min(min_overflow, ng)
            elif isinstance(r, int):
                min_overflow = min(min_overflow, r)

        if len(state.stock) >= 10:
            nd = g + deal_cost()
            if nd <= limit:
                st = state.clone()
                st.deal()
                nodes += 1
                r = search(limit, st, nd, path + [("deal",)])
                if isinstance(r, SearchResult):
                    return r
                if r == "limit":
                    min_overflow = min(min_overflow, nd)

        return min_overflow if min_overflow < 9999 else "bound"

    limit = lower_bound_mw(root)
    for _ in range(max_iterations):
        if limit >= upper_bound:
            break
        r = search(limit, root.clone(), 0, [])
        if isinstance(r, SearchResult):
            return r
        if r == "bound":
            break
        if isinstance(r, int):
            limit = r
        else:
            break
    return SearchResult(False, [], 9999, nodes, time.time() - start)
