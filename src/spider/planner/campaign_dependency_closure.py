"""Bounded same-epoch dependency closure for one named foundation campaign.

The realiser is deliberately narrower than a tableau cleaner or a second
whole-game solver.  Every admitted tableau action must cite one unresolved
dependency of the named campaign.  Bounded misses, graph facts, lifecycle
debt, and cache entries are heuristic evidence only and never proof pruning.
"""

from __future__ import annotations

import hashlib
import heapq
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Mapping, MutableMapping, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.move_lifecycle import MoveLifecycleAssessment, PlacementClass, assess_tableau_move
from spider.planner.analysis_budget import SearchDeadline
from spider.planner.foundation_campaign import FoundationCampaign
from spider.planner.foundation_campaign_removal import (
    CampaignBand,
    bands_can_join,
    locate_campaign_bands,
)
from spider.planner.supply_consumption import (
    SupplyConsumptionResult,
    SupplyConsumptionStage,
    advance_supply_consumption_results,
)
from spider.rules import MW_RULES
from spider.state_identity import CanonicalStateKey, canonical_state_key, states_structurally_equal


class CampaignDependencyType(str, Enum):
    SOURCE_BURIED = "SOURCE_BURIED"
    SOURCE_EXPOSED_BUT_BLOCKED = "SOURCE_EXPOSED_BUT_BLOCKED"
    MISSING_SAME_SUIT_INTERVAL = "MISSING_SAME_SUIT_INTERVAL"
    MIXED_OVERLAY = "MIXED_OVERLAY"
    RECEIVER_MISSING = "RECEIVER_MISSING"
    WORKSPACE_REQUIRED = "WORKSPACE_REQUIRED"
    SUPPLIED_NOT_CONSUMED = "SUPPLIED_NOT_CONSUMED"
    FRAGMENT_ORDERING = "FRAGMENT_ORDERING"
    TERMINAL_ASSEMBLY_PREREQUISITE = "TERMINAL_ASSEMBLY_PREREQUISITE"


class DependencyClosureStatus(str, Enum):
    FOUNDATION_REMOVED = "FOUNDATION_REMOVED"
    DEPENDENCY_CLOSED = "DEPENDENCY_CLOSED"
    SUPPLY_CONSUMED = "SUPPLY_CONSUMED"
    MILESTONE_REACHED = "MILESTONE_REACHED"
    NO_PROGRESS_WITHIN_BOUND = "NO_PROGRESS_WITHIN_BOUND"
    BLOCKED_BY_RECEIVER = "BLOCKED_BY_RECEIVER"
    BLOCKED_BY_WORKSPACE = "BLOCKED_BY_WORKSPACE"
    BLOCKED_BY_OVERLAY = "BLOCKED_BY_OVERLAY"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True)
class DependencyClosureConfig:
    max_added_cost: int = 14
    max_nodes: int = 4_000
    time_limit_s: float = 2.0
    beam_width: int = 192
    permit_stock_transition: bool = False
    require_bounded_park_exit: bool = True

    def __post_init__(self) -> None:
        if self.max_added_cost <= 0 or self.max_nodes <= 0 or self.time_limit_s <= 0:
            raise ValueError("dependency-closure resources must be positive")
        if self.beam_width <= 0:
            raise ValueError("dependency-closure beam width must be positive")

    def fingerprint(self) -> Tuple[int, int, int, int, int, int]:
        return (
            self.max_added_cost,
            self.max_nodes,
            int(round(self.time_limit_s * 1_000)),
            self.beam_width,
            int(self.permit_stock_transition),
            int(self.require_bounded_park_exit),
        )


@dataclass(frozen=True)
class MixedOverlayBlocker:
    blocker_id: str
    campaign_id: str
    band_label: str
    column: int
    covering_cards: Tuple[Card, ...]
    covering_groups: int
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class CampaignDependency:
    dependency_id: str
    kind: CampaignDependencyType
    campaign_id: str
    description: str
    card: Optional[Card] = None
    rank_interval: Optional[Tuple[int, int]] = None
    column: Optional[int] = None
    depth: int = 0
    source_key: Optional[str] = None
    prerequisites: Tuple[str, ...] = ()
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class CampaignDependencyGraph:
    state_key: CanonicalStateKey
    campaign_id: str
    dependencies: Tuple[CampaignDependency, ...]
    edges: Tuple[Tuple[str, str], ...]
    mixed_overlays: Tuple[MixedOverlayBlocker, ...]
    terminal_dependency_id: str
    graph_hash: str
    proof_pruning_allowed: bool = False

    @property
    def dependency_ids(self) -> Tuple[str, ...]:
        return tuple(item.dependency_id for item in self.dependencies)

    def count(self, kind: CampaignDependencyType) -> int:
        return sum(item.kind == kind for item in self.dependencies)


