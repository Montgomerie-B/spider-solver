"""C1-C8 gates for exact-state project-intent coalescing."""

from __future__ import annotations

from dataclasses import replace

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.planner.anytime_controller import AnytimeControllerConfig
from spider.planner.project_intent_coalescing import (
    ProjectIntentLossClass,
    ProjectIntentSuppressionKind,
    campaign_supported_on_state,
    consider_suppressed_project_progress,
)
from spider.planner.state_service_registry import (
    ServiceSubscriberKind,
    StateServiceRegistry,
)
from spider.planner.strategic_project import (
    StrategicProjectRegistry,
)
from spider.planner.structural_investment import (
    SameCampaignContinuationCredit,
    StructuralHarvest,
    StructuralHarvestKind,
)
from spider.state_identity import canonical_state_key


def _credit(target="C#1", dependencies=("d1", "d2")):
    return SameCampaignContinuationCredit(
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


def _state(*, foundations=None) -> SpiderState:
    return SpiderState(
        [Column([], [Card("c", 8), Card("c", 7)]), Column([], [Card("d", 9)])]
        + [Column([], []) for _ in range(8)],
        [],
        foundations or [],
    )


def _clubs_foundation() -> list[Card]:
    return [Card("c", rank) for rank in range(13, 0, -1)]


class _Witness:
    def __init__(self, state, g=4):
        self.state = state
        self.g = g
        self.analysis = None
        self.node_id = 1


def _registry():
    return StateServiceRegistry(max_states=16, max_requests=32, enable_subscribers=True)


def _admit(registry, state, cost=4, credit=0):
    key = canonical_state_key(state)
    registry.admit_arrival(key, cost, _Witness(state, cost))
    return registry.request_service(key, credit)


def test_c1_tt_transfer_attaches_project_without_changing_best_cost():
    registry, projects = _registry(), StrategicProjectRegistry()
    state = _state()
    request = _admit(registry, state, cost=4)
    other = _admit(registry, _state(foundations=[_clubs_foundation()]), cost=6)
    projects.attach_continuation(
        _credit(),
        other.key,
        priority_information=(1,),
        arrival_version=1,
        expansion=1,
    )
    before_cost = registry.arrival(canonical_state_key(state)).best_cost
    before_witness = registry.arrival(canonical_state_key(state)).witness
    record = consider_suppressed_project_progress(
        registry=registry,
        projects=projects,
        campaign_id="C#1",
        project_id="ignored",
        child_key=canonical_state_key(state),
        credit=_credit(),
        expansion=3,
        suppression=ProjectIntentSuppressionKind.TT_DOMINATED,
        transfer=True,
        request_key=request.key,
        priority_information=(9,),
    )
    arrival = registry.arrival(canonical_state_key(state))
    project = projects.projects[0]
    assert record.classification is ProjectIntentLossClass.TRANSFERABLE_PROJECT_INTENT_LOST
    assert record.transferred
    assert arrival.best_cost == before_cost
    assert arrival.witness is before_witness
    assert request.key in project.candidates
    assert len(project.candidates) == 2


def test_c2_nontransferable_context_does_not_attach():
    registry, projects = _registry(), StrategicProjectRegistry()
    done = _state(foundations=[_clubs_foundation()])
    request = _admit(registry, done, cost=4)
    assert not campaign_supported_on_state(done, "C#1")
    projects.attach_continuation(
        _credit(),
        _admit(registry, _state(), cost=5).key,
        priority_information=(0,),
        arrival_version=1,
        expansion=1,
    )
    record = consider_suppressed_project_progress(
        registry=registry,
        projects=projects,
        campaign_id="C#1",
        project_id="ignored",
        child_key=canonical_state_key(done),
        credit=_credit(),
        expansion=4,
        suppression=ProjectIntentSuppressionKind.TT_DOMINATED,
        transfer=True,
        request_key=request.key,
    )
    assert record.classification is ProjectIntentLossClass.NONTRANSFERABLE_CONTEXT_ONLY_PROGRESS
    assert not record.transferred
    assert request.key not in projects.projects[0].candidates


def test_c3_already_represented_is_idempotent():
    registry, projects = _registry(), StrategicProjectRegistry()
    state = _state()
    request = _admit(registry, state, cost=4)
    project = projects.attach_continuation(
        _credit(),
        request.key,
        priority_information=(0,),
        arrival_version=1,
        expansion=1,
    )
    record = consider_suppressed_project_progress(
        registry=registry,
        projects=projects,
        campaign_id="C#1",
        project_id=project.project_id,
        child_key=canonical_state_key(state),
        credit=_credit(),
        expansion=2,
        suppression=ProjectIntentSuppressionKind.TT_DOMINATED,
        transfer=True,
        request_key=request.key,
    )
    assert record.classification is ProjectIntentLossClass.STATE_ALREADY_HAS_PROJECT_INTENT
    assert not record.transferred
    assert len(project.candidates) == 1


def test_c4_same_child_different_projects_share_one_request():
    registry, projects = _registry(), StrategicProjectRegistry()
    state = _state()
    request = _admit(registry, state, cost=4)
    consider_suppressed_project_progress(
        registry=registry,
        projects=projects,
        campaign_id="C#1",
        project_id="c",
        child_key=canonical_state_key(state),
        credit=_credit("C#1"),
        expansion=2,
        suppression=ProjectIntentSuppressionKind.SAME_EXPANSION_DEDUP,
        transfer=True,
        request_key=request.key,
    )
    consider_suppressed_project_progress(
        registry=registry,
        projects=projects,
        campaign_id="D#1",
        project_id="d",
        child_key=canonical_state_key(state),
        credit=_credit("D#1"),
        expansion=2,
        suppression=ProjectIntentSuppressionKind.SAME_EXPANSION_DEDUP,
        transfer=True,
        request_key=request.key,
    )
    assert len(projects.projects) == 2
    assert {item.target.campaign_id for item in projects.projects} == {"C#1", "D#1"}
    assert all(request.key in item.candidates for item in projects.projects)
    assert registry.request_count == 1


def test_c5_same_child_same_project_keeps_one_candidate():
    registry, projects = _registry(), StrategicProjectRegistry()
    state = _state()
    request = _admit(registry, state, cost=4)
    kwargs = dict(
        registry=registry,
        projects=projects,
        campaign_id="C#1",
        project_id="c",
        child_key=canonical_state_key(state),
        credit=_credit(),
        expansion=2,
        suppression=ProjectIntentSuppressionKind.SAME_EXPANSION_DEDUP,
        transfer=True,
        request_key=request.key,
    )
    consider_suppressed_project_progress(**kwargs)
    consider_suppressed_project_progress(**kwargs)
    assert len(projects.projects) == 1
    assert len(projects.projects[0].candidates) == 1


def test_c6_cheaper_arrival_keeps_one_project_and_updates_version():
    registry, projects = _registry(), StrategicProjectRegistry()
    state = _state()
    key = canonical_state_key(state)
    registry.admit_arrival(key, 8, _Witness(state, 8))
    request = registry.request_service(key, 0)
    project = projects.attach_continuation(
        _credit(),
        request.key,
        priority_information=(0,),
        arrival_version=1,
        expansion=1,
    )
    cheaper = registry.admit_arrival(key, 3, _Witness(state, 3))
    assert cheaper.value == "IMPROVED"
    projects.revalidate_cheaper_arrival(request.key, arrival_version=2)
    record = consider_suppressed_project_progress(
        registry=registry,
        projects=projects,
        campaign_id="C#1",
        project_id=project.project_id,
        child_key=key,
        credit=_credit(),
        expansion=4,
        suppression=ProjectIntentSuppressionKind.TT_DOMINATED,
        transfer=True,
        request_key=request.key,
    )
    assert record.classification is ProjectIntentLossClass.STATE_ALREADY_HAS_PROJECT_INTENT
    assert len(projects.projects) == 1
    assert project.candidates[request.key].arrival_version == 2
    assert registry.arrival(key).best_cost == 3


def test_c7_subscribers_share_one_request_and_handle():
    registry, projects = _registry(), StrategicProjectRegistry()
    state = _state()
    request = _admit(registry, state, cost=4)
    consider_suppressed_project_progress(
        registry=registry,
        projects=projects,
        campaign_id="C#1",
        project_id="c",
        child_key=canonical_state_key(state),
        credit=_credit(),
        expansion=2,
        suppression=ProjectIntentSuppressionKind.TT_DOMINATED,
        transfer=True,
        request_key=request.key,
        priority_information=(0,),
    )
    assert registry.activate(request.key, 11)
    projects.select_global_candidate(registry, (request.key,), expansion=3)
    assert registry.has_active_subscriber(request.key, ServiceSubscriberKind.ORDINARY)
    assert registry.has_active_subscriber(
        request.key, ServiceSubscriberKind.STRATEGIC_PROJECT_CONTINUATION
    )
    assert request.live_handle_id == 11
    assert len(registry._handles) == 1


def test_c8_transfer_has_no_proof_authority():
    registry, projects = _registry(), StrategicProjectRegistry()
    state = _state()
    request = _admit(registry, state, cost=4)
    consider_suppressed_project_progress(
        registry=registry,
        projects=projects,
        campaign_id="C#1",
        project_id="c",
        child_key=canonical_state_key(state),
        credit=_credit(),
        expansion=2,
        suppression=ProjectIntentSuppressionKind.TT_DOMINATED,
        transfer=True,
        request_key=request.key,
    )
    project = projects.projects[0]
    assert project.proof_pruning_allowed is False
    source = __import__(
        "inspect"
    ).getsource(__import__("spider.planner.project_intent_coalescing", fromlist=["consider_suppressed_project_progress"]).consider_suppressed_project_progress)
    assert "tt.admit" not in source
    assert "proof_pruning_allowed=True" not in source


def test_config_requires_project_registry():
    try:
        AnytimeControllerConfig(enable_project_intent_coalescing=True)
    except ValueError as exc:
        assert "StrategicProject" in str(exc)
    else:
        raise AssertionError("expected config error")
