"""Static checks for the inventory-valid motif sources.

No lookahead is imported or run. The scripted replays use the engine's
own costing to show that each constructed mechanism still reaches, or
deliberately does not reach, its target column.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.dependency_objective_inventory import (
    COMPARISON_BUDGET,
    CONSTRUCTION_RULE,
    DECK_LABEL,
    FACE_DOWN_CAP,
    FACE_DOWN_TOTAL_CAP,
    MECHANISM_REPLAYS,
    OPENING_REACHABILITY,
    build_state,
    inventory_shape_failures,
    inventory_sources,
)
from spider.dependency_objective_panel import (
    COMPARISON_BUDGET as PANEL_BUDGET,
    build_state as build_panel_state,
    panel_boards,
    reveal_predicate,
)
from spider.packed_state import pack_state, unpack_state
from spider.research_actions import apply_action, step_cost, tableau_actions

_ABSTRACT_SIX = (
    "blocker-chain",
    "immediate-join",
    "symmetric-tie",
    "distractor-reveal",
    "three-deep-uncover",
    "zero-cost-workspace",
)

_FOUNDATIONS = {
    "blocker-chain": ("s", "h", "d", "c"),
    "immediate-join": ("s", "h", "d", "c"),
    "symmetric-tie": ("s", "h", "d", "c"),
    "distractor-reveal": ("s", "h", "d"),
    "three-deep-uncover": ("s", "h", "d", "c"),
    "zero-cost-workspace": ("s", "h", "d", "c"),
}

_INERT = {
    "blocker-chain": ((5, "Ks"), (6, "Kh"), (7, "Kd"), (8, "Kc"), (9, "7s")),
    "immediate-join": ((2, "Ks"), (3, "Kh"), (4, "Kd"), (7, "Kc"), (8, "Js"), (9, "Jh")),
    "symmetric-tie": ((3, "Ks"), (5, "Kh"), (6, "Kd"), (7, "Kc"), (8, "Js"), (9, "Jh")),
    "distractor-reveal": ((4, "9s"), (7, "9h"), (8, "9d"), (9, "7s")),
    "three-deep-uncover": ((6, "9s"), (7, "9h"), (8, "9d"), (9, "7s")),
    "zero-cost-workspace": ((7, "Ks"), (8, "Kh"), (9, "Kc")),
}


def test_manifest_labels_budget_and_no_search_in_the_fixture():
    sources = inventory_sources()
    assert [source.source_id for source in sources] == list(_ABSTRACT_SIX)
    assert DECK_LABEL == "constructed_inventory_valid"
    assert OPENING_REACHABILITY == "unestablished"
    assert CONSTRUCTION_RULE == "spine-plus-inert-top-and-foundation-sink"
    assert COMPARISON_BUDGET is PANEL_BUDGET
    assert COMPARISON_BUDGET["max_unique"] == 20
    assert COMPARISON_BUDGET["time_limit_s"] == 2.0
    assert COMPARISON_BUDGET["rss_abort_mb"] == 512.0
    assert COMPARISON_BUDGET["cost_ceiling"] == 4
    assert COMPARISON_BUDGET["max_depth"] is None
    assert COMPARISON_BUDGET["workers"] == 1
    assert COMPARISON_BUDGET["stop_on_first_terminal"] is False
    assert COMPARISON_BUDGET["harvest_slack"] is None
    text = (ROOT / "src" / "spider" / "dependency_objective_inventory.py").read_text(encoding="utf-8")
    assert "compare_local_objective" not in text
    assert "run_search" not in text
    helper = inspect.getsource(inventory_shape_failures)
    assert "can_move" not in helper
    assert "enumerate_legal" not in helper
    assert "enumerate_moves" not in helper
    assert "tableau_actions" not in helper


def test_each_source_has_a_full_two_deck_inventory():
    for source in inventory_sources():
        state = build_state(source)
        assert inventory_shape_failures(state) == ()
        assert len(state.stock) == 0
        assert state.can_deal() is False
        assert source.foundation_suits == _FOUNDATIONS[source.source_id]
        assert source.inert_tops == _INERT[source.source_id]
        assert len(state.columns[source.target_column].face_down) == 1
        occupied = [index for index, count in enumerate(source.body_counts) if count]
        unprotected = [
            index
            for index in range(10)
            if index != source.target_column and index not in source.free_columns
        ]
        assert occupied == [unprotected[0]]
        assert source.face_up[source.target_column] == source.mechanism[source.target_column]
        for index, text in enumerate(source.face_down):
            expected = 0 if index in source.free_columns else 1
            assert len(text.split()) == expected
            assert len(state.columns[index].face_down) <= FACE_DOWN_CAP[index]
        assert sum(len(column.face_down) for column in state.columns) <= FACE_DOWN_TOTAL_CAP
        unpacked = unpack_state(pack_state(state))
        assert pack_state(unpacked) == pack_state(state)


def test_legal_sets_match_the_engine_and_stay_inside_eight():
    expected = {source.source_id: source.legal_actions for source in inventory_sources()}
    assert expected["blocker-chain"] == ((1, 2, 1), (3, 4, 1))
    assert expected["immediate-join"] == ((0, 1, 2), (5, 6, 1))
    assert expected["symmetric-tie"] == ((0, 2, 1), (0, 4, 1))
    assert expected["distractor-reveal"] == ((0, 2, 1), (5, 6, 1))
    assert expected["three-deep-uncover"] == ((0, 2, 1), (2, 3, 1), (4, 5, 1))
    assert expected["zero-cost-workspace"] == ((1, 2, 1), (2, 3, 1), (5, 6, 1))
    baselines = {source.source_id: source.baseline_id for source in inventory_sources()}
    assert baselines == {
        "blocker-chain": "(3, 4, 1)",
        "immediate-join": "(0, 1, 2)",
        "symmetric-tie": "(0, 2, 1)",
        "distractor-reveal": "(5, 6, 1)",
        "three-deep-uncover": "(4, 5, 1)",
        "zero-cost-workspace": "(5, 6, 1)",
    }
    for source in inventory_sources():
        state = build_state(source)
        legal = tuple(state.enumerate_legal_actions())
        tableau = tuple(tableau_actions(state))
        assert ("deal",) not in legal
        assert legal == tableau == source.legal_actions
        assert 1 <= len(tableau) <= 8


def test_scripted_mechanism_replays_use_engine_costs():
    for source in inventory_sources():
        state = build_state(source)
        predicate = reveal_predicate(state, source.target_column)
        assert predicate(state) is False
        cases = MECHANISM_REPLAYS[source.source_id]
        assert cases
        for case in cases:
            current = state.clone()
            flags = []
            costs = []
            for action in case.actions:
                assert action in tableau_actions(current)
                costs.append(step_cost(current, action))
                apply_action(current, action)
                flags.append(predicate(current))
            assert tuple(costs) == case.costs
            assert flags == [False] * (len(case.actions) - 1) + [case.revealed_at_end]


def test_original_six_abstract_fixtures_fail_the_inventory_check():
    seen = set()
    for board in panel_boards():
        if board.board_id not in _ABSTRACT_SIX:
            continue
        seen.add(board.board_id)
        state = build_panel_state(board)
        failures = inventory_shape_failures(state)
        assert any(item.startswith("card-count:") for item in failures)
        assert any(item.startswith("stock:") for item in failures)
        assert "two-copy" in failures
    assert seen == set(_ABSTRACT_SIX)
