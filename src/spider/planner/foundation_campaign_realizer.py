"""Bounded realisation of one foundation campaign through its next stock row.

This is a tactical bridge between :mod:`foundation_campaign` and the existing
objective realizer.  It deliberately stops after one deal, keeps the selected
suit/copy/target epoch fixed, and reanalyses after every realized fragment so
interchangeable physical copies may replace the originally selected source.

Campaign estimates and receiver preferences order work only.  They are never
used to prove that a route is impossible.  Every returned route is replayed
with the engine and corrected MobilityWare accounting.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.planner.excavation_closure import close_column
from spider.planner.foundation_campaign import (
    FoundationCampaign,
    RankSource,
    RankSourceKind,
    SpacePolicy,
    analyze_foundation_campaign,
)
from spider.planner.foundation_feasibility import current_stock_epoch
from spider.planner.objective_realizer import (
    RealizationMode,
    RealizationStatus,
    realize_objective,
)
from spider.planner.space_lifecycle import empty_columns
from spider.planner.stock_reception import next_stock_row
from spider.planner.strategic_objectives import (
    ObjectiveKind,
    PriorityComponents,
    StrategicObjective,
)
from spider.planner.workspace_tactics import WorkspaceBackend, realize_workspace


class CampaignObligationKind(str, Enum):
    EXCAVATE_PREFIX = "excavate_prefix"
    MAKE_RANK_USABLE = "make_rank_usable"
    PRESERVE_FRAGMENT = "preserve_fragment"
    SHAPE_RECEIVER = "shape_receiver"
    PREPARE_WORKSPACE = "prepare_workspace"
    APPLY_DEAL = "apply_deal"
    VERIFY_POST_DEAL = "verify_post_deal"


class CampaignRealizationStatus(str, Enum):
    FOUND = "found"
    PARTIAL = "partial"
    NOT_FOUND_WITHIN_BOUND = "not_found_within_bound"
    RESOURCE_LIMIT = "resource_limit"
    INVALID_CAMPAIGN = "invalid_campaign"


@dataclass(frozen=True)
class CampaignIdentity:
    suit: str
    copy_index: int
    target_epoch: int

    @property
    def label(self) -> str:
        return f"{self.suit.upper()}#{self.copy_index}@D{self.target_epoch}"


@dataclass(frozen=True)
class PrefixDestinationPrerequisite:
    peel_card: Card
    required_rank: Optional[int]
    hard_ready: bool
    future_stock: bool
    blocked: bool


@dataclass(frozen=True)
class TargetPrefixClosure:
    """Target-relative public view of the prefix that exposes one rank."""

    source_column: Optional[int]
    selected_source_key: Optional[str]
    interchangeable_source_keys: Tuple[str, ...]
    target_rank: int
    required_peels: int
    required_reveals: int
    max_face_down: Optional[int]
    destination_prerequisites: Tuple[PrefixDestinationPrerequisite, ...]
    helper_tasks: Tuple[Tuple[int, int], ...]
    requires_temp_workspace: bool
    already_satisfied: bool
    notes: Tuple[str, ...]


@dataclass(frozen=True)
class CampaignObligation:
    obligation_id: str
    kind: CampaignObligationKind
    description: str
    mandatory_before_deal: bool
    deadline_epoch: int
    rank: Optional[int] = None
    source_column: Optional[int] = None
    source_keys: Tuple[str, ...] = ()
    required_reveals: int = 0
    max_face_down: Optional[int] = None
    receiver_column: Optional[int] = None
    incoming_card: Optional[Card] = None
    receiver_rank: Optional[int] = None
    fragment: Tuple[Card, ...] = ()
    notes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class CampaignProgress:
    phase: str
    action_count: int
    corrected_added_cost: int
    epoch: int
    satisfied: Tuple[str, ...]
    remaining: Tuple[str, ...]
    must_source_keys: Tuple[str, ...]
    receiver_conditions_satisfied: Tuple[str, ...]
    empty_columns: Tuple[int, ...]
    note: str


@dataclass(frozen=True)
class CampaignRealizationResult:
    status: CampaignRealizationStatus
    identity: CampaignIdentity
    start_epoch: int
    target_epoch: int
    actions: Tuple[Action, ...]
    action_roles: Tuple[str, ...]
    corrected_added_cost: Optional[int]
    resulting_state: SpiderState
    obligations_initial: Tuple[CampaignObligation, ...]
    obligations_satisfied: Tuple[CampaignObligation, ...]
    obligations_remaining: Tuple[CampaignObligation, ...]
    receiver_conditions_satisfied: Tuple[str, ...]
    receiver_conditions_remaining: Tuple[str, ...]
    workspace_events: Tuple[str, ...]
    must_sources_before: Tuple[str, ...]
    must_sources_after: Tuple[str, ...]
    campaign_before: FoundationCampaign
    campaign_after: Optional[FoundationCampaign]
    progress: Tuple[CampaignProgress, ...]
    nodes_expanded: int
    elapsed_seconds: float
    stop_reason: str
    independent_replay_verified: bool
    replayed_cost: Optional[int]
    exact_row: Tuple[Card, ...]


def _identity(campaign: FoundationCampaign) -> CampaignIdentity:
    if campaign.target_removal_epoch is None:
        raise ValueError("campaign has no target removal epoch")
    return CampaignIdentity(
        campaign.suit, campaign.copy_index, campaign.target_removal_epoch
    )


def _must_keys(campaign: Optional[FoundationCampaign]) -> Tuple[str, ...]:
    if campaign is None:
        return ()
    return tuple(source.source_key for source in campaign.tableau_critical_cards)


def _usable_rank(state: SpiderState, suit: str, rank: int) -> bool:
    """Whether a rank is in a movable same-suit suffix of a tableau column."""
    for column in state.columns:
        up = column.face_up
        if not up:
            continue
        first = len(up) - 1
        while (
            first > 0
            and up[first - 1].suit == up[first].suit
            and up[first - 1].rank - 1 == up[first].rank
        ):
            first -= 1
        if any(card.suit == suit and card.rank == rank for card in up[first:]):
            return True
    return False


def _fragment_present(state: SpiderState, fragment: Sequence[Card]) -> bool:
    if not fragment:
        return True
    target = tuple(fragment)
    n = len(target)
    for column in state.columns:
        up = column.face_up
        for i in range(len(up) - n + 1):
            if tuple(up[i : i + n]) == target:
                return True
    return False


def _selected_source(campaign: FoundationCampaign, rank: int) -> Optional[RankSource]:
    return campaign.rank_need(rank).chosen


def campaign_target_prefix_closure(
    state: SpiderState,
    campaign: FoundationCampaign,
    rank: int,
) -> TargetPrefixClosure:
    """Describe only the tableau prefix needed to make ``rank`` usable.

    All interchangeable tableau sources from the campaign rank need are
    exposed in the result.  Dependency facts come from the existing public
    excavation closure, capped at the selected source's prefix rather than
    priced as a full-column evacuation.
    """
    need = campaign.rank_need(rank)
    selected = need.chosen
    tableau = tuple(
        source
        for source in need.sources
        if source.kind
        in (
            RankSourceKind.ALREADY_USABLE,
            RankSourceKind.SHALLOW_TABLEAU,
            RankSourceKind.DEEP_TABLEAU,
        )
    )
    already = _usable_rank(state, campaign.suit, rank)
    if already or selected is None or selected.column is None:
        return TargetPrefixClosure(
            source_column=selected.column if selected else None,
            selected_source_key=selected.source_key if selected else None,
            interchangeable_source_keys=tuple(s.source_key for s in tableau),
            target_rank=rank,
            required_peels=0,
            required_reveals=0,
            max_face_down=None,
            destination_prerequisites=(),
            helper_tasks=(),
            requires_temp_workspace=False,
            already_satisfied=already,
            notes=("rank already belongs to a movable same-suit suffix",)
            if already
            else ("selected source is not a tableau excavation source",),
        )

    column = selected.column
    pile = state.columns[column]
    required_reveals = (
        selected.depth + 1 if selected.tableau_zone == "face_down" else 0
    )
    max_face_down = (
        max(0, len(pile.face_down) - required_reveals)
        if required_reveals
        else len(pile.face_down)
    )
    prefix_hops = max(selected.closure_prefix_hops, required_reveals)
    closure = close_column(state, column)
    hop_closures = closure.hop_closures[:prefix_hops]
    prerequisites = tuple(
        PrefixDestinationPrerequisite(
            peel_card=hop.hop.card,
            required_rank=hop.hop.need_rank,
            hard_ready=hop.hard_ready,
            future_stock=hop.future_stock,
            blocked=hop.blocked,
        )
        for hop in hop_closures
    )
    helpers: Dict[int, int] = {}
    for hop in hop_closures:
        for helper_column, depth in hop.prep_tasks:
            helpers[helper_column] = max(helpers.get(helper_column, 0), depth)
    return TargetPrefixClosure(
        source_column=column,
        selected_source_key=selected.source_key,
        interchangeable_source_keys=tuple(s.source_key for s in tableau),
        target_rank=rank,
        required_peels=max(selected.excavation_peels, len(hop_closures)),
        required_reveals=required_reveals,
        max_face_down=max_face_down,
        destination_prerequisites=prerequisites,
        helper_tasks=tuple(sorted(helpers.items())),
        requires_temp_workspace=any(hop.needs_space for hop in hop_closures),
        already_satisfied=False,
        notes=(
            f"target-relative prefix uses {len(hop_closures)} of "
            f"{len(closure.hop_closures)} full-column hops",
        ),
    )


def campaign_obligations_for_next_epoch(
    state: SpiderState,
    campaign: FoundationCampaign,
    cards: Sequence[Card],
) -> Tuple[CampaignObligation, ...]:
    """Derive machine-testable work through the campaign's next stock row."""
    del cards  # inventory is already embodied by the frozen campaign
    next_epoch = campaign.current_epoch + 1
    if (
        campaign.target_removal_epoch is None
        or next_epoch > campaign.target_removal_epoch
        or len(state.stock) < 10
    ):
        return ()

    out: List[CampaignObligation] = []
    for project in campaign.prerequisite_excavation_projects:
        if not project.deadline_before_deal or project.deadline_epoch > next_epoch:
            continue
        for rank in project.required_ranks:
            prefix = campaign_target_prefix_closure(state, campaign, rank)
            source_keys = prefix.interchangeable_source_keys
            out.append(
                CampaignObligation(
                    obligation_id=f"excavate:r{rank}:d{next_epoch}",
                    kind=CampaignObligationKind.EXCAVATE_PREFIX,
                    description=(
                        f"expose a usable {rank}{campaign.suit} source via the "
                        f"target-relative prefix on column "
                        f"{(prefix.source_column + 1) if prefix.source_column is not None else '?'}"
                    ),
                    mandatory_before_deal=True,
                    deadline_epoch=next_epoch,
                    rank=rank,
                    source_column=prefix.source_column,
                    source_keys=source_keys,
                    required_reveals=prefix.required_reveals,
                    max_face_down=prefix.max_face_down,
                    notes=prefix.notes,
                )
            )
            out.append(
                CampaignObligation(
                    obligation_id=f"usable:r{rank}:d{next_epoch}",
                    kind=CampaignObligationKind.MAKE_RANK_USABLE,
                    description=f"make an interchangeable rank {rank} source usable",
                    mandatory_before_deal=True,
                    deadline_epoch=next_epoch,
                    rank=rank,
                    source_column=prefix.source_column,
                    source_keys=source_keys,
                )
            )

    # Preserve every currently top, non-trivial selected-suit fragment.
    seen_fragments = set()
    for fragment_fact in campaign.current_same_suit_fragments:
        fragment = tuple(
            Card(campaign.suit, rank)
            for rank in range(
                fragment_fact.top_rank, fragment_fact.bottom_rank - 1, -1
            )
        )
        if not fragment_fact.at_pile_top or len(fragment) < 2 or fragment in seen_fragments:
            continue
        seen_fragments.add(fragment)
        ranks = f"{fragment[0].rank}-{fragment[-1].rank}"
        out.append(
            CampaignObligation(
                obligation_id=f"preserve:{ranks}:{campaign.suit}",
                kind=CampaignObligationKind.PRESERVE_FRAGMENT,
                description=f"preserve same-suit fragment {ranks}{campaign.suit}",
                mandatory_before_deal=True,
                deadline_epoch=next_epoch,
                fragment=fragment,
            )
        )

    epoch_plan = next(
        (plan for plan in campaign.stock_plan if plan.epoch == next_epoch), None
    )
    if epoch_plan is not None:
        selected_incoming = [item for item in epoch_plan.incoming if item.selected_source]
        incoming_ranks = {
            item.card.rank for item in selected_incoming if item.card.suit == campaign.suit
        }
        for item in selected_incoming:
            receiver_rank = item.card.rank + 1 if item.card.rank < 13 else None
            notes = [item.receiver_requirement, item.reception_status]
            if receiver_rank in incoming_ranks:
                notes.append("same-suit parent arrives in the same exact row")
            out.append(
                CampaignObligation(
                    obligation_id=(
                        f"receiver:{item.card.suit}{item.card.rank}:"
                        f"c{item.column}:d{next_epoch}"
                    ),
                    kind=CampaignObligationKind.SHAPE_RECEIVER,
                    description=item.receiver_requirement,
                    mandatory_before_deal=False,
                    deadline_epoch=next_epoch,
                    rank=item.card.rank,
                    receiver_column=item.column,
                    incoming_card=item.card,
                    receiver_rank=receiver_rank,
                    notes=tuple(notes),
                )
            )

    if campaign.space_plan.policy not in (SpacePolicy.NONE, SpacePolicy.HOLD):
        out.append(
            CampaignObligation(
                obligation_id=f"workspace:d{next_epoch}",
                kind=CampaignObligationKind.PREPARE_WORKSPACE,
                description=campaign.space_plan.enabled_action,
                mandatory_before_deal=False,
                deadline_epoch=next_epoch,
                notes=campaign.space_plan.reasons,
            )
        )

    out.extend(
        (
            CampaignObligation(
                obligation_id=f"deal:d{next_epoch}",
                kind=CampaignObligationKind.APPLY_DEAL,
                description=f"apply the exact known stock row for epoch {next_epoch}",
                mandatory_before_deal=False,
                deadline_epoch=next_epoch,
            ),
            CampaignObligation(
                obligation_id=f"verify:{campaign.suit}{campaign.copy_index}:d{next_epoch}",
                kind=CampaignObligationKind.VERIFY_POST_DEAL,
                description="reanalyze the fixed campaign identity after the deal",
                mandatory_before_deal=False,
                deadline_epoch=next_epoch,
            ),
        )
    )
    return tuple(out)


