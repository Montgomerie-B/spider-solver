"""Bounded coordinator for converting primitive tactics into one milestone."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Callable, Optional, Tuple

from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.planner.milestone_actionability import ResidualMilestoneTarget
from spider.planner.strategic_milestone import (
    MilestoneRealizationResult,
    StrategicMilestone,
    StrategicMilestoneProgress,
    StrategicMilestoneStatus,
    classify_milestone_outcome,
    milestone_target_identity,
)
from spider.state_identity import states_structurally_equal


@dataclass(frozen=True)
class MilestonePrimitiveStep:
    actions: Tuple[Action, ...]
    end_state: SpiderState
    corrected_paid_cost: int
    tactical_nodes: int
    harvest_events: Tuple[str, ...]
    independently_replay_verified: bool
    reason: str
    workspace_created: bool = False
    workspace_used: bool = False
    workspace_recovered_or_replaced: bool = False


@dataclass(frozen=True)
class FreshMilestoneAssessment:
    milestone: Optional[StrategicMilestone]
    progress: StrategicMilestoneProgress
    contradicted: bool = False
    superseded: bool = False
    reason: str = "fresh milestone analysis"
    residual_target: Optional[ResidualMilestoneTarget] = None
    structural_progress: bool = False


PrimitiveProvider = Callable[[SpiderState, StrategicMilestone, int, int, float], Optional[MilestonePrimitiveStep]]
FreshAnalyzer = Callable[[SpiderState, StrategicMilestone], FreshMilestoneAssessment]


def _verify_step(start: SpiderState, step: MilestonePrimitiveStep) -> bool:
    if not step.independently_replay_verified or not step.actions:
        return False
    replay = start.clone()
    try:
        cost = replay_actions(replay, list(step.actions))
    except (ValueError, IndexError):
        return False
    return cost == step.corrected_paid_cost and states_structurally_equal(replay, step.end_state)


def realize_milestone(
    start_state: SpiderState,
    milestone: StrategicMilestone,
    primitive_provider: PrimitiveProvider,
    fresh_analyzer: FreshAnalyzer,
    *,
    max_primitive_steps: Optional[int] = None,
    max_tactical_nodes: Optional[int] = None,
    time_limit_s: Optional[float] = None,
) -> MilestoneRealizationResult:
    """Chain existing primitive work with mandatory fresh analysis per step."""
    started = time.perf_counter()
    step_limit = min(milestone.max_primitive_steps, max_primitive_steps or milestone.max_primitive_steps)
    node_limit = min(milestone.max_tactical_nodes, max_tactical_nodes or milestone.max_tactical_nodes)
    seconds = min(milestone.max_elapsed_seconds, time_limit_s or milestone.max_elapsed_seconds)
    state = start_state.clone()
    active = milestone
    actions = []
    cost = 0
    nodes = 0
    harvest = []
    residual_timeline = []
    blocker_transitions = []
    previous_blockers: Tuple[str, ...] = ()
    reanalyses = 0
    primitive_invocations = 0
    status = active.status
    reason = "bounded primitive envelope exhausted"
    for index in range(step_limit):
        elapsed = time.perf_counter() - started
        if elapsed >= seconds or nodes >= node_limit:
            status = StrategicMilestoneStatus.BOUNDED_MISS
            reason = "milestone time/node envelope exhausted"
            break
        step = primitive_provider(state, active, node_limit - nodes, step_limit - index, seconds - elapsed)
        if step is None:
            status = StrategicMilestoneStatus.BOUNDED_MISS
            reason = "no relevant v0.8 tactical grant or primitive remained"
            break
        primitive_invocations += 1
        if not _verify_step(state, step):
            status = StrategicMilestoneStatus.INVALIDATED
            reason = "primitive edge failed independent replay"
            break
        state = step.end_state.clone()
        actions.extend(step.actions)
        cost += step.corrected_paid_cost
        nodes += step.tactical_nodes
        harvest.extend(step.harvest_events)
        if (
            step.workspace_created
            or step.workspace_used
            or step.workspace_recovered_or_replaced
        ):
            active = replace(
                active,
                progress=replace(
                    active.progress,
                    workspace_created=(
                        active.progress.workspace_created or step.workspace_created
                    ),
                    workspace_used=(
                        active.progress.workspace_used or step.workspace_used
                    ),
                    workspace_recovered_or_replaced=(
                        active.progress.workspace_recovered_or_replaced
                        or step.workspace_recovered_or_replaced
                    ),
                ),
            )
        fresh = fresh_analyzer(state, active)
        reanalyses += 1
        if fresh.residual_target is not None:
            residual_timeline.append(fresh.residual_target.summary)
            blockers = tuple(item.value for item in fresh.residual_target.blockers)
            if previous_blockers and blockers != previous_blockers:
                blocker_transitions.append(
                    f"{','.join(previous_blockers) or 'none'} -> {','.join(blockers) or 'none'}"
                )
            previous_blockers = blockers
        if fresh.superseded:
            status = StrategicMilestoneStatus.SUPERSEDED
            active = replace(active, progress=fresh.progress, status=status)
            reason = fresh.reason
            break
        if fresh.contradicted or fresh.milestone is None:
            status = StrategicMilestoneStatus.INVALIDATED
            active = replace(active, progress=fresh.progress, status=status)
            reason = fresh.reason
            break
        previous = active.progress
        active = replace(fresh.milestone, progress=fresh.progress)
        if fresh.progress.complete:
            status = StrategicMilestoneStatus.ACHIEVED
            active = replace(active, status=status)
            reason = fresh.reason
            break
        if (
            fresh.progress.satisfied_units > previous.satisfied_units
            or fresh.structural_progress
        ):
            status = StrategicMilestoneStatus.ADVANCED
            active = replace(active, status=status)
            reason = fresh.reason
        else:
            status = StrategicMilestoneStatus.BOUNDED_MISS
            active = replace(active, status=status)
            reason = "fresh analysis found no progress toward the same target"
            break
    else:
        if status not in (
            StrategicMilestoneStatus.ACHIEVED,
            StrategicMilestoneStatus.INVALIDATED,
            StrategicMilestoneStatus.ADVANCED,
        ):
            status = StrategicMilestoneStatus.BOUNDED_MISS
            active = replace(active, status=status)
    verified = bool(actions)
    if verified:
        replay = start_state.clone()
        try:
            verified = replay_actions(replay, list(actions)) == cost and states_structurally_equal(replay, state)
        except (ValueError, IndexError):
            verified = False
    return MilestoneRealizationResult(
        active,
        status,
        tuple(actions),
        cost,
        state,
        primitive_invocations,
        nodes,
        time.perf_counter() - started,
        verified,
        reanalyses,
        tuple(harvest),
        reason,
        outcome_kind=classify_milestone_outcome(active, status),
        target_identity=milestone_target_identity(active),
        residual_timeline=tuple(residual_timeline),
        blocker_transitions=tuple(blocker_transitions),
    )
