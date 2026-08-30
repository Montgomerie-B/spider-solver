"""v0.11 buried-source closure candidate audit and completion gates."""

from dataclasses import replace
from pathlib import Path

import pytest

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.move_lifecycle import (
    BoundedCompensatingBenefit,
    PlacementClass,
    assess_tableau_move,
    stable_join_dominates,
    with_bounded_compensation,
)
from spider.planner.anytime_controller import AnytimeControllerConfig, analyze_strategic_state, freeze_active_rule_profile
from spider.planner.buried_source_closure import (
    ClosureCandidateRejectionReason,
    ClosureFailureDiagnosis,
    ClosureProgressKind,
    compare_legal_candidate_coverage,
    describe_buried_source,
    physical_source_alternatives,
)
from spider.planner.campaign_dependency_closure import (
    CampaignDependencyType,
    DependencyClosureConfig,
    DependencyClosureStatus,
    build_campaign_dependency_graph,
    realize_campaign_dependency_closure,
)
from spider.planner.foundation_campaign import CampaignReadiness, RankSource, RankSourceKind
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key


ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"


def _columns(*face_up):
    columns = [Column([], list(cards)) for cards in face_up]
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return columns


def _source(suit, rank):
    return RankSource(
        f"fixture:{suit}:{rank}", Card(suit, rank), RankSourceKind.SHALLOW_TABLEAU,
        0, "face_up", 1, None, None, True, False, 1, 0, (), False, False,
        "not_applicable", 1.0, "generic fixture",
    )


@pytest.fixture(scope="module")
def base_campaign():
    cards = tuple(load_deal(DEAL))
    state = SpiderState.from_cards(cards)
    config = AnytimeControllerConfig(
        wall_clock_limit_s=2.0, max_strategic_expansions=1,
        max_tactical_nodes=100, max_frontier_size=16,
        enable_campaign_edges=False, enable_expensive_deal_timing=False,
    )
    analysis = analyze_strategic_state(
        state, cards, spent_cost=0, incumbent_cost=None, config=config,
        include_deal_timing=False,
    )
    return analysis.economic.campaign_portfolio.campaigns[0]


def _campaign(base, suit="c", rank=5, space=0):
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
        base, suit=suit, current_epoch=5, target_removal_epoch=5,
        rank_needs=needs,
        tableau_critical_cards=tuple(n.chosen for n in needs if n.chosen),
        future_stock_supplied_cards=(), optional_replaceable_buried_copies=(),
        prerequisite_excavation_projects=(), shared_prerequisite_tasks=(),
        space_requirement=space, stock_plan=(), estimated_campaign_cost=4.0,
        blockers=(), readiness=CampaignReadiness.ASSEMBLY_LED,
    )


def _run(state, campaign, *, nodes=400, cost=8, beam=192, audit=True):
    return realize_campaign_dependency_closure(
        state, campaign, target_dependency_id=f"source:5:c",
        semantic_target_id="generic-source-chain",
        config=DependencyClosureConfig(
            max_added_cost=cost, max_nodes=nodes, time_limit_s=1.5,
            beam_width=beam, enable_legal_candidate_audit=audit,
        ),
    )


@pytest.fixture
def one_blocker(base_campaign):
    state = SpiderState(_columns(
        [Card("c", 5), Card("d", 4)], [Card("d", 5)], [Card("h", 6)],
        *([Card("h", 1)] for _ in range(7))), [])
    return state, _campaign(base_campaign)


@pytest.fixture
def receiver_case(base_campaign):
    state = SpiderState(_columns(
        [Card("c", 5), Card("d", 4)], [Card("h", 5), Card("s", 9)],
        [Card("s", 10)], [Card("h", 6)],
        *([Card("h", 1)] for _ in range(6))), [])
    return state, _campaign(base_campaign)


def test_01_unrestricted_deal_remains_on():
    assert MW_RULES.can_deal_into_empty


def test_02_rule_profile_is_unrestricted():
    cards = tuple(load_deal(DEAL))
    assert freeze_active_rule_profile(SpiderState.from_cards(cards), cards).profile.can_deal_into_empty


def test_03_canonical_anchor_unchanged():
    r = validate_solution("4925153", ROOT / "solutions" / "4925153_canonical.moves")
    assert (r.mobilityware_moves, r.explicit_commands, r.tableau_moves, r.stock_deals, r.foundations) == (172, 174, 169, 5, 8)


