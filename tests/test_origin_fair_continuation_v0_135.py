"""v0.135 origin-fair continuation contracts.

These tests use tiny limits. They do not run the 6-second macro discovery
or the 20,000-state continuation.
"""

from __future__ import annotations

import hashlib
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file
from spider.origin_fair_continuation import (
    CONTINUATION_RSS_MB,
    CONTINUATION_TIME_S,
    CONTINUATION_UNIQUE,
    HISTORICAL_V0134,
    cost_lane_key,
    fair_lane_names,
    goal_lane_key,
    search_origin_fair,
)
from spider.packed_state import pack_post_stock_symmetry_state, pack_state
from spider.purposeful_macro import PostDealRoot, compose_discovered_route, discover_macros, search_bridge_roots
from spider.research_actions import apply_action, step_cost, tableau_actions
from spider.search_kernel import SearchLimits, run_search
from spider.stock_boundary_bridge import load_verified_bridge_inputs, reference_table

DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
AUTONOMOUS = ROOT / "solutions" / "4925153_autonomous_185.moves"
CANONICAL_SHA = "18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33"
AUTONOMOUS_SHA = "B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73"
DRIVER = ROOT / "tools" / "origin_fair_continuation_v0_135.py"
MACRO = ROOT / "src" / "spider" / "purposeful_macro.py"


def _columns(*runs, foundations=None) -> SpiderState:
    cols = [Column([], list(run)) for run in runs]
    while len(cols) < 10:
        cols.append(Column([], []))
    return SpiderState(cols, [], list(foundations or []))


def _kings(n: int):
    return [[Card("s", 13)] for _ in range(n)]


def _kernel_root(state: SpiderState, g: int) -> dict:
    return {"g": g, "ordered_digest": pack_state(state).hex()}


def _root(state: SpiderState, g: int, macro=()) -> PostDealRoot:
    return PostDealRoot(state=state, g=g, macro=tuple(macro), pack=pack_state(state).hex())


def _cards(text: str):
    return [Card.parse(token) for token in text.split() if token]


def _state(columns, foundations=None) -> SpiderState:
    cols = [Column([], _cards(columns.get(index, ""))) for index in range(10)]
    return SpiderState(cols, [], foundations or [])


def _sequence(suit: str):
    ranks = ["k", "q", "j", "10", "9", "8", "7", "6", "5", "4", "3", "2", "a"]
    return [Card.parse(rank + suit) for rank in ranks]


def _opening() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL)))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _ladder(suit: str) -> SpiderState:
    return _columns(
        [Card(suit, 6), Card(suit, 5), Card(suit, 4), Card(suit, 3)],
        [Card(suit, 4)],
        [Card(suit, 5)],
        [Card(suit, 6)],
        [Card(suit, 7)],
        *_kings(5),
    )


def _chain(suit: str, moves):
    state = _ladder(suit)
    table = {}
    packs = []
    for action in moves:
        packed = pack_state(state)
        table[packed] = [action]
        packs.append(packed)
        apply_action(state, action)
    return table, packs


def test_solution_hashes_and_budgets_stay_at_the_v0134_caps():
    assert _sha(CANONICAL) == CANONICAL_SHA
    assert _sha(AUTONOMOUS) == AUTONOMOUS_SHA
    assert CONTINUATION_UNIQUE == 20_000
    assert CONTINUATION_TIME_S == 45.0
    assert CONTINUATION_RSS_MB == 512.0
    assert HISTORICAL_V0134["rerun"] is False
    assert HISTORICAL_V0134["expansions_by_origin"] == (1, 1, 0, 0, 0, 0, 0, 2190)
    assert sum(HISTORICAL_V0134["expansions_by_origin"]) == HISTORICAL_V0134["expanded"]
    assert HISTORICAL_V0134["lane_exp_goal"] == 2180
    assert HISTORICAL_V0134["lane_exp_cost"] == 12


