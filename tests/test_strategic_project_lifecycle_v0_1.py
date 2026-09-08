"""Deterministic P1-P10 gates for StrategicProject lifecycle v0.1."""

from __future__ import annotations

from dataclasses import replace

import pytest

from spider.planner.anytime_controller import AnytimeControllerConfig
from spider.planner.state_service_registry import (
    ServiceSubscriberKind,
    ServiceStatus,
    StateServiceRegistry,
)
from spider.planner.strategic_project import (
    StrategicProjectRegistry,
    StrategicProjectStatus,
)
from spider.planner.structural_investment import (
    SameCampaignContinuationCredit,
    SameCampaignContinuationStatus,
    StructuralHarvest,
    StructuralHarvestKind,
    refresh_continuation_credit,
)


def _credit(target="campaign:A", dependencies=("d1", "d2"), **changes):
    credit = SameCampaignContinuationCredit(
        f"credit:{target}",
        target,
        f"investment:{target}",
        (
            StructuralHarvest(
                StructuralHarvestKind.DEPENDENCY_CLOSED,
                target,
                "fixture semantic harvest",
                dependency_ids=("prior",),
            ),
        ),
        tuple(dependencies),
        3,
        14,
        2,
        30.0,
        0,
        0.0,
        baseline_total_g=3,
    )
    return replace(credit, **changes)


def _registry():
    return StateServiceRegistry(
        max_states=16,
        max_requests=32,
        enable_subscribers=True,
    )


def _request(registry, state, cost=3):
    registry.admit_arrival(state, cost, {"state": state, "cost": cost})
    return registry.request_service(state, 0)


def _attach(projects, registry, request, credit=None, priority=(0,)):
    arrival = registry.arrival(request.key.state_key)
    assert arrival is not None
    return projects.attach_continuation(
        credit or _credit(),
        request.key,
        priority_information=priority,
        arrival_version=arrival.version,
        expansion=1,
    )


def _activate_and_select(projects, registry, *requests):
    for handle, request in enumerate(requests, 10):
        assert registry.activate(request.key, handle)
    return projects.select_global_candidate(
        registry,
        (item.key for item in requests),
        expansion=2,
    )


def test_p1_project_creation_has_one_semantic_campaign_target():
    registry, projects = _registry(), StrategicProjectRegistry()
    project = _attach(projects, registry, _request(registry, "state:A"))
    assert len(projects.projects) == 1
    assert project.target.campaign_id == "campaign:A"
    assert project.project_id not in {"state:A", "credit:campaign:A"}
    assert not project.proof_pruning_allowed


def test_p2_compatible_candidate_requests_merge_into_one_project():
    registry, projects = _registry(), StrategicProjectRegistry()
    first = _attach(projects, registry, _request(registry, "state:A"))
    second = _attach(projects, registry, _request(registry, "state:B"))
    assert first is second
    assert len(projects.projects) == 1
    assert len(first.candidates) == 2
    assert projects.metrics.projects_reused == 1


def test_p3_incompatible_campaign_targets_remain_separate():
    registry, projects = _registry(), StrategicProjectRegistry()
    _attach(projects, registry, _request(registry, "state:A"))
    _attach(
        projects,
        registry,
        _request(registry, "state:B"),
        _credit("campaign:B"),
    )
    assert len(projects.projects) == 2
    assert {item.target.campaign_id for item in projects.projects} == {
        "campaign:A",
        "campaign:B",
    }


def test_p4_stronger_compatible_candidate_replaces_selection_not_project():
    registry, projects = _registry(), StrategicProjectRegistry()
    weak, strong = _request(registry, "weak"), _request(registry, "strong")
    project = _attach(projects, registry, weak, priority=(9,))
    _attach(projects, registry, strong, priority=(10,))
    _activate_and_select(projects, registry, weak, strong)
    assert project.selected_candidate == weak.key
    project.candidates[strong.key].priority_information = (1,)
    projects.select_global_candidate(
        registry, (weak.key, strong.key), expansion=3
    )
    assert project.selected_candidate == strong.key
    assert projects.projects == (project,)
    assert projects.metrics.candidate_replacements == 1
    assert not registry.has_active_subscriber(
        weak.key, ServiceSubscriberKind.STRATEGIC_PROJECT_CONTINUATION
    )


def test_p5_shared_request_has_one_handle_execution_and_shared_result():
    registry, projects = _registry(), StrategicProjectRegistry()
    request = _request(registry, "shared")
    project = _attach(projects, registry, request)
    registry.subscribe(request.key, ServiceSubscriberKind.COMPLETION_CASH_OUT)
    registry.subscribe(request.key, ServiceSubscriberKind.EPOCH_TRANSITION)
    _activate_and_select(projects, registry, request)
    assert registry.begin(10).accepted
    registry.complete(request.key, outcome="SUCCESSORS_GENERATED")
    projects.observe_execution(
        request.key,
        execution_ordinal=1,
        expansion=3,
        result=request.last_execution_result,
    )
    assert request.executions == 1
    assert registry.metrics.shared_executions == 1
    results = {
        id(item.last_execution_result)
        for item in request.subscribers.values()
    }
    assert len(results) == 1
    assert project.candidates[request.key].last_execution_result is request.last_execution_result
    assert project.activity_events == 1


