"""Focused regressions for v0.5 bounded conversion-child expansion coverage."""

from __future__ import annotations

import inspect
from dataclasses import replace
from types import SimpleNamespace

from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    ControllerTelemetry,
    StrategicTranspositionTable,
    _node_priority,
    _reserve_arrival_conversion_coverage,
    _trim_frontier_with_checkpoint_diversity,
    analyze_stage0_state,
)
from spider.planner.residual_campaign import FoundationCheckpointPortfolio
from spider.planner.lower_bounds import compute_solution_lower_bound
from spider.planner.whole_deal_scheduler import (
    ArrivalConversionCoverage,
    ArrivalConversionCoverageStatus,
    ArrivalConversionHarvest,
    ArrivalConversionHarvestKind,
    ArrivalConversionStatus,
    ArrivalStructuralDelta,
    qualify_arrival_conversion_coverage,
)
from spider.state_identity import canonical_state_key

from test_whole_deal_scheduler_v0_4 import _cards, _merge_state, _state
from test_whole_deal_scheduler_v0_5 import _conversion_child, _matured_schedule


def _harvest(
    *kinds,
    opportunity_id="opp-a",
    fragments=(3, 2),
):
    return tuple(
        ArrivalConversionHarvest(
            kind,
            opportunity_id,
            "obl-a",
            kind.value,
            ArrivalStructuralDelta(
                fragment_count_before=fragments[0],
                fragment_count_after=fragments[1],
            ),
        )
        for kind in kinds
    )


def _ledger(harvests, *, status=ArrivalConversionStatus.SPENT, opportunity_id="opp-a"):
    opportunity = SimpleNamespace(opportunity_id=opportunity_id)
    obligation = SimpleNamespace(
        obligation_id="obl-a",
        opportunity=opportunity,
        status=status,
    )
    return SimpleNamespace(harvests=harvests, obligations=(obligation,))


def _coverage(
    state,
    *,
    opportunity_id="opp-a",
    g=4,
    status=ArrivalConversionCoverageStatus.QUALIFIED,
    kinds=(
        ArrivalConversionHarvestKind.ARRIVAL_SOURCE_INTEGRATED,
        ArrivalConversionHarvestKind.FRAGMENTS_JOINED,
    ),
):
    harvests = _harvest(*kinds, opportunity_id=opportunity_id)
    return ArrivalConversionCoverage(
        opportunity_id,
        "obl-a",
        canonical_state_key(state),
        g,
        harvests,
        1,
        status=status,
    )


def _search_node(state, coverage=None, node_id=1, g=4):
    schedule = _matured_schedule(state)
    return replace(
        _conversion_child(state, schedule, coverage.opportunity_id if coverage else "none"),
        node_id=node_id,
        g=g,
        arrival_conversion_coverage=coverage,
        stage0=analyze_stage0_state(state, spent_cost=g, incumbent_cost=None),
    )


def _frontier(*nodes):
    return [(_node_priority(node), node.node_id, node) for node in nodes]


def test_01_tt_admitted_integrated_child_qualifies_for_one_expansion():
    state = _merge_state()
    harvests = _harvest(
        ArrivalConversionHarvestKind.ARRIVAL_SOURCE_INTEGRATED,
        ArrivalConversionHarvestKind.FRAGMENTS_JOINED,
    )
    coverage = qualify_arrival_conversion_coverage(
        _ledger(harvests),
        opportunity_id="opp-a",
        end_state=state,
        corrected_g=5,
        independently_replay_verified=True,
    )
    assert coverage is not None
    assert coverage.exact_tt_admitted
    assert coverage.has_integration
    assert coverage.has_structural_harvest
    assert coverage.proof_pruning_allowed is False
    tt = StrategicTranspositionTable()
    assert tt.admit(state, 5)
    telemetry = ControllerTelemetry()
    reserved = _reserve_arrival_conversion_coverage(
        _frontier(_search_node(state, coverage)),
        tt=tt,
        spent_opportunity_ids=(),
        telemetry=telemetry,
    )
    assert telemetry.arrival_conversion_representatives_reserved == 1
    assert reserved[0][2].arrival_conversion_coverage.status == (
        ArrivalConversionCoverageStatus.RESERVED
    )


def test_02_at_most_one_live_reservation():
    state = _merge_state()
    first = _coverage(state, opportunity_id="opp-a", g=3)
    second = _coverage(state, opportunity_id="opp-b", g=9)
    telemetry = ControllerTelemetry()
    tt = StrategicTranspositionTable()
    tt.admit(state, 3)
    reserved = _reserve_arrival_conversion_coverage(
        _frontier(
            _search_node(state, first, node_id=1, g=3),
            _search_node(state, second, node_id=2, g=9),
        ),
        tt=tt,
        spent_opportunity_ids=(),
        telemetry=telemetry,
    )
    statuses = [
        item[2].arrival_conversion_coverage.status for item in reserved
    ]
    assert statuses.count(ArrivalConversionCoverageStatus.RESERVED) == 1
    assert telemetry.arrival_conversion_representatives_reserved == 1
    reserved_ids = {
        item[2].arrival_conversion_coverage.opportunity_id
        for item in reserved
        if item[2].arrival_conversion_coverage.status
        == ArrivalConversionCoverageStatus.RESERVED
    }
    assert reserved_ids == {"opp-a"}


