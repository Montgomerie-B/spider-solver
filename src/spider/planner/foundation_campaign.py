"""Perfect-information foundation campaign planning.

This module turns foundation feasibility into a chronological plan of attack:

* choose the next outstanding foundation ordinal for every suit;
* work backwards from a proposed removal epoch;
* substitute interchangeable physical copies before charging excavation;
* union tableau/project prerequisites instead of double-counting them;
* treat an empty column as spendable working capital; and
* describe the exact known stock rows and receiver geometry up to removal.

The analysis is diagnostic.  It does not search a whole game, modify scoring,
or integrate with :mod:`spider.planner.plan_search`.  Theoretical stock epochs
are hard facts.  Target epochs, costs, readiness, confidence, and ranking are
transparent heuristics and must not be used as proof pruning.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from itertools import product
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from spider.cards import Card, rank_str
from spider.deal import stock_deal_rounds
from spider.engine import SpiderState
from spider.planner.backward_strategy import (
    BuriedCardFact,
    SpaceLiquidity,
    StockBackwardPass,
    analyze_buried_cards,
    analyze_space_liquidity,
    analyze_stock_backward,
)
from spider.planner.excavation_closure import (
    ProjectClosure,
    close_all_columns,
)
from spider.planner.foundation_feasibility import (
    FOUNDATION_RANKS,
    FoundationCandidate,
    FoundationFeasibilityAnalysis,
    SuitFragmentFact,
    analyze_foundation_feasibility,
    epoch_name,
)
from spider.planner.space_lifecycle import (
    WorkspaceEffectKind,
    empty_columns,
    empty_count,
    simulate_move_effect,
)
from spider.planner.workspace_obstruction import longest_movable_k, profile_state
from spider.rules import deal_cost


class RankSourceKind(str, Enum):
    """How one physical rank copy can contribute to a campaign."""

    ALREADY_USABLE = "already_usable"
    SHALLOW_TABLEAU = "shallow_tableau"
    DEEP_TABLEAU = "deep_tableau"
    STOCK = "stock"
    LATE_STOCK = "late_stock"
    COMPLETED_FOUNDATION = "completed_foundation"


class SpacePolicy(str, Enum):
    """Recommended treatment of current workspace."""

    NONE = "none"
    CREATE_THEN_SPEND = "create_then_spend"
    HOLD = "hold"
    SPEND = "spend"
    RELOCATE = "relocate"
    FILL_BEFORE_DEAL = "fill_before_deal"
    CARRY_AND_RECOVER = "carry_and_recover"


class CampaignReadiness(str, Enum):
    READY_NOW = "ready_now"
    EXCAVATION_LED = "excavation_led"
    STOCK_GATED = "stock_gated"
    ASSEMBLY_LED = "assembly_led"
    DEFERRED = "deferred"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class RankSource:
    """One physical copy with stable provenance.

    ``source_key`` is necessary because :class:`Card` is a value object and
    the two physical copies of (for example) ``7s`` otherwise compare equal.
    """

    source_key: str
    card: Card
    kind: RankSourceKind
    column: Optional[int]
    tableau_zone: Optional[str]
    depth: int
    stock_epoch: Optional[int]
    stock_column: Optional[int]
    usable_by_target: bool
    reserved_by_completed_foundation: bool
    excavation_peels: int
    closure_prefix_hops: int
    helper_tasks: Tuple[Tuple[int, int], ...]
    needs_temp_space: bool
    dependency_blocked: bool
    reception_status: str
    estimated_cost: float
    note: str

    @property
    def is_tableau_work(self) -> bool:
        return self.kind in (
            RankSourceKind.SHALLOW_TABLEAU,
            RankSourceKind.DEEP_TABLEAU,
        )

    @property
    def is_conditional(self) -> bool:
        return self.reception_status in (
            "requires_predeal_shaping",
            "prospective_known_row",
            "unvalidated_tableau_peels",
        )


@dataclass(frozen=True)
class CampaignRankNeed:
    rank: int
    sources: Tuple[RankSource, ...]
    chosen: Optional[RankSource]
    must_excavate: bool
    safe_to_wait: Tuple[RankSource, ...]
    reason: str


@dataclass(frozen=True)
class CampaignExcavationProject:
    column: int
    required_ranks: Tuple[int, ...]
    source_keys: Tuple[str, ...]
    required_peels: int
    helper_tasks: Tuple[Tuple[int, int], ...]
    deadline_epoch: int
    deadline_before_deal: bool
    needs_temp_space: bool
    blocked_dependencies: int
    estimated_direct_cost: int
    estimated_prep_cost: int
    estimated_total_cost: int
    notes: Tuple[str, ...]


@dataclass(frozen=True)
class CampaignIncomingCard:
    card: Card
    column: int
    selected_source: bool
    receiver_requirement: str
    landing_now: str
    reception_status: str
    geometry_is_exact: bool


@dataclass(frozen=True)
class CampaignEpochPlan:
    epoch: int
    epoch_label: str
    incoming: Tuple[CampaignIncomingCard, ...]
    campaign_ranks_arriving: Tuple[int, ...]
    selected_ranks_arriving: Tuple[int, ...]
    available_rank_bands_before: Tuple[Tuple[int, int], ...]
    receiver_requirements: Tuple[str, ...]
    useful_same_suit_joins: Tuple[str, ...]
    carry_empty_policy: str
    expected_workspace_after_deal: Optional[int]
    unlocks: Tuple[str, ...]
    geometry_is_exact: bool


@dataclass(frozen=True)
class CampaignSpacePlan:
    workspace_available_now: int
    cheapest_recoverable_workspace: Optional[int]
    likely_temporary_uses: Tuple[str, ...]
    policy: SpacePolicy
    enabled_action: str
    enabled_project_column: Optional[int]
    enabled_ranks: Tuple[int, ...]
    action: Optional[Tuple[int, int, int]]
    estimated_regain_cost: Optional[int]
    next_deal_policy: str
    reasons: Tuple[str, ...]


@dataclass(frozen=True)
class CriticalPathStep:
    epoch: int
    phase: str
    description: str
    ranks: Tuple[int, ...]
    columns: Tuple[int, ...]


@dataclass(frozen=True)
class CampaignScoreBreakdown:
    epoch_delay: float
    excavation: float
    stock_handling: float
    assembly_and_parking: float
    workspace: float
    current_structure_credit: float
    stock_assistance_credit: float
    structural_payoff_credit: float
    uncertainty: float
    total: float


@dataclass(frozen=True)
class FoundationCampaign:
    suit: str
    copy_index: int
    current_epoch: int
    earliest_theoretical_epoch: Optional[int]
    target_removal_epoch: Optional[int]
    current_same_suit_fragments: Tuple[SuitFragmentFact, ...]
    required_ranks: Tuple[int, ...]
    rank_needs: Tuple[CampaignRankNeed, ...]
    tableau_critical_cards: Tuple[RankSource, ...]
    future_stock_supplied_cards: Tuple[RankSource, ...]
    optional_replaceable_buried_copies: Tuple[RankSource, ...]
    prerequisite_excavation_projects: Tuple[CampaignExcavationProject, ...]
    shared_prerequisite_tasks: Tuple[Tuple[int, int], ...]
    shared_prerequisite_saving: int
    space_requirement: int
    estimated_park_moves: int
    pre_deal_receiver_requirements: Tuple[str, ...]
    stock_plan: Tuple[CampaignEpochPlan, ...]
    space_plan: CampaignSpacePlan
    critical_path: Tuple[CriticalPathStep, ...]
    estimated_campaign_cost: float
    expected_structural_payoff: float
    confidence: str
    blockers: Tuple[str, ...]
    readiness: CampaignReadiness
    readiness_score: float
    campaign_score: float
    score_breakdown: CampaignScoreBreakdown
    rationale: Tuple[str, ...]

    @property
    def label(self) -> str:
        return f"{self.suit.upper()}#{self.copy_index}"

    def rank_need(self, rank: int) -> CampaignRankNeed:
        for need in self.rank_needs:
            if need.rank == rank:
                return need
        raise KeyError(rank)


@dataclass(frozen=True)
class FoundationCampaignPortfolio:
    current_epoch: int
    campaigns: Tuple[FoundationCampaign, ...]
    primary: Optional[FoundationCampaign]
    secondary: Optional[FoundationCampaign]
    deferred: Tuple[FoundationCampaign, ...]
    notes: Tuple[str, ...]

    def campaign_for(self, suit: str, copy_index: Optional[int] = None) -> FoundationCampaign:
        suit = suit.lower()
        for campaign in self.campaigns:
            if campaign.suit == suit and (
                copy_index is None or campaign.copy_index == copy_index
            ):
                return campaign
        raise KeyError((suit, copy_index))


@dataclass(frozen=True)
class _Context:
    cards: Tuple[Card, ...]
    state: SpiderState
    foundation: FoundationFeasibilityAnalysis
    buried: Tuple[BuriedCardFact, ...]
    closures: Dict[int, ProjectClosure]
    liquidity: SpaceLiquidity
    stock_backward: StockBackwardPass
    current_epoch: int
    stock_deals_total: int


def _foundations_removed(state: SpiderState, suit: str) -> int:
    return sum(
        1
        for seq in state.foundations
        if len(seq) == 13 and seq and all(c.suit == suit for c in seq)
    )


def _candidate_for(
    analysis: FoundationFeasibilityAnalysis, suit: str, copy_index: int
) -> FoundationCandidate:
    for candidate in analysis.frontier.candidates:
        if candidate.suit == suit and candidate.copy_index == copy_index:
            return candidate
    raise KeyError((suit, copy_index))


def _face_up_peels_above(cards: Sequence[Card]) -> int:
    """Number of descending suffix groups that must move to clear ``cards``.

    ``cards`` is the face-up material above a target, bottom-to-top.  This is
    a move-count estimate, not a legality proof that all destinations exist.
    """
    if not cards:
        return 0
    groups = 1
    for i in range(len(cards) - 1):
        if cards[i].rank - 1 != cards[i + 1].rank:
            groups += 1
    return groups


def _top_usable_indexes(state: SpiderState, suit: str) -> Dict[int, set[int]]:
    """Face-up indexes already usable alone or in a top same-suit fragment."""
    out: Dict[int, set[int]] = {}
    for col_idx, col in enumerate(state.columns):
        usable: set[int] = set()
        if col.face_up:
            usable.add(len(col.face_up) - 1)
        i = len(col.face_up) - 1
        while i > 0:
            upper = col.face_up[i]
            lower = col.face_up[i - 1]
            if (
                upper.suit == suit
                and lower.suit == suit
                and lower.rank - 1 == upper.rank
            ):
                usable.add(i - 1)
                i -= 1
            else:
                break
        out[col_idx] = usable
    return out


def _landing_label(state: SpiderState, column: int, incoming: Card) -> str:
    top = state.columns[column].top()
    if top is None:
        return "empty_landing"
    if top.rank - 1 != incoming.rank:
        return "non_connecting"
    return "same_suit_connect" if top.suit == incoming.suit else "mixed_rank_connect"


def _receiver_penalty(state: SpiderState, epoch: int, column: int, card: Card, current: int) -> float:
    if epoch != current + 1:
        return 0.75
    landing = _landing_label(state, column, card)
    if landing == "same_suit_connect":
        return 0.1
    if landing == "mixed_rank_connect":
        return 0.65
    if landing == "empty_landing":
        return 0.9
    return 1.0


def _exact_next_row_reception(state: SpiderState) -> Dict[int, str]:
    """Classify next-row extraction against the unchanged snapshot.

    Exact means the row, receiver columns, and one-move outs are replayed from
    this state.  It does not claim that a proposed pre-deal excavation leaves
    those tops unchanged; callers therefore describe it as snapshot-exact.
    """
    if len(state.stock) < 10:
        return {}
    row = tuple(state.stock[-10:])
    landings = {
        column: _landing_label(state, column, card)
        for column, card in enumerate(row)
    }
    post = state.clone()
    post.deal()
    one_card_outs = {src for src, _dst, k in post.enumerate_moves() if k == 1}
    statuses: Dict[int, str] = {}
    for column, card in enumerate(row):
        if landings[column] == "same_suit_connect":
            statuses[column] = "snapshot_exact_connected"
        elif post.columns[column].top() != card:
            # The deal can immediately complete and remove a sequence.
            statuses[column] = "snapshot_exact_completed"
        elif column in one_card_outs:
            statuses[column] = "snapshot_exact_extractable"
        else:
            statuses[column] = "requires_predeal_shaping"
    return statuses


def _reception_risk(status: str) -> float:
    if status in ("snapshot_exact_connected", "snapshot_exact_completed"):
        return 0.0
    if status == "snapshot_exact_extractable":
        return 0.25
    if status == "requires_predeal_shaping":
        return 1.25
    if status == "prospective_known_row":
        return 1.0
    return 0.0


def _prefix_closure_metadata(
    closure: Optional[ProjectClosure],
    prefix_hops: int,
    *,
    target_epoch: int,
    stock_epoch_inclusive: bool = True,
) -> Tuple[Tuple[Tuple[int, int], ...], bool, bool, int]:
    """Return helper union, temporary-space flag, blocked flag, prep estimate.

    The existing closure prices an entire column.  A campaign needs only the
    prefix through its selected card, so inspect only that prefix's public
    ``HopClosure`` records and max-union their preparation tasks.
    """
    if closure is None or prefix_hops <= 0:
        return (), False, False, 0
    helper: Dict[int, int] = {}
    needs_space = False
    blocked = False
    extra = 0
    for hop in closure.hop_closures[:prefix_hops]:
        needs_space = needs_space or hop.needs_space
        if hop.future_stock:
            stock_epochs = [
                option.loc.stock_epoch
                for option in hop.options
                if option.loc.stock_epoch is not None
            ]
            # A future destination only satisfies this source prefix if it
            # enters play no later than the campaign target.
            stock_is_late = (
                min(stock_epochs) > target_epoch
                if stock_epoch_inclusive
                else min(stock_epochs) >= target_epoch
            ) if stock_epochs else True
            if stock_is_late:
                blocked = True
        elif hop.blocked and not hop.needs_space:
            # A King with no current empty is a workspace prerequisite, not
            # proof that the card cannot be exposed this epoch.
            blocked = True
        for col, depth in hop.prep_tasks:
            helper[col] = max(helper.get(col, 0), depth)
        if not hop.prep_tasks:
            extra += max(0, hop.prep_cost)
    tasks = tuple(sorted(helper.items()))
    return tasks, needs_space, blocked, sum(helper.values()) + extra


def _enumerate_sources(
    ctx: _Context,
    *,
    suit: str,
    target_epoch: int,
) -> Dict[int, Tuple[RankSource, ...]]:
    state = ctx.state
    current = ctx.current_epoch
    usable_indexes = _top_usable_indexes(state, suit)
    by_rank: Dict[int, List[RankSource]] = {r: [] for r in FOUNDATION_RANKS}

    for col_idx, col in enumerate(state.columns):
        for fd_idx, card in enumerate(col.face_down):
            if card.suit != suit:
                continue
            depth = len(col.face_down) - 1 - fd_idx
            face_groups = _face_up_peels_above(col.face_up)
            peels = max(1, face_groups + depth)
            prefix_hops = max(1, depth + 1)
            conditional_peels = face_groups > 1
            tasks, needs_space, blocked, prep = _prefix_closure_metadata(
                ctx.closures.get(col_idx),
                prefix_hops,
                target_epoch=target_epoch,
            )
            kind = (
                RankSourceKind.SHALLOW_TABLEAU
                if peels <= 2 and not blocked and not needs_space
                else RankSourceKind.DEEP_TABLEAU
            )
            cost = float(peels + prep)
            if needs_space:
                cost += 1.5
            if blocked:
                cost += 8.0
            if conditional_peels:
                cost += 1.5
            by_rank[card.rank].append(
                RankSource(
                    source_key=f"tableau:{col_idx}:down:{fd_idx}",
                    card=card,
                    kind=kind,
                    column=col_idx,
                    tableau_zone="face_down",
                    depth=depth,
                    stock_epoch=None,
                    stock_column=None,
                    usable_by_target=not blocked,
                    reserved_by_completed_foundation=False,
                    excavation_peels=peels,
                    closure_prefix_hops=prefix_hops,
                    helper_tasks=tasks,
                    needs_temp_space=needs_space,
                    dependency_blocked=blocked,
                    reception_status=(
                        "unvalidated_tableau_peels"
                        if conditional_peels
                        else "not_applicable"
                    ),
                    estimated_cost=round(cost, 2),
                    note=(
                        f"tableau col {col_idx + 1}, face-down reveal depth {depth}; "
                        f"prefix peels~{peels}"
                    ),
                )
            )
        for up_idx, card in enumerate(col.face_up):
            if card.suit != suit:
                continue
            depth = len(col.face_up) - 1 - up_idx
            if up_idx in usable_indexes[col_idx]:
                kind = RankSourceKind.ALREADY_USABLE
                peels = 0
                cost = 0.0
                note = f"usable in top fragment on col {col_idx + 1}"
            else:
                peels = _face_up_peels_above(col.face_up[up_idx + 1 :])
                kind = (
                    RankSourceKind.SHALLOW_TABLEAU
                    if peels <= 2
                    else RankSourceKind.DEEP_TABLEAU
                )
                # Existing column closures describe the current movable head,
                # not a target-relative peel above an arbitrary face-up card.
                # Until such a closure is public, every non-top face-up source
                # remains a conditional estimate, even when its blockers form
                # one legal descending run.
                cost = float(max(1, peels)) + 1.5
                note = f"face-up under {depth} card(s) on col {col_idx + 1}"
            by_rank[card.rank].append(
                RankSource(
                    source_key=f"tableau:{col_idx}:up:{up_idx}",
                    card=card,
                    kind=kind,
                    column=col_idx,
                    tableau_zone="face_up",
                    depth=depth,
                    stock_epoch=None,
                    stock_column=None,
                    usable_by_target=True,
                    reserved_by_completed_foundation=False,
                    excavation_peels=peels,
                    closure_prefix_hops=0,
                    helper_tasks=(),
                    needs_temp_space=False,
                    dependency_blocked=False,
                    reception_status=(
                        "unvalidated_tableau_peels"
                        if kind != RankSourceKind.ALREADY_USABLE
                        else "not_applicable"
                    ),
                    estimated_cost=round(cost, 2),
                    note=note,
                )
            )

    # Exact stock row mapping.  Do not use backward_strategy.CardLocation.column:
    # that legacy helper reverses columns inside each ten-card row.
    exact_reception = _exact_next_row_reception(state)
    for offset, row in enumerate(stock_deal_rounds(list(state.stock)), 1):
        epoch = current + offset
        for column, card in enumerate(row):
            if card.suit != suit:
                continue
            usable = epoch <= target_epoch
            kind = RankSourceKind.STOCK if usable else RankSourceKind.LATE_STOCK
            reception = (
                exact_reception.get(column, "requires_predeal_shaping")
                if offset == 1
                else "prospective_known_row"
            )
            handling = _receiver_penalty(state, epoch, column, card, current)
            wait_carry = 0.2 * max(0, target_epoch - epoch)
            by_rank[card.rank].append(
                RankSource(
                    source_key=f"stock:{epoch}:{column}",
                    card=card,
                    kind=kind,
                    column=None,
                    tableau_zone=None,
                    depth=0,
                    stock_epoch=epoch,
                    stock_column=column,
                    usable_by_target=usable,
                    reserved_by_completed_foundation=False,
                    excavation_peels=0,
                    closure_prefix_hops=0,
                    helper_tasks=(),
                    needs_temp_space=False,
                    dependency_blocked=False,
                    reception_status=reception,
                    estimated_cost=round(
                        0.45 + handling + wait_carry + _reception_risk(reception), 2
                    ),
                    note=(
                        f"arrives {epoch_name(epoch)} on col {column + 1}; "
                        f"reception={reception}"
                        if usable
                        else f"blocked until {epoch_name(epoch)}"
                    ),
                )
            )

    for foundation_idx, sequence in enumerate(state.foundations):
        for card_idx, card in enumerate(sequence):
            if card.suit != suit:
                continue
            by_rank[card.rank].append(
                RankSource(
                    source_key=f"foundation:{foundation_idx}:{card_idx}",
                    card=card,
                    kind=RankSourceKind.COMPLETED_FOUNDATION,
                    column=None,
                    tableau_zone=None,
                    depth=0,
                    stock_epoch=None,
                    stock_column=None,
                    usable_by_target=False,
                    reserved_by_completed_foundation=True,
                    excavation_peels=0,
                    closure_prefix_hops=0,
                    helper_tasks=(),
                    needs_temp_space=False,
                    dependency_blocked=False,
                    reception_status="already_removed",
                    estimated_cost=0.0,
                    note="reserved by an already removed foundation ordinal",
                )
            )

    priority = {
        RankSourceKind.ALREADY_USABLE: 0,
        RankSourceKind.STOCK: 1,
        RankSourceKind.SHALLOW_TABLEAU: 2,
        RankSourceKind.DEEP_TABLEAU: 3,
        RankSourceKind.LATE_STOCK: 4,
        RankSourceKind.COMPLETED_FOUNDATION: 5,
    }
    return {
        rank: tuple(
            sorted(
                sources,
                key=lambda s: (
                    0 if s.usable_by_target and not s.reserved_by_completed_foundation else 1,
                    s.estimated_cost,
                    priority[s.kind],
                    s.source_key,
                ),
            )
        )
        for rank, sources in by_rank.items()
    }


def _merge_excavation_projects(
    selected: Sequence[RankSource],
    *,
    closures: Dict[int, ProjectClosure],
    deadline_epoch: int,
) -> Tuple[
    Tuple[CampaignExcavationProject, ...],
    Tuple[Tuple[int, int], ...],
    int,
    int,
]:
    """Max-union selected source prefixes and their helper prerequisites.

    Returns ``(projects, global_helper_tasks, shared_saving, aggregate_cost)``.
    """
    grouped: Dict[int, List[RankSource]] = {}
    selected_by_rank = {source.card.rank: source for source in selected}

    def source_deadline(source: RankSource) -> Tuple[int, bool]:
        """Return (epoch, before_deal) for making this rank available."""
        child = selected_by_rank.get(source.card.rank - 1)
        if (
            child is not None
            and child.stock_epoch is not None
            and child.stock_epoch <= deadline_epoch
        ):
            return child.stock_epoch, True
        return deadline_epoch, False

    for source in selected:
        if source.is_tableau_work and source.column is not None:
            grouped.setdefault(source.column, []).append(source)

    source_metadata: Dict[
        str,
        Tuple[Tuple[Tuple[int, int], ...], bool, bool, int, bool],
    ] = {}
    for source in selected:
        tasks = source.helper_tasks
        needs_space = source.needs_temp_space
        blocked = source.dependency_blocked
        if (
            source.is_tableau_work
            and source.column is not None
            and source.closure_prefix_hops > 0
        ):
            source_epoch, before_deal = source_deadline(source)
            tasks, needs_space, blocked, _prep = _prefix_closure_metadata(
                closures.get(source.column),
                source.closure_prefix_hops,
                target_epoch=source_epoch,
                stock_epoch_inclusive=not before_deal,
            )
        source_epoch, before_deal = source_deadline(source)
        source_metadata[source.source_key] = (
            tasks,
            needs_space,
            blocked,
            source_epoch,
            before_deal,
        )

    direct_depth = {
        column: max(source.excavation_peels for source in sources)
        for column, sources in grouped.items()
    }

    def expand_helpers(
        initial: Iterable[Tuple[int, int, int, bool]],
    ) -> Tuple[Dict[int, int], bool, bool]:
        """Recursively max-union helpers while preserving phase deadlines."""
        tasks: Dict[int, int] = {}
        pending = list(initial)
        seen: set[Tuple[int, int, int, bool]] = set()
        needs_space = False
        blocked = False
        while pending:
            column, depth, helper_epoch, before_deal = pending.pop()
            item = (column, depth, helper_epoch, before_deal)
            if item in seen:
                continue
            seen.add(item)
            tasks[column] = max(tasks.get(column, 0), depth)
            closure = closures.get(column)
            if closure is None:
                continue
            _direct, helper_space, helper_blocked, _prep = _prefix_closure_metadata(
                closure,
                depth,
                target_epoch=helper_epoch,
                stock_epoch_inclusive=not before_deal,
            )
            needs_space = needs_space or helper_space
            blocked = blocked or helper_blocked
            for hop in closure.hop_closures[:depth]:
                pending.extend(
                    (child_col, child_depth, helper_epoch, before_deal)
                    for child_col, child_depth in hop.prep_tasks
                )
        return tasks, needs_space, blocked

    projects: List[CampaignExcavationProject] = []
    local_helper_sum = 0
    any_space = False
    all_raw_helpers: List[Tuple[int, int, int, bool]] = []
    for column, sources in sorted(grouped.items()):
        required_peels = direct_depth[column]
        raw_local: List[Tuple[int, int, int, bool]] = []
        for source in sources:
            (
                source_tasks,
                _source_space,
                _source_blocked,
                source_epoch,
                before_deal,
            ) = source_metadata[source.source_key]
            timed_tasks = [
                (helper_col, depth, source_epoch, before_deal)
                for helper_col, depth in source_tasks
            ]
            raw_local.extend(timed_tasks)
            all_raw_helpers.extend(timed_tasks)
        local, nested_space, nested_blocked = expand_helpers(raw_local)
        local.pop(column, None)
        local_prep = sum(local.values())
        local_helper_sum += local_prep
        needs_space = any(
            source_metadata[source.source_key][1] for source in sources
        ) or nested_space
        blocked_n = sum(
            1 for source in sources if source_metadata[source.source_key][2]
        ) + int(nested_blocked)
        any_space = any_space or needs_space
        notes = [
            "prefix-only estimate; full-column closure is not charged",
            "physical duplicate sources were substituted before this project was selected",
        ]
        closure = closures.get(column)
        if closure is not None:
            notes.append(
                f"full closure envelope cost~{closure.estimated_total_cost}; "
                f"campaign prefix~{required_peels + local_prep}"
            )
        project_deadline = min(
            (source_deadline(source) for source in sources),
            key=lambda value: (value[0], 0 if value[1] else 1),
        )
        projects.append(
            CampaignExcavationProject(
                column=column,
                required_ranks=tuple(sorted((s.card.rank for s in sources), reverse=True)),
                source_keys=tuple(sorted(s.source_key for s in sources)),
                required_peels=required_peels,
                helper_tasks=tuple(sorted(local.items())),
                deadline_epoch=project_deadline[0],
                deadline_before_deal=project_deadline[1],
                needs_temp_space=needs_space,
                blocked_dependencies=blocked_n,
                estimated_direct_cost=required_peels,
                estimated_prep_cost=local_prep,
                estimated_total_cost=required_peels + local_prep + int(needs_space),
                notes=tuple(notes),
            )
        )
    expanded_helpers, helper_space, _helper_blocked = expand_helpers(all_raw_helpers)
    any_space = any_space or helper_space
    # A helper column that is itself a selected target project is one physical
    # work footprint.  Max-union it with the direct prefix and do not publish
    # or charge it a second time as an external prerequisite.
    footprint = dict(direct_depth)
    for column, depth in expanded_helpers.items():
        footprint[column] = max(footprint.get(column, 0), depth)
    global_tasks = tuple(
        sorted(
            (column, depth)
            for column, depth in expanded_helpers.items()
            if column not in direct_depth
        )
    )
    direct_total = sum(direct_depth.values())
    naive_total = direct_total + local_helper_sum + int(any_space)
    aggregate = sum(footprint.values()) + int(any_space)
    saving = max(0, naive_total - aggregate)
    return tuple(projects), global_tasks, saving, aggregate


def _select_sources(
    catalogs: Dict[int, Tuple[RankSource, ...]],
    *,
    closures: Dict[int, ProjectClosure],
    deadline_epoch: int,
) -> Tuple[
    Tuple[CampaignRankNeed, ...],
    Tuple[CampaignExcavationProject, ...],
    Tuple[Tuple[int, int], ...],
    int,
    int,
]:
    alternatives: List[Tuple[RankSource, ...]] = []
    blocked_ranks: List[int] = []
    for rank in FOUNDATION_RANKS:
        usable = tuple(
            s
            for s in catalogs[rank]
            if s.usable_by_target and not s.reserved_by_completed_foundation
        )
        if not usable:
            blocked_ranks.append(rank)
        alternatives.append(usable)
    if blocked_ranks:
        # Preserve valid per-rank information even when the proposed target is
        # infeasible.  Reporting every rank as missing would turn one hard
        # stock gate into thirteen false blockers.
        partial_selected: List[RankSource] = []
        partial_needs: List[CampaignRankNeed] = []
        for rank, usable in zip(FOUNDATION_RANKS, alternatives):
            chosen = min(
                usable,
                key=lambda source: (
                    source.estimated_cost,
                    source.kind.value,
                    source.source_key,
                ),
            ) if usable else None
            if chosen is not None:
                partial_selected.append(chosen)
            partial_needs.append(
                CampaignRankNeed(
                    rank=rank,
                    sources=catalogs[rank],
                    chosen=chosen,
                    must_excavate=bool(chosen and chosen.is_tableau_work),
                    safe_to_wait=(),
                    reason=(
                        f"no physical copy usable by target for {rank_str(rank)}"
                        if chosen is None
                        else "provisional source; campaign target remains blocked by another rank"
                    ),
                )
            )
        projects, tasks, saving, aggregate = _merge_excavation_projects(
            partial_selected,
            closures=closures,
            deadline_epoch=deadline_epoch,
        )
        return tuple(partial_needs), projects, tasks, saving, aggregate

    # At most two physical copies per rank in standard Spider: <= 8192 plans.
    best_combo: Optional[Tuple[RankSource, ...]] = None
    best_projects: Tuple[CampaignExcavationProject, ...] = ()
    best_tasks: Tuple[Tuple[int, int], ...] = ()
    best_saving = 0
    best_aggregate = 0
    best_key: Optional[Tuple] = None
    for combo in product(*alternatives):
        projects, tasks, saving, excavation_cost = _merge_excavation_projects(
            combo, closures=closures, deadline_epoch=deadline_epoch
        )
        non_excavation = sum(
            s.estimated_cost for s in combo if not s.is_tableau_work
        )
        # A hidden copy that has a timely stock substitute should not become
        # "mandatory" merely because another rank already pays some work in
        # the same column.  Charge a small dependency-risk premium so the
        # guaranteed stock copy wins unless the tableau copy is materially
        # cheaper, not just marginally free under a shared project.
        replaceable_tableau_penalty = 0.0
        for rank, source in zip(FOUNDATION_RANKS, combo):
            if not source.is_tableau_work:
                continue
            if any(
                alt.kind == RankSourceKind.STOCK and alt.usable_by_target
                for alt in catalogs[rank]
            ):
                replaceable_tableau_penalty += 2.25
        source_groups = {
            ("tableau", source.column)
            if source.column is not None
            else ("stock", source.stock_epoch, source.stock_column)
            for source in combo
        }
        # Equal-cost duplicate choices should preserve existing spines instead
        # of scattering the selected physical copies across more columns.
        # This is a small assembly estimate, not a suit/rank preference.
        group_penalty = 0.35 * max(0, len(source_groups) - 1)
        deep = sum(1 for s in combo if s.kind == RankSourceKind.DEEP_TABLEAU)
        stock = sum(1 for s in combo if s.kind == RankSourceKind.STOCK)
        deadline_blockers = sum(project.blocked_dependencies for project in projects)
        key = (
            round(
                excavation_cost
                + non_excavation
                + replaceable_tableau_penalty
                + group_penalty
                + 25.0 * deadline_blockers,
                4,
            ),
            deep,
            len(source_groups),
            len(projects) + stock,
            tuple(s.source_key for s in combo),
        )
        if best_key is None or key < best_key:
            best_key = key
            best_combo = tuple(combo)
            best_projects = projects
            best_tasks = tasks
            best_saving = saving
            best_aggregate = excavation_cost
    assert best_combo is not None

    needs_out: List[CampaignRankNeed] = []
    for rank, chosen in zip(FOUNDATION_RANKS, best_combo):
        safe: List[RankSource] = []
        for source in catalogs[rank]:
            if source.source_key == chosen.source_key:
                continue
            if source.kind in (
                RankSourceKind.SHALLOW_TABLEAU,
                RankSourceKind.DEEP_TABLEAU,
            ) and (
                chosen.kind in (RankSourceKind.ALREADY_USABLE, RankSourceKind.STOCK)
                or source.estimated_cost >= chosen.estimated_cost
            ):
                safe.append(source)
        if chosen.is_tableau_work:
            reason = (
                f"{chosen.card} is on the target critical path; no cheaper usable "
                "copy or timely stock source was selected"
            )
        elif chosen.kind == RankSourceKind.STOCK:
            qualifier = (
                "conditional on the listed receiver/shaping requirement"
                if chosen.is_conditional
                else "snapshot reception is directly connected or extractable"
            )
            reason = (
                f"use interchangeable stock copy arriving {epoch_name(chosen.stock_epoch or 0)}; "
                f"{qualifier}, so buried alternatives need not be on the MUST path"
            )
        else:
            reason = "already usable in the tableau structure"
        needs_out.append(
            CampaignRankNeed(
                rank=rank,
                sources=catalogs[rank],
                chosen=chosen,
                must_excavate=chosen.is_tableau_work,
                safe_to_wait=tuple(safe),
                reason=reason,
            )
        )
    return (
        tuple(needs_out),
        best_projects,
        best_tasks,
        best_saving,
        best_aggregate,
    )


def _rank_bands(ranks: Iterable[int]) -> Tuple[Tuple[int, int], ...]:
    values = sorted(set(ranks), reverse=True)
    if not values:
        return ()
    bands: List[Tuple[int, int]] = []
    top = bottom = values[0]
    for rank in values[1:]:
        if bottom - 1 == rank:
            bottom = rank
        else:
            bands.append((top, bottom))
            top = bottom = rank
    bands.append((top, bottom))
    return tuple(bands)


def _format_band(suit: str, band: Tuple[int, int]) -> str:
    top, bottom = band
    if top == bottom:
        return f"{rank_str(top)}{suit}"
    return f"{rank_str(top)}{suit}-{rank_str(bottom)}{suit}"


def _stock_plan(
    ctx: _Context,
    *,
    suit: str,
    target_epoch: int,
    needs: Sequence[CampaignRankNeed],
) -> Tuple[CampaignEpochPlan, ...]:
    selected = {
        need.chosen.source_key
        for need in needs
        if need.chosen is not None
    }
    chosen_by_rank = {
        need.rank: need.chosen for need in needs if need.chosen is not None
    }
    rank_deadlines: Dict[int, int] = {}
    for rank, source in chosen_by_rank.items():
        if source is None or not source.is_tableau_work:
            continue
        child = chosen_by_rank.get(rank - 1)
        rank_deadlines[rank] = (
            min(target_epoch, child.stock_epoch)
            if child is not None and child.stock_epoch is not None
            else target_epoch
        )
    plans: List[CampaignEpochPlan] = []
    rows = stock_deal_rounds(list(ctx.state.stock))
    exact_statuses = _exact_next_row_reception(ctx.state)
    for offset, row in enumerate(rows, 1):
        epoch = ctx.current_epoch + offset
        if epoch > target_epoch:
            break
        exact = offset == 1
        incoming: List[CampaignIncomingCard] = []
        requirements: List[str] = []
        joins: List[str] = []
        selected_ranks: List[int] = []

        available_before: List[int] = []
        for rank, source in chosen_by_rank.items():
            if source is None:
                continue
            if source.kind == RankSourceKind.ALREADY_USABLE:
                available_before.append(rank)
            elif source.is_tableau_work and rank_deadlines.get(rank, target_epoch) <= epoch:
                available_before.append(rank)
            elif source.stock_epoch is not None and source.stock_epoch < epoch:
                available_before.append(rank)
        desired_bands = _rank_bands(available_before)

        same_row_parent: Dict[int, int] = {
            card.rank: col
            for col, card in enumerate(row)
            if card.suit == suit
        }
        for column, card in enumerate(row):
            if card.suit != suit:
                continue
            source_key = f"stock:{epoch}:{column}"
            is_selected = source_key in selected
            chosen_source = chosen_by_rank.get(card.rank)
            reception_status = (
                chosen_source.reception_status
                if is_selected and chosen_source is not None
                else (
                    exact_statuses.get(column, "requires_predeal_shaping")
                    if exact
                    else "prospective_known_row"
                )
            )
            if is_selected:
                selected_ranks.append(card.rank)
            landing = _landing_label(ctx.state, column, card) if exact else "prospective"
            if card.rank == 13:
                receiver = (
                    f"col {column + 1}: let incoming {card} become the final King base; "
                    "keep the campaign spine able to move onto it"
                )
            elif card.rank + 1 in same_row_parent:
                parent_col = same_row_parent[card.rank + 1]
                receiver = (
                    f"col {column + 1}: reserve a post-deal join of {card} onto incoming "
                    f"{rank_str(card.rank + 1)}{suit} on col {parent_col + 1}"
                )
                joins.append(receiver)
            elif card.rank + 1 in available_before:
                receiver = (
                    f"col {column + 1}: shape/place the available "
                    f"{rank_str(card.rank + 1)}{suit} rank or band here, or keep it exposed "
                    f"for incoming {card} to walk onto"
                )
            else:
                receiver = (
                    f"col {column + 1}: prepare/expose "
                    f"{rank_str(card.rank + 1)}{suit} as the receiver for incoming {card}"
                )
            if is_selected:
                requirements.append(receiver)
            if exact and landing == "same_suit_connect":
                joins.append(f"{card} already makes a same-suit landing on col {column + 1}")
            incoming.append(
                CampaignIncomingCard(
                    card=card,
                    column=column,
                    selected_source=is_selected,
                    receiver_requirement=receiver,
                    landing_now=landing,
                    reception_status=reception_status,
                    geometry_is_exact=exact,
                )
            )

        if offset == 1:
            carry = ctx.stock_backward.recommendation
            expected = ctx.stock_backward.post_deal_empty
        else:
            carry = (
                "prospective: carry an empty only when its incoming card has a planned "
                "walk-off; otherwise fill/use it and budget cheap recreation"
            )
            expected = None
        unlocks: List[str] = []
        if selected_ranks:
            unlocks.append(
                "campaign inventory gains "
                + ", ".join(f"{rank_str(r)}{suit}" for r in sorted(set(selected_ranks), reverse=True))
            )
        if desired_bands:
            unlocks.append(
                "shape available ranks into desired bands "
                + ", ".join(_format_band(suit, band) for band in desired_bands)
            )
        plans.append(
            CampaignEpochPlan(
                epoch=epoch,
                epoch_label=epoch_name(epoch),
                incoming=tuple(incoming),
                campaign_ranks_arriving=tuple(
                    card.rank for card in row if card.suit == suit
                ),
                selected_ranks_arriving=tuple(sorted(set(selected_ranks), reverse=True)),
                available_rank_bands_before=desired_bands,
                receiver_requirements=tuple(requirements),
                useful_same_suit_joins=tuple(joins),
                carry_empty_policy=carry,
                expected_workspace_after_deal=expected,
                unlocks=tuple(unlocks),
                geometry_is_exact=exact,
            )
        )
    return tuple(plans)


def _source_groups(needs: Sequence[CampaignRankNeed]) -> int:
    groups = set()
    for need in needs:
        source = need.chosen
        if source is None:
            continue
        if source.column is not None:
            groups.add(("tableau", source.column))
        elif source.stock_epoch is not None:
            groups.add(("stock", source.stock_epoch, source.stock_column))
    return len(groups)


def _empty_space_plan() -> CampaignSpacePlan:
    return CampaignSpacePlan(
        workspace_available_now=0,
        cheapest_recoverable_workspace=None,
        likely_temporary_uses=(),
        policy=SpacePolicy.NONE,
        enabled_action="no campaign-specific workspace action",
        enabled_project_column=None,
        enabled_ranks=(),
        action=None,
        estimated_regain_cost=None,
        next_deal_policy="n/a",
        reasons=(),
    )


def _one_move_regain_cost(state: SpiderState) -> Optional[int]:
    best: Optional[int] = None
    for profile in profile_state(state):
        if not profile.one_move_creates:
            continue
        for src, dst, k in state.enumerate_moves():
            if src != profile.column or state.columns[dst].is_empty():
                continue
            effect = simulate_move_effect(state, src, dst, k)
            if effect.effect != WorkspaceEffectKind.CREATES:
                continue
            if best is None or effect.corrected_mw_cost < best:
                best = effect.corrected_mw_cost
    return best


def _concrete_fill_then_deal(
    state: SpiderState,
) -> Optional[Tuple[Tuple[int, int, int], Optional[int]]]:
    """Replay one legal workspace-consuming fill and the exact next deal."""
    if len(state.stock) < 10:
        return None
    candidates: List[Tuple[int, int, int, int]] = []
    spaces = set(empty_columns(state))
    for src, dst, k in state.enumerate_moves():
        if dst not in spaces:
            continue
        effect = simulate_move_effect(state, src, dst, k)
        if effect.effect != WorkspaceEffectKind.CONSUMES:
            continue
        candidates.append((effect.corrected_mw_cost, src, dst, k))
    if not candidates:
        return None
    _cost, src, dst, k = min(candidates)
    post = state.clone()
    post.move(src, dst, k)
    post.deal()
    return (src, dst, k), _one_move_regain_cost(post)


def _space_plan(
    ctx: _Context,
    *,
    projects: Sequence[CampaignExcavationProject],
    stock_plan: Sequence[CampaignEpochPlan],
) -> CampaignSpacePlan:
    spaces = empty_columns(ctx.state)
    temporary: List[str] = []
    for project in projects:
        ranks = ",".join(rank_str(r) for r in project.required_ranks)
        temporary.append(
            f"peel col {project.column + 1} toward campaign rank(s) {ranks}"
        )
    if projects:
        temporary.append("park/rejoin campaign fragments while merging the K-A spine")

    next_policy = stock_plan[0].carry_empty_policy if stock_plan else "no stock before target"
    reasons: List[str] = []
    action: Optional[Tuple[int, int, int]] = None
    enabled_col: Optional[int] = None
    enabled_ranks: Tuple[int, ...] = ()
    enabled_text = "no immediate campaign-critical use found"
    policy = SpacePolicy.NONE
    regain: Optional[int] = None

    if not spaces:
        space_projects = [project for project in projects if project.needs_temp_space]
        if space_projects and ctx.liquidity.cheapest_create is not None:
            project = space_projects[0]
            policy = SpacePolicy.CREATE_THEN_SPEND
            enabled_col = project.column
            enabled_ranks = project.required_ranks
            enabled_text = (
                f"create one workspace unit at estimated cost "
                f"{ctx.liquidity.cheapest_create}, then use it to advance col "
                f"{enabled_col + 1} toward "
                + ", ".join(rank_str(r) for r in enabled_ranks)
            )
            reasons.append("a King peel explicitly requires workspace and a creation route is known")
        elif space_projects:
            enabled_col = space_projects[0].column
            enabled_ranks = space_projects[0].required_ranks
            enabled_text = (
                "workspace is required, but the bounded liquidity probe did not "
                "prove a creation route"
            )
            reasons.append("workspace prerequisite is prospective, not currently realizable")
        elif projects:
            enabled_text = (
                "advance mandatory projects through their modeled non-empty receivers; "
                "no empty is required by the selected prefixes"
            )
            reasons.append("current projects do not contain a King/no-empty dependency")
        else:
            reasons.append("campaign has no mandatory tableau project before its target")
        return CampaignSpacePlan(
            workspace_available_now=0,
            cheapest_recoverable_workspace=ctx.liquidity.cheapest_create,
            likely_temporary_uses=tuple(temporary),
            policy=policy,
            enabled_action=enabled_text,
            enabled_project_column=enabled_col,
            enabled_ranks=enabled_ranks,
            action=None,
            estimated_regain_cost=(
                ctx.liquidity.cheapest_create if space_projects else None
            ),
            next_deal_policy=next_policy,
            reasons=tuple(reasons),
        )

    # Prefer an actual legal move from a critical project into an empty.
    best: Optional[Tuple[int, int, int, int, bool]] = None
    by_column = {project.column: project for project in projects}
    for project in projects:
        src = project.column
        k = longest_movable_k(ctx.state, src)
        if k <= 0:
            continue
        for dst in spaces:
            if not ctx.state.can_move(src, dst, k):
                continue
            effect = simulate_move_effect(ctx.state, src, dst, k)
            key = (0 if effect.flipped else 1, project.estimated_total_cost, src, dst)
            candidate = (key[0] * 100 + key[1], src, dst, k, effect.flipped)
            if best is None or candidate < best:
                best = candidate
    if best is not None:
        _score, src, dst, k, flipped = best
        action = (src, dst, k)
        project = by_column[src]
        enabled_col = src
        enabled_ranks = project.required_ranks
        effect = simulate_move_effect(ctx.state, src, dst, k)
        st2 = ctx.state.clone()
        st2.move(src, dst, k)
        regain = 0 if effect.effect == WorkspaceEffectKind.RELOCATES else _one_move_regain_cost(st2)
        enabled_text = (
            f"move col {src + 1} -> empty col {dst + 1} (k={k}) to "
            f"advance the {','.join(rank_str(r) for r in project.required_ranks)} "
            f"critical prefix" + (" and flip its next card" if flipped else "")
        )
        if effect.effect == WorkspaceEffectKind.RELOCATES:
            policy = SpacePolicy.RELOCATE
            reasons.append("the legal critical move migrates rather than consumes workspace")
        else:
            policy = SpacePolicy.SPEND
            reasons.append("one empty directly advances a mandatory campaign prefix")
        reasons.append(
            f"one-move workspace regain after exact use: {regain}"
            if regain is not None
            else "no one-move workspace regain was proved after the exact use"
        )
    else:
        # If the next row would occupy an empty without a recovery, follow the
        # existing exact stock analysis; otherwise retain it for assembly.
        if ctx.stock_backward.recommendation == "fill_then_deal_then_recreate":
            fill = _concrete_fill_then_deal(ctx.state)
            if fill is not None:
                action, regain = fill
                src, dst, k = action
                policy = SpacePolicy.FILL_BEFORE_DEAL
                enabled_text = (
                    f"move col {src + 1} -> empty col {dst + 1} (k={k}), "
                    "deal the exact next row, then recreate workspace"
                )
                reasons.append(
                    f"fill-then-deal replay found one-move regain cost {regain}"
                    if regain is not None
                    else "fill-then-deal replay found no one-move regain"
                )
            else:
                policy = SpacePolicy.HOLD
                enabled_text = (
                    "hold the empty: the generic fill preference has no concrete "
                    "legal consuming action in this snapshot"
                )
                regain = None
        elif ctx.stock_backward.recommendation == "carry_empty_if_needed_recovery_exists":
            policy = SpacePolicy.CARRY_AND_RECOVER
            enabled_text = "carry the empty through the next row and use its exact walk-off"
            regain = 1
        else:
            policy = SpacePolicy.HOLD
            enabled_text = "hold the empty as a parking bay for the next campaign join"
            regain = None
        reasons.append("no legal current move from a mandatory project uses the empty")

    return CampaignSpacePlan(
        workspace_available_now=len(spaces),
        cheapest_recoverable_workspace=ctx.liquidity.cheapest_create,
        likely_temporary_uses=tuple(temporary),
        policy=policy,
        enabled_action=enabled_text,
        enabled_project_column=enabled_col,
        enabled_ranks=enabled_ranks,
        action=action,
        estimated_regain_cost=regain,
        next_deal_policy=next_policy,
        reasons=tuple(reasons),
    )


def _critical_path(
    *,
    suit: str,
    current_epoch: int,
    target_epoch: int,
    projects: Sequence[CampaignExcavationProject],
    stock_plan: Sequence[CampaignEpochPlan],
    needs: Sequence[CampaignRankNeed],
) -> Tuple[CriticalPathStep, ...]:
    steps: List[CriticalPathStep] = []
    for project in projects:
        work_epoch = (
            max(current_epoch, project.deadline_epoch - 1)
            if project.deadline_before_deal
            else max(current_epoch, project.deadline_epoch)
        )
        timing = (
            f" before {epoch_name(project.deadline_epoch)}"
            if project.deadline_before_deal
            else f" during {epoch_name(project.deadline_epoch)}"
        )
        steps.append(
            CriticalPathStep(
                epoch=min(target_epoch, work_epoch),
                phase="excavate",
                description=(
                    f"MUST expose {', '.join(rank_str(r) + suit for r in project.required_ranks)} "
                    f"from col {project.column + 1}; max-unioned prefix "
                    f"{project.required_peels} peel(s){timing}"
                ),
                ranks=project.required_ranks,
                columns=(project.column,),
            )
        )
    for epoch_plan in stock_plan:
        if epoch_plan.receiver_requirements:
            steps.append(
                CriticalPathStep(
                    epoch=max(current_epoch, epoch_plan.epoch - 1),
                    phase="shape_before_deal",
                    description="; ".join(epoch_plan.receiver_requirements),
                    ranks=epoch_plan.selected_ranks_arriving,
                    columns=tuple(
                        card.column for card in epoch_plan.incoming if card.selected_source
                    ),
                )
            )
        steps.append(
            CriticalPathStep(
                epoch=epoch_plan.epoch,
                phase="receive_stock",
                description=(
                    (
                        "deal snapshot-exact next row; "
                        if epoch_plan.geometry_is_exact
                        else "receive known future row (landing geometry prospective); "
                    )
                    + "; ".join(epoch_plan.unlocks)
                    if epoch_plan.unlocks
                    else (
                        "deal snapshot-exact next row and preserve campaign geometry"
                        if epoch_plan.geometry_is_exact
                        else "receive known future row; recompute landing geometry first"
                    )
                ),
                ranks=epoch_plan.selected_ranks_arriving,
                columns=tuple(
                    card.column for card in epoch_plan.incoming if card.selected_source
                ),
            )
        )
    all_selected = tuple(
        need.rank for need in needs if need.chosen is not None
    )
    steps.append(
        CriticalPathStep(
            epoch=target_epoch,
            phase="remove_foundation",
            description=f"join the remaining {suit.upper()} fragments into K-A and remove foundation",
            ranks=all_selected,
            columns=(),
        )
    )
    phase_order = {"excavate": 0, "shape_before_deal": 1, "receive_stock": 2, "remove_foundation": 3}
    return tuple(sorted(steps, key=lambda s: (s.epoch, phase_order.get(s.phase, 9), s.columns)))


def _confidence_and_readiness(
    *,
    blockers: Sequence[str],
    target_epoch: int,
    current_epoch: int,
    projects: Sequence[CampaignExcavationProject],
    stock_cards: Sequence[RankSource],
    assembly_moves: int,
    conditional_sources: int,
    workspace_unproved: bool,
    estimated_cost: float,
) -> Tuple[str, CampaignReadiness]:
    if blockers:
        return "LOW", CampaignReadiness.BLOCKED
    delay = target_epoch - current_epoch
    if (
        target_epoch == current_epoch
        and not projects
        and not stock_cards
        and assembly_moves == 0
    ):
        return "HIGH", CampaignReadiness.READY_NOW
    if any(p.blocked_dependencies for p in projects):
        return "LOW", CampaignReadiness.DEFERRED
    if workspace_unproved:
        return "LOW", CampaignReadiness.DEFERRED
    if delay > 3 or estimated_cost > 26:
        return "LOW", CampaignReadiness.DEFERRED
    confidence = (
        "HIGH"
        if delay <= 1
        and estimated_cost <= 16
        and conditional_sources == 0
        and assembly_moves <= 1
        else "MEDIUM"
    )
    if conditional_sources >= 3:
        confidence = "LOW"
    if projects:
        readiness = CampaignReadiness.EXCAVATION_LED
    elif stock_cards:
        readiness = CampaignReadiness.STOCK_GATED
    else:
        readiness = CampaignReadiness.ASSEMBLY_LED
    return confidence, readiness


def _evaluate_epoch(
    ctx: _Context,
    *,
    suit: str,
    copy_index: int,
    target_epoch: int,
) -> FoundationCampaign:
    candidate = _candidate_for(ctx.foundation, suit, copy_index)
    availability = ctx.foundation.availability_for(suit, copy_index)
    catalogs = _enumerate_sources(ctx, suit=suit, target_epoch=target_epoch)
    needs, projects, shared_tasks, saving, excavation_cost = _select_sources(
        catalogs, closures=ctx.closures, deadline_epoch=target_epoch
    )
    blockers: List[str] = []
    if availability.earliest_epoch is None:
        blockers.append("no theoretical complete rank set exists")
    elif target_epoch < availability.earliest_epoch:
        blockers.append(
            f"hard stock gate: not theoretically available until {epoch_name(availability.earliest_epoch)}"
        )
    missing = [need.rank for need in needs if need.chosen is None]
    if missing:
        blockers.append(
            "no usable physical source by target for "
            + ", ".join(rank_str(r) for r in missing)
        )
    deadline_blocked = [
        project for project in projects if project.blocked_dependencies
    ]
    if deadline_blocked:
        blockers.append(
            "selected tableau prefix has a destination dependency unavailable "
            "by its pre-deal receiver deadline"
        )

    critical = tuple(
        need.chosen
        for need in needs
        if need.chosen is not None and need.must_excavate
    )
    stock_cards = tuple(
        need.chosen
        for need in needs
        if need.chosen is not None and need.chosen.kind == RankSourceKind.STOCK
    )
    optional = tuple(
        source for need in needs for source in need.safe_to_wait
    )
    stock_plan = _stock_plan(
        ctx, suit=suit, target_epoch=target_epoch, needs=needs
    )

    stock_handling = sum(source.estimated_cost for source in stock_cards)
    groups = _source_groups(needs)
    assembly_moves = max(0, groups - 1)
    park_moves = assembly_moves + sum(1 for project in projects if project.needs_temp_space)
    space_requirement = 1 if any(p.needs_temp_space for p in projects) else 0
    workspace_unproved = bool(
        space_requirement
        and empty_count(ctx.state) == 0
        and ctx.liquidity.cheapest_create is None
    )
    workspace_cost = 0.0
    if (
        space_requirement
        and empty_count(ctx.state) == 0
        and ctx.liquidity.cheapest_create is not None
    ):
        workspace_cost = float(ctx.liquidity.cheapest_create)
    receiver_count = sum(len(plan.receiver_requirements) for plan in stock_plan)
    mandatory_deal_moves = max(0, target_epoch - ctx.current_epoch) * deal_cost()
    stock_join_moves = sum(
        0
        if source.reception_status
        in ("snapshot_exact_connected", "snapshot_exact_completed")
        else 1
        for source in stock_cards
    )
    estimated_cost = round(
        excavation_cost
        + stock_join_moves
        + assembly_moves
        + workspace_cost
        + mandatory_deal_moves,
        1,
    )

    fragments = candidate.same_suit_fragments
    fragment_mass = sum(fragment.length for fragment in fragments if fragment.at_pile_top)
    longest = candidate.longest_same_suit_fragment
    delay = max(0, target_epoch - ctx.current_epoch)
    structural_payoff = round(13.0 + min(6.0, fragment_mass * 0.35) + min(3.0, len(projects)), 1)
    conditional_sources = sum(
        1
        for need in needs
        if need.chosen is not None and need.chosen.is_conditional
    )
    uncertainty = float(
        sum(1 for p in projects if p.blocked_dependencies)
        + conditional_sources
        + int(workspace_unproved)
        + sum(1 for plan in stock_plan if not plan.geometry_is_exact and plan.receiver_requirements)
    )
    breakdown = CampaignScoreBreakdown(
        epoch_delay=7.0 * delay,
        excavation=3.0 * excavation_cost,
        stock_handling=1.2 * stock_handling,
        assembly_and_parking=1.1 * (assembly_moves + receiver_count),
        workspace=2.0 * workspace_cost,
        current_structure_credit=2.2 * longest + 0.8 * fragment_mass,
        stock_assistance_credit=1.4 * len(stock_cards),
        structural_payoff_credit=0.8 * structural_payoff,
        uncertainty=1.5 * uncertainty,
        total=0.0,
    )
    campaign_score = round(
        110.0
        - breakdown.epoch_delay
        - breakdown.excavation
        - breakdown.stock_handling
        - breakdown.assembly_and_parking
        - breakdown.workspace
        - breakdown.uncertainty
        + breakdown.current_structure_credit
        + breakdown.stock_assistance_credit
        + breakdown.structural_payoff_credit,
        2,
    )
    breakdown = replace(breakdown, total=campaign_score)
    readiness_score = round(
        max(
            0.0,
            min(
                100.0,
                100.0
                - 4.0 * estimated_cost
                - 5.0 * delay
                + 1.5 * longest
                + 0.5 * fragment_mass,
            ),
        ),
        1,
    )
    confidence, readiness = _confidence_and_readiness(
        blockers=blockers,
        target_epoch=target_epoch,
        current_epoch=ctx.current_epoch,
        projects=projects,
        stock_cards=stock_cards,
        assembly_moves=assembly_moves,
        conditional_sources=conditional_sources,
        workspace_unproved=workspace_unproved,
        estimated_cost=estimated_cost,
    )
    rationale: List[str] = [
        f"target {epoch_name(target_epoch)}; hard earliest {availability.earliest_epoch_name}",
        f"{len(critical)} MUST-excavate rank source(s) across {len(projects)} max-unioned project(s)",
        f"stock supplies {len(stock_cards)} selected rank(s); {len(optional)} buried "
        "duplicate(s) are off the MUST path, conditional on any listed receiver shaping",
        f"current top-fragment mass={fragment_mass}, longest={longest}",
        f"paid-move estimate includes {mandatory_deal_moves} mandatory deal move(s); "
        f"temporary park/join estimate={park_moves}",
    ]
    if conditional_sources:
        rationale.append(
            f"{conditional_sources} selected source(s) remain conditional on "
            "receiver geometry or unvalidated multi-group tableau peels"
        )
    if workspace_unproved:
        rationale.append(
            "workspace is required, but the bounded liquidity probe found no "
            "creation path; confidence is downgraded without inventing a move cost"
        )
    if saving:
        rationale.append(f"shared prerequisite union saves ~{saving} duplicate prep move(s)")
    if blockers:
        rationale.extend(blockers)
    predeal = tuple(
        requirement
        for plan in stock_plan
        for requirement in plan.receiver_requirements
    )
    critical_path = _critical_path(
        suit=suit,
        current_epoch=ctx.current_epoch,
        target_epoch=target_epoch,
        projects=projects,
        stock_plan=stock_plan,
        needs=needs,
    )
    return FoundationCampaign(
        suit=suit,
        copy_index=copy_index,
        current_epoch=ctx.current_epoch,
        earliest_theoretical_epoch=availability.earliest_epoch,
        target_removal_epoch=target_epoch,
        current_same_suit_fragments=fragments,
        required_ranks=FOUNDATION_RANKS,
        rank_needs=needs,
        tableau_critical_cards=critical,
        future_stock_supplied_cards=stock_cards,
        optional_replaceable_buried_copies=optional,
        prerequisite_excavation_projects=projects,
        shared_prerequisite_tasks=shared_tasks,
        shared_prerequisite_saving=saving,
        space_requirement=space_requirement,
        estimated_park_moves=park_moves,
        pre_deal_receiver_requirements=predeal,
        stock_plan=stock_plan,
        space_plan=_empty_space_plan(),
        critical_path=critical_path,
        estimated_campaign_cost=estimated_cost,
        expected_structural_payoff=structural_payoff,
        confidence=confidence,
        blockers=tuple(blockers),
        readiness=readiness,
        readiness_score=readiness_score,
        campaign_score=campaign_score,
        score_breakdown=breakdown,
        rationale=tuple(rationale),
    )


def _choose_schedule(
    schedules: Sequence[FoundationCampaign],
) -> FoundationCampaign:
    confidence_penalty = {"HIGH": 0.0, "MEDIUM": 2.0, "LOW": 6.0}

    def key(campaign: FoundationCampaign) -> Tuple:
        target = campaign.target_removal_epoch if campaign.target_removal_epoch is not None else 99
        blocked = 1 if campaign.blockers else 0
        objective = (
            campaign.estimated_campaign_cost
            + 6.0 * max(0, target - campaign.current_epoch)
            + confidence_penalty.get(campaign.confidence, 6.0)
        )
        return (blocked, objective, target, -campaign.campaign_score, campaign.suit)

    return min(schedules, key=key)


def _build_context(
    state: SpiderState,
    *,
    cards: Sequence[Card],
    foundation_analysis: Optional[FoundationFeasibilityAnalysis] = None,
) -> _Context:
    frozen_cards = tuple(cards)
    foundation = foundation_analysis or analyze_foundation_feasibility(frozen_cards, state)
    buried = analyze_buried_cards(state, cards=frozen_cards, foundation=foundation)
    closures = {
        closure.column: closure
        for closure in close_all_columns(state, buried=buried)
    }
    liquidity = analyze_space_liquidity(state, buried)
    stock_backward = analyze_stock_backward(state, cards=frozen_cards, buried=buried)
    return _Context(
        cards=frozen_cards,
        state=state,
        foundation=foundation,
        buried=buried,
        closures=closures,
        liquidity=liquidity,
        stock_backward=stock_backward,
        current_epoch=foundation.current_epoch,
        stock_deals_total=foundation.stock_deals_total,
    )


def analyze_foundation_campaign(
    state: SpiderState,
    *,
    cards: Sequence[Card],
    suit: str,
    copy_index: Optional[int] = None,
    target_epoch: Optional[int] = None,
    foundation_analysis: Optional[FoundationFeasibilityAnalysis] = None,
) -> FoundationCampaign:
    """Analyse one suit's next outstanding foundation campaign.

    ``target_epoch`` is useful for focused diagnostics/tests.  When omitted,
    every hard-feasible epoch is evaluated and the best transparent schedule
    is selected.  A later ordinal cannot compete unless prior ordinals of the
    suit are already completed in ``state``.
    """
    suit = suit.lower()
    if suit not in "cdhs":
        raise ValueError(f"unknown suit {suit!r}")
    ctx = _build_context(
        state, cards=cards, foundation_analysis=foundation_analysis
    )
    next_copy = _foundations_removed(state, suit) + 1
    requested = next_copy if copy_index is None else copy_index
    if requested != next_copy:
        raise ValueError(
            f"only next outstanding ordinal {suit.upper()}#{next_copy} may be analysed "
            f"from this state (requested #{requested})"
        )
    availability = ctx.foundation.availability_for(suit, requested)
    first = max(
        ctx.current_epoch,
        availability.earliest_epoch
        if availability.earliest_epoch is not None
        else ctx.stock_deals_total,
    )
    if target_epoch is not None:
        if target_epoch < ctx.current_epoch or target_epoch > ctx.stock_deals_total:
            raise ValueError("target epoch outside current deal horizon")
        campaign = _evaluate_epoch(
            ctx, suit=suit, copy_index=requested, target_epoch=target_epoch
        )
    else:
        schedules = [
            _evaluate_epoch(ctx, suit=suit, copy_index=requested, target_epoch=epoch)
            for epoch in range(first, ctx.stock_deals_total + 1)
        ]
        campaign = _choose_schedule(schedules)
    return replace(
        campaign,
        space_plan=_space_plan(
            ctx,
            projects=campaign.prerequisite_excavation_projects,
            stock_plan=campaign.stock_plan,
        ),
    )


def analyze_foundation_campaigns(
    state: SpiderState,
    *,
    cards: Sequence[Card],
    foundation_analysis: Optional[FoundationFeasibilityAnalysis] = None,
) -> FoundationCampaignPortfolio:
    """Rank each suit's next outstanding foundation as a campaign portfolio."""
    ctx = _build_context(
        state, cards=cards, foundation_analysis=foundation_analysis
    )
    campaigns: List[FoundationCampaign] = []
    for suit in "cdhs":
        copy_index = _foundations_removed(state, suit) + 1
        if copy_index > 2:
            continue
        availability = ctx.foundation.availability_for(suit, copy_index)
        first = max(
            ctx.current_epoch,
            availability.earliest_epoch
            if availability.earliest_epoch is not None
            else ctx.stock_deals_total,
        )
        schedules = [
            _evaluate_epoch(ctx, suit=suit, copy_index=copy_index, target_epoch=epoch)
            for epoch in range(first, ctx.stock_deals_total + 1)
        ]
        chosen = _choose_schedule(schedules)
        chosen = replace(
            chosen,
            space_plan=_space_plan(
                ctx,
                projects=chosen.prerequisite_excavation_projects,
                stock_plan=chosen.stock_plan,
            ),
        )
        campaigns.append(chosen)
    confidence_penalty = {"HIGH": 0.0, "MEDIUM": 2.0, "LOW": 6.0}

    def portfolio_key(campaign: FoundationCampaign) -> Tuple:
        target = (
            campaign.target_removal_epoch
            if campaign.target_removal_epoch is not None
            else 99
        )
        # The same risk-adjusted schedule objective used to choose an epoch is
        # the primary portfolio order.  This prevents a cheap but very late
        # campaign from masquerading as the likely first removal merely due
        # to a large current fragment.  The public score remains a useful
        # non-flat readiness/structure diagnostic and breaks close schedules.
        objective = (
            campaign.estimated_campaign_cost
            + 6.0 * max(0, target - campaign.current_epoch)
            + confidence_penalty.get(campaign.confidence, 6.0)
        )
        return (
            1 if campaign.blockers else 0,
            objective,
            target,
            -campaign.campaign_score,
            campaign.suit,
        )

    ranked = tuple(sorted(campaigns, key=portfolio_key))
    primary = ranked[0] if ranked else None
    secondary = ranked[1] if len(ranked) > 1 else None
    deferred = ranked[2:] if len(ranked) > 2 else ()
    notes = (
        "Only each suit's next outstanding ordinal competes; duplicate physical cards are interchangeable.",
        "Target epochs and scores are heuristic schedules; theoretical earliest epochs are hard facts.",
        "Next-row reception is exact only relative to the current snapshot; "
        "later known rows and pre-deal shaping are prospective.",
        "The secondary slot is the independent runner-up from this state, not "
        "a simulated campaign after primary removal.",
    )
    return FoundationCampaignPortfolio(
        current_epoch=ctx.current_epoch,
        campaigns=ranked,
        primary=primary,
        secondary=secondary,
        deferred=deferred,
        notes=notes,
    )