@dataclass(frozen=True)
class DependencyClosureStep:
    action: Action
    paid_cost: int
    targeted_dependencies: Tuple[str, ...]
    rationale: str
    lifecycle: Optional[MoveLifecycleAssessment]
    dependencies_before: int
    dependencies_after: int
    overlays_before: int
    overlays_after: int
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class DependencyClosureAssessment:
    graph: CampaignDependencyGraph
    unresolved_by_type: Tuple[Tuple[CampaignDependencyType, int], ...]
    deepest_source: int
    movable_same_suit_coverage: int
    supplied_not_consumed: int
    near_terminal: bool
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class DependencyClosureResult:
    status: DependencyClosureStatus
    campaign_id: str
    actions: Tuple[Action, ...]
    corrected_added_cost: Optional[int]
    end_state: SpiderState
    graph_before: CampaignDependencyGraph
    graph_after: CampaignDependencyGraph
    dependencies_closed: Tuple[str, ...]
    overlays_cleared: Tuple[str, ...]
    steps: Tuple[DependencyClosureStep, ...]
    supply_consumptions: Tuple[SupplyConsumptionResult, ...]
    nodes_expanded: int
    elapsed_seconds: float
    independent_replay_verified: bool
    reason: str
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class DependencyClosureCacheKey:
    state_key: CanonicalStateKey
    campaign_id: str
    config_fingerprint: Tuple[int, ...]
    supply_fingerprint: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()


DependencyClosureCache = MutableMapping[DependencyClosureCacheKey, DependencyClosureResult]


def _face_up_source(
    state: SpiderState, card: Card
) -> Optional[Tuple[int, int, int, bool]]:
    candidates = []
    for column, tableau in enumerate(state.columns):
        for index, current in enumerate(tableau.face_up):
            if current != card:
                continue
            suffix = tableau.face_up[index:]
            exposed = SpiderState.is_movable_run(suffix)
            depth = len(tableau.face_up) - 1 - index
            candidates.append((not exposed, depth, column, index, exposed))
    if not candidates:
        return None
    _blocked, depth, column, index, exposed = min(candidates)
    return column, index, depth, exposed


def _face_down_source(state: SpiderState, card: Card) -> Optional[Tuple[int, int]]:
    candidates = []
    for column, tableau in enumerate(state.columns):
        for index, current in enumerate(tableau.face_down):
            if current == card:
                depth = len(tableau.face_down) - index + max(1, bool(tableau.face_up))
                candidates.append((depth, column))
    return min(candidates) if candidates else None


def _source_has_receiver(state: SpiderState, column: int, index: int) -> bool:
    count = len(state.columns[column].face_up) - index
    return any(state.can_move(column, dst, count) for dst in range(len(state.columns)))


def _rank_intervals(ranks: Sequence[int]) -> Tuple[Tuple[int, int], ...]:
    ordered = sorted(set(ranks), reverse=True)
    if not ordered:
        return ()
    out = []
    high = low = ordered[0]
    for rank in ordered[1:]:
        if low - 1 == rank:
            low = rank
        else:
            out.append((high, low))
            high = low = rank
    out.append((high, low))
    return tuple(out)


def _covering_groups(cards: Sequence[Card]) -> int:
    groups = 0
    previous = None
    for card in cards:
        if previous is None or previous.suit != card.suit or previous.rank - 1 != card.rank:
            groups += 1
        previous = card
    return groups


def _supply_unconsumed(
    campaign_id: str,
    results: Sequence[SupplyConsumptionResult],
) -> Tuple[Tuple[SupplyConsumptionResult, object, object], ...]:
    out = []
    for result in results:
        if result.campaign_id != campaign_id:
            continue
        for obligation, evidence in zip(result.obligations, result.evidence):
            if evidence.stage not in (
                SupplyConsumptionStage.CONSUMED,
                SupplyConsumptionStage.INTEGRATED,
                SupplyConsumptionStage.INVALIDATED,
                SupplyConsumptionStage.EXPIRED,
            ):
                out.append((result, obligation, evidence))
    return tuple(out)


