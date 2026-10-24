"""Cheap structural features, admissible bounds, and heuristic estimates.

Admissible values may prune. Heuristic values may only order candidates.
Experimental debt scores are not computed here and are not bounds.
"""

from __future__ import annotations

from typing import Optional

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.engine import SpiderState
from spider.metrics import Action, format_action
from spider.planner.lower_bounds import compute_solution_lower_bound
from spider.planner.space_lifecycle import empty_count
from spider.planner.stock_reception import next_stock_row
from spider.research_actions import all_legal_actions, face_down_count, step_cost


def stock_rows(state: SpiderState) -> int:
    return len(state.stock) // 10


def admissible_remaining(state: SpiderState) -> int:
    """Safe lower bound on remaining corrected MW. Not a debt score."""

    bound = int(compute_solution_lower_bound(state).h_admissible)
    if stock_rows(state) == 0:
        bound = max(bound, int(stock_empty_assembly_h(state, 0)))
    return bound


def same_suit_bonds(state: SpiderState) -> int:
    bonds = 0
    for column in state.columns:
        up = column.face_up
        for index in range(len(up) - 1):
            upper, lower = up[index], up[index + 1]
            if upper.suit == lower.suit and upper.rank == lower.rank + 1:
                bonds += 1
    return bonds


def mixed_boundaries(state: SpiderState) -> int:
    count = 0
    for column in state.columns:
        up = column.face_up
        for index in range(len(up) - 1):
            upper, lower = up[index], up[index + 1]
            if upper.suit != lower.suit and upper.rank == lower.rank + 1:
                count += 1
    return count


def longest_same_suit_run(state: SpiderState) -> int:
    best = 0
    for column in state.columns:
        up = column.face_up
        run = 0
        for index, card in enumerate(up):
            if index == 0:
                run = 1
            elif up[index - 1].suit == card.suit and up[index - 1].rank == card.rank + 1:
                run += 1
            else:
                best = max(best, run)
                run = 1
        best = max(best, run)
    return best


def _same_suit_home(state: SpiderState, src: int, rank: int, suit: str) -> bool:
    for dst in range(len(state.columns)):
        if dst == src:
            continue
        top = state.columns[dst].top()
        if top is None:
            continue
        if top.suit == suit and top.rank == rank + 1 and state.can_move(src, dst, 1):
            return True
    return False


def bury_risk(state: SpiderState) -> int:
    """Accessible cards an immediate deal would cover despite a same-suit home.

    This is an estimate input. It is not an admissible bound.
    """

    row = next_stock_row(state)
    if row is None:
        return 0
    risk = 0
    for index, incoming in enumerate(row):
        column = state.columns[index]
        top = column.top()
        if top is None:
            continue
        if top.suit == incoming.suit and top.rank == incoming.rank + 1:
            continue
        up = column.face_up
        if len(up) >= 2 and up[-2].suit == top.suit and up[-2].rank == top.rank + 1:
            continue
        if _same_suit_home(state, index, top.rank, top.suit):
            risk += 1
    return risk


def _home_top_exists(state: SpiderState, src: int, rank: int, suit: str) -> bool:
    """A visible top is the same-suit parent, whether or not the buried card can move."""

    for dst, column in enumerate(state.columns):
        if dst == src:
            continue
        top = column.top()
        if top is not None and top.suit == suit and top.rank == rank + 1:
            return True
    return False


def buried_useful(state: SpiderState) -> int:
    """Covered cards that still have a same-suit home on another top. Capped.

    ``can_move`` is the wrong test here: the covered card is not the top, so
    a legal move of the current top does not describe the buried card.
    """

    found = 0
    for src, column in enumerate(state.columns):
        up = column.face_up
        for depth, card in enumerate(up[:-1]):
            cover = up[depth + 1]
            if cover.suit == card.suit and cover.rank == card.rank - 1:
                continue
            if _home_top_exists(state, src, card.rank, card.suit):
                found += 1
                if found >= 4:
                    return found
    return found


def same_suit_landings(state: SpiderState) -> int:
    row = next_stock_row(state)
    if row is None:
        return 0
    count = 0
    for index, incoming in enumerate(row):
        top = state.columns[index].top()
        if top is not None and top.suit == incoming.suit and top.rank == incoming.rank + 1:
            count += 1
    return count


def debt_score(state: SpiderState) -> float:
    """Estimated structural burden. Not an admissible bound."""

    return (
        1.0 * face_down_count(state)
        + 0.5 * mixed_boundaries(state)
        + 2.0 * bury_risk(state)
        + 2.0 * buried_useful(state)
    )


