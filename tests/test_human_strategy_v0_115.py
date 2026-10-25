"""v0.115 multi-foundation progression tests.

Captured g=83 actions are a replay checkpoint. They are not passed to the
live controller as a policy. Cold solves do not receive them.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.human_strategy.controller import solve
from spider.human_strategy.foundation_direction import (
    close_foundation_campaign,
    plan_foundation_bottleneck,
    rank_foundations,
)
from spider.human_strategy.profiles import resolve_profile
from spider.human_strategy.strategic_frontier import (
    FOUNDATION_FACE_DOWN_WEIGHT,
    StrategicFrontier,
    line_priority,
)
from spider.metrics import replay_actions
from spider.research_actions import all_legal_actions, apply_action, face_down_count, step_cost
from spider.state_identity import canonical_state_key

DEAL = ROOT / "deals" / "4925153.txt"
G83_PATH = ROOT / "tests" / "fixtures" / "g83_4925153_actions.json"


def _cards():
    return load_deal(DEAL)


def _opening():
    return SpiderState.from_cards(list(_cards()))


def _parse(text):
    parts = text.split()
    if parts[0] == "deal":
        return ("deal",)
    return (int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3]))


def _g83_actions():
    payload = json.loads(G83_PATH.read_text(encoding="utf-8"))
    return tuple(_parse(text) for text in payload["actions"])


def _replay(actions):
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


def _bag(state):
    counts = Counter()
    for column in state.columns:
        for card in list(column.face_down) + list(column.face_up):
            counts[(card.suit, card.rank)] += 1
    for card in state.stock:
        counts[(card.suit, card.rank)] += 1
    for sequence in state.foundations:
        for card in sequence:
            counts[(card.suit, card.rank)] += 1
    return counts


def _take(pools, suit, rank):
    return pools[(suit, rank)].pop()


def _ready_third_foundation():
    """Two finished suits, and one legal move that removes hearts.

    Built from the real deal's cards so copy identity stays inside that deck.
    The move itself is not handed to the controller.
    """

    pools = {}
    for card in _cards():
        pools.setdefault((card.suit, card.rank), []).append(card)
    spades = [_take(pools, "s", rank) for rank in range(13, 0, -1)]
    clubs = [_take(pools, "c", rank) for rank in range(13, 0, -1)]
    hearts = [_take(pools, "h", rank) for rank in range(13, 2, -1)]
    tail = [_take(pools, "h", 2), _take(pools, "h", 1)]
    rest = [card for bucket in pools.values() for card in bucket]
    columns = [Column([], hearts), Column([], tail)]
    for index in range(8):
        face_up = [rest.pop()] if rest else [Card.parse("kd")]
        face_down = []
        while rest and len(face_down) < 8:
            face_down.append(rest.pop())
        columns.append(Column(face_down, face_up))
    assert not rest
    return SpiderState(columns, [], [spades, clubs])


def test_g83_replays_two_foundations_and_conserves_cards():
    actions = _g83_actions()
    assert len(actions) == 83
    assert actions[-1] == (6, 0, 2)
    opening = _opening()
    before = _bag(opening)
    state = opening.clone()
    g = 0
    for action in actions[:-1]:
        g += apply_action(state, action)
    assert len(state.foundations) == 1
    assert state.foundations[0][0].suit == "s"
    assert g == 82
    column = state.columns[0]
    assert [str(card) for card in column.face_up] == [
        "Kc", "Qc", "Jc", "10c", "9c", "8c", "7c", "6c", "5c", "4c", "3c",
    ]
    moving = state.columns[6].face_up[-2:]
    assert [str(card) for card in moving] == ["2c", "Ac"]
    assert state.can_move(6, 0, 2)
    g += apply_action(state, actions[-1])
    assert g == 83
    assert len(state.foundations) == 2
    assert [item[0].suit for item in state.foundations] == ["s", "c"]
    assert [str(card) for card in state.foundations[1]][0] == "Kc"
    assert [str(card) for card in state.foundations[1]][-1] == "Ac"
    assert state.is_solved() is False
    assert _bag(state) == before
    assert sum(before.values()) == 104
    again, spent = _replay(actions)
    assert spent == 83
    assert canonical_state_key(again) == canonical_state_key(state)


def test_closing_a_campaign_drops_stale_obligations_and_copies_stay_distinct():
    lock = {
        "label": "C#1",
        "operational_epoch": 5,
        "outstanding": ["excavate:c12"],
        "failures": {"excavate:c12": 3},
        "suspended_notes": {"excavate:c12"},
        "fork_block": ("DEAL:C#1",),
        "bottleneck_cache": {"old": "GRAPH_EXHAUSTED"},
        "refused_switch": ("C#1", "H#1", 0),
        "pinned_actions": [(6, 0, 2)],
        "alternatives": ["H#1", "D#1"],
    }
    record = close_foundation_campaign(
        lock,
        reason="C#1 removed at corrected cost 64",
        exact_cost=64,
        cumulative_g=83,
        label="C#1",
    )
    assert record["label"] == "C#1"
    assert lock.get("operational_epoch") is None
    assert lock.get("failures") is None
    assert lock.get("fork_block") is None
    assert lock.get("bottleneck_cache") is None
    assert lock.get("refused_switch") is None
    assert lock.get("pinned_actions") is None
    assert lock.get("label") is None
    assert lock["completed"][0]["cumulative_g"] == 83
    state, g = _replay(_g83_actions())
    assert g == 83
    views = rank_foundations(state, _cards())
    labels = [item.label for item in views]
    assert len(labels) == len(set(labels))
    assert {"H#1", "D#1", "S#2", "C#2"} <= set(labels)
    by_label = {item.label: item for item in views}
    assert by_label["H#1"].copy_index == 1
    assert by_label["S#2"].copy_index == 2
    assert by_label["C#2"].suit == "c"
    assert by_label["H#1"].suit != by_label["D#1"].suit


def test_two_foundations_do_not_meet_a_three_foundation_target():
    state = _ready_third_foundation()
    assert len(state.foundations) == 2
    result = solve(
        state,
        _profile(max_steps=1, time_limit_s=15, frontier_limit=4, proposals_per_decision=3),
        mode="diagnose",
        opening_g=83,
        goal="foundations",
        target_foundations=3,
        deal_cards=_cards(),
        provenance_note="synthetic third-foundation fixture; no stored prefix",
    )
    assert result.foundations == 3
    assert result.status == "STEP_LIMIT"
    assert "strategic step budget ended" in result.stop_reason
    assert result.status != "FOUNDATION_TARGET_REACHED"
    assert result.solved is False
    assert "closed completed campaign" in "\n".join(result.events)
    assert result.provenance["prefix_injected"] is False
    assert result.provenance["frontier"]["generated"] >= 1


def test_a_tractable_fixture_removes_the_third_foundation_on_replay():
    state = _ready_third_foundation()
    before = len(state.foundations)
    result = solve(
        state,
        _profile(max_steps=4, time_limit_s=15, frontier_limit=1),
        mode="diagnose",
        opening_g=83,
        goal="foundations",
        target_foundations=1,
        deal_cards=_cards(),
        provenance_note="synthetic one-move hearts completion",
    )
    assert result.status == "FOUNDATION_TARGET_REACHED"
    assert result.foundations == before + 1
    assert result.solved is False
    trial = state.clone()
    spent = replay_actions(trial, list(result.actions))
    assert spent == result.suffix_mw
    assert len(trial.foundations) == 3
    assert trial.foundations[-1][0].suit == "h"
    assert trial.is_solved() is False
    assert canonical_state_key(trial) == canonical_state_key(
        SpiderState(
            [Column(list(column.face_down), list(column.face_up)) for column in trial.columns],
            list(trial.stock),
            [list(item) for item in trial.foundations],
        )
    )


def test_foundation_count_does_not_outrank_a_prepared_line():
    opening = _opening()
    later, g = _replay(_g83_actions()[:19])
    assert g == 19
    assert line_priority(later, g) < line_priority(opening, 0)
    buried = SpiderState(
        [Column([Card.parse("as") for _ in range(5)], [Card.parse("kh")]) for _ in range(10)],
        [],
        [[Card.parse("ks")], [Card.parse("qs")]],
    )
    prepared = SpiderState(
        [Column([], [Card.parse("ah")]) for _ in range(10)],
        [],
        [[Card.parse("ks")]],
    )
    assert face_down_count(buried) == 50
    assert len(buried.foundations) == 2
    assert face_down_count(prepared) == 0
    assert line_priority(prepared, 30) < line_priority(buried, 20)
    assert FOUNDATION_FACE_DOWN_WEIGHT == 20


def test_distinct_states_stay_distinct_and_labels_do_not():
    frontier = StrategicFrontier(limit=8, proposals=3)
    opening = _opening()
    later, g = _replay(_g83_actions()[:19])
    frontier.consider(
        state=opening.clone(), g=0, actions=(), lock={"label": "S#1"},
        force_id=None, reason="opening", label="S#1", payload=None,
    )
    frontier.consider(
        state=opening.clone(), g=0, actions=(), lock={"label": "H#1"},
        force_id=None, reason="same board", label="H#1", payload=None,
    )
    frontier.consider(
        state=later.clone(), g=g, actions=_g83_actions()[:19], lock={"label": "S#1"},
        force_id=None, reason="after spades", label="S#1", payload=None,
    )
    keys = {canonical_state_key(node.state) for node in frontier.queue}
    assert len(keys) == 2
    labels = {node.label for node in frontier.queue}
    assert "H#1" in labels or "H#1" in frontier.labels_at[canonical_state_key(opening)]
    first = frontier.pop_next()
    second = frontier.pop_next()
    assert canonical_state_key(first.state) != canonical_state_key(second.state)
    assert first.actions != second.actions


def test_a_dead_line_restores_a_queued_alternative(monkeypatch):
    import spider.human_strategy.controller as controller

    opening = _opening()
    later, later_g = _replay(_g83_actions()[:19])

    class Prequeued(StrategicFrontier):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.consider(
                state=later.clone(),
                g=later_g,
                actions=_g83_actions()[:19],
                lock={"label": "H#1"},
                force_id=None,
                reason="held for the exhaustion test",
                label="H#1",
                payload=None,
            )

    monkeypatch.setattr(controller, "StrategicFrontier", Prequeued)
    monkeypatch.setattr(controller, "build_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(controller, "all_legal_actions", lambda state: [])
    result = solve(
        opening,
        _profile(max_steps=8, time_limit_s=8, frontier_limit=4, proposals_per_decision=3),
        mode="cold",
        goal="foundations",
        target_foundations=3,
        deal_cards=_cards(),
    )
    text = "\n".join(result.events)
    assert "frontier: restore held for the exhaustion test" in text
    assert result.provenance["prefix_injected"] is False
    assert result.status != "FOUNDATION_TARGET_REACHED"


def test_search_limit_and_zero_cost_and_eight_foundations():
    hearts = [
        Card.parse(token) for token in "qh jh 10h 9h 8h 7h 6h 5h 4h 3h 2h ah".split()
    ]
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
    state = SpiderState(columns, [])
    limited = plan_foundation_bottleneck(state, max_cost=8, max_nodes=1, time_left=2.0)
    assert limited.status == "RESOURCE_LIMIT"
    assert "not infeasibility" in limited.note
    assert limited.status != "PROVEN_INFEASIBLE"
    found = plan_foundation_bottleneck(state, max_cost=8, max_nodes=2500, time_left=2.0)
    assert found.status == "FOUND"
    trial = state.clone()
    replay_actions(trial, list(found.actions))
    assert len(trial.foundations) == 1
    assert trial.is_solved() is False
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
    seven = [[Card.parse("kh")] for _ in range(7)]
    assert SpiderState([Column([], []) for _ in range(10)], [], seven).is_solved() is False
    eight = seven + [[Card.parse("ks")]]
    assert SpiderState([Column([], []) for _ in range(10)], [], eight).is_solved() is True


def test_cold_mode_rejects_a_saved_prefix_and_a_worse_bound_stays_queued():
    try:
        solve(
            _opening(),
            _profile(max_steps=1, time_limit_s=2),
            mode="cold",
            goal="foundations",
            target_foundations=3,
            deal_cards=_cards(),
            incumbent_actions=_g83_actions(),
        )
    except ValueError as exc:
        assert "cold" in str(exc).lower()
    else:
        raise AssertionError("cold mode accepted a stored prefix")
    frontier = StrategicFrontier(limit=8, proposals=3)
    state = _opening()
    accepted, _event = frontier.consider(
        state=state.clone(),
        g=100,
        actions=(),
        lock={"label": "D#1"},
        force_id=None,
        reason="expensive but admissible does not prune",
        label="D#1",
        payload=None,
    )
    assert accepted is True
    assert frontier.queue[0].g == 100
    assert all_legal_actions(state)
