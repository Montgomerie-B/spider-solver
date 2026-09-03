"""Focused regressions for bounded lead-source excavation parks.

A MIXED_SUIT_PARK may be admitted at CLEAN only when an exact two-peel
prefix from the same column exposes a same-suit receiver whose consume
exposes a current lead-lane buried source.  Receiver-uncover is not widened.
Unrelated parks stay speculative.  allowed_frontier_tiers(CLEAN) is unchanged.
"""

from __future__ import annotations

import inspect
import time
from pathlib import Path

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.move_lifecycle import PlacementClass, assess_tableau_move
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    ControllerTelemetry,
    StrategicCreditLevel,
    StrategicSearchNode,
    StrategicTranspositionTable,
    allowed_frontier_tiers,
    analyze_strategic_state,
    generate_strategic_successors,
)
from spider.planner.economic_projects import (
    EconomicFrontierTier,
    EconomicProjectKind,
    _project_from_lifecycle,
    analyze_economic_projects,
)
from spider.planner.lead_source_excavation import (
    LeadSourceExcavationReject,
    assess_lead_source_excavation,
)
from spider.planner.receiver_uncover import assess_receiver_uncover
from spider.rules import MW_RULES
from spider.state_identity import canonical_state_key, states_structurally_equal


ROOT = Path(__file__).resolve().parents[1]
PARK1 = (3, 0, 1)
PARK2 = (3, 8, 1)
CONSUME = (2, 3, 1)


def _card(suit: str, rank: int) -> Card:
    return Card(suit, rank)


def _state(*face_up) -> SpiderState:
    columns = [Column([], list(cards)) for cards in face_up]
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return SpiderState(columns, [])


def _cards() -> list[Card]:
    return [Card(suit, rank) for suit in "cdhs" for rank in range(1, 14) for _ in range(2)]


def _clean_config() -> AnytimeControllerConfig:
    return AnytimeControllerConfig(
        wall_clock_limit_s=8,
        max_strategic_expansions=2,
        max_tactical_nodes=1_000,
        max_frontier_size=50,
        max_credit_level=StrategicCreditLevel.CLEAN,
        campaign_source_combination_limit=4,
        enable_campaign_edges=False,
        enable_removal_edges=False,
        max_trace_entries=2,
        max_timeline_entries=2,
    )


def known_pattern_state() -> SpiderState:
    """As park, 9h park, Qh->Kh exposes Qd. Diamonds remain the cheap lead."""
    return _state(
        [_card("d", 2)],
        [_card("s", 9)],
        [_card("d", 12), _card("h", 12)],
        [_card("h", 13), _card("h", 9), _card("s", 1)],
        [_card("d", 1)],
        [_card("s", 8)],
        [_card("c", 7)],
        [_card("h", 5)],
        [_card("c", 10)],
        [_card("c", 4)],
    )


def join_broken_state() -> SpiderState:
    return _state(
        [_card("d", 2)],
        [_card("s", 9)],
        [_card("d", 12), _card("h", 12)],
        [_card("h", 13), _card("h", 9), _card("s", 2), _card("s", 1)],
        [_card("d", 1)],
        [_card("s", 8)],
        [_card("c", 7)],
        [_card("h", 5)],
        [_card("c", 10)],
        [_card("c", 4)],
    )


def no_source_state() -> SpiderState:
    """Same two peels, but Qh sits on nothing of the lead suit."""
    return _state(
        [_card("d", 2)],
        [_card("s", 9)],
        [_card("h", 12)],
        [_card("h", 13), _card("h", 9), _card("s", 1)],
        [_card("d", 1)],
        [_card("s", 8)],
        [_card("c", 7)],
        [_card("h", 5)],
        [_card("c", 10)],
        [_card("c", 4)],
    )


def uncover_pattern_state() -> SpiderState:
    """Existing receiver-uncover fixture: hQ park exposes s8, s7 joins."""
    return _state(
        [_card("s", 13)],
        [_card("d", 2)],
        [_card("c", 5)],
        [_card("s", 7)],
        [_card("h", 2)],
        [_card("d", 9)],
        [_card("c", 9)],
        [_card("h", 9)],
        [_card("s", 8), _card("h", 12)],
        [_card("d", 4)],
    )


def unrelated_speculative_park_state() -> SpiderState:
    return _state(
        [_card("c", 13)],
        [_card("s", 8), _card("h", 12)],
        [_card("d", 5)],
        [_card("c", 5)],
        [_card("h", 5)],
        [_card("s", 5)],
        [_card("d", 4)],
        [_card("c", 4)],
        [_card("h", 4)],
        [_card("s", 4)],
    )


