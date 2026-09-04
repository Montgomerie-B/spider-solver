"""Bounded scheduled-lane excavation planner.

Search only graph-relevant tableau moves to satisfy one unresolved
same-suit edge of an existing scheduler lane.  Stock-empty, no Deal,
no empty-column creation, no stable-join breaking.

This is not generic whole-tableau search and is not a mixed-park cap raise.
Local transposition is planner-only and does not touch production TT.
"""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.move_lifecycle import PlacementClass, assess_tableau_move
from spider.planner.receiver_uncover import _movable_run_length
from spider.rules import MW_RULES
from spider.state_identity import canonical_state_key


TableauMove = Tuple[int, int, int]
MAX_DEPTH = 8
MAX_VISITED = 5_000


@dataclass(frozen=True)
class BoundedExcavationPlan:
    solved: bool
    actions: Tuple[TableauMove, ...] = ()
    cost: int = 0
    visited: int = 0
    max_depth: int = 0
    elapsed_seconds: float = 0.0
    target_suit: str = ""
    high_rank: int = 0
    low_rank: int = 0
    chosen_low_column: Optional[int] = None
    reject: Optional[str] = None
    joins_before: int = 0
    joins_after: int = 0
    fd_before: int = 0
    fd_after: int = 0
    mixed_parks: int = 0
    replay_ok: bool = False
    edge_satisfied: bool = False
    proof_pruning_allowed: bool = False


def _fd(state: SpiderState) -> int:
    return sum(len(col.face_down) for col in state.columns)


def _suit_joins(state: SpiderState, suit: str) -> int:
    n = 0
    for col in state.columns:
        up = col.face_up
        for a, b in zip(up, up[1:]):
            if a.suit == suit and b.suit == suit and a.rank - 1 == b.rank:
                n += 1
    return n


def _edge_count(state: SpiderState, suit: str, high: int, low: int) -> int:
    n = 0
    for col in state.columns:
        up = col.face_up
        for a, b in zip(up, up[1:]):
            if (
                a.suit == suit
                and b.suit == suit
                and a.rank == high
                and b.rank == low
            ):
                n += 1
    return n


def _edge_immediately_legal(state: SpiderState, suit: str, high: int, low: int) -> bool:
    highs, lows = [], []
    for ci, col in enumerate(state.columns):
        top = col.top()
        if top is None:
            continue
        if top.suit == suit and top.rank == high:
            highs.append(ci)
        if top.suit == suit and top.rank == low:
            lows.append(ci)
    for src in lows:
        k = _movable_run_length(state, src)
        if k <= 0:
            continue
        head = state.columns[src].face_up[-k]
        if head.suit != suit or head.rank != low:
            # k=1 head is the top
            head = state.columns[src].top()
        if head is None or head.suit != suit or head.rank != low:
            continue
        for dst in highs:
            if src != dst and state.can_move(src, dst, 1):
                return True
    return False


def _copies(state: SpiderState, suit: str, rank: int) -> List[Tuple[int, int, str, int]]:
    """(column, index, zone, depth) for each physical copy."""

    out = []
    for ci, col in enumerate(state.columns):
        fu_n = len(col.face_up)
        fd_n = len(col.face_down)
        for i, card in enumerate(col.face_down):
            if card.suit == suit and card.rank == rank:
                out.append((ci, i, "fd", fu_n + (fd_n - 1 - i)))
        for i, card in enumerate(col.face_up):
            if card.suit == suit and card.rank == rank:
                out.append((ci, i, "fu", fu_n - 1 - i))
    out.sort(key=lambda item: (item[3], item[0], item[1]))
    return out


def _breaks_join(state: SpiderState, action: TableauMove) -> bool:
    life = assess_tableau_move(state, action, discover_exit=False)
    return bool(life.same_suit_joins_broken)


def _mixed(state: SpiderState, action: TableauMove) -> bool:
    life = assess_tableau_move(state, action, discover_exit=False)
    return life.placement_class == PlacementClass.MIXED_SUIT_PARK


def _rehandling(state: SpiderState, action: TableauMove) -> float:
    return float(assess_tableau_move(state, action, discover_exit=False).estimated_rehandling_cost)


def _ranks_covering(state: SpiderState, suit: str, rank: int) -> List[int]:
    return [ci for ci, _i, _z, _d in _copies(state, suit, rank)]


def _needed_receiver_rank(card: Card) -> Optional[int]:
    if card.rank >= 13:
        return None
    return card.rank + 1


def _columns_holding_rank(state: SpiderState, rank: int) -> List[int]:
    cols = []
    for ci, col in enumerate(state.columns):
        if any(c.rank == rank for c in col.face_up) or any(c.rank == rank for c in col.face_down):
            cols.append(ci)
    return cols


