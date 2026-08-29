from __future__ import annotations

import inspect
import random
from dataclasses import replace
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
import spider.planner.anytime_controller as controller_module
import spider.planner.milestone_actionability as actionability_module
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    StrategicCreditLevel,
    StrategicSearchNode,
    StrategicTranspositionTable,
    analyze_strategic_state,
)
from spider.planner.campaign_dependency_closure import (
    CampaignDependency,
    CampaignDependencyGraph,
    CampaignDependencyType,
)
from spider.planner.incumbent_budget import build_incumbent_budget
from spider.planner.milestone_actionability import (
    MilestoneBlockerKind,
    PostDealObligationStatus,
    ResidualTargetStatus,
    create_post_deal_obligation,
    derive_residual_milestone_target,
    refresh_post_deal_obligation,
)
from spider.planner.milestone_conversion import (
    FreshMilestoneAssessment,
    MilestonePrimitiveStep,
    realize_milestone,
)
from spider.planner.strategic_milestone import (
    MilestoneConversionLedger,
    MilestoneOutcomeKind,
    MilestonePredicateKind,
    MilestoneRealizationResult,
    MilestoneTargetPredicate,
    StrategicMilestone,
    StrategicMilestoneKind,
    StrategicMilestonePlan,
    StrategicMilestonePortfolio,
    StrategicMilestoneProgress,
    StrategicMilestoneStatus,
    classify_milestone_outcome,
    evaluate_milestone_progress,
    milestone_target_identity,
)
from spider.planner.structural_construction import analyze_same_suit_construction
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key


ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"


def _state(*face_up, stock=(), face_down=()):
    columns = []
    for index, cards in enumerate(face_up):
        down = list(face_down[index]) if index < len(face_down) else []
        columns.append(Column(down, list(cards)))
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return SpiderState(columns, list(stock))


def _milestone(
    state: SpiderState,
    *,
    kind: StrategicMilestoneKind = StrategicMilestoneKind.INTERVAL_ASSEMBLY,
    target: MilestoneTargetPredicate | None = None,
    dependencies=("overlay:7-5:c3",),
) -> StrategicMilestone:
    target = target or MilestoneTargetPredicate(
        MilestonePredicateKind.SAME_SUIT_INTERVAL,
        "assemble club 7 through 5",
        suit="c",
        high_rank=7,
        low_rank=5,
        dependency_ids=tuple(dependencies),
    )
    return StrategicMilestone(
        "target-fixture",
        canonical_state_key(state),
        "C#1",
        "C#1",
        kind,
        target,
        "c",
        (7, 6, 5),
        ("column 3",),
        (),
        StrategicMilestoneProgress(1, 3),
        3,
        4,
        3,
        4.0,
        12_000,
        "one contiguous club run covers 7 through 5",
        "fresh analysis contradicts the logical objective",
        None,
    )


def _graph(state: SpiderState, *kinds: CampaignDependencyType) -> CampaignDependencyGraph:
    dependencies = tuple(
        CampaignDependency(
            (
                f"overlay:7-5:c{index}"
                if kind == CampaignDependencyType.MIXED_OVERLAY
                else f"{kind.value.lower()}:{index}"
            ),
            kind,
            "C#1",
            kind.value,
            rank_interval=(7, 5)
            if kind == CampaignDependencyType.MISSING_SAME_SUIT_INTERVAL
            else None,
            column=index,
            depth=index,
        )
        for index, kind in enumerate(kinds, 1)
    )
    return CampaignDependencyGraph(
        canonical_state_key(state),
        "C#1",
        dependencies,
        (),
        (),
        "terminal:C#1",
        "fixture-graph",
    )


def _source_milestone(state: SpiderState, dependency="source_buried:1"):
    target = MilestoneTargetPredicate(
        MilestonePredicateKind.DEPENDENCIES_CLOSED,
        "close named source chain",
        suit="c",
        dependency_ids=(dependency,),
    )
    return replace(
        _milestone(state, kind=StrategicMilestoneKind.SOURCE_CHAIN, target=target),
        ranks=(),
        progress=StrategicMilestoneProgress(0, 1, (dependency,)),
    )


