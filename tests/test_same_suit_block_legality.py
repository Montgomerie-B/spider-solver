"""Regression tests for Spider's same-suit multi-card movement rule."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner.committed_excavation import project_tt_key
from spider.planner.diagnostics.same_suit_block_legality_audit import (
    audit_machine_prefixes,
    audit_queen_variants,
)
from spider.planner.diagnostics.opt012_free_quotient import (
    free_slot_analysis,
    is_free_relocation,
)
from spider.planner.workspace_tactics import workspace_quotient_key
from spider.solution_archive import validate_solution


def _columns(*face_up_columns):
    columns = [Column([], list(cards)) for cards in face_up_columns]
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return columns


def _card(suit: str, rank: int) -> Card:
    return Card(suit, rank)


def test_one_mixed_suit_card_can_move_onto_rank_plus_one():
    state = SpiderState(
        _columns([_card("d", 7)], [_card("c", 8)]),
        [],
    )
    assert state.can_move(0, 1, 1)
    assert state.move(0, 1, 1) == 1


def test_descending_same_suit_two_card_block_is_legal():
    state = SpiderState(
        _columns([_card("d", 7), _card("d", 6)], [_card("c", 8)]),
        [],
    )
    assert state.can_move(0, 1, 2)


def test_descending_mixed_suit_two_card_block_is_illegal():
    state = SpiderState(
        _columns([_card("d", 7), _card("c", 6)], [_card("h", 8)]),
        [],
    )
    assert not state.can_move(0, 1, 2)


def test_longer_same_suit_descending_block_is_legal():
    state = SpiderState(
        _columns(
            [_card("h", rank) for rank in (9, 8, 7, 6)],
            [_card("d", 10)],
        ),
        [],
    )
    assert state.can_move(0, 1, 4)


def test_longer_descending_block_with_one_suit_break_is_illegal():
    state = SpiderState(
        _columns(
            [
                _card("h", 9),
                _card("h", 8),
                _card("s", 7),
                _card("s", 6),
            ],
            [_card("d", 10)],
        ),
        [],
    )
    assert not state.can_move(0, 1, 4)


def test_enumerate_moves_never_emits_mixed_suit_multicard_block():
    state = SpiderState(
        _columns(
            [
                _card("h", 9),
                _card("h", 8),
                _card("s", 7),
                _card("s", 6),
            ],
            [_card("d", 10)],
            [_card("c", 8)],
        ),
        [],
    )
    moves = state.enumerate_moves()
    assert moves
    for src, _dst, k in moves:
        run = state.columns[src].face_up[-k:]
        assert k == 1 or state.is_same_suit(run)


def test_replay_rejects_illegal_mixed_suit_block():
    state = SpiderState(
        _columns([_card("d", 7), _card("c", 6)], [_card("h", 8)]),
        [],
    )
    with pytest.raises(ValueError, match="illegal move"):
        replay_actions(state, [(0, 1, 2)])


def test_automatic_king_to_ace_removal_still_requires_same_suit():
    same = SpiderState(
        _columns(
            [_card("h", 1)],
            [_card("h", rank) for rank in range(13, 1, -1)],
        ),
        [],
    )
    same.move(0, 1, 1)
    assert len(same.foundations) == 1
    assert all(card.suit == "h" for card in same.foundations[0])

    mixed_run = [_card("h", rank) for rank in range(13, 1, -1)]
    mixed_run[6] = _card("c", mixed_run[6].rank)
    mixed = SpiderState(
        _columns([_card("h", 1)], mixed_run),
        [],
    )
    mixed.move(0, 1, 1)
    assert mixed.foundations == []


def test_legal_whole_column_to_empty_move_remains_free():
    state = SpiderState(
        _columns([_card("d", 7), _card("d", 6)], []),
        [],
    )
    assert state.can_move(0, 1, 2)
    assert state.move(0, 1, 2) == 0
    assert state.columns[0].is_empty()


def test_mixed_suit_full_column_cannot_move_to_empty_as_block():
    state = SpiderState(
        _columns([_card("d", 7), _card("c", 6)], []),
        [],
    )
    assert not state.can_move(0, 1, 2)
    with pytest.raises(ValueError, match="illegal move"):
        state.move(0, 1, 2)


def test_mixed_open_pile_is_not_a_free_quotient_entity():
    pile = [_card("d", 7), _card("c", 6)]
    a = SpiderState(_columns(pile, []), [])
    b = SpiderState(_columns([], pile), [])

    analysis = free_slot_analysis(a)
    assert 0 in analysis["fixed_indices"]
    assert 0 not in analysis["free_indices"]
    assert not is_free_relocation(a, (0, 1, 2))
    assert workspace_quotient_key(a) != workspace_quotient_key(b)


def test_committed_project_quotient_keeps_mixed_open_pile_fixed():
    pile = [_card("d", 7), _card("c", 6)]
    target = [_card("h", 9)]
    a = SpiderState(_columns(pile, [], target), [])
    b = SpiderState(_columns([], pile, target), [])
    assert project_tt_key(a, 2) != project_tt_key(b, 2)


def test_canonical_solution_remains_legal_and_solved():
    result = validate_solution(
        "4925153", ROOT / "solutions" / "4925153_canonical.moves"
    )
    assert result.valid and result.solved
    assert result.mobilityware_moves == 172
    assert result.foundations == 8
    assert result.stock_remaining == 0
    assert result.path_hash == "77d169da2538ba8c"


def test_published_machine_prefixes_fail_at_derived_suit_break():
    cards = tuple(load_deal(ROOT / "deals" / "4925153.txt"))
    results = audit_machine_prefixes(cards)
    assert tuple(result.valid for result in results) == (
        True,
        True,
        True,
        False,
        False,
        False,
    )
    for result in results[3:]:
        assert result.corrected_cost == 13
        assert result.first_illegal_command == 14
        assert result.first_illegal_action == (7, 6, 2)
        assert result.cards_moved == ("7d", "6c")
        assert "suit break" in result.reason


def test_queen_placement_variants_are_legal_and_deal1_replayable():
    cards = tuple(load_deal(ROOT / "deals" / "4925153.txt"))
    a, b = audit_queen_variants(cards)
    variants = (a, b)
    assert all(result.legal for result in variants)
    assert a.immediate_added_cost == b.immediate_added_cost == 3
    assert a.projected_lifecycle_cost == 10
    assert b.projected_lifecycle_cost == 9
    assert a.estimated_rehandling_cost == 2
    assert b.estimated_rehandling_cost == 1
    assert len(a.same_suit_joins_created) == 1
    assert len(b.same_suit_joins_created) == 2
    assert len(a.mixed_suit_boundaries_created) == 2
    assert len(b.mixed_suit_boundaries_created) == 1
    assert len(a.park_exit_routes) == 2
    assert len(b.park_exit_routes) == 1
    assert a.override_reasons == b.override_reasons == ()
    assert all(result.empty_columns == (6,) for result in variants)
    assert all(result.s1_target_epoch == 2 for result in variants)
    assert all(result.s1_must == ("10s",) for result in variants)
    assert all(result.realizer_status == "found" for result in variants)
    assert all(result.realizer_added_cost == 5 for result in variants)
    assert all(result.realizer_replay_verified for result in variants)