def build_campaign_dependency_graph(
    state: SpiderState,
    campaign: FoundationCampaign,
    *,
    supply_consumptions: Sequence[SupplyConsumptionResult] = (),
) -> CampaignDependencyGraph:
    """Build a deterministic, inspectable graph for one live campaign."""
    dependencies = []
    edges = []
    overlays = []
    campaign_id = campaign.label
    bands = locate_campaign_bands(state, campaign.suit)

    required_ranks = tuple(
        need.rank for need in campaign.rank_needs if need.must_excavate and need.chosen is not None
    )
    for rank in sorted(set(required_ranks), reverse=True):
        card = Card(campaign.suit, rank)
        if any(band.length >= 2 and band.high_rank >= rank >= band.low_rank for band in bands):
            # The named rank is already integrated into campaign structure;
            # it no longer needs an independent exit receiver.
            continue
        visible = _face_up_source(state, card)
        source_id = f"source:{rank}:{campaign.suit}"
        if visible is not None:
            column, index, depth, exposed = visible
            if not exposed:
                dependencies.append(
                    CampaignDependency(
                        source_id,
                        CampaignDependencyType.SOURCE_BURIED,
                        campaign_id,
                        f"required {card} lies below {depth} face-up overlay card(s)",
                        card,
                        (rank, rank),
                        column,
                        depth,
                        f"tableau:{column}:up:{index}",
                    )
                )
            elif not _source_has_receiver(state, column, index):
                dependencies.append(
                    CampaignDependency(
                        source_id,
                        CampaignDependencyType.SOURCE_EXPOSED_BUT_BLOCKED,
                        campaign_id,
                        f"required {card} is exposed but has no current receiver/workspace path",
                        card,
                        (rank, rank),
                        column,
                        0,
                        f"tableau:{column}:up:{index}",
                    )
                )
        else:
            buried = _face_down_source(state, card)
            if buried is not None:
                depth, column = buried
                dependencies.append(
                    CampaignDependency(
                        source_id,
                        CampaignDependencyType.SOURCE_BURIED,
                        campaign_id,
                        f"required {card} remains face-down at bounded depth {depth}",
                        card,
                        (rank, rank),
                        column,
                        depth,
                        f"tableau:{column}:down",
                    )
                )

    present_ranks = {card.rank for band in bands for card in band.cards}
    missing = tuple(rank for rank in range(13, 0, -1) if rank not in present_ranks)
    for high, low in _rank_intervals(missing):
        dependency_id = f"interval:{high}-{low}:{campaign.suit}"
        prerequisites = tuple(
            f"source:{rank}:{campaign.suit}"
            for rank in range(high, low - 1, -1)
            if f"source:{rank}:{campaign.suit}" in {item.dependency_id for item in dependencies}
        )
        dependencies.append(
            CampaignDependency(
                dependency_id,
                CampaignDependencyType.MISSING_SAME_SUIT_INTERVAL,
                campaign_id,
                f"same-suit interval {high}-{low}{campaign.suit} is not face-up assembled material",
                rank_interval=(high, low),
                prerequisites=prerequisites,
            )
        )
        edges.extend((item, dependency_id) for item in prerequisites)

    for band in bands:
        mixed_cover = tuple(card for card in band.covering_cards if card.suit != campaign.suit)
        if not mixed_cover:
            continue
        blocker_id = f"overlay:{band.high_rank}-{band.low_rank}:c{band.column}"
        blocker = MixedOverlayBlocker(
            blocker_id,
            campaign_id,
            band.label,
            band.column,
            mixed_cover,
            _covering_groups(mixed_cover),
        )
        overlays.append(blocker)
        dependencies.append(
            CampaignDependency(
                blocker_id,
                CampaignDependencyType.MIXED_OVERLAY,
                campaign_id,
                f"mixed overlay covers required campaign fragment {band.label}",
                rank_interval=(band.high_rank, band.low_rank),
                column=band.column,
                depth=len(mixed_cover),
            )
        )

    movable_bands = tuple(band for band in bands if band.movable)
    joinable = any(bands_can_join(upper, lower) for upper in movable_bands for lower in movable_bands)
    if len(movable_bands) > 1 and not joinable:
        dependencies.append(
            CampaignDependency(
                f"ordering:{campaign.suit}",
                CampaignDependencyType.FRAGMENT_ORDERING,
                campaign_id,
                "same-suit fragments exist but are not currently joinable in legal order",
            )
        )
        dependencies.append(
            CampaignDependency(
                f"receiver:{campaign.suit}",
                CampaignDependencyType.RECEIVER_MISSING,
                campaign_id,
                "campaign fragments lack a direct or bounded current receiver",
            )
        )

    empty_count = sum(column.is_empty() for column in state.columns)
    if campaign.space_requirement > empty_count:
        dependencies.append(
            CampaignDependency(
                f"workspace:{campaign.suit}",
                CampaignDependencyType.WORKSPACE_REQUIRED,
                campaign_id,
                f"campaign needs {campaign.space_requirement} workspace column(s); {empty_count} empty",
            )
        )

    for _result, obligation, evidence in _supply_unconsumed(campaign_id, supply_consumptions):
        dependency_id = f"supply:{obligation.obligation_id}"
        dependencies.append(
            CampaignDependency(
                dependency_id,
                CampaignDependencyType.SUPPLIED_NOT_CONSUMED,
                campaign_id,
                f"{obligation.card} was {evidence.stage.value.lower()} but not consumed",
                obligation.card,
                obligation.dependency_interval,
                evidence.current_column,
                0,
                evidence.active_source_key,
            )
        )

    terminal_id = f"terminal:{campaign_id}"
    blockers = tuple(item.dependency_id for item in dependencies)
    dependencies.append(
        CampaignDependency(
            terminal_id,
            CampaignDependencyType.TERMINAL_ASSEMBLY_PREREQUISITE,
            campaign_id,
            "all removal-relevant dependencies precede terminal assembly",
            prerequisites=blockers,
        )
    )
    edges.extend((item, terminal_id) for item in blockers)
    dependencies = sorted(dependencies, key=lambda item: (item.kind.value, item.dependency_id))
    edges = sorted(set(edges))
    payload = repr(
        (
            canonical_state_key(state),
            campaign_id,
            tuple((item.dependency_id, item.kind.value, item.prerequisites) for item in dependencies),
            tuple(edges),
        )
    ).encode("utf-8")
    return CampaignDependencyGraph(
        canonical_state_key(state),
        campaign_id,
        tuple(dependencies),
        tuple(edges),
        tuple(sorted(overlays, key=lambda item: item.blocker_id)),
        terminal_id,
        hashlib.sha256(payload).hexdigest()[:16],
    )