def test_legacy_callers_keep_the_same_schedule_when_the_hook_is_omitted():
    assert inspect.signature(run_search).parameters["origin_lane_keys_fn"].default is None
    state = _columns([Card("c", 5), Card("c", 4)], [Card("c", 6)], *_kings(8))
    limits = SearchLimits(max_unique=20, time_limit_s=2.0, rss_abort_mb=4096, cost_ceiling=3)
    shared = dict(
        identity_fn=pack_state,
        is_terminal=lambda _state: False,
        actions_fn=tableau_actions,
    )
    keys = lambda _state, g: {"goal": (g,), "cost": (g,)}
    legacy = run_search(
        [_kernel_root(state, 0)],
        limits=limits,
        lane_names=("goal", "cost"),
        lane_keys_fn=keys,
        **shared,
    )
    hooked = run_search(
        [_kernel_root(state, 0)],
        limits=limits,
        lane_names=("goal", "cost"),
        origin_lane_keys_fn=lambda _state, g, _origin: keys(_state, g),
        **shared,
    )
    assert list(legacy.lane_pops) == ["goal", "cost"]
    assert legacy.expanded == hooked.expanded
    assert legacy.unique == hooked.unique
    assert legacy.stop_reason == hooked.stop_reason
    assert [node.g for node in legacy.nodes] == [node.g for node in hooked.nodes]
    assert "origin_lane_keys_fn" not in inspect.getsource(search_bridge_roots)
    assert "origin_lane_keys_fn" not in MACRO.read_text(encoding="utf-8")


def test_cost_key_keeps_ties_and_drops_a_worse_displacement():
    best, key = cost_lane_key(4, 5, 10**9)
    assert best == 5
    assert key == (4, 5)
    best, tie = cost_lane_key(6, 5, best)
    assert tie == (6, 5)
    best, worse = cost_lane_key(7, 9, best)
    assert worse is None
    assert best == 5
    best, improved = cost_lane_key(8, 2, best)
    assert best == 2
    assert improved == (8, 2)
    assert goal_lane_key(8, 9) == (9, 8)

    source = _ladder("h")
    improving = (0, 2, 2)
    worse_move = (0, 1, 1)
    assert improving in tableau_actions(source)
    assert worse_move in tableau_actions(source)
    better = source.clone()
    worse_state = source.clone()
    apply_action(better, improving)
    apply_action(worse_state, worse_move)
    packs = {
        pack_state(source): 5,
        pack_state(better): 1,
        pack_state(worse_state): 9,
    }
    nearest = [10**9]
    cost_packs = []

    def keys(state, g, _origin):
        updated, cost = cost_lane_key(g, packs[pack_state(state)], nearest[0])
        nearest[0] = updated
        if cost is not None:
            cost_packs.append(pack_state(state))
        return {"0.goal": goal_lane_key(g, packs[pack_state(state)]), "0.cost": cost}

    def order(_state, actions):
        wanted = [improving, worse_move]
        return [action for action in wanted if action in actions]

    found = run_search(
        [_kernel_root(source, 0)],
        limits=SearchLimits(max_unique=10, time_limit_s=2.0, rss_abort_mb=4096, cost_ceiling=4),
        identity_fn=pack_state,
        lane_names=("0.goal", "0.cost"),
        origin_lane_keys_fn=keys,
        is_terminal=lambda _state: False,
        actions_fn=lambda state: [improving, worse_move] if pack_state(state) == pack_state(source) else [],
        action_order=order,
    )
    assert pack_state(better) in cost_packs
    assert pack_state(worse_state) not in cost_packs
    assert found.unique == 3
    assert any(node.store == pack_state(worse_state) for node in found.nodes)


def test_one_node_on_two_lanes_expands_once():
    state = _columns([Card("h", 13)], [Card("s", 7)], *_kings(8))
    packed = pack_state(state)
    calls = []

    def actions(current):
        calls.append(pack_state(current))
        return []

    found = run_search(
        [_kernel_root(state, 0)],
        limits=SearchLimits(max_unique=5, time_limit_s=2.0, rss_abort_mb=4096, cost_ceiling=2),
        identity_fn=pack_state,
        lane_names=("0.goal", "0.cost"),
        origin_lane_keys_fn=lambda _state, g, _origin: {"0.goal": (g,), "0.cost": (g,)},
        is_terminal=lambda _state: False,
        actions_fn=actions,
    )
    assert calls == [packed]
    assert found.expanded == 1
    assert found.stale_skips >= 1
    assert found.lane_exp["0.goal"] + found.lane_exp["0.cost"] == 1
    assert found.lane_remaining["0.goal"] == 0
    assert found.lane_remaining["0.cost"] == 0


def test_caller_index_survives_admission_sorting():
    states = [
        _columns([Card("h", 13)], *_kings(9)),
        _columns([Card("d", 13)], *_kings(9)),
        _columns([Card("c", 13)], *_kings(9)),
    ]
    packs = [pack_state(state) for state in states]
    seen = []
    found = run_search(
        [_kernel_root(states[0], 9), _kernel_root(states[1], 1), _kernel_root(states[2], 5)],
        limits=SearchLimits(max_unique=5, time_limit_s=2.0, rss_abort_mb=4096, cost_ceiling=20),
        identity_fn=pack_state,
        lane_names=fair_lane_names(3),
        origin_lane_keys_fn=lambda _state, g, origin: {f"{origin}.goal": (0, g)},
        is_terminal=lambda _state: False,
        actions_fn=lambda state: seen.append(pack_state(state)) or [],
    )
    assert seen[:3] == packs
    for index, packed in enumerate(packs):
        node = next(item for item in found.nodes if item.parent < 0 and item.store == packed)
        assert node.origin == index
    assert found.expanded == 3