def _cheapest_buried_holder(state: SpiderState, rank: int, exclude: int) -> List[int]:
    """Columns holding a buried copy of rank, cheapest first, excluding exclude."""

    holders = []
    for ci, col in enumerate(state.columns):
        if ci == exclude:
            continue
        best = None
        for i, card in enumerate(col.face_down):
            if card.rank != rank:
                continue
            depth = len(col.face_up) + (len(col.face_down) - 1 - i)
            best = depth if best is None else min(best, depth)
        for i, card in enumerate(col.face_up):
            if card.rank != rank:
                continue
            depth = len(col.face_up) - 1 - i
            if depth == 0:
                continue
            best = depth if best is None else min(best, depth)
        if best is not None:
            holders.append((best, ci))
    holders.sort()
    return [ci for _d, ci in holders[:4]]


def _graph_source_columns(state: SpiderState, suit: str, high: int, low: int) -> Tuple[int, ...]:
    copies = _copies(state, suit, low)
    if not copies:
        return ()
    target_col = copies[0][0]
    cols = {target_col}
    top = state.columns[target_col].top()
    if top is not None:
        need = _needed_receiver_rank(top)
        if need is not None:
            dest_exists = any(
                ci != target_col
                and col.top() is not None
                and col.top().rank == need
                for ci, col in enumerate(state.columns)
            )
            if not dest_exists:
                for ci in _cheapest_buried_holder(state, need, target_col):
                    cols.add(ci)
                    cover = state.columns[ci].top()
                    if cover is not None and cover.rank != need:
                        need2 = _needed_receiver_rank(cover)
                        if need2 is not None:
                            dest2 = any(
                                cj != ci
                                and state.columns[cj].top() is not None
                                and state.columns[cj].top().rank == need2
                                for cj in range(10)
                            )
                            if not dest2:
                                for cj in _cheapest_buried_holder(state, need2, ci):
                                    cols.add(cj)
    return tuple(sorted(cols))


def _completes_edge(
    state: SpiderState, action: TableauMove, suit: str, high: int, low: int
) -> bool:
    src, dst, k = action
    if k <= 0 or not state.columns[src].face_up:
        return False
    head = state.columns[src].face_up[-k]
    dest_top = state.columns[dst].top()
    if dest_top is None:
        return False
    return (
        head.suit == suit
        and dest_top.suit == suit
        and head.rank == low
        and dest_top.rank == high
    )


def _relevant_moves(
    state: SpiderState, suit: str, high: int, low: int
) -> Tuple[TableauMove, ...]:
    sources = _graph_source_columns(state, suit, high, low)
    if not sources:
        return ()
    copies = _copies(state, suit, low)
    target_col = copies[0][0] if copies else None
    moves: List[TableauMove] = []
    for src in sources:
        run = _movable_run_length(state, src)
        if run <= 0:
            continue
        for k in range(1, run + 1):
            for dst in range(10):
                if dst == src:
                    continue
                if state.columns[dst].is_empty():
                    continue
                action = (src, dst, k)
                if not state.can_move(src, dst, k):
                    continue
                if _breaks_join(state, action):
                    continue
                completes = _completes_edge(state, action, suit, high, low)
                peels_target = src == target_col
                if completes or peels_target:
                    moves.append(action)
                    continue
                # Peel a receiver-dependency column, or create an exact receiver
                dest_top = state.columns[dst].top()
                moving_head = state.columns[src].face_up[-k]
                creates_receiver = (
                    dest_top is not None
                    and moving_head.suit == dest_top.suit
                    and dest_top.rank - 1 == moving_head.rank
                )
                if creates_receiver or src in sources:
                    moves.append(action)
    unique = []
    seen = set()
    for action in sorted(moves):
        if action in seen:
            continue
        seen.add(action)
        unique.append(action)
    return tuple(unique)


