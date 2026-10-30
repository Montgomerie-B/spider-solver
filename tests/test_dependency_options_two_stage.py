"""Synthetic two-stage dependency options.

The board is a fixture, not a deal row and not a 171 game. Column 3 keeps
the king under the competing club so spending that club does not open an
empty column. The module under test does not contain these card literals.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.dependency_options import (
    OptionContractError,
    build_option,
    dependency_penalty_of,
    kernel_lower_bound,
    prefer_option_actions,
    rebuild_obligations,
    select_dependency_portfolio,
)
from spider.engine import Column, SpiderState
from spider.human_strategy.evaluation import admissible_remaining, same_suit_bonds
from spider.packed_state import pack_state, permute_tableau_columns, unpack_state
from spider.research_actions import (
    apply_action,
    empty_column_indices,
    face_down_count,
    step_cost,
    tableau_actions,
)
from spider.search_kernel import SearchLimits, run_search


def _cards(text: str):
    return [Card.parse(token) for token in text.split() if token]


def _board(column4: str = "ks") -> SpiderState:
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
    columns = [
        Column(
            _cards("4d" if index == 0 else ""),
            _cards(face_up[index]),
        )
        for index in range(10)
    ]
    return SpiderState(columns, _cards("ad"), [])


def face_up(state, index):
    return tuple((card.rank, card.suit) for card in state.columns[index].face_up)


def apply_replay(state, actions):
    clone = state.clone()
    for action in actions:
        apply_action(clone, action)
    return clone


def _named_options(state):
    obligations = rebuild_obligations(state)
    preserve = build_option(
        state,
        ((0, 2, 1),),
        source_g=0,
        structural_name="preserve-receiver",
        obligations=obligations,
        provenance="synthetic-fixture",
    )
    spend = build_option(
        state,
        ((3, 1, 1),),
        source_g=0,
        structural_name="spend-only-receiver",
        obligations=obligations,
        provenance="synthetic-fixture",
    )
    return obligations, (preserve, spend)


def test_size_one_preserves_the_only_receiver():
    source = _board()
    obligations, options = _named_options(source)
    preserve, spend = options
    obligation_ids = {node.obligation_id for node in obligations}
    assert "join:c:8:col0" in obligation_ids
    assert "join:c:8:col3" in obligation_ids
    assert "reveal:col0:depth0" in obligation_ids

    assert tuple((card.rank, card.suit) for card in source.columns[0].face_down) == ((4, "d"),)
    assert face_up(source, 0) == ((8, "c"), (3, "h"))
    assert face_up(source, 1) == ((9, "c"),)
    assert face_up(source, 2) == ((4, "d"),)
    assert face_up(source, 3) == ((13, "d"), (8, "c"))
    assert source.columns[3].face_down == []
    assert [face_up(source, index) for index in range(4, 10)] == [
        ((13, "s"),),
        ((13, "h"),),
        ((13, "d"),),
        ((13, "c"),),
        ((13, "s"),),
        ((13, "h"),),
    ]
    assert len(source.stock) == 1
    assert (source.stock[0].rank, source.stock[0].suit) == (1, "d")
    assert source.can_deal() is False
    assert len(source.foundations) == 0
    assert face_down_count(source) == 1
    assert same_suit_bonds(source) == 0
    assert empty_column_indices(source) == ()
    assert admissible_remaining(source) == 8
    assert set(tableau_actions(source)) == {(0, 2, 1), (3, 1, 1)}
    assert step_cost(source, (0, 2, 1)) == 1
    assert step_cost(source, (3, 1, 1)) == 1
    assert (3, 1, 1) in tableau_actions(source)

    assert preserve.actions == ((0, 2, 1),)
    assert preserve.cost == 1
    assert preserve.target_bonds == 0
    assert preserve.enables == ("join:c:8:col0", "reveal:col0:depth0")
    assert preserve.broken_dependencies == ()
    assert preserve.blocks == ()
    assert preserve.dependency_penalty == 0
    assert preserve.f_target == preserve.target_g + preserve.h_target
    assert preserve.finishability_proof is False
    assert preserve.replay_ok is True
    assert preserve.independent_cold_complete is False
    assert preserve.source_symmetry is None
    assert (0, 1, 1) not in preserve.actions

    after_preserve = apply_replay(source, ((0, 2, 1),))
    assert same_suit_bonds(after_preserve) == 0
    assert empty_column_indices(after_preserve) == ()
    assert face_down_count(after_preserve) == 1
    assert set(tableau_actions(after_preserve)) == {(0, 1, 1), (3, 1, 1)}
    assert step_cost(after_preserve, (0, 1, 1)) == 1
    assert step_cost(after_preserve, (3, 1, 1)) == 1
    assert admissible_remaining(after_preserve) == 8
    assert preserve.h_target == admissible_remaining(after_preserve)
    assert dependency_penalty_of(source, after_preserve, preserve) == 0

    after_join = apply_replay(after_preserve, ((0, 1, 1),))
    assert step_cost(source, (0, 2, 1)) + step_cost(after_preserve, (0, 1, 1)) == 2
    assert after_join.last_move[3] is True
    assert face_down_count(after_join) == 0
    assert len(after_join.foundations) == 0
    assert same_suit_bonds(after_join) == 1
    assert face_up(after_join, 0) == ((4, "d"),)
    assert face_up(after_join, 1) == ((9, "c"), (8, "c"))
    assert set(tableau_actions(after_join)) == {(2, 0, 1)}
    assert step_cost(after_join, (2, 0, 1)) == 1
    assert admissible_remaining(after_join) == 8

    assert spend.actions == ((3, 1, 1),)
    assert spend.cost == 1
    assert spend.target_bonds == 1
    assert spend.broken_dependencies == ("join:c:8:col0", "reveal:col0:depth0")
    assert spend.blocks == ("join:c:8:col0", "reveal:col0:depth0")
    assert spend.enables == ()
    assert spend.dependency_penalty == 4  # 2 + 0 + 2, ranking only
    assert "join:c:8:col3" not in spend.blocks
    assert "join:c:8:col3" not in spend.broken_dependencies
    assert spend.f_target == spend.target_g + spend.h_target
    assert spend.replay_ok is True
    assert dependency_penalty_of(source, apply_replay(source, spend.actions), spend) == 4

    after_spend = apply_replay(source, ((3, 1, 1),))
    assert step_cost(source, (3, 1, 1)) == 1
    assert same_suit_bonds(after_spend) == 1
    assert empty_column_indices(after_spend) == ()
    assert face_up(after_spend, 3) == ((13, "d"),)
    assert face_up(after_spend, 1) == ((9, "c"), (8, "c"))
    assert set(tableau_actions(after_spend)) == {(0, 2, 1)}
    assert step_cost(after_spend, (0, 2, 1)) == 1
    assert admissible_remaining(after_spend) == 8
    assert spend.h_target == admissible_remaining(after_spend)

    after_spend_then_blocker = apply_replay(after_spend, ((0, 2, 1),))
    assert step_cost(source, (3, 1, 1)) + step_cost(after_spend, (0, 2, 1)) == 2
    assert empty_column_indices(after_spend_then_blocker) == ()
    assert face_down_count(after_spend_then_blocker) == 1
    assert same_suit_bonds(after_spend_then_blocker) == 1
    assert tableau_actions(after_spend_then_blocker) == []
    assert after_spend_then_blocker.can_move(0, 1, 1) is False
    assert after_spend_then_blocker.can_move(0, 3, 1) is False
    assert admissible_remaining(after_spend_then_blocker) == 8
    assert spend.actions == ((3, 1, 1),)

    pick = select_dependency_portfolio(options, obligations, limit=2)
    assert pick.chosen[0].option_id == "preserve-receiver"
    assert pick.chosen[0].actions == ((0, 2, 1),)
    assert pick.chosen[0].cost == 1
    assert pick.chosen[0].dependency_penalty == 0
    assert pick.chosen[0].f_target == pick.chosen[0].target_g + pick.chosen[0].h_target
    assert pick.chosen[1].option_id == "spend-only-receiver"
    assert pick.omitted_not_proved_impossible is False
    assert pick.diverse_ancestor_available is False
    assert kernel_lower_bound(source, 0) == admissible_remaining(source)
    assert kernel_lower_bound(after_preserve, 1) == admissible_remaining(after_preserve)
    assert kernel_lower_bound(after_spend, 1) == admissible_remaining(after_spend)

    reserved = select_dependency_portfolio(options, obligations, limit=1)
    assert reserved.chosen[0].option_id == "preserve-receiver"
    assert reserved.omitted_not_proved_impossible is True
    assert (3, 1, 1) in tableau_actions(source)
    assert pack_state(source).hex() == preserve.source_pack


def test_size_two_allows_the_bond_when_another_receiver_remains():
    source_or = _board("9c")
    obligations_or, options_or = _named_options(source_or)
    preserve_or, spend_or = options_or

    assert face_up(source_or, 4) == ((9, "c"),)
    assert face_up(source_or, 3) == ((13, "d"), (8, "c"))
    assert same_suit_bonds(source_or) == 0
    assert empty_column_indices(source_or) == ()
    assert admissible_remaining(source_or) == 8
    assert set(tableau_actions(source_or)) == {(0, 2, 1), (3, 1, 1), (3, 4, 1)}
    assert step_cost(source_or, (0, 2, 1)) == 1
    assert step_cost(source_or, (3, 1, 1)) == 1
    assert step_cost(source_or, (3, 4, 1)) == 1
    assert (3, 1, 1) in tableau_actions(source_or)
    assert (3, 4, 1) in tableau_actions(source_or)
    assert all((3, 4, 1) not in option.actions for option in options_or)

    assert preserve_or.actions == ((0, 2, 1),)
    assert preserve_or.cost == 1
    assert preserve_or.target_bonds == 0
    assert preserve_or.enables == ("join:c:8:col0", "reveal:col0:depth0")
    assert preserve_or.blocks == ()
    assert preserve_or.dependency_penalty == 0
    assert preserve_or.f_target == preserve_or.target_g + preserve_or.h_target

    assert spend_or.actions == ((3, 1, 1),)
    assert spend_or.cost == 1
    assert spend_or.target_bonds == 1
    assert spend_or.broken_dependencies == ()
    assert spend_or.blocks == ()
    assert spend_or.enables == ()
    assert spend_or.dependency_penalty == 0
    assert "join:c:8:col3" not in spend_or.blocks
    assert spend_or.f_target == spend_or.target_g + spend_or.h_target
    assert dependency_penalty_of(source_or, apply_replay(source_or, spend_or.actions), spend_or) == 0

    after_spend_or = apply_replay(source_or, ((3, 1, 1),))
    assert empty_column_indices(after_spend_or) == ()
    assert same_suit_bonds(after_spend_or) == 1
    assert face_up(after_spend_or, 4) == ((9, "c"),)
    assert set(tableau_actions(after_spend_or)) == {(0, 2, 1), (1, 4, 1)}
    assert step_cost(after_spend_or, (0, 2, 1)) == 1
    assert step_cost(after_spend_or, (1, 4, 1)) == 1
    assert admissible_remaining(after_spend_or) == 8

    after_or_block = apply_replay(after_spend_or, ((0, 2, 1),))
    assert empty_column_indices(after_or_block) == ()
    assert same_suit_bonds(after_or_block) == 1
    assert face_down_count(after_or_block) == 1
    assert set(tableau_actions(after_or_block)) == {(0, 4, 1), (1, 4, 1)}
    assert step_cost(after_or_block, (0, 4, 1)) == 1
    assert step_cost(after_or_block, (1, 4, 1)) == 1
    assert after_or_block.can_move(0, 1, 1) is False
    assert after_or_block.can_move(0, 3, 1) is False
    assert after_or_block.can_move(0, 4, 1) is True
    assert admissible_remaining(after_or_block) == 8

    after_or_reveal = apply_replay(after_or_block, ((0, 4, 1),))
    assert (
        step_cost(source_or, (3, 1, 1))
        + step_cost(after_spend_or, (0, 2, 1))
        + step_cost(after_or_block, (0, 4, 1))
    ) == 3
    assert after_or_reveal.last_move[3] is True
    assert face_down_count(after_or_reveal) == 0
    assert len(after_or_reveal.foundations) == 0
    assert same_suit_bonds(after_or_reveal) == 2
    assert admissible_remaining(after_or_reveal) == 8

    after_preserve_or = apply_replay(source_or, ((0, 2, 1),))
    assert set(tableau_actions(after_preserve_or)) == {(0, 1, 1), (0, 4, 1), (3, 1, 1), (3, 4, 1)}
    assert all(step_cost(after_preserve_or, action) == 1 for action in tableau_actions(after_preserve_or))
    assert admissible_remaining(after_preserve_or) == 8

    pick_or = select_dependency_portfolio(options_or, obligations_or, limit=2)
    assert pick_or.chosen[0].option_id == "spend-only-receiver"
    assert pick_or.chosen[0].actions == ((3, 1, 1),)
    assert pick_or.chosen[0].cost == 1
    assert pick_or.chosen[0].target_bonds == 1
    assert pick_or.chosen[0].dependency_penalty == 0
    assert pick_or.chosen[0].f_target == pick_or.chosen[0].target_g + pick_or.chosen[0].h_target
    assert pick_or.chosen[1].option_id == "preserve-receiver"
    assert kernel_lower_bound(source_or, 0) == admissible_remaining(source_or)
    assert kernel_lower_bound(after_preserve_or, 1) == admissible_remaining(after_preserve_or)
    assert kernel_lower_bound(after_spend_or, 1) == admissible_remaining(after_spend_or)


def test_ordered_identity_and_preference_do_not_drop_moves():
    source = _board()
    _obligations, options = _named_options(source)
    preserve, spend = options
    swapped = permute_tableau_columns(source, (1, 0, 2, 3, 4, 5, 6, 7, 8, 9))
    assert source.stock
    assert pack_state(source) != pack_state(swapped)

    generated = tableau_actions(source)
    preferred = prefer_option_actions(source, generated, preserve)
    assert preferred[0] == (0, 2, 1)
    assert set(preferred) == set(generated)
    assert (0, 1, 1) not in preferred
    assert len(preferred) == len(generated)

    unchanged = prefer_option_actions(source, [(3, 1, 1)], preserve)
    assert unchanged == [(3, 1, 1)]

    spend_first = prefer_option_actions(source, generated, spend)
    assert spend_first[0] == (3, 1, 1)
    assert set(spend_first) == set(generated)

    try:
        build_option(
            source,
            ((0, 1, 1),),
            source_g=0,
            structural_name="buried-block",
            obligations=rebuild_obligations(source),
        )
    except OptionContractError:
        rejected = True
    else:
        rejected = False
    assert rejected is True
    assert set(tableau_actions(source)) == {(0, 2, 1), (3, 1, 1)}


def test_kernel_records_every_legal_source_move():
    source = _board()
    source_or = _board("9c")
    recorded = []

    def actions_fn(state):
        acts = tableau_actions(state)
        recorded.append(tuple(acts))
        return acts

    def action_order(state, actions):
        del state
        preferred = (0, 2, 1)
        if preferred not in actions:
            return list(actions)
        rest = [action for action in actions if action != preferred]
        return [preferred, *rest]

    run_search(
        [{"ordered_digest": pack_state(source).hex(), "g": 0}],
        limits=SearchLimits(
            max_unique=20,
            time_limit_s=2.0,
            rss_abort_mb=512,
            cost_ceiling=None,
            proof_ceiling=50,
        ),
        identity_fn=pack_state,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        actions_fn=actions_fn,
        action_order=action_order,
        lower_bound_fn=kernel_lower_bound,
        stop_on_first_terminal=False,
    )
    assert set(recorded[0]) == {(0, 2, 1), (3, 1, 1)}
    assert (3, 1, 1) in recorded[0]
    assert (0, 2, 1) in recorded[0]

    recorded_or = []

    def actions_fn_or(state):
        acts = tableau_actions(state)
        recorded_or.append(tuple(acts))
        return acts

    run_search(
        [{"ordered_digest": pack_state(source_or).hex(), "g": 0}],
        limits=SearchLimits(
            max_unique=20,
            time_limit_s=2.0,
            rss_abort_mb=512,
            cost_ceiling=None,
            proof_ceiling=50,
        ),
        identity_fn=pack_state,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        actions_fn=actions_fn_or,
        action_order=action_order,
        lower_bound_fn=kernel_lower_bound,
        stop_on_first_terminal=False,
    )
    assert set(recorded_or[0]) == {(0, 2, 1), (3, 1, 1), (3, 4, 1)}
