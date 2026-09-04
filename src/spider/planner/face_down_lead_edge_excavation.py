"""Scheduler v0.8 bounded face-down lead-edge excavation.

Recognise only the exact stock-empty two-park + consume pattern:

* a current whole-deal schedule lane has an unresolved missing-edge rank
  whose useful (minimum-depth) physical copy is face-down;
* that column currently has exactly two face-up blockers above the next
  face-down card X;
* both blockers peel sequentially as MIXED_SUIT_PARK moves (k=1, no empty
  destination, no stable join broken);
* the second park flips X;
* X has an exact legal same-suit receiver and joining it is a stable
  same-suit consume that flips the required lead-edge rank underneath;
* the complete three-action suffix is replay-valid;
* the owning lane's ordering_key() after the complete suffix is non-worse.

This is not generic depth-3 search, not a mixed-park cap raise, not a
widening of lead-source excavation or receiver-uncover, and not a search
over arbitrary face-down cards.  Parks are never emitted independently.
Economics are evaluated only after the complete suffix, on the schedule
lane that owns the excavated missing edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.move_lifecycle import PlacementClass, assess_tableau_move
from spider.planner.receiver_uncover import _movable_run_length
from spider.planner.whole_deal_scheduler import (
    FoundationLaneMaturationState,
    build_whole_deal_blueprint,
    rebuild_whole_deal_schedule,
)
from spider.rules import MW_RULES


TableauMove = Tuple[int, int, int]
Macro = Tuple[TableauMove, TableauMove, TableauMove]


class FaceDownLeadEdgeExcavationReject(str, Enum):
    STOCK_NONEMPTY = "stock_nonempty"
    NO_CURRENT_LEAD = "no_current_lead"
    NO_MISSING_EDGE = "no_missing_edge"
    NO_TWO_BLOCKER_COLUMN = "no_two_blocker_column"
    MORE_THAN_TWO_FACE_UP_BLOCKERS = "more_than_two_face_up_blockers"
    PARK_JOIN_BROKEN = "park_join_broken"
    PARK_USES_EMPTY = "park_uses_empty"
    PARK_NOT_MIXED = "park_not_mixed"
    PARK_ILLEGAL = "park_illegal"
    SECOND_PARK_NO_FLIP = "second_park_no_flip"
    NO_SAME_SUIT_RECEIVER = "no_same_suit_receiver"
    CONSUME_NOT_STABLE_JOIN = "consume_not_stable_join"
    CONSUME_NOT_SAME_SUIT = "consume_not_same_suit"
    REQUIRED_RANK_NOT_REVEALED = "required_rank_not_revealed"
    REVEALED_UNRELATED_TO_LEAD = "revealed_unrelated_to_lead"
    CANONICAL_WORSE = "canonical_worse"
    ILLEGAL_INTERMEDIATE = "illegal_intermediate"
    ALREADY_COVERED = "already_covered"
    NOT_USEFUL_COPY = "not_useful_copy"


@dataclass(frozen=True)
class FaceDownLeadEdgeExcavationEvidence:
    qualified: bool
    reject: Optional[FaceDownLeadEdgeExcavationReject] = None
    actions: Optional[Macro] = None
    cost: int = 0
    required: Optional[Card] = None
    flipped: Optional[Card] = None
    receiver: Optional[Card] = None
    source_column: Optional[int] = None
    consume_column: Optional[int] = None
    lane_suit: Optional[str] = None
    lane_id: Optional[int] = None
    pre_key: Optional[Tuple] = None
    post_key: Optional[Tuple] = None
    pre_lead_key: Optional[Tuple] = None
    post_lead_key: Optional[Tuple] = None
    proof_pruning_allowed: bool = False


def _schedule(state: SpiderState):
    if state.stock:
        return None
    return rebuild_whole_deal_schedule(state, build_whole_deal_blueprint(state))


def _lead_key(schedule) -> Optional[Tuple]:
    if schedule is None or schedule.lane_sequence_priority is None:
        return None
    lead = schedule.lane_sequence_priority.lead
    if lead is None:
        return None
    return lead.ordering_key()


def _lane_key(schedule, suit: str, lane_id: int) -> Optional[Tuple]:
    if schedule is None or schedule.lane_sequence_priority is None:
        return None
    for item in schedule.lane_sequence_priority.ordered:
        if item.suit == suit and item.lane == lane_id:
            return item.ordering_key()
    return None


def _min_copy_depth(state: SpiderState, suit: str, rank: int) -> Optional[int]:
    best: Optional[int] = None
    for col in state.columns:
        fu_n = len(col.face_up)
        fd_n = len(col.face_down)
        for i, card in enumerate(col.face_down):
            if card.suit != suit or card.rank != rank:
                continue
            depth = fu_n + (fd_n - 1 - i)
            best = depth if best is None else min(best, depth)
        for i, card in enumerate(col.face_up):
            if card.suit != suit or card.rank != rank:
                continue
            depth = fu_n - 1 - i
            best = depth if best is None else min(best, depth)
    return best


def _needed_ranks(schedule) -> Dict[Tuple[str, int], Tuple[Tuple[str, int, Tuple], ...]]:
    """Map (suit, rank) to owning non-removed lanes and their pre-keys."""

    owned: Dict[Tuple[str, int], List[Tuple[str, int, Tuple]]] = {}
    if schedule is None or schedule.lane_sequence_priority is None:
        return {}
    for item in schedule.lane_sequence_priority.ordered:
        if item.state == FoundationLaneMaturationState.REMOVED:
            continue
        if not item.missing_edges:
            continue
        key = item.ordering_key()
        for high, low in item.missing_edges:
            for rank in (high, low):
                owned.setdefault((item.suit, rank), []).append((item.suit, item.lane, key))
    return {card: tuple(lanes) for card, lanes in owned.items()}


def _two_blocker_slots(
    state: SpiderState,
    needed: Dict[Tuple[str, int], Tuple[Tuple[str, int, Tuple], ...]],
) -> Tuple[Tuple[int, Card, Card, Tuple[Tuple[str, int, Tuple], ...]], ...]:
    """(column, X, required, owning_lanes) for the exact two-blocker pattern."""

    slots = []
    for ci, col in enumerate(state.columns):
        if len(col.face_up) != 2:
            continue
        if len(col.face_down) < 2:
            continue
        if _movable_run_length(state, ci) != 1:
            continue
        flipped = col.face_down[-1]
        required = col.face_down[-2]
        owners = needed.get((required.suit, required.rank))
        if not owners:
            continue
        depth = len(col.face_up) + 1
        useful = _min_copy_depth(state, required.suit, required.rank)
        if useful is None or depth != useful:
            continue
        slots.append((ci, flipped, required, owners))
    return tuple(slots)


def _park_ok(state: SpiderState, action: TableauMove) -> Optional[FaceDownLeadEdgeExcavationReject]:
    src, dst, k = action
    if not state.can_move(src, dst, k):
        return FaceDownLeadEdgeExcavationReject.PARK_ILLEGAL
    if state.columns[dst].is_empty():
        return FaceDownLeadEdgeExcavationReject.PARK_USES_EMPTY
    life = assess_tableau_move(state, action, discover_exit=False)
    if life.placement_class != PlacementClass.MIXED_SUIT_PARK:
        return FaceDownLeadEdgeExcavationReject.PARK_NOT_MIXED
    if life.same_suit_joins_broken:
        return FaceDownLeadEdgeExcavationReject.PARK_JOIN_BROKEN
    return None


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


def _same_suit_consume_destinations(
    state: SpiderState,
    column: int,
    card: Card,
) -> Tuple[Tuple[TableauMove, Card], ...]:
    dests = []
    for dst in range(10):
        if dst == column:
            continue
        if state.columns[dst].is_empty():
            continue
        top = state.columns[dst].top()
        if top is None or top.suit != card.suit or top.rank - 1 != card.rank:
            continue
        action = (column, dst, 1)
        if not state.can_move(*action):
            continue
        dests.append((action, top))
    return tuple(dests)


def _replay_macro(state: SpiderState, actions: Macro) -> Optional[Tuple[SpiderState, int]]:
    end = state.clone()
    try:
        cost = replay_actions(end, list(actions))
    except (ValueError, AssertionError, IndexError):
        return None
    return end, cost


def recognise_face_down_lead_edge_excavation(
    state: SpiderState,
) -> Tuple[FaceDownLeadEdgeExcavationEvidence, ...]:
    """Return every qualified two-park + consume macro, lex-smallest first."""

    if state.stock:
        return ()
    schedule = _schedule(state)
    if schedule is None or schedule.lane_sequence_priority is None:
        return ()
    if schedule.lane_sequence_priority.lead is None:
        return ()
    needed = _needed_ranks(schedule)
    if not needed:
        return ()
    pre_lead_key = _lead_key(schedule)
    slots = _two_blocker_slots(state, needed)
    found: List[FaceDownLeadEdgeExcavationEvidence] = []
    for source_col, flipped, required, owners in slots:
        peels1 = _mixed_peel_destinations(state, source_col)
        if not peels1:
            continue
        for park1 in peels1:
            mid = state.clone()
            mid.move(*park1, rules=MW_RULES)
            if len(mid.columns[source_col].face_up) != 1:
                continue
            if _movable_run_length(mid, source_col) != 1:
                continue
            peels2 = _mixed_peel_destinations(mid, source_col)
            for park2 in peels2:
                after2 = mid.clone()
                after2.move(*park2, rules=MW_RULES)
                if after2.columns[source_col].top() != flipped:
                    continue
                if len(after2.columns[source_col].face_down) != len(
                    state.columns[source_col].face_down
                ) - 1:
                    continue
                consumes = _same_suit_consume_destinations(after2, source_col, flipped)
                for consume, receiver in consumes:
                    life3 = assess_tableau_move(after2, consume, discover_exit=False)
                    if life3.placement_class != PlacementClass.STABLE_SAME_SUIT_JOIN:
                        continue
                    if life3.same_suit_joins_broken:
                        continue
                    if receiver.suit != flipped.suit or receiver.rank - 1 != flipped.rank:
                        continue
                    replayed = _replay_macro(state, (park1, park2, consume))
                    if replayed is None:
                        continue
                    end, cost = replayed
                    if cost != 3:
                        continue
                    exposed = end.columns[source_col].top()
                    if exposed != required:
                        continue
                    if (exposed.suit, exposed.rank) not in needed:
                        continue
                    if len(end.columns[source_col].face_down) != len(
                        state.columns[source_col].face_down
                    ) - 2:
                        continue
                    end_schedule = _schedule(end)
                    post_lead_key = _lead_key(end_schedule)
                    accepted = None
                    for lane_suit, lane_id, pre_key in owners:
                        post_key = _lane_key(end_schedule, lane_suit, lane_id)
                        if post_key is None or post_key > pre_key:
                            continue
                        accepted = (lane_suit, lane_id, pre_key, post_key)
                        break
                    if accepted is None:
                        continue
                    lane_suit, lane_id, pre_key, post_key = accepted
                    found.append(
                        FaceDownLeadEdgeExcavationEvidence(
                            True,
                            actions=(park1, park2, consume),
                            cost=cost,
                            required=required,
                            flipped=flipped,
                            receiver=receiver,
                            source_column=source_col,
                            consume_column=consume[1],
                            lane_suit=lane_suit,
                            lane_id=lane_id,
                            pre_key=pre_key,
                            post_key=post_key,
                            pre_lead_key=pre_lead_key,
                            post_lead_key=post_lead_key,
                        )
                    )
    unique = {}
    for item in found:
        unique[item.actions] = item
    return tuple(sorted(unique.values(), key=lambda item: item.actions))


def face_down_lead_edge_excavation_reject_reason(
    state: SpiderState,
) -> Optional[FaceDownLeadEdgeExcavationReject]:
    """Primary reason a state has no qualified macro.  Diagnostic only."""

    if state.stock:
        return FaceDownLeadEdgeExcavationReject.STOCK_NONEMPTY
    schedule = _schedule(state)
    if schedule is None or schedule.lane_sequence_priority is None:
        return FaceDownLeadEdgeExcavationReject.NO_CURRENT_LEAD
    if schedule.lane_sequence_priority.lead is None:
        return FaceDownLeadEdgeExcavationReject.NO_CURRENT_LEAD
    needed = _needed_ranks(schedule)
    if not needed:
        return FaceDownLeadEdgeExcavationReject.NO_MISSING_EDGE
    saw_three_up = False
    for col in state.columns:
        if len(col.face_up) > 2 and len(col.face_down) >= 2:
            required = col.face_down[-2] if len(col.face_down) >= 2 else None
            if required is not None and (required.suit, required.rank) in needed:
                saw_three_up = True
    slots = _two_blocker_slots(state, needed)
    if not slots:
        if saw_three_up:
            return FaceDownLeadEdgeExcavationReject.MORE_THAN_TWO_FACE_UP_BLOCKERS
        return FaceDownLeadEdgeExcavationReject.NO_TWO_BLOCKER_COLUMN
    saw_illegal = False
    saw_join_broken = False
    saw_empty = False
    saw_no_flip = False
    saw_no_receiver = False
    saw_not_revealed = False
    saw_unrelated = False
    saw_worse = False
    for source_col, flipped, required, owners in slots:
        peels1 = _mixed_peel_destinations(state, source_col)
        if not peels1:
            for dst in range(10):
                if dst == source_col:
                    continue
                action = (source_col, dst, 1)
                reason = _park_ok(state, action)
                if reason == FaceDownLeadEdgeExcavationReject.PARK_JOIN_BROKEN:
                    saw_join_broken = True
                elif reason == FaceDownLeadEdgeExcavationReject.PARK_USES_EMPTY:
                    saw_empty = True
                elif reason == FaceDownLeadEdgeExcavationReject.PARK_ILLEGAL:
                    saw_illegal = True
            continue
        for park1 in peels1:
            mid = state.clone()
            mid.move(*park1, rules=MW_RULES)
            peels2 = _mixed_peel_destinations(mid, source_col)
            if not peels2:
                saw_illegal = True
                continue
            for park2 in peels2:
                after2 = mid.clone()
                after2.move(*park2, rules=MW_RULES)
                if after2.columns[source_col].top() != flipped:
                    saw_no_flip = True
                    continue
                consumes = _same_suit_consume_destinations(after2, source_col, flipped)
                if not consumes:
                    saw_no_receiver = True
                    continue
                for consume, _receiver in consumes:
                    replayed = _replay_macro(state, (park1, park2, consume))
                    if replayed is None:
                        continue
                    end, _cost = replayed
                    exposed = end.columns[source_col].top()
                    if exposed != required:
                        saw_not_revealed = True
                        continue
                    if (exposed.suit, exposed.rank) not in needed:
                        saw_unrelated = True
                        continue
                    end_schedule = _schedule(end)
                    improved = False
                    for lane_suit, lane_id, pre_key in owners:
                        post_key = _lane_key(end_schedule, lane_suit, lane_id)
                        if post_key is not None and post_key <= pre_key:
                            improved = True
                            break
                    if not improved:
                        saw_worse = True
                        continue
                    return None
    if saw_worse:
        return FaceDownLeadEdgeExcavationReject.CANONICAL_WORSE
    if saw_unrelated:
        return FaceDownLeadEdgeExcavationReject.REVEALED_UNRELATED_TO_LEAD
    if saw_not_revealed:
        return FaceDownLeadEdgeExcavationReject.REQUIRED_RANK_NOT_REVEALED
    if saw_no_receiver:
        return FaceDownLeadEdgeExcavationReject.NO_SAME_SUIT_RECEIVER
    if saw_no_flip:
        return FaceDownLeadEdgeExcavationReject.SECOND_PARK_NO_FLIP
    if saw_join_broken:
        return FaceDownLeadEdgeExcavationReject.PARK_JOIN_BROKEN
    if saw_empty:
        return FaceDownLeadEdgeExcavationReject.PARK_USES_EMPTY
    if saw_illegal:
        return FaceDownLeadEdgeExcavationReject.PARK_ILLEGAL
    return FaceDownLeadEdgeExcavationReject.NO_TWO_BLOCKER_COLUMN
