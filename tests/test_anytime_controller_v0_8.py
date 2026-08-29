from __future__ import annotations

import inspect
import random
from dataclasses import replace
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
import spider.planner.anytime_controller as controller_module
from spider.planner.anytime_controller import (
    StrategicTranspositionTable,
    analyze_same_suit_construction,
)
from spider.planner.campaign_dependency_closure import (
    CampaignDependency,
    CampaignDependencyGraph,
    CampaignDependencyType,
    build_campaign_critical_path,
)
from spider.planner.incumbent_budget import build_incumbent_budget
from spider.planner.tactical_resource_allocator import (
    RemovalAllocationPolicy,
    TacticalDemand,
    TacticalObjectiveKind,
    TacticalRealizerKind,
    TacticalResourceAllocator,
    TacticalResourceDecision,
    TacticalResourceOutcome,
    TacticalResourceTier,
    derive_tactical_demands,
)
from spider.planner.structural_construction import ConstructionDisposition
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key


ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"


def _columns(*face_up):
    columns = [Column([], list(cards)) for cards in face_up]
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return columns


def _state(*, stock=()):
    return SpiderState(_columns([Card("d", 9), Card("c", 5)], [Card("c", 6)]), list(stock))


def _graph(kind: CampaignDependencyType, *, dependency_id="blocker"):
    state = _state()
    dependency = CampaignDependency(
        dependency_id,
        kind,
        "C#1",
        "fixture blocker",
        depth=2 if kind == CampaignDependencyType.SOURCE_BURIED else 0,
    )
    terminal = CampaignDependency(
        "terminal:C#1",
        CampaignDependencyType.TERMINAL_ASSEMBLY_PREREQUISITE,
        "C#1",
        "terminal",
        prerequisites=(dependency_id,),
    )
    return CampaignDependencyGraph(
        canonical_state_key(state),
        "C#1",
        (dependency, terminal),
        ((dependency_id, "terminal:C#1"),),
        (),
        "terminal:C#1",
        f"fixture-{kind.value}",
    )


def _portfolio(kind: CampaignDependencyType, *, terminal=False, continuation=None):
    summary = build_campaign_critical_path(_graph(kind), terminal_qualified=terminal)
    return derive_tactical_demands(
        (summary,),
        campaign_suits={"C#1": "c"},
        continuation_objective_id=continuation,
        deal_available=True,
    )


def _demand(kind=CampaignDependencyType.RECEIVER_MISSING):
    return _portfolio(kind).best_for(TacticalRealizerKind.DEPENDENCY_CLOSURE, campaign_id="C#1")


def _outcome(grant, **changes):
    values = dict(
        request_id=grant.request_id,
        key=grant.key,
        tier=grant.tier,
        nodes_consumed=grant.nodes_granted,
        seconds_consumed=grant.seconds_granted,
        corrected_paid_cost=0,
        legal_successor_count=0,
        blocker_before="blocker",
        blocker_after="blocker",
    )
    values.update(changes)
    return TacticalResourceOutcome(**values)


def test_01_inherited_baseline_recorded_before_development():
    report = ROOT / "docs" / "anytime_whole_game_controller_v0_7.md"
    assert report.is_file()


def test_02_unrestricted_deal_remains_on():
    assert MW_RULES.can_deal_into_empty is True


def test_03_regression_anchor_is_unchanged():
    result = validate_solution("4925153", ROOT / "solutions" / "4925153_canonical.moves")
    assert (result.mobilityware_moves, result.path_hash, result.state_hash) == (
        172,
        "77d169da2538ba8c",
        "4e9861540eac570cb",
    )


def test_04_objective_kinds_cover_required_tactical_demands():
    assert {item.value for item in TacticalObjectiveKind} == {
        "DEPENDENCY_CLOSURE", "RECEIVER_CREATION", "INTERVAL_ASSEMBLY",
        "OVERLAY_CLEARING", "SUPPLY_CONSUMPTION", "RUN_CONSTRUCTION",
        "EXCAVATION", "WORKSPACE", "FOUNDATION_REMOVAL", "DEAL_PREPARATION",
        "DEAL_EVALUATION", "RAW_FALLBACK",
    }


def test_05_receiver_blocker_selects_receiver_closure():
    demand = _demand(CampaignDependencyType.RECEIVER_MISSING)
    assert demand.objective == TacticalObjectiveKind.RECEIVER_CREATION
    assert demand.realizer == TacticalRealizerKind.DEPENDENCY_CLOSURE


def test_06_interval_blocker_selects_interval_closure():
    demand = _demand(CampaignDependencyType.MISSING_SAME_SUIT_INTERVAL)
    assert demand.objective == TacticalObjectiveKind.INTERVAL_ASSEMBLY


