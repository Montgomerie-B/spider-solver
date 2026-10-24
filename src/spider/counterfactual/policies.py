"""Action policies for one counterfactual search.

C0 is the engine's legal action list, including Deal.
C1 hides tableau moves that raise one column's exposed suit boundaries
until the next stock deal. The engine still considers those moves legal.
C2 keeps every legal move. Its search key breaks ties at equal corrected
MW cost. The key is not the experimental debt score.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import Action, format_action
from spider.research_actions import all_legal_actions

FOCUS_INDEX_DEFAULT = 3


def suit_boundaries(face_up: Sequence) -> int:
    return sum(1 for deeper, shallower in zip(face_up, face_up[1:]) if deeper.suit != shallower.suit)


def rank_discontinuities(face_up: Sequence) -> int:
    return sum(
        1 for deeper, shallower in zip(face_up, face_up[1:]) if deeper.rank != shallower.rank + 1
    )


def same_suit_bonds(state: SpiderState) -> int:
    bonds = 0
    for column in state.columns:
        face_up = column.face_up
        for deeper, shallower in zip(face_up, face_up[1:]):
            if deeper.suit == shallower.suit and deeper.rank == shallower.rank + 1:
                bonds += 1
    return bonds


def focus_suit_boundaries(state: SpiderState, focus_index: int) -> int:
    return suit_boundaries(state.columns[focus_index].face_up)


def increases_focus_suit_boundaries(state: SpiderState, action: Action, focus_index: int) -> bool:
    """True when a tableau move raises the focus column's suit-boundary count.

    The comparison applies the move on a clone, so reveal and automatic
    foundation removal are the engine's. Deal is never an increase here:
    the hard policy does not forbid Deal.
    """

    if action == ("deal",):
        return False
    src, dst, _k = action  # type: ignore[misc]
    if src != focus_index and dst != focus_index:
        return False
    before = focus_suit_boundaries(state, focus_index)
    trial = state.clone()
    trial.move(src, dst, _k)
    return focus_suit_boundaries(trial, focus_index) > before


def soft_lane_key(state: SpiderState, g: int, focus_index: int) -> Tuple[int, int, int, int]:
    """Best-g first. Structure only orders equal corrected-MW states.

    Lower is expanded first. Components, in order: focus suit boundaries,
    focus rank discontinuities, then more same-suit bonds. This is not a
    forecast of remaining MW and it is not the experimental debt total.
    """

    face_up = state.columns[focus_index].face_up
    return (
        int(g),
        suit_boundaries(face_up),
        rank_discontinuities(face_up),
        -same_suit_bonds(state),
    )


def control_lane_key(state: SpiderState, g: int) -> Tuple[int]:
    del state
    return (int(g),)


def policy_actions(
    kind: str,
    state: SpiderState,
    *,
    focus_index: int,
    root_stock_len: int,
    root_store: bytes,
    forbidden: Optional[Action],
) -> list:
    """Legal actions after the policy. Engine order is preserved."""

    legal = all_legal_actions(state)
    if kind == "control":
        return legal
    if kind == "soft":
        return legal
    if kind == "suppress_one":
        if forbidden is None or not pack_matches(state, root_store):
            return legal
        return [action for action in legal if action != forbidden]
    if kind == "hard":
        if len(state.stock) != root_stock_len:
            return legal
        return [
            action
            for action in legal
            if action == ("deal",) or not increases_focus_suit_boundaries(state, action, focus_index)
        ]
    raise ValueError(f"unknown policy kind: {kind}")


def pack_matches(state: SpiderState, root_store: bytes) -> bool:
    from spider.packed_state import pack_state

    return pack_state(state) == root_store


POLICIES = (
    {
        "name": "C0",
        "kind": "control",
        "experiments": ("A", "B"),
        "summary": "Unmodified legal actions, including Deal. Best-g search. No column restriction.",
    },
    {
        "name": "C1",
        "kind": "hard",
        "experiments": ("A", "B"),
        "summary": (
            "Until the next stock deal, tableau moves that increase the focus column's "
            "exposed suit boundaries are hidden from search. They stay legal in the engine. "
            "Deal is allowed. The restriction lifts at the next deal."
        ),
    },
    {
        "name": "C2",
        "kind": "soft",
        "experiments": ("A", "B"),
        "summary": (
            "Every legal move remains available. At equal corrected MW cost, search expands "
            "a lower focus-column suit-boundary count, then fewer rank discontinuities, "
            "then more same-suit bonds. Corrected MW stays the primary key."
        ),
    },
    {
        "name": "A-suppress",
        "kind": "suppress_one",
        "experiments": ("A",),
        "summary": (
            "At the experiment root only, hide the original first action. "
            "Later placements onto the focus column stay available."
        ),
    },
)


def describe_action(action: Action) -> str:
    return format_action(action)
