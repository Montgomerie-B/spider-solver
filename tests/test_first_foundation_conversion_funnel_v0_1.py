from __future__ import annotations

import inspect
from dataclasses import replace

import pytest

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner import anytime_controller as controller
from spider.planner.anytime_controller import AnytimeControllerConfig
from spider.planner.campaign_dependency_closure import (
    CampaignCriticalPathEntry,
    CampaignCriticalPathSummary,
    CampaignDependencyType,
)
from spider.planner.foundation_conversion_funnel import (
    FoundationConversionFunnel,
    FoundationFunnelFailure,
    FoundationFunnelStage,
)
from spider.planner.tactical_resource_allocator import (
    TacticalRealizerKind,
    TacticalResourceAllocator,
    TacticalResourceTier,
    derive_tactical_demands,
)
from spider.rules import MW_RULES
from spider.state_identity import canonical_state_key


def _state() -> SpiderState:
    return SpiderState(
        [
            Column([], [Card("c", 8), Card("c", 7)]),
            Column([], [Card("d", 9)]),
        ]
        + [Column([], []) for _ in range(8)],
        [],
        [],
    )


def _summary(campaign_id: str = "C#1") -> CampaignCriticalPathSummary:
    entry = CampaignCriticalPathEntry(
        "source:C#1:6",
        CampaignDependencyType.SOURCE_BURIED,
        (),
        2,
        1,
        False,
        False,
        1,
        "buried current-epoch campaign source",
    )
    return CampaignCriticalPathSummary(
        campaign_id,
        (entry,),
        3,
        entry.dependency_id,
        bottleneck_kind=entry.kind,
        prerequisite_dependency_ids=(entry.dependency_id,),
        deepest_source_depth=1,
    )


def _bridge_portfolio(*, continuation="C#1", enabled=True):
    return derive_tactical_demands(
        (_summary(),),
        campaign_suits={"C#1": "c"},
        continuation_objective_id=continuation,
        enable_foundation_demand_bridge=enabled,
    )


def _record(funnel, stage, state, *, actions=()):
    return funnel.record(
        stage,
        expansion=4,
        project_id="project-1",
        campaign_id="C#1",
        state_key=canonical_state_key(state),
        actions=actions,
        request_key=("request", 1),
    )


def test_01_funnel_stage_accounting_deduplicates_exact_request_and_state():
    funnel = FoundationConversionFunnel()
    assert _record(funnel, FoundationFunnelStage.PROJECT_EXISTS, _state())
    assert not _record(funnel, FoundationFunnelStage.PROJECT_EXISTS, _state())
    row = funnel.snapshot()["stages"]["F0_PROJECT_EXISTS"]
    assert row == {
        "entrants": 1,
        "first_expansion": 4,
        "unique_projects": 1,
        "unique_states": 1,
    }


def test_02_project_and_campaign_identity_are_preserved():
    funnel = FoundationConversionFunnel()
    _record(funnel, FoundationFunnelStage.CANDIDATE_AVAILABLE, _state())
    event = funnel.snapshot()["events"][0]
    assert (event["project_id"], event["campaign_id"]) == ("project-1", "C#1")


def test_03_joint_trajectory_fingerprint_changes_only_with_actual_prefix():
    funnel = FoundationConversionFunnel()
    state = _state()
    _record(funnel, FoundationFunnelStage.CAMPAIGN_ANALYSED, state, actions=((0, 1, 1),))
    _record(funnel, FoundationFunnelStage.CAMPAIGN_ANALYSED, state, actions=((1, 0, 1),))
    events = funnel.snapshot()["events"]
    assert events[0]["state_digest"] == events[1]["state_digest"]
    assert events[0]["trajectory_digest"] != events[1]["trajectory_digest"]


def test_04_control_derivation_exposes_the_confirmed_demand_gap():
    portfolio = _bridge_portfolio(enabled=False)
    assert not portfolio.for_realizer(
        TacticalRealizerKind.CAMPAIGN_CURRENT_EPOCH, campaign_id="C#1"
    )


