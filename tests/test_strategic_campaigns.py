"""Sprint 1J — strategic campaign generation and execution tests."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner import campaign_realizer as cr_mod
from spider.planner.campaign_realizer import (
    realize_campaign,
    run_campaign_frontier,
    stratify_campaign_results,
)
from spider.planner.strategic_campaigns import (
    CampaignKind,
    campaign_subobjectives,
    generate_campaigns,
)
from spider.planner import strategic_campaigns as sc_mod
from spider.planner.lower_bounds import count_face_down
from spider.planner.objective_realizer import RealizationStatus


def _pad(cols, stock=None):
    while len(cols) < 10:
        cols.append(Column([], [Card("d", 5 if len(cols) % 2 else 4)]))
    if stock is None:
        stock = [Card("h", r) for r in range(1, 11)] * 5
    return SpiderState(cols, list(stock), [])


def test_no_benchmark_constants_in_campaigns():
    for mod in (sc_mod, cr_mod):
        src = inspect.getsource(mod)
        assert "4925153" not in src
        assert "77d169da" not in src
        assert "Deal 3" not in src
        assert "deal 3" not in src


def test_repeated_shallow_reveals_excavate_synthetic():
    # Shallow chain: 4c on 5c reveals 3c; 3c on 4c reveals 2c.
    st = _pad(
        [
            Column([Card("c", 2), Card("c", 3)], [Card("c", 4)]),
            Column([], [Card("c", 5)]),
        ]
    )
    camps = generate_campaigns(st)
    access = [c for c in camps if c.kind == CampaignKind.ACCESS]
    assert access
    r = realize_campaign(
        st,
        access[0],
        max_paid_cost=8,
        max_steps=6,
        tactical_max_cost=3,
        workspace_max_cost=4,
    )
    assert r.replay_verified
    assert ("deal",) not in r.actions
    found = [s for s in r.steps if s.status == "found"]
    assert len(found) >= 2
    assert r.fd_reduction >= 2


def test_workspace_then_productive_use():
    st = _pad(
        [
            Column([Card("c", 2)], [Card("s", 13)]),
            Column([], [Card("s", 9), Card("s", 8)]),
            Column([], [Card("s", 7)]),
        ]
    )
    camp = next(
        c for c in generate_campaigns(st) if c.kind == CampaignKind.WORKSPACE_EXPLOIT
    )
    r = realize_campaign(st, camp, max_paid_cost=8, max_steps=6)
    assert r.replay_verified
    kinds = [s.objective_kind for s in r.steps if s.status == "found"]
    if "CREATE_WORKSPACE" in kinds:
        follow = [k for k in kinds if k != "CREATE_WORKSPACE"]
        assert r.productive or follow
        if r.status == "success":
            assert r.productive
            assert r.fd_reduction > 0 or r.end_ss > r.start_ss


def test_campaign_replay_exact():
    st = _pad(
        [
            Column([], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
    )
    camp = generate_campaigns(st)[0]
    r = realize_campaign(st, camp, max_paid_cost=6, max_steps=4)
    chk = st.clone()
    cost = replay_actions(chk, list(r.actions)) if r.actions else 0
    assert cost == r.paid_cost
    assert r.replay_verified


def test_campaign_stops_on_budget():
    st = _pad(
        [
            Column([Card("c", i) for i in range(2, 6)], [Card("s", 13)]),
            Column([], [Card("s", 9), Card("s", 8)]),
        ]
    )
    camp = next(
        c for c in generate_campaigns(st) if c.kind == CampaignKind.WORKSPACE_EXPLOIT
    )
    r = realize_campaign(st, camp, max_paid_cost=2, max_steps=8, tactical_max_cost=2)
    assert r.paid_cost <= 2
    assert r.stop_reason in ("budget", "plateau", "success", "resource_limit")


def test_generic_foundation_selection():
    st = _pad(
        [
            Column([], [Card("c", 10), Card("c", 9), Card("c", 8)]),
            Column([], [Card("s", 5)]),
        ]
    )
    camps = generate_campaigns(st)
    founds = [c for c in camps if c.kind == CampaignKind.FOUNDATION_BUILD]
    for c in founds:
        assert c.focus_suit in ("c", "d", "h", "s", None)


def test_never_deals():
    st = _pad([Column([], [Card("h", 4)])])
    stock0 = len(st.stock)
    for camp in generate_campaigns(st):
        r = realize_campaign(st, camp, max_paid_cost=3, max_steps=3)
        assert ("deal",) not in r.actions
        chk = st.clone()
        if r.actions:
            replay_actions(chk, list(r.actions))
        assert len(chk.stock) == stock0


def test_reanalyse_after_every_subobjective(monkeypatch):
    calls = {"n": 0}
    orig = cr_mod.analyze_strategic

    def wrapped(*args, **kwargs):
        calls["n"] += 1
        return orig(*args, **kwargs)

    monkeypatch.setattr(cr_mod, "analyze_strategic", wrapped)
    st = _pad(
        [
            Column([Card("c", 2), Card("c", 3)], [Card("c", 4)]),
            Column([], [Card("c", 5)]),
        ]
    )
    camp = next(c for c in generate_campaigns(st) if c.kind == CampaignKind.ACCESS)
    r = realize_campaign(st, camp, max_paid_cost=6, max_steps=4)
    found = [s for s in r.steps if s.status == "found"]
    # start + each loop iteration + final snapshot
    assert calls["n"] >= 2 + len(found)
    if len(found) >= 2:
        assert found[0].objective_id != found[1].objective_id or found[0].cost > 0


def test_frontier_no_deal():
    st = _pad(
        [
            Column([], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
    )
    frontier = run_campaign_frontier(st, max_paid_cost=4, max_campaigns=3)
    assert frontier.results
    assert all(("deal",) not in r.actions for r in frontier.results)
    assert frontier.pareto
    assert frontier.stratified


def test_resource_limit_is_not_impossible():
    st = _pad(
        [
            Column([Card("c", i) for i in range(2, 8)], [Card("s", 13)]),
            Column([], [Card("h", 6)]),
        ]
    )
    camp = next(c for c in generate_campaigns(st) if c.kind == CampaignKind.ACCESS)
    r = realize_campaign(
        st,
        camp,
        max_paid_cost=2,
        max_steps=3,
        tactical_max_cost=1,
        tactical_max_nodes=8,
        tactical_time_s=0.01,
    )
    assert r.status != "impossible"
    assert r.stop_reason != "impossible"
    assert RealizationStatus.RESOURCE_LIMIT.value != "impossible"
    for step in r.steps:
        assert step.status != "impossible"


def test_workspace_create_alone_not_success():
    # Isolated king: workspace cannot be created, or if created has no follow-on.
    st = _pad(
        [
            Column([], [Card("s", 13)]),
            Column([], [Card("h", 6)]),
            Column([], [Card("d", 8)]),
        ]
    )
    camp = next(
        c for c in generate_campaigns(st) if c.kind == CampaignKind.WORKSPACE_EXPLOIT
    )
    r = realize_campaign(st, camp, max_paid_cost=6, max_steps=4, tactical_max_cost=2)
    if r.fd_reduction == 0 and r.end_ss <= r.start_ss and r.foundations_delta == 0:
        assert r.status != "success"
        assert not r.productive


def test_stratify_is_diverse():
    st = _pad(
        [
            Column([Card("c", 2)], [Card("c", 4)]),
            Column([], [Card("c", 5)]),
            Column([], [Card("s", 9), Card("s", 8)]),
        ]
    )
    frontier = run_campaign_frontier(st, max_paid_cost=5, max_campaigns=4)
    picked = stratify_campaign_results(frontier.results, limit=4)
    assert len(picked) >= 1
    assert len(picked) <= len(frontier.results)