def _terminal_milestone(state: SpiderState):
    target = MilestoneTargetPredicate(
        MilestonePredicateKind.TERMINAL_QUALIFIED,
        "reach existing terminal predicate",
        suit="c",
    )
    return replace(
        _milestone(state, kind=StrategicMilestoneKind.TERMINAL_QUALIFICATION, target=target),
        ranks=tuple(range(13, 0, -1)),
        progress=StrategicMilestoneProgress(0, 1),
    )


def _epoch_milestone(state: SpiderState):
    target = MilestoneTargetPredicate(
        MilestonePredicateKind.STOCK_EPOCH_REACHED,
        "reach next stock epoch",
        suit="c",
        target_stock_epoch=1,
    )
    return replace(
        _milestone(state, kind=StrategicMilestoneKind.EPOCH_TRANSITION, target=target),
        progress=StrategicMilestoneProgress(0, 1),
        max_primitive_steps=1,
    )


def _epoch_result(state: SpiderState) -> MilestoneRealizationResult:
    milestone = replace(
        _epoch_milestone(state), status=StrategicMilestoneStatus.ACHIEVED
    )
    return MilestoneRealizationResult(
        milestone,
        StrategicMilestoneStatus.ACHIEVED,
        (("deal",),),
        1,
        state,
        1,
        0,
        0.0,
        True,
        1,
        (),
        "fixture transition",
        outcome_kind=MilestoneOutcomeKind.TRANSITION_CHECKPOINT,
        target_identity=milestone_target_identity(milestone),
    )


def _interval_conversion(max_steps=4):
    start = _state([Card("c", 7)], [Card("c", 6)], [Card("c", 5)])
    milestone = _milestone(start)

    def primitive(state, _target, *_limits):
        action = (1, 0, 1) if state.columns[1].face_up else (2, 0, 1)
        end = state.clone()
        cost = end.move(*action)
        return MilestonePrimitiveStep((action,), end, cost, 1, (), True, "join")

    def fresh(state, prior):
        progress = evaluate_milestone_progress(state, prior)
        return FreshMilestoneAssessment(prior, progress, reason="fresh interval")

    return realize_milestone(
        start, milestone, primitive, fresh, max_primitive_steps=max_steps
    )


def test_01_unrestricted_deal_remains_on():
    assert MW_RULES.can_deal_into_empty


def test_02_regression_anchors_unchanged():
    result = validate_solution("4925153", ROOT / "solutions" / "4925153_canonical.moves")
    assert (result.mobilityware_moves, result.path_hash, result.state_hash) == (
        172, "77d169da2538ba8c", "4e9861540eac570cb"
    )


def test_03_semantic_interval_identity_contains_no_coordinates():
    identity = milestone_target_identity(_milestone(_state()))
    assert "c3" not in repr(identity.fingerprint) and "column" not in repr(identity.fingerprint)


def test_04_semantic_source_chain_identity_contains_no_stale_coordinates():
    milestone = _source_milestone(_state(), "overlay:7-5:c8")
    assert milestone_target_identity(milestone).dependency_outcomes == ("overlay:7-5",)


def test_05_residual_target_removes_satisfied_requirements():
    state = _state([Card("c", 7), Card("c", 6), Card("c", 5)])
    residual = derive_residual_milestone_target(state, _milestone(state))
    assert residual.status == ResidualTargetStatus.COMPLETE and all(
        item.satisfied for item in residual.requirements
    )


def test_06_residual_target_retains_unsatisfied_predicate():
    state = _state([Card("c", 7)], [Card("c", 6)], [Card("c", 5)])
    residual = derive_residual_milestone_target(
        state, _milestone(state), construction=analyze_same_suit_construction(state)
    )
    assert residual.status == ResidualTargetStatus.ACTIONABLE and not all(
        item.satisfied for item in residual.requirements
    )


def test_07_blocker_remaps_overlay_to_receiver():
    state = _state([Card("c", 7)])
    target = _terminal_milestone(state)
    overlay = derive_residual_milestone_target(
        state, target, graph=_graph(state, CampaignDependencyType.MIXED_OVERLAY)
    )
    receiver = derive_residual_milestone_target(
        state, target, graph=_graph(state, CampaignDependencyType.RECEIVER_MISSING)
    )
    assert overlay.blockers[0] == MilestoneBlockerKind.MIXED_OVERLAY
    assert receiver.blockers[0] == MilestoneBlockerKind.RECEIVER_MISSING