def test_three_viable_roots_are_covered_and_a_shared_lane_is_not():
    moves = ((0, 1, 1), (0, 2, 1), (0, 3, 1), (0, 4, 1))
    heart, heart_packs = _chain("h", moves)
    spade, spade_packs = _chain("s", moves[:1])
    diamond, diamond_packs = _chain("d", moves[:1])
    roots = [_ladder("h"), _ladder("s"), _ladder("d")]
    root_packs = [pack_state(state) for state in roots]
    owned = {pack: 0 for pack in heart_packs}
    owned[spade_packs[0]] = 1
    owned[diamond_packs[0]] = 2
    table = {}
    table.update(heart)
    table.update(spade)
    table.update(diamond)

    def actions(state):
        return list(table.get(pack_state(state), []))

    limits = SearchLimits(max_unique=6, time_limit_s=2.0, rss_abort_mb=4096, cost_ceiling=8)
    fair_seen = []
    fair = run_search(
        [_kernel_root(state, 0) for state in roots],
        limits=limits,
        identity_fn=pack_state,
        lane_names=fair_lane_names(3),
        origin_lane_keys_fn=lambda state, g, origin: {f"{origin}.goal": (0, g)},
        is_terminal=lambda _state: False,
        actions_fn=lambda state: fair_seen.append(pack_state(state)) or actions(state),
    )
    assert fair_seen[:3] == root_packs
    assert fair.stop_reason == "unique limit"
    assert {owned[pack] for pack in fair_seen} == {0, 1, 2}

    unfair_seen = []

    def unfair_keys(state, g):
        rank = 0 if pack_state(state) in set(heart_packs) else 100
        return {"goal": (rank, g)}

    unfair = run_search(
        [_kernel_root(state, 0) for state in roots],
        limits=limits,
        identity_fn=pack_state,
        lane_names=("goal",),
        lane_keys_fn=unfair_keys,
        is_terminal=lambda _state: False,
        actions_fn=lambda state: unfair_seen.append(pack_state(state)) or actions(state),
    )
    assert unfair.expanded >= 2
    assert set(unfair_seen).isdisjoint({spade_packs[0], diamond_packs[0]})
    assert all(pack in set(heart_packs) for pack in unfair_seen)


def test_cross_origin_better_g_keeps_the_winning_replay():
    filler = (
        [Card("s", 7)],
        [Card("h", 7)],
        [Card("d", 7)],
        [Card("s", 9)],
        [Card("h", 9)],
        [Card("d", 9)],
        [Card("s", 2)],
        [Card("h", 2)],
    )
    cheap = _columns([Card("c", 6)], [Card("h", 13), Card("c", 5)], *filler)
    expensive = _columns([Card("c", 6), Card("c", 5)], [Card("h", 13)], *filler)
    action = None
    for candidate in tableau_actions(cheap):
        trial = cheap.clone()
        cost = apply_action(trial, candidate)
        if cost == 1 and pack_state(trial) == pack_state(expensive):
            action = candidate
            break
    assert action is not None
    cheap_pack = pack_state(cheap)
    found = run_search(
        [_kernel_root(expensive, 3), _kernel_root(cheap, 0)],
        limits=SearchLimits(max_unique=8, time_limit_s=2.0, rss_abort_mb=4096, cost_ceiling=6),
        identity_fn=pack_state,
        lane_names=fair_lane_names(2),
        origin_lane_keys_fn=lambda _state, g, origin: {f"{origin}.goal": (0, g)},
        is_terminal=lambda _state: False,
        actions_fn=lambda state: [action] if pack_state(state) == cheap_pack else [],
    )
    winner = next(
        node
        for node in found.nodes
        if node.ident == pack_state(expensive) and node.parent >= 0 and node.g == 1
    )
    assert winner.origin == 1
    replay = cheap.clone()
    spent = 0
    for step in found.reconstruct(found.nodes.index(winner)):
        spent += apply_action(replay, step)
    assert spent == 1
    assert pack_state(replay) == winner.store
    assert any(node.parent < 0 and node.origin == 0 and node.g == 3 for node in found.nodes)


