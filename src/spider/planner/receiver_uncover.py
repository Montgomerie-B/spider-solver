"""One-ply same-suit receiver-uncover evidence.

This is not generic two-ply search.  A candidate first move is inspected, the
newly exposed source-column top is read, and only already-exposed movable runs
in other columns are tested as exact immediate consumers of that top.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.move_lifecycle import PlacementClass, assess_tableau_move
from spider.planner.whole_deal_scheduler import (
    SUITS,
    _stable_fragments,
    build_whole_deal_blueprint,
    rebuild_whole_deal_schedule,
)
from spider.rules import MW_RULES


TableauMove = Tuple[int, int, int]


class ReceiverUncoverReject(str, Enum):
    NOT_LEGAL = "not_legal"
    NOT_MIXED_PARK = "not_mixed_park"
    JOIN_BROKEN = "join_broken"
    NO_EXPOSED_RECEIVER = "no_exposed_receiver"
    NO_SAME_SUIT_FOLLOWUP = "no_same_suit_followup"
    NO_FRAGMENT_REDUCTION = "no_fragment_reduction"
    CANONICAL_WORSE = "canonical_worse"


@dataclass(frozen=True)
class ReceiverUncoverEvidence:
    action: TableauMove
    qualified: bool
    reject: Optional[ReceiverUncoverReject] = None
    followup: Optional[TableauMove] = None
    receiver: Optional[Card] = None
    followup_head: Optional[Card] = None
    fragment_reduction: int = 0
    pre_key: Optional[Tuple] = None
    followup_key: Optional[Tuple] = None
    proof_pruning_allowed: bool = False


def _movable_run_length(state: SpiderState, column: int) -> int:
    up = state.columns[column].face_up
    if not up:
        return 0
    length = 1
    for lower, upper in zip(reversed(up[:-1]), reversed(up[1:])):
        if lower.suit == upper.suit and lower.rank - 1 == upper.rank:
            length += 1
        else:
            break
    return length


def _fragment_count(state: SpiderState) -> int:
    return sum(len(_stable_fragments(state, suit)) for suit in SUITS)


def _lead_ordering_key(state: SpiderState) -> Optional[Tuple]:
    schedule = rebuild_whole_deal_schedule(state, build_whole_deal_blueprint(state))
    if schedule.lane_sequence_priority is None or schedule.lane_sequence_priority.lead is None:
        return None
    return schedule.lane_sequence_priority.lead.ordering_key()


def assess_receiver_uncover(
    state: SpiderState,
    action: TableauMove,
) -> ReceiverUncoverEvidence:
    """Return one-ply receiver-uncover evidence for a single legal first move."""

    if not isinstance(action, tuple) or len(action) != 3:
        return ReceiverUncoverEvidence(action, False, ReceiverUncoverReject.NOT_LEGAL)
    src, dst, k = action
    if not state.can_move(src, dst, k):
        return ReceiverUncoverEvidence(action, False, ReceiverUncoverReject.NOT_LEGAL)
    lifecycle = assess_tableau_move(state, action)
    if lifecycle.placement_class != PlacementClass.MIXED_SUIT_PARK:
        return ReceiverUncoverEvidence(action, False, ReceiverUncoverReject.NOT_MIXED_PARK)
    if lifecycle.same_suit_joins_broken:
        return ReceiverUncoverEvidence(action, False, ReceiverUncoverReject.JOIN_BROKEN)
    before_top = state.columns[src].top()
    remaining_up = len(state.columns[src].face_up) - k
    if remaining_up <= 0 and not state.columns[src].face_down:
        return ReceiverUncoverEvidence(action, False, ReceiverUncoverReject.NO_EXPOSED_RECEIVER)
    post = state.clone()
    post.move(src, dst, k, rules=MW_RULES)
    receiver = post.columns[src].top()
    if receiver is None or receiver == before_top:
        return ReceiverUncoverEvidence(action, False, ReceiverUncoverReject.NO_EXPOSED_RECEIVER)
    follow_ups = []
    for other in range(10):
        if other == src:
            continue
        run_len = _movable_run_length(post, other)
        if run_len <= 0:
            continue
        for k2 in range(1, run_len + 1):
            head = post.columns[other].face_up[-k2]
            if not post.can_move(other, src, k2):
                continue
            if receiver.suit != head.suit or receiver.rank - 1 != head.rank:
                continue
            follow_ups.append(((other, src, k2), head, k2))
    if not follow_ups:
        return ReceiverUncoverEvidence(
            action, False, ReceiverUncoverReject.NO_SAME_SUIT_FOLLOWUP, receiver=receiver
        )
    followup, head, _k2 = max(follow_ups, key=lambda item: (item[2], -item[0][0]))
    after = post.clone()
    after.move(*followup, rules=MW_RULES)
    reduction = _fragment_count(state) - _fragment_count(after)
    if reduction < 1:
        return ReceiverUncoverEvidence(
            action,
            False,
            ReceiverUncoverReject.NO_FRAGMENT_REDUCTION,
            followup=followup,
            receiver=receiver,
            followup_head=head,
            fragment_reduction=reduction,
        )
    pre_key = _lead_ordering_key(state)
    followup_key = _lead_ordering_key(after)
    if pre_key is None or followup_key is None or followup_key > pre_key:
        return ReceiverUncoverEvidence(
            action,
            False,
            ReceiverUncoverReject.CANONICAL_WORSE,
            followup=followup,
            receiver=receiver,
            followup_head=head,
            fragment_reduction=reduction,
            pre_key=pre_key,
            followup_key=followup_key,
        )
    return ReceiverUncoverEvidence(
        action,
        True,
        followup=followup,
        receiver=receiver,
        followup_head=head,
        fragment_reduction=reduction,
        pre_key=pre_key,
        followup_key=followup_key,
    )
