"""Isolated resource-aware excavation planner (v0.1 experiment).

Search bounded RESOURCE OPERATORS, each realised by a short pattern-matching
tactical step.  This is not unrestricted tableau BFS, not a CLEAN-macro
widening, and not a controller/scheduler integration.

Local transposition is planner-only.  Production/global TT and proof
semantics are untouched.  ``proof_pruning_allowed`` is always False.

Not imported by ``anytime_controller``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterator, List, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.move_lifecycle import assess_tableau_move
from spider.planner.receiver_uncover import _movable_run_length
from spider.state_identity import CanonicalStateKey, canonical_state_key


TableauMove = Tuple[int, int, int]

# Structural caps.  These are not the bounded-excavation 8/5000 envelope.
MAX_OPERATORS = 8
MAX_UNRESOLVED_OBLIGATIONS = 2
MAX_REALISER_MOVES = 4


class ResourcePlanResult(str, Enum):
    REALISED_CAMPAIGN_PROGRESS = "REALISED_CAMPAIGN_PROGRESS"
    PREPAID_DEPENDENCY = "PREPAID_DEPENDENCY"
    NO_BOUNDED_PLAN = "NO_BOUNDED_PLAN"
    RESOURCE_DEADLOCK = "RESOURCE_DEADLOCK"


class OperatorKind(str, Enum):
    CREATE_WORKSPACE = "CREATE_WORKSPACE"
    INVEST_WORKSPACE = "INVEST_WORKSPACE"
    RECOVER_WORKSPACE = "RECOVER_WORKSPACE"
    RESERVE_RECEIVER = "RESERVE_RECEIVER"
    PREPAY_DEPENDENCY = "PREPAY_DEPENDENCY"
    TEMPORARY_REWORK = "TEMPORARY_REWORK"
    REPAY_REWORK = "REPAY_REWORK"
    REALISE_CAMPAIGN_EDGE = "REALISE_CAMPAIGN_EDGE"


@dataclass(frozen=True)
class CampaignTarget:
    """Caller-supplied scheduled same-suit edge.  Not inferred from a deal."""

    suit: str
    high_rank: int
    low_rank: int


@dataclass(frozen=True)
class ReceiverReservation:
    """One physical receiver copy reserved for one scheduled consumer."""

    column: int
    suit: str
    rank: int
    consumer_suit: str
    consumer_rank: int


@dataclass(frozen=True)
class WorkspaceObligation:
    """Borrowed empty column that must be returned to empty.

    ``occupant_*`` is the invested run head (not necessarily the column top).
    Occupancy of the borrowed column, not a top-card match, is the debt.
    """

    column: int
    occupant_suit: str
    occupant_rank: int
    recovery_rank: int


@dataclass(frozen=True)
class ReworkDebt:
    """At most one bounded broken stable join, with a known repair dest.

    ``restore_join_count`` is the matching-join capacity before the break.
    An untouched duplicate join elsewhere must not discharge this debt.
    """

    suit: str
    high_rank: int
    low_rank: int
    origin_column: int
    parked_column: int
    restore_join_count: int


@dataclass(frozen=True)
class ObligationState:
    reservation: Optional[ReceiverReservation] = None
    workspace: Optional[WorkspaceObligation] = None
    rework: Optional[ReworkDebt] = None

    def unresolved_count(self) -> int:
        return int(self.reservation is not None) + int(
            self.workspace is not None
        ) + int(self.rework is not None)


@dataclass(frozen=True)
class ResourceExcavationPlan:
    result: ResourcePlanResult
    actions: Tuple[TableauMove, ...] = ()
    operators: Tuple[OperatorKind, ...] = ()
    operator_trace: Tuple[Tuple[OperatorKind, Tuple[TableauMove, ...]], ...] = ()
    cost: int = 0
    visited: int = 0
    replay_ok: bool = False
    edge_before: int = 0
    edge_after: int = 0
    proof_pruning_allowed: bool = False
    reject: Optional[str] = None


@dataclass(frozen=True)
class OperatorRealisation:
    kind: OperatorKind
    actions: Tuple[TableauMove, ...]
    state: SpiderState
    obligations: ObligationState


def empty_obligations() -> ObligationState:
    return ObligationState()


def local_transposition_key(
    state: SpiderState, obligations: ObligationState
) -> Tuple[CanonicalStateKey, Tuple]:
    """Planner-local identity.  Never written to the production TT."""

    return (
        canonical_state_key(state),
        canonical_outstanding_obligations(state, obligations),
    )


def canonical_outstanding_obligations(
    state: SpiderState, obligations: ObligationState
) -> Tuple:
    obl = normalize_obligations(state, obligations)
    parts: List[Tuple] = []
    if obl.reservation is not None:
        reserved = obl.reservation
        parts.append(
            (
                "R",
                reserved.column,
                reserved.suit,
                reserved.rank,
                reserved.consumer_suit,
                reserved.consumer_rank,
            )
        )
    if obl.workspace is not None:
        workspace = obl.workspace
        parts.append(
            (
                "W",
                workspace.column,
                workspace.occupant_suit,
                workspace.occupant_rank,
                workspace.recovery_rank,
            )
        )
    if obl.rework is not None:
        debt = obl.rework
        parts.append(
            (
                "D",
                debt.suit,
                debt.high_rank,
                debt.low_rank,
                debt.origin_column,
                debt.parked_column,
                debt.restore_join_count,
            )
        )
    return tuple(parts)


def unique_usable_receiver_column(
    state: SpiderState, target: CampaignTarget
) -> Optional[int]:
    """Column of the unique currently-top campaign-high copy, or None."""

    cols = _rank_top_copies(state, target.suit, target.high_rank)
    if len(cols) != 1:
        return None
    return cols[0]


def receiver_threat_action(
    state: SpiderState, target: CampaignTarget
) -> Optional[TableauMove]:
    """Engine-legal non-owner consume of a campaign-high top.

    Anchored to the threatened receiver column.  A second identical copy
    elsewhere is a different resource.  The rightful campaign low is not a
    threat.  Absence of a threat means RESERVE_RECEIVER has no future
    consequence and must not be generated.
    """

    receivers = _rank_top_copies(state, target.suit, target.high_rank)
    for receiver in receivers:
        for src in range(len(state.columns)):
            if src == receiver:
                continue
            max_k = _movable_run_length(state, src)
            for k in range(1, max_k + 1):
                if not state.can_move(src, receiver, k):
                    continue
                head = state.columns[src].face_up[-k]
                if head.suit == target.suit and head.rank == target.low_rank:
                    continue
                return (src, receiver, k)
    return None


def is_reserved_receiver_misuse(
    state: SpiderState,
    obligations: ObligationState,
    action: TableauMove,
) -> bool:
    """True when ``action`` would consume a RESERVED copy for a non-owner."""

    reserved = obligations.reservation
    if reserved is None:
        return False
    src, dst, k = action
    if dst != reserved.column:
        return False
    dest_top = state.columns[dst].top()
    if dest_top is None:
        return False
    if dest_top.suit != reserved.suit or dest_top.rank != reserved.rank:
        return False
    if k <= 0 or k > len(state.columns[src].face_up):
        return True
    head = state.columns[src].face_up[-k]
    return not (
        head.suit == reserved.consumer_suit and head.rank == reserved.consumer_rank
    )


def plan_resource_excavation(
    state: SpiderState,
    target: CampaignTarget,
    *,
    obligations: Optional[ObligationState] = None,
    disabled_operators: Sequence[OperatorKind] = (),
) -> ResourceExcavationPlan:
    """Search operator sequences for campaign-edge or prepaid progress."""

    start = state.clone()
    start_obl = normalize_obligations(start, obligations or empty_obligations())
    edges0 = _edge_count(start, target)
    queue: deque[
        Tuple[
            SpiderState,
            ObligationState,
            Tuple[TableauMove, ...],
            Tuple[Tuple[OperatorKind, Tuple[TableauMove, ...]], ...],
        ]
    ] = deque()
    queue.append((start, start_obl, (), ()))
    seen = {local_transposition_key(start, start_obl)}
    visited = 0
    saw_mutex = _resource_deadlock(start, start_obl, target)
    prepaid_hit: Optional[ResourceExcavationPlan] = None

    while queue:
        cur, obl, actions, trace = queue.popleft()
        visited += 1
        ops = tuple(kind for kind, _acts in trace)
        edges = _edge_count(cur, target)
        if edges > edges0 and obl.unresolved_count() == 0:
            replay = start.clone()
            try:
                paid = replay_actions(replay, list(actions))
            except (ValueError, AssertionError, IndexError):
                continue
            if _edge_count(replay, target) > edges0:
                return ResourceExcavationPlan(
                    ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS,
                    actions=actions,
                    operators=ops,
                    operator_trace=trace,
                    cost=paid,
                    visited=visited,
                    replay_ok=True,
                    edge_before=edges0,
                    edge_after=_edge_count(replay, target),
                )
        if prepaid_hit is None:
            prepaid = _prepaid_success(start, cur, obl, target, actions)
            if prepaid is not None:
                prepaid_hit = ResourceExcavationPlan(
                    ResourcePlanResult.PREPAID_DEPENDENCY,
                    actions=actions,
                    operators=ops,
                    operator_trace=trace,
                    cost=prepaid,
                    visited=visited,
                    replay_ok=True,
                    edge_before=edges0,
                    edge_after=edges,
                )
        if len(trace) >= MAX_OPERATORS:
            continue
        for step in _generate_steps(
            cur, obl, target, disabled=disabled_operators
        ):
            if any(is_reserved_receiver_misuse(cur, obl, action) for action in step.actions):
                continue
            new_obl = normalize_obligations(step.state, step.obligations)
            if new_obl.unresolved_count() > MAX_UNRESOLVED_OBLIGATIONS:
                continue
            if (
                new_obl.workspace is not None
                and obl.workspace is not None
                and new_obl.workspace != obl.workspace
            ):
                continue
            if new_obl.rework is not None and obl.rework is not None and new_obl.rework != obl.rework:
                continue
            if (
                new_obl.reservation is not None
                and obl.reservation is not None
                and new_obl.reservation != obl.reservation
            ):
                continue
            key = local_transposition_key(step.state, new_obl)
            if key in seen:
                continue
            seen.add(key)
            if _resource_deadlock(step.state, new_obl, target):
                saw_mutex = True
            queue.append(
                (
                    step.state,
                    new_obl,
                    actions + step.actions,
                    trace + ((step.kind, step.actions),),
                )
            )

    if prepaid_hit is not None:
        return prepaid_hit
    result = (
        ResourcePlanResult.RESOURCE_DEADLOCK
        if saw_mutex
        else ResourcePlanResult.NO_BOUNDED_PLAN
    )
    return ResourceExcavationPlan(
        result,
        visited=visited,
        edge_before=edges0,
        edge_after=edges0,
        reject=result.value,
    )


def apply_operator(
    state: SpiderState,
    target: CampaignTarget,
    kind: OperatorKind,
    *,
    obligations: Optional[ObligationState] = None,
    candidate: Optional[TableauMove] = None,
) -> Optional[OperatorRealisation]:
    """Realise one named operator, or None on failure.  Used by negative controls."""

    obl = normalize_obligations(state, obligations or empty_obligations())
    if candidate is not None and is_reserved_receiver_misuse(state, obl, candidate):
        return None
    for step in _generate_steps(state, obl, target, kinds=(kind,)):
        if candidate is None or candidate in step.actions or step.actions[:1] == (candidate,):
            if any(is_reserved_receiver_misuse(state, obl, action) for action in step.actions):
                continue
            return OperatorRealisation(
                step.kind,
                step.actions,
                step.state,
                normalize_obligations(step.state, step.obligations),
            )
    return None


def normalize_obligations(
    state: SpiderState, obligations: ObligationState
) -> ObligationState:
    reservation = obligations.reservation
    if reservation is not None:
        top = state.columns[reservation.column].top()
        if (
            top is not None
            and top.suit == reservation.consumer_suit
            and top.rank == reservation.consumer_rank
        ):
            reservation = None

    workspace = obligations.workspace
    if workspace is not None:
        col = state.columns[workspace.column]
        if col.is_empty():
            workspace = None

    rework = obligations.rework
    if rework is not None and _join_count(
        state, rework.suit, rework.high_rank, rework.low_rank
    ) >= rework.restore_join_count:
        rework = None

    return ObligationState(reservation=reservation, workspace=workspace, rework=rework)


def _generate_steps(
    state: SpiderState,
    obl: ObligationState,
    target: CampaignTarget,
    *,
    kinds: Optional[Sequence[OperatorKind]] = None,
    disabled: Sequence[OperatorKind] = (),
) -> Iterator[OperatorRealisation]:
    order = kinds or (
        OperatorKind.RESERVE_RECEIVER,
        OperatorKind.REALISE_CAMPAIGN_EDGE,
        OperatorKind.REPAY_REWORK,
        OperatorKind.RECOVER_WORKSPACE,
        OperatorKind.CREATE_WORKSPACE,
        OperatorKind.PREPAY_DEPENDENCY,
        OperatorKind.TEMPORARY_REWORK,
        OperatorKind.INVEST_WORKSPACE,
    )
    blocked = set(disabled)
    if (
        kinds is None
        and obl.reservation is None
        and receiver_threat_action(state, target) is not None
    ):
        if OperatorKind.RESERVE_RECEIVER not in blocked:
            yield from _realise_reserve(state, obl, target)
        return
    generators: dict[OperatorKind, Callable[..., Iterator[OperatorRealisation]]] = {
        OperatorKind.RESERVE_RECEIVER: _realise_reserve,
        OperatorKind.REALISE_CAMPAIGN_EDGE: _realise_campaign,
        OperatorKind.REPAY_REWORK: _realise_repay,
        OperatorKind.RECOVER_WORKSPACE: _realise_recover,
        OperatorKind.CREATE_WORKSPACE: _realise_create,
        OperatorKind.PREPAY_DEPENDENCY: _realise_prepay,
        OperatorKind.TEMPORARY_REWORK: _realise_rework,
        OperatorKind.INVEST_WORKSPACE: _realise_invest,
    }
    for kind in order:
        if kind in blocked:
            continue
        yield from generators[kind](state, obl, target)


def _realise_reserve(
    state: SpiderState, obl: ObligationState, target: CampaignTarget
) -> Iterator[OperatorRealisation]:
    if obl.reservation is not None:
        return
    threat = receiver_threat_action(state, target)
    if threat is None:
        return
    column = threat[1]
    top = state.columns[column].top()
    if top is None or top.suit != target.suit or top.rank != target.high_rank:
        return
    reserved = ReceiverReservation(
        column,
        target.suit,
        target.high_rank,
        target.suit,
        target.low_rank,
    )
    yield OperatorRealisation(
        OperatorKind.RESERVE_RECEIVER,
        (),
        state.clone(),
        ObligationState(reserved, obl.workspace, obl.rework),
    )


def _realise_create(
    state: SpiderState, obl: ObligationState, target: CampaignTarget
) -> Iterator[OperatorRealisation]:
    if _idle_empties(state):
        return
    if obl.workspace is not None:
        return
    for src in range(len(state.columns)):
        col = state.columns[src]
        if col.face_down or not col.face_up:
            continue
        # Protect the actual campaign-high card, not every same-rank singleton.
        if (
            len(col.face_up) == 1
            and col.face_up[0].suit == target.suit
            and col.face_up[0].rank == target.high_rank
        ):
            continue
        k = len(col.face_up)
        if _movable_run_length(state, src) != k:
            continue
        for dst in range(len(state.columns)):
            if dst == src or not state.can_move(src, dst, k):
                continue
            if state.columns[dst].is_empty():
                continue
            action = (src, dst, k)
            if _breaks_join(state, action):
                continue
            if is_reserved_receiver_misuse(state, obl, action):
                continue
            if _occupies_unique_receiver(state, target, action, obl):
                continue
            nxt, ok = _play(state, (action,))
            if not ok or not nxt.columns[src].is_empty():
                continue
            if _edge_count(nxt, target) > _edge_count(state, target):
                continue
            yield OperatorRealisation(
                OperatorKind.CREATE_WORKSPACE,
                (action,),
                nxt,
                obl,
            )


def _realise_invest(
    state: SpiderState, obl: ObligationState, target: CampaignTarget
) -> Iterator[OperatorRealisation]:
    if obl.workspace is not None:
        return
    empties = _idle_empties(state)
    if not empties:
        return
    for src in range(len(state.columns)):
        k = _movable_run_length(state, src)
        if k <= 0:
            continue
        remaining = len(state.columns[src].face_up) - k
        if remaining <= 0 and not state.columns[src].face_down:
            continue
        head = state.columns[src].face_up[-k]
        if _breaks_join(state, (src, empties[0], k)):
            continue
        for dst in empties:
            action = (src, dst, k)
            if not state.can_move(src, dst, k):
                continue
            if _breaks_join(state, action):
                continue
            nxt, ok = _play(state, (action,))
            if not ok:
                continue
            exposed = nxt.columns[src].top()
            if exposed is None or not _useful_card(exposed, nxt, src, target):
                continue
            recovery = _recovery_dests(nxt, dst, k, obl, forbidden=(src,))
            if not recovery and not _realise_would_create_recovery_dest(
                nxt, src, head, exposed, target
            ):
                continue
            workspace = WorkspaceObligation(
                dst, head.suit, head.rank, head.rank + 1
            )
            yield OperatorRealisation(
                OperatorKind.INVEST_WORKSPACE,
                (action,),
                nxt,
                ObligationState(obl.reservation, workspace, obl.rework),
            )


def _realise_recover(
    state: SpiderState, obl: ObligationState, target: CampaignTarget
) -> Iterator[OperatorRealisation]:
    workspace = obl.workspace
    if workspace is None:
        return
    src = workspace.column
    k = _movable_run_length(state, src)
    if k <= 0:
        return
    head = state.columns[src].face_up[-k]
    if head.suit != workspace.occupant_suit or head.rank != workspace.occupant_rank:
        return
    for dst in _recovery_dests(state, src, k, obl):
        action = (src, dst, k)
        if is_reserved_receiver_misuse(state, obl, action):
            continue
        if _destroys_reserved_without_payoff(state, obl, target, action):
            continue
        dest_top = state.columns[dst].top()
        if (
            dest_top is not None
            and dest_top.suit == target.suit
            and dest_top.rank == target.low_rank
            and _edge_count(state, target) == 0
        ):
            # Recovering onto the still-unrealised campaign low re-covers it.
            continue
        nxt, ok = _play(state, (action,))
        if not ok or not nxt.columns[src].is_empty():
            continue
        if _edge_count(nxt, target) < _edge_count(state, target):
            continue
        yield OperatorRealisation(
            OperatorKind.RECOVER_WORKSPACE,
            (action,),
            nxt,
            ObligationState(obl.reservation, None, obl.rework),
        )


def _realise_prepay(
    state: SpiderState, obl: ObligationState, target: CampaignTarget
) -> Iterator[OperatorRealisation]:
    empties = _idle_empties(state)
    if not empties or obl.workspace is not None:
        return
    empty = empties[0]
    for src in range(len(state.columns)):
        up = state.columns[src].face_up
        if len(up) < 3:
            continue
        top, second, useful = up[-1], up[-2], up[-3]
        if top.rank + 1 != second.rank:
            continue
        if _same_suit_join(second, top) or _same_suit_join(useful, second):
            continue
        if not _useful_card(useful, state, src, target):
            continue
        if _movable_run_length(state, src) != 1:
            continue
        park = (src, empty, 1)
        if not state.can_move(src, empty, 1) or _breaks_join(state, park):
            continue
        mid, ok = _play(state, (park,))
        if not ok:
            continue
        dests = [
            dst
            for dst in range(len(mid.columns))
            if dst not in (src, empty)
            and mid.columns[dst].top() is not None
            and mid.columns[dst].top().rank == second.rank + 1
            and mid.can_move(src, dst, 1)
        ]
        for dest in dests:
            peel = (src, dest, 1)
            if _breaks_join(mid, peel):
                continue
            if is_reserved_receiver_misuse(mid, obl, peel):
                continue
            after_peel, ok_peel = _play(mid, (peel,))
            if not ok_peel:
                continue
            recover = (empty, dest, 1)
            if not after_peel.can_move(empty, dest, 1):
                continue
            if _breaks_join(after_peel, recover):
                continue
            end, ok_end = _play(after_peel, (recover,))
            if not ok_end:
                continue
            if not end.columns[empty].is_empty():
                continue
            new_top = end.columns[src].top()
            if new_top is None or not _same_card(new_top, useful):
                continue
            yield OperatorRealisation(
                OperatorKind.PREPAY_DEPENDENCY,
                (park, peel, recover),
                end,
                ObligationState(obl.reservation, None, obl.rework),
            )


def _realise_rework(
    state: SpiderState, obl: ObligationState, target: CampaignTarget
) -> Iterator[OperatorRealisation]:
    if obl.rework is not None:
        return
    for src in range(len(state.columns)):
        up = state.columns[src].face_up
        if len(up) < 2:
            continue
        max_k = _movable_run_length(state, src)
        if max_k <= 0:
            continue
        for k in range(1, max_k + 1):
            if k >= len(up):
                continue
            child = up[-k]
            parent = up[-k - 1]
            if not _same_suit_join(parent, child):
                continue
            if not _useful_card(parent, state, src, target) and not _useful_card(
                child, state, src, target
            ):
                if not (
                    parent.suit == target.suit
                    and parent.rank in (target.high_rank, target.low_rank)
                ):
                    continue
            dests = _rework_destinations(state, src, k, obl, target)
            if not dests:
                continue
            for dst in dests:
                action = (src, dst, k)
                if not _breaks_join(state, action):
                    continue
                if is_reserved_receiver_misuse(state, obl, action):
                    continue
                nxt, ok = _play(state, (action,))
                if not ok:
                    continue
                workspace = obl.workspace
                if nxt.columns[dst].top() is not None and state.columns[dst].is_empty():
                    workspace = WorkspaceObligation(
                        dst, child.suit, child.rank, child.rank + 1
                    )
                debt = ReworkDebt(
                    parent.suit,
                    parent.rank,
                    child.rank,
                    src,
                    dst,
                    _join_count(state, parent.suit, parent.rank, child.rank),
                )
                new_obl = ObligationState(obl.reservation, workspace, debt)
                if new_obl.unresolved_count() > MAX_UNRESOLVED_OBLIGATIONS:
                    continue
                yield OperatorRealisation(
                    OperatorKind.TEMPORARY_REWORK,
                    (action,),
                    nxt,
                    new_obl,
                )


def _realise_repay(
    state: SpiderState, obl: ObligationState, target: CampaignTarget
) -> Iterator[OperatorRealisation]:
    debt = obl.rework
    if debt is None:
        return
    parked = debt.parked_column
    k = _movable_run_length(state, parked)
    if k <= 0:
        return
    head = state.columns[parked].face_up[-k]
    if head.suit != debt.suit or head.rank != debt.low_rank:
        return
    high_col = _find_top(state, debt.suit, debt.high_rank)
    if high_col is None:
        return
    action = (parked, high_col, k)
    if not state.can_move(parked, high_col, k):
        return
    if is_reserved_receiver_misuse(state, obl, action):
        return
    nxt, ok = _play(state, (action,))
    if not ok:
        return
    workspace = obl.workspace
    if workspace is not None and parked == workspace.column and nxt.columns[parked].is_empty():
        workspace = None
    yield OperatorRealisation(
        OperatorKind.REPAY_REWORK,
        (action,),
        nxt,
        ObligationState(obl.reservation, workspace, None),
    )


def _realise_campaign(
    state: SpiderState, obl: ObligationState, target: CampaignTarget
) -> Iterator[OperatorRealisation]:
    highs = [
        i
        for i, col in enumerate(state.columns)
        if col.top() is not None
        and col.top().suit == target.suit
        and col.top().rank == target.high_rank
    ]
    if obl.reservation is not None:
        highs = [i for i in highs if i == obl.reservation.column]
    for src in range(len(state.columns)):
        k = _campaign_source_k(state, src, target)
        if k <= 0:
            continue
        for dst in highs:
            if src == dst:
                continue
            action = (src, dst, k)
            if not state.can_move(src, dst, k):
                continue
            if is_reserved_receiver_misuse(state, obl, action):
                continue
            nxt, ok = _play(state, (action,))
            if not ok:
                continue
            if _edge_count(nxt, target) <= _edge_count(state, target):
                continue
            yield OperatorRealisation(
                OperatorKind.REALISE_CAMPAIGN_EDGE,
                (action,),
                nxt,
                obl,
            )


def _prepaid_success(
    start: SpiderState,
    cur: SpiderState,
    obl: ObligationState,
    target: CampaignTarget,
    actions: Tuple[TableauMove, ...],
) -> Optional[int]:
    if not actions:
        return None
    if obl.reservation is not None or obl.workspace is not None or obl.rework is not None:
        return None
    if _edge_count(cur, target) > _edge_count(start, target):
        return None
    if unique_usable_receiver_column(cur, target) is None:
        return None
    exposed = False
    for ci, col in enumerate(cur.columns):
        top = col.top()
        if top is None or not _useful_card(top, cur, ci, target):
            continue
        start_top = start.columns[ci].top()
        if start_top is None or not _same_card(start_top, top):
            exposed = True
            break
    if not exposed:
        return None
    replay = start.clone()
    try:
        paid = replay_actions(replay, list(actions))
    except (ValueError, AssertionError, IndexError):
        return None
    return paid


def _resource_deadlock(
    state: SpiderState, obl: ObligationState, target: CampaignTarget
) -> bool:
    if _edge_count(state, target) > 0 and _find_top(state, target.suit, target.low_rank) is None:
        return False
    if _campaign_source_k_any(state, target) and _find_top(state, target.suit, target.high_rank) is not None:
        return False
    empties = _idle_empties(state)
    reserved_col = None
    if obl.reservation is not None:
        reserved_col = obl.reservation.column
    else:
        reserved_col = _find_top(state, target.suit, target.high_rank)
    if reserved_col is None:
        return False
    if empties:
        if obl.workspace is None:
            return False
        src = obl.workspace.column
        k = _movable_run_length(state, src)
        if k <= 0:
            return False
        dests = [
            dst
            for dst in range(len(state.columns))
            if dst != src and state.can_move(src, dst, k)
        ]
        if not dests:
            return False
        return all(
            is_reserved_receiver_misuse(state, obl, (src, dst, k))
            or _destroys_reserved_without_payoff(state, obl, target, (src, dst, k))
            for dst in dests
        )
    # No empty: creating one only by occupying the unique receiver.
    emptying = []
    for src in range(len(state.columns)):
        col = state.columns[src]
        if col.face_down or not col.face_up:
            continue
        k = len(col.face_up)
        if _movable_run_length(state, src) != k:
            continue
        for dst in range(len(state.columns)):
            if dst == src or not state.can_move(src, dst, k):
                continue
            emptying.append((src, dst, k))
    if not emptying:
        return False
    fake = obl
    if fake.reservation is None and reserved_col is not None:
        fake = ObligationState(
            ReceiverReservation(
                reserved_col,
                target.suit,
                target.high_rank,
                target.suit,
                target.low_rank,
            ),
            obl.workspace,
            obl.rework,
        )
    return all(
        is_reserved_receiver_misuse(state, fake, action)
        or _occupies_unique_receiver(state, target, action, fake)
        for action in emptying
    )


def _rework_destinations(
    state: SpiderState,
    src: int,
    k: int,
    obl: ObligationState,
    target: CampaignTarget,
) -> Tuple[int, ...]:
    dests = []
    for dst in range(len(state.columns)):
        if dst == src or not state.can_move(src, dst, k):
            continue
        if is_reserved_receiver_misuse(state, obl, (src, dst, k)):
            continue
        dest_top = state.columns[dst].top()
        if dest_top is None:
            dests.append(dst)
            continue
        dests.append(dst)
    return tuple(dests)


def _realise_would_create_recovery_dest(
    post_invest: SpiderState,
    source_column: int,
    occupant: Card,
    exposed: Card,
    target: CampaignTarget,
) -> bool:
    """True when realising the newly exposed campaign low creates occupant's dest.

    The parked card's recovery rank is occupant.rank+1.  If that equals the
    exposed campaign low, joining the low onto the unique campaign high makes
    a bounded recovery dest that does not re-cover the source in place.
    """

    if exposed.suit != target.suit or exposed.rank != target.low_rank:
        return False
    if occupant.rank + 1 != exposed.rank:
        return False
    receiver = unique_usable_receiver_column(post_invest, target)
    if receiver is None or receiver == source_column:
        return False
    k = _campaign_source_k(post_invest, source_column, target)
    return k > 0 and post_invest.can_move(source_column, receiver, k)


def _recovery_dests(
    state: SpiderState,
    src: int,
    k: int,
    obl: ObligationState,
    forbidden: Tuple[int, ...] = (),
) -> List[int]:
    dests = []
    for dst in range(len(state.columns)):
        if dst == src or dst in forbidden:
            continue
        if not state.can_move(src, dst, k):
            continue
        if state.columns[dst].is_empty():
            continue
        if is_reserved_receiver_misuse(state, obl, (src, dst, k)):
            continue
        dests.append(dst)
    return dests


def _occupies_unique_receiver(
    state: SpiderState,
    target: CampaignTarget,
    action: TableauMove,
    obl: ObligationState,
) -> bool:
    src, dst, k = action
    dest_top = state.columns[dst].top()
    if dest_top is None:
        return False
    if dest_top.suit != target.suit or dest_top.rank != target.high_rank:
        return False
    head = state.columns[src].face_up[-k]
    if head.suit == target.suit and head.rank == target.low_rank:
        return False
    copies = _rank_top_copies(state, target.suit, target.high_rank)
    return len(copies) <= 1


def _destroys_reserved_without_payoff(
    state: SpiderState,
    obl: ObligationState,
    target: CampaignTarget,
    action: TableauMove,
) -> bool:
    if not is_reserved_receiver_misuse(state, obl, action) and obl.reservation is None:
        reserved_col = _find_top(state, target.suit, target.high_rank)
        if reserved_col is None or action[1] != reserved_col:
            return False
        src, dst, k = action
        head = state.columns[src].face_up[-k]
        if head.suit == target.suit and head.rank == target.low_rank:
            return False
        return True
    if is_reserved_receiver_misuse(state, obl, action):
        return True
    return False


def _campaign_source_k(state: SpiderState, src: int, target: CampaignTarget) -> int:
    """Realise only an already-exposed campaign low.

    A buried low that is merely the head of a same-suit run under a join is
    not yet a realisable source; exposing it is TEMPORARY_REWORK, not REALISE.
    """

    up = state.columns[src].face_up
    if not up:
        return 0
    top = up[-1]
    if top.suit != target.suit or top.rank != target.low_rank:
        return 0
    k = _movable_run_length(state, src)
    if k <= 0:
        return 0
    return 1


def _campaign_source_k_any(state: SpiderState, target: CampaignTarget) -> bool:
    return any(_campaign_source_k(state, src, target) > 0 for src in range(len(state.columns)))


def _useful_card(
    card: Optional[Card], state: SpiderState, column: int, target: CampaignTarget
) -> bool:
    if card is None:
        return False
    if card.suit == target.suit and card.rank in (target.high_rank, target.low_rank):
        return True
    for held in list(state.columns[column].face_up) + list(state.columns[column].face_down):
        if held.suit == target.suit and held.rank in (target.high_rank, target.low_rank):
            return True
    return False


def _idle_empties(state: SpiderState) -> Tuple[int, ...]:
    return tuple(i for i, col in enumerate(state.columns) if col.is_empty())


def _find_top(state: SpiderState, suit: str, rank: int) -> Optional[int]:
    for i, col in enumerate(state.columns):
        top = col.top()
        if top is not None and top.suit == suit and top.rank == rank:
            return i
    return None


def _rank_top_copies(state: SpiderState, suit: str, rank: int) -> List[int]:
    return [
        i
        for i, col in enumerate(state.columns)
        if col.top() is not None and col.top().suit == suit and col.top().rank == rank
    ]


def _edge_count(state: SpiderState, target: CampaignTarget) -> int:
    n = 0
    for col in state.columns:
        up = col.face_up
        for a, b in zip(up, up[1:]):
            if (
                a.suit == target.suit
                and b.suit == target.suit
                and a.rank == target.high_rank
                and b.rank == target.low_rank
            ):
                n += 1
    return n


def _join_count(state: SpiderState, suit: str, high: int, low: int) -> int:
    n = 0
    for col in state.columns:
        up = col.face_up
        for a, b in zip(up, up[1:]):
            if a.suit == suit and b.suit == suit and a.rank == high and b.rank == low:
                n += 1
    return n


def _join_present(state: SpiderState, suit: str, high: int, low: int) -> bool:
    return _join_count(state, suit, high, low) > 0


def _same_suit_join(parent: Card, child: Card) -> bool:
    return parent.suit == child.suit and parent.rank - 1 == child.rank


def _same_card(a: Card, b: Card) -> bool:
    return a.suit == b.suit and a.rank == b.rank


def _breaks_join(state: SpiderState, action: TableauMove) -> bool:
    life = assess_tableau_move(state, action, discover_exit=False)
    return bool(life.same_suit_joins_broken)


def _play(
    state: SpiderState, actions: Sequence[TableauMove]
) -> Tuple[SpiderState, bool]:
    if len(actions) > MAX_REALISER_MOVES:
        return state, False
    nxt = state.clone()
    try:
        replay_actions(nxt, list(actions))
    except (ValueError, AssertionError, IndexError):
        return state, False
    return nxt, True
