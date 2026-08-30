from __future__ import annotations

import inspect
import random
from dataclasses import replace
from pathlib import Path

import pytest

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
import spider.planner.anytime_controller as controller_module
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    ControllerTelemetry,
    StrategicCreditLevel,
    StrategicSearchNode,
    StrategicSuccessor,
    StrategicTranspositionTable,
    analyze_strategic_state,
)
from spider.planner.campaign_dependency_closure import (
    CampaignDependencyType,
    ClosureCompletionClass,
    DependencyClosureConfig,
    build_campaign_dependency_graph,
    realize_campaign_dependency_closure,
)
from spider.planner.foundation_campaign import (
    CampaignReadiness,
    RankSource,
    RankSourceKind,
)
from spider.planner.milestone_actionability import (
    MilestoneBlockerKind,
    derive_residual_milestone_target,
)
from spider.planner.milestone_conversion import MilestonePrimitiveStep
from spider.planner.source_completion import (
    PhysicalSourceIdentity,
    SemanticSourceRequirement,
    SourceCompletionDisposition,
    SourceCompletionLedger,
    SourceCompletionLossReason,
    SourceCompletionPropagationTrace,
    SourceCompletionScope,
    SourceCompletionStage,
    SourceExpiryClassification,
    SourceRequirementReopeningReason,
    SourceRequirementSatisfactionState,
    classify_completion_loss,
    classify_source_expiry,
    physical_source_identity,
    reconcile_source_satisfaction,
    semantic_source_requirement,
    source_completion_event,
    source_state_hash,
)
from spider.planner.strategic_milestone import (
    MilestonePredicateKind,
    MilestoneTargetPredicate,
    StrategicMilestone,
    StrategicMilestoneKind,
    StrategicMilestoneProgress,
    StrategicMilestoneStatus,
    milestone_target_identity,
)
from spider.planner.tactical_resource_allocator import (
    TacticalResourceAllocatorConfig,
    TacticalResourceTier,
)
from spider.planner.target_grant_lineage import (
    TargetCommitmentEvidence,
    TargetCommitmentStatus,
    new_target_lineage_entry,
    record_lineage_source_completion,
)
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key, states_structurally_equal


ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"


def _columns(*face_up):
    columns = [Column([], list(cards)) for cards in face_up]
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return columns


def _source(suit: str, rank: int) -> RankSource:
    return RankSource(
        f"fixture:{suit}:{rank}", Card(suit, rank), RankSourceKind.SHALLOW_TABLEAU,
        0, "face_up", 1, None, None, True, False, 1, 0, (), False, False,
        "not_applicable", 1.0, "generic v0.14 source fixture",
    )


@pytest.fixture(scope="module")
def base_campaign():
    cards = tuple(load_deal(DEAL))
    state = SpiderState.from_cards(cards)
    config = AnytimeControllerConfig(
        wall_clock_limit_s=2.0,
        max_strategic_expansions=1,
        max_tactical_nodes=100,
        max_frontier_size=16,
        enable_campaign_edges=False,
        enable_expensive_deal_timing=False,
    )
    analysis = analyze_strategic_state(
        state, cards, spent_cost=0, incumbent_cost=None, config=config,
        include_deal_timing=False,
    )
    return analysis.economic.campaign_portfolio.campaigns[0]


def _campaign(base, suit="c", rank=5):
    needs = tuple(
        replace(
            need,
            chosen=_source(suit, need.rank) if need.rank == rank else None,
            must_excavate=need.rank == rank,
            reason="generic named source",
        )
        for need in base.rank_needs
    )
    return replace(
        base,
        suit=suit,
        current_epoch=5,
        target_removal_epoch=5,
        rank_needs=needs,
        tableau_critical_cards=tuple(item.chosen for item in needs if item.chosen),
        future_stock_supplied_cards=(),
        optional_replaceable_buried_copies=(),
        prerequisite_excavation_projects=(),
        shared_prerequisite_tasks=(),
        space_requirement=0,
        stock_plan=(),
        estimated_campaign_cost=4.0,
        blockers=(),
        readiness=CampaignReadiness.ASSEMBLY_LED,
    )