def goodness_score(state: SpiderState) -> float:
    """Estimated construction progress. Tie-break only; it cannot cancel a move."""

    return (
        0.8 * same_suit_landings(state)
        + 0.25 * same_suit_bonds(state)
        + 0.15 * longest_same_suit_run(state)
    )


def placed_debt(state: SpiderState) -> float:
    """Mixed boundaries and buried cards already on the tableau."""

    return 0.5 * mixed_boundaries(state) + 2.0 * buried_useful(state)


def incoming_row_damage(state: SpiderState) -> float:
    """Estimated debt the next stock row adds if it is dealt immediately.

    Charged on positions that still hold the row, so a move cannot look
    cheaper merely by leaving that debt uncounted. It is not admissible.
    """

    if len(state.stock) < 10:
        return 0.0
    before = placed_debt(state)
    clone = state.clone()
    clone.deal()
    return max(0.0, placed_debt(clone) - before)


def tableau_assembly_estimate(state: SpiderState) -> int:
    """Assembly bound of the cards already on the tableau.

    While stock remains, ``stock_empty_assembly_h`` is defined to be 0.
    That hides work the current cards will still require, and it makes
    the last deal look like it created the whole endgame. This preview
    is an estimate. ``admissible_remaining`` does not include it until
    the stock is actually empty.
    """

    if stock_rows(state) == 0:
        return int(stock_empty_assembly_h(state, 0))
    clone = state.clone()
    clone.stock.clear()
    return int(stock_empty_assembly_h(clone, 0))


def estimate_remaining(state: SpiderState) -> float:
    """Heuristic remaining completion cost. Explicitly not admissible.

    A solved board is 0. Otherwise the figure is the admissible remainder
    plus estimated debt. While stock remains, the latent tableau assembly
    cost is added so a deal is compared with the work already on the board.
    Attractiveness is not subtracted.
    """

    if state.is_solved():
        return 0.0
    estimate = float(admissible_remaining(state)) + debt_score(state)
    if stock_rows(state) != 0:
        estimate += float(tableau_assembly_estimate(state))
        estimate += incoming_row_damage(state)
    return estimate


def splits_same_suit_run(state: SpiderState, action: Action) -> bool:
    if action == ("deal",):
        return False
    src, _dst, k = action
    up = state.columns[src].face_up
    if k >= len(up):
        return False
    parent = up[-k - 1]
    head = up[-k]
    return parent.suit == head.suit and parent.rank == head.rank + 1


def reveals(state: SpiderState, action: Action) -> bool:
    if action == ("deal",):
        return False
    src, _dst, k = action
    column = state.columns[src]
    return k == len(column.face_up) and len(column.face_down) > 0


def unproductive_empty_move(state: SpiderState, action: Action, after: SpiderState) -> bool:
    """A move onto an empty column that reveals nothing and builds nothing.

    A zero-cost transfer that creates a same-suit landing, or a peel that
    flips a face-down card, is productive and returns False.
    """

    if action == ("deal",):
        return False
    _src, dst, _k = action
    if not state.columns[dst].is_empty():
        return False
    if reveals(state, action):
        return False
    if same_suit_bonds(after) > same_suit_bonds(state):
        return False
    if same_suit_landings(after) > same_suit_landings(state):
        return False
    return True


def useless_king_relocate(state: SpiderState, action: Action) -> bool:
    """A king moved onto an empty column that reveals nothing and fixes no landing."""

    if action == ("deal",):
        return False
    src, dst, k = action
    up = state.columns[src].face_up
    if k != len(up) or not up or up[0].rank != 13:
        return False
    if not state.columns[dst].is_empty():
        return False
    if len(state.columns[src].face_down) > 0:
        return False
    before = bury_risk(state)
    trial = state.clone()
    trial.move(src, dst, k)
    return bury_risk(trial) >= before and same_suit_landings(trial) <= same_suit_landings(state)


def cost_led_action(state: SpiderState) -> Optional[Action]:
    """One-ply minimum immediate cost. Ties prefer Deal.

    This is the v0.106 failure mode in miniature: Deal costs 1, so it ties
    every ordinary tableau move and wins the tie. It is not a full search.
    """

    actions = all_legal_actions(state)
    if not actions:
        return None

    def key(action: Action):
        deal_first = 0 if action == ("deal",) else 1
        return (step_cost(state, action), deal_first, format_action(action))

    return min(actions, key=key)


def should_switch(
    active_projected: float,
    challenger_projected: float,
    active_failed: bool,
    margin: float,
) -> bool:
    """True when the principal objective should be dropped.

    A tiny improvement inside ``margin`` does not switch an open plan.
    """

    if active_failed:
        return True
    return challenger_projected + margin < active_projected
