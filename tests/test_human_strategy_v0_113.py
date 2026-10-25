"""v0.113 multi-line strategic frontier tests.

Recorded g19 and g32 actions are oracles for fixtures. Cold solves do not
receive them. A frontier limit of 1 is the v0.112 controller.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.human_strategy.controller import solve
from spider.human_strategy.profiles import resolve_profile
from spider.human_strategy.strategic_frontier import (
    StrategicFrontier,
    better_outcome,
    line_priority,
    outcome_rank,
)
from spider.metrics import replay_actions
from spider.research_actions import all_legal_actions, apply_action, face_down_count, step_cost
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


def _cards():
    return load_deal(DEAL)


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


def _opening():
    return SpiderState.from_cards(list(_cards()))


def _at(actions):
    state = _opening()
    g = 0
    for action in actions:
        g += apply_action(state, action)
    return state, g


def _offer(frontier, state, g, label, actions=(), force_id=None, reason=""):
    return frontier.consider(
        state=state.clone(),
        g=g,
        actions=actions,
        lock={"label": label, "alternatives": []},
        force_id=force_id,
        reason=reason or label,
        label=label,
        payload=None,
    )


def test_two_branches_keep_separate_states_and_histories():
    opening = _opening()
    later, g = _at(G19)
    assert g == 19
    frontier = StrategicFrontier(limit=8, proposals=3)
    _offer(frontier, opening, 0, "S#1", actions=(), reason="opening")
    _offer(frontier, later, 19, "D#1", actions=G19, reason="after spades")
    assert frontier.generated == 2
    first = frontier.pop_next()
    second = frontier.pop_next()
    assert first is not None and second is not None
    assert first.actions != second.actions
    assert canonical_state_key(first.state) != canonical_state_key(second.state)
    stock_before = len(second.state.stock)
    first.state.stock.clear()
    assert len(second.state.stock) == stock_before
    assert len(first.state.foundations) != len(second.state.foundations)


def test_dominance_keeps_the_cheapest_ancestry_and_its_other_label():
    state = _opening()
    frontier = StrategicFrontier(limit=8, proposals=3)
    _offer(frontier, state, 10, "D#1", reason="cheap diamonds")
    _accepted, event = _offer(frontier, state, 14, "H#1", reason="dear hearts")
    assert _accepted is False
    assert "transposition" in event
    assert frontier.transpositions == 1
    assert all(node.g <= 10 for node in frontier.queue)
    labels = {node.label for node in frontier.queue}
    labels.update(frontier.labels_at[canonical_state_key(state)])
    assert "H#1" in labels
    accepted, _event = _offer(frontier, state, 10, "C#1", reason="clubs at the same cost")
    assert accepted is True
    assert {node.label for node in frontier.queue} >= {"D#1", "C#1"}


def test_a_cheap_line_does_not_outrank_a_foundation_or_an_excavation():
    opening = _opening()
    later, g = _at(G19)
    assert line_priority(later, g) < line_priority(opening, 0)
    assert outcome_rank(later, g) < outcome_rank(opening, 0)
    buried = outcome_rank(later, 19)
    excavated = (buried[0], buried[1], 10, 40)
    assert better_outcome(buried, excavated) == excavated
    assert better_outcome(outcome_rank(opening, 0), outcome_rank(later, 30)) == outcome_rank(later, 30)


def test_frontier_stays_inside_its_cap_and_a_failed_pop_leaves_the_rest():
    frontier = StrategicFrontier(limit=3, proposals=2)
    state = _opening()
    states = [state]
    for _ in range(8):
        nxt = states[-1].clone()
        move = next(action for action in all_legal_actions(nxt) if action != ("deal",))
        apply_action(nxt, move)
        states.append(nxt)
    for index, item in enumerate(states):
        _offer(frontier, item, index, f"L{index}", force_id=str(index), reason=f"line {index}")
    assert len(frontier.queue) <= 3
    assert frontier.dropped_full >= 1
    held = frontier.pop_next()
    assert held is not None
    assert frontier.queue
    assert frontier.explored == 1


def test_cold_first_foundation_is_unchanged_when_the_frontier_is_on():
    result = solve(
        _opening(),
        _profile(max_steps=40, time_limit_s=40, frontier_limit=4, proposals_per_decision=3),
        mode="cold",
        goal="first-foundation",
        deal_cards=_cards(),
    )
    assert result.provenance["prefix_injected"] is False
    assert result.status == "FOUNDATION_REACHED"
    assert result.solved is False
    assert result.foundations == 1
    assert result.cumulative_g == 19
    assert tuple(result.actions) == G19
    assert result.provenance["frontier"]["enabled"] is True


def test_a_deal_retains_a_preparation_alternative():
    result = solve(
        _opening(),
        _profile(max_steps=14, time_limit_s=25, frontier_limit=4, proposals_per_decision=3),
        mode="cold",
        goal="foundations",
        target_foundations=2,
        deal_cards=_cards(),
    )
    text = "\n".join(result.events)
    assert result.provenance["prefix_injected"] is False
    assert "instead of the deal" in text
    assert result.provenance["frontier"]["generated"] >= 1
    assert result.solved is False
    for branch in result.provenance["frontier"]["branches"]:
        assert branch["replay_ok"] is True


def test_g32_stall_restores_another_line_and_replays():
    state, g = _at(G19 + G32_SUFFIX)
    assert g == 32
    result = solve(
        state,
        _profile(max_steps=48, time_limit_s=45, frontier_limit=6, proposals_per_decision=3),
        mode="diagnose",
        opening_g=32,
        goal="foundations",
        target_foundations=1,
        deal_cards=_cards(),
        provenance_note="diagnostic g32 replay; suffix not injected",
    )
    assert result.provenance["prefix_injected"] is False
    assert result.solved is False
    text = "\n".join(result.events)
    assert "frontier: retain" in text
    assert "frontier: restore" in text
    frontier = result.provenance["frontier"]
    assert frontier["explored"] >= 1
    assert frontier["branches"]
    for branch in frontier["branches"]:
        assert branch["replay_ok"] is True
    sequences = {tuple(branch["actions"]) for branch in frontier["branches"]}
    assert len(sequences) >= 2
    trial = state.clone()
    spent = replay_actions(trial, list(result.actions))
    assert g + spent == result.cumulative_g
    assert len(trial.foundations) == result.foundations
    assert face_down_count(trial) >= 0


def test_cold_mode_refuses_a_prefix_and_zero_cost_scoring_holds():
    try:
        solve(
            _opening(),
            _profile(max_steps=1, time_limit_s=2),
            mode="cold",
            goal="play",
            incumbent_actions=(("deal",),),
        )
    except ValueError as exc:
        assert "cold" in str(exc).lower()
    else:
        raise AssertionError("cold mode accepted a stored prefix")
    columns = []
    for index in range(10):
        if index == 0:
            columns.append(Column([], [Card.parse("8h")]))
        elif index == 1:
            columns.append(Column([], []))
        else:
            columns.append(Column([], [Card.parse("ks")]))
    tiny = SpiderState(columns, [Card.parse(tok) for tok in "9c 7h 2c 3c 4c 5c 6c 4d 3d 2d".split()])
    assert step_cost(tiny, (0, 1, 1)) == 0
    assert step_cost(tiny, ("deal",)) == 1