@pytest.fixture(scope="module")
def exposure_case(base_campaign):
    state = SpiderState(
        _columns(
            [Card("c", 5), Card("d", 5), Card("h", 4)],
            [Card("s", 5)],
            [Card("d", 6)],
            *([Card("h", 1)] for _ in range(7)),
        ),
        [],
    )
    campaign = _campaign(base_campaign)
    target = ("generic-source-chain", campaign.label, "SOURCE_CHAIN")
    result = realize_campaign_dependency_closure(
        state,
        campaign,
        target_dependency_id="source:5:c",
        semantic_target_id=target,
        config=DependencyClosureConfig(
            max_added_cost=8,
            max_nodes=400,
            time_limit_s=1.5,
            beam_width=192,
            enable_legal_candidate_audit=True,
        ),
    )
    return state, campaign, target, result


def _milestone(state, campaign):
    return StrategicMilestone(
        "v014-source-chain",
        canonical_state_key(state),
        "generic-source-chain",
        campaign.label,
        StrategicMilestoneKind.SOURCE_CHAIN,
        MilestoneTargetPredicate(
            MilestonePredicateKind.DEPENDENCIES_CLOSED,
            "close a generic source requirement",
            suit="c",
            dependency_ids=("source:5:c",),
        ),
        "c",
        (5,),
        (),
        (),
        StrategicMilestoneProgress(0, 1, ("source:5:c",)),
        2,
        4,
        3,
        4.0,
        12_000,
        "the scoped source chain closes",
        "fresh exact state invalidates the source chain",
        None,
        target_identity=None,
    )


def _simple_requirement(state, *, copies=1):
    return semantic_source_requirement(
        ("generic", "source-chain"),
        "source:5:c",
        Card("c", 5),
        copies_required=copies,
    )


def _simple_event(state, *, actionable=True, consumed=False, integrated=False):
    requirement = _simple_requirement(state)
    physical = physical_source_identity(
        Card("c", 5), dependency_id="source:5:c", copy_ordinal=1,
        zone="face_up", column=0, offset=0, face_up=True, blocker_depth=0,
        consumed=consumed, integrated=integrated,
    )
    return source_completion_event(
        semantic_target_fingerprint=requirement.semantic_target_fingerprint,
        dependency_id=requirement.dependency_id,
        original_dependency_type="SOURCE_BURIED",
        fresh_dependency_type="SOURCE_EXPOSED_BUT_BLOCKED",
        physical_source=physical,
        requirement=requirement,
        state=state,
        actions=(),
        completion_class="SOURCE_EXPOSED",
        source_depth_before=1,
        source_depth_after=0,
        exposed=True,
        actionable=actionable,
        consumed=consumed,
        integrated=integrated,
        evidence_provenance=("fresh physical analysis",),
    )


def test_01_unrestricted_deal_is_on():
    assert MW_RULES.can_deal_into_empty is True


def test_02_deal_into_empty_remains_legal():
    state = SpiderState(_columns(*([Card("c", 13)] for _ in range(9)), []), [Card("h", 1)] * 10)
    state.deal(MW_RULES)
    assert not state.stock


def test_03_canonical_anchor_counts():
    result = validate_solution("4925153", ROOT / "solutions" / "4925153_canonical.moves")
    assert (result.mobilityware_moves, result.explicit_commands, result.tableau_moves) == (172, 174, 169)


def test_04_canonical_anchor_hashes():
    result = validate_solution("4925153", ROOT / "solutions" / "4925153_canonical.moves")
    assert (result.stock_deals, result.foundations, result.path_hash, result.state_hash) == (5, 8, "77d169da2538ba8c", "4e9861540eac570cb")


