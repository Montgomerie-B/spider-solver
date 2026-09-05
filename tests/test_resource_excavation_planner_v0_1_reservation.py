"""v0.1 receiver-reservation positive gate.

Reservation must be necessary, physical, and cleared on rightful consume.
Planner code must not grow fixture constants.
"""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner.resource_excavation_planner import (
    CampaignTarget,
    OperatorKind,
    ResourcePlanResult,
    apply_operator,
    canonical_outstanding_obligations,
    empty_obligations,
    is_reserved_receiver_misuse,
    local_transposition_key,
    plan_resource_excavation,
    receiver_threat_action,
    unique_usable_receiver_column,
)
from spider.state_identity import canonical_state_key


ROOT = Path(__file__).resolve().parents[1]
PLANNER = ROOT / "src" / "spider" / "planner" / "resource_excavation_planner.py"
CONTROLLER = ROOT / "src" / "spider" / "planner" / "anytime_controller.py"


def _card(suit: str, rank: int) -> Card:
    return Card(suit, rank)


def _filled(slots: dict[int, list[Card]]) -> SpiderState:
    cols = []
    for index in range(10):
        cards = slots.get(index)
        if cards is None:
            cols.append(Column([], [_card("shdc"[index % 4], 13)]))
        else:
            cols.append(Column([], list(cards)))
    return SpiderState(cols, [])


def _digest(state: SpiderState) -> str:
    return hashlib.sha256(repr(canonical_state_key(state)).encode()).hexdigest()[:16]


def reservation_positive_fixture() -> tuple[SpiderState, CampaignTarget]:
    """Unique hearts-9 receiver; 8h buried under a two-mixed PREPAY stack.

    8c can legally occupy 9h (workspace CREATE). 6d→7c creates workspace
    without consuming the receiver. No same-suit join to break.
    """

    target = CampaignTarget("h", 9, 8)
    state = _filled(
        {
            0: [_card("d", 6)],
            1: [_card("h", 9)],
            2: [_card("c", 7)],
            3: [_card("c", 8)],
            4: [_card("c", 4)],
            6: [_card("h", 8), _card("s", 3), _card("d", 2)],
        }
    )
    return state, target


def reservation_unthreatened_fixture() -> tuple[SpiderState, CampaignTarget]:
    """Same campaign shape with the thief removed."""

    target = CampaignTarget("h", 9, 8)
    state = _filled(
        {
            0: [_card("d", 6)],
            1: [_card("h", 9)],
            2: [_card("c", 7)],
            4: [_card("c", 4)],
            6: [_card("h", 8), _card("s", 3), _card("d", 2)],
        }
    )
    return state, target


def _walk(state: SpiderState, target: CampaignTarget, trace):
    cur = state.clone()
    obl = empty_obligations()
    yield None, cur.clone(), obl
    for kind, acts in trace:
        step = apply_operator(
            cur,
            target,
            kind,
            obligations=obl,
            candidate=acts[0] if acts else None,
        )
        assert step is not None, (kind, acts)
        assert step.actions == acts
        cur = step.state
        obl = step.obligations
        yield kind, cur.clone(), obl


def _join_present(state: SpiderState, suit: str, high: int, low: int) -> bool:
    for col in state.columns:
        up = col.face_up
        for a, b in zip(up, up[1:]):
            if a.suit == suit and b.suit == suit and a.rank == high and b.rank == low:
                return True
    return False


def test_thief_move_is_engine_legal_and_useful():
    state, target = reservation_positive_fixture()
    receiver = unique_usable_receiver_column(state, target)
    thief = receiver_threat_action(state, target)
    assert receiver is not None
    assert thief is not None
    src, dst, k = thief
    assert dst == receiver
    assert state.can_move(src, dst, k)
    head = state.columns[src].face_up[-k]
    assert not (head.suit == target.suit and head.rank == target.low_rank)
    empties_before = sum(col.is_empty() for col in state.columns)
    post = state.clone()
    post.move(src, dst, k)
    empties_after = sum(col.is_empty() for col in post.columns)
    assert empties_after > empties_before
    top = post.columns[receiver].top()
    assert top is not None
    assert not (top.suit == target.suit and top.rank == target.low_rank)
    assert _digest(state) != _digest(post)


def test_thief_first_counterfactual_loses_the_plan():
    state, target = reservation_positive_fixture()
    thief = receiver_threat_action(state, target)
    stolen = state.clone()
    stolen.move(*thief)
    receiver = unique_usable_receiver_column(state, target)
    occ = stolen.columns[thief[1]].top()
    assert occ is not None and occ.suit != target.suit
    assert unique_usable_receiver_column(stolen, target) is None
    plan = plan_resource_excavation(stolen, target)
    assert plan.result in (
        ResourcePlanResult.NO_BOUNDED_PLAN,
        ResourcePlanResult.RESOURCE_DEADLOCK,
    )
    assert OperatorKind.REALISE_CAMPAIGN_EDGE not in plan.operators


