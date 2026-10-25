"""Deal-time preparation comparison.

Called only when the controller is about to deal or to chase an unrealised
workspace stretch. It does not rank ordinary one-ply moves.

The comparison uses the authoritative engine on cloned states. Heuristic
nets order the alternatives. They are not admissible bounds and they do not
prune.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from spider.cards import rank_str
from spider.engine import SpiderState
from spider.metrics import Action
from spider.planner.lower_bounds import compute_objective_lower_bound
from spider.planner.objective_realizer import RealizationMode, RealizationStatus, realize_objective
from spider.planner.space_lifecycle import empty_count
from spider.planner.stock_reception import (
    PreDealShapingObjective,
    next_stock_row,
    run_bounded_shaping_probe,
)
from spider.planner.strategic_objectives import (
    ObjectiveKind,
    PriorityComponents,
    StrategicObjective,
)
from spider.research_actions import all_legal_actions, apply_action, face_down_count

from .evaluation import same_suit_bonds
from .profiles import Profile


_PREP_KINDS = {
    ObjectiveKind.EXPOSE_REVEAL_PREFIX,
    ObjectiveKind.CONSOLIDATE_SAME_SUIT,
    ObjectiveKind.ADVANCE_FOUNDATION,
    ObjectiveKind.REMOVE_FOUNDATION,
}


@dataclass(frozen=True)
class PreparationOption:
    """One replayed preparation, measured before the following deal."""

    objective_id: str
    actions: Tuple[Action, ...]
    cost: int
    fd_gain: int
    bond_gain: int
    found_gain: int
    net: float
    evidence: Tuple[str, ...]
    objective: Optional[StrategicObjective] = None


@dataclass(frozen=True)
class DealComparison:
    """Result of comparing deal-now with attained preparations."""

    choice: str
    option: Optional[PreparationOption]
    saved: Tuple[PreparationOption, ...]
    evidence: Tuple[str, ...]
    deal_net: float
    prep_net: Optional[float] = None


def _label(card) -> str:
    return f"{rank_str(card.rank)}{card.suit.upper()}"


def _net(fd: int, bonds: int, found: int, cost: float) -> float:
    return 3.0 * fd + 1.2 * bonds + 8.0 * found - float(cost)


def prefer_preparation(
    *,
    fd_gain: int,
    bond_gain: int,
    found_gain: int,
    tableau_cost: int,
    prep_net: float,
    deal_net: float,
) -> bool:
    """Whether an attained preparation is worth its corrected-MW cost.

    An empty column by itself is not enough. Face-down access, a foundation,
    or a same-suit bond has to pay for the moves, and the attained net has
    to beat dealing immediately.
    """

    if fd_gain <= 0 and found_gain <= 0 and bond_gain <= 0:
        return False
    if tableau_cost > max(4, 3 * max(0, fd_gain) + 2):
        return False
    return prep_net > deal_net


def plan_still_worth_following(state: SpiderState, remaining: Sequence[Action]) -> bool:
    """True while the unfinished plan still earns its corrected cost."""

    return abandonment_reason(state, remaining) is None and bool(remaining)


def abandonment_reason(state: SpiderState, remaining: Sequence[Action]) -> Optional[str]:
    """Why a committed plan should be dropped, or None to keep it."""

    if not remaining:
        return None
    full = _replay(state, remaining)
    if full is None:
        return "abandoned: committed plan is no longer legal"
    _after, cost, fd, bonds, found = full
    net = _net(fd, bonds, found, cost)
    if len(remaining) > 1:
        suffix = _replay(state, remaining[1:])
        if suffix is not None:
            suffix_net = _net(suffix[2], suffix[3], suffix[4], suffix[1])
            if suffix_net >= net:
                return "abandoned: committed plan no longer improves on the alternatives"
    if net > 0 or fd > 0 or bonds > 0 or found > 0:
        return None
    return "abandoned: committed plan no longer improves on the alternatives"


@dataclass(frozen=True)
class ReceptionComparison:
    """Exact corrected-MW comparison of a prepared deal against dealing now."""

    choice: str
    column: int
    actions: Tuple[Action, ...]
    preparation_cost: int
    deal_only_cost: int
    prepared_connects: bool
    immediate_connects: bool
    post_deal_queen_onto_king: bool
    evidence: Tuple[str, ...]


def _dealt_same_suit(state: SpiderState, column: int, suit: str) -> bool:
    face_up = state.columns[column].face_up
    if len(face_up) < 2:
        return False
    parent, child = face_up[-2], face_up[-1]
    return parent.suit == child.suit == suit and parent.rank - 1 == child.rank


def queen_run_lands_on(state: SpiderState, column: int, suit: str) -> bool:
    """True when a queen-led same-suit run can legally move onto ``column``."""

    for src, dst, k in state.enumerate_moves():
        if dst != column:
            continue
        run = state.columns[src].face_up[-k:]
        if run and run[0].suit == suit and run[0].rank == 12:
            return True
    return False


def compare_exact_reception(
    state: SpiderState,
    prep_actions: Sequence[Action],
    column: int,
    suit: str,
) -> ReceptionComparison:
    """Clone, apply a legal preparation, deal, and compare with dealing now.

    A preparation that is illegal, or that does not create a connection the
    immediate deal lacks, loses to dealing now. A king has no rank-14 parent.
    The comparison then asks whether a queen-led run can move onto it after
    the deal. That continuation is not itself a removed foundation.
    """

    row = next_stock_row(state)
    if row is None or not (0 <= column < len(row)):
        return ReceptionComparison(
            "reject",
            column,
            tuple(prep_actions),
            0,
            0,
            False,
            False,
            False,
            ("fact: no incoming card can be placed in that column",),
        )
    incoming = row[column]
    immediate = state.clone()
    try:
        deal_cost = immediate.deal()
    except ValueError:
        return ReceptionComparison(
            "reject",
            column,
            tuple(prep_actions),
            0,
            0,
            False,
            False,
            False,
            ("fact: the stock row cannot be dealt from this state",),
        )
    immediate_connects = _dealt_same_suit(immediate, column, suit)
    immediate_king = bool(
        incoming.suit == suit and incoming.rank == 13 and queen_run_lands_on(immediate, column, suit)
    )
    if not prep_actions:
        return ReceptionComparison(
            "deal_now",
            column,
            (),
            0,
            int(deal_cost),
            False,
            immediate_connects,
            immediate_king,
            (
                f"fact: column {column + 1} incoming {incoming} is dealt with no preparation",
                f"fact: same-suit landing on the deal is {immediate_connects}",
                f"fact: a queen-led {suit} run can follow a king landing: {immediate_king}",
                "fact: corrected MW includes the deal and no preparatory moves",
            ),
        )
    prepared = state.clone()
    prep_cost = 0
    try:
        for action in prep_actions:
            prep_cost += apply_action(prepared, action)
        prep_cost += prepared.deal()
    except ValueError:
        return ReceptionComparison(
            "reject",
            column,
            tuple(prep_actions),
            0,
            int(deal_cost),
            False,
            immediate_connects,
            immediate_king,
            ("fact: the proposed receiver preparation is not legal on this state",),
        )
    prepared_connects = _dealt_same_suit(prepared, column, suit)
    prepared_king = bool(
        incoming.suit == suit and incoming.rank == 13 and queen_run_lands_on(prepared, column, suit)
    )
    created = (prepared_connects and not immediate_connects) or (prepared_king and not immediate_king)
    lost = (immediate_connects and not prepared_connects) or (immediate_king and not prepared_king)
    evidence = (
        f"fact: column {column + 1} receives incoming {incoming}",
        f"fact: preparation cost {prep_cost} against deal-now cost {deal_cost}",
        f"fact: prepared same-suit landing {prepared_connects}; immediate landing {immediate_connects}",
        f"fact: queen-led follow-up prepared {prepared_king}; immediate {immediate_king}",
        "fact: both figures are corrected MobilityWare costs of the replayed actions",
    )
    if created and not lost and prep_cost <= int(deal_cost) + 3:
        choice = "prepare"
    else:
        choice = "deal_now"
    return ReceptionComparison(
        choice,
        column,
        tuple(prep_actions),
        int(prep_cost),
        int(deal_cost),
        prepared_connects,
        immediate_connects,
        prepared_king or immediate_king,
        evidence,
    )


@dataclass(frozen=True)
class ReceiverLanding:
    """Where the parent of one known incoming card actually is.

    ``already_positioned`` is the only direct reception. The other statuses
    say what would still have to be done. None of them is inferred from the
    parent merely existing somewhere in the tableau.
    """

    status: str
    column: int
    direct: bool
    actions: Tuple[Action, ...]
    cost: int
    evidence: Tuple[str, ...]


def _parent_sites(state: SpiderState, suit: str, rank: int) -> Tuple[Tuple[int, str], ...]:
    found = []
    for index, column in enumerate(state.columns):
        if any(card.suit == suit and card.rank == rank for card in column.face_up):
            found.append((index, "face-up"))
        elif any(card.suit == suit and card.rank == rank for card in column.face_down):
            found.append((index, "face-down"))
    return tuple(found)


def _post_deal_transfer(state: SpiderState, card, column: int):
    """A legal one-card move of the incoming card onto a receiver elsewhere.

    The move is applied on a clone. Returning it means the transfer was
    validated, not that a matching card merely exists.
    """

    row = next_stock_row(state)
    if row is None or not (0 <= column < len(row)):
        return None
    incoming = row[column]
    if incoming.suit != card.suit or incoming.rank != card.rank:
        return None
    dealt = state.clone()
    try:
        apply_action(dealt, ("deal",))
    except ValueError:
        return None
    if dealt.columns[column].top() is not incoming:
        return None
    for action in all_legal_actions(dealt):
        if action == ("deal",) or action[0] != column or action[2] != 1:
            continue
        dest = dealt.columns[action[1]].top()
        if dest is None or dest.suit != incoming.suit or dest.rank != incoming.rank + 1:
            continue
        trial = dealt.clone()
        try:
            cost = apply_action(trial, action)
        except ValueError:
            continue
        return action, int(cost)
    return None


def assess_receiver_move(state: SpiderState, card, column: int, actions: Sequence[Action]) -> ReceiverLanding:
    """Judge one explicit relocation. A move that loses the landing is not worthwhile."""

    compared = compare_exact_reception(state, actions, column, card.suit)
    status = "not_worthwhile" if compared.choice != "prepare" else (
        "needs_preparation" if len(tuple(actions)) > 1 else "relocatable"
    )
    if not actions and compared.immediate_connects:
        status = "already_positioned"
    return ReceiverLanding(
        status,
        column,
        status == "already_positioned",
        tuple(actions),
        int(compared.preparation_cost),
        compared.evidence + ("fact: this relocation was replayed before it was accepted",),
    )


def classify_incoming_receiver(
    state: SpiderState,
    card,
    column: int,
    *,
    max_cost: int = 3,
    max_expand: int = 200,
) -> ReceiverLanding:
    """Classify the receiver for ``card`` landing on ``column``.

    Direct success is only the exposed rank+1 parent on that column. A king
    is an anchor check, not a failed ordinary reception and not a foundation.
    """

    if not 0 <= column < len(state.columns):
        return ReceiverLanding(
            "unavailable",
            column,
            False,
            (),
            0,
            ("fact: that column is not on the tableau",),
        )
    if card.rank >= 13:
        dealt = state.clone()
        queen = False
        try:
            apply_action(dealt, ("deal",))
            queen = queen_run_lands_on(dealt, column, card.suit)
        except ValueError:
            queen = False
        return ReceiverLanding(
            "king_anchor",
            column,
            False,
            (),
            0,
            (
                f"fact: incoming king on column {column + 1} is not a completed foundation",
                f"fact: queen-led follow-up is {queen}",
                "fact: a king has no rank+1 receiver",
            ),
        )
    parent_rank = card.rank + 1
    top = state.columns[column].top()
    if top is not None and top.suit == card.suit and top.rank == parent_rank:
        return ReceiverLanding(
            "already_positioned",
            column,
            True,
            (),
            0,
            (
                f"fact: {top} is already the exposed receiver on column {column + 1}",
                "fact: no relocation is required",
            ),
        )
    sites = _parent_sites(state, card.suit, parent_rank)
    post = _post_deal_transfer(state, card, column)
    objective = PreDealShapingObjective(
        code="same_suit_receiver",
        description=f"top of column {column + 1} receives {card}",
        target_column=column,
        incoming=card,
        predicate_key="same_suit_receiver",
        max_cost=max_cost,
    )
    found = run_bounded_shaping_probe(state, objective, max_cost=max_cost, max_expand=max_expand)
    if found.found and found.path:
        judged = assess_receiver_move(state, card, column, found.path)
        if judged.status in {"relocatable", "needs_preparation"}:
            extra = judged.evidence
            if post is not None:
                extra = extra + (
                    f"fact: after the deal {post[0]} also moves the new card onto a receiver",
                )
            return ReceiverLanding(judged.status, column, False, judged.actions, judged.cost, extra)
        if post is not None:
            return ReceiverLanding(
                "post_deal_transfer",
                column,
                False,
                (post[0],),
                post[1],
                judged.evidence + (
                    "fact: moving the parent first is not worthwhile",
                    f"fact: validated post-deal transfer {post[0]} costs {post[1]}",
                ),
            )
        return ReceiverLanding(
            "not_worthwhile",
            column,
            False,
            tuple(found.path),
            judged.cost,
            judged.evidence + ("fact: the relocation does not beat dealing now",),
        )
    if post is not None:
        return ReceiverLanding(
            "post_deal_transfer",
            column,
            False,
            (post[0],),
            post[1],
            (
                f"fact: {card} can move after the deal by {post[0]}",
                f"fact: corrected cost of that transfer is {post[1]}",
                "fact: the parent was not treated as a reception merely because it exists",
            ),
        )
    if any(zone == "face-down" for _index, zone in sites) or any(
        index == column and zone == "face-up" for index, zone in sites
    ):
        return ReceiverLanding(
            "blocked",
            column,
            False,
            (),
            0,
            (
                f"fact: the {parent_rank}{card.suit} receiver is not a legal landing on column {column + 1}",
                "fact: no bounded relocation exposes it",
            ),
        )
    if sites:
        return ReceiverLanding(
            "blocked",
            column,
            False,
            (),
            0,
            (
                "fact: the receiver is on "
                + ", ".join(f"column {index + 1} ({zone})" for index, zone in sites)
                + f", not on landing column {column + 1}",
                "fact: it cannot be relocated within the corrected-cost bound",
            ),
        )
    row = next_stock_row(state) or ()
    later = any(item.suit == card.suit and item.rank == parent_rank and index != column for index, item in enumerate(row))
    return ReceiverLanding(
        "unavailable",
        column,
        False,
        (),
        0,
        (
            "fact: the receiver is not on the landing column",
            "fact: it arrives in this row on another column" if later else "fact: it is not available until a later event",
        ),
    )


def strategic_stop_status(
    *,
    goal: str,
    legal_count: int,
    proved_no_legal_continuation: bool,
) -> Tuple[str, str]:
    """Separate an unfinished plan from a proof that nothing legal remains."""

    if goal in {"first-foundation", "foundations"} and legal_count > 0 and not proved_no_legal_continuation:
        return (
            "PLANNING_STALL",
            f"planning stall: {legal_count} legal tableau moves remain; "
            "this is not a proof that every continuation is exhausted",
        )
    if legal_count <= 0 or proved_no_legal_continuation:
        return "EXHAUSTED", "no legal continuation under the current restrictions"
    return "EXHAUSTED", "principal objective failed and no dormant alternative remained"


def classify_stall(
    *,
    legal_count: int,
    generated_count: int,
    visible_count: int,
    suppressed: int = 0,
    unrealised: int = 0,
    budget_exhausted: bool = False,
) -> str:
    """Name which stall this is. These conditions are not interchangeable."""

    if budget_exhausted and legal_count > 0:
        return "search budget exhausted"
    if legal_count <= 0:
        return "no legal moves"
    if generated_count <= 0:
        return "no strategic objectives generated"
    if visible_count <= 0 and suppressed > 0:
        return "objectives suppressed after failure"
    if visible_count <= 0 and unrealised > 0:
        return "objectives selected but not realisable"
    if visible_count <= 0:
        return "objectives generated but filtered"
    return "objectives remain"


def soft_failure_id(candidate_id: str) -> bool:
    """A missed realisation may be retried. A failed park may not."""

    if candidate_id.startswith("STRETCH:"):
        return True
    if not candidate_id.startswith("PORTFOLIO:"):
        return False
    text = candidate_id.lower()
    return any(token in text for token in ("expose", "create", "consolidat", "foundation", "shape", "workspace"))


def incoming_alignment_notes(state: SpiderState) -> Tuple[str, ...]:
    """Exact next-row alignment. Facts name cards. Estimates name coverage."""

    row = next_stock_row(state)
    if row is None:
        return ("fact: no stock row remains",)
    notes: List[str] = []
    for index, card in enumerate(row):
        column = state.columns[index]
        top = column.top()
        incoming = _label(card)
        if top is None:
            notes.append(f"fact: column {index + 1} incoming {incoming} lands on an empty column")
            continue
        current = _label(top)
        if top.suit == card.suit and top.rank == card.rank + 1:
            notes.append(f"fact: column {index + 1} incoming {incoming} continues {current}")
        elif column.face_down:
            notes.append(
                f"estimate: dealing covers column {index + 1} before its face-down card is exposed"
            )
        else:
            notes.append(f"fact: column {index + 1} incoming {incoming} covers {current}")
    return tuple(notes)


def compare_before_deal(
    state: SpiderState,
    ranked: Sequence,
    profile: Profile,
    time_left: float,
) -> Optional[DealComparison]:
    """Compare deal-now with at most two attained preparations.

    Returns None when no stock row can be dealt. A returned choice of
    ``prepare`` carries the tableau actions of one preparation. The deal
    itself stays a separate decision so a disappeared benefit can still
    cancel it.
    """

    if not state.can_deal():
        return None
    deal_after, deal_cost, deal_fd, deal_bonds, deal_found = _deal_metrics(state)
    deal_net = _net(deal_fd, deal_bonds, deal_found, deal_cost)
    notes = list(incoming_alignment_notes(state))
    if time_left < 0.15:
        notes.append("estimate: preparation search skipped because the time budget is nearly spent")
        return DealComparison("deal", None, (), tuple(notes), deal_net, None)

    objectives = _candidate_objectives(state, ranked)
    if not objectives:
        return DealComparison("deal", None, (), tuple(notes), deal_net, None)

    per_time = min(0.8, max(0.2, time_left / 4.0))
    nodes = min(2500, max(int(profile.tactical_nodes), 600))
    max_cost = min(8, max(6, int(profile.tactical_max_cost)))
    found: List[PreparationOption] = []
    for objective in objectives[:2]:
        option = _realize_one(state, objective, max_cost=max_cost, nodes=nodes, time_limit_s=per_time)
        if option is None:
            notes.append(
                f"estimate: {objective.objective_id} was not realised inside the tactical budget"
            )
            continue
        found.append(option)
        notes.append(
            f"estimate: exposing preparation {option.objective_id} costs {option.cost} MW "
            f"and reveals {option.fd_gain}"
        )

    if not found:
        return DealComparison("deal", None, (), tuple(notes), deal_net, None)

    close = any(abs(option.net - deal_net) <= 1.5 for option in found)
    follow_deal = _followup_gain(deal_after) if close else 0.0
    probed_deal = deal_net + (0.15 * follow_deal if close else 0.0)
    best: Optional[PreparationOption] = None
    best_net = None
    for option in found:
        prep_net = option.net
        if close:
            prep_net += 0.15 * _followup_gain(_after_prep_and_deal(state, option.actions))
        adjusted = PreparationOption(
            objective_id=option.objective_id,
            actions=option.actions,
            cost=option.cost,
            fd_gain=option.fd_gain,
            bond_gain=option.bond_gain,
            found_gain=option.found_gain,
            net=prep_net,
            evidence=option.evidence + tuple(notes),
            objective=option.objective,
        )
        if best is None or adjusted.net > best_net:
            best = adjusted
            best_net = adjusted.net

    saved = tuple(option for option in found if option.fd_gain >= 1 or option.found_gain >= 1)
    assert best is not None and best_net is not None
    take = prefer_preparation(
        fd_gain=best.fd_gain,
        bond_gain=best.bond_gain,
        found_gain=best.found_gain,
        tableau_cost=best.cost,
        prep_net=best_net,
        deal_net=probed_deal,
    )
    if take:
        notes.append(
            f"estimate: preparation net {best_net:.2f} beats dealing now at {probed_deal:.2f}"
        )
        chosen = PreparationOption(
            objective_id=best.objective_id,
            actions=best.actions,
            cost=best.cost,
            fd_gain=best.fd_gain,
            bond_gain=best.bond_gain,
            found_gain=best.found_gain,
            net=best_net,
            evidence=best.evidence + (notes[-1],),
            objective=best.objective,
        )
        return DealComparison("prepare", chosen, saved, tuple(notes), probed_deal, best_net)
    notes.append(
        f"estimate: preparation net {best_net:.2f} does not beat dealing now at {probed_deal:.2f}"
    )
    return DealComparison("deal", None, saved, tuple(notes), probed_deal, best_net)


def _replay(state: SpiderState, actions: Sequence[Action]):
    trial = state.clone()
    cost = 0
    for action in actions:
        if action == ("deal",):
            if not trial.can_deal():
                return None
        elif not trial.can_move(*action):
            return None
        cost += apply_action(trial, action)
    return (
        trial,
        cost,
        face_down_count(state) - face_down_count(trial),
        same_suit_bonds(trial) - same_suit_bonds(state),
        len(trial.foundations) - len(state.foundations),
    )


def _deal_metrics(state: SpiderState):
    played = _replay(state, (("deal",),))
    assert played is not None
    return played


def _after_prep_and_deal(state: SpiderState, actions: Sequence[Action]) -> Optional[SpiderState]:
    mid = _replay(state, actions)
    if mid is None:
        return None
    trial = mid[0]
    if trial.can_deal():
        apply_action(trial, ("deal",))
    return trial


def _followup_gain(state: Optional[SpiderState]) -> float:
    """Best immediate tableau gain after a checkpoint. Ordering only."""

    if state is None:
        return 0.0
    best = 0.0
    seen = 0
    for action in state.enumerate_moves():
        played = _replay(state, (action,))
        if played is None:
            continue
        _trial, cost, fd, bonds, found = played
        best = max(best, _net(fd, bonds, found, cost))
        seen += 1
        if seen >= 40:
            break
    return best


def _candidate_objectives(state: SpiderState, ranked: Sequence) -> List[StrategicObjective]:
    synthesized = _shallow_exposes(state)
    extras: List[StrategicObjective] = []
    for candidate in ranked:
        objective = getattr(candidate, "objective", None)
        if objective is None or objective.kind not in _PREP_KINDS:
            continue
        extras.append(objective)
    extras.sort(key=lambda item: (0 if item.kind == ObjectiveKind.EXPOSE_REVEAL_PREFIX else 1, item.heuristic_est_cost, item.objective_id))
    ordered = synthesized + extras
    chosen: List[StrategicObjective] = []
    seen_columns = set()
    seen_keys = set()
    for objective in ordered:
        key = objective.dedupe_key()
        if key in seen_keys:
            continue
        if objective.kind == ObjectiveKind.EXPOSE_REVEAL_PREFIX:
            column = objective.target_params.get("column")
            if column in seen_columns:
                continue
            seen_columns.add(column)
        seen_keys.add(key)
        chosen.append(objective)
        if len(chosen) == 2:
            break
    return chosen


def _shallow_exposes(state: SpiderState) -> List[StrategicObjective]:
    ranked_columns = []
    for index, column in enumerate(state.columns):
        if not column.face_down or not column.face_up:
            continue
        movable = any(state.can_move(index, dst, 1) for dst in range(10) if dst != index)
        ranked_columns.append((1 if movable else 0, -len(column.face_up), -len(column.face_down), -index, index))
    ranked_columns.sort(reverse=True)
    objectives = []
    for _score in ranked_columns[:2]:
        objectives.append(_expose_objective(state, _score[-1]))
    return objectives


def _expose_objective(state: SpiderState, column: int) -> StrategicObjective:
    start = len(state.columns[column].face_down)
    bound = compute_objective_lower_bound(kind="EXPOSE_REVEAL_PREFIX", min_reveals=1, state=state)
    return StrategicObjective(
        kind=ObjectiveKind.EXPOSE_REVEAL_PREFIX,
        objective_id=f"expose_c{column + 1}_d1",
        description=f"Expose one face-down card on column {column + 1} before dealing",
        target_key="column_face_down_le",
        target_params={
            "column": column,
            "max_face_down": start - 1,
            "start_face_down": start,
            "required_reveals": 1,
        },
        hard_preconditions=(f"column {column + 1} has {start} face-down card(s)",),
        hard_evidence=(f"fact: column {column + 1} face-down {start}",),
        admissible_lb=bound.h_admissible,
        admissible_breakdown=bound,
        heuristic_est_cost=2.0,
        heuristic_est_benefit=1.5,
        priority=PriorityComponents(reveal=3.0, urgency=1.0),
        foundation_relevance="indirect",
        workspace_relevance="local",
        stock_relevance="before the next deal",
        explanation="Shallow excavation checked at the deal boundary.",
    )


def _realize_one(
    state: SpiderState,
    objective: StrategicObjective,
    *,
    max_cost: int,
    nodes: int,
    time_limit_s: float,
) -> Optional[PreparationOption]:
    try:
        found = realize_objective(
            state,
            objective,
            mode=RealizationMode.FAST_BOUNDED,
            max_cost=max_cost,
            max_nodes=nodes,
            time_limit_s=time_limit_s,
            beam=32,
        )
    except Exception:
        return None
    if found.status != RealizationStatus.FOUND or not found.actions:
        return None
    actions = _tableau_only(found.actions)
    if not actions:
        return None
    played = _replay(state, actions)
    if played is None:
        return None
    _mid, cost, fd, bonds, found_gain = played
    if objective.kind == ObjectiveKind.EXPOSE_REVEAL_PREFIX and fd <= 0:
        return None
    end_cost = cost
    end_fd, end_bonds, end_found = fd, bonds, found_gain
    if _mid.can_deal():
        dealt = _replay(_mid, (("deal",),))
        if dealt is not None:
            end_cost = cost + dealt[1]
            end_fd = face_down_count(state) - face_down_count(dealt[0])
            end_bonds = same_suit_bonds(dealt[0]) - same_suit_bonds(state)
            end_found = len(dealt[0].foundations) - len(state.foundations)
    evidence = (
        f"fact: preparation {' '.join(_format(action) for action in actions)}",
        f"fact: corrected tableau cost {cost}",
        f"fact: face-down exposed {fd}; same-suit bonds {bonds:+d}; foundations {found_gain:+d}",
        "estimate: net includes the following deal when it remains legal",
    )
    return PreparationOption(
        objective_id=f"PREPARE:{objective.objective_id}",
        actions=tuple(actions),
        cost=int(cost),
        fd_gain=int(fd),
        bond_gain=int(bonds),
        found_gain=int(found_gain),
        net=_net(end_fd, end_bonds, end_found, end_cost),
        evidence=evidence,
        objective=objective,
    )


def _tableau_only(actions: Sequence[Action]) -> Tuple[Action, ...]:
    if any(action == ("deal",) for action in actions[:-1]):
        return ()
    if actions and actions[-1] == ("deal",):
        return tuple(actions[:-1])
    return tuple(actions)


def _format(action: Action) -> str:
    if action == ("deal",):
        return "deal"
    src, dst, count = action
    return f"move {src + 1} {dst + 1} {count}"


def workspace_created(before: SpiderState, after: SpiderState) -> int:
    return empty_count(after) - empty_count(before)