def test_07_overlay_blocker_selects_overlay_closure():
    assert _demand(CampaignDependencyType.MIXED_OVERLAY).objective == TacticalObjectiveKind.OVERLAY_CLEARING


def test_08_waiting_supply_selects_consumption_closure():
    demand = _demand(CampaignDependencyType.SUPPLIED_NOT_CONSUMED)
    assert demand.objective == TacticalObjectiveKind.SUPPLY_CONSUMPTION
    assert demand.supplied_asset_waiting


def test_09_terminal_campaign_enables_terminal_tier():
    portfolio = _portfolio(CampaignDependencyType.RECEIVER_MISSING, terminal=True)
    demand = portfolio.best_for(
        TacticalRealizerKind.TERMINAL_ASSEMBLY, campaign_id="C#1"
    )
    assert demand.initial_tier == TacticalResourceTier.TERMINAL
    assert demand.removal_policy == RemovalAllocationPolicy.REMOVAL_FULL_BUDGET
    assert portfolio.for_realizer(TacticalRealizerKind.CAMPAIGN_CORRIDOR, campaign_id="C#1")


def test_10_nonterminal_campaign_gets_diagnostic_removal_only():
    demand = _portfolio(CampaignDependencyType.RECEIVER_MISSING).best_for(
        TacticalRealizerKind.CAMPAIGN_REMOVAL, campaign_id="C#1"
    )
    assert demand.initial_tier == TacticalResourceTier.PROBE
    assert demand.removal_policy == RemovalAllocationPolicy.REMOVAL_DIAGNOSTIC_ONLY


def test_11_removal_remains_represented_when_not_qualified():
    portfolio = _portfolio(CampaignDependencyType.RECEIVER_MISSING)
    assert portfolio.for_realizer(
        TacticalRealizerKind.CAMPAIGN_REMOVAL, campaign_id="C#1"
    )
    assert not portfolio.for_realizer(TacticalRealizerKind.CAMPAIGN_CORRIDOR, campaign_id="C#1")


def test_12_probe_tier_is_small_and_bounded():
    spec = TacticalResourceAllocator().config.spec(TacticalResourceTier.PROBE)
    assert 0 < spec.max_nodes < 512 and 0 < spec.max_seconds <= 0.10


def test_13_shallow_tier_is_bounded_and_larger_than_probe():
    config = TacticalResourceAllocator().config
    probe, shallow = config.spec(TacticalResourceTier.PROBE), config.spec(TacticalResourceTier.SHALLOW)
    assert probe.max_nodes < shallow.max_nodes < config.spec(TacticalResourceTier.COMMITTED).max_nodes


def test_14_committed_tier_requires_prior_harvest():
    allocator = TacticalResourceAllocator()
    demand = replace(_demand(), initial_tier=TacticalResourceTier.COMMITTED)
    _request, grant = allocator.request(canonical_state_key(_state()), demand)
    assert grant.tier == TacticalResourceTier.SHALLOW


def test_15_terminal_tier_requires_qualification():
    allocator = TacticalResourceAllocator()
    demand = replace(_demand(), initial_tier=TacticalResourceTier.TERMINAL)
    _request, grant = allocator.request(canonical_state_key(_state()), demand)
    assert grant.tier != TacticalResourceTier.TERMINAL


def test_16_no_harvest_probe_does_not_promote():
    allocator = TacticalResourceAllocator(); key = canonical_state_key(_state()); demand = _demand()
    _request, grant = allocator.request(key, demand)
    outcome = allocator.record_outcome(_outcome(grant))
    _request, next_grant = allocator.request(key, demand)
    assert outcome.decision == TacticalResourceDecision.CONTINUE_SAME_TIER
    assert next_grant.tier == TacticalResourceTier.PROBE


def test_17_dependency_harvest_promotes_probe():
    allocator = TacticalResourceAllocator(); key = canonical_state_key(_state()); demand = _demand()
    _request, grant = allocator.request(key, demand)
    outcome = allocator.record_outcome(_outcome(grant, dependencies_closed=1))
    _request, next_grant = allocator.request(key, demand)
    assert outcome.decision == TacticalResourceDecision.PROMOTE
    assert next_grant.tier == TacticalResourceTier.SHALLOW


def test_18_repeated_unchanged_miss_suspends_exact_context():
    allocator = TacticalResourceAllocator(); key = canonical_state_key(_state()); demand = _demand()
    for _ in range(2):
        _request, grant = allocator.request(key, demand)
        outcome = allocator.record_outcome(_outcome(grant))
    _request, stopped = allocator.request(key, demand)
    assert outcome.decision == TacticalResourceDecision.SUSPEND_FOR_STATE
    assert stopped is None


