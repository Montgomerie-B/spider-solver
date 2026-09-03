"""Focused regressions for scheduler v0.6 bounded receiver-uncover parks.

Qualifying MIXED_SUIT_PARK moves stay TEMPORARY_REWORK.  A bounded PAYOFF
(the exact enabled same-suit follow-up) may admit them at CLEAN without
claiming a bounded EXIT of the parked card and without relaxing unrelated
parks or allowed_frontier_tiers(CLEAN).
"""

from __future__ import annotations

import inspect
import time
from pathlib import Path

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.move_lifecycle import (
    BoundedCompensatingBenefit,
    PlacementClass,
    assess_tableau_move,
    with_bounded_compensation,
)
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
from spider.planner.receiver_uncover import ReceiverUncoverReject, assess_receiver_uncover
from spider.planner.whole_deal_scheduler import (
    SUITS,
    _stable_fragments,
    build_whole_deal_blueprint,
    lead_maturation_legal_step,
    rebuild_whole_deal_schedule,
)
from spider.rules import MW_RULES
from spider.state_identity import canonical_state_key, states_structurally_equal


ROOT = Path(__file__).resolve().parents[1]
PARK = (8, 0, 1)
FOLLOW = (3, 8, 1)


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


def _fragment_count(state: SpiderState) -> int:
    return sum(len(_stable_fragments(state, suit)) for suit in SUITS)


def known_pattern_state() -> SpiderState:
    """hQ park from c9 onto sK exposes s8; s7 can then join."""
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


def join_broken_state() -> SpiderState:
    return _state(
        [_card("c", 8)],
        [_card("d", 2)],
        [_card("h", 2)],
        [_card("s", 4)],
        [_card("d", 5)],
        [_card("h", 5)],
        [_card("s", 5)],
        [_card("d", 9)],
        [_card("s", 8), _card("s", 7)],
        [_card("h", 9)],
    )


def no_fragment_reduction_state() -> SpiderState:
    return _state(
        [_card("s", 13)],
        [_card("d", 2)],
        [_card("c", 5)],
        [_card("s", 9), _card("s", 8), _card("s", 7)],
        [_card("h", 2)],
        [_card("d", 9)],
        [_card("c", 9)],
        [_card("h", 9)],
        [_card("s", 8), _card("h", 12)],
        [_card("d", 4)],
    )


def canonical_worse_state() -> SpiderState:
    """Hearts remain lead; burying hQ under sJ worsens the canonical key."""
    return _state(
        [_card("h", 12)],
        [_card("h", 11)],
        [_card("h", 10)],
        [_card("s", 7)],
        [_card("h", 13)],
        [_card("h", 9)],
        [_card("h", 8)],
        [_card("h", 7)],
        [_card("s", 8), _card("s", 11)],
        [_card("h", 6)],
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


def _quality(state: SpiderState, action) -> str:
    evidence = assess_receiver_uncover(state, action)
    lifecycle = assess_tableau_move(state, action, discover_exit=False)
    pre = evidence.pre_key
    follow = evidence.followup_key
    lead_worse = bool(pre is not None and follow is not None and follow > pre)
    state_order = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6}
    state_b = None if pre is None else pre[0]
    state_f = None if follow is None else follow[0]
    state_worse = bool(
        state_b in state_order
        and state_f in state_order
        and state_f > state_b
    )
    follow_suit = None
    if evidence.followup_head is not None:
        follow_suit = evidence.followup_head.suit
    lead_after_suit = None if follow is None else follow[3]
    pathological = bool(
        lifecycle.same_suit_joins_broken
        or len(lifecycle.mixed_suit_boundaries_created) >= 2
        or lifecycle.estimated_rehandling_cost >= 2
        or (state_worse and (state_f or 0) - (state_b or 0) >= 2)
    )
    if pathological and not (pre is not None and follow is not None and follow < pre):
        return "D_PATHOLOGICAL"
    if (
        lead_after_suit is not None
        and follow_suit is not None
        and lead_after_suit != follow_suit
        and lead_worse
        and evidence.fragment_reduction >= 1
    ):
        return "C_STRUCTURAL_TRADE"
    if lead_worse or state_worse:
        return "B_LOCAL_ONLY"
    return "A_STRONG"


