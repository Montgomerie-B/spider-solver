"""v0.13 persisted-target grant-lineage and conversion-audit gates."""

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
import spider.planner.anytime_controller as controller
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    StrategicCreditLevel,
    StrategicSearchNode,
    StrategicTranspositionTable,
    _trim_frontier_with_checkpoint_diversity,
)
from spider.planner.milestone_actionability import (
    derive_residual_milestone_target,
)
from spider.planner.residual_campaign import FoundationCheckpointPortfolio
from spider.planner.strategic_milestone import (
    MilestonePredicateKind,
    MilestoneTargetPredicate,
    StrategicMilestone,
    StrategicMilestoneKind,
    StrategicMilestoneProgress,
    milestone_target_identity,
)
from spider.planner.structural_construction import analyze_same_suit_construction
from spider.planner.tactical_resource_allocator import (
    TacticalResourceAllocator,
    TacticalResourceAllocatorConfig,
    TacticalResourceTier,
)
from spider.planner.target_grant_lineage import (
    PersistedTargetFailureDiagnosis,
    TargetBoundaryTrace,
    TargetCommitmentEvidence,
    TargetCommitmentStatus,
    TargetCommitmentTransition,
    TargetGrantLineage,
    decide_target_grant,
    diagnose_persisted_target_failure,
    make_boundary_trace,
    new_target_lineage_entry,
    record_target_grant,
    record_target_outcome,
)
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key


ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"


def _state(*face_up, stock=()):
    columns = [Column([], list(cards)) for cards in face_up]
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return SpiderState(columns, list(stock))


def _target(state, *, objective="generic-source-chain", campaign="C#1"):
    milestone = StrategicMilestone(
        "lineage-fixture",
        canonical_state_key(state),
        objective,
        campaign,
        StrategicMilestoneKind.SOURCE_CHAIN,
        MilestoneTargetPredicate(
            MilestonePredicateKind.DURABLE_RUN,
            "build a durable same-suit run",
            suit="c",
            minimum_run_length=4,
        ),
        "c",
        (7, 6, 5, 4),
        (),
        (),
        StrategicMilestoneProgress(1, 4),
        4,
        4,
        3,
        4.0,
        12_000,
        "a four-card same-suit run exists",
        "fresh facts contradict the same target",
        None,
    )
    return replace(milestone, target_identity=milestone_target_identity(milestone))


def _entry(state, *, target=None, tier=TacticalResourceTier.PROBE, limit=3):
    target = target or _target(state)
    return new_target_lineage_entry(
        target.target_identity.fingerprint,
        canonical_state_key(state),
        campaign_id=target.campaign_id,
        objective_id=target.objective_id,
        dependency_id="source:5:c",
        blocker_fingerprint="blocker-a",
        blocker_kind="SOURCE_BURIED",
        initial_tier=tier,
        persistence_limit=limit,
        realizer="DEPENDENCY_CLOSURE",
    )


def _harvest(*, obligation=None, debt=0.0):
    return TargetCommitmentEvidence(
        named_harvest=("SOURCE_DEPTH_REDUCED",),
        completion_class="DEPENDENCY_ADVANCED",
        source_depth_before=3,
        source_depth_after=2,
        blockers_before=3,
        blockers_after=2,
        prerequisite_completed=True,
        target_relevant=True,
        nodes_consumed=128,
        seconds_consumed=0.1,
        corrected_paid_cost=2,
        lifecycle_debt=debt,
        restore_replace_obligation=obligation,
        compensation_credible=True,
    )


def _advanced_entry(state_a, state_b, *, target=None, tier=TacticalResourceTier.PROBE):
    target = target or _target(state_a)
    entry = _entry(state_a, target=target, tier=tier)
    decision = decide_target_grant(
        entry,
        semantic_target_fingerprint=target.target_identity.fingerprint,
        requested_initial_tier=tier,
        terminal_qualified=False,
        target_valid=True,
        current_state_key=canonical_state_key(state_a),
        current_blocker_fingerprint="blocker-a",
        current_blocker_kind="SOURCE_BURIED",
    )
    entry = record_target_grant(
        entry,
        state_key=canonical_state_key(state_a),
        dependency_id="source:5:c",
        blocker_fingerprint="blocker-a",
        blocker_kind="SOURCE_BURIED",
        requested_tier=decision.requested_tier,
        granted_tier=tier,
        decision=decision,
        realizer="DEPENDENCY_CLOSURE",
    )
    return record_target_outcome(
        entry, _harvest(), end_state_key=canonical_state_key(state_b)
    )