def test_05_physical_identity_excludes_column():
    a = physical_source_identity(Card("c", 5), dependency_id="source:5:c", copy_ordinal=1, zone="face_up", column=1, offset=0, face_up=True, blocker_depth=0)
    b = replace(a, current_column=8, current_offset=4)
    assert a.identity_key == b.identity_key and a.location != b.location


def test_06_physical_identity_is_not_state_identity():
    state = SpiderState(_columns([Card("c", 5)]), [])
    before = canonical_state_key(state)
    _ = physical_source_identity(Card("c", 5), dependency_id="source:5:c", copy_ordinal=1, zone="face_up", column=0, offset=0, face_up=True, blocker_depth=0)
    assert canonical_state_key(state) == before


def test_07_gate_a_closure_emits_source_event(exposure_case):
    assert len(exposure_case[3].source_completion_events) == 1


def test_08_gate_a_event_is_buried_predicate(exposure_case):
    event = exposure_case[3].source_completion_events[0]
    assert event.scope == SourceCompletionScope.BURIED_PREDICATE


def test_09_gate_a_dependency_type_transition(exposure_case):
    event = exposure_case[3].source_completion_events[0]
    assert (event.original_dependency_type, event.fresh_dependency_type) == ("SOURCE_BURIED", "SOURCE_EXPOSED_BUT_BLOCKED")


def test_10_gate_a_buried_predicate_completed(exposure_case):
    result = exposure_case[3]
    assert result.endpoint_assessment.requested_dependency_completed
    assert result.completion_class == ClosureCompletionClass.SOURCE_EXPOSED


def test_11_gate_a_follow_on_blocker_remains(exposure_case):
    result = exposure_case[3]
    dependency = next(item for item in result.graph_after.dependencies if item.dependency_id == "source:5:c")
    assert dependency.kind == CampaignDependencyType.SOURCE_EXPOSED_BUT_BLOCKED


def test_12_gate_a_event_has_exact_state(exposure_case):
    event = exposure_case[3].source_completion_events[0]
    assert event.exact_state_key == canonical_state_key(exposure_case[3].end_state)


def test_13_gate_a_event_replay_provenance(exposure_case):
    start, _campaign_value, _target, result = exposure_case
    replay = start.clone()
    assert replay_actions(replay, list(result.actions)) == result.corrected_added_cost
    assert states_structurally_equal(replay, result.end_state)


def test_14_gate_b_same_state_exposure_is_monotone(exposure_case):
    event = exposure_case[3].source_completion_events[0]
    fresh = reconcile_source_satisfaction(exposure_case[3].end_state, event.requirement, event.satisfaction, current_dependency_type=event.fresh_dependency_type)
    assert fresh.state in {SourceRequirementSatisfactionState.EXPOSED, SourceRequirementSatisfactionState.ACTIONABLE, SourceRequirementSatisfactionState.INTEGRATED}
    assert fresh.fresh_reanalysis_preserved


def test_15_gate_b_same_state_hash_is_stable(exposure_case):
    event = exposure_case[3].source_completion_events[0]
    assert source_state_hash(exposure_case[3].end_state) == event.exact_state_hash


def test_16_consumed_same_state_is_monotone():
    state = SpiderState(_columns([Card("c", 6), Card("c", 5)]), [])
    event = _simple_event(state, consumed=True, integrated=True)
    fresh = reconcile_source_satisfaction(state, event.requirement, event.satisfaction)
    assert fresh.state == SourceRequirementSatisfactionState.INTEGRATED


def test_17_gate_c_copy_reassignment_preserves_one_copy():
    state = SpiderState(_columns([Card("c", 5)], [Card("c", 5)]), [])
    prior = reconcile_source_satisfaction(state, _simple_requirement(state))
    prior = replace(prior, satisfying_sources=(replace(prior.satisfying_sources[0], current_column=1),))
    fresh = reconcile_source_satisfaction(state, prior.requirement, prior)
    assert fresh.satisfied and fresh.copy_reassigned


