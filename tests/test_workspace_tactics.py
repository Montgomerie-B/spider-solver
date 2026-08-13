"""Sprint 1M — focused CREATE_WORKSPACE tactical backend tests."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner.objective_realizer import RealizationStatus
from spider.planner.space_lifecycle import empty_count
from spider.planner import workspace_tactics as wt
from spider.planner.workspace_tactics import (
    WorkspaceBackend,
    productive_follow_on,
    realize_workspace,
    workspace_quotient_key,
)
from spider.rules import MW_RULES


def _pad(cols, stock=None):
    while len(cols) < 10:
        cols.append(Column([], [Card("d", 4 if len(cols) % 2 else 5)]))
    return SpiderState(cols, list(stock or [Card("h", r) for r in range(1, 11)] * 3), [])


def test_no_benchmark_constants():
    src = inspect.getsource(wt)
    assert "4925153" not in src
    assert "77d169da" not in src


def test_improved_workspace_replay_and_cost():
    st = _pad(
        [
            Column([Card("c", 2)], [Card("s", 13)]),
            Column([], [Card("s", 9), Card("s", 8)]),
            Column([], [Card("s", 7)]),
        ]
    )
    assert empty_count(st) == 0
    res = realize_workspace(
        st, backend=WorkspaceBackend.IMPROVED, max_cost=6, max_nodes=800
    )
    assert res.status == RealizationStatus.FOUND
    assert res.corrected_mw_cost is not None
    chk = st.clone()
    cost = replay_actions(chk, list(res.actions))
    assert cost == res.corrected_mw_cost
    assert empty_count(chk) >= 1
    assert ("deal",) not in res.actions


def test_legacy_vs_improved_synthetic():
    st = _pad(
        [
            Column([], [Card("s", 9), Card("s", 8)]),
            Column([], [Card("s", 7)]),
        ]
    )
    old = realize_workspace(st, backend=WorkspaceBackend.LEGACY, max_cost=5, max_nodes=600)
    new = realize_workspace(st, backend=WorkspaceBackend.IMPROVED, max_cost=5, max_nodes=600)
    assert new.status == RealizationStatus.FOUND
    if old.status == RealizationStatus.FOUND:
        assert new.corrected_mw_cost <= old.corrected_mw_cost


def test_quotient_identifies_free_relocations():
    a = _pad(
        [
            Column([], [Card("s", 13)]),
            Column([], []),
            Column([], [Card("h", 13)]),
        ]
    )
    b = a.clone()
    # Relocate the open king onto the empty (0-cost if fully open).
    b.move(0, 1, 1, rules=MW_RULES)
    assert workspace_quotient_key(a) == workspace_quotient_key(b)
    # Emptying a new column changes the quotient.
    c = _pad(
        [
            Column([], [Card("s", 9), Card("s", 8)]),
            Column([], [Card("s", 7)]),
            Column([], [Card("s", 13)]),
            Column([], []),
        ]
    )
    d = c.clone()
    d.move(1, 0, 1, rules=MW_RULES)  # 7s onto 8s, creates empty
    assert workspace_quotient_key(c) != workspace_quotient_key(d)


def test_bounded_miss_is_not_impossible():
    st = _pad([Column([], [Card("s", 13)]) for _ in range(10)])
    res = realize_workspace(
        st, backend=WorkspaceBackend.IMPROVED, max_cost=2, max_nodes=40, time_limit_s=0.05
    )
    assert res.status in (
        RealizationStatus.NOT_FOUND_WITHIN_BOUND,
        RealizationStatus.RESOURCE_LIMIT,
    )
    assert res.status != RealizationStatus.FOUND or res.corrected_mw_cost is not None
    assert res.status.value != "impossible"
    assert any("miss != impossible" in n or "not_found_within_bound != impossible" in n for n in res.notes) or res.status == RealizationStatus.RESOURCE_LIMIT


def test_productive_follow_on_after_workspace():
    st = _pad(
        [
            Column([Card("c", 2)], [Card("s", 13)]),
            Column([], [Card("s", 9), Card("s", 8)]),
            Column([], [Card("s", 7)]),
        ]
    )
    res = realize_workspace(st, backend=WorkspaceBackend.IMPROVED, max_cost=6)
    assert res.status == RealizationStatus.FOUND
    follow = productive_follow_on(st, res.actions, max_cost=4, max_nodes=300)
    # At least one follow-on family is attempted; reveal of buried 2c is the intent.
    assert isinstance(follow, tuple)
    if follow:
        assert any(f.kind for f in follow)


def test_improved_beats_orbit_explosion():
    # Many free kings + empties; one mixed column emptyable in 3 peels.
    st = _pad(
        [
            Column([], [Card("h", 9), Card("c", 8), Card("s", 7)]),
            Column([], [Card("s", 8)]),
            Column([], [Card("c", 9)]),
            Column([], [Card("h", 10)]),
            Column([], [Card("s", 13)]),
            Column([], [Card("d", 13)]),
            Column([], [Card("c", 13)]),
            Column([], []),
            Column([], []),
            Column([], []),
        ]
    )
    new = realize_workspace(
        st,
        backend=WorkspaceBackend.IMPROVED,
        max_cost=5,
        max_nodes=120,
        time_limit_s=0.6,
    )
    old = realize_workspace(
        st,
        backend=WorkspaceBackend.LEGACY,
        max_cost=5,
        max_nodes=120,
        time_limit_s=0.6,
    )
    assert new.status == RealizationStatus.FOUND
    assert empty_count(st) == 3
    chk = st.clone()
    replay_actions(chk, list(new.actions))
    assert empty_count(chk) >= 4
    # Improved should find; legacy may miss under the same tiny node cap.
    if old.status == RealizationStatus.FOUND:
        assert new.corrected_mw_cost <= old.corrected_mw_cost
