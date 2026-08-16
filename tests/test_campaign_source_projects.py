"""Focused tests for shared-helper campaign source projects."""

from __future__ import annotations

import inspect
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner import campaign_source_projects as csp
from spider.planner.campaign_source_projects import (
    CampaignSourceProjectPlan,
    CampaignSourceRealizationStatus,
    build_campaign_source_project_plan,
    helper_task_is_satisfied,
    realize_campaign_source_projects,
)
from spider.planner.diagnostics.residual_campaign_continuation_report import (
    reconstruct_cost47,
)
from spider.planner.foundation_campaign_transition import CampaignTransitionStatus
from spider.state_identity import states_structurally_equal


@pytest.fixture(scope="module")
def benchmark():
    cards = tuple(load_deal(ROOT / "deals" / "4925153.txt"))
    reconstructed = reconstruct_cost47(cards)
    plan = build_campaign_source_project_plan(
        reconstructed.state, reconstructed.campaign
    )
    result = realize_campaign_source_projects(
        reconstructed.state,
        reconstructed.campaign,
        cards,
        max_added_cost=6,
        max_nodes=50_000,
        time_limit_s=12,
        branch_cap=24,
    )
    return cards, reconstructed, plan, result


def _foundation(suit: str):
    return [Card(suit, rank) for rank in range(13, 0, -1)]


def _empty_plan(campaign):
    return CampaignSourceProjectPlan(
        csp.CampaignIdentity(
            campaign.suit,
            campaign.copy_index,
            campaign.target_removal_epoch,
        ),
        (),
        (),
        (),
        (),
        (),
        ("synthetic no-source handoff",),
    )


def test_remaining_must_sources_become_source_projects(benchmark):
    _cards, reconstructed, plan, _result = benchmark
    modeled = {
        rank for project in plan.projects for rank in project.required_ranks
    }
    expected = {
        source.card.rank
        for source in reconstructed.campaign.tableau_critical_cards
    }
    assert modeled == expected
    assert all(not project.current_satisfied for project in plan.projects)


def test_interchangeable_physical_sources_are_represented(benchmark):
    _cards, reconstructed, _plan, _result = benchmark
    campaign = reconstructed.campaign
    need = next(
        need
        for need in campaign.rank_needs
        if need.chosen is not None and need.must_excavate
    )
    alternate = replace(
        need.chosen,
        source_key=f"synthetic:alternate:{need.rank}",
        column=(need.chosen.column + 1) % len(reconstructed.state.columns),
    )
    updated_need = replace(need, sources=need.sources + (alternate,))
    altered = replace(
        campaign,
        rank_needs=tuple(
            updated_need if item.rank == need.rank else item
            for item in campaign.rank_needs
        ),
    )
    plan = build_campaign_source_project_plan(reconstructed.state, altered)
    keys = {
        key
        for project in plan.projects
        for rank, sources in project.interchangeable_sources
        if rank == need.rank
        for key in sources
    }
    assert need.chosen.source_key in keys
    assert alternate.source_key in keys


def test_shared_helper_tasks_are_max_unioned(benchmark):
    _cards, _reconstructed, plan, _result = benchmark
    assert plan.helper_tasks
    shared = [task for task in plan.helper_tasks if task.shared]
    assert shared
    assert all(len(task.dependent_project_ids) > 1 for task in shared)
    assert len({task.column for task in plan.helper_tasks}) == len(
        plan.helper_tasks
    )
    assert len(plan.shared_helper_edges) > len(plan.helper_tasks)


def test_deeper_shared_helper_replaces_shallower_dependency(
    benchmark, monkeypatch
):
    _cards, reconstructed, _plan, _result = benchmark
    original_close = csp.close_column
    source_columns = {
        project.column: index + 1
        for index, project in enumerate(
            reconstructed.campaign.prerequisite_excavation_projects
        )
    }
    helper_column = 9

    def varied_close(state, column):
        closure = original_close(state, column)
        depth = source_columns.get(column)
        if depth is None or not closure.hop_closures:
            return closure
        first = replace(
            closure.hop_closures[0],
            prep_tasks=((helper_column, depth),),
        )
        return replace(
            closure,
            hop_closures=(first,) + closure.hop_closures[1:],
        )

    monkeypatch.setattr(csp, "close_column", varied_close)
    plan = build_campaign_source_project_plan(
        reconstructed.state, reconstructed.campaign
    )
    expected = f"helper:c{helper_column}:h{max(source_columns.values())}"
    assert tuple(task.task_id for task in plan.helper_tasks) == (expected,)
    assert all(project.helper_task_ids == (expected,) for project in plan.projects)


def test_one_helper_completion_satisfies_multiple_projects(benchmark):
    _cards, reconstructed, plan, result = benchmark
    helper = next(task for task in plan.helper_tasks if task.shared)
    helper_progress = next(
        progress for progress in result.progress if progress.phase == "helper"
    )
    helper_actions = result.actions[: helper_progress.action_count]
    checked = reconstructed.state.clone()
    replay_actions(checked, list(helper_actions))
    assert helper_task_is_satisfied(checked, helper)
    assert helper.task_id in helper_progress.helper_tasks_satisfied
    assert len(helper.dependent_project_ids) >= 2


