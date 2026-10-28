"""v0.134 purposeful macro contract.

These tests replay small fixtures and the known route's public helpers.
They do not run the 4,000-state discovery or the 20,000-state continuation.
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
from spider.human_strategy.incumbent import proof_prune
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import (
    pack_post_stock_symmetry_state,
    pack_state,
    permute_tableau_columns,
)
from spider.planner.strategic_objectives import ObjectiveKind, evaluate_target
from spider.purposeful_macro import (
    CONTINUATION_RSS_MB,
    CONTINUATION_TIME_S,
    CONTINUATION_UNIQUE,
    DISCOVERY_DEPTH,
    DISCOVERY_PAID,
    DISCOVERY_TIME_S,
    DISCOVERY_UNIQUE,
    HISTORICAL_SINGLE_ROOT,
    ORDERING_COMPONENTS,
    RECEIVER_OBJECTIVE,
    RECEIVER_TARGET,
    accept_improved_route,
    audit_workspace,
    compose_discovered_route,
    discover_macros,
    macro_identity,
    ordering_key,
    rank_macro_actions,
    same_suit_hits,
    search_bridge_roots,
)
from spider.research_actions import all_legal_actions, step_cost, tableau_actions
from spider.stock_boundary_bridge import (
    load_verified_bridge_inputs,
    reference_table,
)

DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
AUTONOMOUS = ROOT / "solutions" / "4925153_autonomous_185.moves"
CANONICAL_SHA = "18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33"
AUTONOMOUS_SHA = "B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73"
MODULE = ROOT / "src" / "spider" / "purposeful_macro.py"
DRIVER = ROOT / "tools" / "purposeful_macro_portfolio_v0_134.py"
ROW = "3h 9s 9d 8c 8d 8h 7s 7d 7c 6s"


def _cards(text: str):
    return [Card.parse(token) for token in text.split() if token]


def _state(columns, stock: str = "", downs=None, foundations=None) -> SpiderState:
    downs = downs or {}
    cols = [
        Column(_cards(downs.get(index, "")), _cards(columns.get(index, "")))
        for index in range(10)
    ]
    return SpiderState(cols, _cards(stock), foundations or [])


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _opening() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL)))


def _sequence(suit: str):
    ranks = ["k", "q", "j", "10", "9", "8", "7", "6", "5", "4", "3", "2", "a"]
    return [Card.parse(rank + suit) for rank in ranks]


def _blocked_receiver():
    """2C blocks the 3H column. 4H cannot move there until 2C is parked."""

    columns = {0: "2c", 2: "4h"}
    downs = {2: "ks"}
    for index in range(3, 10):
        columns[index] = "kh"
        downs[index] = "qs"
    return _state(columns, stock=ROW, downs=downs)


def _two_space_board():
    columns = {1: "2c", 2: "4h", 3: "jh"}
    downs = {2: "ks", 3: "qd"}
    for index in range(5, 10):
        columns[index] = "kh"
        downs[index] = "qs"
    stock = "3h 10h 9s 9d 8c 8d 8h 7s 7d 6c"
    return _state(columns, stock=stock, downs=downs)


def test_solution_hashes_and_historical_baseline_stay_recorded():
    assert _sha(CANONICAL) == CANONICAL_SHA
    assert _sha(AUTONOMOUS) == AUTONOMOUS_SHA
    assert HISTORICAL_SINGLE_ROOT["rerun"] is False
    assert HISTORICAL_SINGLE_ROOT["generated"] == 129336
    assert HISTORICAL_SINGLE_ROOT["lower_bound_prunes"] == 107775
    assert HISTORICAL_SINGLE_ROOT["unique"] == 3317
    assert HISTORICAL_SINGLE_ROOT["expanded"] == 2765
    assert HISTORICAL_SINGLE_ROOT["min_f"] == 166
    assert HISTORICAL_SINGLE_ROOT["max_foundations"] == 3
    assert HISTORICAL_SINGLE_ROOT["reference_checkpoint_matches"] == 0
    assert HISTORICAL_SINGLE_ROOT["lane_exp_goal"] == 2751
    assert DISCOVERY_DEPTH == 8
    assert DISCOVERY_PAID == 4
    assert DISCOVERY_UNIQUE == 4_000
    assert DISCOVERY_TIME_S == 6.0
    assert CONTINUATION_UNIQUE == 20_000
    assert CONTINUATION_TIME_S == 45.0
    assert CONTINUATION_RSS_MB == 512.0
    assert RECEIVER_OBJECTIVE is ObjectiveKind.SHAPE_STOCK_RECEIVER
    assert RECEIVER_TARGET == "column_top_is"
    assert "empty" not in "".join(ORDERING_COMPONENTS)


def test_zero_cost_park_is_kept_and_then_the_receiver_is_seated():
    source = _blocked_receiver()
    row = _cards(ROW)
    assert same_suit_hits(source, row) == 0
    park = (0, 1, 1)
    assert step_cost(source, park) == 0
    assert park in tableau_actions(source)
    ordered = rank_macro_actions(source, tableau_actions(source), row)
    assert ordered[0] == park
    assert len(ordered) == len(tableau_actions(source))
    found = discover_macros(
        source,
        g0=10,
        max_depth=4,
        paid_moves=2,
        max_unique=200,
        time_limit_s=2.0,
        rss_abort_mb=512,
    )
    assert found.candidates
    best = found.candidates[0]
    assert best.actions[0] == park
    assert best.actions == (park, (2, 0, 1))
    assert best.cost == 1
    assert best.g_pre == 11
    assert best.g_post == 12
    assert best.h_post is not None and best.f_post == best.g_post + best.h_post
    assert best.hits == 1
    assert best.purpose_ok
    assert best.complete_game is False
    assert best.workspace.zero_cost_transfers
    trial = source.clone()
    assert replay_actions(trial, list(best.actions)) == 1
    assert same_suit_hits(trial, row) == 1
    assert evaluate_target(trial, "column_top_is", {"column": 0, "suit": "h", "rank": 4})
    missed = discover_macros(
        source,
        g0=10,
        max_depth=4,
        paid_moves=0,
        max_unique=50,
        time_limit_s=2.0,
        rss_abort_mb=512,
    )
    assert missed.zero_cost_actions >= 1
    assert missed.candidates == ()


def test_an_empty_column_does_not_outrank_a_receiver():
    columns = {2: "4h", 8: "9s", 9: "10s"}
    downs = {2: "ks"}
    for index in (1, 3, 4, 5, 6, 7):
        columns[index] = "kh"
        downs[index] = "qs"
    source = _state(columns, stock=ROW, downs=downs)
    row = _cards(ROW)
    seat = (2, 0, 1)
    emptying = (8, 9, 1)
    assert step_cost(source, seat) == 1
    assert step_cost(source, emptying) == 1
    seated = source.clone()
    seated.move(2, 0, 1)
    emptied = source.clone()
    emptied.move(8, 9, 1)
    assert same_suit_hits(seated, row) == 1
    assert same_suit_hits(emptied, row) == 0
    assert len([col for col in emptied.columns if col.is_empty()]) > len(
        [col for col in seated.columns if col.is_empty()]
    )
    assert ordering_key(seated, 5, row) < ordering_key(emptied, 5, row)
    assert ordering_key(seated, 5, row)[0] == -1
    assert ordering_key(emptied, 5, row)[0] == 0
    ordered = rank_macro_actions(source, tableau_actions(source), row)
    assert ordered.index(seat) < ordered.index(emptying)
    found = discover_macros(
        source,
        g0=5,
        max_depth=2,
        paid_moves=1,
        max_unique=80,
        time_limit_s=2.0,
        rss_abort_mb=512,
    )
    assert found.candidates
    assert found.candidates[0].actions[0] == seat
    assert found.candidates[0].hits >= 1
    assert found.candidates[0].complete_game is False


def test_receiver_is_column_specific():
    row = _cards(ROW)
    parked = _state({2: "4h"}, stock=ROW)
    assert same_suit_hits(parked, row) == 0
    assert not evaluate_target(parked, "column_top_is", {"column": 0, "suit": "h", "rank": 4})
    seated = parked.clone()
    seated.move(2, 0, 1)
    assert same_suit_hits(seated, row) == 1
    assert evaluate_target(seated, "column_top_is", {"column": 0, "suit": "h", "rank": 4})
    wrong = _state({3: "4h"}, stock=ROW)
    assert same_suit_hits(wrong, row) == 0


def test_two_spaces_are_a_resource_and_the_search_uses_them():
    source = _two_space_board()
    path = ((1, 4, 1), (2, 0, 1), (3, 1, 1))
    assert step_cost(source, path[0]) == 0
    audit = audit_workspace(source, path)
    assert audit.two_spaces_available
    assert audit.zero_cost_transfers
    assert audit.spaces_spent_at
    assert audit.relocated_holding_two
    assert audit.empty_at_start == 2
    found = discover_macros(
        source,
        g0=20,
        max_depth=4,
        paid_moves=2,
        max_unique=400,
        time_limit_s=2.0,
        rss_abort_mb=512,
    )
    purposeful = [item for item in found.candidates if item.hits >= 2]
    assert purposeful
    best = purposeful[0]
    assert best.workspace.two_spaces_available
    assert best.workspace.zero_cost_transfers
    assert best.workspace.spaces_spent_at
    assert best.g_post == 20 + best.cost + 1
    assert best.complete_game is False
    trial = source.clone()
    assert replay_actions(trial, list(best.actions)) == best.cost


def test_stock_bearing_identity_stays_physical():
    left = _blocked_receiver()
    columns = {0: "4h", 1: "2c", 2: "kh"}
    right_columns = {0: "2c", 1: "4h", 2: "kh"}
    downs = {2: "qs"}
    for index in range(3, 10):
        columns[index] = "kh"
        right_columns[index] = "kh"
        downs[index] = "qs"
    stocked = _state(columns, stock=ROW, downs=downs)
    swapped = _state(right_columns, stock=ROW, downs=downs)
    assert stocked.stock and swapped.stock
    assert macro_identity(stocked) == pack_state(stocked)
    assert macro_identity(stocked) != macro_identity(swapped)
    try:
        pack_post_stock_symmetry_state(swapped)
    except ValueError:
        raised = True
    else:
        raised = False
    assert raised
    found = discover_macros(
        left,
        g0=1,
        max_depth=2,
        paid_moves=1,
        max_unique=20,
        time_limit_s=2.0,
        rss_abort_mb=512,
    )
    assert found.searched
    assert found.unique >= 1


def test_origin_reconstruction_uses_the_matching_prefix():
    decoy = _state({0: "kh"})
    near = _state({0: " ".join(str(card) for card in _sequence("c"))}, foundations=[
        _sequence(suit) for suit in ("s", "s", "h", "h", "d", "d", "c")
    ])
    finishing = (0, 1, 13)
    assert step_cost(near, finishing) == 0
    roots = [
        _root(decoy, 160, ((0, 1, 1),)),
        _root(near, 160, ((1, 2, 1),)),
    ]
    root_pack = pack_state(near)

    def actions(state: SpiderState):
        if pack_state(state) == root_pack:
            return [finishing]
        return []

    found = search_bridge_roots(
        roots,
        references=reference_table([]),
        ordering_targets=(),
        ceiling=171,
        max_unique=10,
        time_limit_s=2.0,
        rss_abort_mb=512,
        lower_bound_fn=lambda _state, _g: 0,
        actions_fn=actions,
    )
    assert found.accepted
    assert found.kind == "solved"
    assert found.origin == 1
    assert found.macro == ((1, 2, 1),)
    assert found.continuation == (finishing,)
    assert found.g == 160
    assert found.expanded >= 1
    assert found.expansions_by_origin[1] >= 1
    assert found.independent_cold_complete is False


def test_remapped_suffix_is_attached_to_the_matching_origin():
    opening = _opening()
    canonical = parse_moves_file(CANONICAL)
    _early, table, targets, _checkpoints = load_verified_bridge_inputs(opening, canonical)
    reference = table.stops[0]
    candidate = None
    mapping = None
    for left in range(10):
        for right in range(left + 1, 10):
            perm = list(range(10))
            perm[left], perm[right] = perm[right], perm[left]
            trial = permute_tableau_columns(reference.state, perm)
            if pack_state(trial) == pack_state(reference.state):
                continue
            candidate = trial
            mapping = (left, right)
            break
        if candidate is not None:
            break
    assert candidate is not None and mapping is not None
    decoy = _state({0: "kh"})
    macro = ((2, 3, 1),)
    found = search_bridge_roots(
        [_root(decoy, 149, ((0, 1, 1),)), _root(candidate, 149, macro)],
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
    assert found.continuation == ()
    assert found.kind == "reference rejoin"
    assert found.projected_cost == 171
    assert found.remapped_suffix
    full = compose_discovered_route(canonical, found.macro, found.continuation, found.remapped_suffix)
    assert full[:140] == list(canonical[:140])
    assert full[140] == macro[0]
    assert full[141] == ("deal",)
    assert full[142:] == list(found.remapped_suffix)


def test_last_slot_terminal_is_admitted_and_over_ceiling_is_not():
    near = _state(
        {0: " ".join(str(card) for card in _sequence("c"))},
        foundations=[_sequence(suit) for suit in ("s", "s", "h", "h", "d", "d", "c")],
    )
    pack = pack_state(near)

    def actions(state: SpiderState):
        if pack_state(state) == pack:
            return [(0, 1, 13)]
        return []

    filled = search_bridge_roots(
        [_root(near, 170, ())],
        references=reference_table([]),
        ordering_targets=(),
        ceiling=171,
        max_unique=2,
        time_limit_s=2.0,
        rss_abort_mb=512,
        lower_bound_fn=lambda _state, _g: 0,
        actions_fn=actions,
    )
    assert filled.accepted
    assert filled.kind == "solved"
    assert filled.unique == 2
    assert filled.expanded == 1
    assert filled.g == 170
    solved = SpiderState([Column([], []) for _index in range(10)], [], [_sequence(suit) for suit in "shdc" for _copy in range(2)])
    assert solved.is_solved()
    early = search_bridge_roots(
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
    over = search_bridge_roots(
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
    root = pack_state(source)
    kept = (0, 1, 1)
    pruned = (0, 2, 2)
    assert step_cost(source, kept) == 1
    assert step_cost(source, pruned) == 1
    kept_state = source.clone()
    pruned_state = source.clone()
    kept_state.move(0, 1, 1)
    pruned_state.move(0, 2, 2)
    kept_pack = pack_state(kept_state)
    assert kept_pack != pack_state(pruned_state)
    assert kept_pack != root
    assert proof_prune(171, 0, 171)

    def actions(current: SpiderState):
        if pack_state(current) != root:
            return []
        return [kept, pruned]

    def bound(current: SpiderState, _g: int) -> int:
        if pack_state(current) == root or pack_state(current) == kept_pack:
            return 0
        return 1

    found = search_bridge_roots(
        [_root(source, 170, ())],
        references=reference_table([]),
        ordering_targets=(),
        ceiling=171,
        max_unique=10,
        time_limit_s=2.0,
        rss_abort_mb=512,
        lower_bound_fn=bound,
        actions_fn=actions,
    )
    assert found.generated == 2
    assert found.unique == 2
    assert found.lower_bound_prunes == 1
    assert found.proof_prune_identities == 1
    assert not found.accepted
    assert found.stop_reason == "complete"
    assert found.negative_within_cap


def test_a_tactical_receiver_is_not_a_complete_game():
    source = _blocked_receiver()
    found = discover_macros(
        source,
        g0=4,
        max_depth=4,
        paid_moves=2,
        max_unique=80,
        time_limit_s=2.0,
        rss_abort_mb=512,
    )
    assert found.candidates
    assert found.candidates[0].purpose_ok
    assert found.public()["complete_game"] is False
    assert accept_improved_route(_opening(), found.candidates[0].actions, expected_cost=found.candidates[0].cost) is None


def test_generator_does_not_seed_the_named_preparation_or_retune_the_bridge():
    text = MODULE.read_text(encoding="utf-8")
    assert "(1, 4, 1)" not in text
    assert "(2, 0, 2)" not in text
    assert "(8, 1, 1)" not in text
    assert "workspace_quotient_key" not in text
    assert "strategic_action_order" not in text
    assert "search_post_sd5" not in text
    assert "80_000" not in text
    assert "80000" not in text
    search_source = inspect.getsource(_search_source())
    assert "assess_immediate_deal" not in search_source
    assert "tableau_actions" in search_source
    assert "pack_state" in search_source
    bridge_source = inspect.getsource(search_bridge_roots)
    assert "bridge_action_order" in bridge_source
    assert "rank_macro_actions" not in bridge_source
    assert "pack_whole_game_identity" in bridge_source
    driver = DRIVER.read_text(encoding="utf-8")
    assert "search_post_sd5" not in driver
    assert "search_route_bridge" not in driver
    assert "80_000" not in driver
    assert "80000" not in driver
    assert "time_limit_s=90" not in driver
    assert "EARLY_PREP" not in inspect.getsource(discover_macros)


def _search_source():
    from spider.purposeful_macro import _search_tableau_macros

    return _search_tableau_macros


def _root(state: SpiderState, g: int, macro):
    from spider.purposeful_macro import PostDealRoot

    return PostDealRoot(state=state, g=g, macro=tuple(macro), pack=pack_state(state).hex())


def test_action_order_keeps_every_legal_move():
    source = _blocked_receiver()
    actions = all_legal_actions(source)
    tableau = [action for action in actions if action != ("deal",)]
    ordered = rank_macro_actions(source, tableau)
    assert len(ordered) == len(tableau)
    assert sorted(map(repr, ordered)) == sorted(map(repr, tableau))
    assert ("deal",) not in ordered