def test_08_blocker_remaps_receiver_to_construction():
    state = _state([Card("c", 7)], [Card("c", 6)])
    target = _terminal_milestone(state)
    receiver = derive_residual_milestone_target(
        state, target, graph=_graph(state, CampaignDependencyType.RECEIVER_MISSING)
    )
    interval = derive_residual_milestone_target(
        state,
        target,
        graph=_graph(state, CampaignDependencyType.MISSING_SAME_SUIT_INTERVAL),
        construction=analyze_same_suit_construction(state),
    )
    assert receiver.blockers[0] == MilestoneBlockerKind.RECEIVER_MISSING
    assert MilestoneBlockerKind.MISSING_INTERVAL in interval.blockers


def test_09_blocker_remaps_supplied_asset_to_integration():
    state = _state([Card("c", 7)])
    residual = derive_residual_milestone_target(
        state,
        _terminal_milestone(state),
        graph=_graph(state, CampaignDependencyType.SUPPLIED_NOT_CONSUMED),
    )
    assert residual.candidates[0].demand.objective.value == "SUPPLY_CONSUMPTION"


def test_10_terminal_ready_remaps_to_terminal_assembly():
    state = _state([Card("c", 7)])
    residual = derive_residual_milestone_target(
        state,
        _terminal_milestone(state),
        graph=_graph(state, CampaignDependencyType.TERMINAL_ASSEMBLY_PREREQUISITE),
    )
    assert residual.candidates[0].demand.realizer.value == "TERMINAL_ASSEMBLY"


def test_11_fresh_descendant_does_not_restart_completed_work():
    first = _state([Card("c", 7), Card("c", 6)], [Card("c", 5)])
    second = _state([Card("c", 7), Card("c", 6), Card("c", 5)])
    milestone = _milestone(first)
    a = derive_residual_milestone_target(first, milestone, construction=analyze_same_suit_construction(first))
    b = derive_residual_milestone_target(second, milestone)
    assert a.progress.satisfied_units == 2 and b.progress.satisfied_units == 3


def test_12_physical_copy_substitution_preserves_target():
    a = _milestone(_state([Card("c", 7)]))
    b = replace(a, starting_state=canonical_state_key(_state([Card("c", 7)], [Card("c", 7)])))
    assert milestone_target_identity(a) == milestone_target_identity(b)


def test_13_source_location_changes_without_target_identity_change():
    a = _source_milestone(_state([Card("c", 7)]), "overlay:7-5:c1")
    b = replace(a, target=replace(a.target, dependency_ids=("overlay:7-5:c9",)))
    assert milestone_target_identity(a).fingerprint == milestone_target_identity(b).fingerprint


def test_14_one_permanent_join_records_primitive_harvest():
    result = _interval_conversion(max_steps=1)
    assert result.primitive_steps == 1 and result.harvest_events == ()


def test_15_one_join_does_not_automatically_imply_substantial_completion():
    result = _interval_conversion(max_steps=1)
    assert result.outcome_kind == MilestoneOutcomeKind.PRIMITIVE_RESULT


def test_16_completed_coherent_interval_records_substantial_milestone():
    result = _interval_conversion()
    assert result.status == StrategicMilestoneStatus.ACHIEVED
    assert result.outcome_kind == MilestoneOutcomeKind.SUBSTANTIAL_STRUCTURAL_MILESTONE


def test_17_partial_source_chain_remains_active():
    state = _state([Card("c", 7)])
    residual = derive_residual_milestone_target(
        state,
        _source_milestone(state),
        graph=_graph(state, CampaignDependencyType.SOURCE_BURIED),
    )
    assert residual.status == ResidualTargetStatus.ACTIONABLE and not residual.progress.complete


def test_18_complete_source_chain_records_substantial_completion():
    state = _state([Card("c", 7)])
    milestone = _source_milestone(state)
    milestone = replace(
        milestone,
        target=replace(
            milestone.target,
            dependency_ids=("source_buried:1", "receiver_missing:2"),
        ),
        progress=StrategicMilestoneProgress(
            0, 2, ("source_buried:1", "receiver_missing:2")
        ),
    )
    residual = derive_residual_milestone_target(state, milestone, graph=_graph(state))
    status = StrategicMilestoneStatus.ACHIEVED if residual.progress.complete else StrategicMilestoneStatus.ACTIVE
    assert classify_milestone_outcome(milestone, status) == MilestoneOutcomeKind.SUBSTANTIAL_STRUCTURAL_MILESTONE


