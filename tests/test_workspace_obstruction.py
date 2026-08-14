"""Focused tests for workspace obstruction diagnostic helpers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.planner.space_lifecycle import empty_count
from spider.planner.workspace_obstruction import (
    profile_column,
    profile_state,
    promising_columns,
    search_evacuation,
    workspace_potential,
)
from spider.planner.workspace_tactics import workspace_quotient_key
from spider.rules import MW_RULES


def _pad(cols, stock=None):
    while len(cols) < 10:
        cols.append(Column([], [Card("d", 4 if len(cols) % 2 else 5)]))
    return SpiderState(cols, list(stock or [Card("h", r) for r in range(1, 11)] * 3), [])


def test_one_move_create_profile():
    st = _pad(
        [
            Column([], [Card("s", 9), Card("s", 8)]),
            Column([], [Card("s", 7)]),
        ]
    )
    p1 = profile_column(st, 1)
    assert p1.one_move_creates
    assert 0 in p1.dests_nonempty
    assert p1.shortage == "none"
    wp = workspace_potential(st)
    assert wp["one_move_creates"] >= 1
    assert wp["score"] > 10


def test_king_needs_empty_shortage():
    st = _pad([Column([], [Card("s", 13)]) for _ in range(10)])
    p = profile_column(st, 0)
    assert p.shortage == "king_needs_empty"
    assert not p.one_move_creates
    wp = workspace_potential(st)
    assert wp["one_move_creates"] == 0
    assert wp["evac_open"] == 0


def test_target_search_finds_synthetic():
    st = _pad(
        [
            Column([], [Card("s", 9), Card("s", 8)]),
            Column([], [Card("s", 7)]),
        ]
    )
    r = search_evacuation(st, target_column=1, max_cost=3, max_nodes=200, time_limit_s=1.0)
    assert r.status == "FOUND"
    assert r.cost == 1
    chk = st.clone()
    from spider.metrics import replay_actions

    replay_actions(chk, list(r.actions))
    assert chk.columns[1].is_empty()
    assert empty_count(chk) >= 1


def test_resource_limit_not_exhausted():
    st = _pad([Column([], [Card("s", 13)]) for _ in range(10)])
    r = search_evacuation(st, max_cost=4, max_nodes=8, time_limit_s=0.01)
    assert r.status in ("RESOURCE_LIMIT", "EXHAUSTED")
    assert r.status != "FOUND" or r.cost is not None


def test_metric_separates_easy_from_blocked():
    easy = _pad(
        [
            Column([], [Card("s", 9), Card("s", 8)]),
            Column([], [Card("s", 7)]),
        ]
    )
    hard = _pad([Column([], [Card("s", 13)]) for _ in range(10)])
    assert workspace_potential(easy)["score"] > workspace_potential(hard)["score"]
    assert promising_columns(easy)
    assert len(profile_state(easy)) == 10


def test_metric_rewards_open_columns_even_without_dest():
    # Human-like: several fully-open piles, no instant dest.
    openish = _pad(
        [
            Column([], [Card("s", 12), Card("s", 11), Card("s", 10)]),
            Column([], [Card("h", 8), Card("h", 7), Card("h", 6)]),
            Column([Card("c", 2)], [Card("c", 5)]),
        ]
    )
    # Machine-like: every column still has face-down (including pads).
    buried = SpiderState(
        [
            Column([Card("s", 2), Card("s", 3)], [Card("s", 7)]),
            Column([Card("h", 4)], [Card("h", 9)]),
            Column([Card("c", 5)], [Card("c", 6)]),
        ]
        + [Column([Card("d", 3)], [Card("d", 5 if i % 2 else 4)]) for i in range(7)],
        [Card("h", r) for r in range(1, 11)] * 3,
        [],
    )
    so = workspace_potential(openish)
    sb = workspace_potential(buried)
    assert so["open_columns"] >= 2
    assert sb["open_columns"] == 0
    assert so["score"] > sb["score"]


def test_quotient_stable_under_free_relocate():
    a = _pad(
        [
            Column([], [Card("s", 13)]),
            Column([], []),
        ]
    )
    b = a.clone()
    b.move(0, 1, 1, rules=MW_RULES)
    assert workspace_quotient_key(a) == workspace_quotient_key(b)