def test_18_gate_c_two_copy_requirement_is_distinct():
    state = SpiderState(_columns([Card("c", 5)]), [])
    fresh = reconcile_source_satisfaction(state, _simple_requirement(state, copies=2))
    assert fresh.state == SourceRequirementSatisfactionState.PARTIALLY_SATISFIED


def test_19_gate_c_preference_change_does_not_erase_fact():
    state = SpiderState(_columns([Card("c", 5)], [Card("c", 5)]), [])
    fresh = reconcile_source_satisfaction(state, _simple_requirement(state))
    assert fresh.first_satisfied_state_hash == source_state_hash(state)


def test_20_gate_d_residual_preserves_buried_completion(exposure_case):
    _start, campaign, _target, result = exposure_case
    milestone = _milestone(result.end_state, campaign)
    graph = build_campaign_dependency_graph(result.end_state, campaign)
    event = result.source_completion_events[0]
    residual = derive_residual_milestone_target(result.end_state, milestone, graph=graph, prior_source_satisfactions=(event.satisfaction,))
    assert residual.source_satisfactions[0].fresh_reanalysis_preserved


def test_21_gate_d_follow_on_is_explicit(exposure_case):
    _start, campaign, _target, result = exposure_case
    residual = derive_residual_milestone_target(result.end_state, _milestone(result.end_state, campaign), graph=result.graph_after, prior_source_satisfactions=(result.source_completion_events[0].satisfaction,))
    assert MilestoneBlockerKind.EXPOSED_BLOCKED in residual.blockers


def test_22_gate_d_no_silent_reopening(exposure_case):
    _start, campaign, _target, result = exposure_case
    residual = derive_residual_milestone_target(result.end_state, _milestone(result.end_state, campaign), graph=result.graph_after, prior_source_satisfactions=(result.source_completion_events[0].satisfaction,))
    assert residual.source_reopenings == ()


def test_23_explicit_same_state_defect_is_named():
    state = SpiderState(_columns([Card("c", 5)]), [])
    prior = reconcile_source_satisfaction(state, _simple_requirement(state))
    contradictory = SpiderState(_columns([Card("d", 5)]), [])
    prior = replace(prior, current_state_hash=source_state_hash(contradictory))
    fresh = reconcile_source_satisfaction(contradictory, prior.requirement, prior)
    assert fresh.reopening_reason == SourceRequirementReopeningReason.ANALYSIS_DEFECT


def test_24_gate_e_successor_preserves_trace():
    state = SpiderState(_columns([Card("c", 5)]), [])
    trace = SourceCompletionPropagationTrace(_simple_event(state)).advance(SourceCompletionStage.CONTROLLER_SUCCESSOR_CREATED)
    successor = StrategicSuccessor(
        controller_module.StrategicActionKind.CAMPAIGN_DEPENDENCY_CLOSURE,
        "dependency_closure",
        "fixture",
        ((0, 1, 1),),
        1,
        state,
        StrategicCreditLevel.CLEAN,
        1,
        1,
        1,
        True,
        False,
        (),
        source_completion_traces=(trace,),
    )
    assert successor.source_completion_traces[0].successor_created


def test_25_gate_e_admitted_completion_is_deduplicated():
    state = SpiderState(_columns([Card("c", 5)]), [])
    trace = SourceCompletionPropagationTrace(_simple_event(state)).advance(SourceCompletionStage.CONTROLLER_ADMITTED_COMPLETION)
    telemetry = ControllerTelemetry()
    controller_module._record_source_completion_trace(telemetry, trace, 32)
    controller_module._record_source_completion_trace(telemetry, trace, 32)
    assert telemetry.source_controller_admitted_completions == 1


def test_26_gate_e_trimmed_completion_is_admission_loss():
    loss = classify_completion_loss(trace_completed=True, successor_created=True, controller_admitted=False, metadata_present=True, residual_preserved=False, attribution_preserved=True, strategically_trimmed=True)
    assert loss == SourceCompletionLossReason.STRATEGIC_ADMISSION_LOSS


