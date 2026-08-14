"""Focused tests for committed excavation-project search."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner import committed_excavation as ce
from spider.planner.committed_excavation import (
    ProjectStatus,
    measure_progress,
    search_empty_column,
    select_portfolio,
)
from spider.planner.space_lifecycle import empty_count


def _pad(cols, stock=None):
    while len(cols) < 10:
        i = len(cols)
        cols.append(Column([Card("d", 2 if i % 2 else 3)], [Card("d", 13)]))
    if stock is None:
        stock = [Card("h", 13)] * 50
    return SpiderState(cols, list(stock), [])


def test_no_benchmark_constants():
    src = inspect.getsource(ce)
    assert "4925153" not in src
    assert "77d169da" not in src
    assert "col 10" not in src.lower()
    assert "column 10" not in src.lower()


def test_target_commitment_persists():
    # Col0 needs two peels. Col1 is one move from empty. Commitment to col0
    # must empty col0, not succeed by emptying col1.
    st = _pad(
        [
            Column([Card("s", 6)], [Card("c", 12)]),
            Column([], [Card("s", 7)]),
            Column([], [Card("s", 8)]),
            Column([], [Card("c", 13)]),
        ]
    )
    assert empty_count(st) == 0
    res = search_empty_column(st, target=0, max_cost=6, max_nodes=800, time_limit_s=2.0)
    assert res.target == 0
    if res.status == ProjectStatus.FOUND:
        chk = st.clone()
        replay_actions(chk, list(res.actions))
        assert chk.columns[0].is_empty()
        assert ("deal",) not in res.actions


def test_auxiliary_dependency_move_allowed():
    # Target 6s under 4d. 4d has a live dest. 6s dest 7s is under 9h.
    st = _pad(
        [
            Column([Card("s", 6)], [Card("d", 4)]),
            Column([Card("s", 7)], [Card("h", 9)]),
            Column([], [Card("d", 5)]),
            Column([], [Card("h", 10)]),
        ]
    )
    res = search_empty_column(st, target=0, max_cost=6, max_nodes=1500, time_limit_s=3.0)
    assert res.status == ProjectStatus.FOUND
    assert res.cost is not None and res.cost <= 3
    srcs = [a[0] for a in res.actions]
    assert 0 in srcs
    assert any(s != 0 for s in srcs)  # dest-prep on another column
    chk = st.clone()
    assert replay_actions(chk, list(res.actions)) == res.cost
    assert chk.columns[0].is_empty()
    assert ("deal",) not in res.actions


def test_progress_updates_after_dest_prep():
    st = _pad(
        [
            Column([Card("s", 6)], [Card("d", 4)]),
            Column([Card("s", 7)], [Card("h", 9)]),
            Column([], [Card("d", 5)]),
            Column([], [Card("h", 10)]),
        ]
    )
    before = measure_progress(st, 0)
    # Peel the dest-prep column: 9h onto 10h, expose 7s.
    st2 = st.clone()
    st2.move(1, 3, 1)
    after = measure_progress(st2, 0)
    assert after.next_hop_live or after.prereqs_satisfied > before.prereqs_satisfied
    assert after.unresolved_depth <= before.unresolved_depth


def test_synthetic_prep_then_evacuate_replay():
    st = _pad(
        [
            Column([Card("s", 6)], [Card("d", 4)]),
            Column([Card("s", 7)], [Card("h", 9)]),
            Column([], [Card("d", 5)]),
            Column([], [Card("h", 10)]),
        ]
    )
    res = search_empty_column(st, target=0, max_cost=8, max_nodes=2000)
    assert res.status == ProjectStatus.FOUND
    chk = st.clone()
    cost = replay_actions(chk, list(res.actions))
    assert cost == res.cost
    assert chk.columns[0].is_empty()
    assert empty_count(chk) >= 1
    assert all(a != ("deal",) for a in res.actions)


def test_portfolio_is_small_and_generic():
    st = _pad(
        [
            Column([Card("s", 6)], [Card("c", 12)]),
            Column([], [Card("s", 7)]),
            Column([Card("h", 2), Card("h", 3), Card("h", 4)], [Card("s", 13)]),
            Column([], [Card("h", 8)]),
        ]
    )
    port = select_portfolio(st, max_projects=5, cost_slack=4)
    assert 1 <= len(port) <= 5
    # Cheapest emptyable band — the hard king column should not crowd it out.
    cols = {e.column for e in port}
    assert 0 in cols
    assert all(e.emptyable for e in port)


def test_no_deal_even_when_stock_present():
    st = _pad(
        [
            Column([Card("s", 6)], [Card("c", 12)]),
            Column([], [Card("s", 7)]),
        ],
        stock=[Card("h", r) for r in range(1, 11)] * 5,
    )
    res = search_empty_column(st, target=0, max_cost=5, max_nodes=500)
    if res.actions:
        assert ("deal",) not in res.actions
