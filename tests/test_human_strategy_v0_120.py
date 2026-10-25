"""v0.120 progressive tactical budgets and search timing.

Synthetic boards are the fixtures. The solver does not contain these positions.
Direct callers that leave the schedule unset keep the historical probe sizes.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.human_strategy.anchored import (
    AnchoredRefused,
    build_checkpoints,
    optimise_anchored,
    search_segment,
    search_targets,
)
from spider.human_strategy.controller import _proposal_time_left, solve
from spider.human_strategy.foundation_direction import (
    FoundationAgenda,
    FoundationView,
    _PROGRESSIVE_LADDER,
    _bind_budget,
    _cached_excavation,
    _deepen_if_scheduled,
    _elapsed_access_proposal,
    _fingerprint,
    _make_access_plan,
    _next_allowance,
    _progressive_excavation,
    _run_allowance,
    _scope_fingerprint,
    _screen_card,
    _span,
    excavation_cache_key,
    excavation_cache_lookup,
    excavation_probe_category,
    plan_obstructed_access,
)
from spider.human_strategy.incumbent import verify_complete_solution
from spider.human_strategy.search_budget import (
    BudgetCoordinator,
    TacticalLimits,
    _classify,
    register_budget,
    unregister_budget,
)
from spider.human_strategy.strategic_frontier import StrategicFrontier
from spider.metrics import parse_moves_file, replay_actions
from spider.state_identity import canonical_state_key
from spider.human_strategy.profiles import resolve_profile
from spider.planner.backward_strategy import (
    _cheap_workspace_cost,
    workspace_probe_cache,
    workspace_probe_seconds,
    workspace_probe_timing,
)
from spider.planner.objective_realizer import RealizationStatus

import spider.human_strategy.foundation_direction as foundation_direction


HEARTS = "qh jh 10h 9h 8h 7h 6h 5h 4h 3h 2h ah"


def _cards(text: str):
    return [Card.parse(token) for token in text.split() if token]


def _state(columns, stock="", foundations=0) -> SpiderState:
    cols = []
    for index in range(10):
        spec = columns.get(index, ("", ""))
        if isinstance(spec, str):
            down, up = "", spec
        else:
            down, up = spec
        cols.append(Column(_cards(down), _cards(up)))
    found = []
    for count in range(foundations):
        suit = "shdc"[count % 4]
        found.append([Card(suit, rank) for rank in range(13, 0, -1)])
    return SpiderState(cols, _cards(stock), found)


def _micro():
    return _state({0: HEARTS, 1: "kh"}, foundations=7)


def _profile(**kwargs):
    base = dict(
        time_limit_s=1,
        max_steps=0,
        tactical_nodes=40,
        tactical_time_s=0.2,
        tactical_max_cost=1,
        consult_portfolio=False,
        strategic_width=1,
        max_width=1,
        frontier_limit=1,
        rss_abort_mb=8192,
    )
    base.update(kwargs)
    return resolve_profile("smoke").with_overrides(**base)


def _pad(columns):
    cols = list(columns)
    while len(cols) < 10:
        cols.append(Column([Card("d", 13)], [Card("s", 13)]))
    return SpiderState(cols, [])


def _view(suit="c"):
    return FoundationView(
        suit=suit,
        copy_index=1,
        label=f"{suit.upper()}#1",
        target_epoch=0,
        current_epoch=0,
        earliest_epoch=0,
        other_copy_earliest=None,
        estimated_cost=10.0,
        readiness="excavation_led",
        confidence="HIGH",
        theoretically_available=True,
        operationally_attainable=True,
        economically_attractive=True,
        face_up=1,
        face_down=1,
        stock_count=0,
        burial=2,
        longest_fragment=1,
        reasons=("fact: fixture campaign",),
    )


class _Campaign:
    def __init__(self, suit):
        self.suit = suit
        self.estimated_campaign_cost = 10.0
        self.rank_needs = ()


def _agenda(suit="c"):
    view = _view(suit)
    return FoundationAgenda(
        view=view,
        alternatives=(),
        prerequisites=(),
        protected_fragments=(),
        campaign_cost=10.0,
        target_epoch=0,
        current_epoch=0,
        stock_len=0,
        reasons=view.reasons,
    )


def _clubs_board():
    buried = Card("c", 8)
    state = _pad(
        [
            Column([buried], [Card("c", 6), Card("s", 3)]),
            Column([], [Card("d", 4)]),
            Column([], [Card("d", 7)]),
        ]
    )
    return state, buried


def _connector_board():
    """9c is the connector above an exposed 8c-7c run, so expansion stays relevant.

    7c can move onto 8s, so the position is not an obvious no-move screen.
    """

    buried = Card("c", 9)
    state = _pad(
        [
            Column([buried], [Card("c", 8), Card("c", 7)]),
            Column([], [Card("s", 8)]),
        ]
    )
    return state, buried


def _zero_board():
    """One node does not uncover 8c. Ah onto the empty column is a trap."""

    buried = Card("c", 8)
    state = _pad(
        [
            Column([buried], [Card("c", 6), Card("h", 1)]),
            Column([], []),
            Column([], [Card("d", 13)]),
        ]
    )
    return state, buried


class _Probe:
    def __init__(self, status):
        self.status = status
        self.corrected_mw_cost = None
        self.nodes_expanded = 1


def test_nested_span_keeps_exclusive_time_out_of_the_parent():
    lock = {}
    with _span(lock, "outer"):
        time.sleep(0.03)
        with _span(lock, "inner"):
            time.sleep(0.03)
    outer = lock["timing"]["outer"]
    inner = lock["timing"]["inner"]
    inclusive = lock["timing_inclusive"]["outer"]
    assert inclusive > outer
    assert abs((outer + inner) - inclusive) < 0.02
    assert "_time_stack" not in lock


def test_screening_does_not_search_a_card_that_is_already_classified():
    columns = [Column([], []) for _ in range(10)]
    columns[0] = Column([], [Card("h", 5)])
    columns[1] = Column([], [Card("s", 6)])
    movable = SpiderState(columns, [], [])
    head = columns[0].face_up[0]
    assert _screen_card(movable, head) == "already_movable"

    covered = [Column([], [Card("s", 13)]) for _ in range(10)]
    exposed = SpiderState(covered, [], [])
    king = covered[0].face_up[0]
    assert _screen_card(exposed, king) == "already_exposed"
    assert _screen_card(exposed, Card("h", 2)) == "absent"

    def boom(*_args, **_kwargs):
        raise AssertionError("screened card entered the excavation search")

    original = foundation_direction.plan_obstructed_access
    foundation_direction.plan_obstructed_access = boom
    try:
        lock = {"tactical_schedule": "progressive"}
        plan = _progressive_excavation(
            movable,
            head,
            (),
            lock,
            source_key="tableau:0:up:0",
            column=0,
            time_left=5,
        )
    finally:
        foundation_direction.plan_obstructed_access = original
    assert plan.status == "already_movable"
    assert lock["probe_stats"]["screened"] == 1
    assert lock["probe_stats"]["misses"] == 0
    assert "excavation_cache" not in lock


def test_a_time_limit_is_not_a_node_cap_and_the_same_node_cap_is_not_repeated():
    state, buried = _clubs_board()
    calls = []

    def fake(*_args, **_kwargs):
        calls.append(1)
        return _make_access_plan(
            (),
            0,
            "TIME_LIMIT",
            24,
            "tableau:0:down:0",
            0,
            2,
            2,
            (),
            stop="TIME_LIMIT",
            max_cost_limit=4,
            max_nodes_limit=500,
        )

    original = foundation_direction.plan_obstructed_access
    foundation_direction.plan_obstructed_access = fake
    try:
        lock = {}
        first = _cached_excavation(
            state,
            buried,
            (),
            lock,
            source_key="tableau:0:down:0",
            column=0,
            max_cost=4,
            max_nodes=500,
            time_left=5,
            deadline_s=0.2,
        )
        assert first.status == "TIME_LIMIT"
        base = excavation_cache_key(
            foundation_direction._fingerprint(state),
            "tableau:0:down:0",
            False,
            4,
            500,
            "receiver-then-peel",
        )
        assert base not in lock["excavation_cache"]
        assert any(isinstance(key, tuple) and len(key) == 7 for key in lock["excavation_cache"])
        second = _cached_excavation(
            state,
            buried,
            (),
            lock,
            source_key="tableau:0:down:0",
            column=0,
            max_cost=4,
            max_nodes=500,
            time_left=5,
            deadline_s=2.0,
        )
        assert second is not first
        third = _cached_excavation(
            state,
            buried,
            (),
            lock,
            source_key="tableau:0:down:0",
            column=0,
            max_cost=4,
            max_nodes=500,
            time_left=5,
            deadline_s=0.2,
        )
        assert third is first
        assert len(calls) == 2
        assert lock["probe_stats"]["deadline_stops"] == 2
    finally:
        foundation_direction.plan_obstructed_access = original

    zero_state, zero_card = _zero_board()
    fresh = {}
    limited = _cached_excavation(
        zero_state,
        zero_card,
        (),
        fresh,
        source_key="tableau:0:down:0",
        column=0,
        max_cost=4,
        max_nodes=1,
        time_left=5,
    )
    assert limited.status == "NODE_LIMIT"
    repeated = _cached_excavation(
        zero_state,
        zero_card,
        (),
        fresh,
        source_key="tableau:0:down:0",
        column=0,
        max_cost=4,
        max_nodes=1,
        time_left=5,
    )
    assert repeated is limited
    assert fresh["probe_stats"]["misses"] == 1
    assert fresh["probe_stats"]["hits"] == 1


def test_allowance_grows_only_after_cover_falls_inside_the_node_budget():
    blind = _make_access_plan(
        (),
        0,
        "NODE_LIMIT",
        160,
        "src",
        0,
        4,
        4,
        (),
        stop="NODE_LIMIT",
        max_nodes_limit=160,
        max_cost_limit=4,
    )
    assert _next_allowance(blind, 5) is None
    timed = _make_access_plan(
        ((0, 1, 1),),
        1,
        "progress",
        160,
        "src",
        0,
        4,
        2,
        (),
        stop="TIME_LIMIT",
        max_nodes_limit=160,
        max_cost_limit=4,
    )
    assert _next_allowance(timed, 5) is None
    useful = _make_access_plan(
        ((0, 1, 1),),
        1,
        "progress",
        160,
        "src",
        0,
        4,
        2,
        (),
        stop="NODE_LIMIT",
        max_nodes_limit=160,
        max_cost_limit=4,
    )
    assert _next_allowance(useful, 5) == _PROGRESSIVE_LADDER[1]
    assert _next_allowance(useful, 0.1) is None
    deeper = _make_access_plan(
        ((0, 1, 1),),
        1,
        "progress",
        800,
        "src",
        0,
        4,
        1,
        (),
        stop="NODE_LIMIT",
        max_nodes_limit=800,
        max_cost_limit=6,
    )
    assert _next_allowance(deeper, 5) == _PROGRESSIVE_LADDER[2]
    done = _make_access_plan(
        ((0, 1, 1),),
        1,
        "exposed",
        160,
        "src",
        0,
        4,
        0,
        (),
        max_nodes_limit=160,
        max_cost_limit=4,
    )
    assert _next_allowance(done, 5) is None


def test_an_unscheduled_call_still_uses_the_historical_excavation_budgets():
    state, _buried = _connector_board()
    calls = []

    def fake(_state, _card, _protected, _lock, **kwargs):
        calls.append((kwargs["max_nodes"], kwargs["deadline_s"]))
        return _make_access_plan(
            (),
            0,
            "NODE_LIMIT",
            kwargs["max_nodes"],
            kwargs["source_key"],
            kwargs["column"],
            3,
            3,
            (),
            stop="NODE_LIMIT",
            max_cost_limit=kwargs["max_cost"],
            max_nodes_limit=kwargs["max_nodes"],
        )

    original = foundation_direction._cached_excavation
    foundation_direction._cached_excavation = fake
    try:
        _elapsed_access_proposal(state, 0, _Campaign("c"), _agenda(), {}, [], set(), 20.0)
    finally:
        foundation_direction._cached_excavation = original
    assert calls[0] == (2000, 3.0)
    assert (4500, 12.0) in calls


def test_progressive_search_starts_small_and_climbs_only_when_cover_falls():
    state, buried = _connector_board()
    calls = []

    def fake(_state, _card, _protected, **kwargs):
        nodes = kwargs["max_nodes"]
        calls.append(nodes)
        if nodes <= 160:
            return _make_access_plan(
                ((0, 1, 1),),
                1,
                "progress",
                20,
                kwargs.get("source_key", "src"),
                kwargs.get("column", 0),
                3,
                2,
                (),
                stop="NODE_LIMIT",
                max_cost_limit=kwargs["max_cost"],
                max_nodes_limit=nodes,
            )
        if nodes <= 800:
            return _make_access_plan(
                ((0, 1, 1),),
                1,
                "progress",
                40,
                kwargs.get("source_key", "src"),
                kwargs.get("column", 0),
                3,
                1,
                (),
                stop="NODE_LIMIT",
                max_cost_limit=kwargs["max_cost"],
                max_nodes_limit=nodes,
            )
        return _make_access_plan(
            ((0, 1, 1), (1, 2, 1)),
            2,
            "exposed",
            60,
            kwargs.get("source_key", "src"),
            kwargs.get("column", 0),
            3,
            0,
            (),
            max_cost_limit=kwargs["max_cost"],
            max_nodes_limit=nodes,
        )

    original = foundation_direction.plan_obstructed_access
    foundation_direction.plan_obstructed_access = fake
    try:
        lock = {"tactical_schedule": "progressive", "proposal_slice_s": 1.25}
        plan = _progressive_excavation(
            state,
            buried,
            (),
            lock,
            source_key="tableau:0:down:0",
            column=0,
            time_left=5,
        )
    finally:
        foundation_direction.plan_obstructed_access = original
    assert calls == [160, 800, 4500]
    assert plan.status == "exposed"
    assert lock["probe_stats"]["completed"] == 1
    assert lock["probe_stats"]["expanded"] == 2
    assert 12.0 not in calls

    stalled_calls = []

    def stalled(*_args, **kwargs):
        stalled_calls.append((kwargs["max_nodes"], kwargs.get("deadline")))
        return _make_access_plan(
            (),
            0,
            "NODE_LIMIT",
            kwargs["max_nodes"],
            kwargs.get("source_key", "src"),
            kwargs.get("column", 0),
            3,
            3,
            (),
            stop="NODE_LIMIT",
            max_cost_limit=kwargs["max_cost"],
            max_nodes_limit=kwargs["max_nodes"],
        )

    foundation_direction.plan_obstructed_access = stalled
    try:
        quiet = {"tactical_schedule": "progressive"}
        _progressive_excavation(
            state,
            buried,
            (),
            quiet,
            source_key="tableau:0:down:0",
            column=0,
            time_left=20,
        )
    finally:
        foundation_direction.plan_obstructed_access = original
    assert stalled_calls
    assert all(nodes == 160 for nodes, _deadline in stalled_calls)
    assert quiet["probe_stats"].get("level4", 0) == 0
    assert quiet["probe_stats"]["expanded"] == 0


def test_a_real_clubs_excavation_finishes_inside_the_first_search_allowance():
    state, buried = _clubs_board()
    events = []
    lock = {"tactical_schedule": "progressive", "proposal_slice_s": 1.25}
    proposal = _elapsed_access_proposal(
        state,
        0,
        _Campaign("c"),
        _agenda(),
        lock,
        events,
        set(),
        3.0,
    )
    text = "\n".join(events)
    assert proposal is not None
    assert proposal.candidate is not None
    assert len(proposal.candidate.actions) >= 2
    assert lock["probe_stats"].get("level2", 0) >= 1
    assert lock["probe_stats"].get("level4", 0) == 0
    assert "nodes 4500" not in text
    assert "nodes 2000" not in text
    assert buried is not None


def test_workspace_planning_is_timed_apart_from_its_cache(monkeypatch):
    calls = []

    def fake(_state, **_kwargs):
        calls.append(1)
        return _Probe(RealizationStatus.RESOURCE_LIMIT)

    monkeypatch.setattr("spider.planner.backward_strategy.realize_workspace", fake)
    state = SpiderState([Column([], [Card("s", 13)]) for _ in range(10)], [], [])
    timing = {}
    cache = {"hits": 0, "misses": 0, "negative_hits": 0}
    token_s = workspace_probe_seconds.set(0.08)
    token_c = workspace_probe_cache.set(cache)
    token_t = workspace_probe_timing.set(timing)
    try:
        first = _cheap_workspace_cost(state)
        second = _cheap_workspace_cost(state)
    finally:
        workspace_probe_seconds.reset(token_s)
        workspace_probe_cache.reset(token_c)
        workspace_probe_timing.reset(token_t)
    assert first[0] is None and second == first
    assert "no legal tableau move" in first[1]
    assert calls == []
    assert "workspace_screen" in timing
    assert timing["workspace_screen"] >= 0
    assert cache["misses"] == 1
    assert cache["hits"] == 1


def test_the_controller_slices_proposals_and_a_short_search_is_not_a_complete_game():
    deadline = time.perf_counter() + 30
    full = _proposal_time_left(deadline, {})
    sliced = _proposal_time_left(
        deadline,
        {"tactical_schedule": "progressive", "proposal_slice_s": 1.25},
    )
    assert full > 20
    assert 1.0 < sliced <= 1.25
    result = solve(_micro(), _profile(), mode="cold")
    assert result.solved is False
    assert result.foundations < 8
    assert result.provenance["best_verified_cost"] is None
    assert result.provenance["adaptive"] is False
    assert result.provenance["anchored_used"] is False
    assert result.provenance["cold_injection"] is False
    assert result.provenance["target_mode"] == "global"
    schedule = result.provenance["tactical_schedule"]
    assert schedule["name"] == "progressive"
    assert schedule["proposal_slice_s"] == 1.25
    assert schedule["time_limit_is_not_a_node_cap"] is True
    assert "remaining global deadline" in result.provenance["nested_budget"]
    assert "Do not add" in result.provenance["state_counts"]["note"]
    assert result.provenance["state_counts"]["unique_states_are_strategic"] is True
    assert result.provenance["unique_states_are_strategic"] is True
    assert "component_inclusive.execute" in result.provenance["timing_note"]
    assert result.provenance["budget"]["limits"]["ladder"][0]["max_nodes"] == 160
    assert result.provenance["tactical_schedule"]["levels"][1]["max_nodes"] == 160
    assert result.provenance["tactical_schedule"]["levels"][3]["max_nodes"] == 4500


DEAL = ROOT / "deals" / "4925153.txt"
MOVES_185 = ROOT / "solutions" / "4925153_autonomous_185.moves"
MOVES_172 = ROOT / "solutions" / "4925153_canonical.moves"
G83_PATH = ROOT / "tests" / "fixtures" / "g83_4925153_actions.json"


def _distinct(shift: int) -> SpiderState:
    columns = []
    for index in range(10):
        rank = ((index + shift) % 13) + 1
        suit = "shdc"[index % 4]
        columns.append(Column([Card("d", 13)], [Card(suit, rank)]))
    return SpiderState(columns, [])


def _register(limits=None, seconds=30.0):
    budget = BudgetCoordinator(time.perf_counter() + seconds, limits or TacticalLimits(), [])
    key = register_budget(budget)
    lock = {
        "tactical_schedule": "progressive",
        "proposal_slice_s": budget.limits.proposal_slice_s,
        "tactical_ladder": budget.limits.ladder,
        "budget_key": key,
        "alternatives_waiting": 0,
    }
    return budget, lock


def _node_limit(nodes=160, actions=(), depth_after=4):
    return _make_access_plan(
        actions,
        0 if not actions else 1,
        "NODE_LIMIT" if not actions else "progress",
        nodes,
        "tableau:0:down:0",
        0,
        4,
        depth_after,
        (),
        stop="NODE_LIMIT",
        max_cost_limit=4,
        max_nodes_limit=nodes,
    )


def test_the_global_deadline_clips_every_nested_allowance(monkeypatch):
    parent = time.perf_counter() + 0.02
    budget = BudgetCoordinator(parent, TacticalLimits(deep_share=0.15), [])
    assert budget.clip(30.0, 30.0) <= 0.03
    assert budget.clip(0.01, 30.0) <= 0.01
    deep = BudgetCoordinator(time.perf_counter() + 10.0, TacticalLimits(deep_share=0.15), [])
    clipped = deep.clip(1.25, 10.0, deep=True)
    assert clipped <= 1.5
    assert clipped <= 10.0 * 0.15 + 1e-9
    expired = BudgetCoordinator(time.perf_counter() - 1.0, TacticalLimits(), [])
    assert expired.clip(5.0, 5.0) == 0.0
    key = register_budget(expired)
    lock = {"budget_key": key}

    def forbidden(*_args, **_kwargs):
        raise AssertionError("a nested probe ran after the parent deadline")

    monkeypatch.setattr(foundation_direction, "plan_obstructed_access", forbidden)
    try:
        plan = _run_allowance(
            _connector_board()[0],
            _connector_board()[1],
            (),
            lock,
            source_key="tableau:0:down:0",
            column=0,
            time_left=30.0,
            level=4,
            max_cost=8,
            max_nodes=4500,
            deadline_s=12.0,
            announce=None,
            escalated=True,
        )
    finally:
        unregister_budget(key)
    assert plan.status == "TIME_LIMIT"
    assert plan.stop == "TIME_LIMIT"
    assert plan.nodes == 0


def test_one_scheduled_probe_returns_without_spending_the_deep_cap():
    state, buried = _connector_board()
    budget, lock = _register()
    calls = []

    def fake(_state, _card, _protected, **kwargs):
        calls.append(kwargs["max_nodes"])
        return _node_limit(kwargs["max_nodes"])

    original = foundation_direction.plan_obstructed_access
    foundation_direction.plan_obstructed_access = fake
    try:
        _bind_budget(lock)
        plan = _progressive_excavation(
            state,
            buried,
            (),
            lock,
            source_key="tableau:0:down:0",
            column=0,
            time_left=5.0,
        )
    finally:
        foundation_direction.plan_obstructed_access = original
        unregister_budget(lock["budget_key"])
    assert calls == [160]
    assert plan.status == "NODE_LIMIT"
    assert budget.nodes_granted == 160
    assert lock["probe_stats"]["level4"] == 0


def test_a_real_probe_never_expands_past_its_node_allowance():
    state, buried = _zero_board()
    started = time.perf_counter()
    plan = plan_obstructed_access(
        state,
        buried,
        (),
        max_cost=4,
        max_nodes=1,
        deadline=started + 2.0,
    )
    assert plan is not None
    assert plan.nodes <= 1
    assert plan.status == "NODE_LIMIT"
    assert plan.exhaustive is False
    assert excavation_probe_category(plan) == "NODE_LIMIT"
    stopped = plan_obstructed_access(
        state,
        buried,
        (),
        max_cost=8,
        max_nodes=400,
        deadline=time.perf_counter() - 1.0,
    )
    assert stopped.status == "TIME_LIMIT"
    assert stopped.nodes == 0
    assert stopped.exhaustive is False


def test_a_useful_partial_can_deepen_and_a_blind_cap_cannot():
    state, buried = _connector_board()
    budget, lock = _register(seconds=20.0)
    calls = []

    def fake(_state, _card, _protected, **kwargs):
        nodes = kwargs["max_nodes"]
        calls.append(nodes)
        if nodes <= 160:
            return _make_access_plan(
                ((1, 0, 1),),
                1,
                "progress",
                20,
                kwargs.get("source_key", "src"),
                0,
                3,
                2,
                (),
                stop="NODE_LIMIT",
                max_cost_limit=kwargs["max_cost"],
                max_nodes_limit=nodes,
            )
        return _make_access_plan(
            ((1, 0, 1),),
            1,
            "progress",
            40,
            kwargs.get("source_key", "src"),
            0,
            3,
            1,
            (),
            stop="NODE_LIMIT",
            max_cost_limit=kwargs["max_cost"],
            max_nodes_limit=nodes,
        )

    original = foundation_direction.plan_obstructed_access
    foundation_direction.plan_obstructed_access = fake
    try:
        _bind_budget(lock)
        _progressive_excavation(
            state, buried, (), lock, source_key="buried-a", column=0, time_left=5.0
        )
        deepened = _deepen_if_scheduled(state, (), lock, 5.0)
    finally:
        foundation_direction.plan_obstructed_access = original
        unregister_budget(lock["budget_key"])
    assert calls == [160, 800]
    assert deepened is not None
    assert deepened.max_nodes_limit == 800
    assert budget.deepened == 1
    assert 4500 not in calls
    blind, blind_lock = _register()
    try:
        _bind_budget(blind_lock)
        decision = blind.begin_probe(state, "buried-a", 0, buried, 5.0)
        assert decision.kind == "search"
        blind.finish(state, "buried-a", 0, buried, _node_limit(), decision.allowance, 0.01)
        again = blind.begin_probe(state, "buried-a", 0, buried, 5.0)
        assert again.kind == "defer"
        assert blind.identical_skips == 1
        assert _classify(_node_limit()) == "resource_limited"
    finally:
        unregister_budget(blind_lock["budget_key"])


def test_success_and_scoped_exhaustion_reuse_and_a_smaller_miss_does_not():
    state, _buried = _connector_board()
    fingerprint = _fingerprint(state)
    success = _make_access_plan(
        ((1, 0, 1),),
        1,
        "unlocked",
        12,
        "tableau:0:down:0",
        0,
        2,
        0,
        (),
        max_cost_limit=4,
        max_nodes_limit=160,
    )
    success_key = excavation_cache_key(fingerprint, "tableau:0:down:0", False, 4, 160, "receiver-then-peel")
    wider = excavation_cache_key(fingerprint, "tableau:0:down:0", False, 8, 4500, "receiver-then-peel")
    cache = {success_key: success}
    assert excavation_cache_lookup(cache, wider) is success
    exhausted = _make_access_plan(
        (),
        0,
        "GRAPH_EXHAUSTED_WITHIN_BOUND",
        48,
        "tableau:0:down:0",
        0,
        2,
        2,
        (),
        exhaustive=True,
        stop="GRAPH_EXHAUSTED_WITHIN_BOUND",
        max_cost_limit=6,
        max_nodes_limit=800,
    )
    proved = excavation_cache_key(fingerprint, "src", False, 6, 800, "receiver-then-peel")
    smaller = excavation_cache_key(fingerprint, "src", False, 4, 160, "receiver-then-peel")
    larger = excavation_cache_key(fingerprint, "src", False, 8, 4500, "receiver-then-peel")
    negative = {proved: exhausted}
    assert excavation_cache_lookup(negative, smaller) is exhausted
    assert excavation_cache_lookup(negative, larger) is None
    limited = _node_limit()
    limited_key = excavation_cache_key(fingerprint, "tableau:0:down:0", False, 4, 160, "receiver-then-peel")
    bigger_nodes = excavation_cache_key(fingerprint, "tableau:0:down:0", False, 4, 800, "receiver-then-peel")
    held = {limited_key: limited}
    assert excavation_cache_lookup(held, limited_key) is limited
    assert excavation_cache_lookup(held, bigger_nodes) is None
    assert excavation_probe_category(limited) != "PROVEN_INFEASIBLE_UNDER_EXPLICIT_CONDITIONS"


def test_a_changed_board_or_deal_policy_cannot_reuse_the_old_conclusion():
    state, buried = _connector_board()
    stocked = _state({0: ("8c", "6c 3s"), 1: ("", "4d")}, stock="kh qs")
    other_stock = _state({0: ("8c", "6c 3s"), 1: ("", "4d")}, stock="as jd")
    quiet = _fingerprint(stocked)
    dealing = _scope_fingerprint(stocked, True)
    other = _scope_fingerprint(other_stock, True)
    assert quiet != dealing
    assert dealing != other
    miss = _make_access_plan(
        (),
        0,
        "GRAPH_EXHAUSTED_WITHIN_BOUND",
        10,
        "tableau:0:down:0",
        0,
        2,
        2,
        (),
        exhaustive=True,
        stop="GRAPH_EXHAUSTED_WITHIN_BOUND",
        max_cost_limit=4,
        max_nodes_limit=160,
    )
    off = excavation_cache_key(quiet, "tableau:0:down:0", False, 4, 160, "receiver-then-peel")
    on = excavation_cache_key(dealing, "tableau:0:down:0", True, 4, 160, "receiver-then-peel")
    cache = {off: miss}
    assert excavation_cache_lookup(cache, on) is None
    moved = _distinct(3)
    assert canonical_state_key(state) != canonical_state_key(moved)
    budget, _lock = _register()
    try:
        allowance = budget.limits.first()
        budget.finish(state, "tableau:0:down:0", 0, buried, _node_limit(), allowance, 0.01)
        same = budget.begin_probe(state, "tableau:0:down:0", 0, buried, 5.0)
        changed = budget.begin_probe(moved, "tableau:0:down:0", 0, buried, 5.0)
        assert same.kind == "defer"
        assert changed.kind == "search"
    finally:
        unregister_budget(_lock["budget_key"])


def test_deepening_yields_while_another_objective_still_gets_a_cheap_probe():
    state, buried = _connector_board()
    budget, lock = _register(seconds=20.0)
    lock["alternatives_waiting"] = 4
    calls = []

    def fake(_state, _card, _protected, **kwargs):
        calls.append((kwargs.get("source_key"), kwargs["max_nodes"]))
        return _make_access_plan(
            ((1, 0, 1),),
            1,
            "progress",
            15,
            kwargs.get("source_key", "src"),
            0,
            3,
            2,
            (),
            stop="NODE_LIMIT",
            max_cost_limit=kwargs["max_cost"],
            max_nodes_limit=kwargs["max_nodes"],
        )

    original = foundation_direction.plan_obstructed_access
    foundation_direction.plan_obstructed_access = fake
    try:
        _bind_budget(lock)
        _progressive_excavation(
            state, buried, (), lock, source_key="first-objective", column=0, time_left=5.0
        )
        _progressive_excavation(
            state, buried, (), lock, source_key="second-objective", column=1, time_left=5.0
        )
        held = _deepen_if_scheduled(state, (), lock, 5.0)
        assert held is None
        assert budget.pending_deepen is True
        assert calls == [("first-objective", 160), ("second-objective", 160)]
        assert any("another strategic line" in event for event in budget.events)
        assert budget.should_skip_proposal(canonical_state_key(state), "H#1", 4, ()) is False
        lock["alternatives_waiting"] = 0
        _bind_budget(lock)
        replayed = _progressive_excavation(
            state, buried, (), lock, source_key="first-objective", column=0, time_left=5.0
        )
        returned = _deepen_if_scheduled(state, (), lock, 5.0)
    finally:
        foundation_direction.plan_obstructed_access = original
        unregister_budget(lock["budget_key"])
    assert replayed is not None
    assert calls == [
        ("first-objective", 160),
        ("second-objective", 160),
        ("first-objective", 800),
    ]
    assert returned is not None
    assert returned.max_nodes_limit == 800
    assert budget.revisited == 1
    assert budget.deepened == 1
    assert budget.open_partials


def test_exact_state_duplicates_keep_the_cheapest_ancestry_and_a_full_beam_is_not_a_proof():
    frontier = StrategicFrontier(limit=8, proposals=3)
    state = _distinct(0)
    ident = canonical_state_key(state)
    accepted, _event = frontier.consider(
        state=state, g=10, actions=(), lock={}, force_id=None, reason="first", label="H#1", payload=None
    )
    assert accepted is True
    again, _event = frontier.consider(
        state=state, g=10, actions=(), lock={}, force_id=None, reason="same", label="H#1", payload=None
    )
    assert again is False
    assert frontier.generated == 1
    cheaper, _event = frontier.consider(
        state=state, g=4, actions=((0, 1, 1),), lock={}, force_id=None, reason="cheaper", label="C#1", payload=None
    )
    assert cheaper is True
    assert frontier.best_g[ident] == 4
    assert all(item.g == 4 for item in frontier.queue if item.token[0] == ident)
    later, _event = frontier.consider(
        state=state, g=12, actions=(), lock={}, force_id=None, reason="costlier", label="S#1", payload=None
    )
    assert later is False
    dominance = [item for item in frontier.exclusion_log if item["kind"] == "transposition_dominance"]
    assert dominance
    assert all(item["proof"] is True for item in dominance)
    assert frontier.best_g[ident] == 4
    other = _distinct(1)
    other_ok, _event = frontier.consider(
        state=other, g=3, actions=(), lock={}, force_id=None, reason="different", label="D#1", payload=None
    )
    assert other_ok is True
    assert canonical_state_key(other) != ident
    assert len(frontier.best_g) == 2

    packed = StrategicFrontier(limit=8, proposals=3)
    for index in range(8):
        kept, _event = packed.consider(
            state=_distinct(index),
            g=1,
            actions=(),
            lock={},
            force_id=None,
            reason=f"line {index}",
            label=f"L{index}",
            payload=None,
        )
        assert kept is True
    rejected, event = packed.consider(
        state=_distinct(8),
        g=1,
        actions=(),
        lock={},
        force_id=None,
        reason="ninth",
        label="L8",
        payload=None,
    )
    assert rejected is False
    assert "not exhaustion" in event
    assert packed.exclusion_log[-1]["kind"] == "heuristic_admission"
    assert packed.exclusion_log[-1]["proof"] is False


def test_a_zero_second_solve_reports_time_limit_and_a_custom_ladder_is_visible():
    stopped = solve(_micro(), _profile(time_limit_s=0, max_steps=5), mode="cold")
    assert stopped.status == "TIME_LIMIT"
    assert stopped.provenance["search_status"] == "TIME_LIMIT"
    assert stopped.provenance["resource_stops"] >= 1
    assert stopped.solved is False
    assert stopped.provenance["best_verified_cost"] is None
    assert "PLANNING_STALL" in stopped.provenance["planning_stall_is_not_time_limit"]
    assert "TIME_LIMIT" in stopped.provenance["planning_stall_is_not_time_limit"]
    custom = TacticalLimits(
        proposal_slice_s=0.4,
        ladder=((2, 4, 11, 0.05), (3, 6, 22, 0.1), (4, 8, 33, 0.2)),
    )
    shown = solve(_micro(), _profile(), mode="cold", schedule=custom)
    levels = shown.provenance["tactical_schedule"]["levels"]
    assert shown.provenance["tactical_schedule"]["proposal_slice_s"] == 0.4
    assert levels[1]["max_nodes"] == 11
    assert levels[3]["max_nodes"] == 33
    assert shown.provenance["budget"]["limits"]["ladder"][2]["max_nodes"] == 33
    assert shown.provenance["cold_injection"] is False


def test_g19_and_g83_prefixes_and_both_complete_routes_stay_valid():
    payload = json.loads(G83_PATH.read_text(encoding="utf-8"))

    def _parse(text):
        parts = text.split()
        if parts[0] == "deal":
            return ("deal",)
        return (int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3]))

    actions = tuple(_parse(text) for text in payload["actions"])
    opening = SpiderState.from_cards(list(load_deal(DEAL)))
    early = opening.clone()
    assert replay_actions(early, list(actions[:19])) == 19
    assert actions[18] == (1, 0, 12)
    assert len(early.foundations) == 1
    assert early.foundations[0][0].suit == "s"
    assert early.is_solved() is False
    full = opening.clone()
    assert replay_actions(full, list(actions)) == 83
    assert [item[0].suit for item in full.foundations] == ["s", "c"]
    assert full.is_solved() is False
    route_185 = verify_complete_solution(
        opening.clone(),
        parse_moves_file(MOVES_185),
        expected_cost=185,
        source="imported",
        source_id=str(MOVES_185),
    )
    route_172 = verify_complete_solution(
        opening.clone(),
        parse_moves_file(MOVES_172),
        expected_cost=172,
        source="imported",
        source_id=str(MOVES_172),
    )
    assert route_185.solved is True and route_185.cost == 185
    assert route_172.solved is True and route_172.cost == 172
    try:
        optimise_anchored(opening, route_185.actions, mode="cold", time_limit_s=0, source="imported")
        refused = False
    except AnchoredRefused:
        refused = True
    assert refused is True
    anchored = optimise_anchored(
        opening.clone(),
        route_185.actions,
        mode="anchored",
        time_limit_s=0,
        adaptive=True,
        source="imported",
        source_id="v0.120-smoke",
        expected_cost=185,
    )
    assert anchored.cumulative_g == 185
    assert anchored.solved is True
    assert anchored.provenance["improved"] is False
    assert anchored.provenance["target_mode"] == "multi-checkpoint"


def test_matched_horizon_fixed_and_adaptive_search_both_see_checkpoint_11():
    opening = _micro()
    actions = (
        (0, 3, 1),
        (3, 4, 1),
        (4, 5, 1),
        (5, 6, 1),
        (6, 7, 1),
        (7, 8, 1),
        (8, 9, 1),
        (1, 2, 1),
        (2, 3, 1),
        (3, 4, 1),
        (9, 0, 1),
        (0, 4, 12),
    )
    checkpoints = build_checkpoints(opening, actions)
    horizon = [(item.state, item.g, item.index) for item in checkpoints[1:12]]
    assert horizon[-1][2] == 11
    fixed = search_segment(
        opening,
        checkpoints[11].state,
        checkpoints[11].g,
        time_limit_s=3,
        max_unique=1500,
    )
    adaptive = search_targets(opening, horizon, time_limit_s=3, max_unique=1500)
    assert fixed.status == "FOUND"
    assert adaptive.status == "FOUND"
    assert adaptive.target_index == 11
    assert fixed.cost == adaptive.cost
    assert fixed.cost is not None and fixed.cost < checkpoints[11].g
    assert fixed.expanded >= 1
    assert adaptive.expanded >= 1


def test_a_short_live_solve_shares_probes_and_keeps_the_deep_cap_idle():
    """The opening plays cheap moves, then several buried objectives, inside one deadline.

    An empty or exhausted probe stays at the first allowance. The same objective
    can be searched again after the board changes, and an unchanged board does
    not buy another identical search.
    """

    opening = SpiderState.from_cards(list(load_deal(DEAL)))
    result = solve(
        opening,
        _profile(
            time_limit_s=6,
            max_steps=80,
            frontier_limit=8,
            proposals_per_decision=3,
            slice_steps=4,
            line_attempt_cap=8,
        ),
        mode="cold",
        goal="foundations",
        deal_cards=list(load_deal(DEAL)),
        target_foundations=8,
    )
    budget = result.provenance["budget"]
    probe = result.provenance["excavation_probe_stats"]
    assert result.status == "TIME_LIMIT"
    assert result.provenance["search_status"] == "TIME_LIMIT"
    assert result.solved is False
    assert result.provenance["best_verified_cost"] is None
    assert result.provenance["cold_injection"] is False
    assert result.provenance["frontier"]["limit"] == 8
    assert result.objectives_attempted >= 8
    assert probe.get("level4", 0) == 0
    assert budget["limits"]["ladder"][-1]["max_nodes"] == 4500
    assert budget["nodes_granted"] > 0
    assert budget["nodes_used"] < budget["nodes_granted"]
    assert budget["classifications"].get("proved_impossible", 0) == 0
    assert len(budget["objective_work"]) >= 2
    assert budget["identical_skips"] >= 1
    assert any(item["visits"] >= 2 for item in budget["objective_work"])
    assert all(item["nodes"] <= 960 * item["visits"] for item in budget["objective_work"])
    assert "nodes 4500" not in "\n".join(result.events)