def obligation_is_satisfied(
    state: SpiderState,
    campaign: FoundationCampaign,
    obligation: CampaignObligation,
    *,
    accomplished: Sequence[str] = (),
) -> bool:
    """Public machine predicate for one campaign obligation."""
    if obligation.obligation_id in accomplished:
        return True
    if obligation.kind in (
        CampaignObligationKind.EXCAVATE_PREFIX,
        CampaignObligationKind.MAKE_RANK_USABLE,
    ):
        return obligation.rank is not None and _usable_rank(
            state, campaign.suit, obligation.rank
        )
    if obligation.kind == CampaignObligationKind.PRESERVE_FRAGMENT:
        return _fragment_present(state, obligation.fragment)
    if obligation.kind == CampaignObligationKind.SHAPE_RECEIVER:
        card = obligation.incoming_card
        receiver_rank = obligation.receiver_rank
        if card is None or receiver_rank is None:
            return True
        column = obligation.receiver_column
        if column is not None:
            top = state.columns[column].top()
            if top is not None and top.suit == card.suit and top.rank == receiver_rank:
                return True
        # A known same-suit walk-off receiver elsewhere is also useful.
        if _usable_rank(state, card.suit, receiver_rank):
            return True
        # Or the parent arrives earlier/in the same exact row.
        row = next_stock_row(state)
        return bool(
            row
            and any(
                incoming.suit == card.suit and incoming.rank == receiver_rank
                for incoming in row
            )
        )
    if obligation.kind == CampaignObligationKind.PREPARE_WORKSPACE:
        if empty_columns(state):
            return True
        return campaign.space_plan.estimated_regain_cost is not None
    if obligation.kind in (
        CampaignObligationKind.APPLY_DEAL,
        CampaignObligationKind.VERIFY_POST_DEAL,
    ):
        return current_stock_epoch(state, 5) >= obligation.deadline_epoch
    return False


