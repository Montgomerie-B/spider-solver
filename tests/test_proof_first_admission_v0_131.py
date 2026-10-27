"""v0.131 proof-first admission.

A child with g + h above the ceiling must not take a unique slot, a best-g
entry, or a heap entry. A later cheaper arrival to that same identity is
still eligible. Equality g + h == ceiling stays eligible. These fixtures are
deterministic and do not run the 80,000-state experiment.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.packed_state import (
    pack_post_stock_symmetry_state,
    pack_state,
    pack_whole_game_identity,
    unpack_state,
)
from spider.post_sd5_completion import search_post_sd5
from spider.research_actions import all_legal_actions, apply_action, step_cost
from spider.search_kernel import SearchLimits, run_search


def _cards(text: str):
    return [Card.parse(tok) for tok in text.split() if tok]


def _state(columns, stock: str = "") -> SpiderState:
    cols = []
    for index in range(10):
        cols.append(Column([], _cards(columns.get(index, ""))))
    return SpiderState(cols, _cards(stock), [])


def _root(state: SpiderState, g: int = 0) -> dict:
    return {"ordered_digest": pack_state(state).hex(), "g": g}


def _limits(**overrides) -> SearchLimits:
    values = dict(max_unique=30, time_limit_s=2.0, rss_abort_mb=4096, cost_ceiling=5)
    values.update(overrides)
    return SearchLimits(**values)


def _run(state: SpiderState, **kwargs):
    limits = kwargs.pop("limits", None) or _limits()
    return run_search(
        [_root(state, kwargs.pop("g0", 0))],
        limits=limits,
        identity_fn=kwargs.pop("identity_fn", pack_state),
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=("cost",),
        lane_key_fns=(lambda _state, g: (int(g),),),
        is_terminal=kwargs.pop("is_terminal", lambda _state: False),
        actions_fn=kwargs.pop("actions_fn", all_legal_actions),
        lower_bound_fn=kwargs.pop("lower_bound_fn", None),
        stop_on_first_terminal=kwargs.pop("stop_on_first_terminal", False),
        on_child=kwargs.pop("on_child", None),
    )


def _pair() -> SpiderState:
    """Qh is the exposed top. Moving it costs 1. Moving the whole column is free."""

    return _state({0: "kh qh"})


def _replay(state: SpiderState, kernel, node: int) -> tuple:
    path = kernel.reconstruct(node)
    trial = state.clone()
    spent = 0
    for action in path:
        spent += apply_action(trial, action)
    return path, trial, spent


def test_proof_dead_child_does_not_consume_the_slot_needed_by_a_later_candidate():
    state = _pair()
    root_pack = pack_state(state)
    paid = (0, 1, 1)
    free = (0, 2, 2)
    assert step_cost(state, paid) == 1
    assert step_cost(state, free) == 0
    paid_state = state.clone()
    apply_action(paid_state, paid)
    paid_pack = pack_state(paid_state)
    observed = []

    def actions(current: SpiderState):
        if pack_state(current) != root_pack:
            return []
        return [paid, free]

    def bound(current: SpiderState, _g: int) -> int:
        packed = pack_state(current)
        if packed == root_pack:
            return 0
        if packed == paid_pack:
            return 5
        return 0

    found = _run(
        state,
        limits=_limits(max_unique=2, cost_ceiling=1),
        actions_fn=actions,
        lower_bound_fn=bound,
        on_child=lambda _state, g, _index: observed.append(g),
    )
    assert found.stop_reason == "unique limit"
    assert found.unique == 2
    assert len(found.nodes) == 2
    assert found.generated == 2
    assert found.lower_bound_prunes == 1
    assert found.proof_prune_identities == 1
    assert found.proof_prune_unretained == 1
    assert found.duplicate_skips == 0
    assert observed == [0, 0]
    child = found.nodes[1]
    assert child.g == 0
    assert child.action == free
    path, trial, spent = _replay(state, found, 1)
    assert path == [free]
    assert spent == 0
    assert pack_state(trial) == child.store


def test_rejected_higher_g_arrival_does_not_block_a_later_cheaper_arrival():
    """The shared identity is a kernel fixture. Spider step costs cannot produce it."""

    state = _pair()
    root_pack = pack_state(state)
    paid = (0, 1, 1)
    free = (0, 2, 2)

    def actions(current: SpiderState):
        if pack_state(current) != root_pack:
            return []
        return [paid, free]

    def identity(current: SpiderState) -> bytes:
        if pack_state(current) == root_pack:
            return b"ROOT"
        return b"SAME"

    found = _run(
        state,
        limits=_limits(max_unique=2, cost_ceiling=1),
        identity_fn=identity,
        actions_fn=actions,
        lower_bound_fn=lambda current, _g: 0 if pack_state(current) == root_pack else 1,
    )
    assert found.unique == 2
    assert len(found.nodes) == 2
    assert found.lower_bound_prunes == 1
    assert found.proof_prune_identities == 1
    assert found.proof_prune_unretained == 0
    assert found.nodes[1].g == 0
    assert found.nodes[1].action == free
    assert found.nodes[1].ident == b"SAME"
    path, trial, spent = _replay(state, found, 1)
    assert path == [free]
    assert spent == 0
    assert pack_state(trial) == found.nodes[1].store


def test_equality_at_the_ceiling_is_kept_and_one_above_is_rejected():
    state = _pair()
    root_pack = pack_state(state)

    def actions(current: SpiderState):
        if pack_state(current) != root_pack:
            return []
        return [(0, 1, 1), (0, 2, 2)]

    found = _run(
        state,
        limits=_limits(max_unique=10, cost_ceiling=1),
        actions_fn=actions,
        lower_bound_fn=lambda current, _g: 0 if pack_state(current) == root_pack else 1,
    )
    admitted = [node for node in found.nodes if node.parent >= 0]
    assert [node.g for node in admitted] == [0]
    assert admitted[0].action == (0, 2, 2)
    assert admitted[0].g + 1 == 1
    assert found.lower_bound_prunes == 1
    assert found.generated == 2
    assert found.min_f == 0


def test_repeated_proof_dead_arrivals_count_events_once_per_identity():
    state = _pair()
    root_pack = pack_state(state)

    def actions(current: SpiderState):
        if pack_state(current) != root_pack:
            return []
        return [(0, 1, 1), (0, 2, 2)]

    def identity(current: SpiderState) -> bytes:
        if pack_state(current) == root_pack:
            return b"ROOT"
        return b"DEAD"

    def bound(current: SpiderState, _g: int) -> int:
        return 0 if pack_state(current) == root_pack else 100

    found = _run(
        state,
        limits=_limits(max_unique=10, cost_ceiling=5),
        identity_fn=identity,
        actions_fn=actions,
        lower_bound_fn=bound,
    )
    assert found.stop_reason == "complete"
    assert found.unique == 1
    assert len(found.nodes) == 1
    assert found.generated == 2
    assert found.lower_bound_prunes == 2
    assert found.proof_prune_identities == 1
    assert found.proof_prune_unretained == 1
    assert found.expanded == 1
    assert found.max_h == 100
    assert found.terminals == []


def test_terminal_on_the_last_unique_slot_is_stored_and_replayable():
    state = _state({0: "kh"})
    root_pack = pack_state(state)
    terminal_action = (0, 4, 1)
    dead = [(0, index, 1) for index in range(1, 10) if index != 4]
    assert step_cost(state, terminal_action) == 0
    assert all(step_cost(state, action) == 0 for action in dead)

    def actions(current: SpiderState):
        if pack_state(current) != root_pack:
            return []
        return dead + [terminal_action]

    def is_terminal(current: SpiderState) -> bool:
        return (
            current.columns[0].is_empty()
            and current.columns[4].face_up == [Card.parse("kh")]
        )

    def bound(current: SpiderState, _g: int) -> int:
        if pack_state(current) == root_pack or is_terminal(current):
            return 0
        return 100

    common = dict(
        limits=_limits(max_unique=2, cost_ceiling=5),
        actions_fn=actions,
        lower_bound_fn=bound,
        is_terminal=is_terminal,
    )
    solved = _run(state, stop_on_first_terminal=True, **common)
    assert solved.stop_reason == "solved"
    assert solved.unique == 2
    assert len(solved.nodes) == 2
    assert solved.lower_bound_prunes == len(dead)
    assert solved.proof_prune_unretained == len(dead)
    assert solved.generated == len(dead) + 1
    path, trial, spent = _replay(state, solved, solved.terminals[0]["node"])
    assert path == [terminal_action]
    assert spent == 0
    assert is_terminal(trial)
    assert pack_state(trial).hex() == solved.terminals[0]["store"]

    capped = _run(state, stop_on_first_terminal=False, **common)
    assert capped.stop_reason == "unique limit"
    assert capped.unique == 2
    assert len(capped.terminals) == 1
    assert capped.reconstruct(capped.terminals[0]["node"]) == [terminal_action]


def test_zero_cost_transfer_replays_on_ordered_and_symmetry_identities():
    state = _pair()

    def is_terminal(current: SpiderState) -> bool:
        return (
            current.columns[0].face_up == [Card.parse("kh")]
            and current.columns[1].face_up == [Card.parse("qh")]
        )

    for identity in (pack_state, pack_post_stock_symmetry_state):
        found = _run(
            state,
            limits=_limits(max_unique=40, cost_ceiling=3),
            identity_fn=identity,
            is_terminal=is_terminal,
            stop_on_first_terminal=True,
        )
        assert found.stop_reason == "solved"
        assert found.terminals
        path, trial, spent = _replay(state, found, found.terminals[0]["node"])
        assert path
        assert spent == found.terminals[0]["g"]
        assert is_terminal(trial)
        stored = found.nodes[found.terminals[0]["node"]]
        assert stored.store == pack_state(trial)
        assert stored.ident == identity(trial)
    scout = _run(state, limits=_limits(max_unique=20, cost_ceiling=0))
    assert scout.zero_cost_actions >= 1
    assert scout.generated_by_g.get(1, 0) == 0
    assert step_cost(state, (0, 2, 2)) == 0


def test_stock_bearing_columns_stay_distinct_in_the_kernel():
    left = _state({0: "kh", 1: "qh"}, stock="as 2s 3s 4s 5s 6s 7s 8s 9s 10s")
    right = _state({0: "qh", 1: "kh"}, stock="as 2s 3s 4s 5s 6s 7s 8s 9s 10s")
    assert pack_whole_game_identity(left) == pack_state(left)
    assert pack_whole_game_identity(left) != pack_whole_game_identity(right)
    try:
        pack_post_stock_symmetry_state(left)
    except ValueError as exc:
        assert "stock" in str(exc)
    else:
        raise AssertionError("stock-bearing symmetry identity was accepted")
    found = run_search(
        [_root(left), _root(right)],
        limits=_limits(max_unique=2, cost_ceiling=0),
        identity_fn=pack_whole_game_identity,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=("cost",),
        lane_key_fns=(lambda _state, g: (int(g),),),
        is_terminal=lambda _state: False,
        actions_fn=all_legal_actions,
    )
    retained = {node.ident for node in found.nodes if node.parent < 0}
    assert pack_whole_game_identity(left) in retained
    assert pack_whole_game_identity(right) in retained
    assert found.unique >= 2


def test_no_bound_and_zero_bound_search_the_same_graph():
    state = _state({0: "kh"})

    def once(bound):
        return _run(
            state,
            limits=_limits(max_unique=40, cost_ceiling=2),
            lower_bound_fn=bound,
        )

    bare = once(None)
    zero = once(lambda _state, _g: 0)
    assert bare.stop_reason == zero.stop_reason == "complete"
    assert bare.unique == zero.unique == 10
    assert bare.expanded == zero.expanded
    assert bare.generated == zero.generated
    assert bare.duplicate_skips == zero.duplicate_skips
    assert bare.ceiling_prunes == zero.ceiling_prunes
    assert bare.lower_bound_prunes == 0
    assert zero.lower_bound_prunes == 0
    assert bare.proof_prune_identities == 0
    assert zero.proof_prune_identities == 0
    assert zero.proof_prune_unretained == 0
    assert bare.lower_bound_calls == 0
    assert zero.lower_bound_calls > 0

    open_limits = _limits(max_unique=40, cost_ceiling=None)
    open_bare = _run(state, limits=open_limits, lower_bound_fn=None)
    open_bound = _run(
        state,
        limits=open_limits,
        lower_bound_fn=lambda _state, _g: 100,
    )
    assert open_bound.lower_bound_prunes == 0
    assert open_bound.proof_prune_identities == 0
    assert open_bound.lower_bound_calls == 0
    assert open_bound.unique == open_bare.unique
    assert open_bound.generated == open_bare.generated
    assert open_bound.expanded == open_bare.expanded
    assert open_bound.stop_reason == open_bare.stop_reason


def test_cap_exhaustion_is_not_a_completed_frontier():
    state = _state({0: "kh"})
    capped = _run(state, limits=_limits(max_unique=2, cost_ceiling=2))
    assert capped.stop_reason == "unique limit"
    assert capped.unique == 2
    assert capped.terminals == []

    exhausted = _run(state, limits=_limits(max_unique=100, cost_ceiling=2))
    assert exhausted.stop_reason == "complete"
    assert exhausted.unique == 10
    assert exhausted.terminals == []
    assert exhausted.proof_prune_identities == 0


def test_partial_foundations_are_not_a_solution_and_a_cap_is_not_a_proof():
    hearts = [Card("h", rank) for rank in range(13, 1, -1)]
    columns = [Column([], []) for _ in range(10)]
    columns[0] = Column([], hearts)
    columns[1] = Column([], [Card("h", 1)])
    foundations = []
    for suit, copies in (("h", 1), ("s", 2), ("d", 2), ("c", 2)):
        for _copy in range(copies):
            foundations.append([Card(suit, rank) for rank in range(13, 0, -1)])
    state = SpiderState(columns, [], foundations)
    assert len(state.foundations) == 7
    assert state.is_solved() is False

    capped = search_post_sd5(
        _pair(),
        g0=0,
        ceiling=12,
        ordering="completion",
        max_unique=2,
        time_limit_s=5,
    )
    assert capped.solved is False
    assert capped.replay_ok is False
    assert capped.negative_proof is False
    assert capped.stop_reason == "unique limit"
    assert capped.suffix == ()
    assert capped.terminals == 0
    assert len(state.foundations) == 7

    proved = search_post_sd5(
        state,
        g0=10,
        ceiling=10,
        ordering="cost",
        max_unique=20,
        time_limit_s=5,
    )
    assert proved.stop_reason == "complete"
    assert proved.negative_proof is True
    assert proved.solved is False
    assert proved.expanded == 0
