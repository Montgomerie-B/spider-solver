"""v0.116 buried-card excavation and probe-cache tests.

Synthetic boards are the policy fixtures. The g=83 checkpoint is replayed
only to name a real buried card. Its actions are not the controller's policy.
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
from spider.human_strategy.foundation_direction import (
    AccessPlan,
    FoundationAgenda,
    FoundationView,
    _access_proposal,
    _cached_excavation,
    _cards_above,
    _cover_depth,
    _elapsed_access_proposal,
    _empty_spent_without_receiver,
    _justified_expansion,
    _legally_movable_head,
    _obstruction_labels,
    _target_join,
    close_foundation_campaign,
    load_portfolio,
    views_from_portfolio,
    excavation_cache_key,
    excavation_cache_lookup,
    excavation_probe_category,
    plan_obstructed_access,
)
from spider.human_strategy.strategic_frontier import StrategicFrontier
from spider.metrics import replay_actions
from spider.research_actions import apply_action, step_cost

DEAL = ROOT / "deals" / "4925153.txt"
G83_PATH = ROOT / "tests" / "fixtures" / "g83_4925153_actions.json"


def _opening():
    return SpiderState.from_cards(list(load_deal(DEAL)))


def _parse(text):
    parts = text.split()
    if parts[0] == "deal":
        return ("deal",)
    return (int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3]))


def _g83_actions():
    payload = json.loads(G83_PATH.read_text(encoding="utf-8"))
    return tuple(_parse(text) for text in payload["actions"])


def _pad(columns):
    cols = list(columns)
    while len(cols) < 10:
        cols.append(Column([Card("d", 13)], [Card("s", 13)]))
    return SpiderState(cols, [])


def _clubs_board():
    """Face-down 8c under 6c and 3s. 4d and 7d are the only receivers."""

    buried = Card("c", 8)
    state = _pad(
        [
            Column([buried], [Card("c", 6), Card("s", 3)]),
            Column([], [Card("d", 4)]),
            Column([], [Card("d", 7)]),
        ]
    )
    return state, buried


def _park_board():
    """5s must land on 6s before that spade run can move onto 7d."""

    buried = Card("c", 8)
    state = _pad(
        [
            Column([buried], [Card("s", 6)]),
            Column([], [Card("d", 7), Card("s", 5)]),
        ]
    )
    return state, buried


def _zero_board():
    """Ah onto the only empty leaves 6c with no move. A lone king transfer costs 0."""

    buried = Card("c", 8)
    state = _pad(
        [
            Column([buried], [Card("c", 6), Card("h", 1)]),
            Column([], []),
            Column([], [Card("d", 13)]),
        ]
    )
    return state, buried


def _depths(state, card, actions):
    trial = state.clone()
    found = [_cover_depth(trial, card)]
    spent = 0
    for action in actions:
        spent += apply_action(trial, action)
        found.append(_cover_depth(trial, card))
    return trial, spent, found


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


def _stored(status, actions=(), cost=0, exhaustive=False):
    return AccessPlan(
        tuple(actions),
        cost,
        status,
        1,
        "src",
        0,
        2,
        0 if status in {"exposed", "unlocked"} else 2,
        (),
        exhaustive=exhaustive,
        strategy="receiver-then-peel",
        allow_deals=False,
        max_cost_limit=0,
        max_nodes_limit=0,
    )


def test_buried_clubs_card_is_a_distinct_face_down_object():
    state, buried = _clubs_board()
    other = Card("c", 8)
    assert buried is state.columns[0].face_down[0]
    assert buried is not other
    assert buried == other
    assert _cover_depth(state, buried) == 2
    assert _obstruction_labels(state, buried) == ("6c", "3s")
    assert [str(card) for card in _cards_above(state, buried)] == ["3s", "6c"]
    assert state.is_movable_run([state.columns[0].face_up[-1]])
    assert state.is_movable_run(state.columns[0].face_up) is False
    assert _legally_movable_head(state, buried) is False


def test_multi_move_clubs_excavation_reveals_without_making_the_card_movable():
    state, buried = _clubs_board()
    partial = plan_obstructed_access(state, buried, (), max_cost=1, max_nodes=40)
    assert partial is not None
    assert partial.status == "progress"
    assert partial.depth_before == 2
    assert partial.depth_after == 1
    assert len(partial.actions) >= 1
    trial, spent, depths = _depths(state, buried, partial.actions)
    assert spent == partial.cost
    assert depths[-1] == 1
    assert buried in trial.columns[0].face_down
    assert excavation_probe_category(partial) == "PARTIAL_PROGRESS"

    revealed = plan_obstructed_access(state, buried, (), max_cost=4, max_nodes=40)
    assert revealed is not None
    assert revealed.status == "exposed"
    assert revealed.movable is False
    assert revealed.depth_after == 0
    assert len(revealed.actions) >= 2
    assert revealed.cost == 2
    trial, spent, depths = _depths(state, buried, revealed.actions)
    assert spent == revealed.cost == 2
    assert depths == [2, 1, 0]
    assert buried in trial.columns[0].face_up
    assert _cover_depth(trial, buried) == 0
    assert _legally_movable_head(trial, buried) is False
    assert excavation_probe_category(revealed) == "SUCCESS"


def test_face_up_card_can_be_visible_and_still_immovable():
    stuck = Card("c", 8)
    state = _pad([Column([], [stuck, Card("s", 3)]), Column([], [Card("d", 4)])])
    assert stuck in state.columns[0].face_up
    assert _cover_depth(state, stuck) == 1
    assert _legally_movable_head(state, stuck) is False
    plan = plan_obstructed_access(state, stuck, (), max_cost=3, max_nodes=20)
    assert plan is not None
    assert plan.status == "exposed"
    assert plan.movable is False
    trial, spent, _depths_now = _depths(state, stuck, plan.actions)
    assert spent == plan.cost
    assert trial.columns[0].face_up == [stuck]
    assert _legally_movable_head(trial, stuck) is False


def test_two_physical_copies_are_planned_separately():
    buried = Card("c", 8)
    free = Card("c", 8)
    state = _pad(
        [
            Column([buried], [Card("c", 6), Card("s", 3)]),
            Column([], [Card("d", 4)]),
            Column([], [Card("d", 7)]),
            Column([], [Card("d", 9)]),
            Column([], [free]),
        ]
    )
    assert buried is not free
    assert _cover_depth(state, buried) == 2
    assert _legally_movable_head(state, free) is True
    assert plan_obstructed_access(state, free, (), max_cost=4, max_nodes=20) is None
    plan = plan_obstructed_access(state, buried, (), max_cost=4, max_nodes=40)
    assert plan is not None
    assert plan.status in {"exposed", "unlocked"}
    trial, spent, _found = _depths(state, buried, plan.actions)
    assert spent == plan.cost
    assert buried in trial.columns[0].face_up or _legally_movable_head(trial, buried)
    assert free is not buried


def test_temporary_parking_may_raise_cover_before_the_reveal():
    state, buried = _park_board()
    assert _cover_depth(state, buried) == 1
    plan = plan_obstructed_access(state, buried, (), max_cost=4, max_nodes=40)
    assert plan is not None
    assert plan.status == "exposed"
    assert plan.movable is False
    assert len(plan.actions) >= 2
    trial, spent, depths = _depths(state, buried, plan.actions)
    assert spent == plan.cost
    assert max(depths) > depths[0]
    assert depths[-1] == 0
    assert buried in trial.columns[0].face_up
    assert _legally_movable_head(trial, buried) is False


def test_zero_cost_transfer_is_expanded_and_a_dead_end_peel_is_not_success():
    state, buried = _zero_board()
    king_move = (2, 1, 1)
    assert state.can_move(*king_move)
    assert step_cost(state, king_move) == 0
    assert step_cost(state, (0, 1, 1)) == 1
    plan = plan_obstructed_access(state, buried, (), max_cost=4, max_nodes=80)
    assert plan is not None
    assert plan.zero_cost_expansions > 0
    assert plan.actions == ()
    assert plan.status == "GRAPH_EXHAUSTED_WITHIN_BOUND"
    assert plan.exhaustive is True
    assert plan.allow_deals is False
    assert plan.depth_after == plan.depth_before == 2
    assert excavation_probe_category(plan) == "GRAPH_EXHAUSTED_WITHIN_BOUND"
    fingerprint = ("zero",)
    cache = {
        excavation_cache_key(fingerprint, "src", False, plan.max_cost_limit, 80, plan.strategy): plan
    }
    same = excavation_cache_key(fingerprint, "src", False, 2, 10, plan.strategy)
    higher = excavation_cache_key(fingerprint, "src", False, 8, 80, plan.strategy)
    dealt = excavation_cache_key(fingerprint, "src", True, 4, 80, plan.strategy)
    other = excavation_cache_key(fingerprint, "src", False, 4, 80, "unrestricted")
    assert excavation_cache_lookup(cache, same) is plan
    assert excavation_cache_lookup(cache, higher) is None
    assert excavation_cache_lookup(cache, dealt) is None
    assert excavation_cache_lookup(cache, other) is None


def test_probe_limits_do_not_become_infeasibility_and_are_not_repeated():
    fingerprint = ("board",)
    source = "src"
    strategy = "receiver-then-peel"
    limited = _stored("PROBE_LIMIT")
    exact = excavation_cache_key(fingerprint, source, False, 4, 10, strategy)
    cache = {exact: limited}
    assert excavation_cache_lookup(cache, exact) is limited
    assert excavation_probe_category(limited) == "PROBE_LIMIT"
    larger_nodes = excavation_cache_key(fingerprint, source, False, 4, 50, strategy)
    larger_cost = excavation_cache_key(fingerprint, source, False, 8, 10, strategy)
    assert excavation_cache_lookup(cache, larger_nodes) is None
    assert excavation_cache_lookup(cache, larger_cost) is None
    assert _justified_expansion(limited) is True

    success = _stored("exposed", actions=((0, 1, 1),), cost=2)
    success_key = excavation_cache_key(fingerprint, source, False, 4, 10, strategy)
    success_cache = {success_key: success}
    reuse = excavation_cache_key(fingerprint, source, False, 8, 100, strategy)
    too_cheap = excavation_cache_key(fingerprint, source, False, 1, 100, strategy)
    assert excavation_cache_lookup(success_cache, reuse) is success
    assert excavation_cache_lookup(success_cache, too_cheap) is None
    assert excavation_probe_category(success) == "SUCCESS"
    assert _justified_expansion(success) is False

    missing = Card("h", 8)
    absent = plan_obstructed_access(_pad([]), missing, (), max_cost=4, max_nodes=10)
    assert absent is not None
    assert absent.status == "PROVEN_INFEASIBLE_UNDER_EXPLICIT_CONDITIONS"
    assert absent.exhaustive is True


def test_a_small_node_cap_can_be_revisited_and_an_identical_cap_is_not():
    state, buried = _zero_board()
    lock = {}
    first = _cached_excavation(
        state,
        buried,
        (),
        lock,
        source_key="tableau:0:down:0",
        column=0,
        max_cost=4,
        max_nodes=1,
        time_left=5,
    )
    assert first.status == "NODE_LIMIT"
    assert excavation_probe_category(first) == "NODE_LIMIT"
    assert _justified_expansion(first) is True
    assert lock["probe_stats"]["misses"] == 1
    second = _cached_excavation(
        state,
        buried,
        (),
        lock,
        source_key="tableau:0:down:0",
        column=0,
        max_cost=4,
        max_nodes=1,
        time_left=5,
    )
    assert second is first
    assert lock["probe_stats"]["hits"] == 1
    assert lock["probe_stats"]["misses"] == 1
    wider = _cached_excavation(
        state,
        buried,
        (),
        lock,
        source_key="tableau:0:down:0",
        column=0,
        max_cost=4,
        max_nodes=80,
        time_left=5,
    )
    assert wider is not first
    assert wider.status == "GRAPH_EXHAUSTED_WITHIN_BOUND"
    assert lock["probe_stats"]["misses"] == 2
    assert lock["probe_stats"]["revisits"] == 0


def test_a_time_guard_skip_is_not_cached():
    state, buried = _clubs_board()
    lock = {}
    skipped = _cached_excavation(
        state,
        buried,
        (),
        lock,
        source_key="tableau:0:down:0",
        column=0,
        max_cost=4,
        max_nodes=20,
        time_left=0.01,
    )
    assert skipped.status == "TIME_LIMIT"
    assert lock["excavation_cache"] == {}
    found = _cached_excavation(
        state,
        buried,
        (),
        lock,
        source_key="tableau:0:down:0",
        column=0,
        max_cost=4,
        max_nodes=20,
        time_left=5,
    )
    assert found.status == "exposed"
    assert len(lock["excavation_cache"]) == 1


def test_elapsed_campaign_executes_a_clubs_excavation_and_the_frontier_can_keep_it():
    state, buried = _clubs_board()
    events = []
    lock = {}
    proposal = _elapsed_access_proposal(
        state,
        0,
        _Campaign("c"),
        _agenda("c"),
        lock,
        events,
        set(),
        20.0,
    )
    assert proposal is not None
    candidate = proposal.candidate
    assert candidate is not None
    assert candidate.kind == "ACCESS"
    assert candidate.hold is True
    assert len(candidate.actions) >= 2
    text = " ".join(candidate.evidence)
    assert "face-up does not mean the card is legally movable" in text
    assert "a probe limit is not infeasibility" in text
    trial, spent, depths = _depths(state, buried, candidate.actions)
    assert spent == 2
    assert depths[-1] == 0
    assert buried in trial.columns[0].face_up
    assert any("excavation plays" in event for event in events)

    frontier = StrategicFrontier(limit=8, proposals=3)
    accepted, event = frontier.consider(
        state=trial,
        g=spent,
        actions=tuple(candidate.actions),
        lock={"label": "C#1"},
        force_id=None,
        reason="excavated clubs card",
        label="C#1",
        payload=None,
    )
    assert accepted is True
    assert "retain" in event
    assert len(frontier.queue) == 1
    for rank in range(1, 8):
        variant = trial.clone()
        variant.columns[9].face_up = [Card("h", rank)]
        added, _note = frontier.consider(
            state=variant,
            g=spent,
            actions=(),
            lock={},
            force_id=None,
            reason=f"filler {rank}",
            label=f"L{rank}",
            payload=None,
        )
        assert added is True
    assert len(frontier.queue) == 8
    rejected = trial.clone()
    rejected.columns[9].face_up = [Card("h", 9)]
    kept, note = frontier.consider(
        state=rejected,
        g=spent,
        actions=(),
        lock={},
        force_id=None,
        reason="over capacity",
        label="L9",
        payload=None,
    )
    assert kept is False
    assert frontier.dropped_full == 1
    assert "not exhaustion" in note

    lock["excavation_cache"] = {"stale": limited_marker()}
    close_foundation_campaign(
        lock,
        reason="fixture close",
        exact_cost=2,
        cumulative_g=2,
        label="C#1",
    )
    assert "excavation_cache" not in lock


def limited_marker():
    return _stored("NODE_LIMIT")


def test_g83_buried_eight_of_hearts_has_a_legal_reveal_beyond_the_one_move_trap():
    state = _opening()
    replay_actions(state, list(_g83_actions()))
    buried = None
    column_index = None
    for index, column in enumerate(state.columns):
        for card in column.face_down:
            if card.suit == "h" and card.rank == 8:
                buried = card
                column_index = index
    exposed_copy = None
    for column in state.columns:
        for card in column.face_up:
            if card.suit == "h" and card.rank == 8:
                exposed_copy = card
    assert buried is not None and exposed_copy is not None
    assert buried is not exposed_copy
    assert column_index == 6
    assert _cover_depth(state, buried) == 3
    assert _obstruction_labels(state, buried) == ("6c", "Ah", "3s")
    assert _legally_movable_head(state, buried) is False
    assert _legally_movable_head(state, exposed_copy) is True
    assert plan_obstructed_access(state, exposed_copy, (), max_cost=4, max_nodes=20) is None

    started = time.perf_counter()
    plan = plan_obstructed_access(
        state,
        buried,
        (),
        source_key="tableau:6:down:0",
        column=6,
        max_cost=8,
        max_nodes=4500,
        deadline=time.perf_counter() + 25,
    )
    assert plan is not None
    assert plan.status == "exposed"
    assert plan.movable is False
    assert plan.depth_before == 3
    assert plan.depth_after == 0
    assert len(plan.actions) >= 4
    assert plan.actions != ((6, 0, 1),)
    assert plan.cost > 1
    trial, spent, depths = _depths(state, buried, plan.actions)
    assert spent == plan.cost
    assert depths[0] == 3
    assert depths[-1] == 0
    assert max(depths) >= 3
    assert buried in trial.columns[column_index].face_up or any(
        buried in column.face_up for column in trial.columns
    )
    assert _legally_movable_head(trial, buried) is False
    assert time.perf_counter() - started < 25


def test_g19_and_g83_trajectories_stay_replay_valid():
    actions = _g83_actions()
    assert len(actions) == 83
    early = actions[:19]
    state = _opening()
    g = replay_actions(state, list(early))
    assert g == 19
    assert early[-1] == (1, 0, 12)
    assert len(state.foundations) == 1
    assert state.foundations[0][0].suit == "s"
    assert state.is_solved() is False
    again = _opening()
    spent = replay_actions(again, list(actions))
    assert spent == 83
    assert [item[0].suit for item in again.foundations] == ["s", "c"]
    assert again.is_solved() is False


def test_an_empty_column_is_not_spent_on_a_card_that_cannot_receive_the_suit():
    buried = Card("h", 8)
    ace = Card("h", 1)
    waste = _pad(
        [
            Column([buried], [ace, Card("s", 3)]),
            Column([], []),
            Column([], [Card("h", 12), Card("h", 11)]),
        ]
    )
    parked = AccessPlan(((0, 1, 1),), 1, "exposed", 1, "src", 0, 1, 0, ("3s",))
    assert _empty_spent_without_receiver(waste, ace, parked, "h") is True

    king = Card("h", 13)
    useful = _pad(
        [
            Column([Card("d", 2)], [king, Card("d", 8)]),
            Column([], []),
            Column([], [Card("h", 12), Card("h", 11), Card("h", 10)]),
        ]
    )
    opened = AccessPlan(((0, 1, 1),), 1, "exposed", 1, "src", 0, 1, 0, ("8d",))
    assert _empty_spent_without_receiver(useful, king, opened, "h") is False
    trial = useful.clone()
    apply_action(trial, (0, 1, 1))
    assert trial.columns[0].top() is king
    assert trial.can_move(2, 0, 3) is True


def test_after_the_hearts_join_access_builds_a_king_receiver():
    state = _opening()
    replay_actions(state, list(_g83_actions()))
    cards = list(load_deal(DEAL))
    joined = _target_join(state, "h", ())
    assert joined is not None
    apply_action(state, joined)
    feasibility, portfolio = load_portfolio(state, cards, {})
    hearts = next(item for item in portfolio.campaigns if item.label == "H#1")
    view = next(item for item in views_from_portfolio(feasibility, portfolio) if item.label == "H#1")
    agenda = FoundationAgenda(
        view=view,
        alternatives=(),
        prerequisites=(),
        protected_fragments=(),
        campaign_cost=float(hearts.estimated_campaign_cost),
        target_epoch=hearts.target_removal_epoch,
        current_epoch=hearts.current_epoch,
        stock_len=len(state.stock),
        reasons=view.reasons,
    )
    events = []
    proposal = _access_proposal(state, 84, hearts, agenda, {}, events, set(), 20.0, "hearts")
    assert proposal is not None
    candidate = proposal.candidate
    assert candidate is not None
    assert candidate.actions != ((6, 0, 1),)
    assert any("not a receiver" in event for event in events)
    trial = state.clone()
    for action in candidate.actions:
        apply_action(trial, action)
    follow = _target_join(trial, "h", ())
    assert follow is not None
    _src, dst, width = follow
    assert trial.columns[dst].top().suit == "h"
    assert trial.columns[dst].top().rank == 13
    assert width >= 7
    landed = trial.clone()
    apply_action(landed, follow)
    hearts = [
        card.rank
        for card in landed.columns[dst].face_up
        if card.suit == "h"
    ]
    assert 13 in hearts and 12 in hearts and 6 in hearts


def test_solved_still_requires_all_eight_foundations():
    state = _opening()
    replay_actions(state, list(_g83_actions()))
    assert len(state.foundations) == 2
    assert state.is_solved() is False
    almost = SpiderState([Column([], []) for _ in range(10)], [], [[] for _ in range(7)])
    assert almost.is_solved() is False
    done = SpiderState([Column([], []) for _ in range(10)], [], [[] for _ in range(8)])
    assert done.is_solved() is True