def test_27_gate_f_selected_path_is_distinct():
    state = SpiderState(_columns([Card("c", 5)]), [])
    trace = SourceCompletionPropagationTrace(_simple_event(state)).advance(SourceCompletionStage.CONTROLLER_ADMITTED_COMPLETION)
    assert trace.controller_admitted and not trace.selected_path


def test_28_gate_f_selected_stage_can_be_added():
    state = SpiderState(_columns([Card("c", 5)]), [])
    trace = SourceCompletionPropagationTrace(_simple_event(state)).advance(SourceCompletionStage.SELECTED_PATH_COMPLETION)
    assert trace.selected_path


def test_29_gate_g_lineage_preserves_event(exposure_case):
    event = exposure_case[3].source_completion_events[0]
    entry = new_target_lineage_entry(event.semantic_target_fingerprint, canonical_state_key(exposure_case[0]), campaign_id="generic", objective_id="source", dependency_id=event.dependency_id, blocker_fingerprint="buried", blocker_kind="SOURCE_BURIED")
    updated = record_lineage_source_completion(entry, (event,))
    assert event.event_id in updated.source_completion_event_ids


def test_30_gate_g_lineage_keeps_follow_on(exposure_case):
    event = exposure_case[3].source_completion_events[0]
    entry = new_target_lineage_entry(event.semantic_target_fingerprint, canonical_state_key(exposure_case[0]), campaign_id="generic", objective_id="source", dependency_id=event.dependency_id, blocker_fingerprint="buried", blocker_kind="SOURCE_BURIED")
    updated = record_lineage_source_completion(entry, (event,))
    assert updated.follow_on_source_requirement_ids


def test_31_gate_g_completion_is_portable_harvest(exposure_case):
    event = exposure_case[3].source_completion_events[0]
    entry = new_target_lineage_entry(event.semantic_target_fingerprint, canonical_state_key(exposure_case[0]), campaign_id="generic", objective_id="source", dependency_id=event.dependency_id, blocker_fingerprint="buried", blocker_kind="SOURCE_BURIED")
    assert record_lineage_source_completion(entry, (event,)).evidence.has_portable_harvest


def test_32_gate_g_scoped_completion_does_not_complete_chain(exposure_case):
    event = exposure_case[3].source_completion_events[0]
    entry = new_target_lineage_entry(event.semantic_target_fingerprint, canonical_state_key(exposure_case[0]), campaign_id="generic", objective_id="source", dependency_id=event.dependency_id, blocker_fingerprint="buried", blocker_kind="SOURCE_BURIED")
    assert record_lineage_source_completion(entry, (event,)).status == TargetCommitmentStatus.NEW


def test_33_gate_h_true_reobstruction_is_explicit():
    state = SpiderState(_columns([Card("c", 5)], [Card("d", 4)]), [])
    prior = reconcile_source_satisfaction(state, _simple_requirement(state))
    state.move(1, 0, 1, rules=MW_RULES)
    fresh = reconcile_source_satisfaction(state, prior.requirement, prior, current_dependency_type="SOURCE_EXPOSED_BUT_BLOCKED")
    assert fresh.reopening_reason == SourceRequirementReopeningReason.SOURCE_BECAME_UNUSABLE


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"completed_before_expiry": True}, SourceExpiryClassification.COMPLETED_BEFORE_EXPIRY),
        ({}, SourceExpiryClassification.LEGITIMATE_NO_PROGRESS_EXPIRY),
        ({"resource_limited": True}, SourceExpiryClassification.RESOURCE_LIMIT_EXPIRY),
        ({"target_turnover": True}, SourceExpiryClassification.TARGET_TURNOVER_EXPIRY),
        ({"attribution_lost": True}, SourceExpiryClassification.ATTRIBUTION_LOSS_EXPIRY),
        ({"lifecycle_terminated": True}, SourceExpiryClassification.LIFECYCLE_EXPIRY),
        ({"superseded": True}, SourceExpiryClassification.SUPERSEDED_EXPIRY),
    ],
)
def test_34_gate_i_expiry_vocabulary(kwargs, expected):
    assert classify_source_expiry(**kwargs) == expected