def test_04_canonical_anchor_hashes_unchanged():
    r = validate_solution("4925153", ROOT / "solutions" / "4925153_canonical.moves")
    assert (r.path_hash, r.state_hash) == ("77d169da2538ba8c", "4e9861540eac570cb")


def test_05_one_blocker_is_described(one_blocker):
    state, _ = one_blocker
    b = describe_buried_source(state, "source:5:c", Card("c", 5))
    assert b.source_depth == 1 and b.blocker_cards == (Card("d", 4),)


def test_06_one_blocker_legal_move_is_enumerated(one_blocker):
    state, _ = one_blocker
    b = describe_buried_source(state, "source:5:c", Card("c", 5))
    assert (0, 1, 1) in b.legal_blocker_moves


def test_07_one_blocker_source_closes(one_blocker):
    state, campaign = one_blocker
    r = _run(state, campaign)
    assert r.status == DependencyClosureStatus.DEPENDENCY_CLOSED


def test_08_one_blocker_replays(one_blocker):
    state, campaign = one_blocker
    r = _run(state, campaign)
    replay = state.clone()
    assert replay_actions(replay, list(r.actions)) == r.corrected_added_cost
    assert canonical_state_key(replay) == canonical_state_key(r.end_state)


def test_09_trace_has_exact_source(one_blocker):
    state, campaign = one_blocker
    t = _run(state, campaign).buried_source_traces[0]
    assert t.required_source == Card("c", 5) and t.target_dependency_id == "source:5:c"


def test_10_trace_has_semantic_identity(one_blocker):
    state, campaign = one_blocker
    assert _run(state, campaign).buried_source_traces[0].semantic_target_id == "generic-source-chain"


def test_11_two_blocker_run_exposes_source(base_campaign):
    state = SpiderState(_columns(
        [Card("c", 5), Card("d", 5), Card("d", 4)], [Card("d", 6)], [Card("h", 6)],
        *([Card("h", 1)] for _ in range(7))), [])
    r = _run(state, _campaign(base_campaign))
    assert r.status == DependencyClosureStatus.DEPENDENCY_CLOSED and r.actions[0] == (0, 1, 2)


def test_12_same_suit_blocker_run_moves_together(base_campaign):
    state = SpiderState(_columns([Card("c", 5), Card("d", 5), Card("d", 4)], [Card("d", 6)]), [])
    assert state.can_move(0, 1, 2)


def test_13_three_blockers_can_close(base_campaign):
    state = SpiderState(_columns(
        [Card("c", 5), Card("d", 6), Card("d", 5), Card("d", 4)],
        [Card("d", 7)], [Card("h", 6)], *([Card("h", 1)] for _ in range(7))), [])
    assert _run(state, _campaign(base_campaign)).status == DependencyClosureStatus.DEPENDENCY_CLOSED


def test_14_receiver_prerequisite_is_generated(receiver_case):
    state, campaign = receiver_case
    t = _run(state, campaign).buried_source_traces[0]
    assert (1, 2, 1) in t.generated_actions


def test_15_receiver_prerequisite_is_target_relevant(receiver_case):
    state, campaign = receiver_case
    t = _run(state, campaign).buried_source_traces[0]
    assert (1, 2, 1) in t.legal_target_relevant_actions


def test_16_receiver_creation_does_not_need_depth_reduction(receiver_case):
    state, campaign = receiver_case
    audits = _run(state, campaign).buried_source_traces[0].candidate_audits
    progress = next(a.progress for a in audits if a.action == (1, 2, 1) and a.progress)
    assert progress.receiver_created and progress.source_depth_after == progress.source_depth_before


def test_17_receiver_chain_closes_source(receiver_case):
    state, campaign = receiver_case
    r = _run(state, campaign)
    assert r.status == DependencyClosureStatus.DEPENDENCY_CLOSED
    assert r.actions[:2] == ((1, 2, 1), (0, 1, 1))


def test_18_receiver_chain_replays(receiver_case):
    state, campaign = receiver_case
    r = _run(state, campaign)
    replay = state.clone()
    assert replay_actions(replay, list(r.actions)) == r.corrected_added_cost


def test_19_legacy_missing_class_is_now_covered(receiver_case):
    state, campaign = receiver_case
    assert not _run(state, campaign).buried_source_traces[0].missing_from_generator