def plan_scheduled_lane_edge(
    state: SpiderState,
    *,
    suit: str,
    high_rank: int,
    low_rank: int,
    max_depth: int = MAX_DEPTH,
    max_visited: int = MAX_VISITED,
) -> BoundedExcavationPlan:
    """Return a replay-verified plan satisfying (high, low) of suit, or unsolved."""

    started = time.perf_counter()
    joins0 = _suit_joins(state, suit)
    edges0 = _edge_count(state, suit, high_rank, low_rank)
    fd0 = _fd(state)
    if state.stock:
        return BoundedExcavationPlan(
            False,
            reject="stock_nonempty",
            target_suit=suit,
            high_rank=high_rank,
            low_rank=low_rank,
            joins_before=joins0,
            fd_before=fd0,
            elapsed_seconds=time.perf_counter() - started,
        )
    if _edge_immediately_legal(state, suit, high_rank, low_rank):
        return BoundedExcavationPlan(
            False,
            reject="already_legal",
            target_suit=suit,
            high_rank=high_rank,
            low_rank=low_rank,
            joins_before=joins0,
            fd_before=fd0,
            elapsed_seconds=time.perf_counter() - started,
        )
    if not _copies(state, suit, low_rank):
        return BoundedExcavationPlan(
            False,
            reject="no_physical_low",
            target_suit=suit,
            high_rank=high_rank,
            low_rank=low_rank,
            joins_before=joins0,
            fd_before=fd0,
            elapsed_seconds=time.perf_counter() - started,
        )

    start_key = canonical_state_key(state)
    # heap: cost, broken, mixed, rehandling, actions, state
    heap: List[Tuple] = []
    heapq.heappush(heap, (0, 0, 0, 0.0, (), state.clone()))
    best_cost = {start_key: (0, 0, 0, 0.0)}
    visited = 0
    max_seen_depth = 0
    best_plan: Optional[BoundedExcavationPlan] = None

    while heap:
        cost, broken, mixed, rehand, actions, cur = heapq.heappop(heap)
        visited += 1
        if visited > max_visited:
            break
        max_seen_depth = max(max_seen_depth, len(actions))
        if _edge_count(cur, suit, high_rank, low_rank) > edges0:
            if broken != 0:
                continue
            if _suit_joins(cur, suit) <= joins0:
                continue
            replay = state.clone()
            try:
                paid = replay_actions(replay, list(actions))
            except (ValueError, AssertionError, IndexError):
                continue
            ok = (
                paid == cost
                and _edge_count(replay, suit, high_rank, low_rank) > edges0
            )
            copies = _copies(replay, suit, low_rank)
            chosen = None
            for ci, col in enumerate(replay.columns):
                up = col.face_up
                for a, b in zip(up, up[1:]):
                    if a.suit == suit and b.suit == suit and a.rank == high_rank and b.rank == low_rank:
                        chosen = ci
                        break
            plan = BoundedExcavationPlan(
                True,
                actions=actions,
                cost=cost,
                visited=visited,
                max_depth=max_seen_depth,
                elapsed_seconds=time.perf_counter() - started,
                target_suit=suit,
                high_rank=high_rank,
                low_rank=low_rank,
                chosen_low_column=chosen,
                joins_before=joins0,
                joins_after=_suit_joins(replay, suit),
                fd_before=fd0,
                fd_after=_fd(replay),
                mixed_parks=mixed,
                replay_ok=ok,
                edge_satisfied=True,
            )
            if ok and cost <= max_depth:
                best_plan = plan
                break
        if len(actions) >= max_depth:
            continue
        for action in _relevant_moves(cur, suit, high_rank, low_rank):
            if _breaks_join(cur, action):
                continue
            nxt = cur.clone()
            try:
                step = nxt.move(*action, rules=MW_RULES)
            except (ValueError, AssertionError, IndexError):
                continue
            ncost = cost + step
            if ncost > max_depth:
                continue
            nmixed = mixed + int(_mixed(cur, action))
            nrehand = rehand + _rehandling(cur, action)
            nbroken = broken  # rejected join-breaks already
            key = canonical_state_key(nxt)
            rec = best_cost.get(key)
            score = (ncost, nbroken, nmixed, nrehand)
            if rec is not None and rec <= score:
                continue
            best_cost[key] = score
            heapq.heappush(
                heap,
                (ncost, nbroken, nmixed, nrehand, actions + (action,), nxt),
            )

    elapsed = time.perf_counter() - started
    if best_plan is not None:
        return BoundedExcavationPlan(
            True,
            actions=best_plan.actions,
            cost=best_plan.cost,
            visited=visited,
            max_depth=max(max_seen_depth, len(best_plan.actions)),
            elapsed_seconds=elapsed,
            target_suit=suit,
            high_rank=high_rank,
            low_rank=low_rank,
            chosen_low_column=best_plan.chosen_low_column,
            joins_before=joins0,
            joins_after=best_plan.joins_after,
            fd_before=fd0,
            fd_after=best_plan.fd_after,
            mixed_parks=best_plan.mixed_parks,
            replay_ok=best_plan.replay_ok,
            edge_satisfied=True,
        )
    reject = "exhausted" if visited > max_visited else "unsolved_within_bounds"
    return BoundedExcavationPlan(
        False,
        visited=visited,
        max_depth=max_seen_depth,
        elapsed_seconds=elapsed,
        target_suit=suit,
        high_rank=high_rank,
        low_rank=low_rank,
        reject=reject,
        joins_before=joins0,
        fd_before=fd0,
    )