def test_p6_cheaper_arrival_reopens_once_and_project_survives():
    registry, projects = _registry(), StrategicProjectRegistry()
    request = _request(registry, "same", cost=8)
    project = _attach(projects, registry, request)
    _activate_and_select(projects, registry, request)
    assert registry.admit_arrival("same", 6, {"cheaper": True}).value == "IMPROVED"
    projects.revalidate_cheaper_arrival(request.key, arrival_version=2)
    assert request.status is ServiceStatus.PENDING
    assert not registry.begin(10).accepted
    assert registry.activate(request.key, 11)
    assert registry.begin(11).accepted
    assert projects.projects == (project,)
    assert projects.metrics.cheaper_arrival_revalidations == 1


def test_p7_deferred_candidate_reactivates_once_while_project_survives():
    registry, projects = _registry(), StrategicProjectRegistry()
    request = _request(registry, "deferred")
    project = _attach(projects, registry, request)
    _activate_and_select(projects, registry, request)
    assert registry.defer_handle(10)
    projects.note_deferred(request.key)
    assert project.status is StrategicProjectStatus.RUNNABLE
    assert registry.activate(request.key, 11)
    projects.note_reactivated(request.key)
    assert registry.begin(11).accepted
    registry.complete(request.key)
    assert request.executions == 1
    assert projects.metrics.candidate_defer_events == 1
    assert projects.metrics.candidate_reactivate_events == 1


@pytest.mark.parametrize(
    ("depth", "elapsed", "current_g", "reason"),
    (
        (3, 1.0, 4, "descendant-expansion envelope expired"),
        (1, 30.0, 4, "elapsed-time envelope expired"),
        (1, 1.0, 18, "maximum further paid-cost envelope expired"),
    ),
)
def test_p8_project_expiry_matches_old_event_and_releases_only_its_entitlement(
    depth, elapsed, current_g, reason
):
    registry, projects = _registry(), StrategicProjectRegistry()
    request = _request(registry, "expiry")
    project = _attach(projects, registry, request)
    _activate_and_select(projects, registry, request)
    expected = refresh_continuation_credit(
        _credit(),
        current_depth=depth,
        current_elapsed_seconds=elapsed,
        objective_still_credible=True,
        current_g=current_g,
    )
    actual = projects.revalidate_selected(
        request.key,
        current_depth=depth,
        current_elapsed_seconds=elapsed,
        objective_still_credible=True,
        fully_harvested=False,
        outstanding_dependencies=("d1", "d2"),
        current_g=current_g,
        registry=registry,
        expansion=3,
    )
    assert actual.status is expected.status is SameCampaignContinuationStatus.EXPIRED
    assert actual.expiry_reason == expected.expiry_reason == reason
    assert project.status is StrategicProjectStatus.EXHAUSTED
    assert request.status is ServiceStatus.LIVE
    assert registry.has_active_subscriber(request.key, ServiceSubscriberKind.ORDINARY)
    assert not registry.has_active_subscriber(
        request.key, ServiceSubscriberKind.STRATEGIC_PROJECT_CONTINUATION
    )


def test_p9_named_dependency_reduction_is_one_semantic_progress_event():
    registry, projects = _registry(), StrategicProjectRegistry()
    request = _request(registry, "progress")
    project = _attach(projects, registry, request)
    _activate_and_select(projects, registry, request)
    assert registry.begin(10).accepted
    projects.revalidate_selected(
        request.key,
        current_depth=1,
        current_elapsed_seconds=1.0,
        objective_still_credible=True,
        fully_harvested=False,
        outstanding_dependencies=("d2",),
        current_g=4,
        registry=registry,
        expansion=2,
    )
    registry.complete(request.key)
    projects.observe_execution(request.key, execution_ordinal=1, expansion=2)
    assert len(project.progress_evidence) == 1
    assert project.progress_evidence[0].dependencies_closed == ("d1",)
    assert projects.metrics.project_progress_events == 1


def test_p10_execution_without_target_change_is_activity_not_progress():
    registry, projects = _registry(), StrategicProjectRegistry()
    request = _request(registry, "activity")
    project = _attach(projects, registry, request)
    _activate_and_select(projects, registry, request)
    assert registry.begin(10).accepted
    projects.revalidate_selected(
        request.key,
        current_depth=1,
        current_elapsed_seconds=1.0,
        objective_still_credible=True,
        fully_harvested=False,
        outstanding_dependencies=("d1", "d2"),
        current_g=4,
        registry=registry,
        expansion=2,
    )
    registry.complete(request.key)
    projects.observe_execution(request.key, execution_ordinal=1, expansion=2)
    assert project.activity_events == 1
    assert project.progress_evidence == []
    assert projects.metrics.service_executions_without_progress == 1


def test_migration_switch_is_explicit_and_production_defaults_remain_unchanged():
    defaults = AnytimeControllerConfig()
    assert not defaults.enable_strategic_project_continuation
    with pytest.raises(ValueError, match="requires registry subscribers"):
        replace(defaults, enable_strategic_project_continuation=True)
