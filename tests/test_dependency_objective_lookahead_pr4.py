"""Development tests for local-objective lookahead.

Reserved panel boards are not built or searched here. Their one-shot
evaluation happens only after the implementation checkpoint.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.dependency_objective_lookahead import compare_local_objective, compare_panel_board
from spider.dependency_objective_panel import (
    board_by_id,
    build_state,
    development_boards,
    reveal_predicate,
)
from spider.dependency_options import (
    build_option,
    rebuild_obligations,
    select_dependency_portfolio,
)
from spider.engine import Column, SpiderState
from spider.packed_state import pack_state
from spider.research_actions import apply_action, step_cost, tableau_actions
from spider.search_kernel import SearchLimits

_DEVELOPMENT = {
    "size-1-scarce-receiver": {
        "choice": "(0, 2, 1)",
        "baseline": "(0, 2, 1)",
        "rows": {
            "(0, 2, 1)": ("exact", 2, ((0, 1, 1),), "complete"),
            "(3, 1, 1)": ("exhausted-no-hit", None, (), "complete"),
        },
    },
    "size-2-alternative-receiver": {
        "choice": "(0, 2, 1)",
        "baseline": "(3, 1, 1)",
        "rows": {
            "(3, 1, 1)": ("exact", 3, ((0, 2, 1), (0, 4, 1)), "complete"),
            "(3, 4, 1)": ("exact", 3, ((0, 2, 1), (0, 1, 1)), "complete"),
            "(0, 2, 1)": ("exact", 2, ((0, 1, 1),), "complete"),
        },
    },
    "blocker-chain": {
        "choice": "(1, 2, 1)",
        "baseline": "(3, 4, 1)",
        "rows": {
            "(3, 4, 1)": ("exact", 3, ((1, 2, 1), (0, 1, 1)), "complete"),
            "(1, 2, 1)": ("exact", 2, ((0, 1, 1),), "complete"),
        },
    },
    "immediate-join": {
        "choice": "(5, 6, 1)",
        "baseline": "(0, 1, 2)",
        "rows": {
            "(0, 1, 2)": ("exact", 2, ((5, 6, 1),), "complete"),
            "(5, 6, 1)": ("exact", 1, (), "prefix-terminal"),
        },
    },
    "symmetric-tie": {
        "choice": "(0, 2, 1)",
        "baseline": "(0, 2, 1)",
        "rows": {
            "(0, 2, 1)": ("exact", 2, ((0, 1, 1),), "complete"),
            "(0, 4, 1)": ("exact", 2, ((0, 1, 1),), "complete"),
        },
    },
}


def _state(spec, stock="2d") -> SpiderState:
    columns = [
        Column(
            [Card.parse(token) for token in down.split() if token],
            [Card.parse(token) for token in up.split() if token],
        )
        for down, up in spec
    ]
    return SpiderState(columns, [Card.parse(stock)], [])


def _replay(state, actions):
    current = state.clone()
    total = 0
    for action in actions:
        total += int(step_cost(current, action))
        apply_action(current, action)
    return current, total


def _row(result, option_id):
    found = [row for row in result.candidates if row.option_id == option_id]
    assert len(found) == 1
    return found[0]


def _forbid_search():
    import spider.dependency_objective_lookahead as module

    def banned(*_args, **_kwargs):
        raise AssertionError("run_search was called")

    previous = module.run_search
    module.run_search = banned
    return module, previous


def test_lookahead_source_has_no_fixture_cards_or_second_kernel():
    source = (ROOT / "src" / "spider" / "dependency_objective_lookahead.py").read_text(encoding="utf-8")
    options = (ROOT / "src" / "spider" / "dependency_options.py").read_text(encoding="utf-8")
    assert "8c" not in source
    assert "9c" not in source
    assert "run_search" in source
    assert "discover_macros" not in source
    assert "kernel_lower_bound" not in source
    assert "lower_bound_fn" not in source
    assert "pack_post_stock_symmetry_state" not in source
    assert "all_legal_actions" not in source
    assert "4925153" not in source
    assert "8c" not in options
    assert "9c" not in options
    assert "run_search" not in options
    assert "discover_macros" not in options


def test_development_board_contrasts_and_unchanged_legal_sets():
    assert [board.board_id for board in development_boards()] == list(_DEVELOPMENT)
    for board in development_boards():
        expected = _DEVELOPMENT[board.board_id]
        state = build_state(board)
        result = compare_panel_board(board)
        legal = tuple(tableau_actions(state))
        assert result.status == "ranked"
        assert result.choice_id == expected["choice"]
        assert result.baseline_id == expected["baseline"]
        assert result.legal_actions == legal
        assert result.pruned == ()
        assert result.rejected_option_ids == ()
        assert result.obligations_status == "matched"
        assert result.absolute_g_used_for_proof is False
        assert result.baseline_seconds >= 0.0
        assert result.kernel_seconds >= 0.0
        assert result.overhead_seconds >= 0.0
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
            for action in legal
        )
        pick = select_dependency_portfolio(options, obligations, limit=len(options))
        assert [row.option_id for row in result.candidates] == [item.option_id for item in pick.chosen]
        assert len(result.candidates) == len(legal) <= 8
        predicate = reveal_predicate(state, board.target_column)
        start_down = len(state.columns[board.target_column].face_down)
        for option_id, (status, total, continuation, stop) in expected["rows"].items():
            row = _row(result, option_id)
            assert row.status == status
            assert row.total_cost == total
            assert row.continuation == continuation
            assert row.stop_reason == stop
            assert row.declared_source_g == 0
            reached, replayed = _replay(state, row.actions + row.continuation)
            if status == "exact":
                assert row.continuation_cost == replayed - row.prefix_cost
                assert replayed == total
                assert predicate(reached) is True
                assert len(reached.columns[board.target_column].face_down) == start_down - 1
                assert pack_state(reached).hex()
            else:
                assert row.total_cost is None
                assert row.continuation_cost is None
                assert predicate(reached) is False


def test_size_two_keeps_the_third_legal_move_and_the_two_move_plan():
    board = board_by_id("size-2-alternative-receiver")
    result = compare_panel_board(board)
    assert set(result.legal_actions) == {(0, 2, 1), (3, 1, 1), (3, 4, 1)}
    preserve = _row(result, "(0, 2, 1)")
    spend = _row(result, "(3, 1, 1)")
    third = _row(result, "(3, 4, 1)")
    assert preserve.total_cost == 2
    assert spend.total_cost == 3
    assert third.total_cost == 3
    assert result.choice_id == "(0, 2, 1)"
    assert result.baseline_id == "(3, 1, 1)"


def test_immediate_join_is_prefix_terminal_and_beats_the_longer_plan():
    result = compare_panel_board(board_by_id("immediate-join"))
    reveal = _row(result, "(5, 6, 1)")
    longer = _row(result, "(0, 1, 2)")
    assert reveal.kernel_called is False
    assert reveal.continuation == ()
    assert reveal.continuation_cost == 0
    assert reveal.total_cost == 1
    assert reveal.stop_reason == "prefix-terminal"
    assert longer.kernel_called is True
    assert longer.total_cost == 2
    assert result.choice_id == "(5, 6, 1)"
    assert result.baseline_id == "(0, 1, 2)"


def test_genuine_tie_keeps_the_baseline_order():
    result = compare_panel_board(board_by_id("symmetric-tie"))
    left = _row(result, "(0, 2, 1)")
    right = _row(result, "(0, 4, 1)")
    assert left.total_cost == right.total_cost == 2
    assert left.status == right.status == "exact"
    assert left.baseline_index < right.baseline_index
    assert result.choice_id == result.baseline_id == "(0, 2, 1)"


def test_another_column_reveal_is_not_the_target_objective():
    state = _state(
        (
            ("ks", "8c 3h"),
            ("ks", "9c"),
            ("ks", "4d"),
            ("ks", "kh"),
            ("ks", "kd"),
            ("kd", "qs"),
            ("ks", "ks"),
            ("ks", "kc"),
            ("ks", "ah"),
            ("ks", "ad"),
        )
    )
    legal = tableau_actions(state)
    assert set(legal) == {(0, 2, 1), (5, 3, 1), (5, 4, 1), (5, 6, 1), (5, 7, 1)}
    predicate = reveal_predicate(state, 0)
    queen_state, queen_cost = _replay(state, ((5, 6, 1),))
    assert queen_cost == 1
    assert predicate(queen_state) is False
    assert len(queen_state.columns[5].face_down) == 0
    assert len(queen_state.columns[0].face_down) == 1
    result = compare_local_objective(state, predicate)
    assert result.status == "ranked"
    assert result.legal_actions == tuple(legal)
    assert result.pruned == ()
    assert len(result.candidates) == 5
    target = _row(result, "(0, 2, 1)")
    assert target.total_cost == 2
    assert target.status == "exact"
    assert result.choice_id == "(0, 2, 1)"
    for action in ((5, 3, 1), (5, 4, 1), (5, 6, 1), (5, 7, 1)):
        row = _row(result, str(action))
        assert row.kernel_called is True
        assert row.status == "exact"
        assert row.total_cost == 3
        reached, _cost = _replay(state, row.actions + row.continuation)
        assert predicate(reached) is True
        assert len(reached.columns[0].face_down) == 0


def test_zero_cost_prefix_and_continuation_are_replayed_not_assumed():
    state = _state(
        (
            ("ks", "6c"),
            ("ks", "7c"),
            ("", ""),
            ("ks", "kh"),
            ("ks", "kd"),
            ("ks", "kc"),
            ("ks", "ks"),
            ("ks", "kh"),
            ("", "kh"),
            ("", "kd"),
        )
    )
    assert step_cost(state, (9, 2, 1)) == 0
    moved, _cost = _replay(state, ((9, 2, 1),))
    assert reveal_predicate(state, 0)(moved) is False
    assert len(moved.columns[0].face_down) == 1
    source_pack = pack_state(state)
    mid = state.clone()
    apply_action(mid, (8, 2, 1))
    mid_pack = pack_state(mid)
    predicate = lambda current, source_pack=source_pack, mid_pack=mid_pack: (
        pack_state(current) != source_pack and pack_state(current) != mid_pack
    )
    result = compare_local_objective(state, predicate)
    direct = _row(result, "(9, 2, 1)")
    assert direct.status == "exact"
    assert direct.kernel_called is False
    assert direct.prefix_cost == 0
    assert direct.continuation == ()
    assert direct.total_cost == 0
    setup = _row(result, "(8, 2, 1)")
    assert setup.status == "exact"
    assert setup.stop_reason == "complete"
    assert setup.kernel_called is True
    assert setup.first_g == 1
    assert setup.continuation == ((9, 8, 1),)
    assert setup.continuation_cost == 0
    assert setup.total_cost == 0
    assert setup.first_g != setup.prefix_cost + setup.continuation_cost
    reached, replayed = _replay(state, setup.actions + setup.continuation)
    assert replayed == 0
    assert step_cost(mid, setup.continuation[0]) == 0
    assert predicate(reached) is True
    assert result.legal_actions == tuple(tableau_actions(state))
    assert result.pruned == ()

    workspace = _state(
        (
            ("ks", "6c"),
            ("ks", "7c"),
            ("", "10d"),
            ("ks", "jh"),
            ("", "kd"),
            ("ks", "kh"),
            ("ks", "kc"),
            ("ks", "ks"),
            ("ks", "kh"),
            ("ks", "kd"),
        )
    )
    assert ("deal",) not in workspace.enumerate_legal_actions()
    assert workspace.can_deal() is False
    setup_action = (2, 3, 1)
    assert step_cost(workspace, setup_action) == 1
    after_setup = workspace.clone()
    apply_action(after_setup, setup_action)
    assert step_cost(after_setup, (4, 2, 1)) == 0
    start = pack_state(workspace)
    prepared = pack_state(after_setup)
    any_later = lambda current, start=start, prepared=prepared: (
        pack_state(current) != start and pack_state(current) != prepared
    )
    prepared_result = compare_local_objective(workspace, any_later)
    row = _row(prepared_result, "(2, 3, 1)")
    assert row.status == "exact"
    assert row.stop_reason == "complete"
    assert row.first_g == 2
    assert row.continuation == ((4, 2, 1),)
    assert row.continuation_cost == 0
    assert row.total_cost == 1
    finished, finished_cost = _replay(workspace, row.actions + row.continuation)
    assert finished_cost == 1
    assert any_later(finished) is True
    assert reveal_predicate(workspace, 0)(finished) is False
    assert len(finished.columns[0].face_down) == 1
    assert prepared_result.pruned == ()
    assert prepared_result.legal_actions == tuple(tableau_actions(workspace))


def test_declared_source_g_does_not_change_the_local_decision():
    board = board_by_id("size-2-alternative-receiver")
    state = build_state(board)
    obligations = rebuild_obligations(state)
    shifted_options = tuple(
        build_option(
            state,
            (action,),
            source_g=5,
            structural_name=str(action),
            option_id=str(action),
            obligations=obligations,
        )
        for action in tableau_actions(state)
    )
    assert all(option.source_g == 5 for option in shifted_options)
    assert all(option.target_g == option.source_g + option.cost for option in shifted_options)
    local = compare_panel_board(board)
    shifted = compare_local_objective(
        state,
        reveal_predicate(state, board.target_column),
        options=shifted_options,
    )
    assert shifted.choice_id == local.choice_id == "(0, 2, 1)"
    assert shifted.baseline_id == local.baseline_id == "(3, 1, 1)"
    assert shifted.absolute_g_used_for_proof is False
    for row in shifted.candidates:
        assert row.declared_source_g == 5
        assert row.total_cost == _row(local, row.option_id).total_cost
        assert row.status == _row(local, row.option_id).status


def test_forged_fields_different_source_and_stale_obligations_do_not_search():
    state = build_state(board_by_id("size-1-scarce-receiver"))
    other = build_state(board_by_id("symmetric-tie"))
    obligations = rebuild_obligations(state)
    genuine = tuple(
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
    forged = tuple(replace(option, target_bonds=option.target_bonds + 9) for option in genuine)
    module, previous = _forbid_search()
    try:
        refused = compare_local_objective(
            state,
            reveal_predicate(state, 0),
            options=forged,
        )
        foreign = tuple(
            build_option(
                other,
                (action,),
                source_g=0,
                structural_name=str(action),
                option_id=str(action),
                obligations=rebuild_obligations(other),
            )
            for action in tableau_actions(other)
        )
        mismatched = compare_local_objective(
            state,
            reveal_predicate(state, 0),
            options=foreign,
        )
        stale = compare_local_objective(
            state,
            reveal_predicate(state, 0),
            obligations=rebuild_obligations(other),
        )
        satisfied = compare_local_objective(state, lambda _current: True)
    finally:
        module.run_search = previous
    assert refused.status == "refused"
    assert refused.candidates == ()
    assert refused.choice_id is None
    assert refused.pruned == ()
    assert refused.legal_actions == tuple(tableau_actions(state))
    assert set(refused.rejected_option_ids) == {option.option_id for option in genuine}
    assert mismatched.status == "refused"
    assert mismatched.candidates == ()
    assert stale.status == "refused"
    assert stale.obligations_status == "refused"
    assert stale.candidates == ()
    assert satisfied.status == "already-satisfied"
    assert satisfied.candidates == ()

    mixed = (genuine[0], replace(genuine[1], target_bonds=genuine[1].target_bonds + 9))
    admitted = compare_local_objective(state, reveal_predicate(state, 0), options=mixed)
    assert admitted.status == "ranked"
    assert [row.option_id for row in admitted.candidates] == [genuine[0].option_id]
    assert admitted.rejected_option_ids == (genuine[1].option_id,)
    assert admitted.choice_id == genuine[0].option_id
    assert admitted.legal_actions == tuple(tableau_actions(state))
    assert admitted.pruned == ()


def test_unique_cap_is_unknown_and_keeps_the_baseline():
    board = board_by_id("symmetric-tie")
    limits = SearchLimits(
        max_unique=1,
        time_limit_s=2.0,
        rss_abort_mb=512.0,
        cost_ceiling=4,
        harvest_slack=None,
        max_depth=None,
        proof_ceiling=None,
    )
    result = compare_panel_board(board, limits=limits)
    assert result.status == "inconclusive"
    assert result.choice_id == result.baseline_id == "(0, 2, 1)"
    assert result.reason
    assert result.pruned == ()
    assert len(result.candidates) == 2
    for row in result.candidates:
        assert row.status == "unknown"
        assert row.total_cost is None
        assert row.continuation_cost is None
        assert row.kernel_called is True
        assert row.stop_reason == "unique limit"
    assert all(row.total_cost != 0 for row in result.candidates)
