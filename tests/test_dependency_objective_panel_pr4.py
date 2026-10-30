"""Integrity of the frozen PR4 panel. No lookahead is imported or run."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.dependency_objective_panel import (
    COMPARISON_BUDGET,
    DECK_LABEL,
    PANEL_BOARDS,
    build_state,
    development_boards,
    panel_boards,
    reserved_boards,
    reveal_predicate,
)
from spider.dependency_options import (
    build_option,
    rebuild_obligations,
    select_dependency_portfolio,
)
from spider.packed_state import pack_state, unpack_state
from spider.research_actions import tableau_actions

_BASELINE = {
    "size-1-scarce-receiver": "(0, 2, 1)",
    "size-2-alternative-receiver": "(3, 1, 1)",
    "blocker-chain": "(3, 4, 1)",
    "immediate-join": "(0, 1, 2)",
    "symmetric-tie": "(0, 2, 1)",
    "distractor-reveal": "(5, 6, 1)",
    "three-deep-uncover": "(4, 5, 1)",
    "zero-cost-workspace": "(5, 6, 1)",
}

_ACTIONS = {
    "size-1-scarce-receiver": {(0, 2, 1), (3, 1, 1)},
    "size-2-alternative-receiver": {(0, 2, 1), (3, 1, 1), (3, 4, 1)},
    "blocker-chain": {(1, 2, 1), (3, 4, 1)},
    "immediate-join": {(0, 1, 2), (5, 6, 1)},
    "symmetric-tie": {(0, 2, 1), (0, 4, 1)},
    "distractor-reveal": {(0, 2, 1), (5, 6, 1)},
    "three-deep-uncover": {(0, 2, 1), (2, 3, 1), (4, 5, 1)},
    "zero-cost-workspace": {(1, 2, 1), (2, 3, 1), (5, 6, 1)},
}


def test_panel_shape_budget_and_split():
    boards = panel_boards()
    assert boards == PANEL_BOARDS
    assert len(boards) == 8
    assert len(development_boards()) == 5
    assert len(reserved_boards()) == 3
    new_boards = [board for board in boards if not board.board_id.startswith("size-")]
    assert len(new_boards) == 6
    assert [board.role for board in new_boards].count("development") == 3
    assert [board.role for board in new_boards].count("reserved") == 3
    assert COMPARISON_BUDGET["max_unique"] == 20
    assert COMPARISON_BUDGET["time_limit_s"] == 2.0
    assert COMPARISON_BUDGET["rss_abort_mb"] == 512.0
    assert COMPARISON_BUDGET["cost_ceiling"] == 4
    assert COMPARISON_BUDGET["max_depth"] is None
    assert COMPARISON_BUDGET["workers"] == 1
    assert COMPARISON_BUDGET["stop_on_first_terminal"] is False
    assert COMPARISON_BUDGET["harvest_slack"] is None
    source = Path(build_state.__code__.co_filename).read_text(encoding="utf-8")
    assert "run_search" not in source
    assert "discover_macros" not in source


def test_every_board_is_a_partial_deck_without_a_legal_deal():
    seen = set()
    for board in panel_boards():
        assert board.board_id not in seen
        seen.add(board.board_id)
        assert board.role in ("development", "reserved")
        state = build_state(board)
        assert len(state.stock) == 1
        assert state.can_deal() is False
        legal = state.enumerate_legal_actions()
        tableau = tableau_actions(state)
        assert ("deal",) not in legal
        assert set(legal) == set(tableau)
        assert 1 <= len(tableau) <= 8
        assert set(tableau) == _ACTIONS[board.board_id]
        assert len(state.columns[board.target_column].face_down) >= 1
        assert sum(len(column.face_down) + len(column.face_up) for column in state.columns) + len(state.stock) < 104
        unpacked = unpack_state(pack_state(state))
        assert pack_state(unpacked) == pack_state(state)
        predicate = reveal_predicate(state, board.target_column)
        assert predicate(state) is False


def test_unchanged_selector_order_is_part_of_the_manifest():
    for board in panel_boards():
        state = build_state(board)
        obligations = rebuild_obligations(state)
        options = tuple(
            build_option(
                state,
                (action,),
                source_g=0,
                structural_name=str(action),
                option_id=str(action),
                obligations=obligations,
            )
            for action in tableau_actions(state)
        )
        pick = select_dependency_portfolio(options, obligations, limit=len(options))
        assert pick.obligations_status == "matched"
        assert pick.chosen
        assert pick.chosen[0].option_id == _BASELINE[board.board_id]
        assert len(pick.chosen) == len(options)


def test_deck_label_stays_honest():
    assert DECK_LABEL == "partial-synthetic"
