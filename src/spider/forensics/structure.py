"""State-only structural measures.

Every function here is determined by the current SpiderState. Path history
(parks, rehandles, stock landings) is recorded elsewhere and labelled
path-dependent. Nothing in this module applies moves or uses undo.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from spider.engine import SpiderState
from spider.research_actions import (
    empty_column_indices,
    face_down_count,
    pretty_card,
    stock_rows,
)
from spider.structural_analysis import (
    current_tableau_summary,
    foundation_readiness,
    interference_debt,
    same_suit_component_spans,
)

# Composite weights. Experimental: not a calibrated estimate of remaining
# MobilityWare cost. Face-down count is deliberately excluded. Original
# buried cards are unsolved work, not debt purchased by a convenient move.
EXPERIMENTAL_DEBT_WEIGHTS = {
    "suit_boundaries": 3,
    "rank_discontinuities": 2,
    "buried_face_up": 1,
    "component_layers": 2,
    "immobile_exposed": 1,
}


def _run_text(cards) -> Optional[str]:
    if not cards:
        return None
    if len(cards) == 1:
        return pretty_card(cards[0])
    return f"{pretty_card(cards[0])}-{pretty_card(cards[-1])}"


def movable_block_length(face_up) -> int:
    """Longest suffix of ``face_up`` that is one legal same-suit block."""

    best = 0
    for size in range(1, len(face_up) + 1):
        if SpiderState.is_movable_run(face_up[-size:]):
            best = size
        else:
            break
    return best


def exposed_descending_any_suit(face_up) -> int:
    """Descending run from the exposed top, ignoring suit.

    ``face_up[-1]`` is the exposed card. A step toward the bottom continues
    the run when the deeper card is exactly one rank higher.
    """

    if not face_up:
        return 0
    length = 1
    index = len(face_up) - 1
    while index > 0 and face_up[index - 1].rank == face_up[index].rank + 1:
        length += 1
        index -= 1
    return length


def experimental_debt_score(indicators: Dict[str, int]) -> int:
    """Exploratory column score. Marked experimental wherever it is stored."""

    return sum(
        int(indicators.get(name, 0)) * weight
        for name, weight in EXPERIMENTAL_DEBT_WEIGHTS.items()
    )


def column_structure(state: SpiderState, index: int) -> dict:
    """Interpretable structure of one tableau column. ``index`` is 0-based."""

    column = state.columns[index]
    face_up = column.face_up
    face_down_n = len(column.face_down)
    face_up_n = len(face_up)
    empty = column.is_empty()
    spans = same_suit_component_spans(face_up)
    components = len(spans)
    same_suit_bonds = sum((end - start) - 1 for start, end in spans)
    suit_boundaries = 0
    rank_discontinuities = 0
    off_suit_continuations = 0
    for deeper, shallower in zip(face_up, face_up[1:]):
        rank_continues = deeper.rank == shallower.rank + 1
        same_suit = deeper.suit == shallower.suit
        if not same_suit:
            suit_boundaries += 1
        if not rank_continues:
            rank_discontinuities += 1
        elif not same_suit:
            off_suit_continuations += 1
    movable = movable_block_length(face_up)
    descending_any = exposed_descending_any_suit(face_up)
    legal_destinations = 0
    if movable:
        for dest in range(len(state.columns)):
            if dest != index and state.can_move(index, dest, movable):
                legal_destinations += 1
    free_relocatable = (not empty) and face_down_n == 0 and movable == face_up_n and face_up_n > 0
    immobile = int(movable > 0 and legal_destinations == 0 and not empty)
    buried_face_up = face_up_n - movable
    component_layers = max(0, components - 1)
    indicators = {
        "suit_boundaries": suit_boundaries,
        "rank_discontinuities": rank_discontinuities,
        "off_suit_continuations": off_suit_continuations,
        "buried_face_up": buried_face_up,
        "face_down": face_down_n,
        "component_layers": component_layers,
        "immobile_exposed": immobile,
    }
    disorder = suit_boundaries + rank_discontinuities
    if empty:
        workspace_class = "empty"
    elif free_relocatable:
        workspace_class = "free_relocatable"
    else:
        workspace_class = "occupied"
    return {
        "column": index + 1,
        "face_down": face_down_n,
        "face_up": face_up_n,
        "height": face_down_n + face_up_n,
        "top_card": None if not face_up else pretty_card(face_up[-1]),
        "top_rank": None if not face_up else int(face_up[-1].rank),
        "top_suit": None if not face_up else face_up[-1].suit,
        "empty": empty,
        "exposed_same_suit_run": movable,
        "exposed_run": _run_text(face_up[-movable:] if movable else []),
        "exposed_descending_any_suit": descending_any,
        "suit_boundaries": suit_boundaries,
        "rank_discontinuities": rank_discontinuities,
        "off_suit_continuations": off_suit_continuations,
        "same_suit_bonds": same_suit_bonds,
        "same_suit_components": components,
        "component_layers": component_layers,
        "movable_block": movable,
        "movable_block_destinations": legal_destinations,
        "buried_face_up": buried_face_up,
        "immobile_exposed": immobile,
        "workspace_class": workspace_class,
        "usable_as_workspace": workspace_class == "empty",
        "free_relocatable": free_relocatable,
        "mixed_suit_parked": suit_boundaries > 0,
        "disorder": disorder,
        "debt_indicators": indicators,
        "experimental_debt_score": experimental_debt_score(indicators),
        "experimental_debt_score_note": (
            "exploratory linear combination of state-only indicators; "
            "not a validated remaining-cost estimate; face-down is reported "
            "in the vector and excluded from this score"
        ),
    }


def order_change(previous: Optional[dict], current: dict) -> str:
    """Whether this column became more or less ordered than the prior state."""

    if previous is None:
        return "opening"
    previous_penalty = int(previous["disorder"])
    current_penalty = int(current["disorder"])
    if current_penalty < previous_penalty or (
        current_penalty == previous_penalty
        and int(current["same_suit_bonds"]) > int(previous["same_suit_bonds"])
    ):
        return "more_ordered"
    if current_penalty > previous_penalty or (
        current_penalty == previous_penalty
        and int(current["same_suit_bonds"]) < int(previous["same_suit_bonds"])
    ):
        return "less_ordered"
    return "unchanged"


def tableau_structure(state: SpiderState, *, with_readiness: bool = True) -> dict:
    """Whole-tableau aggregates reused from existing structural measures.

    ``with_readiness`` calls ``foundation_readiness``. Counterfactual
    screening turns it off. The resulting keys are still present and null.
    """

    columns = [column_structure(state, index) for index in range(len(state.columns))]
    summary = current_tableau_summary(state)
    debt = interference_debt(state)
    readiness = foundation_readiness(state) if with_readiness else None
    legal = state.enumerate_moves()
    reveal_moves = 0
    reveal_columns = set()
    same_suit_moves = 0
    empty_dest_moves = 0
    for src, dst, size in legal:
        source = state.columns[src]
        if size == len(source.face_up) and source.face_down:
            reveal_moves += 1
            reveal_columns.add(src)
        run = source.face_up[-size:]
        top = state.columns[dst].top()
        if state.columns[dst].is_empty():
            empty_dest_moves += 1
        elif top is not None and top.suit == run[0].suit and top.rank == run[0].rank + 1:
            same_suit_moves += 1
    parking = sum(1 for column in columns if column["mixed_suit_parked"])
    debt_scores = [column["experimental_debt_score"] for column in columns]
    return {
        "columns": columns,
        "stock_rows_remaining": stock_rows(state),
        "foundations_completed": len(state.foundations),
        "face_down_remaining": face_down_count(state),
        "empty_columns": len(empty_column_indices(state)),
        "empty_column_numbers": [index + 1 for index in empty_column_indices(state)],
        "same_suit_bonds": int(summary["same_suit_bonds"]),
        "run_compression": int(summary["run_compression"]),
        "longest_run": int(summary["longest_run"]),
        "visible_runs": int(summary["visible_runs"]),
        "visible_cards": int(summary["visible_cards"]),
        "exposed_movable_blocks": sum(1 for column in columns if column["movable_block"] > 0),
        "exposed_movable_cards": sum(column["movable_block"] for column in columns),
        "legal_tableau_moves": len(legal),
        "legal_same_suit_attaches": same_suit_moves,
        "legal_reveal_moves": reveal_moves,
        "legal_reveal_columns": len(reveal_columns),
        "legal_empty_destinations": empty_dest_moves,
        "mixed_suit_parking_columns": parking,
        "interference_boundaries": int(debt["boundaries_total"]),
        "interference_off_suit": int(debt["off_suit_boundaries"]),
        "interference_rank_breaks": int(debt["rank_break_boundaries"]),
        "interference_component_layers": int(debt["component_layers"]),
        "interference_mixed_supports": int(debt["mixed_supports"]),
        "max_column_height": max(column["height"] for column in columns),
        "max_column_disorder": max(column["disorder"] for column in columns),
        "experimental_debt_sum": sum(debt_scores),
        "experimental_debt_max": max(debt_scores),
        "experimental_debt_argmax_column": debt_scores.index(max(debt_scores)) + 1,
        "readiness_n_ready": None if readiness is None else int(readiness["n_ready"]),
        "readiness_ready_suits": [] if readiness is None else list(readiness["ready_suits"]),
        "readiness_nearest_horizon": None if readiness is None else readiness["nearest_horizon"],
        "readiness_nearest_suits": [] if readiness is None else list(readiness["nearest_suits"]),
    }


def phase_label(stock_deals_completed: int, stock_rows_remaining: int) -> str:
    """Forensic horizon of a state. Stock boundaries are the primary phases."""

    if stock_deals_completed <= 0:
        return "pre-SD1"
    if stock_rows_remaining <= 0:
        return "stock-empty-endgame"
    return f"post-SD{stock_deals_completed}"
