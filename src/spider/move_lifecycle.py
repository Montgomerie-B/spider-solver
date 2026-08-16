"""Ordering-only lifecycle accounting for Spider tableau placements.

Immediate MobilityWare cost is not a sufficient equivalence relation.  This
module records the structural boundary changes made by a legal move and the
minimum future work implied by temporary parks.  Its debt is deliberately
heuristic: callers may use it to order otherwise-comparable moves, never as an
admissible lower bound or proof-pruning rule.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional, Tuple

from .engine import SpiderState
from .rules import mw_move_cost


TableauMove = Tuple[int, int, int]


class PlacementClass(str, Enum):
    STABLE_SAME_SUIT_JOIN = "STABLE_SAME_SUIT_JOIN"
    PROVISIONAL_SAME_SUIT_JOIN = "PROVISIONAL_SAME_SUIT_JOIN"
    MIXED_SUIT_PARK = "MIXED_SUIT_PARK"
    WORKSPACE_PARK = "WORKSPACE_PARK"


@dataclass(frozen=True)
class BoundedCompensatingBenefit:
    """Concrete bounded evidence that can justify a temporary park."""

    expected_saving: float
    evidence: str
    override_reason: str


@dataclass(frozen=True)
class MoveLifecycleAssessment:
    action: TableauMove
    placement_class: PlacementClass
    immediate_cost: int
    same_suit_joins_created: Tuple[str, ...]
    same_suit_joins_broken: Tuple[str, ...]
    mixed_suit_boundaries_created: Tuple[str, ...]
    mixed_suit_boundaries_removed: Tuple[str, ...]
    future_exit_route: str
    exit_route_bounded: bool
    estimated_rehandling_cost: float
    provisional_reason: Optional[str] = None
    compensating_benefit: Optional[BoundedCompensatingBenefit] = None
    proof_pruning_allowed: bool = False

    @property
    def can_override_permanent_join(self) -> bool:
        benefit = self.compensating_benefit
        return bool(
            self.placement_class == PlacementClass.MIXED_SUIT_PARK
            and self.exit_route_bounded
            and benefit is not None
            and benefit.override_reason.strip()
            and benefit.expected_saving > self.estimated_rehandling_cost
        )

    @property
    def projected_lifecycle_cost(self) -> float:
        """Immediate cost plus ordering-only future rehandling estimate."""
        return float(self.immediate_cost) + self.estimated_rehandling_cost

    def ordering_key(self) -> Tuple[float, int, int, int]:
        """Tie-break key for otherwise comparable moves; lower is preferred."""
        class_rank = {
            PlacementClass.STABLE_SAME_SUIT_JOIN: 0,
            PlacementClass.PROVISIONAL_SAME_SUIT_JOIN: 1,
            PlacementClass.WORKSPACE_PARK: 2,
            PlacementClass.MIXED_SUIT_PARK: 3,
        }[self.placement_class]
        net_debt = self.estimated_rehandling_cost
        if self.can_override_permanent_join:
            assert self.compensating_benefit is not None
            net_debt -= self.compensating_benefit.expected_saving
            class_rank = -1
        return (
            net_debt,
            class_rank,
            len(self.mixed_suit_boundaries_created),
            -len(self.same_suit_joins_created),
        )


def _boundary_label(lower, upper, column: int) -> str:
    return f"{lower}-{upper}@c{column + 1}"


def _same_suit_join(lower, upper) -> bool:
    return lower.suit == upper.suit and lower.rank - 1 == upper.rank


def _discover_exit_route(
    post: SpiderState, source_column: int, k: int
) -> Tuple[str, bool]:
    if k <= 0 or k > len(post.columns[source_column].face_up):
        return "no exit required: moved cards are no longer in tableau", True
    run = post.columns[source_column].face_up[-k:]
    preferred = []
    fallback = []
    for dst in range(len(post.columns)):
        if dst == source_column or not post.can_move(source_column, dst, k):
            continue
        top = post.columns[dst].top()
        route = (
            f"move {run[0]}-{run[-1]} from c{source_column + 1} "
            f"to c{dst + 1}"
        )
        if top is not None and top.suit == run[0].suit:
            preferred.append(route + f" on same-suit {top}")
        else:
            fallback.append(route + (f" on {top}" if top is not None else " into empty"))
    if preferred:
        return preferred[0], True
    if fallback:
        return fallback[0], True
    return "unresolved: requires a future rank+1 receiver or empty workspace", False


def assess_tableau_move(
    state: SpiderState,
    action: TableauMove,
    *,
    provisional_reason: Optional[str] = None,
    future_exit_route: Optional[str] = None,
    exit_route_bounded: Optional[bool] = None,
    compensating_benefit: Optional[BoundedCompensatingBenefit] = None,
    discover_exit: bool = True,
) -> MoveLifecycleAssessment:
    """Classify one legal move and record its local lifecycle obligations."""
    src, dst, k = action
    if not state.can_move(src, dst, k):
        raise ValueError(f"cannot assess illegal move {action}")

    src_col = state.columns[src]
    dst_col = state.columns[dst]
    run = src_col.face_up[-k:]
    source_lower = src_col.face_up[-k - 1] if len(src_col.face_up) > k else None
    moved_head = run[0]
    dest_top = dst_col.top()
    destination_was_empty = dest_top is None

    joins_created = ()
    mixed_created = ()
    if dest_top is not None:
        label = _boundary_label(dest_top, moved_head, dst)
        if _same_suit_join(dest_top, moved_head):
            joins_created = (label,)
        elif dest_top.suit != moved_head.suit:
            mixed_created = (label,)

    joins_broken = ()
    mixed_removed = ()
    if source_lower is not None:
        label = _boundary_label(source_lower, moved_head, src)
        if _same_suit_join(source_lower, moved_head):
            joins_broken = (label,)
        elif source_lower.suit != moved_head.suit:
            mixed_removed = (label,)

    immediate_cost = mw_move_cost(
        cards_moved=k,
        source_face_up_count=len(src_col.face_up),
        dest_was_empty=destination_was_empty,
        source_face_down_count=len(src_col.face_down),
    )
    post = None
    removed_to_foundation = False
    if discover_exit:
        post = state.clone()
        applied_cost = post.move(src, dst, k)
        assert applied_cost == immediate_cost
        removed_to_foundation = len(post.foundations) > len(state.foundations)

    if destination_was_empty:
        placement = PlacementClass.WORKSPACE_PARK
    elif joins_created:
        if provisional_reason or len(joins_broken) > len(joins_created):
            placement = PlacementClass.PROVISIONAL_SAME_SUIT_JOIN
        else:
            placement = PlacementClass.STABLE_SAME_SUIT_JOIN
    else:
        placement = PlacementClass.MIXED_SUIT_PARK

    route = future_exit_route
    bounded = exit_route_bounded
    rehandling = 0.0
    if removed_to_foundation:
        route = route or "completed foundation; no tableau exit required"
        bounded = True if bounded is None else bounded
    elif placement == PlacementClass.STABLE_SAME_SUIT_JOIN:
        route = route or "carry the permanent same-suit band toward foundation"
        bounded = True if bounded is None else bounded
    elif (
        placement == PlacementClass.WORKSPACE_PARK
        and k == len(src_col.face_up)
        and not src_col.face_down
    ):
        route = route or f"reverse the whole-column relocation into vacated c{src + 1}"
        bounded = True if bounded is None else bounded
    elif not discover_exit:
        route = route or "not evaluated by ordering-only lifecycle assessment"
        bounded = False if bounded is None else bounded
        rehandling = 1.0 + len(joins_broken)
    else:
        assert post is not None
        discovered, discovered_bounded = _discover_exit_route(post, dst, k)
        route = route or discovered
        bounded = discovered_bounded if bounded is None else bounded
        rehandling = 1.0 + len(joins_broken)

    assessment = MoveLifecycleAssessment(
        action=action,
        placement_class=placement,
        immediate_cost=immediate_cost,
        same_suit_joins_created=joins_created,
        same_suit_joins_broken=joins_broken,
        mixed_suit_boundaries_created=mixed_created,
        mixed_suit_boundaries_removed=mixed_removed,
        future_exit_route=route,
        exit_route_bounded=bool(bounded),
        estimated_rehandling_cost=rehandling,
        provisional_reason=provisional_reason,
        compensating_benefit=compensating_benefit,
    )
    if compensating_benefit is not None and not assessment.can_override_permanent_join:
        # Preserve the evidence for diagnostics, but do not grant priority.
        return replace(assessment, compensating_benefit=compensating_benefit)
    return assessment


def with_bounded_compensation(
    assessment: MoveLifecycleAssessment,
    benefit: BoundedCompensatingBenefit,
) -> MoveLifecycleAssessment:
    """Attach bounded park evidence without changing proof semantics."""
    return replace(assessment, compensating_benefit=benefit)


def stable_join_dominates(
    stable: MoveLifecycleAssessment,
    alternative: MoveLifecycleAssessment,
    *,
    comparable_effects: bool,
) -> bool:
    """Return the ordering-only dominance result for a comparable pair."""
    if not comparable_effects or stable.immediate_cost != alternative.immediate_cost:
        return False
    if stable.placement_class != PlacementClass.STABLE_SAME_SUIT_JOIN:
        return False
    if alternative.can_override_permanent_join:
        return False
    return stable.ordering_key() < alternative.ordering_key()
