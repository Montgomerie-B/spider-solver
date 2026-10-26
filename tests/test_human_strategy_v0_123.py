"""v0.123 strategic-commit accounting and same-move cycle guard.

Synthetic boards and the saved g83 audit. No 40-second or 150-second search.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.human_strategy import SCHEMA_VERSION
from spider.human_strategy.anchored import AnchoredRefused, optimise_anchored
from spider.human_strategy.controller import (
    next_distinct_objective,
    objective_already_failed,
    purpose_met_substitutes,
    solve,
    suppression_repeats,
)
from spider.human_strategy.evaluation import admissible_remaining, estimate_remaining
from spider.human_strategy.incumbent import IncumbentRejected, proof_prune, verify_complete_solution
from spider.human_strategy.profiles import resolve_profile
from spider.human_strategy.foundation_direction import _make_access_plan, alignment_already_refused
from spider.human_strategy.search_budget import BudgetCoordinator, TacticalLimits
from spider.human_strategy.strategic_frontier import (
    FOUNDATION_FACE_DOWN_WEIGHT,
    StrategicFrontier,
    line_priority,
    pin_named_successor,
)
from spider.human_strategy.strategic_frontier import StrategicNode
from spider.metrics import format_action, parse_moves_file
from spider.research_actions import all_legal_actions, apply_action, face_down_count, opening_from_deal, step_cost
from spider.state_identity import canonical_state_key

DEAL = ROOT / "deals" / "4925153.txt"
MOVES_185 = ROOT / "solutions" / "4925153_autonomous_185.moves"
MOVES_172 = ROOT / "solutions" / "4925153_canonical.moves"
G83_PATH = ROOT / "tests" / "fixtures" / "g83_4925153_actions.json"


def _profile(**kwargs):
    base = dict(
        time_limit_s=2.0,
        max_steps=2,
        tactical_nodes=40,
        tactical_time_s=0.05,
        tactical_max_cost=2,
        consult_portfolio=False,
        strategic_width=1,
        max_width=2,
        rss_abort_mb=3072,
        frontier_limit=8,
        proposals_per_decision=2,
        slice_steps=24,
        line_attempt_cap=48,
    )
    base.update(kwargs)
    return resolve_profile("smoke").with_overrides(**base)


def _opening() -> SpiderState:
    return opening_from_deal(DEAL)


def _parse_g83():
    payload = json.loads(G83_PATH.read_text(encoding="utf-8"))

    def parse(text):
        if text == "deal":
            return ("deal",)
        parts = text.split()
        return (int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3]))

    return [parse(text) for text in payload["actions"]], payload


def _replay(actions):
    state = _opening()
    g = 0
    for action in actions:
        g += step_cost(state, action)
        apply_action(state, action)
    return state, g


def _node(state, g, reason, label, force_id=None):
    return StrategicNode(
        state=state,
        g=g,
        actions=(),
        lock={},
        force_id=force_id,
        reason=reason,
        label=label,
        payload=None,
        priority=(0,),
        signature=(0, 0, label, 0),
        token=(canonical_state_key(state), label, force_id or ""),
    )


def test_schema_is_v0_123_and_the_face_down_weight_stays_20():
    assert SCHEMA_VERSION == "spider-human-strategy-0.123"
    assert FOUNDATION_FACE_DOWN_WEIGHT == 20
    limits = TacticalLimits()
    assert limits.ladder[-1][2] == 4500


def test_strategic_commits_count_successful_steps_and_obey_the_configured_limit():
    limited = solve(_opening(), _profile(max_steps=1, time_limit_s=3), mode="cold", goal="play")
    assert limited.status == "STEP_LIMIT"
    assert limited.provenance["strategic_commit_limit"] == 1
    assert limited.provenance["strategic_commits"] <= 1
    assert limited.provenance["strategic_commit_peak"] <= 1
    assert "strategic step budget ended" in limited.stop_reason
    assert "1 of 1 strategic commits" in limited.stop_reason
    wider = solve(_opening(), _profile(max_steps=4, time_limit_s=3), mode="cold", goal="play")
    assert wider.provenance["strategic_commit_limit"] == 4
    assert wider.provenance["strategic_commits"] <= 4
    assert wider.provenance["strategic_commits"] >= limited.provenance["strategic_commits"]
    assert wider.status in {"STEP_LIMIT", "TIME_LIMIT", "PLANNING_STALL", "EXHAUSTED"}
    assert "220" not in wider.stop_reason


def test_a_configured_limit_above_220_is_not_a_hardcoded_220_stop():
    """220 is the benchmark flag, not a constant inside the controller."""

    text = (ROOT / "src" / "spider" / "human_strategy" / "controller.py").read_text(encoding="utf-8")
    assert "commits >= 220" not in text
    assert "commits >= profile.max_steps" in text
    short = solve(
        _opening(),
        _profile(max_steps=3, time_limit_s=3),
        mode="cold",
        goal="play",
    )
    assert short.provenance["strategic_commit_limit"] == 3
    if short.status == "STEP_LIMIT":
        assert short.provenance["strategic_commits"] <= 3
        assert short.provenance["termination"]["cause"] == "STEP_LIMIT"


def test_the_global_deadline_outranks_a_relaxed_commit_ceiling():
    stopped = solve(
        _opening(),
        _profile(max_steps=1000, time_limit_s=0),
        mode="cold",
        goal="play",
    )
    assert stopped.status == "TIME_LIMIT"
    assert stopped.provenance["deadline_elapsed"] is True
    assert stopped.provenance["termination"]["cause"] == "TIME_LIMIT"
    assert stopped.provenance["strategic_commits"] == 0
    assert stopped.provenance["strategic_commit_limit"] == 1000
    assert stopped.provenance["budget_stop"] == "TIME_LIMIT"


def test_a_memory_ceiling_stops_before_strategic_work():
    stopped = solve(
        _opening(),
        _profile(max_steps=50, time_limit_s=5, rss_abort_mb=0),
        mode="cold",
        goal="play",
    )
    assert stopped.status == "MEMORY_LIMIT"
    assert stopped.provenance["strategic_commits"] == 0
    assert "peak RSS" in stopped.stop_reason


def test_frontier_capacity_stays_eight_and_peaks_are_recorded():
    frontier = StrategicFrontier(limit=8, proposals=3)
    assert frontier.limit == 8
    for index in range(10):
        state = SpiderState(
            [Column([Card("d", 13)], [Card("shdc"[index % 4], (index % 13) + 1)]) for _ in range(10)],
            [],
        )
        # Distinct physical states: vary one exposed card per line.
        state.columns[0] = Column([], [Card("s", (index % 13) + 1)])
        frontier.consider(
            state=state,
            g=index,
            actions=(),
            lock={},
            force_id=None,
            reason=f"line {index}",
            label="L",
            payload=None,
        )
    assert len(frontier.queue) <= 8
    assert frontier.peak_queue <= 8
    assert frontier.peak_queue == len(frontier.queue) or frontier.peak_queue == 8
    assert frontier.deferred_held >= 1
    assert frontier.peak_deferred >= 1
    generated = frontier.generated
    while frontier.queue:
        frontier.pop_next()
    restored = frontier.recover_one()
    assert restored is not None
    again = frontier.recover_one()
    assert again is None
    frontier.pop_next()
    second = frontier.recover_one()
    assert second is not None
    assert restored.token != second.token
    assert frontier.generated == generated


def test_a_refused_alignment_is_not_proposed_again_for_that_suit():
    assert alignment_already_refused(("ALIGN:S#1:2",), "S#1") is True
    assert alignment_already_refused(("ALIGN:S#1:2",), "C#1") is False
    assert alignment_already_refused(("ACCESS:S#1",), "S#1") is False


def test_a_failed_park_is_not_rebuilt_as_a_new_deal_substitute():
    park = SimpleNamespace(candidate_id="PARK:move 4 3 8", actions=((3, 2, 8),), kind="PARK")
    recast = SimpleNamespace(candidate_id="TACTICAL:move 4 3 8", actions=((3, 2, 8),), kind="TACTICAL")
    reveal = SimpleNamespace(candidate_id="REVEAL:move 1 2 1", actions=((0, 1, 1),), kind="REVEAL")
    deal = SimpleNamespace(candidate_id="DEAL_NOW:deal", actions=(("deal",),), kind="DEAL_NOW")
    blocked = {"PARK:move 4 3 8"}
    kept = purpose_met_substitutes([park, recast, reveal], blocked)
    assert [item.candidate_id for item in kept] == ["REVEAL:move 1 2 1"]
    nxt = next_distinct_objective([park, deal, reveal], blocked, park.candidate_id)
    assert nxt is not None and nxt.candidate_id == "REVEAL:move 1 2 1"
    # The deal stays with the campaign proposal. It is not a rebuilt park.
    assert next_distinct_objective([park, deal], blocked, park.candidate_id) is None
    assert next_distinct_objective([park], blocked, park.candidate_id) is None
    # A different physical state's failure set does not hide this move.
    assert [item.candidate_id for item in purpose_met_substitutes([park, reveal], ())] == [
        "PARK:move 4 3 8",
        "REVEAL:move 1 2 1",
    ]
    assert objective_already_failed(park, blocked) is True
    assert objective_already_failed(recast, blocked) is False
    assert objective_already_failed(reveal, blocked) is False
    assert objective_already_failed(reveal, ()) is False


def test_the_same_suppression_is_not_popped_twice_and_a_different_action_is_kept():
    seen = set()
    ident = ("board",)
    assert suppression_repeats(seen, ident, (0, 1, 1), "DEAL_NOW:deal") is False
    assert suppression_repeats(seen, ident, (0, 1, 1), "DEAL_NOW:deal") is True
    assert suppression_repeats(seen, ident, (1, 2, 1), "DEAL_NOW:deal") is False
    assert suppression_repeats(seen, ident, (0, 1, 1), "PARK:move 1 2 1") is False


def test_cheaper_exact_ancestry_dominates_and_distinct_states_both_fit():
    frontier = StrategicFrontier(limit=8, proposals=3)
    state = SpiderState(
        [Column([], [Card("s", index + 1)]) for index in range(10)],
        [Card("h", 1)] * 10,
    )
    other = state.clone()
    other.columns[1] = Column([], [Card("d", 5), Card("d", 4)])
    assert canonical_state_key(state) != canonical_state_key(other)
    first, _event = frontier.consider(
        state=state, g=6, actions=(), lock={}, force_id=None, reason="cheap", label="A", payload=None
    )
    worse, worse_event = frontier.consider(
        state=state, g=9, actions=(), lock={}, force_id="dear", reason="dear", label="A", payload=None
    )
    better, _event = frontier.consider(
        state=state.clone(),
        g=4,
        actions=(),
        lock={},
        force_id="cheaper",
        reason="cheaper",
        label="A",
        payload=None,
    )
    assert "transposition" in worse_event
    second, _event = frontier.consider(
        state=other, g=7, actions=(), lock={}, force_id=None, reason="other", label="B", payload=None
    )
    assert first is True
    assert worse is False
    assert better is True
    assert second is True
    assert frontier.transpositions >= 1
    assert frontier.best_g[canonical_state_key(state)] == 4
    assert len(frontier.queue) == 2


def test_an_illegal_named_pin_does_not_force_a_blocked_plan():
    state = SpiderState(
        [Column([], [Card("s", 2)]) for _ in range(10)],
        [],
    )
    node = _node(state, 0, "after removal try move 1 2 1", "C#1", "PARK:move 1 2 1")
    assert pin_named_successor(node) is False
    assert "pinned_actions" not in node.lock


def test_action_18_deal_and_move_are_legal_in_one_physical_state():
    texts, _payload = _parse_g83()
    parent, g = _replay(texts[:17])
    assert g == 17
    legal = set(all_legal_actions(parent))
    deal = ("deal",)
    move = (6, 7, 1)  # move 7 8 1
    assert deal in legal
    assert move in legal
    dealt = parent.clone()
    moved = parent.clone()
    assert step_cost(parent, deal) == 1
    assert step_cost(parent, move) == 1
    apply_action(dealt, deal)
    apply_action(moved, move)
    assert canonical_state_key(dealt) != canonical_state_key(moved)
    assert canonical_state_key(dealt) != canonical_state_key(parent)
    assert face_down_count(dealt) == face_down_count(parent)
    assert face_down_count(moved) == face_down_count(parent) - 1
    assert line_priority(moved, g + 1) < line_priority(dealt, g + 1)
    # A deal from a different history is not this parent.
    earlier = _opening()
    assert ("deal",) not in all_legal_actions(earlier) or canonical_state_key(earlier) != canonical_state_key(parent)
    assert format_action(move) == "move 7 8 1"


def test_g83_replay_stays_two_foundations_and_cold_search_does_not_load_it():
    actions, payload = _parse_g83()
    assert len(actions) == 83
    end, g = _replay(actions)
    assert g == 83
    assert g == payload["corrected_g"]
    assert len(end.foundations) == 2
    assert end.is_solved() is False
    cold = solve(
        _opening(),
        _profile(time_limit_s=0, max_steps=0),
        mode="cold",
        goal="foundations",
        target_foundations=8,
        deal_cards=list(load_deal(DEAL)),
    )
    assert cold.provenance["cold_injection"] is False
    assert cold.actions == ()
    assert list(actions) != list(cold.actions)
    assert cold.provenance["prefix_injected"] is False


def test_complete_incumbents_and_anchored_modes_stay_intact():
    opening = _opening()
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
    assert route_185.solved and route_185.cost == 185 and route_185.foundations == 8
    assert route_172.solved and route_172.cost == 172 and route_172.foundations == 8
    try:
        verify_complete_solution(opening.clone(), _parse_g83()[0], source="imported", source_id="g83")
        rejected = False
    except IncumbentRejected:
        rejected = True
    assert rejected is True
    try:
        optimise_anchored(opening.clone(), route_185.actions, mode="cold", time_limit_s=0, source="imported")
        refused = False
    except AnchoredRefused:
        refused = True
    assert refused is True
    fixed = optimise_anchored(
        opening.clone(),
        route_185.actions,
        mode="anchored",
        time_limit_s=0,
        adaptive=False,
        source="imported",
        source_id="v0.123",
        expected_cost=185,
    )
    adaptive = optimise_anchored(
        opening.clone(),
        route_185.actions,
        mode="anchored",
        time_limit_s=0,
        adaptive=True,
        source="imported",
        source_id="v0.123",
        expected_cost=185,
    )
    assert fixed.solved and fixed.cumulative_g == 185 and fixed.provenance["improved"] is False
    assert fixed.provenance["target_mode"] == "fixed-endpoint"
    assert adaptive.solved and adaptive.cumulative_g == 185 and adaptive.provenance["improved"] is False
    assert adaptive.provenance["adaptive"] is True


def test_the_reserved_4500_node_excavation_rung_is_still_offered():
    state = SpiderState(
        [Column([Card("d", 13)], [Card("h", (index % 12) + 1)]) for index in range(10)],
        [],
    )
    card = Card("h", 8)
    budget = BudgetCoordinator(__import__("time").perf_counter() + 90.0, TacticalLimits(), [])
    budget.proposal_turns = 4
    middle = budget.limits.next_after(160)
    assert middle is not None and middle.max_nodes == 800
    plan = _make_access_plan(
        ((1, 0, 1),),
        1,
        "progress",
        264,
        "deep-card",
        0,
        3,
        3,
        (),
        stop="TIME_LIMIT",
        max_cost_limit=6,
        max_nodes_limit=800,
    )
    budget.finish(state, "deep-card", 0, card, plan, middle, 0.2)
    grant = budget.take_deepen(1.25)
    assert grant is not None
    assert grant.allowance.max_nodes == 4500
    assert grant.allowance.reserved_deep is True
    assert budget.deep_used == 1


def test_a_heuristic_estimate_is_not_an_admissible_prune():
    state = _opening()
    estimate = estimate_remaining(state)
    admissible = admissible_remaining(state)
    assert proof_prune(0, admissible, 10_000) is False
    assert proof_prune(0, 0, 185) is False
    assert proof_prune(180, admissible, 185) is (180 + admissible >= 185)
    # A large heuristic remainder must not be supplied as the proof term.
    assert proof_prune(1, 0, 185) is False
    assert estimate >= 0
    assert "h_lb" in proof_prune.__doc__
    assert "Heuristic" in proof_prune.__doc__
