from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.planner.anytime_controller import (
    StrategicActionKind,
    StrategicCreditLevel,
    StrategicSearchNode,
    StrategicSuccessor,
    StrategicTranspositionTable,
    _authorised_ids_for_child,
    _current_lead_ordering_key,
    _milestone_checkpoint_order,
    _NO_CURRENT_LEAD_ORDER,
    _node_priority,
    _with_authorised_epoch_transition,
    analyze_stage0_state,
)
from spider.planner.whole_deal_scheduler import (
    EpochSaturationAssessment,
    EpochSaturationStatus,
    EpochTransitionOpportunity,
    EpochTransitionRepresentativeStatus,
    FoundationLaneCashOutEstimate,
    FoundationLaneMaturationAssessment,
    FoundationLaneMaturationState,
    FoundationLaneProgressDelta,
    FoundationLaneProgressKind,
    FoundationLaneSequencePriority,
    SchedulerDealKind,
    WholeDealSchedule,
)
from spider.state_identity import canonical_state_key


ROOT = Path(__file__).resolve().parents[1]


def _state(*face_up) -> SpiderState:
    columns = [Column([], list(cards)) for cards in face_up]
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return SpiderState(columns, [])


def _cash(*, future: int, gap: int, blocker: int = 4) -> FoundationLaneCashOutEstimate:
    return FoundationLaneCashOutEstimate(
        future_gate_count=future,
        fragment_merge_count=1,
        actionable_bridge_count=1,
        actionable_merge_count=1,
        blocker_work=blocker,
        workspace_work=0,
        stable_break_debt=0,
        rehandling_debt=0,
        terminal_gap=gap,
        removal_workspace_payoff=0,
    )


def _lead(
    *,
    future: int,
    gap: int,
    state: FoundationLaneMaturationState = FoundationLaneMaturationState.MERGE_READY,
    fingerprint: str = "lead",
    blocker: int = 4,
    suit: str = "s",
) -> FoundationLaneMaturationAssessment:
    return FoundationLaneMaturationAssessment(
        suit,
        1,
        fingerprint,
        state,
        None,
        False,
        (),
        (),
        (),
        (),
        (),
        (),
        (),
        (),
        _cash(future=future, gap=gap, blocker=blocker),
        None,
        False,
        (),
    )


def _schedule(lead: FoundationLaneMaturationAssessment | None) -> WholeDealSchedule:
    priority = None
    if lead is not None:
        priority = FoundationLaneSequencePriority((lead,), lead, None, ())
    return WholeDealSchedule(
        "fixture",
        "fp",
        0,
        (),
        (),
        (),
        (),
        False,
        lane_sequence_priority=priority,
    )


def _successor(*, substantial: bool = False) -> StrategicSuccessor:
    state = _state([Card("s", 5)])
    delta = None
    mat_state = None
    if substantial:
        mat_state = FoundationLaneMaturationState.MERGE_READY
        delta = FoundationLaneProgressDelta(
            "s",
            "before",
            "after",
            FoundationLaneMaturationState.BRIDGE_READY,
            FoundationLaneMaturationState.MERGE_READY,
            (
                FoundationLaneProgressKind.FRAGMENT_COUNT_REDUCED,
                FoundationLaneProgressKind.BRIDGE_INTEGRATED,
            ),
            6,
            5,
            9,
            8,
            4,
            0,
        )
    return StrategicSuccessor(
        StrategicActionKind.ECONOMIC_PROJECT,
        "economic",
        "fixture",
        ((0, 1, 1),),
        1,
        state,
        StrategicCreditLevel.CLEAN,
        1,
        1,
        0,
        True,
        False,
        ("fixture",),
        maturation_state=mat_state,
        maturation_progress_delta=delta,
    )


def _node(
    *,
    node_id: int = 1,
    g: int = 1,
    actions=(),
    lead: FoundationLaneMaturationAssessment | None = None,
    incoming: StrategicSuccessor | None = None,
    authorised=(),
    opportunity: EpochTransitionOpportunity | None = None,
) -> StrategicSearchNode:
    state = _state([Card("s", 7), Card("s", 6)])
    return StrategicSearchNode(
        node_id,
        state,
        g,
        tuple(actions),
        None,
        incoming,
        1,
        StrategicCreditLevel.CLEAN,
        None,
        analyze_stage0_state(state, spent_cost=g, incumbent_cost=None),
        whole_deal_schedule=_schedule(lead),
        epoch_transition_opportunity=opportunity,
        authorised_epoch_transition_ids=tuple(authorised),
    )


def _saturation() -> EpochSaturationAssessment:
    return EpochSaturationAssessment(
        EpochSaturationStatus.DEAL_READY,
        0,
        (),
        None,
        0,
        0,
        0,
        0,
        0,
        0,
        "fixture",
    )


def _opportunity(
    opportunity_id: str,
    status: EpochTransitionRepresentativeStatus,
) -> EpochTransitionOpportunity:
    state = _state([Card("s", 5)])
    return EpochTransitionOpportunity(
        opportunity_id,
        canonical_state_key(state),
        "src",
        0,
        (),
        1,
        _saturation(),
        SchedulerDealKind.DEAL_NOW,
        0,
        0.0,
        0,
        (),
        status=status,
    )


