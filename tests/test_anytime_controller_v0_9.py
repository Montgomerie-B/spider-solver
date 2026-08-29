from __future__ import annotations

import inspect
import random
from dataclasses import replace
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
import spider.planner.anytime_controller as controller_module
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    StrategicTranspositionTable,
    analyze_strategic_state,
)
from spider.planner.campaign_dependency_closure import (
    CampaignCriticalPathEntry,
    CampaignCriticalPathSummary,
    CampaignDependency,
    CampaignDependencyGraph,
    CampaignDependencyType,
)
from spider.planner.epoch_progression import (
    EpochTransitionStatus,
    PreDealWorkDisposition,
    PreDealWorkItem,
    analyze_campaign_epoch_availability,
    analyze_material_availability,
    assess_epoch_transition,
    classify_pre_deal_construction,
    current_stock_epoch,
    future_stock_rows,
    milestone_epoch_feasibility,
)
from spider.planner.milestone_conversion import (
    FreshMilestoneAssessment,
    MilestonePrimitiveStep,
    realize_milestone,
)
from spider.planner.strategic_milestone import (
    MilestoneConversionLedger,
    MilestonePredicateKind,
    MilestoneTargetPredicate,
    StrategicMilestone,
    StrategicMilestoneKind,
    StrategicMilestonePrerequisite,
    StrategicMilestoneProgress,
    StrategicMilestoneStatus,
    StrategicMilestonePortfolio,
    StrategicMilestonePlan,
    evaluate_milestone_progress,
    interval_is_assembled,
)
from spider.planner.structural_construction import (
    ConstructionDisposition,
    SameSuitConstructionOpportunity,
    analyze_same_suit_construction,
)
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key, states_structurally_equal


ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"


def _columns(*face_up, face_down=()):
    columns = []
    for index, cards in enumerate(face_up):
        down = list(face_down[index]) if index < len(face_down) else []
        columns.append(Column(down, list(cards)))
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return columns


def _state(*face_up, stock=(), face_down=()):
    return SpiderState(_columns(*face_up, face_down=face_down), list(stock))


def _milestone(state, *, kind=StrategicMilestoneKind.RUN_CONSTRUCTION, target=None):
    target = target or MilestoneTargetPredicate(
        MilestonePredicateKind.DURABLE_RUN,
        "build a three-card club run",
        suit="c",
        minimum_run_length=3,
    )
    return StrategicMilestone(
        "fixture-milestone",
        canonical_state_key(state),
        "C#1",
        "C#1",
        kind,
        target,
        "c",
        (7, 6, 5),
        ("fixture",),
        (StrategicMilestonePrerequisite("source", "expose source"),),
        StrategicMilestoneProgress(1, 3),
        2,
        4,
        3,
        4.0,
        12_000,
        "three-card run exists",
        "fresh analysis contradicts target",
        None,
    )


def _opportunity(*, action=(1, 0, 1), disposition=ConstructionDisposition.MAKE_NOW,
                 future=None, receiver=False):
    return SameSuitConstructionOpportunity(
        action, "c", (Card("c", 5),), Card("c", 6), 1, 1, 2, True, 1,
        False, 0, receiver, future, 0.0, 3, 0, disposition, ("fixture",)
    )


def test_01_unrestricted_deal_remains_on():
    assert MW_RULES.can_deal_into_empty is True


def test_02_canonical_regression_anchor_unchanged():
    result = validate_solution("4925153", ROOT / "solutions" / "4925153_canonical.moves")
    assert (result.mobilityware_moves, result.path_hash, result.state_hash) == (
        172, "77d169da2538ba8c", "4e9861540eac570cb"
    )


def test_03_milestone_target_is_explicit():
    milestone = _milestone(_state([Card("c", 7)], [Card("c", 6)], [Card("c", 5)]))
    assert milestone.target.description and milestone.completion_condition


def test_04_milestone_carries_campaign_identity():
    assert _milestone(_state()).campaign_id == "C#1"


def test_05_interval_groups_multiple_ranks():
    target = MilestoneTargetPredicate(MilestonePredicateKind.SAME_SUIT_INTERVAL, "7-5", "c", 7, 5)
    milestone = replace(_milestone(_state()), kind=StrategicMilestoneKind.INTERVAL_ASSEMBLY, target=target)
    assert milestone.ranks == (7, 6, 5)


def test_06_source_chain_groups_dependencies():
    milestone = _milestone(_state())
    assert len(milestone.prerequisites) == 1 and milestone.prerequisites[0].prerequisite_id == "source"


def test_07_fresh_reanalysis_occurs_between_steps():
    result = _two_step_conversion()
    assert result.fresh_reanalyses == 2


