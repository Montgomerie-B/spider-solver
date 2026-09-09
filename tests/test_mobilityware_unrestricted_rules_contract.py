"""Authoritative MobilityWare 4-suit Unrestricted Deal rules contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from spider.cards import Card
from spider.deal import load_deal, stock_deal_rounds, validate_four_suit_two_deck
from spider.engine import Column, SpiderState
from spider.metrics import CANONICAL_MOBILITYWARE_MOVES, replay_actions
from spider.rules import MW_RULES, RESTRICTED_DEAL_RULES, deal_cost
from spider.simple_progressive_solver import enumerate_actions


ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"


def _ten(slots: dict[int, list[Card]], stock: list[Card] | None = None) -> SpiderState:
    cols = []
    for index in range(10):
        cards = slots.get(index, [Card("s", 13)])
        cols.append(Column([], list(cards)))
    return SpiderState(cols, stock or [])


def test_unrestricted_deal_is_legal_with_empty_columns():
    stock = [Card("c", rank) for rank in range(1, 11)]
    state = _ten({0: []}, stock=stock)
    assert state.columns[0].is_empty()
    assert MW_RULES.can_deal_into_empty is True
    assert state.can_deal(MW_RULES) is True
    cost = state.deal(MW_RULES)
    assert cost == 1
    assert not state.columns[0].is_empty()
    for index in range(10):
        assert state.columns[index].top() == stock[index]
    assert state.stock == []


def test_unrestricted_deal_is_legal_while_tableau_moves_remain():
    stock = [Card("d", rank) for rank in range(1, 11)]
    state = _ten({0: [Card("h", 6)], 1: [Card("s", 7)]}, stock=stock)
    tableau = state.enumerate_moves()
    assert tableau
    assert (0, 1, 1) in tableau
    assert state.can_deal(MW_RULES) is True
    legal = state.enumerate_legal_actions(MW_RULES)
    assert (0, 1, 1) in legal
    assert ("deal",) in legal
    assert enumerate_actions(state, rules=MW_RULES) == legal


def test_successive_unrestricted_deals_do_not_require_tableau_exhaustion():
    stock = [Card("c", rank) for rank in range(1, 21)]
    state = _ten({0: [Card("h", 6)], 1: [Card("s", 7)]}, stock=stock)
    assert state.enumerate_moves()
    assert state.can_deal(MW_RULES)
    state.deal(MW_RULES)
    assert state.enumerate_moves()
    assert state.can_deal(MW_RULES)
    state.deal(MW_RULES)
    assert state.stock == []
    assert not state.can_deal(MW_RULES)


def test_final_stock_row_can_be_dealt_with_empty_tableau_columns():
    stock = [Card("h", rank) for rank in range(1, 11)]
    state = _ten({2: [], 7: []}, stock=stock)
    assert state.columns[2].is_empty() and state.columns[7].is_empty()
    assert state.can_deal(MW_RULES)
    state.deal(MW_RULES)
    assert state.stock == []
    assert state.columns[2].top() == Card("h", 3)
    assert state.columns[7].top() == Card("h", 8)


def test_restricted_profile_still_rejects_empty_column_deal():
    stock = [Card("c", rank) for rank in range(1, 11)]
    state = _ten({0: []}, stock=stock)
    assert state.can_deal(MW_RULES) is True
    assert state.can_deal(RESTRICTED_DEAL_RULES) is False
    with pytest.raises(ValueError, match="empty tableau"):
        state.deal(RESTRICTED_DEAL_RULES)
    assert state.columns[0].is_empty()
    assert MW_RULES.can_deal_into_empty is True


def test_single_cross_suit_rank_descending_move_is_legal():
    state = _ten({0: [Card("d", 7)], 1: [Card("c", 8)]})
    assert state.can_move(0, 1, 1)
    assert state.move(0, 1, 1) == 1


def test_same_suit_descending_multi_card_move_is_legal():
    state = _ten({0: [Card("d", 7), Card("d", 6)], 1: [Card("c", 8)]})
    assert state.can_move(0, 1, 2)


def test_mixed_suit_multi_card_move_is_illegal():
    state = _ten({0: [Card("d", 7), Card("c", 6)], 1: [Card("h", 8)]})
    assert not state.can_move(0, 1, 2)
    with pytest.raises(ValueError, match="illegal move"):
        state.move(0, 1, 2)


def test_legal_card_and_same_suit_block_to_empty_are_legal():
    single = _ten({0: [Card("h", 5)], 1: []})
    assert single.can_move(0, 1, 1)
    block = _ten({0: [Card("s", 8), Card("s", 7)], 1: []})
    assert block.can_move(0, 1, 2)


def test_non_king_card_to_empty_is_legal():
    state = _ten({0: [Card("h", 2)], 1: []})
    assert state.can_move(0, 1, 1)
    assert state.move(0, 1, 1) == 0


def test_exposing_face_down_card_flips_automatically():
    cols = [Column([], [Card("s", 13)]) for _ in range(10)]
    cols[0] = Column([Card("d", 9)], [Card("h", 6)])
    cols[1] = Column([], [Card("c", 7)])
    state = SpiderState(cols, [])
    state.move(0, 1, 1)
    assert cols[0].face_down == []
    assert cols[0].face_up == [Card("d", 9)]


def test_foundation_removal_flips_exposed_face_down():
    hearts = [Card("h", rank) for rank in range(13, 1, -1)]
    cols = [Column([], [Card("s", 13)]) for _ in range(10)]
    cols[0] = Column([Card("c", 4)], hearts)
    cols[1] = Column([], [Card("h", 1)])
    state = SpiderState(cols, [])
    state.move(1, 0, 1)
    assert len(state.foundations) == 1
    assert cols[0].face_up == [Card("c", 4)]
    assert cols[0].face_down == []


def test_same_suit_king_ace_removes_automatically():
    hearts = [Card("h", rank) for rank in range(13, 1, -1)]
    state = _ten({0: hearts, 1: [Card("h", 1)]})
    assert state.move(1, 0, 1) == 1
    assert len(state.foundations) == 1
    assert state.columns[0].is_empty()


def test_mixed_suit_rank_sequence_does_not_remove():
    run = [Card("h", rank) for rank in range(13, 1, -1)]
    run[3] = Card("c", 10)
    state = _ten({0: run, 1: [Card("h", 1)]})
    state.move(1, 0, 1)
    assert state.foundations == []
    assert len(state.columns[0].face_up) == 13


def test_deal_can_complete_a_same_suit_sequence():
    hearts = [Card("h", rank) for rank in range(13, 1, -1)]
    stock = [Card("h", 1)] + [Card("d", rank) for rank in range(2, 11)]
    state = _ten({0: hearts}, stock=stock)
    assert state.can_deal(MW_RULES)
    assert state.deal(MW_RULES) == 1
    assert len(state.foundations) == 1
    assert all(card.suit == "h" for card in state.foundations[0])


def test_4925153_stock_rows_land_left_to_right_from_tail():
    cards = load_deal(DEAL)
    opening = SpiderState.from_cards(cards)
    rounds = stock_deal_rounds(opening.stock)
    assert len(rounds) == 5
    assert [str(card) for card in rounds[0]] == [
        "Js",
        "9d",
        "4d",
        "Kh",
        "4d",
        "6d",
        "9s",
        "7d",
        "8s",
        "5c",
    ]
    assert opening.stock[-10:] == rounds[0]
    dealt = opening.clone()
    dealt.deal()
    assert [str(card) for card in dealt.top_row()] == [
        "Js",
        "9d",
        "4d",
        "Kh",
        "4d",
        "6d",
        "9s",
        "7d",
        "8s",
        "5c",
    ]


def test_ordinary_tableau_move_costs_one():
    state = _ten({0: [Card("d", 7)], 1: [Card("c", 8)]})
    assert state.move(0, 1, 1) == 1


def test_full_column_relocation_to_empty_costs_zero():
    state = _ten({0: [Card("s", 8), Card("s", 7)], 1: []})
    assert state.move(0, 1, 2) == 0


def test_face_up_to_empty_with_face_down_remaining_costs_one():
    cols = [Column([], [Card("s", 13)]) for _ in range(10)]
    cols[0] = Column([Card("d", 9)], [Card("h", 6)])
    cols[1] = Column([], [])
    state = SpiderState(cols, [])
    assert state.move(0, 1, 1) == 1


def test_deal_costs_one_and_foundation_removal_costs_zero():
    hearts = [Card("h", rank) for rank in range(13, 1, -1)]
    state = _ten({0: hearts, 1: [Card("h", 1)]})
    before = len(state.foundations)
    assert state.move(1, 0, 1) == 1
    assert len(state.foundations) == before + 1
    assert deal_cost() == 1


def test_opening_layout_54_tableau_50_stock():
    state = SpiderState.from_cards(load_deal(DEAL))
    lengths = [len(col.face_down) + len(col.face_up) for col in state.columns]
    assert lengths == [6, 6, 6, 6, 5, 5, 5, 5, 5, 5]
    assert all(len(col.face_up) == 1 for col in state.columns)
    assert sum(len(col.face_down) for col in state.columns) == 44
    assert len(state.stock) == 50


def test_canonical_4925153_is_legal_solved_eight_foundations_172():
    state = SpiderState.from_cards(load_deal(DEAL))
    actions: list = []
    for line in CANONICAL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] == "move":
            actions.append((int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3])))
        elif parts[0] == "deal":
            actions.append(("deal",))
    paid = replay_actions(state, actions)
    assert state.is_solved()
    assert len(state.foundations) == 8
    assert paid == CANONICAL_MOBILITYWARE_MOVES == 172


def test_out_of_range_column_indices_are_illegal():
    state = _ten({0: [Card("h", 6)], 1: [Card("s", 7)]})
    assert not state.can_move(-1, 1, 1)
    assert not state.can_move(0, 10, 1)
    assert not state.can_move(0, -1, 1)


def test_parse_rejects_impossible_ranks_and_suits():
    with pytest.raises(ValueError):
        Card.parse("14s")
    with pytest.raises(ValueError):
        Card.parse("0h")
    with pytest.raises(ValueError):
        Card.parse("9x")
    with pytest.raises(ValueError):
        Card.from_notation("14c")


def test_load_deal_rejects_wrong_length_and_non_two_deck():
    with pytest.raises(ValueError, match="104"):
        validate_four_suit_two_deck([Card("s", 1)] * 103)
    cards = list(load_deal(DEAL))
    cards[0] = cards[1]
    with pytest.raises(ValueError, match="two complete"):
        validate_four_suit_two_deck(cards)