def test_35_gate_i_persistence_limit_unchanged():
    assert AnytimeControllerConfig().milestone_max_strategic_expansions == 3


def test_36_gate_j_exposure_then_integration():
    exposed = SpiderState(_columns([Card("c", 5)]), [])
    prior = reconcile_source_satisfaction(exposed, _simple_requirement(exposed))
    integrated = SpiderState(_columns([Card("c", 6), Card("c", 5)]), [])
    fresh = reconcile_source_satisfaction(integrated, prior.requirement, prior)
    assert prior.state == SourceRequirementSatisfactionState.ACTIONABLE
    assert fresh.state == SourceRequirementSatisfactionState.INTEGRATED


def test_37_gate_j_primitive_preserves_event():
    state = SpiderState(_columns([Card("c", 5)]), [])
    event = _simple_event(state)
    step = MilestonePrimitiveStep((), state, 0, 0, (), True, "fixture", source_completion_events=(event,))
    assert step.source_completion_events == (event,)


def test_38_gate_k_lower_g_tt_dominance():
    state = SpiderState(_columns([Card("c", 5)]), [])
    table = StrategicTranspositionTable()
    assert table.admit(state, 5) and table.admit(state.clone(), 4)
    assert not table.admit(state.clone(), 6, heuristic_score=SourceCompletionLedger())


def test_39_gate_k_history_not_in_exact_identity():
    state = SpiderState(_columns([Card("c", 5)]), [])
    before = canonical_state_key(state)
    ledger = SourceCompletionLedger().with_trace(SourceCompletionPropagationTrace(_simple_event(state)))
    assert ledger.traces and canonical_state_key(state) == before


def test_40_gate_k_cheaper_node_can_reconstruct_satisfaction():
    state = SpiderState(_columns([Card("c", 5)]), [])
    fresh = reconcile_source_satisfaction(state, _simple_requirement(state), None)
    assert fresh.satisfied


def test_41_controller_propagation_loss_is_distinct():
    loss = classify_completion_loss(trace_completed=True, successor_created=True, controller_admitted=True, metadata_present=False, residual_preserved=False, attribution_preserved=True)
    assert loss == SourceCompletionLossReason.CONTROLLER_PROPAGATION_LOSS


def test_42_residual_reopening_loss_is_distinct():
    loss = classify_completion_loss(trace_completed=True, successor_created=True, controller_admitted=True, metadata_present=True, residual_preserved=False, attribution_preserved=True)
    assert loss == SourceCompletionLossReason.RESIDUAL_REOPENING


def test_43_attribution_loss_is_distinct():
    loss = classify_completion_loss(trace_completed=True, successor_created=True, controller_admitted=True, metadata_present=True, residual_preserved=True, attribution_preserved=False)
    assert loss == SourceCompletionLossReason.PHYSICAL_SOURCE_ATTRIBUTION_LOSS


def test_44_legitimate_rescope_is_distinct():
    loss = classify_completion_loss(trace_completed=True, successor_created=True, controller_admitted=True, metadata_present=True, residual_preserved=False, attribution_preserved=True, legitimate_rescope=True)
    assert loss == SourceCompletionLossReason.PORTFOLIO_REANALYSIS_RESCOPING


def test_45_tier_specs_unchanged():
    specs = TacticalResourceAllocatorConfig()
    assert [(specs.spec(t).max_added_cost, specs.spec(t).max_nodes, specs.spec(t).max_seconds) for t in TacticalResourceTier] == [(2, 128, 0.1), (4, 512, 0.35), (8, 2000, 1.25), (18, 8000, 2.0)]


def test_46_per_expansion_limits_unchanged():
    config = TacticalResourceAllocatorConfig()
    assert (config.max_granted_nodes_per_expansion, config.max_granted_seconds_per_expansion) == (12_000, 4.0)