def _project_for(state: SpiderState, action):
    analysis = analyze_economic_projects(state, cards=_cards())
    matches = [item for item in analysis.projects if item.action == action]
    if matches:
        return analysis, matches[0]
    assessment = assess_tableau_move(state, action, discover_exit=False)
    uncover = assess_receiver_uncover(state, action)
    return analysis, _project_from_lifecycle(assessment, 0, uncover=uncover)


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
    evidence = assess_receiver_uncover(state, PARK)
    lifecycle = assess_tableau_move(state, PARK, discover_exit=False)
    assert state.can_move(*PARK)
    assert lifecycle.placement_class == PlacementClass.MIXED_SUIT_PARK
    assert not lifecycle.same_suit_joins_broken
    assert evidence.qualified
    assert evidence.reject is None
    assert evidence.followup == FOLLOW
    assert evidence.receiver == _card("s", 8)
    assert evidence.followup_head == _card("s", 7)
    assert evidence.fragment_reduction >= 1
    assert evidence.pre_key is not None and evidence.followup_key is not None
    assert evidence.followup_key <= evidence.pre_key
    assert _quality(state, PARK) == "A_STRONG"


def test_known_pattern_is_emitted_at_clean():
    successors, telemetry, analysis = _successors(known_pattern_state())
    uncover = [item for item in successors if item.actions == (PARK,)]
    assert uncover, [item.actions for item in successors]
    assert uncover[0].receiver_uncover_followup == FOLLOW
    assert uncover[0].kind.value == "ECONOMIC_PROJECT"
    assert uncover[0].category == "rework"
    assert telemetry.receiver_uncover_qualified >= 1
    assert telemetry.receiver_uncover_admitted_clean >= 1
    assert telemetry.receiver_uncover_generated >= 1
    project = next(item for item in analysis.economic.projects if item.action == PARK)
    assert project.kind == EconomicProjectKind.TEMPORARY_REWORK
    assert project.assessment.frontier_tier == EconomicFrontierTier.STRUCTURALLY_DOMINANT
    assert allowed_frontier_tiers(StrategicCreditLevel.CLEAN) == (
        EconomicFrontierTier.STRUCTURALLY_DOMINANT,
    )


def test_followup_is_ordinary_legal_spider():
    state = known_pattern_state()
    post = state.clone()
    park_cost = post.move(*PARK, rules=MW_RULES)
    assert park_cost == 1
    assert post.can_move(*FOLLOW)
    follow_cost = post.move(*FOLLOW, rules=MW_RULES)
    assert follow_cost == 1
    replay = known_pattern_state()
    assert replay.move(*PARK, rules=MW_RULES) == 1
    assert replay.move(*FOLLOW, rules=MW_RULES) == 1
    assert states_structurally_equal(replay, post)


def test_followup_reduces_fragments_and_is_generated():
    state = known_pattern_state()
    before = _fragment_count(state)
    post = state.clone()
    post.move(*PARK, rules=MW_RULES)
    schedule = rebuild_whole_deal_schedule(post, build_whole_deal_blueprint(post))
    step = lead_maturation_legal_step(schedule)
    assert step is not None
    _objective, _lead, evidence = step
    assert FOLLOW in evidence.actions
    after = post.clone()
    after.move(*FOLLOW, rules=MW_RULES)
    assert _fragment_count(after) <= before - 1
    successors, _telemetry, _analysis = _successors(post, g=1)
    assert any(FOLLOW in item.actions for item in successors)