def _project_for(state: SpiderState, action):
    analysis = analyze_economic_projects(state, cards=_cards())
    matches = [item for item in analysis.projects if item.action == action]
    if matches:
        return analysis, matches[0]
    assessment = assess_tableau_move(state, action, discover_exit=False)
    uncover = assess_receiver_uncover(state, action)
    excavation = assess_lead_source_excavation(state, action)
    return analysis, _project_from_lifecycle(
        assessment, 0, uncover=uncover, excavation=excavation
    )


def _successors(state: SpiderState, *, incoming=None, g: int = 0):
    config = _clean_config()
    cards = _cards()
    analysis = analyze_strategic_state(
        state, cards, spent_cost=g, incumbent_cost=None, config=config
    )
    node = StrategicSearchNode(
        0,
        state,
        g,
        (),
        None,
        incoming,
        0,
        StrategicCreditLevel.CLEAN,
        analysis,
    )
    telemetry = ControllerTelemetry()
    successors = generate_strategic_successors(
        node,
        cards,
        incumbent_cost=None,
        config=config,
        telemetry=telemetry,
        actionability_cache={},
        started=time.perf_counter(),
    )
    return successors, telemetry, analysis


def test_known_pattern_qualifies():
    state = known_pattern_state()
    evidence = assess_lead_source_excavation(state, PARK1)
    lifecycle = assess_tableau_move(state, PARK1, discover_exit=False)
    assert state.can_move(*PARK1)
    assert lifecycle.placement_class == PlacementClass.MIXED_SUIT_PARK
    assert not lifecycle.same_suit_joins_broken
    assert not assess_receiver_uncover(state, PARK1).qualified
    assert evidence.qualified
    assert evidence.reject is None
    assert evidence.second_park == PARK2
    assert evidence.consume == CONSUME
    assert evidence.receiver == _card("h", 13)
    assert evidence.consume_head == _card("h", 12)
    assert evidence.exposed_source == _card("d", 12)
    replay = state.clone()
    assert replay.move(*PARK1, rules=MW_RULES) == 1
    assert replay.move(*PARK2, rules=MW_RULES) == 1
    assert replay.move(*CONSUME, rules=MW_RULES) == 1
    assert replay.columns[2].top() == _card("d", 12)


def test_known_pattern_is_emitted_at_clean():
    successors, telemetry, analysis = _successors(known_pattern_state())
    excav = [
        item
        for item in successors
        if item.actions == (PARK1,) and item.lead_source_excavation_followup == PARK2
    ]
    assert excav, [item.actions for item in successors]
    assert excav[0].lead_source_excavation_consume == CONSUME
    assert excav[0].kind.value == "ECONOMIC_PROJECT"
    assert excav[0].category == "rework"
    assert excav[0].receiver_uncover_followup is None
    assert telemetry.lead_source_excavation_qualified >= 1
    assert telemetry.lead_source_excavation_admitted_clean >= 1
    assert telemetry.lead_source_excavation_generated >= 1
    project = next(item for item in analysis.economic.projects if item.action == PARK1)
    assert project.kind == EconomicProjectKind.TEMPORARY_REWORK
    assert project.assessment.frontier_tier == EconomicFrontierTier.STRUCTURALLY_DOMINANT
    assert project.rework_investment is not None
    assert project.rework_investment.bounded_payoff is True
    assert project.rework_investment.payoff_followup == PARK2
    assert project.rework_investment.payoff_consume == CONSUME
    assert project.rework_investment.exit_route_bounded is False
    assert allowed_frontier_tiers(StrategicCreditLevel.CLEAN) == (
        EconomicFrontierTier.STRUCTURALLY_DOMINANT,
    )


def test_second_park_is_injected_from_the_child():
    state = known_pattern_state()
    first, _telemetry, _analysis = _successors(state)
    park = next(item for item in first if item.actions == (PARK1,))
    child, telemetry, _ = _successors(park.end_state, incoming=park, g=park.corrected_cost)
    follow = [item for item in child if item.actions == (PARK2,)]
    assert follow, [item.actions for item in child]
    # After peel 1 the remainder may be ordinary receiver-uncover (Kh exposed
    # as a one-ply receiver).  If uncover still rejects, the forced excavation
    # follow-up carries the consume.
    assert (
        follow[0].lead_source_excavation_followup == CONSUME
        or follow[0].receiver_uncover_followup == CONSUME
    )
    mid = park.end_state.clone()
    assert mid.can_move(*PARK2)
    assert mid.move(*PARK2, rules=MW_RULES) == 1
    assert mid.can_move(*CONSUME)
    assert mid.columns[3].top() == _card("h", 13)