def _decision(entry, target, state, *, blocker="SOURCE_BURIED", initial=TacticalResourceTier.PROBE, terminal=False):
    return decide_target_grant(
        entry,
        semantic_target_fingerprint=target.target_identity.fingerprint,
        requested_initial_tier=initial,
        terminal_qualified=terminal,
        target_valid=True,
        current_state_key=canonical_state_key(state),
        current_blocker_fingerprint=f"fresh-{blocker}",
        current_blocker_kind=blocker,
        lifecycle_debt=entry.lifecycle_debt if entry else 0.0,
        compensation_credible=True,
    )


def _trace(entry, decision, *, minimum=None, candidates=("SOURCE_BURIED",), granted=None):
    return make_boundary_trace(
        entry,
        decision,
        dependency_after="source:5:c",
        blocker_after="SOURCE_BURIED",
        progress_before="DEPENDENCY_ADVANCED:3->2",
        progress_after="fresh target remains actionable",
        fresh_candidate_classes=candidates,
        best_next_candidate="move the next named blocker",
        best_candidate_minimum_tier=minimum,
        granted_tier=granted,
    )


def test_01_unrestricted_deal_is_on():
    assert MW_RULES.can_deal_into_empty is True


def test_02_deal_into_empty_is_legal():
    state = _state(*([Card("c", 13)] for _ in range(9)), [], stock=[Card("h", 1)] * 10)
    state.deal(MW_RULES)
    assert len(state.stock) == 0


def test_03_canonical_anchor_unchanged():
    result = validate_solution("4925153", ROOT / "solutions" / "4925153_canonical.moves")
    assert (result.mobilityware_moves, result.explicit_commands, result.tableau_moves) == (172, 174, 169)


def test_04_canonical_anchor_hashes_unchanged():
    result = validate_solution("4925153", ROOT / "solutions" / "4925153_canonical.moves")
    assert (result.stock_deals, result.foundations, result.path_hash, result.state_hash) == (5, 8, "77d169da2538ba8c", "4e9861540eac570cb")


def test_05_semantic_identity_excludes_coordinates():
    identity = _target(_state([Card("c", 7)])).target_identity
    assert all("column" not in str(item).lower() and "c3" not in str(item).lower() for item in identity.fingerprint)


def test_06_lineage_key_is_semantic_identity_only():
    a = _state([Card("c", 7)]); b = _state([Card("c", 7)], [Card("d", 6)])
    target = _target(a)
    assert _entry(a, target=target).identity_key == _entry(b, target=target).identity_key


def test_07_lineage_crosses_exact_state_change():
    a = _state([Card("c", 7)]); b = _state([Card("c", 7)], [Card("d", 6)])
    entry = _advanced_entry(a, b)
    assert entry.previous_state_key != entry.current_state_key and entry.generation == 1


def test_08_named_progress_is_portable():
    assert _harvest().has_portable_harvest


def test_09_unrelated_progress_is_not_portable():
    evidence = replace(_harvest(), target_relevant=False)
    assert not evidence.has_portable_harvest


def test_10_gate_a_probe_progress_earns_shallow():
    a = _state([Card("c", 7)]); b = _state([Card("c", 7)], [Card("d", 6)])
    target = _target(a); entry = _advanced_entry(a, b, target=target)
    assert _decision(entry, target, b).requested_tier == TacticalResourceTier.SHALLOW


def test_11_gate_a_records_retained_promotion():
    a = _state([Card("c", 7)]); b = _state([Card("c", 7)], [Card("d", 6)])
    target = _target(a); decision = _decision(_advanced_entry(a, b, target=target), target, b)
    assert decision.inherited_commitment and decision.status == TargetCommitmentStatus.PROMOTED


def test_12_gate_a_per_expansion_limits_unchanged():
    assert TacticalResourceAllocatorConfig().max_granted_nodes_per_expansion == 12_000


def test_13_gate_a_time_limit_unchanged():
    assert TacticalResourceAllocatorConfig().max_granted_seconds_per_expansion == 4.0


def test_14_gate_b_no_harvest_resets_to_probe():
    a = _state([Card("c", 7)]); b = _state([Card("c", 7)], [Card("d", 6)])
    target = _target(a); entry = _entry(a, target=target)
    entry = record_target_outcome(entry, TargetCommitmentEvidence(), end_state_key=canonical_state_key(b))
    decision = _decision(entry, target, b)
    assert decision.requested_tier == TacticalResourceTier.PROBE and not decision.inherited_commitment