def _objective_for_prefix(
    obligation: CampaignObligation,
) -> Optional[StrategicObjective]:
    if obligation.source_column is None or obligation.max_face_down is None:
        return None
    return StrategicObjective(
        kind=ObjectiveKind.EXPOSE_REVEAL_PREFIX,
        objective_id=obligation.obligation_id,
        description=obligation.description,
        target_key="column_face_down_le",
        target_params={
            "column": obligation.source_column,
            "max_face_down": obligation.max_face_down,
            "required_reveals": obligation.required_reveals,
        },
        hard_preconditions=("selected campaign prefix remains in this column",),
        hard_evidence=obligation.notes,
        admissible_lb=obligation.required_reveals,
        admissible_breakdown=None,
        heuristic_est_cost=float(max(1, obligation.required_reveals + 2)),
        heuristic_est_benefit=8.0,
        priority=PriorityComponents(foundation=8.0, reveal=8.0, urgency=10.0),
        foundation_relevance="campaign MUST prefix",
        workspace_relevance="temporary destinations allowed",
        stock_relevance="due before next exact row",
        explanation="target-relative campaign excavation",
    )


def _classify_action(
    before: SpiderState,
    action: Action,
    critical_columns: Sequence[int],
    receiver_columns: Sequence[int],
) -> str:
    if action == ("deal",):
        return "deal"
    src, dst, _k = action
    if src in critical_columns:
        return "campaign-critical"
    if dst in receiver_columns:
        return "receiver-prep"
    if before.columns[dst].is_empty() or before.columns[src].is_empty():
        return "workspace"
    return "auxiliary"