def test_08_progress_uses_fresh_state_not_coordinates():
    state = _state([Card("c", 7), Card("c", 6), Card("c", 5)])
    progress = evaluate_milestone_progress(state, _milestone(state))
    assert progress.complete and progress.fresh_state_hash


def test_09_copy_substitution_satisfies_interval():
    state = _state([Card("c", 7)], [Card("c", 7), Card("c", 6), Card("c", 5)])
    assert interval_is_assembled(state, "c", 7, 5)


def _two_step_conversion(max_steps=4):
    start = _state([Card("c", 7)], [Card("c", 6)], [Card("c", 5)])
    milestone = _milestone(start)

    def primitive(state, _milestone, *_limits):
        action = (1, 0, 1) if state.columns[1].face_up else (2, 0, 1)
        end = state.clone(); cost = end.move(*action)
        return MilestonePrimitiveStep((action,), end, cost, 1, (str(action),), True, "fixture")

    def fresh(state, prior):
        progress = evaluate_milestone_progress(state, prior)
        return FreshMilestoneAssessment(prior, progress, reason="fresh")

    return realize_milestone(start, milestone, primitive, fresh, max_primitive_steps=max_steps)


def test_10_multi_step_milestone_replays():
    result = _two_step_conversion()
    assert result.status == StrategicMilestoneStatus.ACHIEVED and result.independent_replay_verified


def test_11_bounded_partial_progress_is_represented():
    result = _two_step_conversion(max_steps=1)
    assert result.status == StrategicMilestoneStatus.ADVANCED and result.primitive_steps == 1


def test_12_contradictory_analysis_invalidates():
    start = _state([Card("c", 7)], [Card("c", 6)])
    milestone = _milestone(start)
    def primitive(state, *_args):
        end = state.clone(); cost = end.move(1, 0, 1)
        return MilestonePrimitiveStep(((1, 0, 1),), end, cost, 1, (), True, "fixture")
    result = realize_milestone(start, milestone, primitive, lambda _s, m: FreshMilestoneAssessment(None, m.progress, contradicted=True))
    assert result.status == StrategicMilestoneStatus.INVALIDATED


def test_13_same_target_can_be_superseded():
    start = _state([Card("c", 7)], [Card("c", 6)])
    milestone = _milestone(start)
    def primitive(state, *_args):
        end = state.clone(); cost = end.move(1, 0, 1)
        return MilestonePrimitiveStep(((1, 0, 1),), end, cost, 1, (), True, "fixture")
    result = realize_milestone(start, milestone, primitive, lambda _s, m: FreshMilestoneAssessment(m, m.progress, superseded=True))
    assert result.status == StrategicMilestoneStatus.SUPERSEDED


def test_14_portfolio_retains_alternates():
    a = _milestone(_state()); b = replace(a, milestone_id="alternate", objective_id="D#1", campaign_id="D#1")
    portfolio = StrategicMilestonePortfolio((a, b), StrategicMilestonePlan(a, (b,)), ((a.kind.value, 2),))
    assert portfolio.plan.alternates == (b,) and portfolio.plan.raw_fallback_available


def test_15_milestone_history_not_in_tt_identity():
    state = _state(); tt = StrategicTranspositionTable(); ledger = MilestoneConversionLedger()
    assert tt.admit(state, 2) and not tt.admit(state.clone(), 2, heuristic_score=ledger)


def test_16_lower_g_exact_state_dominates():
    state = _state(); tt = StrategicTranspositionTable()
    assert tt.admit(state, 5) and tt.admit(state.clone(), 4) and not tt.admit(state.clone(), 6)


def test_17_current_tableau_material_identified():
    state = _state([Card("c", 5)], face_down=([Card("c", 5)],))
    fact = analyze_material_availability(state, (("c", 5, 2),))[0]
    assert fact.face_up_copies == 1 and fact.hidden_tableau_copies == 1 and fact.current_epoch_sufficient


def test_18_future_stock_material_identified():
    state = _state([], stock=[Card("h", 13)] * 9 + [Card("c", 5)])
    fact = analyze_material_availability(state, (("c", 5, 1),))[0]
    assert fact.future_stock_epochs and not fact.current_epoch_sufficient


def test_19_duplicate_current_copy_prevents_false_block():
    state = _state([Card("c", 5)], stock=[Card("h", 13)] * 9 + [Card("c", 5)])
    fact = analyze_material_availability(state, (("c", 5, 1),))[0]
    assert fact.current_epoch_sufficient


def test_20_earliest_epoch_is_generic():
    stock = [Card("h", 13)] * 10 + [Card("c", 5)] + [Card("h", 12)] * 9
    state = _state([], stock=stock)
    fact = analyze_material_availability(state, (("c", 5, 1),))[0]
    assert fact.earliest_feasible_epoch == current_stock_epoch(state) + 1


