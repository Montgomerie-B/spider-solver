"""Focused tests for excavation dependency closure."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.planner import excavation_closure as ec
from spider.planner.excavation_closure import (
    DestAvailability,
    close_all_columns,
    close_column,
    column_hops,
    dest_options,
    rank_closures,
)
from spider.planner.backward_strategy import locate_all_cards
from spider.planner.foundation_feasibility import current_stock_epoch


def _pad(cols, stock=None):
    while len(cols) < 10:
        i = len(cols)
        cols.append(Column([Card("d", 2 if i % 2 else 3)], [Card("d", 13)]))
    if stock is None:
        stock = [Card("h", 13)] * 50
    return SpiderState(cols, list(stock), [])


def test_no_benchmark_constants():
    src = inspect.getsource(ec)
    assert "4925153" not in src
    assert "77d169da" not in src
    assert "Section H" not in src
    assert "col 10" not in src.lower()
    assert "column 10" not in src.lower()


def test_recursive_destination_dependency():
    # Target col0: 6s. Dest 7s is buried under 9h; 9h has a live dest 10h.
    st = _pad(
        [
            Column([Card("s", 6)], [Card("c", 12)]),
            Column([Card("s", 7)], [Card("h", 9)]),
            Column([], [Card("h", 10)]),
        ]
    )
    p = close_column(st, 0)
    hop0 = p.hop_closures[0]
    assert hop0.hop.need_rank == 13 or hop0.hop.card.rank == 12
    six = next(h for h in p.hop_closures if h.hop.card == Card("s", 6))
    assert not six.hard_ready
    assert six.chosen is not None
    assert six.chosen.loc.column == 1
    assert 1 in p.dest_prep_columns
    assert p.dependency_depth >= 1
    assert p.estimated_prep_cost >= 1
    assert p.estimated_total_cost > p.direct_target_moves


def test_interchangeable_duplicate_destinations():
    # Two 7s: one exposed, one buried deep. OR-node must pick the exposed copy.
    st = _pad(
        [
            Column([Card("s", 6)], [Card("c", 12)]),
            Column(
                [Card("s", 7), Card("h", 2), Card("h", 3), Card("h", 4)],
                [Card("c", 13)],
            ),
            Column([], [Card("h", 7)]),
        ]
    )
    locs = locate_all_cards(st)
    opts = dest_options(st, 7, locs=locs, exclude_column=0)
    kinds = {o.availability for o in opts}
    assert DestAvailability.EXPOSED_TOP in kinds
    assert DestAvailability.FACE_DOWN in kinds
    p = close_column(st, 0)
    six = next(h for h in p.hop_closures if h.hop.card == Card("s", 6))
    assert six.hard_ready
    assert six.chosen is not None
    assert six.chosen.availability == DestAvailability.EXPOSED_TOP
    assert six.chosen.loc.column == 2
    assert 1 not in p.dest_prep_columns


def test_future_stock_dependency():
    next_row = [Card("s", 7)] + [Card("c", 13)] * 9
    later = [Card("h", 13)] * 40
    st = _pad(
        [
            Column([Card("h", 2)], [Card("s", 6)]),
            Column([Card("h", 3)], [Card("d", 13)]),
        ],
        stock=later + next_row,
    )
    p = close_column(st, 0)
    six = next(h for h in p.hop_closures if h.hop.card == Card("s", 6))
    assert six.future_stock
    assert p.future_stock_deps >= 1
    assert p.earliest_epoch > current_stock_epoch(st, 5)
    assert not p.emptyable_this_epoch


def test_shared_prerequisite_not_double_counted():
    # Two hops on col0 (5s then 4s after flip) both need dests that live
    # under the SAME one-peel helper column (6h under 9c, 5h under that 6h
    # is NOT the case). Simpler: 6s and after flip another 6d, both need 7s
    # which is one peel on col1. Prep must be 1, not 2.
    st = _pad(
        [
            Column([Card("d", 6)], [Card("s", 6)]),
            Column([Card("s", 7)], [Card("h", 9)]),
            Column([], [Card("h", 10)]),
        ]
    )
    p = close_column(st, 0)
    sixes = [h for h in p.hop_closures if h.hop.need_rank == 7]
    assert len(sixes) == 2
    assert all(h.prep_tasks for h in sixes)
    assert p.dest_prep_columns == (1,)
    assert p.dependency_depth == 1
    # Union charges the helper column once.
    assert p.estimated_prep_cost == 1


def test_easy_vs_hard_projects_rank():
    # Col0: 6s onto live 7s — easy.
    # Col1: 5c onto 6c buried three deep under a King — hard.
    st = _pad(
        [
            Column([Card("s", 6)], [Card("c", 12)]),
            Column(
                [Card("c", 6), Card("h", 2), Card("h", 3)],
                [Card("s", 13)],
            ),
            Column([], [Card("s", 7)]),
        ]
    )
    closures = close_all_columns(st)
    ranked = rank_closures(closures, epoch=0)
    by_col = {r.column: r for r in ranked}
    assert by_col[0].est_cost < by_col[1].est_cost
    assert ranked[0].column == 0


def test_hops_follow_excavation_order():
    st = _pad(
        [
            Column([Card("s", 5), Card("s", 6)], [Card("h", 8), Card("h", 7)]),
        ]
    )
    hops = column_hops(st, 0)
    assert hops[0].card == Card("h", 8)
    assert hops[0].k == 2
    assert hops[1].card == Card("s", 6)
    assert hops[2].card == Card("s", 5)
