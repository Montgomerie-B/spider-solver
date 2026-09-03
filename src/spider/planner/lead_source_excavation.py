"""Bounded current-lead source excavation.

Recognise only the exact stock-empty two-peel + consume pattern:

* the current lead's first missing edge needs a face-up source S
  covered by exactly one blocker B;
* B has no legal receiver now;
* a same-suit receiver R for B is buried under exactly two face-up cards;
* those two cards peel as MIXED_SUIT_PARK moves (no empty destination,
  no stable join broken);
* B then joins R and that consume exposes S.

This is not generic depth-2/3 search, not a mixed-park cap raise, and not
a widening of receiver-uncover.  Canonical lead.ordering_key() is evaluated
only after the complete three-action macro.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.move_lifecycle import PlacementClass, assess_tableau_move
from spider.planner.receiver_uncover import (
    _lead_ordering_key,
    _movable_run_length,
)
from spider.planner.whole_deal_scheduler import (
    build_whole_deal_blueprint,
    rebuild_whole_deal_schedule,
)
from spider.rules import MW_RULES


TableauMove = Tuple[int, int, int]
Macro = Tuple[TableauMove, TableauMove, TableauMove]


class LeadSourceExcavationReject(str, Enum):
    STOCK_NONEMPTY = "stock_nonempty"
    NO_CURRENT_LEAD = "no_current_lead"
    NO_MISSING_EDGE = "no_missing_edge"
    NO_SINGLE_BLOCKER_SOURCE = "no_single_blocker_source"
    BLOCKER_ALREADY_MOVABLE = "blocker_already_movable"
    RECEIVER_NEEDS_OTHER_THAN_TWO_PEELS = "receiver_needs_other_than_two_peels"
    PARK_JOIN_BROKEN = "park_join_broken"
    PARK_USES_EMPTY = "park_uses_empty"
    PARK_NOT_MIXED = "park_not_mixed"
    CONSUME_NOT_STABLE_JOIN = "consume_not_stable_join"
    CONSUME_NOT_SAME_SUIT = "consume_not_same_suit"
    SOURCE_NOT_EXPOSED = "source_not_exposed"
    SOURCE_UNRELATED_TO_LEAD = "source_unrelated_to_lead"
    CANONICAL_WORSE = "canonical_worse"
    ILLEGAL_INTERMEDIATE = "illegal_intermediate"
    ALREADY_COVERED = "already_covered"


@dataclass(frozen=True)
class LeadSourceExcavationEvidence:
    qualified: bool
    reject: Optional[LeadSourceExcavationReject] = None
    actions: Optional[Macro] = None
    cost: int = 0
    source: Optional[Card] = None
    blocker: Optional[Card] = None
    receiver: Optional[Card] = None
    source_column: Optional[int] = None
    receiver_column: Optional[int] = None
    pre_key: Optional[Tuple] = None
    post_key: Optional[Tuple] = None
    proof_pruning_allowed: bool = False


def _lead(state: SpiderState):
    if state.stock:
        return None
    schedule = rebuild_whole_deal_schedule(state, build_whole_deal_blueprint(state))
    if schedule.lane_sequence_priority is None:
        return None
    return schedule.lane_sequence_priority.lead


def _park_ok(state: SpiderState, action: TableauMove) -> Optional[LeadSourceExcavationReject]:
    src, dst, k = action
    if not state.can_move(src, dst, k):
        return LeadSourceExcavationReject.ILLEGAL_INTERMEDIATE
    if state.columns[dst].is_empty():
        return LeadSourceExcavationReject.PARK_USES_EMPTY
    life = assess_tableau_move(state, action, discover_exit=False)
    if life.placement_class != PlacementClass.MIXED_SUIT_PARK:
        return LeadSourceExcavationReject.PARK_NOT_MIXED
    if life.same_suit_joins_broken:
        return LeadSourceExcavationReject.PARK_JOIN_BROKEN
    return None


def _blocker_destinations(state: SpiderState, column: int) -> Tuple[int, ...]:
    k = _movable_run_length(state, column)
    if k <= 0:
        return ()
    return tuple(
        dst
        for dst in range(10)
        if dst != column and state.can_move(column, dst, k)
    )


def _mixed_peel_destinations(state: SpiderState, column: int) -> Tuple[TableauMove, ...]:
    k = _movable_run_length(state, column)
    if k != 1:
        return ()
    moves = []
    for dst in range(10):
        if dst == column:
            continue
        action = (column, dst, 1)
        if _park_ok(state, action) is None:
            moves.append(action)
    return tuple(moves)


def _replay_macro(state: SpiderState, actions: Macro) -> Optional[Tuple[SpiderState, int]]:
    end = state.clone()
    try:
        cost = replay_actions(end, list(actions))
    except (ValueError, AssertionError, IndexError):
        return None
    return end, cost


def _first_missing_source_slots(state: SpiderState, lead) -> Tuple[Tuple[int, Card, Card], ...]:
    """(column, source, blocker) for face-up lead sources under exactly one card."""

    if not lead.missing_edges:
        return ()
    high, low = lead.missing_edges[0]
    needed = {high, low}
    slots = []
    for ci, col in enumerate(state.columns):
        up = col.face_up
        if len(up) < 2:
            continue
        if _movable_run_length(state, ci) != 1:
            continue
        source = up[-2]
        blocker = up[-1]
        if source.suit != lead.suit or source.rank not in needed:
            continue
        slots.append((ci, source, blocker))
    return tuple(slots)


def _receiver_slots(state: SpiderState, blocker: Card, source_column: int):
    """Columns where a same-suit receiver sits under exactly two face-up cards."""

    slots = []
    for ci, col in enumerate(state.columns):
        if ci == source_column:
            continue
        up = col.face_up
        if len(up) < 3:
            continue
        receiver = up[-3]
        if receiver.suit != blocker.suit or receiver.rank - 1 != blocker.rank:
            continue
        if _movable_run_length(state, ci) != 1:
            continue
        slots.append((ci, receiver))
    return tuple(slots)


def recognise_lead_source_excavation(
    state: SpiderState,
) -> Tuple[LeadSourceExcavationEvidence, ...]:
    """Return every qualified two-peel + consume macro, lex-smallest first."""

    if state.stock:
        return ()
    lead = _lead(state)
    if lead is None:
        return ()
    if not lead.missing_edges:
        return ()
    pre_key = _lead_ordering_key(state)
    if pre_key is None:
        return ()
    needed = set(lead.missing_edges[0])
    found = []
    for source_col, source, blocker in _first_missing_source_slots(state, lead):
        if _blocker_destinations(state, source_col):
            continue
        for recv_col, receiver in _receiver_slots(state, blocker, source_col):
            peels1 = _mixed_peel_destinations(state, recv_col)
            for park1 in peels1:
                mid = state.clone()
                mid.move(*park1, rules=MW_RULES)
                if _movable_run_length(mid, recv_col) != 1:
                    continue
                if mid.columns[recv_col].face_up[-1] == receiver:
                    continue
                peels2 = _mixed_peel_destinations(mid, recv_col)
                for park2 in peels2:
                    after2 = mid.clone()
                    after2.move(*park2, rules=MW_RULES)
                    if after2.columns[recv_col].top() != receiver:
                        continue
                    k3 = _movable_run_length(after2, source_col)
                    if k3 != 1:
                        continue
                    consume = (source_col, recv_col, 1)
                    if not after2.can_move(*consume):
                        continue
                    life3 = assess_tableau_move(after2, consume, discover_exit=False)
                    if life3.placement_class != PlacementClass.STABLE_SAME_SUIT_JOIN:
                        continue
                    if life3.same_suit_joins_broken:
                        continue
                    if receiver.suit != blocker.suit or receiver.rank - 1 != blocker.rank:
                        continue
                    replayed = _replay_macro(state, (park1, park2, consume))
                    if replayed is None:
                        continue
                    end, cost = replayed
                    exposed = end.columns[source_col].top()
                    if exposed != source:
                        continue
                    if exposed.suit != lead.suit or exposed.rank not in needed:
                        continue
                    post_key = _lead_ordering_key(end)
                    if post_key is None or post_key > pre_key:
                        continue
                    found.append(
                        LeadSourceExcavationEvidence(
                            True,
                            actions=(park1, park2, consume),
                            cost=cost,
                            source=source,
                            blocker=blocker,
                            receiver=receiver,
                            source_column=source_col,
                            receiver_column=recv_col,
                            pre_key=pre_key,
                            post_key=post_key,
                        )
                    )
    unique = {}
    for item in found:
        unique[item.actions] = item
    return tuple(sorted(unique.values(), key=lambda item: item.actions))


def lead_source_excavation_reject_reason(
    state: SpiderState,
) -> Optional[LeadSourceExcavationReject]:
    """Primary reason a state has no qualified macro.  Diagnostic only."""

    if state.stock:
        return LeadSourceExcavationReject.STOCK_NONEMPTY
    lead = _lead(state)
    if lead is None:
        return LeadSourceExcavationReject.NO_CURRENT_LEAD
    if not lead.missing_edges:
        return LeadSourceExcavationReject.NO_MISSING_EDGE
    pre_key = _lead_ordering_key(state)
    if pre_key is None:
        return LeadSourceExcavationReject.NO_CURRENT_LEAD
    slots = _first_missing_source_slots(state, lead)
    if not slots:
        return LeadSourceExcavationReject.NO_SINGLE_BLOCKER_SOURCE
    saw_two_peel = False
    saw_join_broken = False
    saw_empty = False
    saw_not_exposed = False
    saw_worse = False
    saw_movable = False
    for source_col, source, blocker in slots:
        if _blocker_destinations(state, source_col):
            saw_movable = True
            continue
        recvs = _receiver_slots(state, blocker, source_col)
        if not recvs:
            continue
        saw_two_peel = True
        for recv_col, receiver in recvs:
            for park1 in _mixed_peel_destinations(state, recv_col):
                if _park_ok(state, park1) == LeadSourceExcavationReject.PARK_JOIN_BROKEN:
                    saw_join_broken = True
                    continue
                if _park_ok(state, park1) == LeadSourceExcavationReject.PARK_USES_EMPTY:
                    saw_empty = True
                    continue
                mid = state.clone()
                mid.move(*park1, rules=MW_RULES)
                for park2 in _mixed_peel_destinations(mid, recv_col):
                    after2 = mid.clone()
                    after2.move(*park2, rules=MW_RULES)
                    if after2.columns[recv_col].top() != receiver:
                        continue
                    consume = (source_col, recv_col, 1)
                    if not after2.can_move(*consume):
                        continue
                    replayed = _replay_macro(state, (park1, park2, consume))
                    if replayed is None:
                        continue
                    end, _cost = replayed
                    if end.columns[source_col].top() != source:
                        saw_not_exposed = True
                        continue
                    post_key = _lead_ordering_key(end)
                    if post_key is None or post_key > pre_key:
                        saw_worse = True
                        continue
                    return None
    if saw_worse:
        return LeadSourceExcavationReject.CANONICAL_WORSE
    if saw_not_exposed:
        return LeadSourceExcavationReject.SOURCE_NOT_EXPOSED
    if saw_join_broken:
        return LeadSourceExcavationReject.PARK_JOIN_BROKEN
    if saw_empty:
        return LeadSourceExcavationReject.PARK_USES_EMPTY
    if saw_movable:
        return LeadSourceExcavationReject.BLOCKER_ALREADY_MOVABLE
    if not saw_two_peel:
        return LeadSourceExcavationReject.RECEIVER_NEEDS_OTHER_THAN_TWO_PEELS
    return LeadSourceExcavationReject.NO_SINGLE_BLOCKER_SOURCE


def already_covered_by_successors(actions: Macro, successor_actions) -> bool:
    packed = tuple(actions)
    for item in successor_actions:
        if item == packed:
            return True
    return False