def test_19_workspace_creation_alone_remains_incomplete():
    state = _state([Card("c", 7)])
    target = MilestoneTargetPredicate(
        MilestonePredicateKind.WORKSPACE_USED_RECOVERED,
        "workspace lifecycle",
        suit="c",
        workspace_requires_use=True,
        workspace_requires_recovery=True,
    )
    milestone = replace(_milestone(state), kind=StrategicMilestoneKind.WORKSPACE_LIFECYCLE, target=target)
    progress = evaluate_milestone_progress(state, milestone, workspace_created=True)
    residual = derive_residual_milestone_target(
        state, replace(milestone, progress=progress), graph=_graph(state)
    )
    assert not progress.complete and residual.status != ResidualTargetStatus.COMPLETE


def test_20_workspace_use_and_recovery_can_complete_target():
    state = _state([Card("c", 7)])
    target = MilestoneTargetPredicate(
        MilestonePredicateKind.WORKSPACE_USED_RECOVERED,
        "workspace lifecycle",
        workspace_requires_use=True,
        workspace_requires_recovery=True,
    )
    milestone = replace(_milestone(state), kind=StrategicMilestoneKind.WORKSPACE_LIFECYCLE, target=target)
    progress = evaluate_milestone_progress(
        state, milestone, workspace_created=True, workspace_used=True,
        workspace_recovered_or_replaced=True,
    )
    residual = derive_residual_milestone_target(
        state, replace(milestone, progress=progress), graph=_graph(state)
    )
    assert progress.complete and residual.status == ResidualTargetStatus.COMPLETE


def test_21_postdeal_transition_is_distinct_from_structural_completion():
    milestone = _epoch_milestone(_state())
    assert classify_milestone_outcome(milestone, StrategicMilestoneStatus.ACHIEVED) == MilestoneOutcomeKind.TRANSITION_CHECKPOINT


def test_22_purposeful_deal_creates_postdeal_obligation():
    state = _state([], stock=[Card("c", 5)] * 10)
    obligation = create_post_deal_obligation(
        _epoch_milestone(state), _milestone(state), tuple(state.stock[-10:]), created_epoch=1
    )
    assert obligation.transition_milestone_id and obligation.target_identity.kind == StrategicMilestoneKind.INTERVAL_ASSEMBLY


def test_23_postdeal_material_arrival_is_detected():
    state = _state([], stock=[Card("c", 5)] * 10)
    obligation = create_post_deal_obligation(
        _epoch_milestone(state), _milestone(state), tuple(state.stock[-10:]), created_epoch=1
    )
    state.deal(MW_RULES)
    refreshed = refresh_post_deal_obligation(state, obligation, None)
    assert refreshed.material_available


def test_24_actionable_postdeal_target_receives_bounded_opportunity():
    state = _state([Card("c", 7)], [Card("c", 6)], [Card("c", 5)])
    residual = derive_residual_milestone_target(
        state, _milestone(state), construction=analyze_same_suit_construction(state)
    )
    assert residual.next_candidate is not None and residual.next_candidate.demand.continuation_attention


def test_25_structural_conversion_can_fulfil_postdeal_obligation():
    state = _state([Card("c", 7), Card("c", 6), Card("c", 5)])
    obligation = create_post_deal_obligation(
        _epoch_milestone(state), _milestone(state), (Card("c", 5),), created_epoch=1
    )
    complete = derive_residual_milestone_target(state, _milestone(state))
    refreshed = refresh_post_deal_obligation(
        state, obligation, complete, structural_progress=True, substantial_harvest=True
    )
    assert refreshed.status == PostDealObligationStatus.SUBSTANTIAL_HARVEST


def test_26_another_deal_may_remain_legal_before_conversion():
    assert _state([], stock=[Card("h", 9)] * 20).can_deal(MW_RULES)


