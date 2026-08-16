"""Stronger tactical CREATE_WORKSPACE search (Sprint 1M).

Target: empty_count increases by at least 1. Bounded, replay-valid.
Not a new strategic layer — a backend for the existing 1F objective.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.move_lifecycle import assess_tableau_move
from spider.rules import MW_RULES
from spider.state_identity import canonical_state_key
from spider.planner.space_lifecycle import (
    empty_count,
    fully_open_nonempty,
)
from spider.planner.objective_realizer import (
    Action,
    RealizationMode,
    RealizationResult,
    RealizationStatus,
    realize_objective,
)
from spider.planner.strategic_objectives import (
    ObjectiveKind,
    PriorityComponents,
    StrategicObjective,
    generate_objective_portfolio,
)


class WorkspaceBackend(str, Enum):
    LEGACY = "legacy"
    IMPROVED = "improved"


@dataclass
class FollowOnResult:
    kind: str
    found: bool
    cost: Optional[int]
    notes: str


@dataclass
class WorkspaceAttempt:
    backend: WorkspaceBackend
    status: RealizationStatus
    cost: Optional[int]
    actions: Tuple[Action, ...]
    nodes: int
    elapsed: float
    empty_before: int
    empty_after: int
    follow_on: Tuple[FollowOnResult, ...]
    notes: Tuple[str, ...]


def make_workspace_objective(state: SpiderState) -> StrategicObjective:
    need = empty_count(state) + 1
    return StrategicObjective(
        kind=ObjectiveKind.CREATE_WORKSPACE,
        objective_id=f"create_workspace_e{need}",
        description=f"Increase empty_count to >= {need}",
        target_key="empty_count_ge",
        target_params={"min_empty": need},
        hard_preconditions=(),
        hard_evidence=(f"fact: empty_count={need - 1}",),
        admissible_lb=1 if empty_count(state) == need - 1 else 0,
        admissible_breakdown=None,
        heuristic_est_cost=4.0,
        heuristic_est_benefit=3.0,
        priority=PriorityComponents(workspace=5.0),
        foundation_relevance="indirect",
        workspace_relevance="primary",
        stock_relevance="enables recoverable empties",
        explanation="Sprint 1M workspace target",
    )


def workspace_quotient_key(state: SpiderState) -> Tuple:
    """Ignore which empty slot holds which freely relocatable open pile.

    Safe for CREATE_WORKSPACE: 0-cost relocations cannot increase empty_count.
    Creating an empty requires placing an open pile onto a non-empty dest
    (or otherwise emptying a column), which is a paid, quotient-visible change.
    """
    free_piles: List[Tuple] = []
    fixed: List[Tuple] = []
    n_empty = sum(column.is_empty() for column in state.columns)
    has_free_buffer = n_empty > 0
    for i, col in enumerate(state.columns):
        if col.is_empty():
            continue
        fu = tuple((c.suit, c.rank) for c in col.face_up)
        if (
            has_free_buffer
            and not col.face_down
            and state.is_movable_run(col.face_up)
        ):
            free_piles.append(fu)
        else:
            fd = tuple((c.suit, c.rank) for c in col.face_down)
            fixed.append((i, fd, fu))
    stock = tuple((c.suit, c.rank) for c in state.stock)
    founds = tuple(
        tuple((c.suit, c.rank) for c in seq) for seq in state.foundations
    )
    return (tuple(sorted(free_piles)), tuple(fixed), n_empty, stock, founds)


def _ws_move_rank(
    st: SpiderState, src: int, dst: int, k: int, cost: int
) -> Tuple:
    """HEURISTIC order only. Does not prune."""
    src_col = st.columns[src]
    dst_col = st.columns[dst]
    dest_empty = dst_col.is_empty()
    src_all = k == len(src_col.face_up)
    src_open = not src_col.face_down
    src_short = len(src_col.face_up) <= 3
    score = 0
    # Emptying a fully-open column onto a non-empty dest creates workspace.
    if src_all and src_open and not dest_empty:
        score -= 50
        if src_short:
            score -= 20
        if len(src_col.face_up) == 1:
            score -= 10
    elif src_all and src_open:
        score -= 8
    # Same-suit transfer
    top = dst_col.top()
    if top is not None and src_col.face_up:
        moved = src_col.face_up[-k]
        if top.suit == moved.suit and top.rank == moved.rank + 1:
            score -= 16
        elif top.suit == moved.suit:
            score -= 8
    # Consuming an empty without emptying source is anti-workspace.
    if dest_empty and not (src_all and src_open):
        score += 28
    # Pure 0-cost relocate: last, unless we already have a plan (doesn't create).
    if cost == 0:
        score += 35
    # Peel a blocker off a column that then has a short remainder.
    remain = len(src_col.face_up) - k
    if remain == 0 and src_col.face_down:
        score -= 7
    if remain == 1 and src_open:
        score -= 5
    lifecycle = assess_tableau_move(st, (src, dst, k), discover_exit=False)
    return (
        score,
        cost,
        lifecycle.ordering_key(),
        len(src_col.face_up),
        src,
        dst,
        k,
    )


def _expand_ws(st: SpiderState) -> List[Tuple[Action, int, SpiderState]]:
    raw = []
    for src, dst, k in st.enumerate_moves():
        st2 = st.clone()
        try:
            c = st2.move(src, dst, k, rules=MW_RULES)
        except Exception:
            continue
        raw.append((_ws_move_rank(st, src, dst, k, c), (src, dst, k), c, st2))
    raw.sort(key=lambda x: x[0])
    return [(a, c, s) for _, a, c, s in raw]


def _search_improved(
    start: SpiderState,
    target_empty: int,
    max_cost: int,
    max_nodes: int,
    time_limit_s: float,
    t0: float,
) -> Tuple[RealizationStatus, Tuple[Action, ...], Optional[int], int, Tuple[str, ...]]:
    start_q = workspace_quotient_key(start)
    best: Dict = {start_q: 0}
    q: deque = deque()
    q.append((0, start, ()))
    nodes = 0
    notes_extra = ("fact: workspace improved backend", "fact: quotient TT on free piles")
    while q:
        if time.time() - t0 > time_limit_s:
            return (
                RealizationStatus.RESOURCE_LIMIT,
                (),
                None,
                nodes,
                notes_extra + ("fact: time limit", "fact: miss != impossible"),
            )
        if nodes >= max_nodes:
            return (
                RealizationStatus.RESOURCE_LIMIT,
                (),
                None,
                nodes,
                notes_extra + ("fact: node limit", "fact: miss != impossible"),
            )
        cost, st, path = q.popleft()
        nodes += 1
        if cost > max_cost:
            continue
        if empty_count(st) >= target_empty and path:
            return (
                RealizationStatus.FOUND,
                path,
                cost,
                nodes,
                notes_extra + (f"fact: found cost={cost} nodes={nodes}",),
            )
        e0 = empty_count(st)
        for action, c, st2 in _expand_ws(st):
            ncost = cost + c
            if ncost > max_cost:
                continue
            e1 = empty_count(st2)
            # 0-cost cannot create workspace; skip non-productive free orbits.
            if c == 0 and e1 <= e0:
                continue
            key = workspace_quotient_key(st2)
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
        notes_extra
        + (
            f"fact: exhausted cost<={max_cost} nodes={nodes}",
            "fact: not_found_within_bound != impossible",
        ),
    )


def realize_workspace(
    state: SpiderState,
    *,
    backend: WorkspaceBackend = WorkspaceBackend.IMPROVED,
    max_cost: int = 8,
    max_nodes: int = 2500,
    time_limit_s: float = 1.2,
    mode: RealizationMode = RealizationMode.EXACT_BOUNDED,
) -> RealizationResult:
    """Find a path that increases empty_count by at least 1."""
    obj = make_workspace_objective(state)
    if backend == WorkspaceBackend.LEGACY:
        return realize_objective(
            state,
            obj,
            mode=mode,
            max_cost=max_cost,
            max_nodes=max_nodes,
            time_limit_s=time_limit_s,
        )
    t0 = time.time()
    if empty_count(state) >= obj.target_params["min_empty"]:
        return RealizationResult(
            status=RealizationStatus.ALREADY_SATISFIED,
            objective=obj,
            mode=mode,
            corrected_mw_cost=0,
            actions=(),
            action_labels=(),
            result_key_hex=None,
            nodes_expanded=0,
            elapsed_seconds=0.0,
            target_verified=True,
            exact_within_bound=True,
            max_cost=0,
            max_nodes=max_nodes,
            notes=("fact: already satisfied",),
        )
    target = int(obj.target_params["min_empty"])
    status, actions, cost, nodes, notes = _search_improved(
        state, target, max_cost, max_nodes, time_limit_s, t0
    )
    verified = False
    key_hex = None
    if status == RealizationStatus.FOUND and actions:
        st2 = state.clone()
        recost = replay_actions(st2, list(actions))
        ok = empty_count(st2) >= target
        verified = ok and recost == cost
        if not ok:
            status = RealizationStatus.NOT_FOUND_WITHIN_BOUND
            notes = notes + ("fact: replay failed target verification",)
            actions = ()
            cost = None
        elif recost != cost:
            notes = notes + (f"fact: recomputed cost {recost}",)
            cost = recost
        if verified:
            key_hex = hex(hash(canonical_state_key(st2)))[-16:]
    return RealizationResult(
        status=status,
        objective=obj,
        mode=mode,
        corrected_mw_cost=cost,
        actions=tuple(actions or ()),
        action_labels=tuple(
            f"move {a[0] + 1} {a[1] + 1} {a[2]}" if isinstance(a, tuple) and len(a) == 3 else str(a)
            for a in (actions or ())
        ),
        result_key_hex=key_hex,
        nodes_expanded=nodes,
        elapsed_seconds=time.time() - t0,
        target_verified=verified,
        exact_within_bound=status == RealizationStatus.FOUND and verified,
        max_cost=max_cost,
        max_nodes=max_nodes,
        notes=notes,
    )


def productive_follow_on(
    start: SpiderState,
    actions: Sequence[Action],
    *,
    max_cost: int = 4,
    max_nodes: int = 400,
    time_limit_s: float = 0.35,
) -> Tuple[FollowOnResult, ...]:
    """Diagnostic: can the new empty enable a cheap useful follow-on?"""
    st = start.clone()
    if actions:
        replay_actions(st, list(actions))
    out: List[FollowOnResult] = []
    port = generate_objective_portfolio(st, max_objectives=10)
    wanted = (
        ObjectiveKind.EXPOSE_REVEAL_PREFIX,
        ObjectiveKind.CONSOLIDATE_SAME_SUIT,
        ObjectiveKind.ADVANCE_FOUNDATION,
    )
    tried = 0
    for obj in port.objectives:
        if obj.kind not in wanted:
            continue
        if obj.kind == ObjectiveKind.EXPOSE_REVEAL_PREFIX:
            if int(obj.target_params.get("required_reveals", 99)) > 2:
                continue
        tried += 1
        if tried > 4:
            break
        res = realize_objective(
            st,
            obj,
            mode=RealizationMode.EXACT_BOUNDED,
            max_cost=max_cost,
            max_nodes=max_nodes,
            time_limit_s=time_limit_s,
        )
        out.append(
            FollowOnResult(
                kind=obj.kind.value,
                found=res.status == RealizationStatus.FOUND,
                cost=res.corrected_mw_cost,
                notes=obj.objective_id,
            )
        )
    return tuple(out)


def compare_workspace_backends(
    state: SpiderState,
    *,
    ceilings: Sequence[int] = (3, 5, 8, 12),
    max_nodes: int = 2000,
    time_limit_s: float = 0.8,
) -> Dict[str, Tuple[WorkspaceAttempt, ...]]:
    """Run legacy and improved at each ceiling."""
    e0 = empty_count(state)
    out: Dict[str, List[WorkspaceAttempt]] = {"legacy": [], "improved": []}
    for ceil in ceilings:
        for backend in (WorkspaceBackend.LEGACY, WorkspaceBackend.IMPROVED):
            res = realize_workspace(
                state,
                backend=backend,
                max_cost=int(ceil),
                max_nodes=max_nodes,
                time_limit_s=time_limit_s,
            )
            e1 = e0
            follow: Tuple[FollowOnResult, ...] = ()
            if res.status == RealizationStatus.FOUND and res.actions:
                chk = state.clone()
                replay_actions(chk, list(res.actions))
                e1 = empty_count(chk)
                follow = productive_follow_on(state, res.actions)
            out[backend.value].append(
                WorkspaceAttempt(
                    backend=backend,
                    status=res.status,
                    cost=res.corrected_mw_cost,
                    actions=res.actions,
                    nodes=res.nodes_expanded,
                    elapsed=res.elapsed_seconds,
                    empty_before=e0,
                    empty_after=e1,
                    follow_on=follow,
                    notes=res.notes,
                )
            )
    return {k: tuple(v) for k, v in out.items()}