def test_a_dominated_root_is_omitted_and_the_survivor_keeps_its_macro():
    left = _columns([Card("s", 13)], [Card("h", 12)], *_kings(8))
    right = _columns([Card("h", 12)], [Card("s", 13)], *_kings(8))
    assert pack_state(left) != pack_state(right)
    assert pack_post_stock_symmetry_state(left) == pack_post_stock_symmetry_state(right)
    found = search_origin_fair(
        [
            _root(right, 12, ((0, 1, 1),)),
            _root(left, 10, ((2, 3, 1),)),
        ],
        references=reference_table([]),
        ordering_targets=(),
        ceiling=171,
        max_unique=5,
        time_limit_s=2.0,
        rss_abort_mb=512,
        lower_bound_fn=lambda _state, _g: 0,
        actions_fn=lambda _state: [],
    )
    assert len(found.dominated) == 1
    assert found.dominated[0]["dropped_g"] == 12
    assert found.dominated[0]["kept_g"] == 10
    assert found.expansions_by_origin == (1,)
    assert found.origins[0]["macro"] == ["move 3 4 1"]
    assert found.origins[0]["pack"] == pack_state(left).hex()
    assert found.origins[0]["status"] == "exhausted"
    assert found.lane_order == ("0.goal", "0.cost")


def test_a_proof_dead_root_is_not_called_starvation():
    live = _columns([Card("h", 4)], [Card("h", 3)], *_kings(8))
    dead = _columns([Card("d", 4)], [Card("d", 3)], *_kings(8))
    live_pack = pack_state(live)

    def bound(state, _g):
        return 0 if pack_state(state) == live_pack else 50

    found = search_origin_fair(
        [_root(dead, 170, ((0, 1, 1),)), _root(live, 1, ((1, 2, 1),))],
        references=reference_table([]),
        ordering_targets=(),
        ceiling=171,
        max_unique=6,
        time_limit_s=2.0,
        rss_abort_mb=512,
        lower_bound_fn=bound,
        actions_fn=lambda state: [(1, 0, 1)] if pack_state(state) == live_pack else [],
    )
    assert found.origins[0]["status"] == "no viable frontier"
    assert found.origins[0]["expanded"] == 0
    assert found.origins[1]["expanded"] >= 1
    assert found.origins[1]["status"] in {"live", "exhausted"}
    assert found.lower_bound_prunes >= 1


def test_zero_cost_completion_uses_the_matching_origin():
    decoy = _state({0: "kh"})
    near = _state(
        {0: " ".join(str(card) for card in _sequence("c"))},
        foundations=[_sequence(suit) for suit in ("s", "s", "h", "h", "d", "d", "c")],
    )
    finishing = (0, 1, 13)
    assert step_cost(near, finishing) == 0
    near_pack = pack_state(near)
    found = search_origin_fair(
        [_root(decoy, 160, ((0, 1, 1),)), _root(near, 160, ((1, 2, 1),))],
        references=reference_table([]),
        ordering_targets=(),
        ceiling=171,
        max_unique=10,
        time_limit_s=2.0,
        rss_abort_mb=512,
        lower_bound_fn=lambda _state, _g: 0,
        actions_fn=lambda state: [finishing] if pack_state(state) == near_pack else [],
    )
    assert found.accepted
    assert found.kind == "solved"
    assert found.origin == 1
    assert found.macro == ((1, 2, 1),)
    assert found.continuation == (finishing,)
    assert found.g == 160
    assert found.zero_cost_actions >= 1
    assert found.expansions_by_origin[0] >= 1
    assert found.expansions_by_origin[1] >= 1
    assert found.independent_cold_complete is False


def test_remapped_suffix_stays_on_the_rejoining_origin():
    opening = _opening()
    canonical = parse_moves_file(CANONICAL)
    _early, table, targets, _checkpoints = load_verified_bridge_inputs(opening, canonical)
    reference = table.stops[0]
    candidate = None
    for left in range(10):
        for right in range(left + 1, 10):
            perm = list(range(10))
            perm[left], perm[right] = perm[right], perm[left]
            from spider.packed_state import permute_tableau_columns

            trial = permute_tableau_columns(reference.state, perm)
            if pack_state(trial) == pack_state(reference.state):
                continue
            candidate = trial
            break
        if candidate is not None:
            break
    assert candidate is not None
    macro = ((2, 3, 1),)
    found = search_origin_fair(
        [_root(_state({0: "kh"}), 149, ((0, 1, 1),)), _root(candidate, 149, macro)],
        references=table,
        ordering_targets=targets,
        ceiling=171,
        max_unique=5,
        time_limit_s=2.0,
        rss_abort_mb=512,
        lower_bound_fn=lambda _state, _g: 0,
    )
    assert found.accepted
    assert found.searched is False
    assert found.expanded == 0
    assert found.origin == 1
    assert found.macro == macro
    assert found.kind == "reference rejoin"
    assert found.projected_cost == 171
    assert found.remapped_suffix
    assert found.origins[1]["status"] == "admitted rejoin"
    assert found.origins[0]["status"] == "not searched"
    full = compose_discovered_route(canonical, found.macro, found.continuation, found.remapped_suffix)
    assert full[140] == macro[0]
    assert full[141] == ("deal",)
    assert full[142:] == list(found.remapped_suffix)


