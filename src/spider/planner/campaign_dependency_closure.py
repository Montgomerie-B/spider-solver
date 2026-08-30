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
from dataclasses import dataclass, replace
from enum import Enum
from typing import Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.move_lifecycle import (
    BoundedCompensatingBenefit,
    MoveLifecycleAssessment,
    PlacementClass,
    assess_tableau_move,
)
from spider.planner.buried_source_closure import (
    BuriedSourceClosureTrace,
    ClosureBeamDepthAudit,
    ClosureCandidateAudit,
    ClosureCandidateDisposition,
    ClosureCandidateRejectionReason,
    ClosureCandidateStage,
    ClosureFailureDiagnosis,
    ClosureProgressEvidence,
    ClosureProgressKind,
    compare_legal_candidate_coverage,
    describe_buried_source,
    no_progress_evidence,
    source_progress_evidence,
)
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
    enable_legal_candidate_audit: bool = False
    retain_target_progress_diversity: bool = True

    def __post_init__(self) -> None:
        if self.max_added_cost <= 0 or self.max_nodes <= 0 or self.time_limit_s <= 0:
            raise ValueError("dependency-closure resources must be positive")
        if self.beam_width <= 0:
            raise ValueError("dependency-closure beam width must be positive")

    def fingerprint(self) -> Tuple[int, ...]:
        return (
            self.max_added_cost,
            self.max_nodes,
            int(round(self.time_limit_s * 1_000)),
            self.beam_width,
            int(self.permit_stock_transition),
            int(self.require_bounded_park_exit),
            int(self.enable_legal_candidate_audit),
            int(self.retain_target_progress_diversity),
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
class CampaignCriticalPathEntry:
    dependency_id: str
    kind: CampaignDependencyType
    prerequisites: Tuple[str, ...]
    downstream_dependencies_unlocked: int
    source_depth: int
    supplied_asset_waiting: bool
    receiver_or_workspace_bottleneck: bool
    criticality_rank: int
    rationale: str
    proof_pruning_allowed: bool = False

    def ordering_key(self) -> Tuple:
        return (
            self.criticality_rank,
            -self.downstream_dependencies_unlocked,
            -int(self.supplied_asset_waiting),
            -int(self.receiver_or_workspace_bottleneck),
            self.source_depth,
            self.dependency_id,
        )


@dataclass(frozen=True)
class CampaignCriticalPathSummary:
    campaign_id: str
    entries: Tuple[CampaignCriticalPathEntry, ...]
    total_weighted_burden: int
    bottleneck_dependency_id: Optional[str]
    proof_pruning_allowed: bool = False
    bottleneck_kind: Optional[CampaignDependencyType] = None
    prerequisite_dependency_ids: Tuple[str, ...] = ()
    deepest_source_depth: int = 0
    receiver_missing: bool = False
    workspace_required: bool = False
    supplied_asset_waiting: bool = False
    interval_missing: bool = False
    overlay_present: bool = False
    terminal_qualified: bool = False


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
    progress_evidence: Optional[ClosureProgressEvidence] = None


@dataclass(frozen=True)
class DependencyClosureAssessment:
    graph: CampaignDependencyGraph
    unresolved_by_type: Tuple[Tuple[CampaignDependencyType, int], ...]
    deepest_source: int
    movable_same_suit_coverage: int
    supplied_not_consumed: int
    near_terminal: bool
    proof_pruning_allowed: bool = False
    critical_path: Optional[CampaignCriticalPathSummary] = None


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
    target_dependency_id: Optional[str] = None
    buried_source_traces: Tuple[BuriedSourceClosureTrace, ...] = ()
    failure_diagnosis: ClosureFailureDiagnosis = ClosureFailureDiagnosis.LOCAL_BOUNDED_MISS


@dataclass(frozen=True)
class DependencyClosureCacheKey:
    state_key: CanonicalStateKey
    campaign_id: str
    config_fingerprint: Tuple[int, ...]
    supply_fingerprint: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()
    target_dependency_id: Optional[str] = None


DependencyClosureCache = MutableMapping[DependencyClosureCacheKey, DependencyClosureResult]


@dataclass(frozen=True)
class _ClosureChild:
    priority: Tuple
    action: Tuple[int, int, int]
    state: SpiderState
    g: int
    actions: Tuple[Action, ...]
    steps: Tuple[DependencyClosureStep, ...]
    supplies: Tuple[SupplyConsumptionResult, ...]
    assessment: DependencyClosureAssessment
    progress: Optional[ClosureProgressEvidence]
    lifecycle: Optional[MoveLifecycleAssessment]


def retain_target_progress_diversity(
    children: Sequence[_ClosureChild], beam_width: int
) -> Tuple[_ClosureChild, ...]:
    """Keep bounded progress-class representatives without widening the beam."""
    ordered = sorted(children, key=lambda item: (item.priority, item.action))
    if len(ordered) <= beam_width:
        return tuple(ordered)
    representatives: List[_ClosureChild] = []
    represented = set()
    for child in ordered:
        progress = child.progress
        if progress is None or not progress.target_relevant:
            continue
        key = progress.kind
        if key not in represented:
            representatives.append(child)
            represented.add(key)
        if len(representatives) >= beam_width:
            return tuple(representatives)
    selected_ids = {id(item) for item in representatives}
    representatives.extend(
        item for item in ordered if id(item) not in selected_ids
    )
    return tuple(representatives[:beam_width])


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
            if not obligation.is_critical:
                continue
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
        receiver_id = f"receiver:{campaign.suit}"
        dependencies.append(
            CampaignDependency(
                f"ordering:{campaign.suit}",
                CampaignDependencyType.FRAGMENT_ORDERING,
                campaign_id,
                "same-suit fragments exist but are not currently joinable in legal order",
                prerequisites=(receiver_id,),
            )
        )
        dependencies.append(
            CampaignDependency(
                receiver_id,
                CampaignDependencyType.RECEIVER_MISSING,
                campaign_id,
                "campaign fragments lack a direct or bounded current receiver",
            )
        )
        edges.append((receiver_id, f"ordering:{campaign.suit}"))

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
        for interval in dependencies:
            if (
                interval.kind == CampaignDependencyType.MISSING_SAME_SUIT_INTERVAL
                and interval.rank_interval is not None
                and interval.rank_interval[0] >= obligation.card.rank >= interval.rank_interval[1]
            ):
                edges.append((dependency_id, interval.dependency_id))

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


def _transitive_downstream_count(
    graph: CampaignDependencyGraph, dependency_id: str
) -> int:
    outgoing: Dict[str, set[str]] = {}
    for source, destination in graph.edges:
        outgoing.setdefault(source, set()).add(destination)
    seen: set[str] = set()
    pending = list(outgoing.get(dependency_id, ()))
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(outgoing.get(current, ()))
    return len(seen)


def _criticality_rank(dependency: CampaignDependency) -> int:
    """Transparent bottleneck class, independent of campaign suit."""
    return {
        CampaignDependencyType.SUPPLIED_NOT_CONSUMED: 0,
        CampaignDependencyType.RECEIVER_MISSING: 1,
        CampaignDependencyType.SOURCE_EXPOSED_BUT_BLOCKED: 1,
        CampaignDependencyType.SOURCE_BURIED: 2,
        CampaignDependencyType.MIXED_OVERLAY: 2,
        CampaignDependencyType.MISSING_SAME_SUIT_INTERVAL: 3,
        CampaignDependencyType.FRAGMENT_ORDERING: 3,
        CampaignDependencyType.WORKSPACE_REQUIRED: 4,
        CampaignDependencyType.TERMINAL_ASSEMBLY_PREREQUISITE: 99,
    }[dependency.kind]


def build_campaign_critical_path(
    graph: CampaignDependencyGraph,
    *,
    terminal_qualified: bool = False,
) -> CampaignCriticalPathSummary:
    """Return a small dependency bottleneck view for ordering and telemetry."""
    entries = []
    for dependency in graph.dependencies:
        if dependency.kind == CampaignDependencyType.TERMINAL_ASSEMBLY_PREREQUISITE:
            continue
        downstream = _transitive_downstream_count(graph, dependency.dependency_id)
        waiting = dependency.kind == CampaignDependencyType.SUPPLIED_NOT_CONSUMED
        receiver = dependency.kind in (
            CampaignDependencyType.RECEIVER_MISSING,
            CampaignDependencyType.WORKSPACE_REQUIRED,
            CampaignDependencyType.SOURCE_EXPOSED_BUT_BLOCKED,
        )
        entries.append(
            CampaignCriticalPathEntry(
                dependency.dependency_id,
                dependency.kind,
                dependency.prerequisites,
                downstream,
                dependency.depth,
                waiting,
                receiver,
                _criticality_rank(dependency),
                (
                    f"unlocks {downstream} downstream dependency node(s); "
                    f"source_depth={dependency.depth}; waiting_supply={waiting}; "
                    f"receiver_or_workspace={receiver}"
                ),
            )
        )
    entries.sort(key=lambda item: item.ordering_key())
    burden = sum(1 + item.downstream_dependencies_unlocked for item in entries)
    kinds = {item.kind for item in entries}
    leading = entries[0] if entries else None
    return CampaignCriticalPathSummary(
        graph.campaign_id,
        tuple(entries),
        burden,
        leading.dependency_id if leading else None,
        False,
        leading.kind if leading else None,
        leading.prerequisites if leading else (),
        max((item.source_depth for item in entries), default=0),
        bool(
            kinds
            & {
                CampaignDependencyType.RECEIVER_MISSING,
                CampaignDependencyType.SOURCE_EXPOSED_BUT_BLOCKED,
            }
        ),
        CampaignDependencyType.WORKSPACE_REQUIRED in kinds,
        any(item.supplied_asset_waiting for item in entries),
        bool(
            kinds
            & {
                CampaignDependencyType.MISSING_SAME_SUIT_INTERVAL,
                CampaignDependencyType.FRAGMENT_ORDERING,
            }
        ),
        CampaignDependencyType.MIXED_OVERLAY in kinds,
        terminal_qualified,
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
        False,
        build_campaign_critical_path(graph),
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
    critical_path = assessment.critical_path or build_campaign_critical_path(graph)
    unresolved = tuple(
        item for item in graph.dependencies
        if item.kind != CampaignDependencyType.TERMINAL_ASSEMBLY_PREREQUISITE
    )
    return (
        0 if len(state.foundations) > start_foundations else 1,
        critical_path.total_weighted_burden,
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
    unique = tuple(dict.fromkeys(ids))
    path = build_campaign_critical_path(graph)
    ranks = {item.dependency_id: item.ordering_key() for item in path.entries}
    return tuple(sorted(unique, key=lambda item: ranks.get(item, (100, 0, 0, 0, 0, item))))


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
        result.proof_pruning_allowed,
        result.target_dependency_id,
        result.buried_source_traces,
        result.failure_diagnosis,
    )


def realize_campaign_dependency_closure(
    state: SpiderState,
    campaign: FoundationCampaign,
    *,
    config: DependencyClosureConfig = DependencyClosureConfig(),
    supply_consumptions: Sequence[SupplyConsumptionResult] = (),
    deadline: Optional[SearchDeadline] = None,
    cache: Optional[DependencyClosureCache] = None,
    target_dependency_id: Optional[str] = None,
    semantic_target_id: Optional[str] = None,
) -> DependencyClosureResult:
    """Try bounded, campaign-attributable work for one fresh named dependency."""
    started = time.perf_counter()
    start_graph = build_campaign_dependency_graph(
        state, campaign, supply_consumptions=supply_consumptions
    )
    named = next(
        (item for item in start_graph.dependencies if item.dependency_id == target_dependency_id),
        None,
    )
    if target_dependency_id is None:
        path = build_campaign_critical_path(start_graph)
        target_dependency_id = path.bottleneck_dependency_id
        named = next(
            (item for item in start_graph.dependencies if item.dependency_id == target_dependency_id),
            None,
        )
    source_dependency = (
        named
        if named is not None
        and named.kind == CampaignDependencyType.SOURCE_BURIED
        and named.card is not None
        else None
    )
    source_card = source_dependency.card if source_dependency is not None else None
    blocker_before = (
        describe_buried_source(state, target_dependency_id or "", source_card)
        if source_card is not None
        else None
    )
    key = DependencyClosureCacheKey(
        state_key=canonical_state_key(state),
        campaign_id=campaign.label,
        config_fingerprint=config.fingerprint(),
        supply_fingerprint=tuple(
            (item.contract_id, tuple(e.stage.value for e in item.evidence))
            for item in supply_consumptions
            if item.campaign_id == campaign.label
        ),
        target_dependency_id=target_dependency_id,
    )
    if cache is not None and key in cache:
        return _clone_result(cache[key])

    unresolved = tuple(
        item for item in start_graph.dependencies
        if item.kind != CampaignDependencyType.TERMINAL_ASSEMBLY_PREREQUISITE
    )
    if not unresolved:
        result = DependencyClosureResult(
            DependencyClosureStatus.MILESTONE_REACHED, campaign.label, (), 0,
            state.clone(), start_graph, start_graph, (), (), (),
            tuple(supply_consumptions), 0, time.perf_counter() - started, True,
            "named campaign has no unresolved pre-terminal dependencies",
            target_dependency_id=target_dependency_id,
            failure_diagnosis=ClosureFailureDiagnosis.NONE,
        )
        if cache is not None:
            cache[key] = result
        return _clone_result(result)

    if target_dependency_id is not None and named is None:
        result = DependencyClosureResult(
            DependencyClosureStatus.INVALIDATED, campaign.label, (), 0,
            state.clone(), start_graph, start_graph, (), (), (),
            tuple(supply_consumptions), 0, time.perf_counter() - started, True,
            f"named dependency {target_dependency_id} is stale in the fresh graph",
            target_dependency_id=target_dependency_id,
            failure_diagnosis=ClosureFailureDiagnosis.STRUCTURAL_BLOCKER,
        )
        if cache is not None:
            cache[key] = result
        return _clone_result(result)

    local_end = started + config.time_limit_s
    start_foundations = len(state.foundations)
    initial_assessment = assess_campaign_dependency_closure(
        state, campaign, supply_consumptions=supply_consumptions
    )

    def ranked_priority(
        child_state: SpiderState,
        assessment: DependencyClosureAssessment,
        progress: Optional[ClosureProgressEvidence],
        g: int,
        action_count: int,
    ) -> Tuple:
        target_closed = bool(
            target_dependency_id
            and target_dependency_id not in assessment.graph.dependency_ids
        )
        target_prefix = (
            0 if target_closed else 1,
            progress.ordering_key if progress is not None else (99, 0, 0, 10**6, 10**6, 10**6),
        )
        return target_prefix + _priority(
            child_state, assessment,
            start_foundations=start_foundations, g=g, actions=action_count,
        )

    initial_priority = ranked_priority(state, initial_assessment, None, 0, 0)
    uid = 0
    frontier = [(initial_priority, uid, state.clone(), 0, (), (), tuple(supply_consumptions), initial_assessment)]
    best_cost: Dict[CanonicalStateKey, int] = {canonical_state_key(state): 0}
    best = frontier[0]
    nodes = 0
    resource_limited = False
    audits: List[ClosureCandidateAudit] = []
    beam_audits: List[ClosureBeamDepthAudit] = []
    generated_actions = set()
    legal_target_actions = set()

    def record_audit(audit: ClosureCandidateAudit) -> None:
        if len(audits) < 2_048:
            audits.append(audit)

    while frontier and nodes < config.max_nodes:
        if time.perf_counter() >= local_end or (deadline is not None and not deadline.checkpoint()):
            resource_limited = True
            break
        priority, _seq, current, g, actions, steps, supplies, assessment = heapq.heappop(frontier)
        nodes += 1
        if priority < best[0]:
            best = (priority, _seq, current, g, actions, steps, supplies, assessment)
        if len(current.foundations) > start_foundations or (
            target_dependency_id is not None
            and target_dependency_id not in assessment.graph.dependency_ids
        ):
            best = (priority, _seq, current, g, actions, steps, supplies, assessment)
            break

        children: List[_ClosureChild] = []
        replay_valid_count = 0
        for action in current.enumerate_moves():
            lifecycle = assess_tableau_move(
                current, action,
                provisional_reason=(
                    f"bounded prerequisite for {target_dependency_id}"
                    if source_card is not None else None
                ),
            )
            child = current.clone()
            paid = child.move(*action, rules=MW_RULES)
            replay_valid_count += 1
            child_supplies = advance_supply_consumption_results(
                current, (action,), existing=supplies,
            )
            child_assessment = assess_campaign_dependency_closure(
                child, campaign, supply_consumptions=child_supplies
            )
            before_ids = set(assessment.graph.dependency_ids)
            after_ids = set(child_assessment.graph.dependency_ids)
            progress = None
            if source_card is not None and target_dependency_id is not None:
                progress = source_progress_evidence(
                    current, child, target_dependency_id, source_card, action, lifecycle,
                    dependencies_before=max(0, len(before_ids) - 1),
                    dependencies_after=max(0, len(after_ids) - 1),
                    dependency_present_after=target_dependency_id in after_ids,
                )
                if progress.target_relevant:
                    legal_target_actions.add(action)
            targeted = list(_action_targets(current, action, campaign, assessment.graph))
            if progress is not None and progress.target_relevant and target_dependency_id not in targeted:
                targeted.insert(0, target_dependency_id)
            targeted_tuple = tuple(dict.fromkeys(targeted))
            if not targeted_tuple:
                if config.enable_legal_candidate_audit and blocker_before is not None:
                    record_audit(ClosureCandidateAudit(
                        action, ClosureCandidateStage.LEGAL_AUDIT,
                        ClosureCandidateDisposition.LEGAL_ONLY, target_dependency_id or "",
                        False, True, False,
                        progress or no_progress_evidence(blocker_before, len(unresolved), "legal but unrelated"),
                        lifecycle, blocker_before.receiver_rank, False,
                        lifecycle.placement_class in (PlacementClass.MIXED_SUIT_PARK, PlacementClass.WORKSPACE_PARK),
                        lifecycle.future_exit_route, ClosureCandidateRejectionReason.NOT_TARGET_RELEVANT,
                        "fresh graph and physical source audit found no named-target progress",
                        None, None, None, None,
                    ))
                continue
            generated_actions.add(action)

            # A park on the blocker source can have a concrete exit that is
            # created by exposing the source itself.
            if (
                source_card is not None and progress is not None and progress.target_relevant
                and lifecycle.placement_class in (PlacementClass.MIXED_SUIT_PARK, PlacementClass.WORKSPACE_PARK)
                and not lifecycle.exit_route_bounded
            ):
                src, dst, count = action
                after_blocker = describe_buried_source(child, target_dependency_id or "", source_card)
                route_column = after_blocker.chosen_column
                if route_column is not None and child.can_move(dst, route_column, count):
                    saving = lifecycle.estimated_rehandling_cost + 1.0 + len(
                        set(before_ids) - set(after_ids)
                    )
                    lifecycle = replace(
                        lifecycle,
                        future_exit_route=(
                            f"after exposing {source_card}, move parked run from "
                            f"c{dst + 1} to c{route_column + 1}"
                        ),
                        exit_route_bounded=True,
                        compensating_benefit=BoundedCompensatingBenefit(
                            saving,
                            progress.rationale,
                            f"necessary bounded prerequisite for {target_dependency_id}",
                        ),
                    )
            if (
                config.require_bounded_park_exit
                and lifecycle.placement_class in (PlacementClass.MIXED_SUIT_PARK, PlacementClass.WORKSPACE_PARK)
                and not lifecycle.exit_route_bounded
            ):
                record_audit(ClosureCandidateAudit(
                    action, ClosureCandidateStage.LIFECYCLE_CHECK,
                    ClosureCandidateDisposition.REJECTED, target_dependency_id or "",
                    True, True, bool(progress and progress.target_relevant),
                    progress or no_progress_evidence(blocker_before, len(unresolved), "unbounded park") if blocker_before else progress,
                    lifecycle, blocker_before.receiver_rank if blocker_before else None,
                    bool(progress and progress.workspace_created), True,
                    lifecycle.future_exit_route, ClosureCandidateRejectionReason.TEMPORARY_PARK_NO_EXIT,
                    "park lacks a concrete exit inside the named source chain",
                    None, None, None, None,
                ))
                continue
            if lifecycle.same_suit_joins_broken and not (
                progress is not None and progress.target_relevant and lifecycle.exit_route_bounded
            ):
                record_audit(ClosureCandidateAudit(
                    action, ClosureCandidateStage.LIFECYCLE_CHECK,
                    ClosureCandidateDisposition.REJECTED, target_dependency_id or "",
                    True, True, bool(progress and progress.target_relevant), progress,
                    lifecycle, blocker_before.receiver_rank if blocker_before else None,
                    bool(progress and progress.workspace_created), False,
                    lifecycle.future_exit_route,
                    ClosureCandidateRejectionReason.BREAKS_STABLE_STRUCTURE_UNJUSTIFIED,
                    "stable structure break has no bounded restore/replace route and target compensation",
                    None, None, None, None,
                ))
                continue
            ng = g + paid
            if ng > config.max_added_cost:
                record_audit(ClosureCandidateAudit(
                    action, ClosureCandidateStage.ADMISSION,
                    ClosureCandidateDisposition.REJECTED, target_dependency_id or "",
                    True, True, bool(progress and progress.target_relevant), progress,
                    lifecycle, blocker_before.receiver_rank if blocker_before else None,
                    bool(progress and progress.workspace_created), False,
                    lifecycle.future_exit_route, ClosureCandidateRejectionReason.RESOURCE_LIMIT,
                    f"corrected cost {ng} exceeds fixed {config.max_added_cost}",
                    None, None, None, None,
                ))
                continue
            child_key = canonical_state_key(child)
            if best_cost.get(child_key, config.max_added_cost + 1) <= ng:
                record_audit(ClosureCandidateAudit(
                    action, ClosureCandidateStage.EXACT_DEDUP,
                    ClosureCandidateDisposition.DEDUPLICATED, target_dependency_id or "",
                    True, True, bool(progress and progress.target_relevant), progress,
                    lifecycle, blocker_before.receiver_rank if blocker_before else None,
                    bool(progress and progress.workspace_created), False,
                    lifecycle.future_exit_route, ClosureCandidateRejectionReason.DOMINATED_SAME_STATE,
                    "same exact structural state already has equal/lower corrected g",
                    None, None, repr(child_key), None,
                ))
                continue
            best_cost[child_key] = ng
            child_priority = ranked_priority(
                child, child_assessment, progress, ng, len(actions) + 1
            )
            step = DependencyClosureStep(
                action, paid, targeted_tuple,
                f"fresh target progress: {progress.rationale if progress else targeted_tuple}",
                lifecycle, max(0, len(before_ids) - 1), max(0, len(after_ids) - 1),
                len(assessment.graph.mixed_overlays), len(child_assessment.graph.mixed_overlays),
                False, progress,
            )
            children.append(_ClosureChild(
                child_priority, action, child, ng, actions + (action,), steps + (step,),
                tuple(child_supplies), child_assessment, progress, lifecycle,
            ))
            record_audit(ClosureCandidateAudit(
                action, ClosureCandidateStage.ADMISSION, ClosureCandidateDisposition.ADMITTED,
                target_dependency_id or "", True, True,
                bool(progress and progress.target_relevant), progress,
                lifecycle, blocker_before.receiver_rank if blocker_before else None,
                bool(progress and progress.workspace_created),
                lifecycle.placement_class in (PlacementClass.MIXED_SUIT_PARK, PlacementClass.WORKSPACE_PARK),
                lifecycle.future_exit_route, None, "admitted under fresh named-target attribution",
                len(children), None, None, None,
            ))

        ordered = tuple(sorted(children, key=lambda item: (item.priority, item.action)))
        retained = (
            retain_target_progress_diversity(ordered, config.beam_width)
            if config.retain_target_progress_diversity
            else ordered[: config.beam_width]
        )
        retained_ids = {id(item) for item in retained}
        discarded = tuple(item for item in ordered if id(item) not in retained_ids)
        if len(beam_audits) < 512:
            beam_audits.append(ClosureBeamDepthAudit(
                len(actions), len(children), replay_valid_count,
                sum(bool(item.progress and item.progress.target_relevant) for item in children),
                sum(bool(item.progress and item.progress.prerequisite_progress) for item in children),
                len(retained), len(discarded), config.beam_width if discarded else None,
                discarded[0].action if discarded else None,
                discarded[0].progress.kind if discarded and discarded[0].progress else None,
                tuple(dict.fromkeys(
                    item.progress.kind for item in retained if item.progress is not None
                )),
                tuple(item.progress.source_depth_after for item in retained if item.progress is not None),
                tuple(item.progress.source_depth_after for item in discarded if item.progress is not None),
            ))
        for rank, item in enumerate(discarded, start=len(retained) + 1):
            record_audit(ClosureCandidateAudit(
                item.action, ClosureCandidateStage.BEAM_SELECTION,
                ClosureCandidateDisposition.DISCARDED, target_dependency_id or "",
                True, True, bool(item.progress and item.progress.target_relevant), item.progress,
                item.lifecycle, blocker_before.receiver_rank if blocker_before else None,
                bool(item.progress and item.progress.workspace_created),
                bool(item.lifecycle and item.lifecycle.placement_class in (PlacementClass.MIXED_SUIT_PARK, PlacementClass.WORKSPACE_PARK)),
                item.lifecycle.future_exit_route if item.lifecycle else None,
                ClosureCandidateRejectionReason.BEAM_CUTOFF,
                "discarded after bounded target-progress diversity retention",
                None, rank, None, None,
            ))
        for item in retained:
            uid += 1
            heapq.heappush(frontier, (
                item.priority, uid, item.state, item.g, item.actions, item.steps,
                item.supplies, item.assessment,
            ))
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
    overlays_cleared = tuple(sorted(
        {item.blocker_id for item in start_graph.mixed_overlays}
        - {item.blocker_id for item in end_assessment.graph.mixed_overlays}
    ))
    supply_before = sum(item.consumed_count for item in supply_consumptions)
    supply_after = sum(item.consumed_count for item in supplies)
    replay = state.clone()
    try:
        replay_cost = replay_actions(replay, list(actions))
        verified = replay_cost == cost and states_structurally_equal(replay, end_state)
    except (ValueError, AssertionError, IndexError):
        verified = False

    if len(end_state.foundations) > start_foundations:
        status, reason = DependencyClosureStatus.FOUNDATION_REMOVED, "campaign-directed closure removed the next foundation"
    elif supply_after > supply_before:
        status, reason = DependencyClosureStatus.SUPPLY_CONSUMED, "a delivered campaign supply obligation was actually consumed"
    elif closed:
        status, reason = DependencyClosureStatus.DEPENDENCY_CLOSED, "one or more named campaign dependencies were closed"
    elif overlays_cleared or end_assessment.movable_same_suit_coverage > initial_assessment.movable_same_suit_coverage:
        status, reason = DependencyClosureStatus.MILESTONE_REACHED, "named overlay/interval structure materially advanced"
    elif resource_limited:
        status, reason = DependencyClosureStatus.RESOURCE_LIMIT, "bounded dependency closure exhausted its unchanged node/time/deadline envelope"
    else:
        status, reason = _failure_status(start_graph), "no campaign-attributable progress was found within the fixed bound"
    successful = status in {
        DependencyClosureStatus.FOUNDATION_REMOVED,
        DependencyClosureStatus.DEPENDENCY_CLOSED,
        DependencyClosureStatus.SUPPLY_CONSUMED,
        DependencyClosureStatus.MILESTONE_REACHED,
    }
    if successful and (not actions or not verified):
        status = DependencyClosureStatus.NO_PROGRESS_WITHIN_BOUND
        reason = "candidate progress did not produce a non-empty independently replayed edge"
        actions, cost, end_state, end_assessment = (), 0, state.clone(), initial_assessment
        closed, overlays_cleared, steps, supplies, verified = (), (), (), tuple(supply_consumptions), True
        successful = False

    diagnosis = ClosureFailureDiagnosis.NONE if successful else (
        ClosureFailureDiagnosis.RESOURCE_BOUND if resource_limited and legal_target_actions
        else ClosureFailureDiagnosis.STRUCTURAL_BLOCKER if source_card is not None and not legal_target_actions
        else ClosureFailureDiagnosis.SEARCH_POLICY if any(
            audit.target_relevant and audit.rejection_reason not in {
                ClosureCandidateRejectionReason.RESOURCE_LIMIT,
                ClosureCandidateRejectionReason.DOMINATED_SAME_STATE,
            }
            for audit in audits
        )
        else ClosureFailureDiagnosis.LOCAL_BOUNDED_MISS
    )
    traces: Tuple[BuriedSourceClosureTrace, ...] = ()
    if source_card is not None and blocker_before is not None and target_dependency_id is not None:
        blocker_after = describe_buried_source(end_state, target_dependency_id, source_card)
        coverage = compare_legal_candidate_coverage(
            target_dependency_id, legal_target_actions, generated_actions
        )
        missing = coverage.missing_from_generator
        traces = (BuriedSourceClosureTrace(
            campaign.label, semantic_target_id, target_dependency_id,
            canonical_state_key(state), source_card, blocker_before, blocker_after,
            tuple(audits), tuple(beam_audits), tuple(sorted(generated_actions)),
            tuple(sorted(legal_target_actions)), missing,
            sum(bool(step.progress_evidence and step.progress_evidence.source_copy_substituted) for step in steps),
            sum(bool(step.progress_evidence and step.progress_evidence.source_exposed) for step in steps),
            target_dependency_id in closed, diagnosis, status.value,
        ),)
    result = DependencyClosureResult(
        status, campaign.label, actions, cost if verified else None, end_state.clone(),
        start_graph, end_assessment.graph, closed, overlays_cleared, steps,
        tuple(supplies), nodes, time.perf_counter() - started, verified, reason,
        False, target_dependency_id, traces, diagnosis,
    )
    if cache is not None:
        cache[key] = result
    return _clone_result(result)