def test_03_no_double_reservation_of_same_opportunity():
    state = _merge_state()
    coverage = _coverage(state)
    telemetry = ControllerTelemetry()
    tt = StrategicTranspositionTable()
    tt.admit(state, 4)
    first = _reserve_arrival_conversion_coverage(
        _frontier(_search_node(state, coverage)),
        tt=tt,
        spent_opportunity_ids=(),
        telemetry=telemetry,
    )
    spent_id = first[0][2].arrival_conversion_coverage.opportunity_id
    second = _reserve_arrival_conversion_coverage(
        first,
        tt=tt,
        spent_opportunity_ids=(spent_id,),
        telemetry=telemetry,
    )
    assert second[0][2].arrival_conversion_coverage.status == (
        ArrivalConversionCoverageStatus.SPENT
    )
    assert telemetry.arrival_conversion_representatives_reserved == 1


def test_03b_second_conversion_is_not_reserved_after_one_expansion():
    state = _merge_state()
    first = _coverage(state, opportunity_id="opp-a", g=3)
    second = _coverage(state, opportunity_id="opp-b", g=4)
    telemetry = ControllerTelemetry()
    tt = StrategicTranspositionTable()
    tt.admit(state, 3)
    reserved = _reserve_arrival_conversion_coverage(
        _frontier(
            _search_node(state, first, node_id=1, g=3),
            _search_node(state, second, node_id=2, g=4),
        ),
        tt=tt,
        spent_opportunity_ids=("opp-a",),
        telemetry=telemetry,
    )
    assert all(
        item[2].arrival_conversion_coverage.status
        != ArrivalConversionCoverageStatus.RESERVED
        for item in reserved
    )
    assert telemetry.arrival_conversion_representatives_reserved == 0


def test_04_no_extra_frontier_capacity_or_resources():
    config = AnytimeControllerConfig()
    assert config.max_frontier_size == 2_000
    assert config.max_strategic_expansions == 400
    assert config.max_tactical_nodes == 100_000
    state = _merge_state()
    reserved = _search_node(
        state,
        _coverage(state, status=ArrivalConversionCoverageStatus.RESERVED),
        node_id=1,
        g=8,
    )
    ordinary = [
        _search_node(state, node_id=index, g=1)
        for index in range(2, 5)
    ]
    trimmed = _trim_frontier_with_checkpoint_diversity(
        _frontier(reserved, *ordinary),
        maximum=2,
        portfolio=FoundationCheckpointPortfolio((), (), 0, 0, 2),
    )
    assert len(trimmed) == 2
    assert any(
        item[2].arrival_conversion_coverage is not None
        and item[2].arrival_conversion_coverage.status
        == ArrivalConversionCoverageStatus.RESERVED
        for item in trimmed
    )


def test_05_non_integrated_conversion_gets_none():
    state = _merge_state()
    harvests = _harvest(ArrivalConversionHarvestKind.DEPENDENCY_CHAIN_ADVANCE)
    assert (
        qualify_arrival_conversion_coverage(
            _ledger(harvests, status=ArrivalConversionStatus.ACTIONABLE),
            opportunity_id="opp-a",
            end_state=state,
            corrected_g=2,
            independently_replay_verified=True,
        )
        is None
    )


def test_06_conversion_without_structural_harvest_gets_none():
    state = _merge_state()
    harvests = _harvest(
        ArrivalConversionHarvestKind.ARRIVAL_SOURCE_CONSUMED,
        fragments=(2, 2),
    )
    assert (
        qualify_arrival_conversion_coverage(
            _ledger(harvests),
            opportunity_id="opp-a",
            end_state=state,
            corrected_g=2,
            independently_replay_verified=True,
        )
        is None
    )


def test_07_after_expansion_ordinary_economics_resume():
    state = _merge_state()
    reserved = _search_node(
        state,
        _coverage(state, status=ArrivalConversionCoverageStatus.RESERVED),
    )
    spent = replace(
        reserved,
        arrival_conversion_coverage=replace(
            reserved.arrival_conversion_coverage,
            status=ArrivalConversionCoverageStatus.SPENT,
        ),
    )
    child = _search_node(state, coverage=None, node_id=2, g=5)
    assert spent.arrival_conversion_coverage.status == (
        ArrivalConversionCoverageStatus.SPENT
    )
    assert child.arrival_conversion_coverage is None
    reserved_rank = _node_priority(reserved)[1]
    spent_rank = _node_priority(spent)[1]
    child_rank = _node_priority(child)[1]
    assert reserved_rank < spent_rank
    assert spent_rank == child_rank


def test_08_exact_tt_and_proof_unchanged():
    state = _merge_state()
    before = compute_solution_lower_bound(state)
    coverage = qualify_arrival_conversion_coverage(
        _ledger(
            _harvest(
                ArrivalConversionHarvestKind.ARRIVAL_SOURCE_INTEGRATED,
                ArrivalConversionHarvestKind.FRAGMENTS_JOINED,
            )
        ),
        opportunity_id="opp-a",
        end_state=state,
        corrected_g=4,
        independently_replay_verified=True,
    )
    assert coverage.proof_pruning_allowed is False
    assert compute_solution_lower_bound(state) == before
    tt = StrategicTranspositionTable()
    assert tt.admit(state, 4)
    assert not tt.admit(state, 4)
    assert tt.best_g(state) == 4
    source = inspect.getsource(ArrivalConversionCoverage)
    assert "proof_pruning_allowed" in source
    assert ControllerTelemetry().lane_maturation_representatives_reserved == 0
    assert ControllerTelemetry().lane_maturation_representatives_expanded == 0
