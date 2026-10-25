"""v0.121 workspace screening, nonmonotone deepening, and termination causes.

The boards in this file are fixtures. The solver does not store their moves.
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
from spider.human_strategy.anchored import AnchoredRefused, optimise_anchored
from spider.human_strategy.controller import solve
from spider.human_strategy.foundation_direction import (
    _bind_budget,
    _cover_depth,
    _deepen_if_scheduled,
    _make_access_plan,
    _progressive_excavation,
    plan_obstructed_access,
)
from spider.human_strategy.incumbent import verify_complete_solution
from spider.human_strategy.preparation import resolve_termination
from spider.human_strategy.profiles import resolve_profile
from spider.human_strategy.search_budget import (
    BudgetCoordinator,
    TacticalLimits,
    _nonmonotone_reason,
    register_budget,
    unregister_budget,
)
from spider.human_strategy.strategic_frontier import StrategicFrontier, strategic_progress
from spider.metrics import parse_moves_file, replay_actions
from spider.planner.backward_strategy import (
    _cheap_workspace_cost,
    _screen_workspace,
    workspace_probe_cache,
    workspace_probe_deadline,
    workspace_probe_seconds,
)
from spider.planner.objective_realizer import RealizationStatus
from spider.state_identity import canonical_state_key

DEAL = ROOT / "deals" / "4925153.txt"
MOVES_185 = ROOT / "solutions" / "4925153_autonomous_185.moves"
MOVES_172 = ROOT / "solutions" / "4925153_canonical.moves"
G83_PATH = ROOT / "tests" / "fixtures" / "g83_4925153_actions.json"


def _register(seconds=30.0):
    budget = BudgetCoordinator(time.perf_counter() + seconds, TacticalLimits(), [])
    key = register_budget(budget)
    lock = {
        "tactical_schedule": "progressive",
        "proposal_slice_s": budget.limits.proposal_slice_s,
        "tactical_ladder": budget.limits.ladder,
        "budget_key": key,
        "alternatives_waiting": 0,
    }
    return budget, lock


def _parking_board():
    """9c stays covered until a receiver is built, and free kings fill a small search.

    Moving the mixed cover straight onto the only empty column leaves the next
    card with nowhere to go, so the first allowance does not reduce cover.
    """

    target = Card("c", 9)
    columns = [
        Column([target], [Card("c", 8), Card("h", 7)]),
        Column([], [Card("d", 8), Card("c", 2)]),
        Column([], [Card("h", 3)]),
        Column([], []),
        Column([], [Card("s", 13)]),
        Column([], [Card("h", 13)]),
        Column([], [Card("d", 13)]),
        Column([], [Card("c", 13)]),
        Column([Card("d", 12)], [Card("s", 12)]),
        Column([Card("h", 12)], [Card("c", 12)]),
    ]
    return SpiderState(columns, []), target


def _two_move_workspace():
    """2c must move onto 3h before 5s can move onto the exposed 6d.

    No single legal move empties a column. The second ply does.
    """

    return SpiderState(
        [
            Column([], [Card("s", 5)]),
            Column([], [Card("d", 6), Card("c", 2)]),
            Column([], [Card("h", 3)]),
            Column([Card("c", 13)], [Card("d", 9)]),
            Column([Card("h", 13)], [Card("c", 9)]),
            Column([Card("s", 12)], [Card("d", 8)]),
            Column([Card("c", 12)], [Card("h", 8)]),
            Column([Card("d", 11)], [Card("s", 10)]),
            Column([Card("h", 11)], [Card("c", 10)]),
            Column([Card("s", 11)], [Card("d", 10)]),
        ],
        [],
    )


def _parse_g83():
    payload = json.loads(G83_PATH.read_text(encoding="utf-8"))

    def parse(text):
        parts = text.split()
        if parts[0] == "deal":
            return ("deal",)
        return (int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3]))

    return tuple(parse(text) for text in payload["actions"])


def test_a_two_move_legal_screen_answers_without_the_heavy_search(monkeypatch):
    calls = []

    def fake(_state, **_kwargs):
        calls.append(1)
        raise AssertionError("the screen should have answered")

    monkeypatch.setattr("spider.planner.backward_strategy.realize_workspace", fake)
    state = _two_move_workspace()
    screened = _screen_workspace(state, 6)
    assert screened is not None
    assert screened[0] == 2
    assert screened[2] == "legal_two_move"
    cache = {"hits": 0, "misses": 0, "negative_hits": 0}
    token_s = workspace_probe_seconds.set(0.08)
    token_c = workspace_probe_cache.set(cache)
    try:
        found = _cheap_workspace_cost(state)
        again = _cheap_workspace_cost(state)
    finally:
        workspace_probe_seconds.reset(token_s)
        workspace_probe_cache.reset(token_c)
    assert found == (2, "fact: one legal move leaves a one-move create")
    assert again == found
    assert cache["misses"] == 1
    assert cache["hits"] == 1
    assert calls == []
    trial = state.clone()
    trial.move(1, 2, 1)
    assert _child_creates(trial)


def _child_creates(state):
    from spider.planner.workspace_obstruction import profile_state

    return any(profile.one_move_creates for profile in profile_state(state))


def test_structural_and_no_move_screens_are_not_proofs_and_do_not_cross_budgets(monkeypatch):
    calls = []

    def fake(_state, **kwargs):
        calls.append((kwargs.get("time_limit_s"), kwargs.get("max_nodes"), kwargs.get("max_cost")))
        probe = type("Probe", (), {})()
        probe.status = RealizationStatus.RESOURCE_LIMIT
        probe.corrected_mw_cost = None
        probe.nodes_expanded = 1
        return probe

    monkeypatch.setattr("spider.planner.backward_strategy.realize_workspace", fake)
    blocked = SpiderState([Column([Card("s", 1)], [Card("d", 13)]) for _ in range(10)], [])
    deep = SpiderState(
        [
            Column([Card("s", 1)] * 6, [Card("d", 3)]),
            Column([Card("h", 1)] * 6, [Card("c", 2)]),
        ]
        + [Column([Card("d", 1)] * 6, [Card("s", 13)]) for _ in range(8)],
        [],
    )
    cache = {"hits": 0, "misses": 0, "negative_hits": 0, "detail": True}
    token_s = workspace_probe_seconds.set(0.08)
    token_c = workspace_probe_cache.set(cache)
    try:
        none_move = _cheap_workspace_cost(blocked)
        repeat = _cheap_workspace_cost(blocked)
        other_cost = _cheap_workspace_cost(blocked, max_cost=2)
        buried = _cheap_workspace_cost(deep, max_cost=4)
        changed = blocked.clone()
        changed.columns[0].face_up.append(Card("c", 2))
        _cheap_workspace_cost(changed)
    finally:
        workspace_probe_seconds.reset(token_s)
        workspace_probe_cache.reset(token_c)
    assert none_move[0] is None and "no legal tableau move" in none_move[1]
    assert repeat == none_move
    assert cache["hits"] == 1
    assert other_cost[0] is None
    assert cache["hits"] == 1
    assert "inaccessible within cost 4" in buried[1]
    assert "not a proof" not in buried[1] or "inaccessible" in buried[1]
    assert calls == []
    assert cache["traces"]


def test_a_short_two_move_miss_does_not_answer_a_larger_node_budget(monkeypatch):
    calls = []

    def fake(_state, **kwargs):
        calls.append(kwargs.get("max_nodes"))
        probe = type("Probe", (), {})()
        probe.status = RealizationStatus.RESOURCE_LIMIT
        probe.corrected_mw_cost = None
        probe.nodes_expanded = 3
        return probe

    monkeypatch.setattr("spider.planner.backward_strategy.realize_workspace", fake)
    opening = SpiderState.from_cards(list(load_deal(DEAL)))
    cache = {"hits": 0, "misses": 0, "negative_hits": 0}
    token_s = workspace_probe_seconds.set(0.08)
    token_c = workspace_probe_cache.set(cache)
    try:
        short = _cheap_workspace_cost(opening)
        cached = _cheap_workspace_cost(opening)
        assert calls == []
        workspace_probe_seconds.set(0.35)
        wider = _cheap_workspace_cost(opening)
    finally:
        workspace_probe_seconds.reset(token_s)
        workspace_probe_cache.reset(token_c)
    assert short[0] is None and "not a proof" in short[1]
    assert cached == short
    assert wider[0] is None and "resource_limit" in wider[1]
    assert calls == [400]


def test_a_global_deadline_clips_a_workspace_probe_without_caching_the_clock(monkeypatch):
    calls = []

    def fake(_state, **_kwargs):
        calls.append(1)
        raise AssertionError("an expired clock must not search")

    monkeypatch.setattr("spider.planner.backward_strategy.realize_workspace", fake)
    state = _two_move_workspace()
    cache = {"hits": 0, "misses": 0, "negative_hits": 0}
    token_s = workspace_probe_seconds.set(0.08)
    token_c = workspace_probe_cache.set(cache)
    token_d = workspace_probe_deadline.set(time.perf_counter() - 1.0)
    try:
        stopped = _cheap_workspace_cost(state)
        stored = _cheap_workspace_cost(state)
    finally:
        workspace_probe_deadline.reset(token_d)
        workspace_probe_seconds.reset(token_s)
        workspace_probe_cache.reset(token_c)
    assert stopped == (None, "probe TIME_LIMIT")
    assert stored == stopped
    assert cache["misses"] == 2
    assert cache["hits"] == 0
    assert calls == []


def test_cover_reduction_still_deepens_and_a_blind_cap_does_not():
    state, target = _parking_board()
    budget, _lock = _register()
    try:
        allowance = budget.limits.first()
        useful = _make_access_plan(
            ((1, 0, 1),),
            1,
            "progress",
            160,
            "cover-falls",
            0,
            3,
            2,
            (),
            stop="NODE_LIMIT",
            max_cost_limit=4,
            max_nodes_limit=160,
        )
        budget.finish(state, "cover-falls", 0, target, useful, allowance, 0.01)
        grant = budget.take_deepen(5.0)
        assert grant is not None and grant.allowance.max_nodes == 800
        assert budget.nonmonotone_deepened == 0
        blind = _make_access_plan(
            (),
            0,
            "NODE_LIMIT",
            160,
            "blind",
            0,
            4,
            4,
            (),
            stop="NODE_LIMIT",
            max_cost_limit=4,
            max_nodes_limit=160,
        )
        quiet = SpiderState([Column([Card("d", 13)], [Card("s", 13)]) for _ in range(10)], [])
        assert _nonmonotone_reason(quiet, Card("c", 9), blind) == ""
        budget.finish(quiet, "blind", 0, Card("c", 9), blind, allowance, 0.01)
        assert budget.begin_probe(quiet, "blind", 0, Card("c", 9), 5.0).kind == "defer"
        assert "blind" not in {item.objective for item in budget.strategic_holds}
    finally:
        unregister_budget(_lock["budget_key"])


def test_a_blocked_objective_deepens_without_an_immediate_cover_drop():
    state, target = _parking_board()
    assert _cover_depth(state, target) == 2
    # The free-king cloud makes 160 nodes take longer than the production
    # 0.28s first slice. The node caps stay 160 and 800. The wider slice
    # lets the node cap, rather than the clock, stop the first probe.
    limits = TacticalLimits(
        proposal_slice_s=3.0,
        ladder=((2, 4, 160, 1.5), (3, 6, 800, 3.0), (4, 8, 4500, 1.25)),
    )
    budget = BudgetCoordinator(time.perf_counter() + 30.0, limits, [])
    key = register_budget(budget)
    lock = {
        "tactical_schedule": "progressive",
        "proposal_slice_s": limits.proposal_slice_s,
        "tactical_ladder": limits.ladder,
        "budget_key": key,
        "alternatives_waiting": 0,
    }
    started = time.perf_counter()
    try:
        _bind_budget(lock)
        small = _progressive_excavation(
            state,
            target,
            (),
            lock,
            source_key="tableau:0:down:0",
            column=0,
            time_left=20.0,
        )
        assert small is not None
        assert small.max_nodes_limit == 160
        assert small.depth_after >= small.depth_before
        assert small.status == "NODE_LIMIT"
        reason = _nonmonotone_reason(state, target, small)
        assert reason
        deepened = _deepen_if_scheduled(state, (), lock, 20.0)
    finally:
        unregister_budget(key)
    elapsed = time.perf_counter() - started
    assert deepened is not None
    assert deepened.max_nodes_limit == 800
    assert deepened.status in {"exposed", "unlocked", "progress"}
    assert deepened.depth_after < deepened.depth_before
    assert lock["probe_stats"].get("level4", 0) == 0
    assert budget.nonmonotone_deepened == 1
    assert budget.deepened == 1
    assert elapsed < 8.0
    assert budget.remaining() > 15.0
    replayed = state.clone()
    spent = replay_actions(replayed, list(deepened.actions))
    assert spent == deepened.cost
    assert _cover_depth(replayed, target) == deepened.depth_after
    first = state.clone()
    replay_actions(first, [deepened.actions[0]])
    assert _cover_depth(first, target) >= _cover_depth(state, target)
    assert any("deepen" == item["kind"] for item in budget.decision_log)


def test_a_nonmonotone_deepen_waits_while_another_objective_has_not_run():
    state, target = _parking_board()
    budget, _lock = _register()
    try:
        plan = _make_access_plan(
            (),
            0,
            "NODE_LIMIT",
            160,
            "held",
            0,
            2,
            2,
            (),
            stop="NODE_LIMIT",
            max_cost_limit=4,
            max_nodes_limit=160,
        )
        assert _nonmonotone_reason(state, target, plan)
        budget.finish(state, "held", 0, target, plan, budget.limits.first(), 0.01)
        budget.note_alternatives(2)
        budget.proposal_turns = 1
        assert budget.take_deepen(5.0) is None
        assert budget.pending_deepen is True
        assert budget.strategic_holds
        budget.note_alternatives(0)
        budget.proposal_turns = 4
        grant = budget.take_deepen(5.0)
        assert grant is not None
        assert grant.allowance.max_nodes == 800
        assert budget.nonmonotone_deepened == 1
        assert budget.limits.next_after(800).max_nodes == 4500
    finally:
        unregister_budget(_lock["budget_key"])


def test_termination_names_the_deadline_and_keeps_a_stall_secondary():
    clock = {"now": 50.0}

    def fake_clock():
        return clock["now"]

    import spider.human_strategy.search_budget as search_budget

    original = search_budget.time.perf_counter
    search_budget.time.perf_counter = fake_clock
    try:
        budget = BudgetCoordinator(55.0, TacticalLimits(), [])
        assert budget.clip(10.0, 10.0) == 5.0
        clock["now"] = 55.0
        assert budget.clip(10.0, 10.0) == 0.0
        assert budget.remaining() == 0.0
    finally:
        search_budget.time.perf_counter = original
    status, reason, info = resolve_termination(
        "PLANNING_STALL",
        "planning stall: 9 legal tableau moves remain",
        deadline_elapsed=True,
        legal_count=9,
    )
    assert status == "TIME_LIMIT"
    assert info["cause"] == "TIME_LIMIT"
    assert info["secondary"] == "PLANNING_STALL"
    assert info["legal_tableau_moves"] == 9
    assert "secondary PLANNING_STALL" in reason
    still, _reason, quiet = resolve_termination(
        "PLANNING_STALL",
        "planning stall: 9 legal tableau moves remain",
        deadline_elapsed=False,
        legal_count=9,
    )
    assert still == "PLANNING_STALL"
    assert quiet["secondary"] is None
    _status, _reason, bounded = resolve_termination(
        "GRAPH_EXHAUSTED_WITHIN_BOUND",
        "graph finished",
        deadline_elapsed=False,
        legal_count=0,
    )
    assert bounded["cause"] == "BOUNDED_EXHAUSTED"
    _status, _reason, capped = resolve_termination(
        "NODE_LIMIT",
        "node cap",
        deadline_elapsed=False,
        legal_count=3,
    )
    assert capped["cause"] == "NODE_LIMIT"


def test_exact_state_dominance_and_progress_are_not_a_proof_bound():
    frontier = StrategicFrontier(limit=8, proposals=3)
    state, _target = _parking_board()
    ident = canonical_state_key(state)
    kept, _event = frontier.consider(
        state=state, g=8, actions=(), lock={}, force_id=None, reason="first", label="C#1", payload=None
    )
    assert kept is True
    cheaper, _event = frontier.consider(
        state=state, g=3, actions=((0, 1, 1),), lock={}, force_id=None, reason="cheaper", label="H#1", payload=None
    )
    assert cheaper is True
    assert frontier.best_g[ident] == 3
    later, _event = frontier.consider(
        state=state, g=9, actions=(), lock={}, force_id=None, reason="costlier", label="S#1", payload=None
    )
    assert later is False
    assert all(item["proof"] is True for item in frontier.exclusion_log if item["kind"] == "transposition_dominance")
    progress = strategic_progress(state)
    assert progress["heuristic_only"] is True
    assert progress["foundations"] == 0
    assert progress["empty_columns"] == 1
    assert progress["same_suit_runs"] >= 0


def test_g83_prefix_stays_a_legal_two_foundation_line_and_cold_search_does_not_import_it():
    actions = _parse_g83()
    opening = SpiderState.from_cards(list(load_deal(DEAL)))
    played = opening.clone()
    assert replay_actions(played, list(actions)) == 83
    assert [item[0].suit for item in played.foundations] == ["s", "c"]
    buried = next(
        card
        for column in played.columns
        for card in column.face_down
        if card.suit == "h" and card.rank == 8
    )
    small = plan_obstructed_access(
        played,
        buried,
        (),
        source_key="tableau:6:down:0",
        column=6,
        max_cost=4,
        max_nodes=160,
        deadline=time.perf_counter() + 3.0,
    )
    assert small.depth_after >= small.depth_before
    assert _nonmonotone_reason(played, buried, small)
    cards = list(load_deal(DEAL))
    cold = solve(
        opening.clone(),
        resolve_profile("pilot").with_overrides(time_limit_s=0, max_steps=0, frontier_limit=8),
        mode="cold",
        goal="foundations",
        target_foundations=8,
        deal_cards=cards,
    )
    assert cold.provenance["cold_injection"] is False
    assert cold.provenance["best_verified_cost"] is None
    assert cold.actions == ()
    assert cold.status == "TIME_LIMIT"
    assert list(actions) != list(cold.actions)


def test_both_completed_routes_replay_and_a_partial_does_not_replace_them():
    opening = SpiderState.from_cards(list(load_deal(DEAL)))
    route_185 = verify_complete_solution(
        opening.clone(),
        parse_moves_file(MOVES_185),
        expected_cost=185,
        source="imported",
        source_id="185",
    )
    route_172 = verify_complete_solution(
        opening.clone(),
        parse_moves_file(MOVES_172),
        expected_cost=172,
        source="imported",
        source_id="172",
    )
    assert route_185.solved is True and route_185.cost == 185 and len(route_185.actions) > 0
    assert route_172.solved is True and route_172.cost == 172
    replayed = opening.clone()
    assert replay_actions(replayed, list(route_185.actions)) == 185
    assert replayed.is_solved() is True
    assert len(replayed.foundations) == 8
    try:
        optimise_anchored(opening, route_172.actions, mode="cold", time_limit_s=0, source="imported")
        refused = False
    except AnchoredRefused:
        refused = True
    assert refused is True
    anchored = optimise_anchored(
        opening.clone(),
        route_185.actions,
        mode="anchored",
        time_limit_s=0,
        adaptive=False,
        source="imported",
        source_id="v0.121",
        expected_cost=185,
    )
    assert anchored.cumulative_g == 185
    assert anchored.solved is True
    assert anchored.provenance["improved"] is False