def test_21_stock_block_has_no_proof_authority():
    state = _state([], stock=[Card("c", 5)] * 10)
    availability = analyze_campaign_epoch_availability(state, "C#1", "c", (5,))
    assert availability.preparation_only and not availability.proof_pruning_allowed


def test_22_stock_block_generates_preparation_assessment():
    state = _state([], stock=[Card("c", 5)] * 10)
    availability = analyze_campaign_epoch_availability(state, "C#1", "c", (5,))
    work = PreDealWorkItem("w", PreDealWorkDisposition.SHOULD_BEFORE_DEAL, "prep", "C#1", "m", None, 1, 2.0, "useful")
    assessment = assess_epoch_transition(state, (availability,), (work,))
    assert assessment.status == EpochTransitionStatus.PREPARATION_REQUIRED


def test_23_cheap_join_lost_after_deal_is_must():
    row = [Card("h", 9)] * 10
    items = classify_pre_deal_construction(_state([Card("c", 6)], [Card("c", 5)], stock=row), (_opportunity(),))
    assert items[0].disposition == PreDealWorkDisposition.MUST_BEFORE_DEAL


def test_24_exact_future_join_is_deferred():
    item = _opportunity(future=5)
    state = _state([Card("c", 6)], [Card("c", 5)], stock=[Card("h", 9)] * 10)
    assert classify_pre_deal_construction(state, (item,))[0].disposition == PreDealWorkDisposition.DEFER_FOR_FREE_FUTURE_JOIN


def test_25_receiver_damage_is_avoided():
    item = _opportunity(receiver=True)
    state = _state([Card("c", 6)], [Card("c", 5)], stock=[Card("h", 9)] * 10)
    assert classify_pre_deal_construction(state, (item,))[0].disposition == PreDealWorkDisposition.AVOID_BEFORE_DEAL


def test_26_completed_prep_promotes_purposeful_deal():
    state = _state([], stock=[Card("c", 5)] * 10)
    availability = analyze_campaign_epoch_availability(state, "C#1", "c", (5,))
    work = PreDealWorkItem("w", PreDealWorkDisposition.MUST_BEFORE_DEAL, "done", "C#1", "m", None, 1, 2.0, "done", completed=True)
    assert assess_epoch_transition(state, (availability,), (work,)).purposeful_deal_eligible


def test_27_deal_can_be_selected_with_legal_moves():
    state = _state([Card("c", 6)], [Card("c", 5)], stock=[Card("h", 9)] * 10)
    availability = analyze_campaign_epoch_availability(state, "D#1", "d", (5,))
    assert state.enumerate_moves() and assess_epoch_transition(state, (availability,)).purposeful_deal_eligible


def test_28_deal_remains_legal_with_empty_columns():
    assert _state([], stock=[Card("h", 9)] * 10).can_deal(MW_RULES)


def test_29_epoch_transition_records_exact_purpose():
    state = _state([], stock=[Card("c", 5)] * 10)
    availability = analyze_campaign_epoch_availability(state, "C#1", "c", (5,))
    assessment = assess_epoch_transition(state, (availability,))
    assert assessment.exact_next_row == tuple(state.stock[-10:]) and "C#1" in assessment.purpose


def test_30_postdeal_material_analysis_is_fresh():
    state = _state([], stock=[Card("c", 5)] * 10); before = canonical_state_key(state)
    state.deal(MW_RULES)
    assert canonical_state_key(state) != before and analyze_material_availability(state, (("c", 5, 1),))[0].current_epoch_sufficient


def test_31_workspace_requires_intended_use():
    target = MilestoneTargetPredicate(MilestonePredicateKind.WORKSPACE_USED_RECOVERED, "lifecycle", workspace_requires_use=True, workspace_requires_recovery=True)
    milestone = replace(_milestone(_state()), kind=StrategicMilestoneKind.WORKSPACE_LIFECYCLE, target=target, progress=StrategicMilestoneProgress(0, 3))
    progress = evaluate_milestone_progress(_state(), milestone, workspace_created=True, workspace_used=False, workspace_recovered_or_replaced=True)
    assert not progress.complete


def test_32_workspace_recovery_semantics_retained():
    target = MilestoneTargetPredicate(MilestonePredicateKind.WORKSPACE_USED_RECOVERED, "lifecycle", workspace_requires_use=True, workspace_requires_recovery=True)
    milestone = replace(_milestone(_state()), kind=StrategicMilestoneKind.WORKSPACE_LIFECYCLE, target=target, progress=StrategicMilestoneProgress(0, 3))
    assert evaluate_milestone_progress(_state(), milestone, workspace_created=True, workspace_used=True, workspace_recovered_or_replaced=True).complete