def test_20_source_progress_is_explicit(receiver_case):
    state, campaign = receiver_case
    kinds = {s.progress_evidence.kind for s in _run(state, campaign).steps if s.progress_evidence}
    assert ClosureProgressKind.RECEIVER_CREATED in kinds and ClosureProgressKind.SOURCE_CONSUMED in kinds


def test_21_copy_alternatives_are_coordinate_free(base_campaign):
    state = SpiderState(_columns([Card("c", 5), Card("d", 4)], [Card("c", 5)], [Card("h", 6)]), [])
    alternatives = physical_source_alternatives(state, Card("c", 5))
    assert len(alternatives) == 2 and alternatives[0].actionable


def test_22_target_context_is_not_state_identity(one_blocker):
    state, _ = one_blocker
    before = canonical_state_key(state)
    describe_buried_source(state, "arbitrary-semantic-name", Card("c", 5))
    assert canonical_state_key(state) == before


def test_23_exact_cache_separates_target_dependency(one_blocker):
    state, campaign = one_blocker
    cache = {}
    good = realize_campaign_dependency_closure(state, campaign, cache=cache, target_dependency_id="source:5:c")
    stale = realize_campaign_dependency_closure(state, campaign, cache=cache, target_dependency_id="source:6:c")
    assert good.status != stale.status and len(cache) == 2


def test_24_stale_target_is_typed(one_blocker):
    state, campaign = one_blocker
    r = realize_campaign_dependency_closure(state, campaign, target_dependency_id="source:6:c")
    assert r.status == DependencyClosureStatus.INVALIDATED


def test_25_structural_blocker_is_typed(base_campaign):
    state = SpiderState(_columns([Card("c", 5), Card("d", 13)], *([Card("h", 1)] for _ in range(9))), [])
    r = _run(state, _campaign(base_campaign), nodes=20, cost=2)
    assert r.failure_diagnosis in {ClosureFailureDiagnosis.STRUCTURAL_BLOCKER, ClosureFailureDiagnosis.SEARCH_POLICY}


def test_26_resource_exhaustion_is_typed(receiver_case):
    state, campaign = receiver_case
    r = _run(state, campaign, nodes=1)
    assert r.failure_diagnosis == ClosureFailureDiagnosis.RESOURCE_BOUND


def test_27_failure_has_no_proof_authority(receiver_case):
    state, campaign = receiver_case
    assert not _run(state, campaign, nodes=1).proof_pruning_allowed


def test_28_trace_has_no_proof_authority(receiver_case):
    state, campaign = receiver_case
    assert not _run(state, campaign, nodes=1).buried_source_traces[0].proof_pruning_allowed


def test_29_beam_width_default_unchanged():
    assert DependencyClosureConfig().beam_width == 192


def test_30_closure_resources_unchanged():
    c = DependencyClosureConfig()
    assert (c.max_added_cost, c.max_nodes, c.time_limit_s) == (14, 4000, 2.0)


def test_31_controller_envelopes_unchanged():
    c = AnytimeControllerConfig()
    assert (c.milestone_max_primitive_steps, c.milestone_max_strategic_expansions, c.milestone_max_time_s_per_expansion, c.milestone_max_nodes_per_expansion) == (4, 3, 4.0, 12000)


def test_32_audit_mode_is_off_in_production_default():
    assert not DependencyClosureConfig().enable_legal_candidate_audit


def test_33_audit_mode_does_not_change_route(one_blocker):
    state, campaign = one_blocker
    assert _run(state, campaign, audit=False).actions == _run(state, campaign, audit=True).actions


def test_34_lifecycle_debt_is_recorded(receiver_case):
    state, campaign = receiver_case
    assert all(step.lifecycle.estimated_rehandling_cost >= 0 for step in _run(state, campaign).steps)


def test_35_stable_join_dominates_equal_unexplained_park():
    state = SpiderState(_columns([Card("s", 9)], [Card("s", 10)], [Card("h", 10)]), [])
    stable = assess_tableau_move(state, (0, 1, 1))
    park = assess_tableau_move(state, (0, 2, 1))
    assert stable_join_dominates(stable, park, comparable_effects=True)


def test_36_unexplained_mixed_park_is_rejected(base_campaign):
    state = SpiderState(_columns(
        [Card("c", 5), Card("d", 4)], [Card("d", 5)],
        [Card("d", 2), Card("c", 9)], [Card("h", 10)],
        *([Card("h", 1)] for _ in range(6))), [])
    r = _run(state, _campaign(base_campaign), nodes=20)
    reasons = {a.rejection_reason for a in r.buried_source_traces[0].candidate_audits}
    assert ClosureCandidateRejectionReason.TEMPORARY_PARK_NO_EXIT in reasons