def test_19_fresh_state_recalculates_resource_eligibility():
    allocator = TacticalResourceAllocator(); demand = _demand(); first = canonical_state_key(_state())
    for _ in range(2):
        _request, grant = allocator.request(first, demand); allocator.record_outcome(_outcome(grant))
    second = canonical_state_key(_state(stock=[Card("h", 13)] * 10))
    _request, fresh = allocator.request(second, demand)
    assert fresh is not None and fresh.tier == TacticalResourceTier.PROBE


def test_20_resource_key_contains_exact_context_and_critical_path():
    allocator = TacticalResourceAllocator(); state_key = canonical_state_key(_state()); demand = _demand()
    request, _grant = allocator.request(state_key, demand)
    assert request.key.state_key == state_key and request.key.critical_path_fingerprint


def test_21_resource_history_does_not_enter_tt_identity():
    state = _state(); table = StrategicTranspositionTable(); allocator = TacticalResourceAllocator()
    allocator.request(canonical_state_key(state), _demand())
    assert table.admit(state, 3) and not table.admit(state.clone(), 3, heuristic_score=allocator.ledger)


def test_22_lower_g_exact_state_still_dominates():
    state = _state(); table = StrategicTranspositionTable()
    assert table.admit(state, 5) and table.admit(state.clone(), 4) and not table.admit(state.clone(), 6)


def test_23_ledger_records_granted_and_consumed_nodes():
    allocator = TacticalResourceAllocator(); _request, grant = allocator.request(canonical_state_key(_state()), _demand())
    allocator.record_outcome(_outcome(grant, nodes_consumed=7))
    assert allocator.ledger.total_nodes_granted == grant.nodes_granted and allocator.ledger.total_nodes_consumed == 7


def test_24_ledger_records_granted_and_consumed_time():
    allocator = TacticalResourceAllocator(); _request, grant = allocator.request(canonical_state_key(_state()), _demand())
    allocator.record_outcome(_outcome(grant, seconds_consumed=0.02))
    assert allocator.ledger.total_seconds_granted == grant.seconds_granted
    assert allocator.ledger.total_seconds_consumed == 0.02


def test_25_dependency_harvest_is_named():
    allocator = TacticalResourceAllocator(); _request, grant = allocator.request(canonical_state_key(_state()), _demand())
    outcome = allocator.record_outcome(_outcome(grant, dependencies_closed=2))
    assert outcome.named_harvest_events == 2


def test_26_construction_harvest_is_named():
    demand = TacticalDemand(TacticalObjectiveKind.RUN_CONSTRUCTION, TacticalRealizerKind.RUN_CONSTRUCTION, "join")
    allocator = TacticalResourceAllocator(); _request, grant = allocator.request(canonical_state_key(_state()), demand)
    assert allocator.record_outcome(_outcome(grant, permanent_adjacencies_created=1)).has_named_harvest


def test_27_terminal_qualification_change_is_named():
    allocator = TacticalResourceAllocator(); _request, grant = allocator.request(canonical_state_key(_state()), _demand())
    outcome = allocator.record_outcome(_outcome(grant, terminal_qualification_after=True))
    assert outcome.decision == TacticalResourceDecision.TERMINAL_ESCALATION


def test_28_foundation_result_is_named():
    allocator = TacticalResourceAllocator(); _request, grant = allocator.request(canonical_state_key(_state()), _demand())
    assert allocator.record_outcome(_outcome(grant, foundation_removals=1)).has_named_harvest


def test_29_continuation_gets_critical_path_attention():
    demand = _portfolio(CampaignDependencyType.RECEIVER_MISSING, continuation="C#1").best_for(
        TacticalRealizerKind.DEPENDENCY_CLOSURE, campaign_id="C#1"
    )
    assert demand.continuation_attention


def test_30_continuation_does_not_automatically_get_maximum_tier():
    demand = _portfolio(CampaignDependencyType.RECEIVER_MISSING, continuation="C#1").best_for(
        TacticalRealizerKind.DEPENDENCY_CLOSURE, campaign_id="C#1"
    )
    assert demand.initial_tier == TacticalResourceTier.PROBE


def test_31_alternate_campaign_remains_represented():
    a = build_campaign_critical_path(_graph(CampaignDependencyType.RECEIVER_MISSING))
    other_graph = replace(_graph(CampaignDependencyType.MIXED_OVERLAY), campaign_id="D#1")
    other_dependencies = tuple(replace(item, campaign_id="D#1") for item in other_graph.dependencies)
    b = build_campaign_critical_path(replace(other_graph, dependencies=other_dependencies))
    portfolio = derive_tactical_demands((a, b), campaign_suits={"C#1": "c", "D#1": "d"})
    assert set(portfolio.campaign_ids) == {"C#1", "D#1"}


