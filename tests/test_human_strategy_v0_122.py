"""v0.122 frontier recovery and reserved deep search.

The boards here are synthetic. The solver does not store their moves, and
the g83 fixture is replayed only as an audit.
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
from spider.human_strategy import SCHEMA_VERSION
from spider.human_strategy.anchored import AnchoredRefused, optimise_anchored
from spider.human_strategy.controller import reported_search_stop, solve
from spider.human_strategy.foundation_direction import (
    _make_access_plan,
    excavation_cache_key,
    excavation_cache_lookup,
)
from spider.human_strategy.incumbent import IncumbentRejected, proof_prune, verify_complete_solution
from spider.human_strategy.preparation import resolve_termination
from spider.human_strategy.profiles import resolve_profile
from spider.human_strategy.search_budget import (
    BudgetCoordinator,
    TacticalLimits,
    _nonmonotone_reason,
)
from spider.human_strategy.strategic_frontier import (
    StrategicFrontier,
    build_stall_audit,
    pin_named_successor,
)
from spider.metrics import parse_moves_file, replay_actions
from spider.research_actions import all_legal_actions
from spider.state_identity import canonical_state_key

DEAL = ROOT / "deals" / "4925153.txt"
MOVES_185 = ROOT / "solutions" / "4925153_autonomous_185.moves"
MOVES_172 = ROOT / "solutions" / "4925153_canonical.moves"
G83_PATH = ROOT / "tests" / "fixtures" / "g83_4925153_actions.json"


def _state(seed: int, stock: int = 0) -> SpiderState:
    columns = []
    for index in range(10):
        rank = ((seed + index * 3) % 13) + 1
        suit = "shdc"[(seed + index) % 4]
        columns.append(Column([Card("d", 13)], [Card(suit, rank)]))
    pile = [Card("c", ((seed + index) % 13) + 1) for index in range(stock)]
    return SpiderState(columns, pile)


def _admit(frontier, seed, g, label, force_id=None, lock=None, state=None):
    return frontier.consider(
        state=state if state is not None else _state(seed),
        g=g,
        actions=(),
        lock={} if lock is None else lock,
        force_id=force_id,
        reason=f"line {label}",
        label=label,
        payload=None,
    )


def _fill(frontier: StrategicFrontier) -> None:
    for index in range(frontier.limit):
        accepted, _event = _admit(frontier, index, 20 + index, f"L{index}")
        assert accepted is True


def _joinable(stock: int = 10) -> SpiderState:
    columns = [Column([Card("d", 13)], [Card("h", (index % 12) + 1)]) for index in range(10)]
    columns[0] = Column([], [Card("s", 9)])
    columns[1] = Column([], [Card("s", 8)])
    pile = [Card("c", (index % 13) + 1) for index in range(stock)]
    return SpiderState(columns, pile)


def _drain(frontier: StrategicFrontier) -> None:
    while frontier.queue:
        frontier.pop_next()


def _clock_plan(nodes, actions, status="progress", stop="TIME_LIMIT", depth=3):
    return _make_access_plan(
        actions,
        1 if actions else 0,
        status,
        nodes,
        "obj",
        0,
        depth,
        depth,
        (),
        stop=stop,
        max_cost_limit=4,
        max_nodes_limit=nodes,
    )


def _budget(seconds: float) -> BudgetCoordinator:
    budget = BudgetCoordinator(time.perf_counter() + seconds, TacticalLimits(), [])
    budget.proposal_turns = 4
    return budget


def _parse_g83():
    payload = json.loads(G83_PATH.read_text(encoding="utf-8"))

    def parse(text):
        parts = text.split()
        if parts[0] == "deal":
            return ("deal",)
        return (int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3]))

    return tuple(parse(text) for text in payload["actions"])


def test_schema_names_v0_122_and_the_ladder_deadline_stays_1_25():
    assert SCHEMA_VERSION == "spider-human-strategy-0.123"
    limits = TacticalLimits()
    assert limits.ladder[0] == (2, 4, 160, 0.28)
    assert limits.ladder[1] == (3, 6, 800, 0.55)
    assert limits.ladder[2] == (4, 8, 4500, 1.25)
    assert limits.deep_share == 0.15


def test_a_full_frontier_keeps_an_eligible_deferred_candidate():
    frontier = StrategicFrontier(limit=8, proposals=3)
    _fill(frontier)
    copy, _event = _admit(frontier, 0, 20, "COPY", force_id=None)
    assert copy is False
    assert all(node.label != "COPY" for node in frontier.deferred)
    accepted, event = _admit(frontier, 50, 30, "extra", force_id="PREPARE:move 2 1 1")
    assert accepted is False
    assert "not exhaustion" in event
    assert frontier.limit == 8
    assert len(frontier.queue) == 8
    assert frontier.dropped_full >= 1
    assert frontier.deferred_held == 1
    assert frontier.eligible_deferred()
    assert all(item["proof"] is False for item in frontier.exclusion_log if item["kind"] == "heuristic_admission")
    audit = build_stall_audit(frontier, _state(0), remaining_s=100.0, elapsed_s=1.0)
    assert audit["eligible_deferred"] == 1
    assert audit["could_explore_with_remaining_time"] is True
    assert audit["heuristic_discards"] >= 1
    assert "not graph exhaustion" in audit["policy_decision"]


def test_recovery_readmits_one_deferred_candidate_without_growing_the_cap():
    frontier = StrategicFrontier(limit=8, proposals=3)
    _fill(frontier)
    _admit(frontier, 50, 12, "extra", force_id="REVEAL:move 2 1 1")
    _drain(frontier)
    assert frontier.queue == []
    recovered = frontier.recover_one()
    assert recovered is not None
    assert recovered.force_id == "REVEAL:move 2 1 1"
    assert len(frontier.queue) == 1
    assert frontier.limit == 8
    assert frontier.generated == 8
    assert frontier.recoveries == 1
    assert frontier.recovered_states == 1
    popped = frontier.pop_next()
    assert popped is not None
    assert popped.token in frontier.expanded


def test_the_same_token_is_not_recovered_twice_and_the_limit_holds():
    frontier = StrategicFrontier(limit=8, proposals=3)
    frontier.recovery_limit = 1
    _fill(frontier)
    _admit(frontier, 50, 12, "first-drop", force_id="PREPARE:a")
    _admit(frontier, 51, 13, "second-drop", force_id="PREPARE:b")
    assert len(frontier.eligible_deferred()) == 2
    _drain(frontier)
    first = frontier.recover_one()
    assert first is not None
    frontier.pop_next()
    frontier._hold_deferred(first, equivalent=False)
    assert all(item.token != first.token for item in frontier.deferred)
    second = frontier.recover_one()
    assert second is None
    assert frontier.recoveries == 1
    assert frontier.recovery_attempts == 2
    assert frontier.deferred
    audit = build_stall_audit(frontier, _state(0), remaining_s=40.0, elapsed_s=2.0)
    assert audit["could_explore_with_remaining_time"] is False
    assert "recovery limit" in audit["policy_decision"]


def test_recovery_keeps_dominance_and_prefers_the_cheaper_valid_ancestry():
    frontier = StrategicFrontier(limit=8, proposals=3)
    _fill(frontier)
    later = _state(50)
    ident = canonical_state_key(later)
    dropped, _event = _admit(frontier, 50, 9, "later", force_id="old", state=later)
    assert dropped is False
    assert any(node.g == 9 and node.token[0] == ident for node in frontier.deferred)
    cheaper, _event = _admit(frontier, 50, 4, "sooner", force_id="new", state=later)
    assert cheaper is False
    assert frontier.best_g[ident] == 4
    assert all(node.g <= 4 for node in frontier.deferred if node.token[0] == ident)
    assert not any(node.force_id == "old" for node in frontier.deferred)
    _drain(frontier)
    recovered = frontier.recover_one()
    assert recovered is not None
    assert recovered.g == 4
    assert recovered.token[0] == ident
    rejected, _event = _admit(frontier, 50, 9, "later", force_id="old", state=later)
    assert rejected is False
    assert any(item["proof"] is True and item["kind"] == "transposition_dominance" for item in frontier.exclusion_log)
    assert not any(node.g == 9 for node in frontier.deferred)
    assert frontier.transpositions >= 1


def test_heuristic_rejection_is_not_recorded_as_proved_exhaustion():
    frontier = StrategicFrontier(limit=8, proposals=3)
    _fill(frontier)
    _admit(frontier, 50, 11, "held", force_id="PREPARE:move 1 2 1")
    heuristic = [item for item in frontier.exclusion_log if item["kind"] == "heuristic_admission"]
    assert heuristic
    assert all(item["proof"] is False for item in heuristic)
    dominated = _state(1)
    _admit(frontier, 1, 100, "costlier", state=dominated)
    assert any(item["proof"] is True for item in frontier.exclusion_log)
    state = _state(3)
    card = Card("h", 8)
    budget = _budget(30.0)
    exhausted = _make_access_plan(
        (),
        0,
        "GRAPH_EXHAUSTED_WITHIN_BOUND",
        20,
        "gone",
        0,
        2,
        2,
        (),
        stop="GRAPH_EXHAUSTED_WITHIN_BOUND",
        max_cost_limit=4,
        max_nodes_limit=160,
    )
    budget.finish(state, "gone", 0, card, exhausted, budget.limits.first(), 0.01)
    assert budget.begin_probe(state, "gone", 0, card, 1.0).kind == "replay"
    assert "gone" not in {item.objective for item in budget.strategic_holds}
    assert "gone" not in {item.objective for item in budget.deep_ready}
    limited = _clock_plan(160, ((1, 0, 1),))
    assert _nonmonotone_reason(state, card, limited)
    budget.finish(state, "open", 0, card, limited, budget.limits.first(), 0.01)
    assert any(item.objective == "open" for item in budget.strategic_holds)
    assert budget.classifications.get("proved_impossible", 0) == 0


def test_a_legal_alternative_from_an_earlier_state_can_be_recovered():
    frontier = StrategicFrontier(limit=8, proposals=3)
    board = _joinable()
    legal = (1, 0, 1)
    assert legal in all_legal_actions(board)
    _fill(frontier)
    accepted, _event = _admit(
        frontier,
        0,
        6,
        "pinned",
        force_id="pinned:move 2 1 1",
        lock={"pinned_actions": [legal]},
        state=board,
    )
    assert accepted is False
    _drain(frontier)
    recovered = frontier.recover_one()
    assert recovered is not None
    assert recovered.lock["pinned_actions"] == [legal]
    assert recovered.token[0] == canonical_state_key(board)


def test_a_recovered_named_successor_is_pinned_when_it_is_legal():
    frontier = StrategicFrontier(limit=8, proposals=3)
    board = _joinable()
    legal = (1, 0, 1)
    assert legal in all_legal_actions(board)
    assert (0, 1, 1) not in all_legal_actions(board)
    _fill(frontier)
    _admit(frontier, 50, 1, "stretch", force_id="STRETCH:create_workspace")
    _admit(frontier, 0, 40, "park", force_id="PARK:move 2 1 1", state=board)
    _drain(frontier)
    recovered = frontier.recover_one()
    assert recovered is not None
    assert recovered.force_id == "PARK:move 2 1 1"
    assert pin_named_successor(recovered) is True
    assert recovered.lock["pinned_actions"] == [legal]
    assert pin_named_successor(recovered) is False
    assert recovered.lock["pinned_actions"] == [legal]
    stretch = next(node for node in frontier.deferred if node.force_id == "STRETCH:create_workspace")
    assert pin_named_successor(stretch) is False
    assert "pinned_actions" not in stretch.lock


def test_an_illegal_named_move_is_not_pinned():
    frontier = StrategicFrontier(limit=8, proposals=3)
    board = _joinable()
    _fill(frontier)
    _admit(frontier, 0, 9, "bad", force_id="PARK:move 1 2 1", state=board)
    _drain(frontier)
    recovered = frontier.recover_one()
    assert recovered is not None
    assert pin_named_successor(recovered) is False
    assert "pinned_actions" not in recovered.lock


def test_an_illegal_pin_is_not_recovered_and_a_stock_deal_is():
    frontier = StrategicFrontier(limit=8, proposals=3)
    board = _joinable(stock=10)
    assert ("deal",) in all_legal_actions(board)
    _fill(frontier)
    _admit(
        frontier,
        0,
        6,
        "deal",
        force_id="pinned:deal",
        lock={"pinned_actions": [("deal",)]},
        state=board,
    )
    _drain(frontier)
    recovered = frontier.recover_one()
    assert recovered is not None
    assert recovered.lock["pinned_actions"] == [("deal",)]
    audit = build_stall_audit(frontier, board, remaining_s=20.0, elapsed_s=1.0)
    assert audit["legal_stock_deals"] >= 1

    blocked = StrategicFrontier(limit=8, proposals=3)
    dry = _joinable(stock=0)
    assert ("deal",) not in all_legal_actions(dry)
    _fill(blocked)
    _admit(
        blocked,
        0,
        6,
        "dry-deal",
        force_id="pinned:deal",
        lock={"pinned_actions": [("deal",)]},
        state=dry,
    )
    _drain(blocked)
    assert blocked.recover_one() is None
    assert blocked.eligible_deferred() == []


def test_a_bounded_tactical_miss_stays_eligible_for_a_larger_allowance():
    state = _state(4)
    card = Card("h", 8)
    stopped = _clock_plan(120, ((1, 0, 1),))
    assert stopped.stop == "TIME_LIMIT"
    assert _nonmonotone_reason(state, card, stopped)
    silent = _clock_plan(0, (), status="TIME_LIMIT", stop="TIME_LIMIT")
    assert _nonmonotone_reason(state, card, silent) == ""
    blind = _clock_plan(160, (), status="NODE_LIMIT", stop="NODE_LIMIT", depth=4)
    assert _nonmonotone_reason(state, card, blind) == ""
    budget = _budget(90.0)
    budget.finish(state, "buried", 0, card, stopped, budget.limits.first(), 0.01)
    assert budget.classifications["resource_limited"] >= 1
    assert budget.classifications.get("exhausted_within_bound", 0) == 0
    decision = budget.begin_probe(state, "buried", 0, card, 1.25)
    assert decision.kind == "search"
    assert decision.allowance is not None
    assert decision.allowance.max_nodes == 160
    assert decision.allowance.max_nodes < 800
    grant = budget.take_deepen(1.25)
    assert grant is not None
    assert grant.allowance.max_nodes == 800


def test_the_160_node_probe_can_progress_to_800_and_not_straight_to_4500():
    state = _state(5)
    card = Card("h", 8)
    budget = _budget(90.0)
    budget.finish(state, "cover", 0, card, _clock_plan(120, ((1, 0, 1),)), budget.limits.first(), 0.01)
    assert budget.strategic_holds
    assert budget.deep_ready == []
    grant = budget.take_deepen(1.25)
    assert grant is not None
    assert grant.allowance.max_nodes == 800
    assert grant.allowance.reserved_deep is False
    assert budget.nonmonotone_deepened == 1
    assert budget.deep_used == 0
    assert 4500 not in {item.allowance_nodes for item in budget.strategic_holds}


def test_an_800_node_miss_can_reach_the_reserved_4500_node_rung():
    state = _state(6)
    card = Card("h", 8)
    budget = _budget(90.0)
    middle = budget.limits.next_after(160)
    assert middle is not None and middle.max_nodes == 800
    budget.finish(state, "deep-card", 0, card, _clock_plan(264, ((1, 0, 1),)), middle, 0.2)
    assert budget.deep_ready
    assert budget.strategic_holds == []
    grant = budget.take_deepen(1.25)
    assert grant is not None
    assert grant.allowance.max_nodes == 4500
    assert grant.allowance.reserved_deep is True
    assert 6.5 <= grant.allowance.deadline_s <= 12.0
    assert budget.deep_used == 1
    assert budget.nonmonotone_deepened == 0
    assert any("node budget and time budget are separate" in event for event in budget.events)
    budget.begin_proposal()
    assert budget.take_deepen(1.25) is None


def test_cover_that_does_not_fall_can_still_justify_the_next_rung():
    state = _state(7)
    card = Card("c", 9)
    plan = _clock_plan(160, ((0, 1, 1),))
    assert plan.depth_after == plan.depth_before
    reason = _nonmonotone_reason(state, card, plan)
    assert "cover unchanged" in reason
    budget = _budget(90.0)
    budget.finish(state, "unchanged", 0, card, plan, budget.limits.first(), 0.01)
    assert budget.strategic_holds
    assert budget.take_deepen(1.25).allowance.max_nodes == 800


def test_a_short_global_remainder_does_not_grant_a_12_second_deep_probe():
    state = _state(8)
    card = Card("h", 8)
    budget = _budget(2.0)
    middle = budget.limits.next_after(160)
    budget.finish(state, "deep-card", 0, card, _clock_plan(264, ((1, 0, 1),)), middle, 0.2)
    assert budget.deep_ready
    assert budget.clip(12.0, 12.0) <= 2.05
    assert budget.take_deepen(1.25) is None
    assert budget.deep_ready
    assert budget.deep_used == 0
    assert budget._deep_wall() < budget.deep_minimum_s


def test_two_expensive_objectives_each_get_one_deep_grant_and_a_third_does_not():
    state = _state(9)
    card = Card("h", 8)
    budget = _budget(90.0)
    middle = budget.limits.next_after(160)
    hold = _clock_plan(120, ((1, 0, 1),))
    deep = _clock_plan(264, ((1, 0, 1),))
    budget.finish(state, "hold-me", 0, card, hold, budget.limits.first(), 0.01)
    budget.finish(state, "deep-a", 0, card, deep, middle, 0.2)
    budget.finish(_state(10), "deep-b", 1, card, deep, middle, 0.2)
    budget.note_alternatives(3)
    budget.proposal_turns = 1
    assert budget.take_deepen(1.25) is None
    assert len(budget.deep_ready) == 2
    assert budget.strategic_holds
    budget.note_alternatives(0)
    budget.proposal_turns = 4
    first = budget.take_deepen(1.25)
    assert first is not None and first.allowance.max_nodes == 4500
    budget.begin_proposal()
    second = budget.take_deepen(1.25)
    assert second is not None and second.allowance.max_nodes == 4500
    assert first.objective != second.objective
    budget.begin_proposal()
    third = budget.take_deepen(1.25)
    assert third is not None and third.allowance.max_nodes == 800
    assert budget.deep_used == 2

    short = _budget(2.0)
    short.finish(state, "hold-me", 0, card, hold, short.limits.first(), 0.01)
    short.finish(state, "deep-a", 0, card, deep, middle, 0.2)
    grant = short.take_deepen(1.25)
    assert grant is not None and grant.allowance.max_nodes == 800
    assert short.deep_used == 0
    assert short.deep_ready


def test_a_changed_node_allowance_is_not_answered_by_a_smaller_time_stop():
    fingerprint = ("tableau", 1)
    stopped = _clock_plan(40, (), status="TIME_LIMIT", stop="TIME_LIMIT", depth=2)
    small = excavation_cache_key(fingerprint, "obj", False, 4, 160, "receiver-then-peel")
    larger = excavation_cache_key(fingerprint, "obj", False, 4, 800, "receiver-then-peel")
    cache = {small + (0.28,): stopped}
    assert excavation_cache_lookup(cache, small) is None
    assert excavation_cache_lookup(cache, larger) is None
    success = _make_access_plan(((0, 1, 1),), 2, "exposed", 8, "obj", 0, 2, 0, ())
    cache[small] = success
    assert excavation_cache_lookup(cache, larger) is success
    tighter = excavation_cache_key(fingerprint, "obj", False, 1, 800, "receiver-then-peel")
    assert excavation_cache_lookup(cache, tighter) is None


def test_a_probe_recorded_on_one_physical_state_is_not_reused_on_another():
    card = Card("h", 8)
    first = _state(11)
    second = _state(12)
    assert canonical_state_key(first) != canonical_state_key(second)
    budget = _budget(30.0)
    budget.finish(first, "same-name", 0, card, _clock_plan(120, ((1, 0, 1),)), budget.limits.first(), 0.01)
    decision = budget.begin_probe(second, "same-name", 0, card, 1.25)
    assert decision.kind == "search"
    assert decision.allowance is not None
    assert decision.allowance.max_nodes == 160
    other = ("other-board",)
    same = ("tableau", 1)
    plan = _clock_plan(40, (), status="NODE_LIMIT", stop="NODE_LIMIT", depth=2)
    key = excavation_cache_key(same, "obj", False, 4, 160, "receiver-then-peel")
    moved = excavation_cache_key(other, "obj", False, 4, 160, "receiver-then-peel")
    assert excavation_cache_lookup({key: plan}, moved) is None


def test_time_limit_and_planning_stall_stay_distinct():
    renamed, reason, info = resolve_termination(
        "PLANNING_STALL",
        "planning stall: 2 legal tableau moves remain",
        deadline_elapsed=True,
        legal_count=2,
    )
    assert renamed == "TIME_LIMIT"
    assert info["cause"] == "TIME_LIMIT"
    assert info["secondary"] == "PLANNING_STALL"
    assert "secondary PLANNING_STALL" in reason
    still, _reason, quiet = resolve_termination(
        "PLANNING_STALL",
        "planning stall: 2 legal tableau moves remain",
        deadline_elapsed=False,
        legal_count=2,
    )
    assert still == "PLANNING_STALL"
    assert quiet["secondary"] is None
    state = _state(13)
    budget = _budget(30.0)
    budget.finish(
        state,
        "clock",
        0,
        Card("h", 8),
        _clock_plan(20, ((1, 0, 1),)),
        budget.limits.first(),
        0.01,
    )
    assert budget.classifications["resource_limited"] >= 1
    assert budget.classifications.get("proved_impossible", 0) == 0
    assert budget.classifications.get("exhausted_within_bound", 0) == 0


def test_a_step_budget_stop_is_not_relabelled_as_an_earlier_stall():
    status, reason = reported_search_stop(
        "STEP_LIMIT",
        "strategic step budget ended; still queued 3",
        "PLANNING_STALL",
        "planning stall: 1 legal tableau moves remain",
    )
    assert status == "STEP_LIMIT"
    assert "still queued 3" in reason
    memory, memory_reason = reported_search_stop(
        "MEMORY_LIMIT",
        "peak RSS exceeded the abort ceiling",
        "EXHAUSTED",
        "no legal continuation under the current restrictions",
    )
    assert memory == "MEMORY_LIMIT"
    assert "abort ceiling" in memory_reason
    stalled, stalled_reason = reported_search_stop(
        "EXHAUSTED",
        "no legal continuation under the current restrictions",
        "PLANNING_STALL",
        "planning stall: 1 legal tableau moves remain",
    )
    assert stalled == "PLANNING_STALL"
    assert stalled_reason.startswith("planning stall")


def test_planning_stall_is_the_stop_only_when_nothing_eligible_remains():
    frontier = StrategicFrontier(limit=8, proposals=3)
    assert frontier.recover_one() is None
    audit = build_stall_audit(frontier, _state(0), remaining_s=80.0, elapsed_s=3.0)
    assert audit["retained_strategic_states"] == 0
    assert audit["explored_lines"] == 0
    assert audit["eligible_deferred"] == 0
    assert audit["unexplored_successors"] == 0
    assert audit["could_explore_with_remaining_time"] is False
    assert "no eligible deferred candidate remains" in audit["policy_decision"]
    assert "PLANNING_STALL is the policy stop" in audit["policy_decision"]


def test_the_g83_fixture_remains_a_legal_two_foundation_trajectory():
    actions = _parse_g83()
    opening = SpiderState.from_cards(list(load_deal(DEAL)))
    played = opening.clone()
    assert replay_actions(played, list(actions)) == 83
    assert [item[0].suit for item in played.foundations] == ["s", "c"]
    assert played.is_solved() is False
    assert len(actions) == 83


def test_a_cold_solve_does_not_import_the_fixture_or_a_known_route():
    opening = SpiderState.from_cards(list(load_deal(DEAL)))
    cold = solve(
        opening.clone(),
        resolve_profile("pilot").with_overrides(time_limit_s=0, max_steps=0, frontier_limit=8),
        mode="cold",
        goal="foundations",
        target_foundations=8,
        deal_cards=list(load_deal(DEAL)),
    )
    assert cold.provenance["cold_injection"] is False
    assert cold.provenance["best_verified_cost"] is None
    assert cold.actions == ()
    assert cold.status == "TIME_LIMIT"
    assert list(_parse_g83()) != list(cold.actions)
    assert "remaining global deadline" in cold.provenance["nested_budget"]
    assert "Do not add" in cold.provenance["state_counts"]["note"]


def test_mw_185_and_mw_172_still_verify_as_complete_routes():
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
    assert route_185.solved is True and route_185.cost == 185 and route_185.foundations == 8
    assert route_172.solved is True and route_172.cost == 172 and route_172.foundations == 8
    assert route_185.actions != route_172.actions


def test_anchored_optimisation_remains_available_and_refuses_cold_mode():
    opening = SpiderState.from_cards(list(load_deal(DEAL)))
    route = parse_moves_file(MOVES_185)
    try:
        optimise_anchored(opening, route, mode="cold", time_limit_s=0, source="imported")
        refused = False
    except AnchoredRefused:
        refused = True
    assert refused is True
    anchored = optimise_anchored(
        opening.clone(),
        route,
        mode="anchored",
        time_limit_s=0,
        adaptive=False,
        source="imported",
        source_id="v0.122",
        expected_cost=185,
    )
    assert anchored.cumulative_g == 185
    assert anchored.solved is True
    assert anchored.provenance["improved"] is False
    assert anchored.provenance["target_mode"] == "fixed-endpoint"
    assert anchored.provenance["cold_injection"] is False


def test_a_partial_trajectory_cannot_replace_a_verified_complete_incumbent():
    opening = SpiderState.from_cards(list(load_deal(DEAL)))
    try:
        verify_complete_solution(opening.clone(), _parse_g83(), source="imported", source_id="g83")
        rejected = False
    except IncumbentRejected:
        rejected = True
    assert rejected is True
    assert proof_prune(180, 10, 185) is True
    assert proof_prune(10, 0, 185) is False
    assert proof_prune(10, 0, None) is False
    verified = verify_complete_solution(
        opening.clone(),
        parse_moves_file(MOVES_185),
        expected_cost=185,
        source="imported",
        source_id="185",
    )
    assert verified.solved is True
    assert verified.cost < 185 + 1
    assert verified.foundations == 8