def test_consume_is_ordinary_legal_spider():
    state = known_pattern_state()
    replay = state.clone()
    assert replay.move(*PARK1, rules=MW_RULES) == 1
    assert replay.move(*PARK2, rules=MW_RULES) == 1
    assert replay.move(*CONSUME, rules=MW_RULES) == 1
    assert states_structurally_equal(replay, known_pattern_state()) is False
    assert replay.columns[2].top() == _card("d", 12)


def test_breaking_a_stable_join_is_rejected():
    state = join_broken_state()
    evidence = assess_lead_source_excavation(state, PARK1)
    assert evidence.reject == LeadSourceExcavationReject.JOIN_BROKEN
    assert not evidence.qualified
    _analysis, project = _project_for(state, PARK1)
    assert project.assessment.frontier_tier != EconomicFrontierTier.STRUCTURALLY_DOMINANT
    successors, _telemetry, _analysis = _successors(state)
    excav = [
        item
        for item in successors
        if item.actions == (PARK1,) and item.lead_source_excavation_followup is not None
    ]
    assert not excav


def test_consume_without_lead_source_is_rejected():
    state = no_source_state()
    evidence = assess_lead_source_excavation(state, PARK1)
    assert evidence.reject == LeadSourceExcavationReject.NO_LEAD_SOURCE_EXPOSED
    assert not evidence.qualified
    successors, _telemetry, _analysis = _successors(state)
    excav = [
        item
        for item in successors
        if item.actions == (PARK1,) and item.lead_source_excavation_followup is not None
    ]
    assert not excav


def test_receiver_uncover_pattern_is_not_stolen():
    state = uncover_pattern_state()
    park = (8, 0, 1)
    uncover = assess_receiver_uncover(state, park)
    excav = assess_lead_source_excavation(state, park)
    assert uncover.qualified
    assert excav.reject == LeadSourceExcavationReject.UNCOVER_ALREADY_QUALIFIES
    assert not excav.qualified
    successors, telemetry, analysis = _successors(state)
    uncover_edges = [
        item for item in successors if item.actions == (park,) and item.receiver_uncover_followup
    ]
    excav_edges = [
        item
        for item in successors
        if item.actions == (park,) and item.lead_source_excavation_followup is not None
    ]
    assert uncover_edges
    assert not excav_edges
    assert telemetry.receiver_uncover_generated >= 1
    project = next(item for item in analysis.economic.projects if item.action == park)
    assert project.rework_investment is not None
    assert project.rework_investment.payoff_consume is None


def test_unrelated_temporary_rework_stays_speculative_at_clean():
    state = unrelated_speculative_park_state()
    action = (1, 0, 1)
    evidence = assess_lead_source_excavation(state, action)
    assert not evidence.qualified
    _analysis, project = _project_for(state, action)
    assert project.kind == EconomicProjectKind.TEMPORARY_REWORK
    assert project.assessment.frontier_tier == EconomicFrontierTier.SPECULATIVE_DEFERRABLE
    rework = project.rework_investment
    assert rework is None or rework.bounded_payoff is False
    successors, _telemetry, _analysis = _successors(state)
    assert (action,) not in {item.actions for item in successors}
    assert allowed_frontier_tiers(StrategicCreditLevel.CLEAN) == (
        EconomicFrontierTier.STRUCTURALLY_DOMINANT,
    )


def test_tt_canonical_identity_and_proof_unaffected():
    state = known_pattern_state()
    before = canonical_state_key(state)
    evidence = assess_lead_source_excavation(state, PARK1)
    assert evidence.qualified
    assert canonical_state_key(state) == before
    assert states_structurally_equal(state, known_pattern_state())
    _analysis, project = _project_for(state, PARK1)
    assert project.assessment.proof_pruning_allowed is False
    assert project.rework_investment is not None
    assert project.rework_investment.proof_pruning_allowed is False
    assert evidence.proof_pruning_allowed is False
    tt = StrategicTranspositionTable()
    assert tt.admit(state, 4)
    assert not tt.admit(state, 4)
    assert not tt.admit(state, 5)
    assert tt.admit(state, 3)
    source = inspect.getsource(allowed_frontier_tiers)
    assert "StrategicCreditLevel.CLEAN" in source
    assert "STRUCTURALLY_DOMINANT" in source
    assert source.index("return (EconomicFrontierTier.STRUCTURALLY_DOMINANT,)") < source.index(
        "POSITIVE_INVESTMENT"
    )