def assess_campaign_dependency_closure(
    state: SpiderState,
    campaign: FoundationCampaign,
    *,
    supply_consumptions: Sequence[SupplyConsumptionResult] = (),
) -> DependencyClosureAssessment:
    graph = build_campaign_dependency_graph(
        state, campaign, supply_consumptions=supply_consumptions
    )
    kinds = tuple(
        (kind, graph.count(kind))
        for kind in CampaignDependencyType
        if graph.count(kind)
    )
    source_depth = max(
        (
            item.depth
            for item in graph.dependencies
            if item.kind
            in (
                CampaignDependencyType.SOURCE_BURIED,
                CampaignDependencyType.SOURCE_EXPOSED_BUT_BLOCKED,
            )
        ),
        default=0,
    )
    bands = locate_campaign_bands(state, campaign.suit)
    coverage = max((band.length for band in bands if band.movable), default=0)
    supply = graph.count(CampaignDependencyType.SUPPLIED_NOT_CONSUMED)
    removal_blockers = tuple(
        item
        for item in graph.dependencies
        if item.kind != CampaignDependencyType.TERMINAL_ASSEMBLY_PREREQUISITE
    )
    return DependencyClosureAssessment(
        graph,
        kinds,
        source_depth,
        coverage,
        supply,
        len(removal_blockers) <= 2 and coverage >= 8,
    )


def _stable_join_count(state: SpiderState) -> int:
    return sum(
        lower.suit == upper.suit and lower.rank - 1 == upper.rank
        for column in state.columns
        for lower, upper in zip(column.face_up, column.face_up[1:])
    )


def _mixed_boundary_count(state: SpiderState) -> int:
    return sum(
        lower.suit != upper.suit
        for column in state.columns
        for lower, upper in zip(column.face_up, column.face_up[1:])
    )