def test_37_beam_audit_is_present(receiver_case):
    state, campaign = receiver_case
    assert _run(state, campaign).buried_source_traces[0].beam_audits


def test_38_beam_audit_counts_retained(receiver_case):
    state, campaign = receiver_case
    assert _run(state, campaign).buried_source_traces[0].beam_audits[0].retained > 0


def test_39_target_progress_diversity_enabled():
    assert DependencyClosureConfig().retain_target_progress_diversity


def test_40_graph_rebuild_changes_source_kind(receiver_case):
    state, campaign = receiver_case
    r = _run(state, campaign)
    assert "source:5:c" in r.graph_before.dependency_ids and "source:5:c" not in r.graph_after.dependency_ids


@pytest.mark.parametrize("reason", list(ClosureCandidateRejectionReason))
def test_41_typed_rejection_vocabulary_is_explicit(reason):
    assert reason.value and reason.value != "NOT_SELECTED"


@pytest.mark.parametrize("kind", list(ClosureProgressKind))
def test_42_progress_vocabulary_is_explicit(kind):
    assert kind.value and not kind.value.startswith("BENCHMARK")


@pytest.mark.parametrize("token", ["4925153", "924bfd20", "b7522950", "Spades", "119"])
def test_43_no_benchmark_token_in_closure_policy(token):
    source = (ROOT / "src" / "spider" / "planner" / "campaign_dependency_closure.py").read_text()
    assert token not in source


@pytest.mark.parametrize("field", [
    "source_buried_attempts", "source_physical_blockers", "source_copies_considered",
    "closure_candidates_generated", "closure_candidates_admitted",
    "closure_beam_retained", "closure_beam_discarded", "closure_lifecycle_debt",
])
def test_44_controller_candidate_telemetry_exists(field):
    from spider.planner.anytime_controller import ControllerTelemetry
    assert hasattr(ControllerTelemetry(), field)


def test_45_candidate_audits_record_lifecycle(receiver_case):
    state, campaign = receiver_case
    assert any(a.lifecycle is not None for a in _run(state, campaign).buried_source_traces[0].candidate_audits)


def test_46_candidate_audits_record_admission(receiver_case):
    state, campaign = receiver_case
    assert any(a.disposition.value == "ADMITTED" for a in _run(state, campaign).buried_source_traces[0].candidate_audits)


def test_47_direct_progress_records_depth_change(one_blocker):
    state, campaign = one_blocker
    p = _run(state, campaign).steps[0].progress_evidence
    assert p.source_depth_after < p.source_depth_before


def test_48_source_actionability_is_recorded(one_blocker):
    state, campaign = one_blocker
    p = _run(state, campaign).steps[0].progress_evidence
    assert p.source_consumed or p.source_actionable or p.source_exposed


def test_49_result_names_target_dependency(one_blocker):
    state, campaign = one_blocker
    assert _run(state, campaign).target_dependency_id == "source:5:c"


def test_50_local_miss_does_not_deal(one_blocker):
    state, campaign = one_blocker
    assert ("deal",) not in _run(state, campaign).actions


def test_51_deal_remains_legal_with_empty_columns():
    row = [Card("h", rank) for rank in range(1, 11)]
    state = SpiderState(_columns(*([Card("s", 13)] for _ in range(9))), row)
    assert state.can_deal(MW_RULES)


def test_52_exact_state_key_ignores_trace(one_blocker):
    state, campaign = one_blocker
    before = canonical_state_key(state)
    _run(state, campaign)
    assert canonical_state_key(state) == before


def test_53_success_trace_outcome_is_typed(one_blocker):
    state, campaign = one_blocker
    assert _run(state, campaign).buried_source_traces[0].outcome == "DEPENDENCY_CLOSED"


def test_54_success_diagnosis_is_none(one_blocker):
    state, campaign = one_blocker
    assert _run(state, campaign).failure_diagnosis == ClosureFailureDiagnosis.NONE


def test_55_independent_audit_is_bounded(receiver_case):
    state, campaign = receiver_case
    r = _run(state, campaign)
    assert len(r.buried_source_traces[0].candidate_audits) <= 2048