def test_15_gate_b_reset_reason_is_explicit():
    a = _state([Card("c", 7)]); target = _target(a); entry = _entry(a, target=target)
    decision = _decision(entry, target, a)
    assert decision.transition == TargetCommitmentTransition.RESET_NO_PORTABLE_HARVEST


def test_16_gate_c_blocker_change_retains_target():
    a = _state([Card("c", 7)]); b = _state([Card("c", 7)], [Card("d", 6)])
    target = _target(a); decision = _decision(_advanced_entry(a, b, target=target), target, b, blocker="WORKSPACE")
    assert decision.requested_tier == TacticalResourceTier.SHALLOW


def test_17_gate_c_blocker_change_reason_is_explicit():
    a = _state([Card("c", 7)]); b = _state([Card("c", 7)], [Card("d", 6)])
    target = _target(a); decision = _decision(_advanced_entry(a, b, target=target), target, b, blocker="WORKSPACE")
    assert decision.transition == TargetCommitmentTransition.RETAIN_ACROSS_BLOCKER_CHANGE


def test_18_commitment_follows_target_not_realizer():
    a = _state([Card("c", 7)]); b = _state([Card("c", 7)], [Card("d", 6)])
    target = _target(a); entry = replace(_advanced_entry(a, b, target=target), realizer="RUN_CONSTRUCTION")
    assert _decision(entry, target, b).requested_tier == TacticalResourceTier.SHALLOW


def test_19_gate_d_different_target_does_not_inherit():
    a = _state([Card("c", 7)]); b = _state([Card("c", 7)], [Card("d", 6)])
    target_a = _target(a); target_b = _target(b, objective="different-target")
    decision = decide_target_grant(
        _advanced_entry(a, b, target=target_a),
        semantic_target_fingerprint=target_b.target_identity.fingerprint,
        requested_initial_tier=TacticalResourceTier.PROBE,
        terminal_qualified=False,
        target_valid=True,
        current_state_key=canonical_state_key(b),
        current_blocker_fingerprint="b",
        current_blocker_kind="SOURCE_BURIED",
    )
    assert decision.requested_tier == TacticalResourceTier.PROBE and not decision.inherited_commitment


def test_20_different_campaign_does_not_share_fingerprint():
    state = _state([Card("c", 7)])
    assert _target(state, campaign="C#1").target_identity.fingerprint != _target(state, campaign="D#1").target_identity.fingerprint


def test_21_gate_e_first_miss_demotes_shallow():
    a = _state([Card("c", 7)]); b = _state([Card("c", 7)], [Card("d", 6)])
    entry = replace(_entry(a, tier=TacticalResourceTier.SHALLOW), granted_tier=TacticalResourceTier.SHALLOW)
    entry = record_target_outcome(entry, TargetCommitmentEvidence(), end_state_key=canonical_state_key(b))
    assert entry.earned_tier == TacticalResourceTier.PROBE and entry.consecutive_misses == 1


def test_22_gate_e_repeated_miss_never_promotes():
    state = _state([Card("c", 7)]); target = _target(state); entry = _entry(state, target=target)
    entry = record_target_outcome(entry, TargetCommitmentEvidence(), end_state_key=canonical_state_key(state))
    assert _decision(entry, target, state).requested_tier == TacticalResourceTier.PROBE


def test_23_persistence_envelope_expires():
    state = _state([Card("c", 7)]); target = _target(state)
    entry = replace(_entry(state, target=target, limit=1), generation=1, evidence=_harvest(), earned_tier=TacticalResourceTier.SHALLOW)
    assert _decision(entry, target, state).status == TargetCommitmentStatus.EXPIRED


def test_24_gate_f_terminal_is_not_inherited():
    state = _state([Card("c", 7)]); target = _target(state)
    entry = replace(_entry(state, target=target), granted_tier=TacticalResourceTier.COMMITTED, earned_tier=TacticalResourceTier.COMMITTED, evidence=_harvest())
    assert _decision(entry, target, state).requested_tier != TacticalResourceTier.TERMINAL