def test_47_closure_limits_unchanged():
    config = AnytimeControllerConfig().dependency_closure_config
    assert (config.max_added_cost, config.max_nodes, config.time_limit_s) == (14, 4000, 2.0)


def test_48_closure_beam_is_192():
    assert AnytimeControllerConfig().dependency_closure_config.beam_width == 192


def test_49_raw_fallback_remains():
    source = inspect.getsource(controller_module.generate_strategic_successors)
    assert "raw_fallback" in source


def test_50_deal_remains():
    source = inspect.getsource(controller_module.generate_strategic_successors)
    assert "exact legal Deal fallback" in source and "purposeful Deal" in source


def test_51_late_construction_remains():
    assert AnytimeControllerConfig().enable_same_suit_construction


def test_52_no_benchmark_constants_in_source_policy():
    source = (ROOT / "src/spider/planner/source_completion.py").read_text()
    assert all(item not in source for item in ("4925153", "18843bfb94399fdb", "Spades"))


def test_53_no_external_119_in_source_policy():
    source = (ROOT / "src/spider/planner/source_completion.py").read_text()
    assert "119" not in source


def test_54_canonical_actions_unavailable_prospectively():
    source = (ROOT / "src/spider/planner/source_completion.py").read_text()
    assert "924bfd20deac96af" not in source and "77d169da2538ba8c" not in source


@pytest.mark.parametrize("seed", [14014, 14041])
def test_55_unseen_source_trace_is_exact_and_proof_neutral(seed):
    cards = list(load_deal(DEAL))
    random.Random(seed).shuffle(cards)
    state = SpiderState.from_cards(cards)
    card = state.columns[0].face_up[-1]
    requirement = semantic_source_requirement(("unseen", seed), f"source:{card.rank}:{card.suit}", card)
    physical = physical_source_identity(card, dependency_id=requirement.dependency_id, copy_ordinal=1, zone="face_up", column=0, offset=len(state.columns[0].face_up) - 1, face_up=True, blocker_depth=0)
    event = source_completion_event(semantic_target_fingerprint=requirement.semantic_target_fingerprint, dependency_id=requirement.dependency_id, original_dependency_type="SOURCE_BURIED", fresh_dependency_type="SOURCE_EXPOSED_BUT_BLOCKED", physical_source=physical, requirement=requirement, state=state, actions=(), completion_class="SOURCE_EXPOSED", source_depth_before=1, source_depth_after=0, exposed=True, actionable=False, consumed=False, integrated=False, evidence_provenance=("unseen exact-state smoke",))
    assert event.exact_state_key == canonical_state_key(state) and not event.proof_pruning_allowed


def test_56_diagnostic_funnel_fields_exist():
    fields = ControllerTelemetry.__dataclass_fields__
    assert {"source_trace_completions", "source_controller_admitted_completions", "source_selected_path_completions"} <= set(fields)


def test_57_satisfaction_vocabulary_complete():
    assert {item.value for item in SourceRequirementSatisfactionState} == {"UNSATISFIED", "PARTIALLY_SATISFIED", "EXPOSED", "ACTIONABLE", "CONSUMED", "INTEGRATED", "SUPERSEDED", "INVALIDATED"}


def test_58_reopening_vocabulary_complete():
    assert {item.value for item in SourceRequirementReopeningReason} == {"PHYSICAL_COPY_NO_LONGER_SATISFIES", "REQUIREMENT_SCOPE_CHANGED", "ADDITIONAL_COPY_REQUIRED", "SOURCE_BECAME_UNUSABLE", "SEMANTIC_REASSIGNMENT", "ANALYSIS_DEFECT"}


