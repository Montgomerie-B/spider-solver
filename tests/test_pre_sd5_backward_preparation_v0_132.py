"""v0.132 stock-column mapping and pre-SD5 preparation guards.

These tests are deterministic. They do not run the 20,000-state probes.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.human_strategy.anchored import build_checkpoints
from spider.human_strategy.evaluation import admissible_remaining
from spider.metrics import parse_moves_file
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.planner.backward_strategy import LocationKind, analyze_stock_backward, locate_all_cards
from spider.planner.foundation_feasibility import current_stock_epoch
from spider.planner.stock_reception import analyze_stock_reception, next_stock_row
from spider.pre_sd5_preparation import (
    annotate_paths,
    assess_immediate_deal,
    search_preparation,
    shifted_proof_height,
)
from spider.research_actions import apply_action, step_cost
from spider.rules import MW_RULES, RESTRICTED_DEAL_RULES

DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
AUTONOMOUS = ROOT / "solutions" / "4925153_autonomous_185.moves"
CANONICAL_SHA = "18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33"
AUTONOMOUS_SHA = "B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73"
SD5_TEXT = "3H, 10H, 2D, 3C, 9H, 7C, 7H, AS, 3C, 5D"
SD5_COPIES = "3H#B, 10H#B, 2D#A, 3C#A, 9H#B, 7C#B, 7H#B, AS#A, 3C#B, 5D#A"


def _cards(text: str):
    return [Card.parse(tok) for tok in text.split() if tok]


def _state(columns, stock: str = "") -> SpiderState:
    cols = [Column([], _cards(columns.get(index, ""))) for index in range(10)]
    return SpiderState(cols, _cards(stock), [])


def _distinct_stock(n: int):
    cards = [Card(suit, rank) for suit in "shdc" for rank in range(1, 14)]
    return cards[:n]


def _stock_state(cards) -> SpiderState:
    return SpiderState([Column([], []) for _ in range(10)], list(cards))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _opening() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL)))


def _fifth_deal(actions):
    deals = 0
    for index, action in enumerate(actions):
        if action == ("deal",):
            deals += 1
            if deals == 5:
                return index
    raise AssertionError("route has no fifth deal")


def _first_diamond(actions):
    state = _opening()
    for index, action in enumerate(actions):
        before = len(state.foundations)
        apply_action(state, action)
        if len(state.foundations) > before and state.foundations[-1][0].suit == "d":
            return index
    raise AssertionError("route builds no diamond foundation")


def test_future_stock_columns_follow_the_engine_on_every_full_chunk():
    full = _distinct_stock(50)
    for length in (50, 40, 30, 20, 10):
        stock = full[:length]
        state = _stock_state(stock)
        located = [item for item in locate_all_cards(state) if item.kind == LocationKind.STOCK]
        assert len(located) == length
        epoch_now = current_stock_epoch(state, 5)
        assert epoch_now == 5 - length // 10
        for index, item in enumerate(located):
            from_top = length - 1 - index
            deal_offset = from_top // 10
            assert item.depth == deal_offset
            assert item.stock_epoch == epoch_now + 1 + deal_offset
            assert item.column == index % 10
            assert item.note.endswith(f"col {item.column + 1}")
        next_row = [item for item in located if item.depth == 0]
        assert [item.column for item in next_row] == list(range(10))
        assert [item.card for item in next_row] == list(stock[-10:])
        assert next_stock_row(state) == tuple(stock[-10:])
        reception = analyze_stock_reception(state, run_shaping_probe=False)
        assert [fact.column for fact in reception.columns] == list(range(10))
        assert [fact.incoming for fact in reception.columns] == list(stock[-10:])
        work = state.clone()
        for _ in range(length // 10):
            expected = list(work.stock[-10:])
            assert work.deal(rules=MW_RULES) == 1
            for column, card in enumerate(expected):
                assert work.columns[column].face_up[-1] == card


def test_reversed_from_top_formula_disagrees_with_the_engine():
    stock = _distinct_stock(50)
    state = _stock_state(stock)
    located = [item for item in locate_all_cards(state) if item.kind == LocationKind.STOCK]
    # stock[0] is the bottom card. The engine deals it on column 0 in the last row.
    assert (50 - 1 - 0) % 10 == 9
    assert located[0].column == 0
    work = state.clone()
    for _ in range(4):
        work.deal(rules=MW_RULES)
    expected = list(work.stock)
    work.deal(rules=MW_RULES)
    assert work.columns[0].face_up[-1] == expected[0] == stock[0]
    assert work.columns[9].face_up[-1] == expected[9]


def test_sd5_row_and_both_verified_preparations():
    assert _sha(CANONICAL) == CANONICAL_SHA
    assert _sha(AUTONOMOUS) == AUTONOMOUS_SHA
    cards = list(load_deal(DEAL))
    assert len(cards) == 104
    seen = {}
    labelled = []
    for card in cards:
        key = (card.suit, card.rank)
        seen[key] = seen.get(key, 0) + 1
        labelled.append(f"{str(card).upper()}#{chr(ord('A') + seen[key] - 1)}")
    assert ", ".join(labelled[54:64]) == SD5_COPIES

    canonical = parse_moves_file(CANONICAL)
    autonomous = parse_moves_file(AUTONOMOUS)
    opening = _opening()
    canonical_points = build_checkpoints(opening.clone(), canonical)
    autonomous_points = build_checkpoints(opening.clone(), autonomous)
    canonical_deal = _fifth_deal(canonical)
    autonomous_deal = _fifth_deal(autonomous)
    pre = canonical_points[canonical_deal]
    post = canonical_points[canonical_deal + 1]
    other = autonomous_points[autonomous_deal]
    assert canonical_deal == 151
    assert pre.g == 149 and pre.stock_cards == 10 and pre.empty_columns == 0
    assert pre.foundations == 2 and pre.face_down == 1 and pre.bonds == 50
    assert ", ".join(str(card).upper() for card in pre.state.stock) == SD5_TEXT
    assert sum(card.suit == "c" and card.rank == 3 for card in pre.state.stock) == 2
    assert all(seq[0].suit != "c" for seq in pre.state.foundations)
    located = [
        item
        for item in locate_all_cards(pre.state)
        if item.kind == LocationKind.STOCK and item.depth == 0
    ]
    assert [item.column for item in located] == list(range(10))
    assert [item.stock_epoch for item in located] == [5] * 10
    reception = analyze_stock_reception(pre.state, run_shaping_probe=False)
    assert [fact.incoming for fact in reception.columns] == list(pre.state.stock)
    assert [fact.column for fact in reception.columns] == list(range(10))
    same = [fact.column + 1 for fact in reception.columns if fact.landing.value == "same_suit_connect"]
    assert same == [2, 6, 9, 10]
    assert reception.columns[0].pre_deal_same_suit_run_len == 6
    assert reception.columns[6].pre_deal_same_suit_run_len == 10
    backward = analyze_stock_backward(pre.state)
    assert sorted(wish.column for wish in backward.receiver_wishes) == list(range(10))
    assert sorted(
        wish.column + 1 for wish in backward.receiver_wishes if wish.landing_now == "same_suit_connect"
    ) == [2, 6, 9, 10]
    dealt = assess_immediate_deal(pre.state, pre.g, 0, 0)
    assert dealt.same_suit_landings == 4
    assert dealt.g_post == 150 and dealt.h_post == 18 and dealt.f_post == 168
    assert dealt.bonds == 54 and dealt.face_down == 1 and dealt.buried_long_runs == 2
    assert dealt.cannot_beat_if_deal_now is False
    assert post.g == 150 and post.bonds == 54 and int(admissible_remaining(post.state)) == 18

    diamond = _first_diamond(canonical)
    prepared = canonical_points[diamond + 1]
    assert diamond == 139
    assert prepared.index == 140 and prepared.g == 139 and prepared.stock_cards == 10
    assert prepared.empty_columns == 2 and prepared.foundations == 2
    assert pre.index - prepared.index == 11
    assert pre.g - prepared.g == 10
    trial = prepared.state.clone()
    free = []
    for action in canonical[prepared.index : pre.index]:
        if step_cost(trial, action) == 0:
            free.append(action)
        apply_action(trial, action)
    assert free == [(1, 4, 1)]
    assert pack_state(trial) == pack_state(pre.state)

    assert autonomous_deal == 137
    assert other.g == 133 and other.empty_columns == 1 and other.stock_cards == 10
    other_deal = assess_immediate_deal(other.state, other.g, 0, 0)
    assert other_deal.same_suit_landings == 0
    assert other_deal.empty_before == (8,)
    assert other_deal.h_post == 42 and other_deal.f_post == 176
    assert other_deal.bonds == 30 and other_deal.face_down == 2
    assert other_deal.cannot_beat_if_deal_now is True


def test_unrestricted_deal_lands_on_an_empty_column():
    state = _state({0: "ks"}, stock="ad 2d 3d 4d 5d 6d 7d 8d 9d 10d")
    assert state.columns[1].is_empty()
    assert state.can_deal(rules=MW_RULES)
    assert state.can_deal(rules=RESTRICTED_DEAL_RULES) is False
    assert state.deal(rules=MW_RULES) == 1
    assert state.columns[1].face_up[-1] == Card.parse("2d")
    assert state.stock == []


def test_zero_cost_whole_column_counts_as_one_preparation_action():
    state = _state({0: "6s 5s"}, stock="ad 2d 3d 4d 5d 6d 7d 8d 9d 10d")
    assert step_cost(state, (0, 1, 1)) == 1
    assert step_cost(state, (0, 1, 2)) == 0
    found = search_preparation(
        state,
        g0=10,
        label="zero-cost-depth",
        proof_ceiling=1000,
        max_depth=3,
        max_unique=40,
        time_limit_s=2.0,
        proof_bound=lambda _state, _g: 0,
    )
    free = [item for item in found.assessments if item.depth >= 1 and item.g_pre == 10]
    assert free
    annotate_paths(state, 10, found.kernel, free[:4])
    assert any(item.path_zero_cost >= 1 and "deal" not in item.path for item in free[:4])
    assert found.hit_depth_limit or max(item.depth for item in found.assessments) <= 3


def test_stock_bearing_columns_keep_physical_order():
    left = _state({0: "5s", 1: "6h"}, stock="ad 2d 3d 4d 5d 6d 7d 8d 9d 10d")
    right = _state({0: "6h", 1: "5s"}, stock="ad 2d 3d 4d 5d 6d 7d 8d 9d 10d")
    assert pack_state(left) != pack_state(right)
    assert pack_whole_game_identity(left) == pack_state(left)
    assert pack_whole_game_identity(right) == pack_state(right)


def test_deal_now_bound_does_not_delete_the_pre_deal_state():
    state = _state({0: "6h 5s"}, stock="ad 2d 3d 4d 5d 6d 7d 8d 9d 10d")
    found = search_preparation(
        state,
        g0=200,
        label="flag-only",
        proof_ceiling=10000,
        max_depth=1,
        max_unique=20,
        time_limit_s=2.0,
        proof_bound=lambda _state, _g: 0,
    )
    assert found.expanded >= 1
    assert found.unique > 1
    assert found.assessments[0].cannot_beat_if_deal_now is True
    assert found.assessments[0].deal_legal is True
    assert any(item.node != 0 for item in found.assessments)


def test_proof_bound_rejects_a_child_before_it_takes_a_slot():
    state = _state(
        {0: "6h 5s", 1: "ks", 2: "kh", 3: "kd", 4: "kc", 5: "qs", 6: "qh", 7: "qd", 8: "qc", 9: "js"},
        stock="ad 2d 3d 4d 5d 6d 7d 8d 9d 10d",
    )
    found = search_preparation(
        state,
        g0=100,
        label="proof",
        proof_ceiling=171,
        max_depth=1,
        max_unique=20,
        time_limit_s=2.0,
        proof_bound=lambda _state, g: 0 if g <= 100 else 1000,
    )
    assert found.unique == 1
    assert found.lower_bound_prunes >= 1
    assert [item.node for item in found.assessments] == [0]


def test_shifted_height_matches_the_real_proof_ceiling():
    assert shifted_proof_height(22, 171, 149) == 0
    assert (149 + shifted_proof_height(22, 171, 149) > 149) is False
    assert (149 + 22 > 171) is False
    assert shifted_proof_height(23, 171, 149) == 1
    assert (149 + shifted_proof_height(23, 171, 149) > 149) is True
    assert (149 + 23 > 171) is True
    assert shifted_proof_height(31, 171, 149) == 9
    assert (140 + 9 > 149) is False and (140 + 31 > 171) is False
    assert shifted_proof_height(32, 171, 149) == 10
    assert (140 + 10 > 149) is True and (140 + 32 > 171) is True
    for g in range(130, 150):
        for admissible in range(50):
            height = shifted_proof_height(admissible, 171, 149)
            assert (g + height > 149) == (g + admissible > 171)
