"""Typed, proof-neutral audit facts for one buried campaign source.

The dependency-closure realiser remains the only bounded search.  This module
only describes physical source copies, blocker geometry, candidate progress,
beam disposition, and local failure diagnosis.  None of these facts enters
canonical Spider identity or authorizes proof pruning.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.move_lifecycle import MoveLifecycleAssessment, PlacementClass
from spider.state_identity import CanonicalStateKey


TableauAction = Tuple[int, int, int]


class ClosureCandidateStage(str, Enum):
    LEGAL_AUDIT = "LEGAL_AUDIT"
    GENERATED = "GENERATED"
    LIFECYCLE_CHECK = "LIFECYCLE_CHECK"
    REPLAYED = "REPLAYED"
    ADMISSION = "ADMISSION"
    EXACT_DEDUP = "EXACT_DEDUP"
    BEAM_SELECTION = "BEAM_SELECTION"
    OUTCOME = "OUTCOME"


class ClosureCandidateDisposition(str, Enum):
    LEGAL_ONLY = "LEGAL_ONLY"
    GENERATED = "GENERATED"
    REJECTED = "REJECTED"
    ADMITTED = "ADMITTED"
    DEDUPLICATED = "DEDUPLICATED"
    RETAINED = "RETAINED"
    DISCARDED = "DISCARDED"
    SELECTED = "SELECTED"


class ClosureCandidateRejectionReason(str, Enum):
    ILLEGAL = "ILLEGAL"
    NOT_TARGET_RELEVANT = "NOT_TARGET_RELEVANT"
    NO_RECEIVER = "NO_RECEIVER"
    WORKSPACE_REQUIRED = "WORKSPACE_REQUIRED"
    TEMPORARY_PARK_NO_EXIT = "TEMPORARY_PARK_NO_EXIT"
    BREAKS_STABLE_STRUCTURE_UNJUSTIFIED = "BREAKS_STABLE_STRUCTURE_UNJUSTIFIED"
    REHANDLING_DEBT_TOO_HIGH = "REHANDLING_DEBT_TOO_HIGH"
    DOMINATED_SAME_STATE = "DOMINATED_SAME_STATE"
    BEAM_CUTOFF = "BEAM_CUTOFF"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    NO_SOURCE_DEPTH_PROGRESS = "NO_SOURCE_DEPTH_PROGRESS"
    NO_DEPENDENCY_PROGRESS = "NO_DEPENDENCY_PROGRESS"
    STALE_TARGET = "STALE_TARGET"
    OTHER_EXPLICIT_REASON = "OTHER_EXPLICIT_REASON"


class ClosureProgressKind(str, Enum):
    SOURCE_CONSUMED = "SOURCE_CONSUMED"
    SOURCE_EXPOSED = "SOURCE_EXPOSED"
    SOURCE_ACTIONABLE = "SOURCE_ACTIONABLE"
    SOURCE_DEPTH_REDUCED = "SOURCE_DEPTH_REDUCED"
    DIRECT_BLOCKER_REMOVAL = "DIRECT_BLOCKER_REMOVAL"
    RECEIVER_CREATED = "RECEIVER_CREATED"
    WORKSPACE_CREATED = "WORKSPACE_CREATED"
    TEMPORARY_PARK = "TEMPORARY_PARK"
    PERMANENT_SAME_SUIT_PREREQUISITE = "PERMANENT_SAME_SUIT_PREREQUISITE"
    SOURCE_COPY_SUBSTITUTED = "SOURCE_COPY_SUBSTITUTED"
    NO_PROGRESS = "NO_PROGRESS"


class ClosureFailureDiagnosis(str, Enum):
    NONE = "NONE"
    SEARCH_POLICY = "SEARCH_POLICY"
    RESOURCE_BOUND = "RESOURCE_BOUND"
    STRUCTURAL_BLOCKER = "STRUCTURAL_BLOCKER"
    LOCAL_BOUNDED_MISS = "LOCAL_BOUNDED_MISS"


@dataclass(frozen=True)
class PhysicalSourceAlternative:
    source_key: str
    card: Card
    column: int
    zone: str
    index: int
    depth: int
    blocker_cards: Tuple[Card, ...]
    exposed: bool
    actionable: bool
    movable_count: int
    legal_destinations: Tuple[int, ...]
    proof_pruning_allowed: bool = False

    @property
    def ordering_key(self) -> Tuple:
        return (
            0 if self.actionable else 1,
            0 if self.exposed else 1,
            self.depth,
            0 if self.zone == "face_up" else 1,
            self.column,
            self.index,
        )


@dataclass(frozen=True)
class BuriedSourceBlocker:
    dependency_id: str
    required_card: Card
    physical_sources: Tuple[PhysicalSourceAlternative, ...]
    chosen_source_key: Optional[str]
    chosen_column: Optional[int]
    chosen_zone: Optional[str]
    source_depth: int
    blocker_cards: Tuple[Card, ...]
    blocker_runs: Tuple[Tuple[Card, ...], ...]
    legal_blocker_moves: Tuple[TableauAction, ...]
    receiver_rank: Optional[int]
    proof_pruning_allowed: bool = False

    @property
    def chosen(self) -> Optional[PhysicalSourceAlternative]:
        return next(
            (
                item
                for item in self.physical_sources
                if item.source_key == self.chosen_source_key
            ),
            None,
        )


@dataclass(frozen=True)
class ClosureProgressEvidence:
    kind: ClosureProgressKind
    target_relevant: bool
    prerequisite_progress: bool
    source_depth_before: int
    source_depth_after: int
    blockers_before: int
    blockers_after: int
    dependencies_before: int
    dependencies_after: int
    receiver_created: bool
    workspace_created: bool
    source_exposed: bool
    source_actionable: bool
    source_consumed: bool
    source_copy_substituted: bool
    rationale: str
    proof_pruning_allowed: bool = False

    @property
    def ordering_key(self) -> Tuple:
        rank = {
            ClosureProgressKind.SOURCE_CONSUMED: 0,
            ClosureProgressKind.SOURCE_EXPOSED: 1,
            ClosureProgressKind.SOURCE_ACTIONABLE: 2,
            ClosureProgressKind.SOURCE_DEPTH_REDUCED: 3,
            ClosureProgressKind.DIRECT_BLOCKER_REMOVAL: 4,
            ClosureProgressKind.RECEIVER_CREATED: 5,
            ClosureProgressKind.WORKSPACE_CREATED: 6,
            ClosureProgressKind.TEMPORARY_PARK: 7,
            ClosureProgressKind.PERMANENT_SAME_SUIT_PREREQUISITE: 8,
            ClosureProgressKind.SOURCE_COPY_SUBSTITUTED: 9,
            ClosureProgressKind.NO_PROGRESS: 99,
        }[self.kind]
        return (
            rank,
            -int(self.target_relevant),
            -int(self.prerequisite_progress),
            self.source_depth_after,
            self.blockers_after,
            self.dependencies_after,
        )


@dataclass(frozen=True)
class ClosureCandidateAudit:
    action: TableauAction
    stage: ClosureCandidateStage
    disposition: ClosureCandidateDisposition
    target_dependency_id: str
    generated: bool
    legally_possible: bool
    target_relevant: bool
    progress: ClosureProgressEvidence
    lifecycle: Optional[MoveLifecycleAssessment]
    receiver_required: Optional[int]
    workspace_required: bool
    temporary_park: bool
    bounded_exit_route: Optional[str]
    rejection_reason: Optional[ClosureCandidateRejectionReason]
    rejection_detail: str
    admission_rank: Optional[int]
    beam_rank: Optional[int]
    exact_state_dedup: Optional[str]
    eventual_outcome: Optional[str]
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class ClosureBeamDepthAudit:
    search_depth: int
    generated: int
    replay_valid: int
    target_progress: int
    prerequisite_progress: int
    retained: int
    discarded: int
    cutoff_rank: Optional[int]
    best_discarded_action: Optional[TableauAction]
    best_discarded_progress: Optional[ClosureProgressKind]
    retained_progress_kinds: Tuple[ClosureProgressKind, ...]
    source_depths_retained: Tuple[int, ...]
    source_depths_discarded: Tuple[int, ...]
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class BuriedSourceClosureTrace:
    campaign_id: str
    semantic_target_id: Optional[str]
    target_dependency_id: str
    starting_state_key: CanonicalStateKey
    required_source: Card
    blocker_before: BuriedSourceBlocker
    blocker_after: BuriedSourceBlocker
    candidate_audits: Tuple[ClosureCandidateAudit, ...]
    beam_audits: Tuple[ClosureBeamDepthAudit, ...]
    generated_actions: Tuple[TableauAction, ...]
    legal_target_relevant_actions: Tuple[TableauAction, ...]
    missing_from_generator: Tuple[TableauAction, ...]
    source_copy_substitutions: int
    sources_exposed: int
    source_consumed: bool
    failure_diagnosis: ClosureFailureDiagnosis
    outcome: str
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class LegalCandidateCoverageAudit:
    """Independent set comparison used only by diagnostics and tests."""

    target_dependency_id: str
    legally_possible: Tuple[TableauAction, ...]
    generated: Tuple[TableauAction, ...]
    missing_from_generator: Tuple[TableauAction, ...]
    generated_outside_legal_audit: Tuple[TableauAction, ...]
    coverage_complete: bool
    failure_diagnosis: ClosureFailureDiagnosis
    proof_pruning_allowed: bool = False


def compare_legal_candidate_coverage(
    target_dependency_id: str,
    legally_possible: Sequence[TableauAction],
    generated: Sequence[TableauAction],
) -> LegalCandidateCoverageAudit:
    """Compare independently collected legal and generator sets.

    This function does not enumerate production successors and has no pruning
    authority.  Keeping the comparison separate makes a missing generator
    class directly testable instead of making coverage true by construction.
    """

    legal_set = set(legally_possible)
    generated_set = set(generated)
    missing = tuple(sorted(legal_set - generated_set))
    outside = tuple(sorted(generated_set - legal_set))
    return LegalCandidateCoverageAudit(
        target_dependency_id,
        tuple(sorted(legal_set)),
        tuple(sorted(generated_set)),
        missing,
        outside,
        not missing,
        (
            ClosureFailureDiagnosis.SEARCH_POLICY
            if missing
            else ClosureFailureDiagnosis.NONE
        ),
    )


def _movable_suffix_count(cards: Sequence[Card]) -> int:
    count = 0
    for size in range(1, len(cards) + 1):
        if SpiderState.is_movable_run(list(cards[-size:])):
            count = size
        else:
            break
    return count


def _source_key(zone: str, column: int, index: int, card: Card) -> str:
    return f"tableau:{column}:{zone}:{index}:{card.suit}{card.rank}"


def physical_source_alternatives(
    state: SpiderState,
    card: Card,
) -> Tuple[PhysicalSourceAlternative, ...]:
    """Return every physical tableau copy with exact current blocker geometry."""

    alternatives = []
    for column_index, column in enumerate(state.columns):
        for index, current in enumerate(column.face_up):
            if current != card:
                continue
            suffix = column.face_up[index:]
            movable_count = len(suffix) if SpiderState.is_movable_run(suffix) else 0
            destinations = tuple(
                destination
                for destination in range(len(state.columns))
                if movable_count
                and state.can_move(column_index, destination, movable_count)
            )
            blockers = tuple(reversed(column.face_up[index + 1 :]))
            alternatives.append(
                PhysicalSourceAlternative(
                    _source_key("up", column_index, index, card),
                    card,
                    column_index,
                    "face_up",
                    index,
                    len(blockers),
                    blockers,
                    bool(movable_count),
                    bool(destinations),
                    movable_count,
                    destinations,
                )
            )
        for index, current in enumerate(column.face_down):
            if current != card:
                continue
            blockers = tuple(
                list(reversed(column.face_up))
                + list(reversed(column.face_down[index + 1 :]))
            )
            alternatives.append(
                PhysicalSourceAlternative(
                    _source_key("down", column_index, index, card),
                    card,
                    column_index,
                    "face_down",
                    index,
                    len(blockers),
                    blockers,
                    False,
                    False,
                    0,
                    (),
                )
            )
    return tuple(sorted(alternatives, key=lambda item: item.ordering_key))


def _blocker_runs(cards: Sequence[Card]) -> Tuple[Tuple[Card, ...], ...]:
    """Group top-to-bottom blocker cards into same-suit movable units."""

    groups = []
    current = []
    for card in cards:
        if (
            current
            and card.suit == current[-1].suit
            and card.rank == current[-1].rank + 1
        ):
            current.append(card)
        else:
            if current:
                groups.append(tuple(current))
            current = [card]
    if current:
        groups.append(tuple(current))
    return tuple(groups)


def describe_buried_source(
    state: SpiderState,
    dependency_id: str,
    card: Card,
) -> BuriedSourceBlocker:
    alternatives = physical_source_alternatives(state, card)
    chosen = alternatives[0] if alternatives else None
    legal_moves: Tuple[TableauAction, ...] = ()
    receiver_rank = None
    blockers: Tuple[Card, ...] = ()
    if chosen is not None:
        blockers = chosen.blocker_cards
        if blockers:
            receiver_rank = blockers[0].rank + 1 if blockers[0].rank < 13 else None
            legal_moves = tuple(
                action
                for action in state.enumerate_moves()
                if action[0] == chosen.column
                and action[2] <= max(1, chosen.depth)
            )
    return BuriedSourceBlocker(
        dependency_id,
        card,
        alternatives,
        chosen.source_key if chosen else None,
        chosen.column if chosen else None,
        chosen.zone if chosen else None,
        chosen.depth if chosen else 10**6,
        blockers,
        _blocker_runs(blockers),
        legal_moves,
        receiver_rank,
    )


def source_progress_evidence(
    before_state: SpiderState,
    after_state: SpiderState,
    dependency_id: str,
    card: Card,
    action: TableauAction,
    lifecycle: MoveLifecycleAssessment,
    *,
    dependencies_before: int,
    dependencies_after: int,
    dependency_present_after: bool,
) -> ClosureProgressEvidence:
    before = describe_buried_source(before_state, dependency_id, card)
    after = describe_buried_source(after_state, dependency_id, card)
    before_chosen = before.chosen
    after_chosen = after.chosen
    depth_reduced = after.source_depth < before.source_depth
    blockers_reduced = len(after.blocker_cards) < len(before.blocker_cards)
    exposed = bool(
        after_chosen
        and after_chosen.exposed
        and not (before_chosen and before_chosen.exposed)
    )
    actionable = bool(
        after_chosen
        and after_chosen.actionable
        and not (before_chosen and before_chosen.actionable)
    )
    consumed = not dependency_present_after
    substituted = bool(
        before.chosen_source_key
        and after.chosen_source_key
        and before.chosen_source_key != after.chosen_source_key
    )
    receiver_created = bool(
        before.blocker_cards
        and not before.legal_blocker_moves
        and after.legal_blocker_moves
        and action[0] != before.chosen_column
    )
    workspace_created = sum(column.is_empty() for column in after_state.columns) > sum(
        column.is_empty() for column in before_state.columns
    )
    temporary = lifecycle.placement_class in {
        PlacementClass.MIXED_SUIT_PARK,
        PlacementClass.WORKSPACE_PARK,
    }
    stable = lifecycle.placement_class in {
        PlacementClass.STABLE_SAME_SUIT_JOIN,
        PlacementClass.PROVISIONAL_SAME_SUIT_JOIN,
    }
    direct = bool(
        before.chosen_column is not None
        and action[0] == before.chosen_column
        and (depth_reduced or blockers_reduced)
    )
    if consumed:
        kind = ClosureProgressKind.SOURCE_CONSUMED
    elif exposed:
        kind = ClosureProgressKind.SOURCE_EXPOSED
    elif actionable:
        kind = ClosureProgressKind.SOURCE_ACTIONABLE
    elif depth_reduced:
        kind = ClosureProgressKind.SOURCE_DEPTH_REDUCED
    elif direct:
        kind = ClosureProgressKind.DIRECT_BLOCKER_REMOVAL
    elif receiver_created:
        kind = ClosureProgressKind.RECEIVER_CREATED
    elif workspace_created:
        kind = ClosureProgressKind.WORKSPACE_CREATED
    elif substituted:
        kind = ClosureProgressKind.SOURCE_COPY_SUBSTITUTED
    elif temporary:
        kind = ClosureProgressKind.TEMPORARY_PARK
    elif stable:
        kind = ClosureProgressKind.PERMANENT_SAME_SUIT_PREREQUISITE
    else:
        kind = ClosureProgressKind.NO_PROGRESS
    prerequisite = receiver_created or workspace_created or (
        kind
        in {
            ClosureProgressKind.TEMPORARY_PARK,
            ClosureProgressKind.PERMANENT_SAME_SUIT_PREREQUISITE,
        }
        and after.legal_blocker_moves != before.legal_blocker_moves
    )
    target_relevant = bool(
        consumed
        or exposed
        or actionable
        or depth_reduced
        or blockers_reduced
        or prerequisite
        or substituted
    )
    return ClosureProgressEvidence(
        kind,
        target_relevant,
        prerequisite,
        before.source_depth,
        after.source_depth,
        len(before.blocker_cards),
        len(after.blocker_cards),
        dependencies_before,
        dependencies_after,
        receiver_created,
        workspace_created,
        exposed,
        actionable,
        consumed,
        substituted,
        (
            f"{kind.value}: source depth {before.source_depth}->{after.source_depth}; "
            f"blockers {len(before.blocker_cards)}->{len(after.blocker_cards)}; "
            f"dependencies {dependencies_before}->{dependencies_after}"
        ),
    )


def no_progress_evidence(
    blocker: BuriedSourceBlocker,
    dependencies: int,
    reason: str,
) -> ClosureProgressEvidence:
    return ClosureProgressEvidence(
        ClosureProgressKind.NO_PROGRESS,
        False,
        False,
        blocker.source_depth,
        blocker.source_depth,
        len(blocker.blocker_cards),
        len(blocker.blocker_cards),
        dependencies,
        dependencies,
        False,
        False,
        False,
        False,
        False,
        False,
        reason,
    )