def test_59_trace_admitted_selected_are_distinct():
    state = SpiderState(_columns([Card("c", 5)]), [])
    trace = SourceCompletionPropagationTrace(_simple_event(state))
    admitted = trace.advance(SourceCompletionStage.CONTROLLER_ADMITTED_COMPLETION)
    selected = admitted.advance(SourceCompletionStage.SELECTED_PATH_COMPLETION)
    assert not trace.controller_admitted and admitted.controller_admitted and not admitted.selected_path and selected.selected_path


def test_60_all_completion_context_is_proof_neutral():
    state = SpiderState(_columns([Card("c", 5)]), [])
    event = _simple_event(state)
    trace = SourceCompletionPropagationTrace(event)
    assert not event.proof_pruning_allowed and not trace.proof_pruning_allowed and not event.requirement.proof_pruning_allowed


def test_61_repeated_early_observation_cannot_erase_later_stage():
    state = SpiderState(_columns([Card("c", 5)]), [])
    early = SourceCompletionPropagationTrace(_simple_event(state))
    admitted = early.advance(SourceCompletionStage.CONTROLLER_ADMITTED_COMPLETION)
    telemetry = ControllerTelemetry()
    controller_module._record_source_completion_trace(telemetry, admitted, 32)
    controller_module._record_source_completion_trace(telemetry, early, 32)
    stored = telemetry.source_completion_traces[0]
    assert stored.controller_admitted
    assert telemetry.source_trace_completions == 1
    assert telemetry.source_controller_admitted_completions == 1


def test_62_later_admission_resolves_transient_admission_loss():
    state = SpiderState(_columns([Card("c", 5)]), [])
    early = SourceCompletionPropagationTrace(_simple_event(state))
    lost = replace(
        early.advance(SourceCompletionStage.CONTROLLER_SUCCESSOR_CREATED),
        loss_reason=SourceCompletionLossReason.STRATEGIC_ADMISSION_LOSS,
    )
    admitted = early.advance(SourceCompletionStage.CONTROLLER_ADMITTED_COMPLETION)
    telemetry = ControllerTelemetry()
    controller_module._record_source_completion_trace(telemetry, lost, 32)
    controller_module._record_source_completion_trace(telemetry, admitted, 32)
    assert telemetry.source_completion_traces[0].controller_admitted
    assert telemetry.source_completion_traces[0].loss_reason is None
    assert telemetry.source_completion_loss_classifications == {}


def test_63_ledger_merge_cannot_erase_admission():
    state = SpiderState(_columns([Card("c", 5)]), [])
    early = SourceCompletionPropagationTrace(_simple_event(state))
    ledger = SourceCompletionLedger().with_trace(
        early.advance(SourceCompletionStage.CONTROLLER_ADMITTED_COMPLETION)
    )
    ledger = ledger.with_trace(early)
    assert ledger.traces[0].controller_admitted


def test_64_foundation_consumption_reconstructs_as_integrated():
    sequence = tuple(Card("c", rank) for rank in range(13, 0, -1))
    state = SpiderState(_columns(), [], [sequence])
    satisfaction = reconcile_source_satisfaction(state, _simple_requirement(state))
    assert satisfaction.state == SourceRequirementSatisfactionState.INTEGRATED
    assert satisfaction.satisfying_sources[0].current_zone == "foundation"


def test_65_unadmitted_successor_has_explicit_loss_at_funnel_end():
    state = SpiderState(_columns([Card("c", 5)]), [])
    trace = SourceCompletionPropagationTrace(_simple_event(state)).advance(
        SourceCompletionStage.CONTROLLER_SUCCESSOR_CREATED
    )
    telemetry = ControllerTelemetry()
    controller_module._record_source_completion_trace(telemetry, trace, 32)
    lost = replace(
        trace,
        disposition=SourceCompletionDisposition.ADMISSION_LOSS,
        loss_reason=SourceCompletionLossReason.STRATEGIC_ADMISSION_LOSS,
    )
    controller_module._record_source_completion_trace(telemetry, lost, 32)
    assert telemetry.source_completion_loss_classifications == {
        SourceCompletionLossReason.STRATEGIC_ADMISSION_LOSS.value: 1
    }
