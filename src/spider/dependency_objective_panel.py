"""Frozen comparison panel for the PR4 local-objective pilot.

This module records board definitions, the development/reserved split,
the shared reveal objective, the search budget, and the pass criteria.
It does not search and it does not rank. Card literals belong here.
The evaluator takes a state and a predicate; it does not import these
layouts.

Every state is a deliberately partial deck: ten tableau columns and one
stock card, so Deal is illegal. None of these states is deal 4925153
and none is a 104-card deal. An initial structural empty is not used.
On this engine that empty accepts a move from every other face-up
column, which is at least nine candidates and cannot fit the cap of
eight without dropping a legal move.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Tuple

from spider.cards import Card
from spider.engine import Column, SpiderState

DECK_LABEL = "partial-synthetic"

# One worker: the existing kernel is single-threaded. Caps are total
# corrected moves from the common local source, not a second budget.
COMPARISON_BUDGET = {
    "max_unique": 20,
    "time_limit_s": 2.0,
    "rss_abort_mb": 512.0,
    "cost_ceiling": 4,
    "max_depth": None,
    "workers": 1,
    "stop_on_first_terminal": False,
    "harvest_slack": None,
}

SUCCESS_CRITERIA = (
    "size-1 preserves its sole receiver",
    "size-2 selects the verified 2-move reveal instead of the baseline 3-move reveal",
    "at least two of the three reserved boards are fully comparable",
    "at least one structurally different reserved board shows a strict verified improvement",
    "fully comparable boards have no worse pilot choice",
    "ties keep the baseline order",
    "the immediate join, the zero-cost continuation, and the other-column reveal behave correctly",
    "regression checks pass apart from disclosed baseline issues",
)


@dataclass(frozen=True)
class PanelBoard:
    """One frozen synthetic source. ``columns`` is bottom-to-top face-up text."""

    board_id: str
    role: str
    purpose: str
    target_column: int
    stock: str
    columns: Tuple[Tuple[str, str], ...]


def _columns(mapping: Mapping[int, Tuple[str, str]]) -> Tuple[Tuple[str, str], ...]:
    return tuple(mapping[index] for index in range(10))


def _size_control(column4: str) -> Tuple[Tuple[str, str], ...]:
    face_up = {
        0: "8c 3h",
        1: "9c",
        2: "4d",
        3: "kd 8c",
        4: column4,
        5: "kh",
        6: "kd",
        7: "kc",
        8: "ks",
        9: "kh",
    }
    return tuple(("4d" if index == 0 else "", face_up[index]) for index in range(10))


_BURIED = "ks"

PANEL_BOARDS: Tuple[PanelBoard, ...] = (
    PanelBoard(
        board_id="size-1-scarce-receiver",
        role="development",
        purpose="Existing PR1 size-1 control. The only club receiver is column 1. Preserving it is the sole critical receiver.",
        target_column=0,
        stock="ad",
        columns=_size_control("ks"),
    ),
    PanelBoard(
        board_id="size-2-alternative-receiver",
        role="development",
        purpose="Existing size-2 control. Column 4 is a second 9c, so the club join is not critical. The legal set includes (3, 4, 1).",
        target_column=0,
        stock="ad",
        columns=_size_control("9c"),
    ),
    PanelBoard(
        board_id="blocker-chain",
        role="development",
        purpose="The club receiver 8c is covered by 9d. Clearing that cover reveals column 0 in two moves. A same-suit heart join is the competing first move.",
        target_column=0,
        stock="2d",
        columns=_columns(
            {
                0: ("ks", "7c"),
                1: ("ks", "8c 9d"),
                2: (_BURIED, "10h"),
                3: (_BURIED, "2h"),
                4: (_BURIED, "3h"),
                5: (_BURIED, "5c"),
                6: (_BURIED, "5d"),
                7: (_BURIED, "5h"),
                8: (_BURIED, "5s"),
                9: (_BURIED, "kh"),
            }
        ),
    ),
    PanelBoard(
        board_id="immediate-join",
        role="development",
        purpose="Column 5's 8c joins the 9c immediately and reveals that column. The same-suit spade run is a longer plan to the same reveal.",
        target_column=5,
        stock="2d",
        columns=_columns(
            {
                0: (_BURIED, "4s 3s"),
                1: (_BURIED, "5s"),
                2: (_BURIED, "kd"),
                3: (_BURIED, "kc"),
                4: (_BURIED, "kh"),
                5: ("ks", "8c"),
                6: (_BURIED, "9c"),
                7: (_BURIED, "ah"),
                8: (_BURIED, "ad"),
                9: (_BURIED, "ac"),
            }
        ),
    ),
    PanelBoard(
        board_id="symmetric-tie",
        role="development",
        purpose="3h can park on either 4. Both parks then reveal column 0 at the same corrected cost. The pilot keeps the baseline order.",
        target_column=0,
        stock="2d",
        columns=_columns(
            {
                0: ("ks", "8c 3h"),
                1: (_BURIED, "9c"),
                2: (_BURIED, "4d"),
                3: (_BURIED, "6c"),
                4: (_BURIED, "4s"),
                5: (_BURIED, "6d"),
                6: (_BURIED, "6h"),
                7: (_BURIED, "6s"),
                8: (_BURIED, "ah"),
                9: (_BURIED, "ad"),
            }
        ),
    ),
    PanelBoard(
        board_id="distractor-reveal",
        role="reserved",
        purpose="The objective is column 0 only. Queen onto the spade king reveals column 5 and adds a bond. Two 9c landings keep the club join from being a size-1 critical receiver.",
        target_column=0,
        stock="2d",
        columns=_columns(
            {
                0: ("ks", "8c 3h"),
                1: (_BURIED, "9c"),
                2: (_BURIED, "4d"),
                3: (_BURIED, "9c"),
                4: (_BURIED, "ac"),
                5: ("kd", "qs"),
                6: (_BURIED, "ks"),
                7: (_BURIED, "ad"),
                8: (_BURIED, "ah"),
                9: (_BURIED, "as"),
            }
        ),
    ),
    PanelBoard(
        board_id="three-deep-uncover",
        role="reserved",
        purpose="Column 0 is covered by 3h then 4d. Uncovering the 8c takes three moves. The diamond queen-king join is the competing bond.",
        target_column=0,
        stock="2d",
        columns=_columns(
            {
                0: ("7d", "8c 4d 3h"),
                1: ("7c", "9c"),
                2: ("7c", "4s"),
                3: ("7c", "5h"),
                4: ("7c", "qd"),
                5: ("7c", "kd"),
                6: ("7c", "ac"),
                7: ("7c", "ad"),
                8: ("7c", "ah"),
                9: ("7c", "as"),
            }
        ),
    ),
    PanelBoard(
        board_id="zero-cost-workspace",
        role="reserved",
        purpose=(
            "Workspace preparation. 10d onto jh is the move that creates the only empty column. "
            "kd then has a legal zero-cost whole-column move onto that empty. "
            "The same-suit 6s-7s join is the competing first move. "
            "No initial empty is present, because that shape admits at least nine legal tableau moves."
        ),
        target_column=0,
        stock="2c",
        columns=_columns(
            {
                0: ("7d", "8c 3h"),
                1: ("7c", "9c"),
                2: ("", "10d"),
                3: ("7c", "jh"),
                4: ("", "kd"),
                5: ("7c", "6s"),
                6: ("7c", "7s"),
                7: ("7c", "kh"),
                8: ("7c", "kc"),
                9: ("7c", "ks"),
            }
        ),
    ),
)


def panel_boards() -> Tuple[PanelBoard, ...]:
    return PANEL_BOARDS


def board_by_id(board_id: str) -> PanelBoard:
    for board in PANEL_BOARDS:
        if board.board_id == board_id:
            return board
    raise KeyError(board_id)


def development_boards() -> Tuple[PanelBoard, ...]:
    return tuple(board for board in PANEL_BOARDS if board.role == "development")


def reserved_boards() -> Tuple[PanelBoard, ...]:
    return tuple(board for board in PANEL_BOARDS if board.role == "reserved")


def build_state(board: PanelBoard) -> SpiderState:
    """Build the frozen partial deck. Face-up text is bottom-to-top."""

    if len(board.columns) != 10:
        raise ValueError(f"{board.board_id} must have 10 columns")
    columns = [
        Column(
            [Card.parse(token) for token in down.split() if token],
            [Card.parse(token) for token in up.split() if token],
        )
        for down, up in board.columns
    ]
    stock = [Card.parse(token) for token in board.stock.split() if token]
    return SpiderState(columns, stock, [])


def reveal_predicate(source: SpiderState, column: int) -> Callable[[SpiderState], bool]:
    """True when ``column`` has fewer face-down cards than ``source``.

    A reveal in another column, a bare join, and an empty column are not
    success. The caller chooses the column. This function does not name
    a fixture.
    """

    start = len(source.columns[column].face_down)

    def reached(state: SpiderState) -> bool:
        return len(state.columns[column].face_down) < start

    return reached
