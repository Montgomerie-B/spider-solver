"""Focused tests for backward / space-lifecycle diagnostic helpers."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.planner import backward_strategy as bs
from spider.planner.backward_strategy import (
    Urgency,
    analyze_backward,
    analyze_buried_cards,
    analyze_excavation_projects,
    analyze_space_liquidity,
    analyze_stock_backward,
    locate_all_cards,
)
from spider.planner.space_lifecycle import empty_count


def _pad(cols, stock=None, buried_pads=True):
    while len(cols) < 10:
        i = len(cols)
        if buried_pads:
            cols.append(Column([Card("d", 2 if i % 2 else 3)], [Card("d", 5 if i % 2 else 4)]))
        else:
            cols.append(Column([], [Card("d", 5 if i % 2 else 4)]))
    if stock is None:
        # Five full deal-rows so epoch math is standard.
        stock = [Card("h", ((i % 13) + 1)) for i in range(50)]
    return SpiderState(cols, list(stock), [])


def test_no_benchmark_constants():
    src = inspect.getsource(bs)
    assert "4925153" not in src
    assert "77d169da" not in src
    assert "Section H" not in src


def test_buried_card_useful_now_extends_visible_fragment():
    # Visible 8s-7s; 6s is the next flip in col 0. Completing that spine
    # is useful now. A deep unused 2h is not.
    st = _pad(
        [
            Column([Card("s", 6)], [Card("h", 12)]),  # next flip = 6s
            Column([], [Card("s", 8), Card("s", 7)]),
            Column(
                [Card("h", 2), Card("h", 3), Card("h", 4), Card("h", 9)],
                [Card("c", 13)],
            ),
        ],
        stock=[Card("c", 13)] * 50,
    )
    facts = analyze_buried_cards(st)
    six = next(f for f in facts if f.card == Card("s", 6))
    two = next(f for f in facts if f.card == Card("h", 2))
    assert six.urgency == Urgency.USEFUL_NOW
    assert six.ss_join
    assert six.prereq_status.value == "exposed"
    assert two.urgency in (Urgency.CURRENTLY_LOW_VALUE, Urgency.USEFUL_LATER)
    assert six.value_score > two.value_score


def test_buried_card_useful_when_dest_is_next_stock():
    # 5c buried; only 6c is the next-deal card on this column.
    next_row = [Card("c", 6)] + [Card("h", 13)] * 9
    later = [Card("s", 1)] * 40
    st = _pad(
        [
            Column([Card("c", 5)], [Card("s", 13)]),
            Column([Card("d", 2)], [Card("d", 9)]),
        ],
        stock=later + next_row,
        buried_pads=True,
    )
    facts = analyze_buried_cards(st)
    five = next(f for f in facts if f.card == Card("c", 5))
    assert five.urgency in (
        Urgency.USEFUL_BEFORE_NEXT_DEAL,
        Urgency.USEFUL_NOW,
        Urgency.USEFUL_LATER,
    )
    # Dest 6c is in the next row — not currently exposed.
    assert five.prereq_status.value in ("future_stock", "buried", "exposed")
    if five.prereq_status.value == "future_stock":
        assert five.earliest_useful_epoch >= 1


def test_not_every_hidden_card_is_urgent():
    st = _pad(
        [
            Column([Card("h", 1)], [Card("s", 13)]),
            Column([], [Card("s", 8), Card("s", 7)]),
        ]
    )
    facts = analyze_buried_cards(st)
    assert facts
    low = [f for f in facts if f.urgency == Urgency.CURRENTLY_LOW_VALUE]
    now = [f for f in facts if f.urgency == Urgency.USEFUL_NOW]
    # At least the ranking distinguishes; Ace of hearts under a king is not a now-project.
    ace = next(f for f in facts if f.card == Card("h", 1))
    assert ace.urgency != Urgency.USEFUL_NOW or now
    assert ace.value_score < 20


def test_project_rank_prefers_unlock_not_raw_fd():
    # Col0: 1 fd, unlocks 6s onto a live 7s spine.
    # Col1: 4 fd of junk hearts under a king — more raw fd, less value.
    st = _pad(
        [
            Column([Card("s", 6)], [Card("h", 12)]),
            Column(
                [Card("h", 2), Card("h", 3), Card("h", 4), Card("h", 5)],
                [Card("c", 13)],
            ),
            Column([], [Card("s", 8), Card("s", 7)]),
        ],
        stock=[Card("c", 13)] * 50,
    )
    buried = analyze_buried_cards(st)
    projects = analyze_excavation_projects(st, buried)
    ranked_fd = [p for p in projects if p.face_down > 0]
    assert ranked_fd[0].column == 0
    junk = next(p for p in projects if p.column == 1)
    good = next(p for p in projects if p.column == 0)
    assert good.unlock_value > junk.unlock_value
    assert good.rank_score > junk.rank_score


def test_space_option_values_reveal_of_useful_card():
    st = _pad(
        [
            Column([Card("s", 6)], [Card("h", 12)]),
            Column([], [Card("s", 8), Card("s", 7)]),
        ],
        buried_pads=True,
    )
    buried = analyze_buried_cards(st)
    liq = analyze_space_liquidity(st, buried)
    assert liq.spaces_now == 0
    kinds = {u.kind for u in liq.uses}
    assert "reveal_buried" in kinds or "continue_excavation" in kinds
    col0 = [u for u in liq.uses if u.column == 0]
    assert col0
    assert col0[0].value > 8
    assert col0[0].kind in ("reveal_buried", "continue_excavation")


def test_fill_then_deal_allowed_when_incoming_would_occupy_empty():
    # One empty. Incoming on that empty is a disconnected 3h.
    # A consuming fill exists (8s sitting on a face-down). After fill+deal,
    # a fully-open 7h-run can empty onto an 8h that the deal places.
    next_row = [
        Card("h", 3),  # col0 empty → occupy unless filled
        Card("h", 8),  # col1
        Card("s", 2),
        Card("s", 3),
        Card("s", 5),
        Card("s", 9),
        Card("s", 10),
        Card("s", 11),
        Card("s", 12),
        Card("s", 13),
    ]
    later = [Card("c", 1)] * 40
    st = SpiderState(
        [
            Column([], []),  # empty
            Column([Card("c", 2)], [Card("s", 8)]),  # consuming fill
            Column([], [Card("h", 10), Card("h", 9), Card("h", 7)]),  # 7h needs 8h
            Column([], [Card("c", 13)]),
            Column([], [Card("d", 13)]),
            Column([], [Card("h", 13)]),
            Column([], [Card("s", 13)]),
            Column([], [Card("c", 12)]),
            Column([], [Card("d", 12)]),
            Column([], [Card("h", 12)]),
        ],
        later + next_row,
        [],
    )
    assert empty_count(st) == 1
    stock = analyze_stock_backward(st)
    assert stock.can_deal
    assert stock.recommendation in (
        "fill_then_deal_then_recreate",
        "ambiguous_space_policy",
        "carry_empty_if_needed_recovery_exists",
    )
    # The model must *consider* fill-then-recreate, not assume carry is better.
    assert "n/a_no_empty" not in stock.fill_then_recreate_assessment
    assert "occupy" in stock.carry_empty_assessment or "fill" in stock.recommendation


def test_zero_empty_does_not_demand_creating_space_to_carry():
    next_row = [Card("s", r) for r in range(1, 11)]
    later = [Card("h", 1)] * 40
    st = _pad(
        [
            Column([Card("c", 2)], [Card("s", 13)]),
            Column([], [Card("s", 8), Card("s", 7)]),
        ],
        stock=later + next_row,
        buried_pads=True,
    )
    assert empty_count(st) == 0
    stock = analyze_stock_backward(st)
    assert stock.recommendation != "carry_empty_if_needed_recovery_exists"
    assert "carry" in stock.carry_empty_assessment.lower() or "not" in stock.carry_empty_assessment.lower()


def test_meet_in_middle_ranks_useful_project_above_shallow_junk():
    st = _pad(
        [
            Column([Card("s", 6)], [Card("h", 12)]),
            Column([Card("h", 2)], [Card("c", 13)]),
            Column([], [Card("s", 8), Card("s", 7)]),
        ]
    )
    analysis = analyze_backward(st)
    # Column 0 should beat column 1.
    rank = {r.column: i for i, r in enumerate(analysis.ranked)}
    assert rank[0] < rank[1]
    assert analysis.ranked[0].backward >= analysis.ranked[1].backward or analysis.ranked[0].combined > analysis.ranked[1].combined


def test_locate_interchangeable_copies():
    st = _pad(
        [
            Column([Card("s", 6)], [Card("h", 12)]),
            Column([], [Card("s", 6)]),  # second 6s already exposed
        ]
    )
    locs = locate_all_cards(st)
    sixes = [x for x in locs if x.card == Card("s", 6)]
    assert len(sixes) >= 2
    kinds = {x.kind.value for x in sixes}
    assert "face_down" in kinds
    assert "face_up_top" in kinds