def test_positive_plan_reserves_before_any_consume():
    state, target = reservation_positive_fixture()
    plan = plan_resource_excavation(state, target)
    assert plan.result == ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS
    assert plan.replay_ok
    assert plan.proof_pruning_allowed is False
    kinds = list(plan.operators)
    assert OperatorKind.RESERVE_RECEIVER in kinds
    assert OperatorKind.TEMPORARY_REWORK not in kinds
    reserve_at = kinds.index(OperatorKind.RESERVE_RECEIVER)
    realise_at = kinds.index(OperatorKind.REALISE_CAMPAIGN_EDGE)
    assert reserve_at < realise_at
    thief = receiver_threat_action(state, target)
    for kind, acts in plan.operator_trace[:reserve_at]:
        assert thief not in acts and acts[:1] != (thief,)
    receiver = unique_usable_receiver_column(state, target)
    reserved = None
    for kind, cur, obl in _walk(state, target, plan.operator_trace):
        if kind == OperatorKind.RESERVE_RECEIVER:
            reserved = obl.reservation
            assert reserved is not None
            assert reserved.column == receiver
            assert reserved.suit == target.suit
            assert reserved.rank == target.high_rank
            assert reserved.consumer_suit == target.suit
            assert reserved.consumer_rank == target.low_rank
            break
    assert reserved is not None
    end = state.clone()
    replay_actions(end, list(plan.actions))
    assert _join_present(end, target.suit, target.high_rank, target.low_rank)


def test_post_reservation_thief_is_resource_inadmissible():
    state, target = reservation_positive_fixture()
    reserved_step = apply_operator(state, target, OperatorKind.RESERVE_RECEIVER)
    assert reserved_step is not None
    obl = reserved_step.obligations
    thief = receiver_threat_action(state, target)
    before = canonical_state_key(state)
    assert state.can_move(*thief)
    assert is_reserved_receiver_misuse(state, obl, thief)
    assert (
        apply_operator(
            state,
            target,
            OperatorKind.CREATE_WORKSPACE,
            obligations=obl,
            candidate=thief,
        )
        is None
    )
    assert canonical_state_key(state) == before
    assert obl.reservation is not None
    plan = plan_resource_excavation(state, target)
    assert thief not in plan.actions


def test_rightful_consumer_uses_reserved_copy_and_clears():
    state, target = reservation_positive_fixture()
    plan = plan_resource_excavation(state, target)
    saw_reserve = False
    realised = False
    for kind, cur, obl in _walk(state, target, plan.operator_trace):
        if kind == OperatorKind.RESERVE_RECEIVER:
            saw_reserve = True
            assert obl.reservation is not None
        if kind == OperatorKind.REALISE_CAMPAIGN_EDGE:
            assert saw_reserve
            assert _join_present(cur, target.suit, target.high_rank, target.low_rank)
            acts = next(
                a for k, a in plan.operator_trace if k == OperatorKind.REALISE_CAMPAIGN_EDGE
            )
            assert acts
            _src, dst, _k = acts[0]
            # After consume the reservation is cleared: top is the consumer.
            assert obl.reservation is None
            realised = True
            assert plan.proof_pruning_allowed is False
    assert realised
    end = state.clone()
    replay_actions(end, list(plan.actions))
    assert canonical_outstanding_obligations(end, empty_obligations()) == ()


def test_local_identity_lifecycle_for_reservation():
    state, target = reservation_positive_fixture()
    none = empty_obligations()
    reserved_step = apply_operator(state, target, OperatorKind.RESERVE_RECEIVER)
    assert reserved_step is not None
    reserved_obl = reserved_step.obligations
    key_none = local_transposition_key(state, none)
    key_res = local_transposition_key(state, reserved_obl)
    assert key_none[0] == key_res[0] == canonical_state_key(state)
    assert key_none != key_res
    plan = plan_resource_excavation(state, target)
    for kind, cur, obl in _walk(state, target, plan.operator_trace):
        if kind == OperatorKind.REALISE_CAMPAIGN_EDGE:
            assert obl.reservation is None
            assert canonical_outstanding_obligations(cur, obl) == ()
            assert local_transposition_key(cur, obl)[0] == canonical_state_key(cur)


def test_no_gratuitous_reservation_without_thief():
    state, target = reservation_unthreatened_fixture()
    assert receiver_threat_action(state, target) is None
    assert unique_usable_receiver_column(state, target) is not None
    plan = plan_resource_excavation(state, target)
    assert plan.result == ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS
    assert OperatorKind.RESERVE_RECEIVER not in plan.operators
    assert OperatorKind.TEMPORARY_REWORK not in plan.operators


def test_no_alternate_usable_receiver_copy():
    state, target = reservation_positive_fixture()
    tops = [
        i
        for i, col in enumerate(state.columns)
        if col.top() is not None
        and col.top().suit == target.suit
        and col.top().rank == target.high_rank
    ]
    assert tops == [unique_usable_receiver_column(state, target)]
    buried = []
    for i, col in enumerate(state.columns):
        for card in list(col.face_down) + list(col.face_up[:-1] if col.face_up else []):
            if card.suit == target.suit and card.rank == target.high_rank:
                buried.append(i)
    assert buried == []


def test_replay_and_proof_untouched():
    state, target = reservation_positive_fixture()
    before = canonical_state_key(state)
    plan = plan_resource_excavation(state, target)
    assert canonical_state_key(state) == before
    end = state.clone()
    assert replay_actions(end, list(plan.actions)) == plan.cost
    assert plan.replay_ok
    assert plan.proof_pruning_allowed is False
    source = PLANNER.read_text(encoding="utf-8")
    assert "StrategicTranspositionTable" not in source
    assert "from spider.planner.anytime_controller" not in source
    assert "resource_excavation_planner" not in CONTROLLER.read_text(encoding="utf-8")
    assert "proof_pruning_allowed=True" not in inspect.getsource(
        plan_resource_excavation
    )
    assert "4925153" not in source
    for banned in ("reservation_positive_fixture", "9h", "8c", "8h"):
        assert banned not in source
