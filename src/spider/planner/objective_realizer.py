"""Tactical realisation of StrategicObjective targets (Sprint 1F).

Finds a replay-valid legal action sequence satisfying an objective predicate.
Does NOT search the whole deal. A bounded miss is never "impossible".

Uses the real engine + corrected MW_RULES. Zero-cost moves expand at the same
paid-cost layer. Transposition keys are collision-safe CanonicalStateKey.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple, Union

from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.rules import MW_RULES
from spider.state_identity import canonical_state_key
from spider.planner.space_lifecycle import empty_count
from spider.planner.strategic_objectives import (
    ObjectiveKind,
    StrategicObjective,
)

Action = Union[Tuple[int, int, int], Tuple[str]]


class RealizationMode(str, Enum):
    FAST_BOUNDED = "FAST_BOUNDED"
    EXACT_BOUNDED = "EXACT_BOUNDED"


class RealizationStatus(str, Enum):
    ALREADY_SATISFIED = "already_satisfied"
    FOUND = "found"
    NOT_FOUND_WITHIN_BOUND = "not_found_within_bound"
    UNSUPPORTED = "unsupported"
    RESOURCE_LIMIT = "resource_limit"


@dataclass
class RealizationResult:
    status: RealizationStatus
    objective: StrategicObjective
    mode: RealizationMode
    corrected_mw_cost: Optional[int]
    actions: Tuple[Action, ...]
    action_labels: Tuple[str, ...]
    result_key_hex: Optional[str]
    nodes_expanded: int
    elapsed_seconds: float
    target_verified: bool
    exact_within_bound: bool
    max_cost: int
    max_nodes: int
    notes: Tuple[str, ...]


_SUPPORTED = {
    ObjectiveKind.DEAL_NOW,
    ObjectiveKind.CREATE_WORKSPACE,
    ObjectiveKind.SHAPE_STOCK_RECEIVER,
    ObjectiveKind.EXPOSE_REVEAL_PREFIX,
    ObjectiveKind.CONSOLIDATE_SAME_SUIT,
    ObjectiveKind.REMOVE_FOUNDATION,
    ObjectiveKind.ADVANCE_FOUNDATION,  # same predicates as consolidate
}


def _label(a: Action) -> str:
    if a == ("deal",) or a == ("deal",):
        return "deal"
    if isinstance(a, tuple) and len(a) == 3:
        return f"move {a[0] + 1} {a[1] + 1} {a[2]}"
    return str(a)


def _verify_replay(
    start: SpiderState, actions: Sequence[Action], objective: StrategicObjective
) -> Tuple[bool, int, SpiderState]:
    st = start.clone()
    cost = replay_actions(st, list(actions))
    ok = objective.is_satisfied(st)
    return ok, cost, st


def realize_objective(
    state: SpiderState,
    objective: StrategicObjective,
    *,
    mode: RealizationMode = RealizationMode.EXACT_BOUNDED,
    max_cost: Optional[int] = None,
    max_nodes: int = 8000,
    time_limit_s: float = 2.0,
    beam: int = 64,
) -> RealizationResult:
    """Search for a legal path satisfying ``objective``.

    ``max_cost`` defaults to max(admissible_lb, ceil(heuristic_est_cost), 1)
    plus a small family-specific headroom. Heuristic cost never prunes proof;
    it only suggests the budget. admissible_lb is a floor for the budget.
    """
    t0 = time.time()
    if objective.is_satisfied(state):
        return RealizationResult(
            status=RealizationStatus.ALREADY_SATISFIED,
            objective=objective,
            mode=mode,
            corrected_mw_cost=0,
            actions=(),
            action_labels=(),
            result_key_hex=hex(hash(canonical_state_key(state)))[-16:],
            nodes_expanded=0,
            elapsed_seconds=0.0,
            target_verified=True,
            exact_within_bound=True,
            max_cost=0,
            max_nodes=max_nodes,
            notes=("fact: already satisfied",),
        )

    if objective.kind not in _SUPPORTED:
        return RealizationResult(
            status=RealizationStatus.UNSUPPORTED,
            objective=objective,
            mode=mode,
            corrected_mw_cost=None,
            actions=(),
            action_labels=(),
            result_key_hex=None,
            nodes_expanded=0,
            elapsed_seconds=time.time() - t0,
            target_verified=False,
            exact_within_bound=False,
            max_cost=0,
            max_nodes=max_nodes,
            notes=(f"fact: kind {objective.kind.value} not supported",),
        )

    # DEAL_NOW exact
    if objective.kind == ObjectiveKind.DEAL_NOW:
        return _realize_deal_now(state, objective, mode, t0)

    budget = max_cost
    if budget is None:
        est = int(max(1, round(objective.heuristic_est_cost)))
        budget = max(objective.admissible_lb, est, 1)
        if objective.kind == ObjectiveKind.CREATE_WORKSPACE:
            budget = max(budget, 4)
        if objective.kind == ObjectiveKind.EXPOSE_REVEAL_PREFIX:
            req = int(objective.target_params.get("required_reveals", 1))
            budget = max(budget, req + 3)
        budget = min(budget, 8)

    if mode == RealizationMode.FAST_BOUNDED:
        status, actions, cost, nodes, notes = _search_fast(
            state, objective, budget, max_nodes, time_limit_s, beam, t0
        )
        exact = False
    else:
        status, actions, cost, nodes, notes = _search_exact(
            state, objective, budget, max_nodes, time_limit_s, t0
        )
        exact = status == RealizationStatus.FOUND

    verified = False
    key_hex = None
    if status == RealizationStatus.FOUND and actions is not None:
        ok, recost, st2 = _verify_replay(state, actions, objective)
        verified = ok and recost == cost
        if not ok:
            status = RealizationStatus.NOT_FOUND_WITHIN_BOUND
            notes = notes + ("fact: replay failed target verification",)
            actions = ()
            cost = None
        elif recost != cost:
            notes = notes + (f"fact: recomputed cost {recost} (search said {cost})",)
            cost = recost
        if verified:
            key_hex = hex(hash(canonical_state_key(st2)))[-16:]

    return RealizationResult(
        status=status,
        objective=objective,
        mode=mode,
        corrected_mw_cost=cost,
        actions=tuple(actions or ()),
        action_labels=tuple(_label(a) for a in (actions or ())),
        result_key_hex=key_hex,
        nodes_expanded=nodes,
        elapsed_seconds=time.time() - t0,
        target_verified=verified,
        exact_within_bound=exact and verified,
        max_cost=budget,
        max_nodes=max_nodes,
        notes=notes,
    )


def _realize_deal_now(state, objective, mode, t0) -> RealizationResult:
    if len(state.stock) < 10:
        return RealizationResult(
            status=RealizationStatus.NOT_FOUND_WITHIN_BOUND,
            objective=objective,
            mode=mode,
            corrected_mw_cost=None,
            actions=(),
            action_labels=(),
            result_key_hex=None,
            nodes_expanded=0,
            elapsed_seconds=time.time() - t0,
            target_verified=False,
            exact_within_bound=False,
            max_cost=1,
            max_nodes=1,
            notes=("fact: cannot deal (stock < 10)",),
        )
    st = state.clone()
    cost = st.deal()
    ok = objective.is_satisfied(st)
    return RealizationResult(
        status=RealizationStatus.FOUND if ok else RealizationStatus.NOT_FOUND_WITHIN_BOUND,
        objective=objective,
        mode=mode,
        corrected_mw_cost=cost if ok else None,
        actions=(("deal",),) if ok else (),
        action_labels=("deal",) if ok else (),
        result_key_hex=hex(hash(canonical_state_key(st)))[-16:] if ok else None,
        nodes_expanded=1,
        elapsed_seconds=time.time() - t0,
        target_verified=ok,
        exact_within_bound=ok,
        max_cost=1,
        max_nodes=1,
        notes=("fact: DEAL_NOW via engine.deal cost=1",),
    )


def _expand(st: SpiderState) -> List[Tuple[Action, int, SpiderState]]:
    out: List[Tuple[Action, int, SpiderState]] = []
    for src, dst, k in st.enumerate_moves():
        st2 = st.clone()
        try:
            c = st2.move(src, dst, k, rules=MW_RULES)
        except Exception:
            continue
        out.append(((src, dst, k), c, st2))
    return out


def _search_exact(
    start: SpiderState,
    objective: StrategicObjective,
    max_cost: int,
    max_nodes: int,
    time_limit_s: float,
    t0: float,
) -> Tuple[RealizationStatus, Tuple[Action, ...], Optional[int], int, Tuple[str, ...]]:
    """0-1 BFS on corrected cost (0-cost edges first)."""
    start_key = canonical_state_key(start)
    best: Dict = {start_key: 0}
    # deque of (cost, state, path)
    q: deque = deque()
    q.append((0, start, ()))
    nodes = 0
    while q:
        if time.time() - t0 > time_limit_s:
            return (
                RealizationStatus.RESOURCE_LIMIT,
                (),
                None,
                nodes,
                ("fact: time limit", "fact: miss != impossible"),
            )
        if nodes >= max_nodes:
            return (
                RealizationStatus.RESOURCE_LIMIT,
                (),
                None,
                nodes,
                ("fact: node limit", "fact: miss != impossible"),
            )
        cost, st, path = q.popleft()
        nodes += 1
        if cost > max_cost:
            continue
        if objective.is_satisfied(st) and path:
            return (
                RealizationStatus.FOUND,
                path,
                cost,
                nodes,
                (f"fact: exact found cost={cost} nodes={nodes}",),
            )
        for action, c, st2 in _expand(st):
            ncost = cost + c
            if ncost > max_cost:
                continue
            # Zero-cost workspace relocation cannot increase empty count
            if (
                c == 0
                and objective.target_key == "empty_count_ge"
                and empty_count(st2) <= empty_count(st)
            ):
                continue
            key = canonical_state_key(st2)
            prev = best.get(key)
            if prev is not None and prev <= ncost:
                continue
            best[key] = ncost
            npath = path + (action,)
            if c == 0:
                q.appendleft((ncost, st2, npath))
            else:
                q.append((ncost, st2, npath))
    return (
        RealizationStatus.NOT_FOUND_WITHIN_BOUND,
        (),
        None,
        nodes,
        (
            f"fact: exhausted cost<={max_cost} nodes={nodes}",
            "fact: not_found_within_bound != impossible",
        ),
    )


def _search_fast(
    start: SpiderState,
    objective: StrategicObjective,
    max_cost: int,
    max_nodes: int,
    time_limit_s: float,
    beam: int,
    t0: float,
) -> Tuple[RealizationStatus, Tuple[Action, ...], Optional[int], int, Tuple[str, ...]]:
    """Layered beam: keep `beam` lowest-cost states per expansion wave."""
    layer: List[Tuple[int, SpiderState, Tuple[Action, ...]]] = [(0, start, ())]
    best = {canonical_state_key(start): 0}
    nodes = 0
    while layer:
        if time.time() - t0 > time_limit_s:
            return (
                RealizationStatus.RESOURCE_LIMIT,
                (),
                None,
                nodes,
                ("fact: time limit (fast)", "fact: miss != impossible"),
            )
        nxt: List[Tuple[int, SpiderState, Tuple[Action, ...]]] = []
        for cost, st, path in layer:
            if nodes >= max_nodes:
                return (
                    RealizationStatus.RESOURCE_LIMIT,
                    (),
                    None,
                    nodes,
                    ("fact: node limit (fast)", "fact: miss != impossible"),
                )
            nodes += 1
            if objective.is_satisfied(st) and path:
                return (
                    RealizationStatus.FOUND,
                    path,
                    cost,
                    nodes,
                    (f"fact: fast found cost={cost} nodes={nodes}",),
                )
            for action, c, st2 in _expand(st):
                ncost = cost + c
                if ncost > max_cost:
                    continue
                key = canonical_state_key(st2)
                prev = best.get(key)
                if prev is not None and prev <= ncost:
                    continue
                best[key] = ncost
                nxt.append((ncost, st2, path + (action,)))
        nxt.sort(key=lambda x: x[0])
        layer = nxt[:beam]
        if not layer:
            break
    return (
        RealizationStatus.NOT_FOUND_WITHIN_BOUND,
        (),
        None,
        nodes,
        ("fact: fast beam exhausted", "fact: not_found_within_bound != impossible"),
    )


def realize_portfolio(
    state: SpiderState,
    objectives: Sequence[StrategicObjective],
    **kwargs,
) -> Tuple[RealizationResult, ...]:
    return tuple(realize_objective(state, o, **kwargs) for o in objectives)