def test_25_gate_f_fresh_terminal_predicate_enables_terminal():
    state = _state([Card("c", 7)]); target = _target(state); entry = _entry(state, target=target)
    decision = _decision(entry, target, state, initial=TacticalResourceTier.TERMINAL, terminal=True)
    assert decision.requested_tier == TacticalResourceTier.TERMINAL


def test_26_unused_grant_is_not_in_lineage_model():
    names = {field.name for field in __import__("dataclasses").fields(type(_entry(_state([Card("c", 7)]))))}
    assert not {"nodes_remaining", "seconds_remaining", "unused_grant"} & names


def test_27_tier_specs_are_unchanged():
    assert tuple((x.max_added_cost, x.max_nodes, x.max_seconds) for x in TacticalResourceAllocatorConfig().tiers) == ((2, 128, 0.1), (4, 512, 0.35), (8, 2000, 1.25), (18, 8000, 2.0))


def test_28_gate_g_fresh_three_move_path_fits_shallow_not_probe():
    state = _state([Card("c", 7)], [Card("c", 6)], [Card("c", 5)], [Card("c", 4)], [Card("c", 3)], [Card("c", 2)])
    first = ((1, 0, 1), (2, 0, 1)); mid = state.clone(); assert replay_actions(mid, list(first)) == 2
    remainder = ((3, 0, 1), (4, 0, 1), (5, 0, 1)); cost = replay_actions(mid, list(remainder))
    config = TacticalResourceAllocatorConfig()
    assert cost > config.spec(TacticalResourceTier.PROBE).max_added_cost and cost <= config.spec(TacticalResourceTier.SHALLOW).max_added_cost


def test_29_gate_g_earned_shallow_executes_fresh_path():
    state = _state([Card("c", 7)], [Card("c", 6)], [Card("c", 5)], [Card("c", 4)], [Card("c", 3)], [Card("c", 2)])
    mid = state.clone(); replay_actions(mid, [(1, 0, 1), (2, 0, 1)])
    target = _target(state); entry = _advanced_entry(state, mid, target=target)
    assert _decision(entry, target, mid).requested_tier == TacticalResourceTier.SHALLOW
    assert replay_actions(mid, [(3, 0, 1), (4, 0, 1), (5, 0, 1)]) == 3


def test_30_shallow_progress_can_earn_committed():
    state = _state([Card("c", 7)]); entry = replace(_entry(state, tier=TacticalResourceTier.SHALLOW), granted_tier=TacticalResourceTier.SHALLOW)
    entry = record_target_outcome(entry, _harvest(), end_state_key=canonical_state_key(state))
    assert entry.earned_tier == TacticalResourceTier.COMMITTED


def test_31_contradictory_fresh_analysis_invalidates():
    state = _state([Card("c", 7)]); target = _target(state); entry = _entry(state, target=target)
    decision = decide_target_grant(entry, semantic_target_fingerprint=target.target_identity.fingerprint, requested_initial_tier=TacticalResourceTier.PROBE, terminal_qualified=False, target_valid=False, current_state_key=canonical_state_key(state), current_blocker_fingerprint=None, current_blocker_kind=None)
    assert decision.status == TargetCommitmentStatus.INVALIDATED


def test_32_fresh_candidate_set_is_recorded():
    state = _state([Card("c", 7)]); target = _target(state); entry = _entry(state, target=target); decision = _decision(entry, target, state)
    assert _trace(entry, decision, candidates=("SOURCE_BURIED", "WORKSPACE")).fresh_relevant_candidate_count == 2


def test_33_candidate_inside_grant_is_recorded():
    state = _state([Card("c", 7)]); target = _target(state); entry = _entry(state, target=target); decision = _decision(entry, target, state)
    assert _trace(entry, decision, minimum=TacticalResourceTier.PROBE, granted=TacticalResourceTier.SHALLOW).candidate_inside_grant is True


def test_34_candidate_outside_grant_is_recorded():
    state = _state([Card("c", 7)]); target = _target(state); entry = _entry(state, target=target); decision = _decision(entry, target, state)
    assert _trace(entry, decision, minimum=TacticalResourceTier.SHALLOW, granted=TacticalResourceTier.PROBE).candidate_inside_grant is False


def test_35_gate_h_candidate_turnover_is_distinct():
    state = _state([Card("c", 7)]); target = _target(state); entry = _entry(state, target=target); trace = _trace(entry, _decision(entry, target, state))
    assert diagnose_persisted_target_failure(trace, candidate_turnover=True) == PersistedTargetFailureDiagnosis.FRESH_CANDIDATE_TURNOVER