def test_32_late_removal_construction_is_represented():
    analysis = analyze_same_suit_construction(_state(stock=[Card("h", 13)] * 20))
    portfolio = derive_tactical_demands((), construction=analysis)
    assert portfolio.for_realizer(TacticalRealizerKind.RUN_CONSTRUCTION)


def test_33_cheap_two_card_construction_can_receive_probe():
    analysis = analyze_same_suit_construction(_state())
    portfolio = derive_tactical_demands((), construction=analysis)
    demand = portfolio.best_for(TacticalRealizerKind.RUN_CONSTRUCTION)
    assert analysis.opportunities[0].run_length_after == 2 and demand.initial_tier == TacticalResourceTier.PROBE


def test_34_future_free_join_can_still_be_deferred():
    row = [Card("h", 13)] * 10; row[1] = Card("c", 5)
    opportunity = analyze_same_suit_construction(_state(stock=row)).opportunities[0]
    assert opportunity.disposition == ConstructionDisposition.DEFER_FOR_FREE_FUTURE_JOIN


def test_35_workspace_conflict_can_downorder_construction():
    opportunity = analyze_same_suit_construction(_state(), critical_receiver_columns=(1,)).opportunities[0]
    assert opportunity.disposition == ConstructionDisposition.DOWNORDER_WORKSPACE_CONFLICT


def test_36_deal_remains_represented():
    assert _portfolio(CampaignDependencyType.RECEIVER_MISSING).for_realizer(TacticalRealizerKind.DEAL_TIMING)


def test_37_tactical_miss_has_no_proof_authority():
    allocator = TacticalResourceAllocator(); _request, grant = allocator.request(canonical_state_key(_state()), _demand())
    outcome = allocator.record_outcome(_outcome(grant))
    assert not outcome.proof_pruning_allowed and not allocator.ledger.proof_pruning_allowed


def test_38_allocator_cannot_change_admissible_h():
    state = _state(stock=[Card("h", 13)] * 10)
    before = build_incumbent_budget(state, spent_cost=2, incumbent_cost=100, heuristic_remaining_work=5)
    TacticalResourceAllocator().request(canonical_state_key(state), _demand())
    after = build_incumbent_budget(state, spent_cost=2, incumbent_cost=100, heuristic_remaining_work=99)
    assert before.admissible_remaining_lower_bound == after.admissible_remaining_lower_bound


def test_39_allocator_cannot_change_rules():
    before = MW_RULES.can_deal_into_empty; TacticalResourceAllocator()
    assert MW_RULES.can_deal_into_empty == before


def test_40_benchmark_suit_rank_and_column_constants_absent():
    text = (ROOT / "src" / "spider" / "planner" / "tactical_resource_allocator.py").read_text().lower()
    assert "spades" not in text and "diamonds" not in text and "column 7" not in text


def test_41_canonical_actions_unavailable_prospectively():
    source = inspect.getsource(controller_module)
    assert "canonical.moves" not in source and "solution_archive" not in source


def test_42_external_119_absent_from_resource_policy():
    text = (ROOT / "src" / "spider" / "planner" / "tactical_resource_allocator.py").read_text()
    assert "119" not in text


def test_43_progressive_tranches_fit_existing_deadline():
    config = TacticalResourceAllocator().config
    assert config.spec(TacticalResourceTier.TERMINAL).max_seconds <= 2.0
    assert config.max_granted_seconds_per_expansion <= 4.0


def test_44_total_benchmark_budget_constants_remain_unchanged():
    source = (ROOT / "src" / "spider" / "planner" / "diagnostics" / "anytime_whole_game_controller_v0_7_report.py").read_text()
    assert "max_tactical_nodes=500_000" in source and "max_strategic_expansions=50" in source


def test_45_unseen_deals_exercise_generic_allocation():
    base = load_deal(DEAL)
    for seed in (31, 47):
        cards = list(base); random.Random(seed).shuffle(cards)
        analysis = analyze_same_suit_construction(SpiderState.from_cards(cards))
        portfolio = derive_tactical_demands((), construction=analysis, deal_available=True)
        assert portfolio.for_realizer(TacticalRealizerKind.RUN_CONSTRUCTION)
        assert portfolio.for_realizer(TacticalRealizerKind.DEAL_TIMING)


def test_46_diagnostic_api_exposes_per_realizer_return():
    outcome = _outcome(
        TacticalResourceAllocator().request(canonical_state_key(_state()), _demand())[1],
        dependencies_closed=1,
        nodes_consumed=10,
        seconds_consumed=0.5,
    )
    assert outcome.harvest_rate.dependencies_closed_per_second == 2.0
    assert outcome.harvest_rate.harvest_events_per_thousand_nodes == 100.0