def test_last_slot_terminal_and_the_ceiling_boundary():
    near = _state(
        {0: " ".join(str(card) for card in _sequence("c"))},
        foundations=[_sequence(suit) for suit in ("s", "s", "h", "h", "d", "d", "c")],
    )
    packed = pack_state(near)
    filled = search_origin_fair(
        [_root(near, 170, ())],
        references=reference_table([]),
        ordering_targets=(),
        ceiling=171,
        max_unique=2,
        time_limit_s=2.0,
        rss_abort_mb=512,
        lower_bound_fn=lambda _state, _g: 0,
        actions_fn=lambda state: [(0, 1, 13)] if pack_state(state) == packed else [],
    )
    assert filled.accepted
    assert filled.unique == 2
    assert filled.expanded == 1
    assert filled.g == 170
    solved = SpiderState(
        [Column([], []) for _index in range(10)],
        [],
        [_sequence(suit) for suit in "shdc" for _copy in range(2)],
    )
    assert solved.is_solved()
    early = search_origin_fair(
        [_root(solved, 171, ((0, 1, 1),))],
        references=reference_table([]),
        ordering_targets=(),
        ceiling=171,
        max_unique=4,
        time_limit_s=1.0,
        rss_abort_mb=512,
    )
    assert early.accepted
    assert early.searched is False
    assert early.expanded == 0
    assert early.projected_cost == 171
    over = search_origin_fair(
        [_root(solved, 172, ())],
        references=reference_table([]),
        ordering_targets=(),
        ceiling=171,
        max_unique=4,
        time_limit_s=1.0,
        rss_abort_mb=512,
    )
    assert not over.accepted
    assert over.searched
    assert over.expanded == 0


def test_proof_bound_keeps_equality_and_rejects_one_above():
    source = _state(
        {
            0: "7s 6s",
            1: "7h",
            2: "8c",
            3: "ks",
            4: "kh",
            5: "kd",
            6: "kc",
            7: "qs",
            8: "qh",
            9: "qd",
        }
    )
    root_pack = pack_state(source)
    kept = (0, 1, 1)
    pruned = (0, 2, 2)
    assert step_cost(source, kept) == 1
    assert step_cost(source, pruned) == 1
    kept_state = source.clone()
    kept_state.move(0, 1, 1)
    kept_pack = pack_state(kept_state)

    def bound(current, _g):
        if pack_state(current) == root_pack or pack_state(current) == kept_pack:
            return 0
        return 1

    found = search_origin_fair(
        [_root(source, 170, ())],
        references=reference_table([]),
        ordering_targets=(),
        ceiling=171,
        max_unique=10,
        time_limit_s=2.0,
        rss_abort_mb=512,
        lower_bound_fn=bound,
        actions_fn=lambda current: [kept, pruned] if pack_state(current) == root_pack else [],
    )
    assert found.generated == 2
    assert found.unique == 2
    assert found.lower_bound_prunes == 1
    assert found.proof_prune_identities == 1
    assert not found.accepted
    assert found.stop_reason == "complete"
    assert found.negative_within_cap
    assert "proof_prune(" not in inspect.getsource(search_origin_fair)


def test_driver_does_not_raise_caps_or_call_the_old_continuation():
    text = DRIVER.read_text(encoding="utf-8")
    assert "search_bridge_roots" not in text
    assert "search_post_sd5" not in text
    assert "search_route_bridge" not in text
    assert "80_000" not in text
    assert "80000" not in text
    assert "time_limit_s=90" not in text
    assert "discover_macros" in text
    assert "search_origin_fair" in text
    assert "(1, 4, 1)" not in inspect.getsource(discover_macros)
    assert "(2, 0, 2)" not in inspect.getsource(discover_macros)
    assert "(8, 1, 1)" not in inspect.getsource(discover_macros)