def _priority(
    state: SpiderState,
    assessment: DependencyClosureAssessment,
    *,
    start_foundations: int,
    g: int,
    actions: int,
) -> Tuple:
    graph = assessment.graph
    unresolved = tuple(
        item for item in graph.dependencies
        if item.kind != CampaignDependencyType.TERMINAL_ASSEMBLY_PREREQUISITE
    )
    return (
        0 if len(state.foundations) > start_foundations else 1,
        len(unresolved),
        graph.count(CampaignDependencyType.SUPPLIED_NOT_CONSUMED),
        sum(
            item.depth
            for item in unresolved
            if item.kind in (
                CampaignDependencyType.SOURCE_BURIED,
                CampaignDependencyType.SOURCE_EXPOSED_BUT_BLOCKED,
            )
        ),
        graph.count(CampaignDependencyType.MISSING_SAME_SUIT_INTERVAL),
        graph.count(CampaignDependencyType.RECEIVER_MISSING),
        graph.count(CampaignDependencyType.MIXED_OVERLAY),
        -assessment.movable_same_suit_coverage,
        -_stable_join_count(state),
        _mixed_boundary_count(state),
        g,
        actions,
    )


def _action_targets(
    state: SpiderState,
    action: Tuple[int, int, int],
    campaign: FoundationCampaign,
    graph: CampaignDependencyGraph,
) -> Tuple[str, ...]:
    src, dst, count = action
    moved = state.columns[src].face_up[-count:]
    ids = []
    for item in graph.dependencies:
        if item.kind == CampaignDependencyType.TERMINAL_ASSEMBLY_PREREQUISITE:
            continue
        if item.column == src:
            ids.append(item.dependency_id)
        elif item.kind in (
            CampaignDependencyType.MISSING_SAME_SUIT_INTERVAL,
            CampaignDependencyType.FRAGMENT_ORDERING,
            CampaignDependencyType.RECEIVER_MISSING,
            CampaignDependencyType.SUPPLIED_NOT_CONSUMED,
        ) and any(card.suit == campaign.suit for card in moved):
            ids.append(item.dependency_id)
        elif item.kind == CampaignDependencyType.WORKSPACE_REQUIRED and count == len(state.columns[src].face_up):
            ids.append(item.dependency_id)
    destination = state.columns[dst].top()
    if destination is not None and destination.suit == campaign.suit:
        ids.extend(
            item.dependency_id
            for item in graph.dependencies
            if item.kind in (
                CampaignDependencyType.FRAGMENT_ORDERING,
                CampaignDependencyType.RECEIVER_MISSING,
                CampaignDependencyType.MISSING_SAME_SUIT_INTERVAL,
            )
        )
    return tuple(dict.fromkeys(ids))


def _failure_status(graph: CampaignDependencyGraph) -> DependencyClosureStatus:
    kinds = {item.kind for item in graph.dependencies}
    if CampaignDependencyType.MIXED_OVERLAY in kinds:
        return DependencyClosureStatus.BLOCKED_BY_OVERLAY
    if CampaignDependencyType.RECEIVER_MISSING in kinds:
        return DependencyClosureStatus.BLOCKED_BY_RECEIVER
    if CampaignDependencyType.WORKSPACE_REQUIRED in kinds:
        return DependencyClosureStatus.BLOCKED_BY_WORKSPACE
    return DependencyClosureStatus.NO_PROGRESS_WITHIN_BOUND


def _clone_result(result: DependencyClosureResult) -> DependencyClosureResult:
    return DependencyClosureResult(
        result.status,
        result.campaign_id,
        result.actions,
        result.corrected_added_cost,
        result.end_state.clone(),
        result.graph_before,
        result.graph_after,
        result.dependencies_closed,
        result.overlays_cleared,
        result.steps,
        result.supply_consumptions,
        result.nodes_expanded,
        result.elapsed_seconds,
        result.independent_replay_verified,
        result.reason,
    )


