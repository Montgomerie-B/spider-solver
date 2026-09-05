"""v0.1 resource-aware excavation planner — genericity gate.

Fixtures live here.  The planner module must not contain position constants.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner.resource_excavation_planner import (
    CampaignTarget,
    ObligationState,
    OperatorKind,
    ReceiverReservation,
    ResourcePlanResult,
    WorkspaceObligation,
    apply_operator,
    canonical_outstanding_obligations,
    empty_obligations,
    is_reserved_receiver_misuse,
    local_transposition_key,
    plan_resource_excavation,
)
from spider.state_identity import canonical_state_key


ROOT = Path(__file__).resolve().parents[1]
PLANNER = ROOT / "src" / "spider" / "planner" / "resource_excavation_planner.py"
CONTROLLER = ROOT / "src" / "spider" / "planner" / "anytime_controller.py"


def _card(suit: str, rank: int) -> Card:
    return Card(suit, rank)


def _columns(slots: dict[int, list[Card]]) -> list[Column]:
    cols = []
    for index in range(10):
        cards = slots.get(index)
        if cards is None:
            # Distinct non-interacting fillers: kings cannot move except to empty.
            cols.append(Column([], [_card("shdc"[index % 4], 13)]))
        else:
            cols.append(Column([], list(cards)))
    return cols


def resource_shape(
    *,
    suit: str,
    high: int,
    low: int,
    peel_b_suit: str,
    peel_a_suit: str,
    peel_dest_suit: str,
    thief_suit: str,
    create_src_suit: str,
    create_src_rank: int,
    create_dst_suit: str,
    create_dst_rank: int,
    create_src_col: int,
    create_dst_col: int,
    receiver_col: int,
    stack_col: int,
    peel_dest_col: int,
    thief_col: int,
) -> tuple[SpiderState, CampaignTarget]:
    """Same obligation shape, caller-chosen suits/ranks/columns."""

    cover_rank = low - 1
    peel_b_rank = cover_rank - 1
    peel_a_rank = peel_b_rank - 1
    slots = {
        create_src_col: [_card(create_src_suit, create_src_rank)],
        create_dst_col: [_card(create_dst_suit, create_dst_rank)],
        receiver_col: [_card(suit, high)],
        stack_col: [
            _card(suit, low),
            _card(suit, cover_rank),
            _card(peel_b_suit, peel_b_rank),
            _card(peel_a_suit, peel_a_rank),
        ],
        peel_dest_col: [_card(peel_dest_suit, cover_rank)],
        thief_col: [_card(thief_suit, low)],
    }
    return SpiderState(_columns(slots), []), CampaignTarget(suit, high, low)


def p1_fixture() -> tuple[SpiderState, CampaignTarget]:
    """Studied resource shape (workspace + reserve + prepay + one rework)."""

    return resource_shape(
        suit="s",
        high=6,
        low=5,
        peel_b_suit="d",
        peel_a_suit="c",
        peel_dest_suit="h",
        thief_suit="h",
        create_src_suit="c",
        create_src_rank=7,
        create_dst_suit="h",
        create_dst_rank=8,
        create_src_col=0,
        create_dst_col=1,
        receiver_col=2,
        stack_col=3,
        peel_dest_col=4,
        thief_col=5,
    )


def p2_fixture() -> tuple[SpiderState, CampaignTarget]:
    return resource_shape(
        suit="h",
        high=10,
        low=9,
        peel_b_suit="c",
        peel_a_suit="s",
        peel_dest_suit="d",
        thief_suit="c",
        create_src_suit="d",
        create_src_rank=3,
        create_dst_suit="s",
        create_dst_rank=4,
        create_src_col=7,
        create_dst_col=1,
        receiver_col=9,
        stack_col=0,
        peel_dest_col=4,
        thief_col=2,
    )


def p3_fixture() -> tuple[SpiderState, CampaignTarget]:
    return resource_shape(
        suit="d",
        high=8,
        low=7,
        peel_b_suit="s",
        peel_a_suit="h",
        peel_dest_suit="c",
        thief_suit="s",
        create_src_suit="h",
        create_src_rank=2,
        create_dst_suit="c",
        create_dst_rank=3,
        create_src_col=4,
        create_dst_col=8,
        receiver_col=6,
        stack_col=9,
        peel_dest_col=3,
        thief_col=1,
    )


def _assert_realised(plan, start, target):
    assert plan.result == ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS
    assert plan.replay_ok
    assert plan.proof_pruning_allowed is False
    assert plan.actions
    assert OperatorKind.REALISE_CAMPAIGN_EDGE in plan.operators
    end = start.clone()
    paid = replay_actions(end, list(plan.actions))
    assert paid == plan.cost
    assert plan.edge_after > plan.edge_before
    joined = False
    for col in end.columns:
        up = col.face_up
        for a, b in zip(up, up[1:]):
            if (
                a.suit == target.suit
                and b.suit == target.suit
                and a.rank == target.high_rank
                and b.rank == target.low_rank
            ):
                joined = True
    assert joined


def test_p1_studied_shape_realises_campaign_edge():
    state, target = p1_fixture()
    plan = plan_resource_excavation(state, target)
    _assert_realised(plan, state, target)


def test_p2_synthetic_analogue_realises_campaign_edge():
    state, target = p2_fixture()
    plan = plan_resource_excavation(state, target)
    _assert_realised(plan, state, target)


def test_p3_second_analogue_realises_campaign_edge():
    state, target = p3_fixture()
    plan = plan_resource_excavation(state, target)
    _assert_realised(plan, state, target)


def test_positive_fixtures_are_structurally_distinct():
    s1, t1 = p1_fixture()
    s2, t2 = p2_fixture()
    s3, t3 = p3_fixture()
    assert canonical_state_key(s1) != canonical_state_key(s2)
    assert canonical_state_key(s2) != canonical_state_key(s3)
    assert (t1.suit, t1.high_rank, t1.low_rank) != (t2.suit, t2.high_rank, t2.low_rank)
    assert (t2.suit, t2.high_rank, t2.low_rank) != (t3.suit, t3.high_rank, t3.low_rank)


def test_n1_reserved_receiver_misuse_rejected():
    state, target = p1_fixture()
    reserved_col = 2
    thief_col = 5
    obl = ObligationState(
        reservation=ReceiverReservation(
            reserved_col, target.suit, target.high_rank, target.suit, target.low_rank
        )
    )
    action = (thief_col, reserved_col, 1)
    assert state.can_move(*action)
    assert is_reserved_receiver_misuse(state, obl, action)
    assert apply_operator(
        state, target, OperatorKind.REALISE_CAMPAIGN_EDGE, obligations=obl, candidate=action
    ) is None
    plan = plan_resource_excavation(state, target)
    cur = state.clone()
    for _kind, acts in plan.operator_trace:
        for act in acts:
            if act != action:
                continue
            dest_top = cur.columns[reserved_col].top()
            src_top = cur.columns[thief_col].top()
            thief_on_reserved = (
                dest_top is not None
                and dest_top.suit == target.suit
                and dest_top.rank == target.high_rank
                and src_top is not None
                and not (
                    src_top.suit == target.suit and src_top.rank == target.low_rank
                )
            )
            assert not thief_on_reserved
        if acts:
            replay_actions(cur, list(acts))


def test_n2_break_without_destination_rejected():
    slots = {
        0: [_card("s", 5), _card("s", 4)],
        1: [_card("h", 13)],
        2: [_card("d", 13)],
        3: [_card("c", 13)],
        4: [_card("s", 13)],
        5: [_card("h", 12)],
        6: [_card("d", 12)],
        7: [_card("c", 12)],
        8: [_card("s", 12)],
        9: [_card("h", 11)],
    }
    state = SpiderState([Column([], list(cards)) for cards in (slots[i] for i in range(10))], [])
    target = CampaignTarget("s", 5, 4)
    assert apply_operator(state, target, OperatorKind.TEMPORARY_REWORK) is None
    plan = plan_resource_excavation(state, target)
    assert plan.result in (
        ResourcePlanResult.NO_BOUNDED_PLAN,
        ResourcePlanResult.RESOURCE_DEADLOCK,
    )
    assert OperatorKind.TEMPORARY_REWORK not in plan.operators


def test_n3_token_receiver_mutual_exclusion():
    slots = {
        0: [_card("h", 4)],
        1: [_card("s", 5)],
        2: [_card("s", 4), _card("c", 13)],
        3: [_card("d", 13)],
        4: [_card("h", 13)],
        5: [_card("s", 13)],
        6: [_card("c", 12)],
        7: [_card("d", 12)],
        8: [_card("h", 12)],
        9: [_card("s", 12)],
    }
    state = SpiderState([Column([], list(slots[i])) for i in range(10)], [])
    target = CampaignTarget("s", 5, 4)
    obl = ObligationState(
        reservation=ReceiverReservation(1, "s", 5, "s", 4),
        workspace=WorkspaceObligation(0, "h", 4, 5),
    )
    plan = plan_resource_excavation(state, target, obligations=obl)
    assert plan.result in (
        ResourcePlanResult.NO_BOUNDED_PLAN,
        ResourcePlanResult.RESOURCE_DEADLOCK,
    )
    end = state.clone()
    if plan.actions:
        replay_actions(end, list(plan.actions))
    empties = sum(1 for col in end.columns if col.is_empty())
    assert empties <= sum(1 for col in state.columns if col.is_empty())


def test_n4_bad_rework_recovery_rejected():
    slots = {
        0: [_card("h", 4)],
        1: [_card("s", 5)],
        2: [_card("s", 4), _card("c", 13)],
        3: [_card("d", 13)],
        4: [_card("h", 13)],
        5: [_card("s", 13)],
        6: [_card("c", 12)],
        7: [_card("d", 12)],
        8: [_card("h", 12)],
        9: [_card("s", 12)],
    }
    state = SpiderState([Column([], list(slots[i])) for i in range(10)], [])
    target = CampaignTarget("s", 5, 4)
    obl = ObligationState(
        reservation=ReceiverReservation(1, "s", 5, "s", 4),
        workspace=WorkspaceObligation(0, "h", 4, 5),
    )
    recover = apply_operator(state, target, OperatorKind.RECOVER_WORKSPACE, obligations=obl)
    assert recover is None
    misuse = (0, 1, 1)
    assert state.can_move(*misuse)
    assert is_reserved_receiver_misuse(state, obl, misuse)


def test_n5_local_identity_distinguishes_only_live_obligations():
    state, target = p1_fixture()
    none = empty_obligations()
    reserved = ObligationState(
        reservation=ReceiverReservation(2, target.suit, target.high_rank, target.suit, target.low_rank)
    )
    key_none_a = local_transposition_key(state, none)
    key_none_b = local_transposition_key(state.clone(), empty_obligations())
    key_reserved = local_transposition_key(state, reserved)
    assert key_none_a == key_none_b
    assert key_none_a != key_reserved
    assert key_none_a[0] == canonical_state_key(state) == key_reserved[0]
    assert canonical_outstanding_obligations(state, none) == ()
    assert canonical_outstanding_obligations(state, reserved) != ()


def test_replay_of_positive_plans():
    for factory in (p1_fixture, p2_fixture, p3_fixture):
        state, target = factory()
        plan = plan_resource_excavation(state, target)
        end = state.clone()
        replay_actions(end, list(plan.actions))
        assert canonical_state_key(end) != canonical_state_key(state) or plan.operators == (
            OperatorKind.RESERVE_RECEIVER,
        )


def test_planner_not_imported_by_controller():
    source = CONTROLLER.read_text(encoding="utf-8")
    assert "resource_excavation_planner" not in source


def test_planner_has_no_benchmark_or_fixture_constants():
    source = PLANNER.read_text(encoding="utf-8")
    assert "4925153" not in source
    for banned in (
        "9s",
        "Ts",
        "5s",
        "4s",
        "8d",
        "c8",
        "column 8",
        "p1_fixture",
        "228061476b70f3c1",
    ):
        assert banned not in source
    assert "proof_pruning_allowed: bool = False" in source


def test_proof_and_global_tt_semantics_untouched():
    import spider.planner.resource_excavation_planner as module

    state, target = p1_fixture()
    before = canonical_state_key(state)
    plan_resource_excavation(state, target)
    assert canonical_state_key(state) == before
    source = inspect.getsource(module)
    assert "StrategicTranspositionTable" not in source
    assert "proof_pruning_allowed=True" not in source


def test_does_not_import_anytime_controller():
    source = PLANNER.read_text(encoding="utf-8")
    assert "import anytime_controller" not in source
    assert "from spider.planner.anytime_controller" not in source
    assert "from spider.planner.bounded_excavation_planner" not in source
    assert "import bounded_excavation_planner" not in source