def test_27_another_deal_is_downordered_when_promised_target_actionable():
    state = _state([], stock=[Card("c", 5)] * 10)
    obligation = create_post_deal_obligation(
        _epoch_milestone(state), _milestone(state), tuple(state.stock), created_epoch=1
    )
    result = _epoch_result(state)
    node = StrategicSearchNode(
        1, state, 1, (("deal",),), None, None, 1, StrategicCreditLevel.CLEAN,
        None, milestone_ledger=MilestoneConversionLedger((result,)),
        post_deal_obligations=(obligation,),
    )
    clean = replace(node, post_deal_obligations=())
    assert controller_module._milestone_checkpoint_order(node)[2] > controller_module._milestone_checkpoint_order(clean)[2]


def test_28_another_deal_may_win_when_target_genuinely_stock_blocked():
    state = _state([], stock=[Card("h", 9)] * 20)
    obligation = create_post_deal_obligation(
        _epoch_milestone(state), _milestone(state), (Card("c", 5),), created_epoch=1
    )
    blocked = replace(obligation, status=PostDealObligationStatus.BLOCKED, material_available=False)
    assert state.can_deal(MW_RULES) and not blocked.unresolved_actionable


def test_29_transitions_cannot_self_reward_indefinitely():
    state = _state()
    result = _epoch_result(state)
    node = StrategicSearchNode(
        1, state, 2, (("deal",), ("deal",)), None, None, 2,
        StrategicCreditLevel.CLEAN, None,
        milestone_ledger=MilestoneConversionLedger((result, result)),
    )
    assert controller_module._milestone_checkpoint_order(node)[1] == 0
    assert controller_module._milestone_checkpoint_order(node)[3] == 0


def test_30_persistent_target_survives_strategic_expansion_boundary():
    milestone = _milestone(_state([Card("c", 7)]))
    descendant = replace(milestone, starting_state=canonical_state_key(_state([Card("c", 7)], [Card("h", 4)])))
    assert milestone.same_target_key == descendant.same_target_key


def test_31_persistent_target_remains_bounded():
    milestone = _milestone(_state())
    assert (milestone.max_primitive_steps, milestone.max_strategic_expansions, milestone.max_tactical_nodes) == (4, 3, 12_000)


def test_32_persistent_target_invalidates_on_fresh_contradiction():
    state = _state([Card("c", 9)])
    target = replace(
        _milestone(state),
        kind=StrategicMilestoneKind.RUN_CONSTRUCTION,
        target=MilestoneTargetPredicate(
            MilestonePredicateKind.DURABLE_RUN, "club run", suit="c", minimum_run_length=3
        ),
    )
    residual = derive_residual_milestone_target(state, target, construction=analyze_same_suit_construction(state))
    assert residual.status == ResidualTargetStatus.INVALIDATED


def test_33_same_target_superior_descendant_may_supersede():
    start = _state([Card("c", 7)], [Card("c", 6)])
    milestone = _milestone(start)
    def primitive(state, *_args):
        end = state.clone(); cost = end.move(1, 0, 1)
        return MilestonePrimitiveStep(((1, 0, 1),), end, cost, 1, (), True, "join")
    result = realize_milestone(
        start, milestone, primitive,
        lambda _state, current: FreshMilestoneAssessment(current, current.progress, superseded=True),
    )
    assert result.status == StrategicMilestoneStatus.SUPERSEDED


def test_34_alternate_campaign_remains_represented():
    a = _milestone(_state())
    b = replace(a, milestone_id="alternate", objective_id="D#1", campaign_id="D#1")
    portfolio = StrategicMilestonePortfolio((a, b), StrategicMilestonePlan(a, (b,)), ())
    assert portfolio.plan.alternates == (b,)


def test_35_late_removal_construction_remains_represented():
    state = _state([Card("c", 6)], [Card("c", 5)], stock=[Card("h", 9)] * 20)
    assert analyze_same_suit_construction(state).opportunities


def test_36_deal_remains_represented():
    source = inspect.getsource(controller_module.generate_strategic_successors)
    assert "purposeful Deal" in source and "exact legal Deal fallback" in source


def test_37_raw_fallback_remains_represented():
    assert StrategicMilestonePlan(None, ()).raw_fallback_available


def test_38_milestone_actionability_uses_existing_v08_allocator():
    state = _state([Card("c", 7)], [Card("c", 6)])
    residual = derive_residual_milestone_target(
        state, _milestone(state), construction=analyze_same_suit_construction(state)
    )
    assert residual.next_candidate.demand.realizer.value == "RUN_CONSTRUCTION"
    assert "resource_allocator" in inspect.getsource(controller_module._milestone_conversion_successors)


