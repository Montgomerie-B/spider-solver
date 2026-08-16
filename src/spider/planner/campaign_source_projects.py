"""Committed source-project guidance for one fixed foundation campaign.

This module is a narrow orchestration layer over the existing target-relative
campaign closures, committed-excavation search, workspace semantics, and
campaign transition/removal beam.  It does not rank campaigns, deal stock, or
run a whole-game search.

The key distinction from a flat campaign beam is commitment: one structural
helper and then one source prefix remain selected until the predicate is
satisfied, the bounded committed search ends, resources expire, or fixed-
identity reanalysis invalidates the project.  Shared helpers are max-unioned
by column, so a single deeper completion satisfies every shallower dependent
project.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.planner.committed_excavation import (
    ProjectSearchResult,
    ProjectStatus,
    search_empty_column,
)
from spider.planner.excavation_closure import close_column
from spider.planner.foundation_campaign import (
    FoundationCampaign,
    RankSourceKind,
    analyze_foundation_campaign,
)
from spider.planner.foundation_campaign_realizer import (
    CampaignIdentity,
    campaign_target_prefix_closure,
)
from spider.planner.foundation_campaign_removal import (
    CampaignBand,
    campaign_interval_exists,
    locate_campaign_bands,
)
from spider.planner.foundation_campaign_transition import (
    CampaignTransitionResult,
    CampaignTransitionStatus,
    realize_residual_campaign_transition,
)
from spider.planner.foundation_feasibility import FOUNDATION_RANKS, current_stock_epoch
from spider.planner.space_lifecycle import empty_columns
from spider.state_identity import states_structurally_equal


class CampaignSourceRealizationStatus(str, Enum):
    FOUNDATION_REMOVED = "foundation_removed"
    SOURCES_EXPOSED = "sources_exposed"
    PROJECT_ADVANCED = "project_advanced"
    NOT_FOUND_WITHIN_BOUND = "not_found_within_bound"
    RESOURCE_LIMIT = "resource_limit"
    INVALID_CAMPAIGN = "invalid_campaign"


@dataclass(frozen=True)
class CampaignHelperTask:
    """One max-unioned helper prefix shared by source projects."""

    task_id: str
    column: int
    required_hops: int
    initial_face_down: int
    initial_cards: int
    required_face_down_reduction: int
    required_card_reduction: int
    destination_ranks: Tuple[int, ...]
    dependent_project_ids: Tuple[str, ...]
    join_distance: int
    shared: bool
    note: str


@dataclass(frozen=True)
class CampaignSourceProject:
    """Max-unioned tableau prefix for one or more remaining MUST ranks."""

    project_id: str
    source_column: int
    required_ranks: Tuple[int, ...]
    selected_source_keys: Tuple[str, ...]
    interchangeable_sources: Tuple[Tuple[int, Tuple[str, ...]], ...]
    initial_face_down: int
    initial_cards: int
    target_max_face_down: int
    required_reveals: int
    destination_ranks: Tuple[int, ...]
    helper_task_ids: Tuple[str, ...]
    requires_workspace: bool
    associated_bands: Tuple[Tuple[int, int], ...]
    join_distance: int
    shared_preparation: bool
    satisfied_ranks: Tuple[int, ...]
    current_satisfied: bool


@dataclass(frozen=True)
class CampaignSourceProjectPlan:
    identity: CampaignIdentity
    projects: Tuple[CampaignSourceProject, ...]
    helper_tasks: Tuple[CampaignHelperTask, ...]
    priority_order: Tuple[str, ...]
    protected_bands: Tuple[Tuple[int, int], ...]
    shared_helper_edges: Tuple[Tuple[str, str], ...]
    notes: Tuple[str, ...]


@dataclass(frozen=True)
class CampaignSourceProgress:
    phase: str
    committed_target: Optional[str]
    action_count: int
    corrected_added_cost: int
    helper_tasks_satisfied: Tuple[str, ...]
    source_ranks_usable: Tuple[int, ...]
    projects_satisfied: Tuple[str, ...]
    source_face_down_reductions: Tuple[Tuple[int, int], ...]
    must_source_keys: Tuple[str, ...]
    bands: Tuple[CampaignBand, ...]
    empty_columns: Tuple[int, ...]
    foundation_count: int
    note: str


@dataclass(frozen=True)
class CampaignSourceRealizationResult:
    status: CampaignSourceRealizationStatus
    identity: CampaignIdentity
    actions: Tuple[Action, ...]
    action_roles: Tuple[str, ...]
    corrected_added_cost: Optional[int]
    resulting_state: SpiderState
    campaign_before: FoundationCampaign
    campaign_after: Optional[FoundationCampaign]
    plan_before: CampaignSourceProjectPlan
    plan_after: CampaignSourceProjectPlan
    committed_project_ids: Tuple[str, ...]
    helper_tasks_before: Tuple[str, ...]
    helper_tasks_after: Tuple[str, ...]
    must_sources_before: Tuple[str, ...]
    must_sources_after: Tuple[str, ...]
    bands_before: Tuple[CampaignBand, ...]
    bands_after: Tuple[CampaignBand, ...]
    progress: Tuple[CampaignSourceProgress, ...]
    source_searches: Tuple[ProjectSearchResult, ...]
    removal_result: Optional[CampaignTransitionResult]
    nodes_expanded: int
    elapsed_seconds: float
    resource_limited: bool
    deals_applied: int
    foundation_count_before: int
    foundation_count_after: int
    foundation_suits_added: Tuple[str, ...]
    independent_replay_verified: bool
    replayed_cost: Optional[int]
    stop_reason: str


def _identity(campaign: FoundationCampaign) -> CampaignIdentity:
    if campaign.target_removal_epoch is None:
        raise ValueError("campaign has no target removal epoch")
    return CampaignIdentity(
        campaign.suit,
        campaign.copy_index,
        campaign.target_removal_epoch,
    )


def _foundation_count_for_suit(state: SpiderState, suit: str) -> int:
    return sum(
        1
        for sequence in state.foundations
        if len(sequence) == len(FOUNDATION_RANKS)
        and sequence
        and all(card.suit == suit for card in sequence)
    )


def _foundation_suits(state: SpiderState) -> Tuple[str, ...]:
    return tuple(sequence[0].suit for sequence in state.foundations if sequence)


def _rank_usable(state: SpiderState, suit: str, rank: int) -> bool:
    return any(
        band.movable and band.high_rank >= rank >= band.low_rank
        for band in locate_campaign_bands(state, suit)
    )


def _must_keys(campaign: Optional[FoundationCampaign]) -> Tuple[str, ...]:
    if campaign is None:
        return ()
    return tuple(source.source_key for source in campaign.tableau_critical_cards)


def _project_join_distance(
    ranks: Sequence[int], bands: Sequence[CampaignBand]
) -> int:
    if not ranks or not bands:
        return 99
    return min(
        min(
            abs(rank - (band.low_rank - 1)),
            abs(rank - (band.high_rank + 1)),
        )
        for rank in ranks
        for band in bands
    )


def _associated_bands(
    ranks: Sequence[int], bands: Sequence[CampaignBand]
) -> Tuple[Tuple[int, int], ...]:
    out = {
        (band.high_rank, band.low_rank)
        for rank in ranks
        for band in bands
        if rank in (band.low_rank - 1, band.high_rank + 1)
    }
    return tuple(sorted(out, reverse=True))


def build_campaign_source_project_plan(
    state: SpiderState,
    campaign: FoundationCampaign,
) -> CampaignSourceProjectPlan:
    """Convert current MUST ranks into source projects and shared helpers."""
    identity = _identity(campaign)
    bands = locate_campaign_bands(state, campaign)
    protected = tuple(
        sorted(
            {
                (band.high_rank, band.low_rank)
                for band in bands
                if band.length > 1
            },
            reverse=True,
        )
    )
    helper_acc: Dict[int, Dict[str, object]] = {}
    project_helper_columns: Dict[str, Tuple[int, ...]] = {}
    projects: List[CampaignSourceProject] = []

    for excavation in campaign.prerequisite_excavation_projects:
        project_id = (
            f"source:c{excavation.column}:"
            + "-".join(str(rank) for rank in excavation.required_ranks)
        )
        prefixes = tuple(
            campaign_target_prefix_closure(state, campaign, rank)
            for rank in excavation.required_ranks
        )
        max_face_down_values = tuple(
            prefix.max_face_down
            for prefix in prefixes
            if prefix.max_face_down is not None
        )
        target_max_face_down = (
            min(max_face_down_values)
            if max_face_down_values
            else len(state.columns[excavation.column].face_down)
        )
        interchangeable: List[Tuple[int, Tuple[str, ...]]] = []
        selected_keys: List[str] = []
        destination_ranks: set[int] = set()
        helper_columns: Dict[int, int] = {}
        requires_workspace = False

        closure = close_column(state, excavation.column)
        for rank, prefix in zip(excavation.required_ranks, prefixes):
            need = campaign.rank_need(rank)
            interchangeable.append(
                (
                    rank,
                    tuple(
                        source.source_key
                        for source in need.sources
                        if source.usable_by_target
                        and not source.reserved_by_completed_foundation
                        and source.kind != RankSourceKind.COMPLETED_FOUNDATION
                    ),
                )
            )
            if prefix.selected_source_key is not None:
                selected_keys.append(prefix.selected_source_key)
            requires_workspace = (
                requires_workspace or prefix.requires_temp_workspace
            )
            prefix_hops = max(prefix.required_reveals, prefix.required_peels)
            for hop in closure.hop_closures[:prefix_hops]:
                if hop.hop.need_rank is not None:
                    destination_ranks.add(hop.hop.need_rank)
                for helper_column, depth in hop.prep_tasks:
                    helper_columns[helper_column] = max(
                        helper_columns.get(helper_column, 0), depth
                    )
                    acc = helper_acc.setdefault(
                        helper_column,
                        {
                            "depth": 0,
                            "projects": set(),
                            "destination_ranks": set(),
                        },
                    )
                    acc["depth"] = max(int(acc["depth"]), depth)
                    projects_set = acc["projects"]
                    assert isinstance(projects_set, set)
                    projects_set.add(project_id)
                    if hop.hop.need_rank is not None:
                        helper_ranks = acc["destination_ranks"]
                        assert isinstance(helper_ranks, set)
                        helper_ranks.add(hop.hop.need_rank)

        helper_ids = tuple(
            f"helper:c{column}:h{depth}"
            for column, depth in sorted(helper_columns.items())
        )
        project_helper_columns[project_id] = tuple(sorted(helper_columns))
        satisfied_ranks = tuple(
            rank
            for rank in excavation.required_ranks
            if _rank_usable(state, campaign.suit, rank)
        )
        initial_face_down = len(state.columns[excavation.column].face_down)
        initial_cards = initial_face_down + len(
            state.columns[excavation.column].face_up
        )
        projects.append(
            CampaignSourceProject(
                project_id=project_id,
                source_column=excavation.column,
                required_ranks=excavation.required_ranks,
                selected_source_keys=tuple(sorted(selected_keys)),
                interchangeable_sources=tuple(interchangeable),
                initial_face_down=initial_face_down,
                initial_cards=initial_cards,
                target_max_face_down=target_max_face_down,
                required_reveals=max(
                    0, initial_face_down - target_max_face_down
                ),
                destination_ranks=tuple(sorted(destination_ranks)),
                helper_task_ids=helper_ids,
                requires_workspace=requires_workspace,
                associated_bands=_associated_bands(
                    excavation.required_ranks, bands
                ),
                join_distance=_project_join_distance(
                    excavation.required_ranks, bands
                ),
                shared_preparation=bool(helper_ids),
                satisfied_ranks=satisfied_ranks,
                current_satisfied=len(satisfied_ranks)
                == len(excavation.required_ranks),
            )
        )

    project_by_id = {project.project_id: project for project in projects}
    helpers: List[CampaignHelperTask] = []
    for column, raw in sorted(helper_acc.items()):
        depth = int(raw["depth"])
        dependent = tuple(sorted(raw["projects"]))
        destination_ranks = tuple(sorted(raw["destination_ranks"]))
        face_down = len(state.columns[column].face_down)
        cards = face_down + len(state.columns[column].face_up)
        join_distance = min(
            (
                project_by_id[project_id].join_distance
                for project_id in dependent
            ),
            default=99,
        )
        helpers.append(
            CampaignHelperTask(
                task_id=f"helper:c{column}:h{depth}",
                column=column,
                required_hops=depth,
                initial_face_down=face_down,
                initial_cards=cards,
                required_face_down_reduction=min(depth, face_down),
                required_card_reduction=depth if face_down == 0 else 0,
                destination_ranks=destination_ranks,
                dependent_project_ids=dependent,
                join_distance=join_distance,
                shared=len(dependent) > 1,
                note=(
                    "max-unioned helper; a deeper completion satisfies every "
                    "shallower dependency on this column"
                ),
            )
        )

    # A project's provisional helper id contains its local depth.  Normalize
    # every dependency to the max-unioned task id so one deeper helper
    # completion also satisfies all shallower dependencies on that column.
    helper_id_by_column = {task.column: task.task_id for task in helpers}
    shared_helper_ids = {task.task_id for task in helpers if task.shared}
    projects = [
        replace(
            project,
            helper_task_ids=tuple(
                helper_id_by_column[column]
                for column in project_helper_columns[project.project_id]
            ),
            shared_preparation=any(
                helper_id_by_column[column] in shared_helper_ids
                for column in project_helper_columns[project.project_id]
            ),
        )
        for project in projects
    ]
    helpers.sort(
        key=lambda task: (
            -len(task.dependent_project_ids),
            task.join_distance,
            task.column,
        )
    )
    projects.sort(
        key=lambda project: (
            project.current_satisfied,
            project.join_distance,
            -len(project.required_ranks),
            project.source_column,
        )
    )
    edges = tuple(
        sorted(
            (helper.task_id, project_id)
            for helper in helpers
            for project_id in helper.dependent_project_ids
        )
    )
    priority = tuple(helper.task_id for helper in helpers) + tuple(
        project.project_id for project in projects
    )
    return CampaignSourceProjectPlan(
        identity=identity,
        projects=tuple(projects),
        helper_tasks=tuple(helpers),
        priority_order=priority,
        protected_bands=protected,
        shared_helper_edges=edges,
        notes=(
            "helper ordering uses dependent-project count, nearest join, then column",
            "source projects use interchangeable structural rank predicates",
            "campaign estimates and portfolio scores are not modified",
        ),
    )


def helper_task_is_satisfied(
    state: SpiderState, task: CampaignHelperTask
) -> bool:
    """Whether the committed helper prefix has structurally advanced enough."""
    column = state.columns[task.column]
    if column.is_empty():
        return True
    face_down_reduction = task.initial_face_down - len(column.face_down)
    current_cards = len(column.face_down) + len(column.face_up)
    card_reduction = task.initial_cards - current_cards
    return bool(
        (
            task.required_face_down_reduction > 0
            and face_down_reduction >= task.required_face_down_reduction
        )
        or (
            task.required_card_reduction > 0
            and card_reduction >= task.required_card_reduction
        )
    )


def source_project_is_satisfied(
    state: SpiderState,
    campaign: FoundationCampaign,
    project: CampaignSourceProject,
) -> bool:
    """Physical copies are interchangeable; only rank usability is required."""
    return all(
        _rank_usable(state, campaign.suit, rank)
        for rank in project.required_ranks
    )


def _protected_bands_intact(
    state: SpiderState,
    campaign: FoundationCampaign,
    protected: Sequence[Tuple[int, int]],
) -> bool:
    # Covering is permitted during excavation; splitting or destroying an
    # intact campaign interval is not.
    return all(
        campaign_interval_exists(
            state,
            campaign.suit,
            high,
            low,
            movable=False,
        )
        for high, low in protected
    )


def _project_progress_key(
    state: SpiderState,
    campaign: FoundationCampaign,
    project: CampaignSourceProject,
) -> Tuple[int, int, int]:
    usable = sum(
        _rank_usable(state, campaign.suit, rank)
        for rank in project.required_ranks
    )
    column = state.columns[project.source_column]
    face_down_reduction = project.initial_face_down - len(column.face_down)
    cards_reduction = project.initial_cards - (
        len(column.face_down) + len(column.face_up)
    )
    return usable, face_down_reduction, cards_reduction


def _candidate_fragment(
    start: SpiderState,
    result: ProjectSearchResult,
) -> Tuple[Tuple[Action, ...], Optional[SpiderState], Optional[int]]:
    if result.status == ProjectStatus.FOUND and result.actions:
        actions = tuple(result.actions)
    elif result.near is not None and result.near.actions:
        actions = tuple(result.near.actions)
    else:
        return (), None, None
    checked = start.clone()
    try:
        cost = replay_actions(checked, list(actions))
    except ValueError:
        return (), None, None
    return actions, checked, cost


def _fixed_reanalysis(
    state: SpiderState,
    identity: CampaignIdentity,
    cards: Sequence[Card],
) -> Optional[FoundationCampaign]:
    if _foundation_count_for_suit(state, identity.suit) >= identity.copy_index:
        return None
    try:
        return analyze_foundation_campaign(
            state,
            cards=cards,
            suit=identity.suit,
            copy_index=identity.copy_index,
            target_epoch=identity.target_epoch,
        )
    except ValueError:
        return None


def _progress_snapshot(
    *,
    phase: str,
    committed_target: Optional[str],
    state: SpiderState,
    campaign: FoundationCampaign,
    plan: CampaignSourceProjectPlan,
    actions: Sequence[Action],
    cost: int,
    note: str,
    completed_helper_ids: Sequence[str] = (),
) -> CampaignSourceProgress:
    completed_helpers = set(completed_helper_ids)
    helper_done = tuple(
        task.task_id
        for task in plan.helper_tasks
        if task.task_id in completed_helpers
        or helper_task_is_satisfied(state, task)
    )
    ranks = tuple(
        sorted(
            {
                rank
                for project in plan.projects
                for rank in project.required_ranks
                if _rank_usable(state, campaign.suit, rank)
            },
            reverse=True,
        )
    )
    projects_done = tuple(
        project.project_id
        for project in plan.projects
        if source_project_is_satisfied(state, campaign, project)
    )
    reductions = tuple(
        (
            project.source_column,
            max(
                0,
                project.initial_face_down
                - len(state.columns[project.source_column].face_down),
            ),
        )
        for project in plan.projects
    )
    return CampaignSourceProgress(
        phase=phase,
        committed_target=committed_target,
        action_count=len(actions),
        corrected_added_cost=cost,
        helper_tasks_satisfied=helper_done,
        source_ranks_usable=ranks,
        projects_satisfied=projects_done,
        source_face_down_reductions=reductions,
        must_source_keys=_must_keys(campaign),
        bands=locate_campaign_bands(state, campaign),
        empty_columns=tuple(empty_columns(state)),
        foundation_count=len(state.foundations),
        note=note,
    )


def _action_roles(
    start: SpiderState,
    actions: Sequence[Action],
    *,
    suit: str,
    helper_columns: Sequence[int],
    source_columns: Sequence[int],
) -> Tuple[str, ...]:
    state = start.clone()
    out: List[str] = []
    for action in actions:
        before_foundations = len(state.foundations)
        before_empty = tuple(empty_columns(state))
        if action == ("deal",):
            role = "deal"
        else:
            src, _dst, _count = action
            if src in helper_columns:
                role = "shared-helper"
            elif src in source_columns:
                role = "source-prefix"
            else:
                role = "auxiliary"
        replay_actions(state, [action])
        if len(state.foundations) > before_foundations:
            role = "removal-trigger"
        elif tuple(empty_columns(state)) != before_empty and role == "auxiliary":
            role = "workspace"
        out.append(role)
    return tuple(out)


def realize_campaign_source_projects(
    start_state: SpiderState,
    campaign: FoundationCampaign,
    cards: Sequence[Card],
    *,
    max_added_cost: int = 20,
    max_nodes: int = 80_000,
    time_limit_s: float = 30.0,
    branch_cap: int = 24,
    removal_beam_width: int = 512,
) -> CampaignSourceRealizationResult:
    """Realize committed helpers/source prefixes, then reuse removal search."""
    started = time.perf_counter()
    try:
        identity = _identity(campaign)
    except ValueError:
        identity = CampaignIdentity(campaign.suit, campaign.copy_index, -1)
        empty_plan = CampaignSourceProjectPlan(
            identity, (), (), (), (), (), ("invalid campaign",)
        )
        return CampaignSourceRealizationResult(
            CampaignSourceRealizationStatus.INVALID_CAMPAIGN,
            identity,
            (),
            (),
            None,
            start_state.clone(),
            campaign,
            None,
            empty_plan,
            empty_plan,
            (),
            (),
            (),
            _must_keys(campaign),
            (),
            (),
            (),
            (),
            (),
            None,
            0,
            time.perf_counter() - started,
            False,
            0,
            len(start_state.foundations),
            len(start_state.foundations),
            (),
            False,
            None,
            "campaign has no target removal epoch",
        )

    invalid = bool(
        campaign.current_epoch != current_stock_epoch(start_state, 5)
        or identity.target_epoch > campaign.current_epoch
        or max_added_cost < 0
        or max_nodes <= 0
        or time_limit_s <= 0
    )
    plan_before = build_campaign_source_project_plan(start_state, campaign)
    if invalid:
        return CampaignSourceRealizationResult(
            CampaignSourceRealizationStatus.INVALID_CAMPAIGN,
            identity,
            (),
            (),
            None,
            start_state.clone(),
            campaign,
            campaign,
            plan_before,
            plan_before,
            (),
            tuple(task.task_id for task in plan_before.helper_tasks),
            (),
            _must_keys(campaign),
            _must_keys(campaign),
            locate_campaign_bands(start_state, campaign),
            locate_campaign_bands(start_state, campaign),
            (),
            (),
            None,
            0,
            time.perf_counter() - started,
            False,
            0,
            len(start_state.foundations),
            len(start_state.foundations),
            (),
            False,
            None,
            "fixed campaign must remain in the current stock epoch",
        )

    state = start_state.clone()
    current = campaign
    actions: List[Action] = []
    committed_ids: List[str] = []
    searches: List[ProjectSearchResult] = []
    nodes = 0
    cost = 0
    resource_limited = False
    stop_reason = ""
    plan = plan_before
    completed_helper_ids = {
        task.task_id
        for task in plan.helper_tasks
        if helper_task_is_satisfied(state, task)
    }
    progress: List[CampaignSourceProgress] = [
        _progress_snapshot(
            phase="initial",
            committed_target=None,
            state=state,
            campaign=current,
            plan=plan_before,
            actions=actions,
            cost=cost,
            note="fixed campaign and shared-helper graph frozen",
            completed_helper_ids=completed_helper_ids,
        )
    ]
    removal_result: Optional[CampaignTransitionResult] = None

    while True:
        incomplete = next(
            (
                project
                for project in plan.projects
                if not source_project_is_satisfied(state, current, project)
            ),
            None,
        )
        if incomplete is None:
            break
        if incomplete.project_id not in committed_ids:
            committed_ids.append(incomplete.project_id)

        helper_by_id = {task.task_id: task for task in plan.helper_tasks}
        helper_failed = False
        for helper_id in incomplete.helper_task_ids:
            helper = helper_by_id.get(helper_id)
            if helper is None:
                continue
            if (
                helper_id in completed_helper_ids
                or helper_task_is_satisfied(state, helper)
            ):
                completed_helper_ids.add(helper_id)
                continue
            remaining_cost = max_added_cost - cost
            remaining_nodes = max_nodes - nodes
            remaining_time = time_limit_s - (time.perf_counter() - started)
            if remaining_cost < 0 or remaining_nodes <= 0 or remaining_time <= 0:
                resource_limited = True
                stop_reason = "resource limit before committed helper; miss is not impossibility"
                helper_failed = True
                break
            helper_search = search_empty_column(
                state,
                helper.column,
                max_cost=remaining_cost,
                max_nodes=max(1, remaining_nodes),
                time_limit_s=max(0.01, remaining_time),
                branch_cap=branch_cap,
            )
            searches.append(helper_search)
            nodes += helper_search.nodes
            resource_limited = resource_limited or (
                helper_search.status == ProjectStatus.RESOURCE_LIMIT
            )
            fragment, checked, fragment_cost = _candidate_fragment(
                state, helper_search
            )
            if (
                not fragment
                or checked is None
                or fragment_cost is None
                or cost + fragment_cost > max_added_cost
                or not helper_task_is_satisfied(checked, helper)
                or not _protected_bands_intact(
                    checked, current, plan_before.protected_bands
                )
            ):
                stop_reason = (
                    "; ".join(helper_search.notes)
                    or "committed helper did not satisfy its structural predicate"
                )
                helper_failed = True
                break
            state = checked
            actions.extend(fragment)
            cost += fragment_cost
            completed_helper_ids.add(helper.task_id)
            progress.append(
                _progress_snapshot(
                    phase="helper",
                    committed_target=helper.task_id,
                    state=state,
                    campaign=current,
                    plan=plan_before,
                    actions=actions,
                    cost=cost,
                    note=(
                        f"completed helper for {len(helper.dependent_project_ids)} "
                        "dependent source project(s)"
                    ),
                    completed_helper_ids=completed_helper_ids,
                )
            )
        if helper_failed:
            break

        remaining_cost = max_added_cost - cost
        remaining_nodes = max_nodes - nodes
        remaining_time = time_limit_s - (time.perf_counter() - started)
        if remaining_cost < 0 or remaining_nodes <= 0 or remaining_time <= 0:
            resource_limited = True
            stop_reason = "resource limit before committed source prefix; miss is not impossibility"
            break
        before_key = _project_progress_key(state, current, incomplete)
        source_search = search_empty_column(
            state,
            incomplete.source_column,
            max_cost=remaining_cost,
            max_nodes=max(1, remaining_nodes),
            time_limit_s=max(0.01, remaining_time),
            branch_cap=branch_cap,
        )
        searches.append(source_search)
        nodes += source_search.nodes
        resource_limited = resource_limited or (
            source_search.status == ProjectStatus.RESOURCE_LIMIT
        )
        fragment, checked, fragment_cost = _candidate_fragment(
            state, source_search
        )
        progressed = bool(
            fragment
            and checked is not None
            and fragment_cost is not None
            and cost + fragment_cost <= max_added_cost
            and _project_progress_key(checked, current, incomplete) > before_key
            and _protected_bands_intact(
                checked, current, plan_before.protected_bands
            )
        )
        if not progressed:
            stop_reason = (
                "; ".join(source_search.notes)
                or "committed source prefix made no structural progress"
            )
            break
        assert checked is not None and fragment_cost is not None
        state = checked
        actions.extend(fragment)
        cost += fragment_cost
        complete = source_project_is_satisfied(state, current, incomplete)
        progress.append(
            _progress_snapshot(
                phase="source_complete" if complete else "source_advanced",
                committed_target=incomplete.project_id,
                state=state,
                campaign=current,
                plan=plan_before,
                actions=actions,
                cost=cost,
                note=source_search.notes[-1] if source_search.notes else "source search ended",
                completed_helper_ids=completed_helper_ids,
            )
        )
        if not complete:
            stop_reason = (
                "committed source prefix advanced but remains incomplete; "
                + (source_search.notes[-1] if source_search.notes else "bounded search ended")
            )
            break
        updated = _fixed_reanalysis(state, identity, cards)
        if updated is None:
            stop_reason = "fixed campaign removed or invalid after source completion"
            break
        current = updated
        plan = build_campaign_source_project_plan(state, current)

    sources_exposed = not any(
        not source_project_is_satisfied(state, current, project)
        for project in plan.projects
    )
    if sources_exposed and _foundation_count_for_suit(
        state, identity.suit
    ) < identity.copy_index:
        remaining_cost = max_added_cost - cost
        remaining_nodes = max_nodes - nodes
        remaining_time = time_limit_s - (time.perf_counter() - started)
        if remaining_cost >= 0 and remaining_nodes > 0 and remaining_time > 0:
            removal_result = realize_residual_campaign_transition(
                state,
                current,
                cards,
                max_added_cost=remaining_cost,
                max_nodes=remaining_nodes,
                time_limit_s=remaining_time,
                beam_width=removal_beam_width,
            )
            nodes += removal_result.nodes_expanded
            if removal_result.corrected_added_cost is not None:
                actions.extend(removal_result.actions)
                cost += removal_result.corrected_added_cost
                state = removal_result.resulting_state.clone()
            resource_limited = resource_limited or (
                removal_result.status == CampaignTransitionStatus.RESOURCE_LIMIT
            )
            stop_reason = removal_result.stop_reason
        else:
            resource_limited = remaining_time <= 0 or remaining_nodes <= 0
            stop_reason = "sources exposed but no bounded resource remains for removal"

    current_after = _fixed_reanalysis(state, identity, cards)
    if current_after is not None:
        current = current_after
        plan_after = build_campaign_source_project_plan(state, current)
    else:
        plan_after = CampaignSourceProjectPlan(
            identity,
            (),
            (),
            (),
            (),
            (),
            ("fixed campaign no longer outstanding",),
        )

    replayed = start_state.clone()
    replayed_cost: Optional[int]
    replay_ok = False
    try:
        replayed_cost = replay_actions(replayed, list(actions))
        replay_ok = bool(
            replayed_cost == cost
            and states_structurally_equal(replayed, state)
            and ("deal",) not in actions
        )
    except ValueError:
        replayed_cost = None

    before_foundations = len(start_state.foundations)
    before_suit = _foundation_count_for_suit(start_state, identity.suit)
    after_suit = _foundation_count_for_suit(state, identity.suit)
    suits_before = _foundation_suits(start_state)
    suits_after = _foundation_suits(state)
    suits_added = suits_after[len(suits_before) :]
    exact_removed = bool(
        replay_ok
        and len(state.foundations) == before_foundations + 1
        and after_suit == before_suit + 1
        and suits_added == (identity.suit,)
    )
    any_project_progress = any(
        snapshot.phase in ("helper", "source_advanced", "source_complete")
        for snapshot in progress
    )
    if exact_removed:
        status = CampaignSourceRealizationStatus.FOUNDATION_REMOVED
        stop_reason = "fixed campaign foundation removed and independently replayed"
    elif sources_exposed:
        status = CampaignSourceRealizationStatus.SOURCES_EXPOSED
    elif any_project_progress:
        status = CampaignSourceRealizationStatus.PROJECT_ADVANCED
    elif resource_limited:
        status = CampaignSourceRealizationStatus.RESOURCE_LIMIT
    else:
        status = CampaignSourceRealizationStatus.NOT_FOUND_WITHIN_BOUND

    helper_columns = tuple(task.column for task in plan_before.helper_tasks)
    source_columns = tuple(project.source_column for project in plan_before.projects)
    roles = _action_roles(
        start_state,
        actions,
        suit=identity.suit,
        helper_columns=helper_columns,
        source_columns=source_columns,
    )
    progress.append(
        _progress_snapshot(
            phase="complete" if exact_removed else "stopped",
            committed_target=committed_ids[-1] if committed_ids else None,
            state=state,
            campaign=current_after or campaign,
            plan=plan_before,
            actions=actions,
            cost=cost,
            note=stop_reason,
            completed_helper_ids=completed_helper_ids,
        )
    )
    return CampaignSourceRealizationResult(
        status=status,
        identity=identity,
        actions=tuple(actions),
        action_roles=roles,
        corrected_added_cost=cost if replay_ok else None,
        resulting_state=state.clone(),
        campaign_before=campaign,
        campaign_after=current_after,
        plan_before=plan_before,
        plan_after=plan_after,
        committed_project_ids=tuple(committed_ids),
        helper_tasks_before=tuple(
            task.task_id
            for task in plan_before.helper_tasks
            if helper_task_is_satisfied(start_state, task)
        ),
        helper_tasks_after=tuple(
            task.task_id
            for task in plan_before.helper_tasks
            if task.task_id in completed_helper_ids
            or helper_task_is_satisfied(state, task)
        ),
        must_sources_before=_must_keys(campaign),
        must_sources_after=_must_keys(current_after),
        bands_before=locate_campaign_bands(start_state, campaign),
        bands_after=locate_campaign_bands(state, identity.suit),
        progress=tuple(progress),
        source_searches=tuple(searches),
        removal_result=removal_result,
        nodes_expanded=nodes,
        elapsed_seconds=time.perf_counter() - started,
        resource_limited=resource_limited,
        deals_applied=sum(1 for action in actions if action == ("deal",)),
        foundation_count_before=before_foundations,
        foundation_count_after=len(state.foundations),
        foundation_suits_added=suits_added,
        independent_replay_verified=replay_ok,
        replayed_cost=replayed_cost,
        stop_reason=stop_reason,
    )