def test_stale_incoming_maturation_cannot_outrank_better_current_lead():
    stale = _node(
        node_id=55,
        lead=_lead(future=5, gap=12, fingerprint="stale"),
        incoming=_successor(substantial=True),
    )
    better = _node(
        node_id=57,
        lead=_lead(future=1, gap=8, fingerprint="fresh"),
        incoming=_successor(substantial=False),
    )
    assert stale.incoming_edge.maturation_progress_delta.substantial
    assert _node_priority(better) < _node_priority(stale)


def test_future5_gap12_loses_to_future1_gap8():
    worse = _node(node_id=1, lead=_lead(future=5, gap=12, fingerprint="a"))
    better = _node(node_id=2, lead=_lead(future=1, gap=8, fingerprint="b"))
    assert _current_lead_ordering_key(better) < _current_lead_ordering_key(worse)
    assert _node_priority(better) < _node_priority(worse)


def test_current_merge_near_terminal_remain_strongly_ordered():
    fragment = _node(
        node_id=1,
        lead=_lead(future=0, gap=1, state=FoundationLaneMaturationState.FRAGMENT_BUILDING, fingerprint="f"),
    )
    merge = _node(
        node_id=2,
        lead=_lead(future=5, gap=12, state=FoundationLaneMaturationState.MERGE_READY, fingerprint="m"),
    )
    near = _node(
        node_id=3,
        lead=_lead(future=5, gap=12, state=FoundationLaneMaturationState.NEAR_TERMINAL, fingerprint="n"),
    )
    terminal = _node(
        node_id=4,
        lead=_lead(future=5, gap=12, state=FoundationLaneMaturationState.TERMINAL_READY, fingerprint="t"),
    )
    assert _node_priority(terminal) < _node_priority(near) < _node_priority(merge) < _node_priority(fragment)


def test_no_schedule_sentinel_is_deterministic():
    missing = _node(node_id=1, lead=None)
    also_missing = _node(node_id=2, lead=None)
    assert _current_lead_ordering_key(missing) == _NO_CURRENT_LEAD_ORDER
    assert _current_lead_ordering_key(also_missing) == _NO_CURRENT_LEAD_ORDER
    present = _node(node_id=3, lead=_lead(future=5, gap=12))
    assert _current_lead_ordering_key(present) < _NO_CURRENT_LEAD_ORDER
    assert _node_priority(present) < _node_priority(missing)


def test_reserved_or_spent_deal_contributes_exactly_one_unit():
    reserved = _opportunity("auth-1", EpochTransitionRepresentativeStatus.RESERVED)
    spent = _opportunity("auth-1", EpochTransitionRepresentativeStatus.SPENT)
    parent = _node(
        actions=(("deal",),),
        authorised=("auth-1",),
        opportunity=spent,
    )
    child = _node(
        node_id=2,
        actions=(("deal",), ((0, 1, 1),)),
        authorised=_authorised_ids_for_child(parent),
    )
    assert _milestone_checkpoint_order(parent)[0] == 0
    assert child.authorised_epoch_transition_ids == ("auth-1",)
    assert _milestone_checkpoint_order(child)[0] == 0
    added = _with_authorised_epoch_transition(("auth-1",), reserved)
    assert added == ("auth-1",)


def test_qualified_and_none_contribute_zero():
    qualified = _opportunity("q1", EpochTransitionRepresentativeStatus.QUALIFIED)
    empty = ()
    assert _with_authorised_epoch_transition(empty, qualified) == ()
    assert _with_authorised_epoch_transition(empty, None) == ()
    node = _node(actions=(("deal",),), opportunity=qualified)
    assert node.authorised_epoch_transition_ids == ()
    assert _milestone_checkpoint_order(node)[0] == 1


def test_nested_anonymous_deal_debt_remains():
    parent = _node(actions=(("deal",),), authorised=("auth-1",))
    nested = _node(
        node_id=2,
        actions=(("deal",), ("deal",)),
        authorised=_authorised_ids_for_child(parent),
    )
    assert _milestone_checkpoint_order(nested)[0] == 1


def test_preparation_required_raw_deal_remains_penalised():
    undealt = _node(node_id=1, actions=())
    raw = _node(node_id=2, actions=(("deal",),))
    assert _milestone_checkpoint_order(raw)[0] == 1
    assert _milestone_checkpoint_order(undealt)[0] == 0
    assert _milestone_checkpoint_order(raw)[0] > _milestone_checkpoint_order(undealt)[0]


def test_exact_tt_and_state_identity_ignore_authorised_lineage():
    state = _state([Card("s", 7)])
    tt = StrategicTranspositionTable()
    assert tt.admit(state, 1)
    assert not tt.admit(state.clone(), 1)
    with_auth = _node(authorised=("auth-1",))
    without = _node(authorised=())
    assert canonical_state_key(with_auth.state) == canonical_state_key(without.state)
    assert "authorised_epoch_transition_ids" not in canonical_state_key(with_auth.state).to_jsonable()