def test_39_actionability_adapter_is_not_a_broad_search():
    source = inspect.getsource(actionability_module)
    assert "heapq" not in source and "enumerate_moves" not in source


def test_40_existing_per_expansion_budgets_unchanged():
    config = AnytimeControllerConfig(enable_strategic_milestones=True)
    assert (config.milestone_max_primitive_steps, config.milestone_max_strategic_expansions) == (4, 3)
    assert (config.milestone_max_time_s_per_expansion, config.milestone_max_nodes_per_expansion) == (4.0, 12_000)


def test_41_expensive_unqualified_removal_remains_gated():
    source = inspect.getsource(controller_module._foundation_successors)
    assert "campaign_is_near_removal" in source


def test_42_terminal_predicate_unchanged():
    source = inspect.getsource(controller_module._fresh_milestone_facts)
    assert "campaign_is_near_removal" in source


def test_43_actionability_miss_has_no_proof_authority():
    residual = derive_residual_milestone_target(_state([Card("c", 9)]), _milestone(_state([Card("c", 9)])))
    assert not residual.proof_pruning_allowed


def test_44_target_history_does_not_enter_tt_identity():
    state = _state()
    tt = StrategicTranspositionTable()
    assert tt.admit(state, 2)
    assert not tt.admit(state.clone(), 2, heuristic_score=("target history",))


def test_45_lower_g_exact_state_dominance_unchanged():
    state = _state(); tt = StrategicTranspositionTable()
    assert tt.admit(state, 5) and tt.admit(state.clone(), 4) and not tt.admit(state.clone(), 6)


def test_46_admissible_h_unchanged():
    state = _state([], stock=[Card("h", 9)] * 10)
    a = build_incumbent_budget(state, spent_cost=2, incumbent_cost=100, heuristic_remaining_work=3)
    b = build_incumbent_budget(state, spent_cost=2, incumbent_cost=100, heuristic_remaining_work=99)
    assert a.admissible_remaining_lower_bound == b.admissible_remaining_lower_bound


def test_47_benchmark_suit_rank_column_constants_absent():
    source = "".join(
        (ROOT / "src/spider/planner" / name).read_text().lower()
        for name in ("anytime_controller.py", "milestone_actionability.py", "strategic_milestone.py")
    )
    assert "4925153" not in source and "column 7" not in source and "spade campaign" not in source


def test_48_cost21_route_absent_from_production_strategy():
    source = (ROOT / "src/spider/planner/anytime_controller.py").read_text().lower()
    assert "cost-21" not in source and "cost21" not in source


def test_49_canonical_future_actions_unavailable_prospectively():
    assert "canonical.moves" not in inspect.getsource(controller_module)


def test_50_external_119_absent_from_planning_policy():
    source = (ROOT / "src/spider/planner/milestone_actionability.py").read_text()
    assert "119" not in source


def test_51_unseen_deal_exercises_residual_remapping():
    cards = load_deal(DEAL)
    random.Random(107).shuffle(cards)
    state = SpiderState.from_cards(cards)
    config = AnytimeControllerConfig(
        enable_strategic_milestones=True,
        enable_tactical_resource_allocation=True,
    )
    before = analyze_strategic_state(
        state, cards, spent_cost=0, incumbent_cost=None, config=config,
        include_deal_timing=False,
    )
    target = next(
        item for item in before.milestone_portfolio.milestones
        if item.kind not in {StrategicMilestoneKind.EPOCH_TRANSITION, StrategicMilestoneKind.PRE_DEAL_PREPARATION}
    )
    identity = milestone_target_identity(target)
    state.deal(MW_RULES)
    after = analyze_strategic_state(
        state, cards, spent_cost=1, incumbent_cost=None, config=config,
        include_deal_timing=False,
    )
    residual = controller_module._residual_target_for_milestone(state, after, target, config)
    assert residual.identity == identity and residual.fresh_state_fingerprint


def test_52_diagnostic_separates_primitive_transition_substantial_completion():
    fields = controller_module.ControllerTelemetry.__dataclass_fields__
    assert {"primitive_results", "transition_checkpoints", "substantial_structural_milestones"} <= set(fields)