def _apply_verified_fragment(
    state: SpiderState, actions: Sequence[Action]
) -> Tuple[SpiderState, int]:
    checked = state.clone()
    cost = replay_actions(checked, list(actions))
    return checked, cost


def _reanalyze_fixed(
    state: SpiderState,
    identity: CampaignIdentity,
    cards: Sequence[Card],
) -> FoundationCampaign:
    return analyze_foundation_campaign(
        state,
        cards=cards,
        suit=identity.suit,
        copy_index=identity.copy_index,
        target_epoch=identity.target_epoch,
    )


def realize_campaign_to_next_epoch(
    start_state: SpiderState,
    campaign: FoundationCampaign,
    cards: Sequence[Card],
    *,
    max_added_cost: int = 14,
    max_nodes: int = 50_000,
    time_limit_s: float = 30.0,
) -> CampaignRealizationResult:
    """Realize mandatory work and apply exactly one stock row.

    Tactical search is hierarchical: each mandatory prefix is sent to the
    existing exact bounded objective realizer, replayed independently, and the
    fixed campaign is then reanalysed before the hierarchy continues.
    """
    started = time.perf_counter()
    try:
        identity = _identity(campaign)
    except ValueError:
        identity = CampaignIdentity(campaign.suit, campaign.copy_index, -1)
        return CampaignRealizationResult(
            CampaignRealizationStatus.INVALID_CAMPAIGN,
            identity,
            campaign.current_epoch,
            -1,
            (),
            (),
            None,
            start_state.clone(),
            (),
            (),
            (),
            (),
            (),
            (),
            _must_keys(campaign),
            (),
            campaign,
            None,
            (),
            0,
            time.perf_counter() - started,
            "campaign has no target removal epoch",
            False,
            None,
            (),
        )

    start_epoch = current_stock_epoch(start_state, 5)
    next_epoch = start_epoch + 1
    if (
        campaign.suit != identity.suit
        or campaign.copy_index != identity.copy_index
        or campaign.current_epoch != start_epoch
        or identity.target_epoch < next_epoch
        or len(start_state.stock) < 10
    ):
        return CampaignRealizationResult(
            CampaignRealizationStatus.INVALID_CAMPAIGN,
            identity,
            start_epoch,
            next_epoch,
            (),
            (),
            None,
            start_state.clone(),
            (),
            (),
            (),
            (),
            (),
            (),
            _must_keys(campaign),
            (),
            campaign,
            None,
            (),
            0,
            time.perf_counter() - started,
            "campaign identity/epoch is incompatible with the start state",
            False,
            None,
            (),
        )

    obligations = campaign_obligations_for_next_epoch(start_state, campaign, cards)
    state = start_state.clone()
    current = campaign
    actions: List[Action] = []
    roles: List[str] = []
    workspace_events: List[str] = []
    accomplished: List[str] = []
    receiver_accomplished: List[str] = []
    progress: List[CampaignProgress] = []
    total_cost = 0
    nodes = 0
    resource_limited = False
    stop_reason = ""

    def snapshot(phase: str, note: str) -> None:
        satisfied = tuple(
            o.obligation_id
            for o in obligations
            if obligation_is_satisfied(state, current, o, accomplished=accomplished)
        )
        remaining = tuple(o.obligation_id for o in obligations if o.obligation_id not in satisfied)
        progress.append(
            CampaignProgress(
                phase=phase,
                action_count=len(actions),
                corrected_added_cost=total_cost,
                epoch=current_stock_epoch(state, 5),
                satisfied=satisfied,
                remaining=remaining,
                must_source_keys=_must_keys(current),
                receiver_conditions_satisfied=tuple(receiver_accomplished),
                empty_columns=tuple(empty_columns(state)),
                note=note,
            )
        )

    snapshot("initial", "frozen campaign obligations generated")

    # Mandatory excavation only. MAKE_RANK_USABLE is verified by reanalysis
    # after the paired prefix objective; fragments are preservation guards.
    for obligation in obligations:
        if obligation.kind != CampaignObligationKind.EXCAVATE_PREFIX:
            continue
        if obligation_is_satisfied(state, current, obligation, accomplished=accomplished):
            accomplished.append(obligation.obligation_id)
            continue
        remaining_cost = max_added_cost - total_cost - 1  # reserve exact deal cost
        remaining_time = time_limit_s - (time.perf_counter() - started)
        if remaining_cost < 0 or remaining_time <= 0:
            resource_limited = remaining_time <= 0
            stop_reason = "no bounded resource remains for mandatory prefix plus deal"
            break
        objective = _objective_for_prefix(obligation)
        if objective is None:
            stop_reason = "mandatory prefix has no concrete tableau target"
            break
        result = realize_objective(
            state,
            objective,
            mode=RealizationMode.EXACT_BOUNDED,
            max_cost=remaining_cost,
            max_nodes=max(1, max_nodes - nodes),
            time_limit_s=max(0.01, remaining_time),
        )
        nodes += result.nodes_expanded
        if result.status != RealizationStatus.FOUND:
            resource_limited = result.status == RealizationStatus.RESOURCE_LIMIT
            stop_reason = "; ".join(result.notes)
            break
        before_fragment = state
        checked, fragment_cost = _apply_verified_fragment(state, result.actions)
        if fragment_cost != result.corrected_mw_cost or not objective.is_satisfied(checked):
            stop_reason = "tactical fragment failed independent replay verification"
            break
        critical_columns = tuple(
            o.source_column
            for o in obligations
            if o.kind == CampaignObligationKind.EXCAVATE_PREFIX
            and o.source_column is not None
        )
        receiver_columns = tuple(
            o.receiver_column
            for o in obligations
            if o.kind == CampaignObligationKind.SHAPE_RECEIVER
            and o.receiver_column is not None
        )
        cursor = before_fragment.clone()
        for action in result.actions:
            before_empty = tuple(empty_columns(cursor))
            roles.append(_classify_action(cursor, action, critical_columns, receiver_columns))
            replay_actions(cursor, [action])
            after_empty = tuple(empty_columns(cursor))
            if before_empty != after_empty:
                workspace_events.append(
                    f"action {len(actions) + 1}: empties {before_empty} -> {after_empty}"
                )
            actions.append(action)
        state = checked
        total_cost += fragment_cost
        accomplished.append(obligation.obligation_id)
        try:
            current = _reanalyze_fixed(state, identity, cards)
        except ValueError as exc:
            stop_reason = f"fixed campaign failed reanalysis: {exc}"
            break
        snapshot("excavation", f"realized {obligation.obligation_id}")

    mandatory_remaining = [
        obligation
        for obligation in obligations
        if obligation.mandatory_before_deal
        and not obligation_is_satisfied(
            state, current, obligation, accomplished=accomplished
        )
    ]

    # If the selected campaign explicitly treats an empty as working capital,
    # recreate it after the critical prefix when the bounded workspace backend
    # can do so without breaking a mandatory guard.  This is optional shaping,
    # never a proof gate.
    workspace_obligation = next(
        (
            obligation
            for obligation in obligations
            if obligation.kind == CampaignObligationKind.PREPARE_WORKSPACE
        ),
        None,
    )
    if (
        not mandatory_remaining
        and workspace_obligation is not None
        and not empty_columns(state)
        and total_cost + 1 < max_added_cost
    ):
        remaining_time = time_limit_s - (time.perf_counter() - started)
        workspace_result = realize_workspace(
            state,
            backend=WorkspaceBackend.IMPROVED,
            max_cost=max_added_cost - total_cost - 1,
            max_nodes=max(1, max_nodes - nodes),
            time_limit_s=max(0.01, remaining_time),
        )
        nodes += workspace_result.nodes_expanded
        if workspace_result.status == RealizationStatus.FOUND:
            checked, fragment_cost = _apply_verified_fragment(
                state, workspace_result.actions
            )
            try:
                checked_campaign = _reanalyze_fixed(checked, identity, cards)
            except ValueError:
                checked_campaign = None
            guards_hold = checked_campaign is not None and all(
                obligation_is_satisfied(checked, checked_campaign, obligation)
                for obligation in obligations
                if obligation.mandatory_before_deal
            )
            if (
                guards_hold
                and fragment_cost == workspace_result.corrected_mw_cost
                and empty_columns(checked)
            ):
                cursor = state.clone()
                for action in workspace_result.actions:
                    before_empty = tuple(empty_columns(cursor))
                    replay_actions(cursor, [action])
                    after_empty = tuple(empty_columns(cursor))
                    roles.append("workspace")
                    actions.append(action)
                    if before_empty != after_empty:
                        workspace_events.append(
                            f"action {len(actions)}: empties {before_empty} -> {after_empty}"
                        )
                state = checked
                current = checked_campaign
                total_cost += fragment_cost
                accomplished.append(workspace_obligation.obligation_id)
                snapshot(
                    "workspace",
                    f"recreated workspace with corrected cost {fragment_cost}",
                )

    mandatory_remaining = [
        obligation
        for obligation in obligations
        if obligation.mandatory_before_deal
        and not obligation_is_satisfied(
            state, current, obligation, accomplished=accomplished
        )
    ]

    # Freeze practical receiver achievements before the stock row changes the
    # predicate's context.  Receiver obligations are best-effort, not gates.
    if not mandatory_remaining:
        for obligation in obligations:
            if obligation.kind != CampaignObligationKind.SHAPE_RECEIVER:
                continue
            if obligation_is_satisfied(state, current, obligation):
                receiver_accomplished.append(obligation.obligation_id)
                accomplished.append(obligation.obligation_id)
        snapshot("pre_deal", "mandatory work verified; receiver geometry frozen")

    exact_row = tuple(next_stock_row(state) or ())
    if not mandatory_remaining and total_cost + 1 <= max_added_cost:
        before_deal = state.clone()
        try:
            dealt, deal_paid = _apply_verified_fragment(state, (("deal",),))
        except (ValueError, IndexError) as exc:
            stop_reason = f"engine rejected exact deal: {exc}"
        else:
            if deal_paid != 1 or len(exact_row) != 10:
                stop_reason = "deal replay or exact-row verification failed"
            else:
                # Each exact row card must be appended to its receiver column.
                row_verified = all(
                    len(dealt.columns[column].face_up)
                    >= len(before_deal.columns[column].face_up) + 1
                    and dealt.columns[column].face_up[
                        len(before_deal.columns[column].face_up)
                    ]
                    == card
                    for column, card in enumerate(exact_row)
                )
                if not row_verified:
                    stop_reason = "exact incoming cards did not map to engine columns"
                else:
                    state = dealt
                    actions.append(("deal",))
                    roles.append("deal")
                    total_cost += deal_paid
                    accomplished.append(f"deal:d{next_epoch}")
                    try:
                        current = _reanalyze_fixed(state, identity, cards)
                    except ValueError as exc:
                        stop_reason = f"post-deal fixed campaign failed reanalysis: {exc}"
                    else:
                        accomplished.append(
                            f"verify:{identity.suit}{identity.copy_index}:d{next_epoch}"
                        )
                        snapshot("post_deal", "exact row applied and fixed campaign reanalysed")
    elif not stop_reason:
        stop_reason = (
            "mandatory pre-deal obligations remain"
            if mandatory_remaining
            else "added-cost bound leaves no room for the exact deal"
        )

    replayed = start_state.clone()
    replay_ok = False
    replayed_cost: Optional[int] = None
    try:
        replayed_cost = replay_actions(replayed, list(actions))
        replay_ok = replayed_cost == total_cost
    except ValueError:
        replay_ok = False

    reached_epoch = current_stock_epoch(state, 5) == next_epoch
    if reached_epoch and replay_ok and not stop_reason:
        status = CampaignRealizationStatus.FOUND
        stop_reason = "mandatory obligations satisfied; exact next row verified"
    elif resource_limited:
        status = CampaignRealizationStatus.RESOURCE_LIMIT
    elif actions and any(
        o.kind == CampaignObligationKind.EXCAVATE_PREFIX
        and obligation_is_satisfied(state, current, o, accomplished=accomplished)
        for o in obligations
    ):
        status = CampaignRealizationStatus.PARTIAL
    else:
        status = CampaignRealizationStatus.NOT_FOUND_WITHIN_BOUND

    satisfied = tuple(
        obligation
        for obligation in obligations
        if obligation_is_satisfied(state, current, obligation, accomplished=accomplished)
    )
    remaining = tuple(o for o in obligations if o not in satisfied)
    receiver_all = tuple(
        o.obligation_id
        for o in obligations
        if o.kind == CampaignObligationKind.SHAPE_RECEIVER
    )
    receiver_done = tuple(dict.fromkeys(receiver_accomplished))
    return CampaignRealizationResult(
        status=status,
        identity=identity,
        start_epoch=start_epoch,
        target_epoch=next_epoch,
        actions=tuple(actions),
        action_roles=tuple(roles),
        corrected_added_cost=total_cost if replay_ok else None,
        resulting_state=state.clone(),
        obligations_initial=obligations,
        obligations_satisfied=satisfied,
        obligations_remaining=remaining,
        receiver_conditions_satisfied=receiver_done,
        receiver_conditions_remaining=tuple(
            item for item in receiver_all if item not in receiver_done
        ),
        workspace_events=tuple(workspace_events),
        must_sources_before=_must_keys(campaign),
        must_sources_after=_must_keys(current) if reached_epoch else _must_keys(current),
        campaign_before=campaign,
        campaign_after=current if reached_epoch else None,
        progress=tuple(progress),
        nodes_expanded=nodes,
        elapsed_seconds=time.perf_counter() - started,
        stop_reason=stop_reason,
        independent_replay_verified=replay_ok,
        replayed_cost=replayed_cost,
        exact_row=exact_row,
    )


def format_obligation(obligation: CampaignObligation) -> str:
    gate = "MUST" if obligation.mandatory_before_deal else "DESIRED"
    return (
        f"{gate:<7} {obligation.kind.value:<20} "
        f"{obligation.obligation_id}: {obligation.description}"
    )