def realize_campaign_dependency_closure(
    state: SpiderState,
    campaign: FoundationCampaign,
    *,
    config: DependencyClosureConfig = DependencyClosureConfig(),
    supply_consumptions: Sequence[SupplyConsumptionResult] = (),
    deadline: Optional[SearchDeadline] = None,
    cache: Optional[DependencyClosureCache] = None,
) -> DependencyClosureResult:
    """Try bounded, campaign-attributable current-epoch work."""
    started = time.perf_counter()
    start_graph = build_campaign_dependency_graph(
        state, campaign, supply_consumptions=supply_consumptions
    )
    key = DependencyClosureCacheKey(
        canonical_state_key(state),
        campaign.label,
        config.fingerprint(),
        tuple(
            (
                item.contract_id,
                tuple(evidence.stage.value for evidence in item.evidence),
            )
            for item in supply_consumptions
            if item.campaign_id == campaign.label
        ),
    )
    if cache is not None and key in cache:
        return _clone_result(cache[key])
    if not any(
        item.kind != CampaignDependencyType.TERMINAL_ASSEMBLY_PREREQUISITE
        for item in start_graph.dependencies
    ):
        result = DependencyClosureResult(
            DependencyClosureStatus.MILESTONE_REACHED,
            campaign.label,
            (),
            0,
            state.clone(),
            start_graph,
            start_graph,
            (),
            (),
            (),
            tuple(supply_consumptions),
            0,
            time.perf_counter() - started,
            True,
            "named campaign has no unresolved pre-terminal dependencies",
        )
        if cache is not None:
            cache[key] = result
        return _clone_result(result)

    local_end = started + config.time_limit_s
    start_foundations = len(state.foundations)
    initial_assessment = assess_campaign_dependency_closure(
        state, campaign, supply_consumptions=supply_consumptions
    )
    initial_priority = _priority(
        state, initial_assessment, start_foundations=start_foundations, g=0, actions=0
    )
    uid = 0
    frontier = [
        (
            initial_priority,
            uid,
            state.clone(),
            0,
            (),
            (),
            tuple(supply_consumptions),
            initial_assessment,
        )
    ]
    best_cost: Dict[CanonicalStateKey, int] = {canonical_state_key(state): 0}
    best = frontier[0]
    nodes = 0
    resource_limited = False

    while frontier and nodes < config.max_nodes:
        if time.perf_counter() >= local_end or (deadline is not None and not deadline.checkpoint()):
            resource_limited = True
            break
        priority, _seq, current, g, actions, steps, supplies, assessment = heapq.heappop(frontier)
        nodes += 1
        if priority < best[0]:
            best = (priority, _seq, current, g, actions, steps, supplies, assessment)
        if len(current.foundations) > start_foundations:
            best = (priority, _seq, current, g, actions, steps, supplies, assessment)
            break

        children = []
        for action in current.enumerate_moves():
            targeted = _action_targets(current, action, campaign, assessment.graph)
            if not targeted:
                continue
            lifecycle = assess_tableau_move(
                current,
                action,
                provisional_reason=f"close named dependencies {targeted}",
            )
            if (
                config.require_bounded_park_exit
                and lifecycle.placement_class
                in (PlacementClass.MIXED_SUIT_PARK, PlacementClass.WORKSPACE_PARK)
                and not lifecycle.exit_route_bounded
            ):
                continue
            child = current.clone()
            paid = child.move(*action, rules=MW_RULES)
            ng = g + paid
            if ng > config.max_added_cost:
                continue
            child_supplies = advance_supply_consumption_results(
                current,
                (action,),
                existing=supplies,
            )
            child_assessment = assess_campaign_dependency_closure(
                child, campaign, supply_consumptions=child_supplies
            )
            child_priority = _priority(
                child,
                child_assessment,
                start_foundations=start_foundations,
                g=ng,
                actions=len(actions) + 1,
            )
            child_key = canonical_state_key(child)
            if best_cost.get(child_key, config.max_added_cost + 1) <= ng:
                continue
            best_cost[child_key] = ng
            before_ids = set(assessment.graph.dependency_ids)
            after_ids = set(child_assessment.graph.dependency_ids)
            step = DependencyClosureStep(
                action,
                paid,
                targeted,
                f"action is attributable to {', '.join(targeted)}",
                lifecycle,
                len(before_ids) - 1,
                len(after_ids) - 1,
                len(assessment.graph.mixed_overlays),
                len(child_assessment.graph.mixed_overlays),
            )
            children.append(
                (
                    child_priority,
                    action,
                    child,
                    ng,
                    actions + (action,),
                    steps + (step,),
                    child_supplies,
                    child_assessment,
                )
            )

        if config.permit_stock_transition and current.can_deal(MW_RULES):
            child = current.clone()
            paid = child.deal(MW_RULES)
            ng = g + paid
            if ng <= config.max_added_cost:
                child_supplies = advance_supply_consumption_results(
                    current, (("deal",),), existing=supplies
                )
                child_assessment = assess_campaign_dependency_closure(
                    child, campaign, supply_consumptions=child_supplies
                )
                child_priority = _priority(
                    child,
                    child_assessment,
                    start_foundations=start_foundations,
                    g=ng,
                    actions=len(actions) + 1,
                )
                children.append(
                    (
                        child_priority,
                        (99, 99, 99),
                        child,
                        ng,
                        actions + (("deal",),),
                        steps
                        + (
                            DependencyClosureStep(
                                ("deal",),
                                paid,
                                (),
                                "explicitly configured stock transition",
                                None,
                                len(assessment.graph.dependencies) - 1,
                                len(child_assessment.graph.dependencies) - 1,
                                len(assessment.graph.mixed_overlays),
                                len(child_assessment.graph.mixed_overlays),
                            ),
                        ),
                        child_supplies,
                        child_assessment,
                    )
                )

        children.sort(key=lambda item: (item[0], item[1]))
        for child_priority, _action, child, ng, child_actions, child_steps, child_supplies, child_assessment in children[: config.beam_width]:
            uid += 1
            heapq.heappush(
                frontier,
                (
                    child_priority,
                    uid,
                    child,
                    ng,
                    child_actions,
                    child_steps,
                    child_supplies,
                    child_assessment,
                ),
            )
        if len(frontier) > config.beam_width:
            frontier = heapq.nsmallest(config.beam_width, frontier)
            heapq.heapify(frontier)

    if nodes >= config.max_nodes:
        resource_limited = True
    _priority_best, _seq, end_state, cost, actions, steps, supplies, end_assessment = best
    before_ids = set(start_graph.dependency_ids)
    after_ids = set(end_assessment.graph.dependency_ids)
    before_ids.discard(start_graph.terminal_dependency_id)
    after_ids.discard(end_assessment.graph.terminal_dependency_id)
    closed = tuple(sorted(before_ids - after_ids))
    overlays_cleared = tuple(
        sorted(
            {item.blocker_id for item in start_graph.mixed_overlays}
            - {item.blocker_id for item in end_assessment.graph.mixed_overlays}
        )
    )
    supply_before = sum(item.consumed_count for item in supply_consumptions)
    supply_after = sum(item.consumed_count for item in supplies)
    replay = state.clone()
    try:
        replay_cost = replay_actions(replay, list(actions))
        verified = replay_cost == cost and states_structurally_equal(replay, end_state)
    except (ValueError, AssertionError, IndexError):
        verified = False

    if len(end_state.foundations) > start_foundations:
        status = DependencyClosureStatus.FOUNDATION_REMOVED
        reason = "campaign-directed closure removed the next foundation"
    elif supply_after > supply_before:
        status = DependencyClosureStatus.SUPPLY_CONSUMED
        reason = "a delivered campaign supply obligation was actually consumed"
    elif closed:
        status = DependencyClosureStatus.DEPENDENCY_CLOSED
        reason = "one or more named campaign dependencies were closed"
    elif overlays_cleared or end_assessment.movable_same_suit_coverage > initial_assessment.movable_same_suit_coverage:
        status = DependencyClosureStatus.MILESTONE_REACHED
        reason = "named overlay/interval structure materially advanced"
    elif resource_limited:
        status = DependencyClosureStatus.RESOURCE_LIMIT
        reason = "bounded dependency closure exhausted its node/time/deadline envelope"
    else:
        status = _failure_status(start_graph)
        reason = "no campaign-attributable progress was found within the fixed bound"

    successful = status in (
        DependencyClosureStatus.FOUNDATION_REMOVED,
        DependencyClosureStatus.DEPENDENCY_CLOSED,
        DependencyClosureStatus.SUPPLY_CONSUMED,
        DependencyClosureStatus.MILESTONE_REACHED,
    )
    if successful and (not actions or not verified):
        status = DependencyClosureStatus.NO_PROGRESS_WITHIN_BOUND
        reason = "candidate progress did not produce a non-empty independently replayed edge"
        actions = ()
        cost = 0
        end_state = state.clone()
        end_assessment = initial_assessment
        closed = ()
        overlays_cleared = ()
        steps = ()
        supplies = tuple(supply_consumptions)
        verified = True

    result = DependencyClosureResult(
        status,
        campaign.label,
        actions,
        cost if verified else None,
        end_state.clone(),
        start_graph,
        end_assessment.graph,
        closed,
        overlays_cleared,
        steps,
        tuple(supplies),
        nodes,
        time.perf_counter() - started,
        verified,
        reason,
    )
    if cache is not None:
        cache[key] = result
    return _clone_result(result)