def test_committed_source_target_persists(benchmark):
    _cards, _reconstructed, plan, result = benchmark
    assert result.committed_project_ids
    committed = result.committed_project_ids[0]
    source_progress = next(
        progress
        for progress in result.progress
        if progress.phase in ("source_advanced", "source_complete")
    )
    assert source_progress.committed_target == committed
    project = next(item for item in plan.projects if item.project_id == committed)
    assert result.source_searches[-1].target == project.source_column


def test_auxiliary_helper_preparation_moves_are_legal(benchmark):
    _cards, reconstructed, _plan, result = benchmark
    checked = reconstructed.state.clone()
    cost = replay_actions(checked, list(result.actions))
    assert cost == result.corrected_added_cost
    assert states_structurally_equal(checked, result.resulting_state)
    assert "shared-helper" in result.action_roles
    assert "source-prefix" in result.action_roles


def test_project_reanalysis_updates_source_selection(benchmark):
    _cards, _reconstructed, _plan, result = benchmark
    assert result.campaign_after is not None
    assert result.must_sources_after != result.must_sources_before
    assert result.plan_after.identity == result.plan_before.identity


def test_no_deal_three_can_occur(benchmark):
    _cards, reconstructed, _plan, result = benchmark
    assert result.deals_applied == 0
    assert ("deal",) not in result.actions
    assert len(result.resulting_state.stock) == len(reconstructed.state.stock)


def test_source_completion_hands_off_to_existing_removal_search(
    benchmark, monkeypatch
):
    cards, reconstructed, _plan, _result = benchmark
    called = []
    empty_plan = _empty_plan(reconstructed.campaign)
    monkeypatch.setattr(
        csp,
        "build_campaign_source_project_plan",
        lambda *_args, **_kwargs: empty_plan,
    )

    def fake_transition(state, campaign, _cards, **_kwargs):
        called.append((state, campaign))
        return SimpleNamespace(
            nodes_expanded=1,
            corrected_added_cost=0,
            actions=(),
            resulting_state=state.clone(),
            status=CampaignTransitionStatus.NOT_FOUND_WITHIN_BOUND,
            stop_reason="bounded removal miss is not impossibility",
        )

    monkeypatch.setattr(csp, "realize_residual_campaign_transition", fake_transition)
    result = realize_campaign_source_projects(
        reconstructed.state,
        reconstructed.campaign,
        cards,
        max_added_cost=1,
        max_nodes=10,
        time_limit_s=1,
    )
    assert called
    assert result.removal_result is not None
    assert result.status == CampaignSourceRealizationStatus.SOURCES_EXPOSED


def test_automatic_foundation_removal_is_detected(benchmark, monkeypatch):
    cards, reconstructed, _plan, _result = benchmark
    columns = [
        Column([], [Card(reconstructed.campaign.suit, rank) for rank in range(12, 0, -1)]),
        Column([], [Card(reconstructed.campaign.suit, 13)]),
    ]
    columns.extend(Column([], [Card("c", 9)]) for _ in range(8))
    state = SpiderState(
        columns,
        [Card("d", 4) for _ in range(30)],
        [_foundation("s")],
    )
    empty_plan = _empty_plan(reconstructed.campaign)
    monkeypatch.setattr(
        csp,
        "build_campaign_source_project_plan",
        lambda *_args, **_kwargs: empty_plan,
    )

    def removing_transition(start, _campaign, _cards, **_kwargs):
        end = start.clone()
        paid = replay_actions(end, [(0, 1, 12)])
        return SimpleNamespace(
            nodes_expanded=1,
            corrected_added_cost=paid,
            actions=((0, 1, 12),),
            resulting_state=end,
            status=CampaignTransitionStatus.FOUNDATION_REMOVED,
            stop_reason="foundation removed",
        )

    monkeypatch.setattr(
        csp, "realize_residual_campaign_transition", removing_transition
    )
    result = realize_campaign_source_projects(
        state,
        reconstructed.campaign,
        cards,
        max_added_cost=2,
        max_nodes=10,
        time_limit_s=1,
    )
    assert result.status == CampaignSourceRealizationStatus.FOUNDATION_REMOVED
    assert result.foundation_count_before == 1
    assert result.foundation_count_after == 2
    assert result.foundation_suits_added == (reconstructed.campaign.suit,)
    assert result.action_roles[-1] == "removal-trigger"


def test_complete_route_replays_at_equal_corrected_cost(benchmark):
    _cards, reconstructed, _plan, result = benchmark
    checked = reconstructed.opening.clone()
    actions = reconstructed.actions + result.actions
    assert replay_actions(checked, list(actions)) == (
        reconstructed.total_cost + result.corrected_added_cost
    )
    assert states_structurally_equal(checked, result.resulting_state)
    assert result.independent_replay_verified


def test_resource_limited_failure_is_not_impossibility(benchmark):
    _cards, _reconstructed, _plan, result = benchmark
    assert result.resource_limited
    assert result.status == CampaignSourceRealizationStatus.PROJECT_ADVANCED
    assert "resource_limit" in result.stop_reason
    assert "impossible" in result.stop_reason


def test_generic_module_has_no_benchmark_constants():
    source = inspect.getsource(csp).lower()
    for token in (
        "4925153",
        "canonical.moves",
        "hearts",
        "jh",
        "9h",
        "3h",
        "column 10",
        "move 10 7 11",
        "cost-47",
        "47-move",
    ):
        assert token not in source