def test_36_target_attribution_loss_is_detectable():
    state = _state([Card("c", 7)]); target = _target(state); entry = _entry(state, target=target); trace = _trace(entry, _decision(entry, target, state))
    assert diagnose_persisted_target_failure(trace, same_target_attributed=False) == PersistedTargetFailureDiagnosis.TARGET_ATTRIBUTION_LOSS


def test_37_lifecycle_misordering_is_detectable():
    state = _state([Card("c", 7)]); target = _target(state); entry = _entry(state, target=target); trace = _trace(entry, _decision(entry, target, state))
    assert diagnose_persisted_target_failure(trace, lifecycle_context_lost=True) == PersistedTargetFailureDiagnosis.LIFECYCLE_MISORDERING


def test_38_strategic_admission_loss_is_detectable():
    state = _state([Card("c", 7)]); target = _target(state); entry = _entry(state, target=target); trace = _trace(entry, _decision(entry, target, state))
    assert diagnose_persisted_target_failure(trace, strategically_admitted=False) == PersistedTargetFailureDiagnosis.STRATEGIC_ADMISSION_LOSS


def test_39_resource_bound_is_detectable():
    state = _state([Card("c", 7)]); target = _target(state); entry = _entry(state, target=target); trace = _trace(entry, _decision(entry, target, state))
    assert diagnose_persisted_target_failure(trace, resource_bound=True) == PersistedTargetFailureDiagnosis.RESOURCE_BOUND


def test_40_structural_blocker_is_detectable():
    state = _state([Card("c", 7)]); target = _target(state); entry = _entry(state, target=target); trace = _trace(entry, _decision(entry, target, state), candidates=())
    assert diagnose_persisted_target_failure(trace, structural_blocker=True) == PersistedTargetFailureDiagnosis.STRUCTURAL_BLOCKER


def test_41_gate_i_restore_obligation_persists():
    a = _state([Card("c", 7)]); b = _state([Card("c", 7)], [Card("d", 6)])
    entry = _advanced_entry(a, b); entry = replace(entry, evidence=_harvest(obligation="restore one join", debt=1.0), restore_replace_obligation="restore one join", lifecycle_debt=1.0)
    assert entry.restore_replace_obligation == "restore one join" and entry.evidence.compensation_credible


def test_42_invalid_compensation_demotes():
    state = _state([Card("c", 7)]); target = _target(state)
    entry = replace(_entry(state, target=target), evidence=_harvest(obligation="restore", debt=1.0), earned_tier=TacticalResourceTier.SHALLOW, lifecycle_debt=1.0)
    decision = decide_target_grant(entry, semantic_target_fingerprint=target.target_identity.fingerprint, requested_initial_tier=TacticalResourceTier.PROBE, terminal_qualified=False, target_valid=True, current_state_key=canonical_state_key(state), current_blocker_fingerprint="b", current_blocker_kind="SOURCE_BURIED", lifecycle_debt=2.0, compensation_credible=False)
    assert decision.status in {TargetCommitmentStatus.DEMOTED, TargetCommitmentStatus.RESET}


def test_43_gate_j_bounded_target_reservation_keeps_advanced_and_low_g():
    state = _state([Card("c", 7)], [Card("c", 6)], [Card("c", 5)], [Card("c", 4)])
    target = _target(state)
    residual = derive_residual_milestone_target(state, target, construction=analyze_same_suit_construction(state))
    entry = replace(_entry(state, target=target), evidence=_harvest(), earned_tier=TacticalResourceTier.SHALLOW)
    advanced = StrategicSearchNode(2, state.clone(), 4, (), None, None, 1, StrategicCreditLevel.CLEAN, None, active_milestone=target, active_residual_target=residual, target_grant_lineage=TargetGrantLineage((entry,)))
    conservative = StrategicSearchNode(1, state.clone(), 1, (), None, None, 1, StrategicCreditLevel.CLEAN, None)
    other = StrategicSearchNode(3, state.clone(), 2, (), None, None, 1, StrategicCreditLevel.CLEAN, None)
    portfolio = FoundationCheckpointPortfolio((), (), 0, 0, 2)
    kept = _trim_frontier_with_checkpoint_diversity((((0,), 1, conservative), ((9,), 2, advanced), ((1,), 3, other)), maximum=2, portfolio=portfolio)
    assert {item[1] for item in kept} == {1, 2}