def test_breaking_a_stable_join_is_rejected():
    state = join_broken_state()
    evidence = assess_receiver_uncover(state, PARK)
    assert evidence.reject == ReceiverUncoverReject.JOIN_BROKEN
    assert not evidence.qualified
    _analysis, project = _project_for(state, PARK)
    assert project.assessment.frontier_tier != EconomicFrontierTier.STRUCTURALLY_DOMINANT
    successors, _telemetry, _analysis = _successors(state)
    assert (PARK,) not in {item.actions for item in successors}


def test_followup_without_fragment_reduction_is_rejected():
    state = no_fragment_reduction_state()
    evidence = assess_receiver_uncover(state, PARK)
    assert evidence.reject == ReceiverUncoverReject.NO_FRAGMENT_REDUCTION
    assert evidence.followup == FOLLOW
    assert evidence.fragment_reduction < 1
    assert not evidence.qualified
    _analysis, project = _project_for(state, PARK)
    assert project.assessment.frontier_tier != EconomicFrontierTier.STRUCTURALLY_DOMINANT
    successors, _telemetry, _analysis = _successors(state)
    assert (PARK,) not in {item.actions for item in successors}


def test_canonical_followup_lead_worse_is_rejected():
    state = canonical_worse_state()
    evidence = assess_receiver_uncover(state, PARK)
    assert evidence.reject == ReceiverUncoverReject.CANONICAL_WORSE
    assert evidence.fragment_reduction >= 1
    assert evidence.pre_key is not None and evidence.followup_key is not None
    assert evidence.followup_key > evidence.pre_key
    assert not evidence.qualified
    _analysis, project = _project_for(state, PARK)
    assert project.assessment.frontier_tier != EconomicFrontierTier.STRUCTURALLY_DOMINANT
    successors, _telemetry, _analysis = _successors(state)
    uncover = [item for item in successors if item.actions == (PARK,)]
    assert not uncover


def test_b_c_d_quality_fixtures_remain_rejected():
    broken = join_broken_state()
    worse = canonical_worse_state()
    assert _quality(broken, PARK) == "D_PATHOLOGICAL"
    assert _quality(worse, PARK) == "C_STRUCTURAL_TRADE"
    # Compact same-suit-lead regressions improve the canonical key, matching
    # the diagnostic result that B_LOCAL_ONLY died at the canonical filter.
    # The B reject path is the same CANONICAL_WORSE gate exercised here.
    assert not assess_receiver_uncover(broken, PARK).qualified
    assert not assess_receiver_uncover(worse, PARK).qualified
    assert _quality(known_pattern_state(), PARK) == "A_STRONG"


def test_parked_card_exit_may_remain_unbounded_while_payoff_qualifies():
    state = known_pattern_state()
    lifecycle = assess_tableau_move(state, PARK, discover_exit=True)
    assert not lifecycle.exit_route_bounded
    _analysis, project = _project_for(state, PARK)
    rework = project.rework_investment
    assert rework is not None
    assert rework.bounded_payoff is True
    assert rework.payoff_followup == FOLLOW
    assert rework.exit_route_bounded is False
    assert rework.worthwhile is True
    compensated = with_bounded_compensation(
        lifecycle,
        BoundedCompensatingBenefit(
            1.0,
            "exact enabled same-suit follow-up",
            "receiver-uncover bounded payoff; parked-card exit unchanged",
            bounded_payoff=True,
        ),
    )
    assert compensated.compensating_benefit is not None
    assert compensated.compensating_benefit.bounded_payoff is True
    assert not compensated.can_override_permanent_join
    assert not compensated.proof_pruning_allowed


def test_unrelated_temporary_rework_stays_speculative_at_clean():
    state = unrelated_speculative_park_state()
    action = (1, 0, 1)
    evidence = assess_receiver_uncover(state, action)
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
    evidence = assess_receiver_uncover(state, PARK)
    assert evidence.qualified
    assert canonical_state_key(state) == before
    assert states_structurally_equal(state, known_pattern_state())
    _analysis, project = _project_for(state, PARK)
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
    three_arg = BoundedCompensatingBenefit(2, "two saved moves", "bounded alternative")
    assert three_arg.bounded_payoff is False
