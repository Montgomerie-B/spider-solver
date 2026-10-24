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
from spider.planner.stock_reception import next_stock_row
from spider.planner.strategic_objectives import (
    ObjectiveKind,
    PriorityComponents,
    StrategicObjective,
)
from spider.research_actions import apply_action, face_down_count

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