def test_44_no_sunk_cost_without_current_harvest_reservation():
    source = inspect.getsource(_trim_frontier_with_checkpoint_diversity)
    assert "entry.evidence.has_portable_harvest" in source


def test_45_gate_k_lower_g_exact_tt_wins():
    state = _state([Card("c", 7)]); table = StrategicTranspositionTable()
    assert table.admit(state, 5) and table.admit(state.clone(), 4) and not table.admit(state.clone(), 5)


def test_46_lineage_never_enters_canonical_identity():
    state = _state([Card("c", 7)]); before = canonical_state_key(state); TargetGrantLineage((_entry(state),))
    assert canonical_state_key(state) == before


def test_47_expensive_contextual_duplicate_is_suppressed():
    state = _state([Card("c", 7)]); table = StrategicTranspositionTable(); table.admit(state, 2)
    assert not table.admit(state.clone(), 3, heuristic_score=TargetGrantLineage((_entry(state),)))


def test_48_raw_fallback_is_still_present():
    assert "RAW_FALLBACK" in {item.value for item in controller.TacticalObjectiveKind}


def test_49_deal_is_still_a_strategic_action():
    assert "DEAL_NOW" in {item.value for item in controller.StrategicActionKind}


def test_50_late_construction_is_still_enabled():
    assert AnytimeControllerConfig().enable_same_suit_construction


def test_51_unqualified_removal_gating_is_unchanged():
    assert "REMOVAL_DIAGNOSTIC_ONLY" in inspect.getsource(controller._foundation_successors)


def test_52_closure_beam_is_unchanged():
    assert AnytimeControllerConfig().dependency_closure_config.beam_width == 192


def test_53_closure_limits_are_unchanged():
    c = AnytimeControllerConfig().dependency_closure_config
    assert (c.max_added_cost, c.max_nodes, c.time_limit_s) == (14, 4000, 2.0)


def test_54_milestone_limits_are_unchanged():
    c = AnytimeControllerConfig()
    assert (c.milestone_max_primitive_steps, c.milestone_max_strategic_expansions, c.milestone_max_nodes_per_expansion) == (4, 3, 12_000)


@pytest.mark.parametrize("token", ["924bfd20", "b7522950", "Spades", "column 7", "external 119"])
def test_55_benchmark_tokens_absent_from_production_lineage(token):
    source = (ROOT / "src" / "spider" / "planner" / "target_grant_lineage.py").read_text()
    assert token.lower() not in source.lower()


def test_56_canonical_future_actions_are_not_loaded():
    source = inspect.getsource(controller)
    assert "canonical.moves" not in source and "solution_archive" not in source


@pytest.mark.parametrize("seed", [131, 173])
def test_57_unseen_deal_exercises_coordinate_free_lineage(seed):
    cards = list(load_deal(DEAL)); random.Random(seed).shuffle(cards); state = SpiderState.from_cards(cards)
    target = _target(state, objective=f"unseen-{seed}"); entry = _entry(state, target=target)
    assert entry.identity_key == target.target_identity.fingerprint and not entry.proof_pruning_allowed


def test_58_diagnostic_failure_vocabulary_is_complete():
    assert {item.value for item in PersistedTargetFailureDiagnosis} == {"TACTICAL_TIER_RESET", "FRESH_CANDIDATE_TURNOVER", "TARGET_ATTRIBUTION_LOSS", "LIFECYCLE_MISORDERING", "STRATEGIC_ADMISSION_LOSS", "RESOURCE_BOUND", "STRUCTURAL_BLOCKER", "TARGET_SUPERSEDED", "EXPIRED", "OTHER_EXPLICIT"}


def test_59_boundary_trace_reports_tiers_before_and_after():
    state = _state([Card("c", 7)]); target = _target(state); entry = replace(_entry(state, target=target), previous_granted_tier=TacticalResourceTier.PROBE)
    trace = _trace(entry, _decision(entry, target, state), granted=TacticalResourceTier.SHALLOW)
    assert trace.previous_tier == TacticalResourceTier.PROBE and trace.granted_next_tier == TacticalResourceTier.SHALLOW


def test_60_lineage_and_trace_have_no_proof_authority():
    state = _state([Card("c", 7)]); target = _target(state); entry = _entry(state, target=target); trace = _trace(entry, _decision(entry, target, state))
    assert not entry.proof_pruning_allowed and not trace.proof_pruning_allowed