def _source_text(source: RankSource) -> str:
    if source.stock_epoch is not None:
        return (
            f"{source.card}@D{source.stock_epoch}/c{(source.stock_column or 0)+1}"
            f"[{source.reception_status}]"
        )
    if source.column is not None:
        return f"{source.card}@c{source.column+1}({source.kind.value})"
    return f"{source.card}({source.kind.value})"


def format_campaign(campaign: FoundationCampaign) -> str:
    """Render one campaign as a chronological plan, not a flat score row."""
    target = (
        epoch_name(campaign.target_removal_epoch)
        if campaign.target_removal_epoch is not None
        else "no target"
    )
    lines = [
        f"{campaign.label} CAMPAIGN — target {target}",
        f"  readiness={campaign.readiness.value} confidence={campaign.confidence} "
        f"score={campaign.campaign_score:.1f} cost~{campaign.estimated_campaign_cost:.1f}",
    ]
    for reason in campaign.rationale:
        lines.append(f"  why: {reason}")
    if campaign.tableau_critical_cards:
        lines.append(
            "  MUST excavate: "
            + ", ".join(_source_text(source) for source in campaign.tableau_critical_cards)
        )
    else:
        lines.append("  MUST excavate: none selected")
    if campaign.future_stock_supplied_cards:
        lines.append(
            "  stock supplies: "
            + ", ".join(_source_text(source) for source in campaign.future_stock_supplied_cards)
        )
    if campaign.optional_replaceable_buried_copies:
        lines.append(
            "  replaceable/off-MUST (subject to listed stock geometry): "
            + ", ".join(
                _source_text(source)
                for source in campaign.optional_replaceable_buried_copies
            )
        )
    lines.append(
        f"  space: {campaign.space_plan.policy.value} — {campaign.space_plan.enabled_action}"
    )
    for step in campaign.critical_path:
        lines.append(
            f"  [{epoch_name(step.epoch)}] {step.phase}: {step.description}"
        )
    return "\n".join(lines)


def format_campaign_portfolio(portfolio: FoundationCampaignPortfolio) -> str:
    """Human-readable primary/secondary/deferred plan of attack."""
    lines = [
        f"FOUNDATION CAMPAIGN PORTFOLIO ({epoch_name(portfolio.current_epoch)})",
        "=" * 72,
    ]
    if portfolio.primary is None:
        lines.append("No incomplete campaign found.")
        return "\n".join(lines)
    lines.extend(["", "PRIMARY CAMPAIGN", format_campaign(portfolio.primary)])
    if portfolio.secondary is not None:
        lines.extend(
            [
                "",
                "INDEPENDENT RUNNER-UP (SECONDARY SLOT)",
                format_campaign(portfolio.secondary),
            ]
        )
    if portfolio.deferred:
        lines.extend(["", "DEFERRED CAMPAIGNS"])
        for campaign in portfolio.deferred:
            lines.append(
                f"  {campaign.label}: target "
                f"{epoch_name(campaign.target_removal_epoch or campaign.current_epoch)}, "
                f"score={campaign.campaign_score:.1f}, cost~{campaign.estimated_campaign_cost:.1f}; "
                + campaign.rationale[1]
            )
    return "\n".join(lines)