def test_56_workspace_prerequisite_is_admitted(base_campaign):
    state = SpiderState(_columns(
        [Card("c", 5), Card("d", 4)], [Card("s", 9)], [Card("s", 10)],
        [Card("h", 6)], *([Card("h", 1)] for _ in range(6))), [])
    r = _run(state, _campaign(base_campaign))
    assert r.status == DependencyClosureStatus.DEPENDENCY_CLOSED
    assert r.steps[0].progress_evidence.workspace_created


def test_57_workspace_is_used_to_remove_blocker(base_campaign):
    state = SpiderState(_columns(
        [Card("c", 5), Card("d", 4)], [Card("s", 9)], [Card("s", 10)],
        [Card("h", 6)], *([Card("h", 1)] for _ in range(6))), [])
    r = _run(state, _campaign(base_campaign))
    assert r.actions[:2] == ((1, 2, 1), (0, 1, 1))


def test_58_bounded_temporary_park_survives(base_campaign):
    state = SpiderState(_columns(
        [Card("c", 5), Card("d", 4)], [Card("h", 5)], [Card("h", 6)],
        *([Card("h", 1)] for _ in range(7))), [])
    r = _run(state, _campaign(base_campaign))
    assert r.status == DependencyClosureStatus.DEPENDENCY_CLOSED
    assert r.steps[0].lifecycle.placement_class == PlacementClass.MIXED_SUIT_PARK
    assert r.steps[0].lifecycle.exit_route_bounded


def test_59_bounded_park_has_compensating_benefit(base_campaign):
    state = SpiderState(_columns(
        [Card("c", 5), Card("d", 4)], [Card("h", 5)], [Card("h", 6)],
        *([Card("h", 1)] for _ in range(7))), [])
    lifecycle = _run(state, _campaign(base_campaign)).steps[0].lifecycle
    assert lifecycle.future_exit_route and lifecycle.estimated_rehandling_cost > 0


def test_60_stable_run_break_can_be_compensated(base_campaign):
    state = SpiderState(_columns(
        [Card("c", 5), Card("d", 4)], [Card("s", 5), Card("s", 4)],
        [Card("h", 5)], [Card("h", 6)], *([Card("h", 1)] for _ in range(6))), [])
    lifecycle = assess_tableau_move(state, (1, 2, 1))
    lifecycle = with_bounded_compensation(
        lifecycle,
        BoundedCompensatingBenefit(
            lifecycle.estimated_rehandling_cost + 2,
            "fresh source chain gains a required receiver",
            "bounded restoration to the exposed same-suit lower card",
        ),
    )
    assert lifecycle.same_suit_joins_broken and lifecycle.exit_route_bounded
    assert lifecycle.can_override_permanent_join


def test_61_copy_substitution_is_fresh(base_campaign):
    state = SpiderState(_columns(
        [Card("c", 5), Card("d", 4)], [Card("c", 5), Card("s", 9)],
        [Card("s", 10)], [Card("h", 6)], *([Card("h", 1)] for _ in range(6))), [])
    r = _run(state, _campaign(base_campaign))
    assert r.status == DependencyClosureStatus.DEPENDENCY_CLOSED
    assert r.buried_source_traces[0].source_copy_substitutions >= 1


def test_62_width_one_retains_receiver_progress(receiver_case):
    state, campaign = receiver_case
    r = _run(state, campaign, beam=1)
    assert r.actions and r.actions[0] == (1, 2, 1)


def test_63_width_one_is_not_increased(receiver_case):
    state, campaign = receiver_case
    r = _run(state, campaign, beam=1)
    assert all(item.retained <= 1 for item in r.buried_source_traces[0].beam_audits)


def test_64_independent_coverage_audit_detects_missing_generator_class():
    audit = compare_legal_candidate_coverage(
        "source:5:c", ((1, 2, 1), (0, 1, 1)), ((0, 1, 1),)
    )
    assert audit.missing_from_generator == ((1, 2, 1),)
    assert audit.failure_diagnosis == ClosureFailureDiagnosis.SEARCH_POLICY
    assert not audit.coverage_complete and not audit.proof_pruning_allowed


def test_65_independent_coverage_audit_accepts_complete_generator():
    actions = ((1, 2, 1), (0, 1, 1))
    audit = compare_legal_candidate_coverage("source:5:c", actions, actions)
    assert audit.coverage_complete and not audit.missing_from_generator
    assert audit.failure_diagnosis == ClosureFailureDiagnosis.NONE
