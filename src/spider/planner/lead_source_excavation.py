"""Bounded lead-source excavation evidence.

This is not generic two-ply or three-ply search.  A candidate first
MIXED_SUIT_PARK is inspected only when receiver-uncover does not already
qualify it.  The same source column is then allowed exactly one further
mixed park.  If that second park exposes an already-present same-suit
receiver, the exact consumer of that receiver is tested, and the consumer
must expose a current lead-lane buried source.

Lead ``ordering_key()`` is compared after the consume, not after peel 1.
Parked-card EXIT is not claimed.  Stable joins may not be broken.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.move_lifecycle import PlacementClass, assess_tableau_move
from spider.planner.receiver_uncover import (
    _lead_ordering_key,
    _movable_run_length,
    assess_receiver_uncover,
)
from spider.planner.whole_deal_scheduler import (
    build_whole_deal_blueprint,
    rebuild_whole_deal_schedule,
)
from spider.rules import MW_RULES


TableauMove = Tuple[int, int, int]


class LeadSourceExcavationReject(str, Enum):
    NOT_LEGAL = "not_legal"
    NOT_MIXED_PARK = "not_mixed_park"
    JOIN_BROKEN = "join_broken"
    UNCOVER_ALREADY_QUALIFIES = "uncover_already_qualifies"
    NO_SECOND_PEEL = "no_second_peel"
    NO_RECEIVER_AFTER_SECOND_PEEL = "no_receiver_after_second_peel"
    NO_SAME_SUIT_CONSUME = "no_same_suit_consume"
    NO_LEAD_SOURCE_EXPOSED = "no_lead_source_exposed"
    NO_CURRENT_LEAD = "no_current_lead"


@dataclass(frozen=True)
class LeadSourceExcavationEvidence:
    action: TableauMove
    qualified: bool
    reject: Optional[LeadSourceExcavationReject] = None
    second_park: Optional[TableauMove] = None
    consume: Optional[TableauMove] = None
    receiver: Optional[Card] = None
    consume_head: Optional[Card] = None
    exposed_source: Optional[Card] = None
    pre_key: Optional[Tuple] = None
    consume_key: Optional[Tuple] = None
    canonical_non_worse: bool = False
    proof_pruning_allowed: bool = False


def _lead_missing_ranks(state: SpiderState) -> Optional[Tuple[str, frozenset]]:
    schedule = rebuild_whole_deal_schedule(state, build_whole_deal_blueprint(state))
    if schedule.lane_sequence_priority is None or schedule.lane_sequence_priority.lead is None:
        return None
    lead = schedule.lane_sequence_priority.lead
    ranks = set()
    for high, low in lead.missing_edges:
        ranks.add(high)
        ranks.add(low)
    return lead.suit, frozenset(ranks)


def _apply(state: SpiderState, action: TableauMove) -> SpiderState:
    end = state.clone()
    end.move(*action, rules=MW_RULES)
    return end


def assess_lead_source_excavation(
    state: SpiderState,
    action: TableauMove,
) -> LeadSourceExcavationEvidence:
    """Return two-peel lead-source excavation evidence for one legal first park."""

    if not isinstance(action, tuple) or len(action) != 3:
        return LeadSourceExcavationEvidence(
            action, False, LeadSourceExcavationReject.NOT_LEGAL
        )
    src, dst, k = action
    if not state.can_move(src, dst, k):
        return LeadSourceExcavationEvidence(
            action, False, LeadSourceExcavationReject.NOT_LEGAL
        )
    lifecycle = assess_tableau_move(state, action, discover_exit=False)
    if lifecycle.placement_class != PlacementClass.MIXED_SUIT_PARK:
        return LeadSourceExcavationEvidence(
            action, False, LeadSourceExcavationReject.NOT_MIXED_PARK
        )
    if lifecycle.same_suit_joins_broken:
        return LeadSourceExcavationEvidence(
            action, False, LeadSourceExcavationReject.JOIN_BROKEN
        )
    uncover = assess_receiver_uncover(state, action)
    if uncover.qualified:
        return LeadSourceExcavationEvidence(
            action, False, LeadSourceExcavationReject.UNCOVER_ALREADY_QUALIFIES
        )
    remaining_up = len(state.columns[src].face_up) - k
    if remaining_up <= 0:
        return LeadSourceExcavationEvidence(
            action, False, LeadSourceExcavationReject.NO_SECOND_PEEL
        )
    lead_info = _lead_missing_ranks(state)
    if lead_info is None:
        return LeadSourceExcavationEvidence(
            action, False, LeadSourceExcavationReject.NO_CURRENT_LEAD
        )
    lead_suit, missing_ranks = lead_info
    pre_key = _lead_ordering_key(state)
    after1 = _apply(state, action)

    best: Optional[Tuple] = None
    best_payload = None
    saw_second = False
    saw_receiver = False
    saw_consume = False
    saw_source = False
    for action2 in after1.enumerate_moves():
        if action2[0] != src:
            continue
        life2 = assess_tableau_move(after1, action2, discover_exit=False)
        if life2.placement_class != PlacementClass.MIXED_SUIT_PARK:
            continue
        if life2.same_suit_joins_broken:
            continue
        saw_second = True
        after2 = _apply(after1, action2)
        receiver = after2.columns[src].top()
        if receiver is None:
            continue
        saw_receiver = True
        for other in range(10):
            if other == src:
                continue
            run_len = _movable_run_length(after2, other)
            if run_len <= 0:
                continue
            for k3 in range(1, run_len + 1):
                head = after2.columns[other].face_up[-k3]
                if receiver.suit != head.suit or receiver.rank - 1 != head.rank:
                    continue
                if not after2.can_move(other, src, k3):
                    continue
                consume = (other, src, k3)
                saw_consume = True
                after3 = _apply(after2, consume)
                exposed = after3.columns[other].top()
                before_top = after2.columns[other].top()
                if (
                    exposed is None
                    or exposed == before_top
                    or exposed.suit != lead_suit
                    or exposed.rank not in missing_ranks
                ):
                    continue
                saw_source = True
                consume_key = _lead_ordering_key(after3)
                canonical_non_worse = bool(
                    pre_key is not None
                    and consume_key is not None
                    and consume_key <= pre_key
                )
                candidate = (
                    0 if canonical_non_worse else 1,
                    -k3,
                    action2,
                    consume,
                )
                payload = (
                    action2,
                    consume,
                    receiver,
                    head,
                    exposed,
                    pre_key,
                    consume_key,
                    canonical_non_worse,
                )
                if best is None or candidate < best:
                    best = candidate
                    best_payload = payload
    if best_payload is not None:
        (
            action2,
            consume,
            receiver,
            head,
            exposed,
            pre_key,
            consume_key,
            canonical_non_worse,
        ) = best_payload
        return LeadSourceExcavationEvidence(
            action,
            True,
            second_park=action2,
            consume=consume,
            receiver=receiver,
            consume_head=head,
            exposed_source=exposed,
            pre_key=pre_key,
            consume_key=consume_key,
            canonical_non_worse=canonical_non_worse,
        )
    if saw_consume:
        reject = LeadSourceExcavationReject.NO_LEAD_SOURCE_EXPOSED
    elif saw_receiver:
        reject = LeadSourceExcavationReject.NO_SAME_SUIT_CONSUME
    elif saw_second:
        reject = LeadSourceExcavationReject.NO_RECEIVER_AFTER_SECOND_PEEL
    else:
        reject = LeadSourceExcavationReject.NO_SECOND_PEEL
    return LeadSourceExcavationEvidence(action, False, reject, pre_key=pre_key)
