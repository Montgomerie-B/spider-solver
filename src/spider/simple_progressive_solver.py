"""Simple progressive Spider solver — competing baseline v0.1.

A separate search from the strategic anytime controller.  It uses only the
rule engine, legal moves, exact canonical identity, replay, and cheap
human-like move classes.  Progressive relaxation widens the allowed class
set; exact-state memory and backtracking do the rest.

This module must not import the strategic controller or planner policy.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional, Sequence, Tuple, Union

from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.rules import MW_RULES, MobilityWareRules, deal_cost, mw_move_cost
from spider.state_identity import CanonicalStateKey, canonical_state_key


TableauMove = Tuple[int, int, int]
SolverAction = Union[TableauMove, Tuple[str]]


class RelaxationStage(IntEnum):
    """Widening permission, not a score.

    STRICT: same-suit extensions and uncovers that do not break a join.
    BUILD: mixed descending builds and king-to-empty.
    SPACE: creating an empty column or parking a non-king on empty.
    DEAL: stock deal.
    ANY: remaining legal moves, including same-suit join breaks.
    """

    STRICT = 0
    BUILD = 1
    SPACE = 2
    DEAL = 3
    ANY = 4


class MoveClass(IntEnum):
    SAME_SUIT_EXTEND = 0
    UNCOVER = 1
    MIXED_BUILD = 2
    KING_TO_EMPTY = 3
    CREATE_EMPTY = 4
    EMPTY_PARK = 5
    DEAL = 6
    JOIN_BREAK = 7


_STAGE_ALLOWS: Dict[RelaxationStage, Tuple[MoveClass, ...]] = {
    RelaxationStage.STRICT: (MoveClass.SAME_SUIT_EXTEND, MoveClass.UNCOVER),
    RelaxationStage.BUILD: (
        MoveClass.SAME_SUIT_EXTEND,
        MoveClass.UNCOVER,
        MoveClass.MIXED_BUILD,
        MoveClass.KING_TO_EMPTY,
    ),
    RelaxationStage.SPACE: (
        MoveClass.SAME_SUIT_EXTEND,
        MoveClass.UNCOVER,
        MoveClass.MIXED_BUILD,
        MoveClass.KING_TO_EMPTY,
        MoveClass.CREATE_EMPTY,
        MoveClass.EMPTY_PARK,
    ),
    RelaxationStage.DEAL: (
        MoveClass.SAME_SUIT_EXTEND,
        MoveClass.UNCOVER,
        MoveClass.MIXED_BUILD,
        MoveClass.KING_TO_EMPTY,
        MoveClass.CREATE_EMPTY,
        MoveClass.EMPTY_PARK,
        MoveClass.DEAL,
    ),
    RelaxationStage.ANY: tuple(MoveClass),
}


def classify_action(state: SpiderState, action: SolverAction) -> MoveClass:
    """Cheap local class.  No campaign analysis."""

    if action == ("deal",) or action == "deal":
        return MoveClass.DEAL
    src, dst, k = action  # type: ignore[misc]
    src_col = state.columns[src]
    dst_col = state.columns[dst]
    run = src_col.face_up[-k:]
    head = run[0]
    if k < len(src_col.face_up):
        left = src_col.face_up[-k - 1]
        if left.suit == head.suit and left.rank == head.rank + 1:
            return MoveClass.JOIN_BREAK
    dest_top = dst_col.top()
    uncovers = k == len(src_col.face_up) and bool(src_col.face_down)
    empties = k == len(src_col.face_up) and not src_col.face_down
    if dest_top is not None and dest_top.suit == head.suit:
        return MoveClass.SAME_SUIT_EXTEND
    if uncovers:
        return MoveClass.UNCOVER
    if dest_top is None:
        if head.rank == 13:
            return MoveClass.KING_TO_EMPTY
        return MoveClass.EMPTY_PARK
    if empties:
        return MoveClass.CREATE_EMPTY
    return MoveClass.MIXED_BUILD


def action_allowed(kind: MoveClass, stage: RelaxationStage) -> bool:
    return kind in _STAGE_ALLOWS[stage]


def enumerate_actions(
    state: SpiderState, *, rules: MobilityWareRules = MW_RULES
) -> List[SolverAction]:
    actions: List[SolverAction] = list(state.enumerate_moves())
    if state.can_deal(rules=rules):
        actions.append(("deal",))
    return actions


def step_cost(
    state: SpiderState,
    action: SolverAction,
    *,
    rules: MobilityWareRules = MW_RULES,
) -> int:
    if action == ("deal",) or action == "deal":
        return deal_cost()
    src, dst, k = action  # type: ignore[misc]
    src_col = state.columns[src]
    dst_col = state.columns[dst]
    return mw_move_cost(
        cards_moved=k,
        source_face_up_count=len(src_col.face_up),
        dest_was_empty=dst_col.is_empty(),
        source_face_down_count=len(src_col.face_down),
        rules=rules,
    )


def apply_action(
    state: SpiderState,
    action: SolverAction,
    *,
    rules: MobilityWareRules = MW_RULES,
) -> int:
    if action == ("deal",) or action == "deal":
        return state.deal(rules=rules)
    src, dst, k = action  # type: ignore[misc]
    return state.move(src, dst, k, rules=rules)


def _order_key(state: SpiderState, action: SolverAction) -> Tuple:
    kind = classify_action(state, action)
    if action == ("deal",) or action == "deal":
        return (int(kind), 0, 0, 0, 0)
    src, dst, k = action  # type: ignore[misc]
    src_col = state.columns[src]
    uncovers = k == len(src_col.face_up) and bool(src_col.face_down)
    return (
        int(kind),
        0 if uncovers else 1,
        -k,
        src,
        dst,
    )


def ordered_actions(
    state: SpiderState,
    stage: RelaxationStage,
    *,
    rules: MobilityWareRules = MW_RULES,
) -> List[SolverAction]:
    allowed: List[SolverAction] = []
    for action in enumerate_actions(state, rules=rules):
        kind = classify_action(state, action)
        if action_allowed(kind, stage):
            allowed.append(action)
    allowed.sort(key=lambda action: _order_key(state, action))
    return allowed


@dataclass
class ProgressiveSearchResult:
    solved: bool
    actions: List[Action]
    cost: int
    nodes: int
    elapsed_s: float
    stage_reached: int
    max_foundations: int
    min_face_down: int
    min_stock_rows: int
    foundation_path: List[Action] = field(default_factory=list)
    foundation_cost: int = 0
    stop_reason: str = ""
    replay_ok: bool = False


def _face_down(state: SpiderState) -> int:
    return sum(len(col.face_down) for col in state.columns)


def _stock_rows(state: SpiderState) -> int:
    return len(state.stock) // 10


class _ExactMemory:
    """Exact canonical TT.  Re-expand when relaxation is strictly looser."""

    def __init__(self) -> None:
        self._best: Dict[CanonicalStateKey, Tuple[int, int]] = {}

    def should_skip(self, key: CanonicalStateKey, g: int, stage: int) -> bool:
        previous = self._best.get(key)
        if previous is None:
            return False
        prev_g, prev_stage = previous
        if g > prev_g:
            return True
        if g == prev_g and stage <= prev_stage:
            return True
        return False

    def record(self, key: CanonicalStateKey, g: int, stage: int) -> None:
        previous = self._best.get(key)
        if previous is None or g < previous[0] or (g == previous[0] and stage > previous[1]):
            self._best[key] = (g, stage)

    def __len__(self) -> int:
        return len(self._best)


def solve_progressive(
    root: SpiderState,
    *,
    max_nodes: int = 250_000,
    time_limit_s: float = 180.0,
    max_stage: RelaxationStage = RelaxationStage.ANY,
    rules: MobilityWareRules = MW_RULES,
    target_foundations: int = 1,
) -> ProgressiveSearchResult:
    """DFS with exact TT and progressive relaxation.  Backtracks by cloning."""

    started = time.perf_counter()
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 4000))
    memory = _ExactMemory()
    nodes = 0
    max_foundations = len(root.foundations)
    min_fd = _face_down(root)
    min_stock = _stock_rows(root)
    best_foundation_path: List[Action] = []
    best_foundation_cost = 0
    solved_path: Optional[List[Action]] = None
    solved_cost = 0
    stage_reached = int(RelaxationStage.STRICT)
    stop_reason = "stage envelope"
    n_stages = int(max_stage) + 1
    node_cap = 0
    deadline = started
    progress_key = (max_foundations, -min_fd, -min_stock)
    progress_path: List[Action] = []
    progress_cost = 0

    def budget_exhausted() -> bool:
        return nodes >= node_cap or time.perf_counter() >= deadline

    def dfs(state: SpiderState, path: List[Action], g: int, stage: RelaxationStage) -> bool:
        nonlocal nodes, max_foundations, min_fd, min_stock, progress_key
        nonlocal best_foundation_path, best_foundation_cost, solved_path, solved_cost
        nonlocal progress_path, progress_cost
        if budget_exhausted():
            return False
        key = canonical_state_key(state)
        if memory.should_skip(key, g, int(stage)):
            return False
        memory.record(key, g, int(stage))
        nodes += 1
        fd = _face_down(state)
        stock_rows = _stock_rows(state)
        foundations = len(state.foundations)
        if fd < min_fd:
            min_fd = fd
        if stock_rows < min_stock:
            min_stock = stock_rows
        candidate = (foundations, -fd, -stock_rows)
        if candidate > progress_key:
            progress_key = candidate
            progress_path = list(path)
            progress_cost = g
        if foundations > max_foundations:
            max_foundations = foundations
            best_foundation_path = list(path)
            best_foundation_cost = g
        if state.is_solved():
            solved_path = list(path)
            solved_cost = g
            return True
        if foundations >= target_foundations and foundations > len(root.foundations):
            return True
        for action in ordered_actions(state, stage, rules=rules):
            if budget_exhausted():
                return False
            child = state.clone()
            try:
                cost = apply_action(child, action, rules=rules)
            except (ValueError, AssertionError):
                continue
            child_action: Action = ("deal",) if action == ("deal",) or action == "deal" else action
            if dfs(child, path + [child_action], g + cost, stage):
                return True
        return False

    for stage in RelaxationStage:
        if int(stage) > int(max_stage):
            break
        stage_reached = int(stage)
        node_cap = min(max_nodes, nodes + max(1, max_nodes // n_stages))
        deadline = min(started + time_limit_s, deadline + (time_limit_s / n_stages))
        if dfs(root.clone(), [], 0, stage):
            stop_reason = "target reached"
            break
        if nodes >= max_nodes:
            stop_reason = "node limit"
            break
        if time.perf_counter() - started >= time_limit_s:
            stop_reason = "time limit"
            break
    else:
        stop_reason = "stage envelope"

    actions = (
        solved_path
        if solved_path is not None
        else (best_foundation_path or progress_path)
    )
    cost = (
        solved_cost
        if solved_path is not None
        else (best_foundation_cost if best_foundation_path else progress_cost)
    )
    replay_ok = False
    if actions:
        probe = root.clone()
        try:
            paid = replay_actions(probe, list(actions))
            replay_ok = paid == cost
            if solved_path is not None:
                replay_ok = replay_ok and probe.is_solved()
            elif max_foundations > len(root.foundations):
                replay_ok = replay_ok and len(probe.foundations) >= max_foundations
        except (ValueError, AssertionError):
            replay_ok = False
    return ProgressiveSearchResult(
        solved=solved_path is not None,
        actions=list(actions),
        cost=cost,
        nodes=nodes,
        elapsed_s=time.perf_counter() - started,
        stage_reached=stage_reached,
        max_foundations=max_foundations,
        min_face_down=min_fd,
        min_stock_rows=min_stock,
        foundation_path=list(best_foundation_path),
        foundation_cost=best_foundation_cost,
        stop_reason=stop_reason,
        replay_ok=replay_ok,
    )