def test_05_bridge_uses_existing_project_and_campaign_eligibility():
    demand = _bridge_portfolio().best_for(
        TacticalRealizerKind.CAMPAIGN_CURRENT_EPOCH, campaign_id="C#1"
    )
    assert demand is not None
    assert demand.target_dependency_id == "source:C#1:6"
    assert demand.continuation_attention
    assert demand.initial_tier == TacticalResourceTier.PROBE


def test_06_bridge_does_not_emit_for_an_ineligible_project():
    portfolio = _bridge_portfolio(continuation="D#1")
    assert not portfolio.for_realizer(TacticalRealizerKind.CAMPAIGN_CURRENT_EPOCH)


def test_07_bridge_still_requires_the_existing_allocator():
    demand = _bridge_portfolio().best_for(TacticalRealizerKind.CAMPAIGN_CURRENT_EPOCH)
    allocator = TacticalResourceAllocator()
    request, grant = allocator.request(canonical_state_key(_state()), demand)
    assert request.demand is demand and grant is not None
    assert allocator.ledger.total_nodes_granted == grant.nodes_granted


def test_08_bridge_does_not_change_tactical_budgets():
    before = TacticalResourceAllocator().config.fingerprint
    _bridge_portfolio()
    after = TacticalResourceAllocator().config.fingerprint
    assert before == after


def test_09_existing_current_epoch_realiser_is_invoked_by_that_demand_kind():
    source = inspect.getsource(controller._foundation_successors)
    assert "TacticalRealizerKind.CAMPAIGN_CURRENT_EPOCH" in source
    assert "realize_campaign_to_next_epoch(" in source
    assert source.index("allocator.request") < source.index("realize_campaign_to_next_epoch(")


def test_10_drop_stage_uses_the_bounded_failure_taxonomy():
    funnel = FoundationConversionFunnel()
    state = _state()
    assert funnel.drop(
        FoundationFunnelStage.REPLAYABLE_PROGRESS_RETURNED,
        FoundationFunnelStage.PROGRESS_RETAINED,
        FoundationFunnelFailure.TT_DOMINATED,
        expansion=5,
        project_id="project-1",
        campaign_id="C#1",
        state_key=canonical_state_key(state),
        request_key=("request", 1),
        evidence="equal/lower-g exact state",
    )
    assert funnel.snapshot()["drops"][0]["reason"] == "TT_DOMINATED"


def test_11_foundation_successor_stage_is_explicit():
    funnel = FoundationConversionFunnel()
    _record(funnel, FoundationFunnelStage.FOUNDATION_GENERATED, _state())
    assert funnel.snapshot()["deepest_stage"] == "F12_FOUNDATION_GENERATED"


def test_12_independent_first_foundation_replay_matches_exact_state_and_cost():
    run = [Card("s", rank) for rank in range(13, 1, -1)]
    opening = SpiderState(
        [Column([], run), Column([], [Card("s", 1)])]
        + [Column([], []) for _ in range(8)],
        [],
        [],
    )
    result = opening.clone()
    cost = result.move(1, 0, 1, rules=MW_RULES)
    replay = opening.clone()
    assert replay_actions(replay, [(1, 0, 1)]) == cost
    assert canonical_state_key(replay) == canonical_state_key(result)
    assert len(result.foundations) == 1


def test_13_bridge_and_funnel_add_no_proof_authority():
    demand = _bridge_portfolio().best_for(TacticalRealizerKind.CAMPAIGN_CURRENT_EPOCH)
    assert demand.proof_pruning_allowed is False
    assert not hasattr(FoundationConversionFunnel(), "proof_pruning_allowed")


def test_14_production_defaults_are_unchanged_and_opt_in_is_guarded():
    config = AnytimeControllerConfig()
    assert not config.enable_foundation_conversion_funnel
    assert not config.enable_foundation_demand_bridge
    with pytest.raises(ValueError, match="requires StrategicProject"):
        replace(config, enable_foundation_demand_bridge=True)
