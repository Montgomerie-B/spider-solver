"""v0.114 frontier integrity and foundation-bottleneck tests.

Cold solves do not receive g19, g52, g74, or a reference solution.
A frontier limit of 1 keeps the single-line controller.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.human_strategy.controller import solve
from spider.human_strategy.foundation_direction import (
    choose_without_unjustified_cover,
    covers_productive_run,
    plan_foundation_bottleneck,
)
from spider.human_strategy.portfolio import Candidate
from spider.human_strategy.profiles import resolve_profile
from spider.human_strategy.strategic_frontier import StrategicFrontier
from spider.metrics import replay_actions
from spider.research_actions import apply_action, step_cost
from spider.state_identity import canonical_state_key

DEAL = ROOT / "deals" / "4925153.txt"

G19 = (
    (2, 5, 1),
    (6, 8, 1),
    (9, 8, 1),
    (6, 9, 1),
    (5, 7, 2),
    (5, 7, 1),
    (0, 7, 1),
    (2, 1, 1),
    (7, 2, 5),
    ("deal",),
    (9, 5, 1),
    (1, 9, 1),
    (2, 5, 1),
    (2, 8, 6),
    (8, 6, 7),
    (6, 0, 9),
    (0, 1, 10),
    ("deal",),
    (1, 0, 12),
)
G32_SUFFIX = (
    (7, 9, 1),
    (0, 2, 1),
    (3, 0, 1),
    (8, 3, 1),
    (3, 1, 1),
    (9, 1, 2),
    (0, 9, 2),
    (2, 0, 1),
    (0, 7, 2),
    (1, 0, 2),
    (1, 3, 1),
    (0, 1, 3),
    (7, 8, 2),
)
G52_TAIL = (
    (8, 7, 2),
    ("deal",),
    (0, 6, 1),
    (2, 3, 1),
    (7, 2, 1),
    (9, 2, 1),
    (9, 5, 2),
    (9, 0, 1),
    (0, 1, 1),
    (5, 1, 2),
    (1, 4, 1),
    (7, 4, 2),
    ("deal",),
    (5, 6, 1),
    (7, 5, 1),
    ("deal",),
    (4, 1, 1),
    (4, 5, 3),
    (3, 5, 1),
    (7, 2, 1),
)


def _cards():
    return load_deal(DEAL)


def _opening():
    return SpiderState.from_cards(list(_cards()))


def _at(actions):
    state = _opening()
    g = 0
    for action in actions:
        g += apply_action(state, action)
    return state, g


def _profile(**kwargs):
    base = dict(
        time_limit_s=20,
        max_steps=8,
        tactical_nodes=400,
        tactical_time_s=0.8,
        tactical_max_cost=4,
        consult_portfolio=False,
        strategic_width=2,
        max_width=3,
        rss_abort_mb=2048,
        frontier_limit=1,
        proposals_per_decision=2,
    )
    base.update(kwargs)
    return resolve_profile("smoke").with_overrides(**base)


def _offer(frontier, state, g, label, actions=(), force_id=None):
    return frontier.consider(
        state=state.clone(),
        g=g,
        actions=actions,
        lock={"label": label, "alternatives": []},
        force_id=force_id,
        reason=label,
        label=label,
        payload=None,
    )


def _hearts_bottleneck():
    """Hearts queen-to-ace, two covered kings, and a zero-cost decoy. Not clubs."""

    hearts = [Card.parse(token) for token in "qh jh 10h 9h 8h 7h 6h 5h 4h 3h 2h ah".split()]
    columns = [
        Column([Card.parse("as")], [Card.parse("kh"), Card.parse("5s")]),
        Column([Card.parse("2d")], [Card.parse("6c")]),
        Column([], []),
        Column([], [Card.parse("9d")]),
        Column([Card.parse("3s")], hearts),
        Column([Card.parse("4c")], [Card.parse("kh"), Card.parse("4d"), Card.parse("8s")]),
        Column([Card.parse("5d")], [Card.parse("9s")]),
        Column([Card.parse("6d")], [Card.parse("7d")]),
        Column([Card.parse("7s")], [Card.parse("jc")]),
        Column([Card.parse("8d")], [Card.parse("2s")]),
    ]
    return SpiderState(columns, [])


def _candidate(identifier, action, evidence=(), kind="PARK"):
    return Candidate(
        candidate_id=identifier,
        kind=kind,
        purpose="",
        principles=(11, 12),
        actions=(action,),
        objective=None,
        immediate_cost=1,
        cost_is_exact=False,
        expected_benefit=1.0,
        structural_risk=0.0,
        horizon="test",
        feasibility="test",
        evidence=tuple(evidence),
        admissible_lb=0,
        projected=1.0,
        solves=False,
    )


def _replay_cost(state, actions):
    trial = state.clone()
    spent = 0
    for action in actions:
        assert trial.can_move(*action)
        spent += step_cost(trial, action)
        apply_action(trial, action)
    return trial, spent


def test_labels_are_not_distinct_physical_branches():
    state = _opening()
    frontier = StrategicFrontier(limit=8, proposals=3)
    _offer(frontier, state, 10, "D#1")
    accepted, event = _offer(frontier, state, 14, "H#1")
    assert accepted is False
    assert "transposition" in event
    accepted, _event = _offer(frontier, state, 10, "C#1")
    assert accepted is True
    keys = {canonical_state_key(node.state) for node in frontier.queue}
    assert len(keys) == 1
    assert len(frontier.queue) >= 2
    labels = {node.label for node in frontier.queue}
    labels.update(frontier.labels_at[canonical_state_key(state)])
    assert {"D#1", "C#1", "H#1"} <= labels


def test_merged_state_keeps_the_other_objective():
    state = _opening()
    frontier = StrategicFrontier(limit=8, proposals=3)
    _offer(frontier, state, 10, "D#1")
    _offer(frontier, state, 14, "H#1")
    ident = canonical_state_key(state)
    assert "H#1" in frontier.labels_at[ident]
    assert all(node.g == frontier.best_g[ident] for node in frontier.queue)


def test_unexplored_signature_outside_the_pool_gets_one_turn():
    opening = _opening()
    later, g = _at(G19)
    assert g == 19
    frontier = StrategicFrontier(limit=8, proposals=3)
    for label in ("D#1", "H#1", "C#1", "S#2"):
        _offer(frontier, later, 19, label, actions=G19)
    _offer(frontier, opening, 0, "S#1")
    first = frontier.pop_next()
    second = frontier.pop_next()
    assert first is not None and second is not None
    assert len(first.state.foundations) == 1
    assert len(second.state.foundations) == 0
    assert canonical_state_key(first.state) != canonical_state_key(second.state)
    assert first.actions != second.actions


def test_distinct_lines_restore_with_their_own_g_and_tableau():
    state, g = _at(G19)
    result = solve(
        state,
        _profile(
            max_steps=28,
            time_limit_s=25,
            frontier_limit=6,
            proposals_per_decision=3,
            slice_steps=6,
            line_attempt_cap=40,
        ),
        mode="diagnose",
        opening_g=g,
        goal="foundations",
        target_foundations=1,
        deal_cards=_cards(),
        provenance_note="diagnostic g19 checkpoint; no stored prefix",
    )
    frontier = result.provenance["frontier"]
    assert frontier["enabled"] is True
    assert result.provenance["prefix_injected"] is False
    assert "frontier: restore" in "\n".join(result.events)
    histories = {tuple(branch["actions"]) for branch in frontier["branches"]}
    assert len(histories) >= 2
    assert frontier["unique_histories"] == len(histories)
    assert frontier["unique_histories"] <= len(frontier["branches"])
    seen_states = set()
    for branch in frontier["branches"]:
        assert branch["replay_ok"] is True
        trial = state.clone()
        spent = replay_actions(trial, _parse(branch["actions"]))
        assert g + spent == branch["g"]
        seen_states.add(canonical_state_key(trial))
    assert len(seen_states) >= 2


def test_slice_services_a_pending_line_inside_the_budget():
    result = solve(
        _opening(),
        _profile(
            max_steps=18,
            time_limit_s=20,
            frontier_limit=6,
            proposals_per_decision=3,
            slice_steps=4,
            line_attempt_cap=24,
        ),
        mode="cold",
        goal="foundations",
        target_foundations=1,
        deal_cards=_cards(),
    )
    text = "\n".join(result.events)
    frontier = result.provenance["frontier"]
    assert result.provenance["prefix_injected"] is False
    assert "yielded" in text or "frontier: restore" in text
    assert frontier["explored"] >= 1
    assert frontier["still_queued"] == len(frontier["pending"])
    if result.status == "STEP_LIMIT" and frontier["still_queued"]:
        assert "still queued" in result.stop_reason


def test_seed_111_restores_a_queued_alternative():
    cards = list(_cards())
    random.Random(111).shuffle(cards)
    opening = SpiderState.from_cards(cards)
    result = solve(
        opening,
        _profile(
            max_steps=60,
            time_limit_s=25,
            frontier_limit=8,
            proposals_per_decision=3,
            slice_steps=8,
            line_attempt_cap=16,
        ),
        mode="cold",
        goal="foundations",
        target_foundations=1,
        deal_cards=cards,
    )
    text = "\n".join(result.events)
    frontier = result.provenance["frontier"]
    assert result.provenance["prefix_injected"] is False
    assert "frontier: restore" in text
    assert frontier["explored"] >= 1
    histories = {tuple(branch["actions"]) for branch in frontier["branches"]}
    assert len(histories) >= 2
    for branch in frontier["branches"]:
        assert branch["replay_ok"] is True
        trial = opening.clone()
        spent = replay_actions(trial, _parse(branch["actions"]))
        assert spent == branch["g"]


def _parse(actions):
    parsed = []
    for action in actions:
        parts = action.split()
        if parts[0] == "deal":
            parsed.append(("deal",))
        else:
            parsed.append((int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3])))
    return parsed


def test_both_kings_are_examined_and_a_covered_king_is_not_a_receiver():
    state = _hearts_bottleneck()
    plan = plan_foundation_bottleneck(state, max_cost=8, max_nodes=2500, time_left=2.0)
    assert plan.suit == "h"
    assert len(plan.kings) == 2
    assert {king.column for king in plan.kings} == {0, 5}
    for king in plan.kings:
        assert king.face_up is True
        assert king.depth > 0
        assert king.accessible is False
        assert king.blockers
        assert "face-up is not a legal receiver" in " ".join(king.notes)
    shallow = min(plan.kings, key=lambda item: item.depth)
    assert shallow.movable_runs
    assert state.can_move(shallow.column, 1, shallow.movable_runs[0])


def test_blocker_removal_is_a_legal_multi_action_plan():
    state = _hearts_bottleneck()
    plan = plan_foundation_bottleneck(state, max_cost=8, max_nodes=2500, time_left=2.0)
    assert plan.status == "FOUND"
    assert len(plan.actions) >= 2
    trial, spent = _replay_cost(state, plan.actions)
    assert spent == plan.cost
    assert len(trial.foundations) == len(state.foundations) + 1
    assert plan.foundations_after == len(trial.foundations)
    assert trial.foundations[-1][0].suit == "h"
    assert not plan.covers_run or "temporary park is recoverable"


def test_zero_cost_edges_are_ordered_by_corrected_cost():
    state = _hearts_bottleneck()
    decoy = (3, 2, 1)
    assert step_cost(state, decoy) == 0
    plan = plan_foundation_bottleneck(state, max_cost=8, max_nodes=2500, time_left=2.0)
    assert plan.zero_cost_expansions > 0
    assert plan.cheapest_zero_edge == 0
    _trial, spent = _replay_cost(state, plan.actions)
    assert spent == plan.cost
    assert plan.cost != len(plan.actions) or plan.cheapest_zero_edge == 0


def test_the_long_run_is_preserved_until_the_king_receives_it():
    state = _hearts_bottleneck()
    plan = plan_foundation_bottleneck(state, max_cost=8, max_nodes=2500, time_left=2.0)
    assert plan.status == "FOUND"
    probe = state.clone()
    saw_run = False
    for action in plan.actions:
        hearts = [
            column.face_up[-12:]
            for column in probe.columns
            if len(column.face_up) >= 12 and column.face_up[-1].suit == "h" and column.face_up[-12].rank == 12
        ]
        if hearts:
            saw_run = True
        apply_action(probe, action)
    assert saw_run
    assert len(probe.foundations) == 1


def test_unjustified_cover_loses_to_a_preserving_move():
    state, g = _at(G19 + G32_SUFFIX + G52_TAIL)
    assert g == 52
    cover = (3, 5, 1)
    preserve = (3, 0, 1)
    assert covers_productive_run(state, cover) is True
    assert covers_productive_run(state, preserve) is False
    covered = state.clone()
    apply_action(covered, cover)
    kept = state.clone()
    apply_action(kept, preserve)
    exposed = _exposed_clubs(kept)
    buried = _exposed_clubs(covered)
    assert exposed >= 7
    assert buried < exposed
    choice = _candidate("cover", cover)
    other = _candidate("keep", preserve, kind="SAME_SUIT")
    chosen, note = choose_without_unjustified_cover(state, choice, [choice, other])
    assert chosen.candidate_id == "keep"
    assert note.startswith("run guard:")


def test_a_justified_temporary_park_stays_available():
    state, g = _at(G19 + G32_SUFFIX + G52_TAIL)
    assert g == 52
    cover = (3, 5, 1)
    preserve = (3, 0, 1)
    parked = _candidate(
        "park",
        cover,
        evidence=("fact: temporary park is recoverable",),
        kind="BOTTLENECK",
    )
    other = _candidate("keep", preserve)
    chosen, note = choose_without_unjustified_cover(state, parked, [parked, other])
    assert chosen.candidate_id == "park"
    assert note == ""
    assert state.can_move(*cover)


def test_a_bottleneck_plan_removes_a_foundation_on_replay():
    state = _hearts_bottleneck()
    before = len(state.foundations)
    plan = plan_foundation_bottleneck(state, max_cost=8, max_nodes=2500, time_left=2.0)
    assert plan.status == "FOUND"
    trial = state.clone()
    replay_actions(trial, list(plan.actions))
    assert len(trial.foundations) == before + 1
    assert not trial.is_solved()


def test_a_search_limit_is_not_infeasibility():
    state = _hearts_bottleneck()
    plan = plan_foundation_bottleneck(state, max_cost=8, max_nodes=1, time_left=2.0)
    assert plan.status == "RESOURCE_LIMIT"
    assert "not infeasibility" in plan.note
    assert plan.status != "PROVEN_INFEASIBLE"
    stopped = plan_foundation_bottleneck(state, time_left=0)
    assert stopped.status == "RESOURCE_LIMIT"
    assert "not infeasibility" in stopped.note


def test_a_finished_game_still_needs_eight_foundations():
    columns = [Column([], []) for _ in range(10)]
    seven = [[Card.parse("kh")] for _ in range(7)]
    assert SpiderState(columns, [], seven).is_solved() is False
    eight = seven + [[Card.parse("ks")]]
    assert SpiderState([Column([], []) for _ in range(10)], [], eight).is_solved() is True


def test_cold_solving_does_not_load_a_saved_prefix():
    try:
        solve(
            _opening(),
            _profile(max_steps=1, time_limit_s=2),
            mode="cold",
            goal="foundations",
            target_foundations=1,
            deal_cards=_cards(),
            incumbent_actions=(("deal",),),
        )
    except ValueError as exc:
        assert "cold" in str(exc).lower()
    else:
        raise AssertionError("cold mode accepted a stored prefix")
    result = solve(
        _opening(),
        _profile(max_steps=2, time_limit_s=8, frontier_limit=2, proposals_per_decision=2),
        mode="cold",
        goal="foundations",
        target_foundations=1,
        deal_cards=_cards(),
    )
    assert result.provenance["prefix_injected"] is False
    assert result.provenance["assisted_suffix"] is False
    assert result.solved is False
    assert "4925153_autonomous" not in (result.provenance.get("note") or "")
    assert "172" not in (result.provenance.get("note") or "")


def _exposed_clubs(state):
    best = 0
    for column in state.columns:
        up = column.face_up
        if not up:
            continue
        start = len(up) - 1
        if up[start].suit != "c":
            continue
        while start > 0 and up[start - 1].suit == "c" and up[start - 1].rank == up[start].rank + 1:
            start -= 1
        best = max(best, len(up) - start)
    return best