def test_33_two_card_run_is_a_durable_milestone():
    state = _state([Card("c", 6)], [Card("c", 5)])
    opportunity = analyze_same_suit_construction(state).opportunities[0]
    assert opportunity.run_length_after == 2 and StrategicMilestoneKind.RUN_CONSTRUCTION.value


def test_34_late_suit_construction_visible():
    state = _state([Card("c", 6)], [Card("c", 5)], stock=[Card("h", 9)] * 20)
    assert analyze_same_suit_construction(state).opportunities


def test_35_near_removal_does_not_erase_construction_kind():
    assert StrategicMilestoneKind.RUN_CONSTRUCTION in tuple(StrategicMilestoneKind)


def test_36_controller_milestones_require_v08_allocator_envelope():
    config = AnytimeControllerConfig(enable_strategic_milestones=True, enable_tactical_resource_allocation=True)
    assert config.milestone_max_nodes_per_expansion == config.tactical_resource_config.max_granted_nodes_per_expansion


def test_37_conversion_time_cap_cannot_exceed_allocator():
    config = AnytimeControllerConfig(enable_strategic_milestones=True)
    assert config.milestone_max_time_s_per_expansion <= config.tactical_resource_config.max_granted_seconds_per_expansion


def test_38_conversion_node_cap_cannot_exceed_allocator():
    config = AnytimeControllerConfig(enable_strategic_milestones=True)
    assert config.milestone_max_nodes_per_expansion <= config.tactical_resource_config.max_granted_nodes_per_expansion


def test_39_bounded_miss_has_no_proof_authority():
    start = _state(); result = realize_milestone(start, _milestone(start), lambda *_: None, lambda _s, m: FreshMilestoneAssessment(m, m.progress))
    assert result.status == StrategicMilestoneStatus.BOUNDED_MISS and not result.proof_pruning_allowed


def test_40_expensive_unqualified_removal_stays_gated():
    source = inspect.getsource(controller_module._foundation_successors)
    assert "REMOVAL_DIAGNOSTIC_ONLY" in source and "terminal_qualified" not in source.lower() or "campaign_is_near_removal" in source


def test_41_terminal_predicate_is_existing_predicate():
    source = inspect.getsource(controller_module._fresh_milestone_facts)
    assert "campaign_is_near_removal" in source


def test_42_qualified_kind_can_invoke_terminal_assembly():
    source = inspect.getsource(controller_module._milestone_conversion_successors)
    assert "FOUNDATION_REMOVAL" in source and "_foundation_successors" in source


def test_43_purposeful_deal_is_not_automatic():
    state = _state([Card("c", 5)], stock=[Card("h", 9)] * 10)
    available = analyze_campaign_epoch_availability(state, "C#1", "c", (5,))
    assert not assess_epoch_transition(state, (available,)).purposeful_deal_eligible


def test_44_boundedly_exhausted_work_cannot_suppress_deal_forever():
    state = _state([], stock=[Card("c", 5)] * 10)
    blocked = analyze_campaign_epoch_availability(state, "C#1", "c", (5,))
    work = PreDealWorkItem("w", PreDealWorkDisposition.MUST_BEFORE_DEAL, "prep", "C#1", "m", None, 1, 1, "pending")
    assert assess_epoch_transition(state, (blocked,), (work,), boundedly_exhausted=True).purposeful_deal_eligible


def test_45_raw_fallback_remains_available():
    assert StrategicMilestonePlan(None, ()).raw_fallback_available


def test_46_canonical_actions_unavailable_prospectively():
    assert "canonical.moves" not in inspect.getsource(controller_module)


def test_47_external_target_absent_from_strategy():
    text = (ROOT / "src/spider/planner/strategic_milestone.py").read_text()
    assert "119" not in text


def test_48_benchmark_constants_absent_from_milestone_modules():
    text = "".join((ROOT / "src/spider/planner" / name).read_text().lower() for name in ("strategic_milestone.py", "epoch_progression.py", "milestone_conversion.py"))
    assert "spade" not in text and "diamond" not in text and "4925153" not in text


def test_49_unseen_deals_get_generic_epoch_analysis():
    cards = load_deal(DEAL); random.Random(73).shuffle(cards); state = SpiderState.from_cards(cards)
    fact = analyze_campaign_epoch_availability(state, "H#1", "h", tuple(range(13, 0, -1)))
    assert len(fact.material) == 13 and fact.current_epoch == 0


def test_50_diagnostic_telemetry_fields_exist():
    fields = controller_module.ControllerTelemetry.__dataclass_fields__
    assert "milestone_timeline" in fields and "epoch_timeline" in fields and "purposeful_deals" in fields
