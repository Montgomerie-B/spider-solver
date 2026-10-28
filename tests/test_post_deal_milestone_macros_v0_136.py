"""v0.136 post-deal milestone contract.

The canonical window is replayed only to show the outcome is feasible.
Those actions are not written into the solver. The 12,000-state control,
the eight tactic searches, and the 45-second continuation stay in the driver.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.human_strategy.anchored import build_checkpoints
from spider.metrics import parse_moves_file
from spider.packed_state import (
    pack_state,
    pack_whole_game_identity,
    permute_tableau_columns,
    unpack_state,
)
from spider.post_deal_milestone import (
    CONTROL_DEPTH,
    CONTROL_PAID,
    CONTROL_PROOF,
    CONTROL_TIME_S,
    CONTROL_UNIQUE,
    ENDPOINT_CEILING,
    TACTIC_DEPTH,
    TACTIC_PAID,
    TACTIC_PROOF,
    TACTIC_TIME_S,
    TACTIC_UNIQUE,
    MilestoneEndpoint,
    control_succeeded,
    milestone_identity,
    milestone_met,
    rank_milestone_actions,
    retain_endpoints,
    route_for_endpoint,
    search_milestone,
    spec_from_source,
    suit_foundation_count,
)
from spider.purposeful_macro import CHECKPOINT_PREP, accept_improved_route
from spider.research_actions import apply_action, face_down_count, step_cost, tableau_actions
from spider.search_kernel import SearchLimits, run_search

DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
MODULE = ROOT / "src" / "spider" / "post_deal_milestone.py"
DRIVER = ROOT / "tools" / "post_deal_milestone_macros_v0_136.py"
KERNEL = ROOT / "src" / "spider" / "search_kernel.py"


def _cards(text: str):
    return [Card.parse(token) for token in text.split() if token]


def _state(columns, stock: str = "", downs=None, foundations=None) -> SpiderState:
    downs = downs or {}
    cols = [
        Column(_cards(downs.get(index, "")), _cards(columns.get(index, "")))
        for index in range(10)
    ]
    return SpiderState(cols, _cards(stock), foundations or [])


def _ranks(high: int, low: int, suit: str) -> str:
    names = {1: "a", 10: "10", 11: "j", 12: "q", 13: "k"}
    return " ".join(names.get(rank, str(rank)) + suit for rank in range(high, low - 1, -1))


def _root(state: SpiderState, g: int = 0) -> dict:
    return {"ordered_digest": pack_state(state).hex(), "g": g}


def _opening():
    return SpiderState.from_cards(list(load_deal(DEAL)))


def _foundation_board():
    """Ace is buried. Two paid moves reveal it and complete the club run."""

    columns = {0: _ranks(13, 2, "c"), 1: "5d", 2: "4d"}
    downs = {2: "ac"}
    for index in range(3, 10):
        columns[index] = "kh"
        downs[index] = "qs"
    return _state(columns, downs=downs)


def _park_board():
    """Kh blocks column 0. Parking it is free and does not reveal or join."""

    columns = {0: "kh", 2: "4c", 3: "5c"}
    downs = {2: "qs"}
    for index in range(4, 10):
        columns[index] = "kd"
        downs[index] = "qs"
    return _state(columns, downs=downs)


def test_budgets_stay_at_the_issue_caps():
    assert CONTROL_PAID == 8
    assert CONTROL_DEPTH == 12
    assert CONTROL_UNIQUE == 12_000
    assert CONTROL_TIME_S == 12.0
    assert CONTROL_PROOF == 172
    assert TACTIC_PAID == 12
    assert TACTIC_DEPTH == 18
    assert TACTIC_UNIQUE == 6_000
    assert TACTIC_TIME_S == 6.0
    assert TACTIC_PROOF == 171
    assert ENDPOINT_CEILING == 171
    assert SearchLimits().proof_ceiling is None


def test_canonical_window_is_feasible_and_not_seeded():
    opening = _opening()
    actions = parse_moves_file(CANONICAL)
    checkpoints = build_checkpoints(opening, actions)
    post = checkpoints[152]
    assert post.g == 150
    assert post.state.stock == []
    assert suit_foundation_count(post.state, "c") == 0
    assert face_down_count(post.state) >= 1
    spec = spec_from_source(post.state, "c")
    assert not milestone_met(post.state, spec)
    state = post.state.clone()
    reveal_step = None
    foundation_step = None
    for step, action in enumerate(actions[152:160], start=1):
        before_hidden = face_down_count(state)
        before_clubs = suit_foundation_count(state, "c")
        apply_action(state, action)
        if reveal_step is None and face_down_count(state) < before_hidden:
            reveal_step = step
        if foundation_step is None and suit_foundation_count(state, "c") > before_clubs:
            foundation_step = step
    assert checkpoints[160].g == 158
    assert reveal_step == 7
    assert foundation_step == 8
    assert milestone_met(state, spec)
    assert pack_state(state) == pack_state(checkpoints[160].state)
    source = MODULE.read_text(encoding="utf-8")
    for action in actions[152:160]:
        assert repr(action) not in source
    assert "4925153" not in source
    assert "proof_prune(" not in source
    assert "empty_count" not in source
    assert "search_post_sd5" not in source
    assert "search_route_bridge" not in source


def test_synthetic_board_reveals_and_completes_the_suit():
    source = _foundation_board()
    spec = spec_from_source(source, "c")
    assert suit_foundation_count(source, "c") == 0
    assert face_down_count(source) >= 1
    found = search_milestone(
        source,
        g0=20,
        suit="c",
        paid_moves=3,
        max_depth=4,
        max_unique=80,
        time_limit_s=2.0,
        rss_abort_mb=512,
        stop_on_first=True,
    )
    assert found.met
    assert found.replay_ok
    assert found.paid <= 3
    assert found.suit_before == 0
    assert found.suit_after == 1
    assert found.face_down_after is not None
    assert found.face_down_after < found.face_down_before
    assert found.g == 20 + found.paid
    trial = source.clone()
    spent = 0
    for action in found.actions:
        spent += apply_action(trial, action)
    assert spent == found.paid
    assert pack_state(trial).hex() == found.pack
    assert milestone_met(trial, spec)
    assert sum(item[1] for item in found.lane_exp) == found.expanded


def test_zero_cost_relocation_is_kept_before_the_paid_join():
    source = _park_board()
    park = (0, 1, 1)
    assert step_cost(source, park) == 0
    assert park in tableau_actions(source)
    ordered = rank_milestone_actions(source, tableau_actions(source), "c", column=0)
    assert park in ordered
    assert len(ordered) == len(tableau_actions(source))
    parked = source.clone()
    apply_action(parked, park)
    hidden = face_down_count(source)

    def joined(state: SpiderState) -> bool:
        up = state.columns[0].face_up
        return (
            len(up) >= 2
            and up[-2].suit == "c"
            and up[-2].rank == 5
            and up[-1].suit == "c"
            and up[-1].rank == 4
            and face_down_count(state) < hidden
        )

    assert not joined(parked)
    found = search_milestone(
        source,
        g0=4,
        suit="c",
        paid_moves=2,
        max_depth=4,
        max_unique=400,
        time_limit_s=2.0,
        rss_abort_mb=512,
        column=0,
        terminal_fn=joined,
        stop_on_first=True,
    )
    assert found.met
    assert found.actions
    assert found.actions[0] == park
    assert step_cost(source, found.actions[0]) == 0
    assert found.zero_cost >= 1
    assert any(step_cost(source, found.actions[0]) == 0 for _ in (0,))
    trial = source.clone()
    saw_paid_after_free = False
    free_seen = False
    for action in found.actions:
        cost = step_cost(trial, action)
        if cost == 0:
            free_seen = True
        elif free_seen:
            saw_paid_after_free = True
        apply_action(trial, action)
    assert free_seen and saw_paid_after_free
    assert joined(trial)
    assert found.column_specific
    assert milestone_identity(source, column=0) == pack_state(source)


def test_a_foundation_without_a_reveal_is_not_terminal():
    columns = {0: _ranks(13, 1, "c"), 2: "qh"}
    source = _state(columns, downs={2: "kh"})
    spec = spec_from_source(source, "c")
    done = source.clone()
    assert step_cost(done, (0, 1, 13)) == 0
    apply_action(done, (0, 1, 13))
    assert suit_foundation_count(done, "c") == 1
    assert face_down_count(done) == face_down_count(source)
    assert not milestone_met(done, spec)
    found = search_milestone(
        source,
        g0=5,
        suit="c",
        paid_moves=0,
        max_depth=3,
        max_unique=40,
        time_limit_s=2.0,
        rss_abort_mb=512,
    )
    assert not found.met
    assert not control_succeeded(found)
    assert found.diagnostics["foundation_without_reveal"] >= 1


def test_symmetry_identity_and_column_specific_fallback():
    left = _state({0: "5c", 1: "4c"}, downs={2: "ac"})
    right = permute_tableau_columns(left, (1, 0, 2, 3, 4, 5, 6, 7, 8, 9))
    assert left.stock == []
    assert pack_state(left) != pack_state(right)
    assert pack_whole_game_identity(left) == pack_whole_game_identity(right)
    assert milestone_identity(left) == milestone_identity(right)
    assert milestone_identity(left, column=2) == pack_state(left)
    assert milestone_identity(left, column=2) != milestone_identity(right, column=2)
    spec = spec_from_source(left, "c", column=2, max_face_down=0)
    assert spec.column_specific
    assert evaluate_column(left, spec) is False
    exposed = left.clone()
    exposed.columns[2].face_up.append(exposed.columns[2].face_down.pop())
    assert face_down_count(exposed) < face_down_count(left)
    # The column fell, but no club foundation was added.
    assert not milestone_met(exposed, spec)


def evaluate_column(state, spec) -> bool:
    return milestone_met(state, spec)


def test_proof_ceiling_keeps_equality_and_legacy_callers():
    state = _state({0: "kh qh"})
    root_pack = pack_state(state)
    paid = (0, 1, 1)
    assert step_cost(state, paid) == 1

    def actions(current: SpiderState):
        if pack_state(current) == root_pack:
            return [paid]
        return []

    def bound(current: SpiderState, g: int) -> int:
        if pack_state(current) == root_pack:
            return 0
        return 4

    kept = run_search(
        [_root(state, 0)],
        limits=SearchLimits(
            max_unique=10,
            time_limit_s=2.0,
            rss_abort_mb=4096,
            cost_ceiling=8,
            proof_ceiling=5,
        ),
        identity_fn=pack_state,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        is_terminal=lambda _state: False,
        actions_fn=actions,
        lower_bound_fn=bound,
    )
    assert kept.unique == 2
    assert kept.lower_bound_prunes == 0
    assert any(node.g == 1 for node in kept.nodes)

    pruned = run_search(
        [_root(state, 0)],
        limits=SearchLimits(
            max_unique=10,
            time_limit_s=2.0,
            rss_abort_mb=4096,
            cost_ceiling=8,
            proof_ceiling=4,
        ),
        identity_fn=pack_state,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        is_terminal=lambda _state: False,
        actions_fn=actions,
        lower_bound_fn=bound,
    )
    assert pruned.unique == 1
    assert pruned.lower_bound_prunes == 1
    assert pruned.proof_prune_identities == 1
    assert all(node.g == 0 for node in pruned.nodes)

    legacy = run_search(
        [_root(state, 0)],
        limits=SearchLimits(max_unique=10, time_limit_s=2.0, rss_abort_mb=4096, cost_ceiling=1),
        identity_fn=pack_state,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        is_terminal=lambda _state: False,
        actions_fn=actions,
        lower_bound_fn=bound,
    )
    assert legacy.unique == 1
    assert legacy.lower_bound_prunes == 1

    dead_root = run_search(
        [_root(state, 0)],
        limits=SearchLimits(
            max_unique=10,
            time_limit_s=2.0,
            rss_abort_mb=4096,
            cost_ceiling=10,
            proof_ceiling=4,
        ),
        identity_fn=pack_state,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        is_terminal=lambda _state: False,
        actions_fn=actions,
        lower_bound_fn=lambda current, _g: 5 if pack_state(current) == root_pack else 0,
    )
    assert dead_root.expanded == 0
    assert dead_root.lower_bound_prunes == 1


def _endpoint(state, g, h, root, macro, tactical, gain=1, drop=1):
    return MilestoneEndpoint(
        root_index=root,
        g=g,
        h=h,
        actions=tuple(tactical),
        pre_deal_macro=tuple(macro),
        state=state,
        pack=pack_state(state).hex(),
        symmetry=pack_whole_game_identity(state).hex(),
        suit_gain=gain,
        face_down_drop=drop,
        zero_cost=0,
        paid=1,
    )


def test_dominance_keeps_the_cheaper_physical_prefix_and_its_root():
    left = _state({0: "5c", 1: "4d"})
    right = permute_tableau_columns(left, (1, 0, 2, 3, 4, 5, 6, 7, 8, 9))
    cheap = _endpoint(left, 150, 20, 1, ((1, 2, 1),), ((2, 3, 1),))
    costly = _endpoint(right, 154, 16, 4, ((3, 4, 1),), ((4, 5, 1),))
    over = _endpoint(left.clone(), 160, 12, 2, ((0, 1, 1),), ((1, 0, 1),))
    assert cheap.f == 170
    assert over.f == 172
    assert cheap.symmetry == costly.symmetry
    kept, dominated = retain_endpoints([costly, over, cheap])
    assert len(kept) == 1
    assert kept[0].g == 150
    assert kept[0].root_index == 1
    assert kept[0].pre_deal_macro == ((1, 2, 1),)
    assert kept[0].actions == ((2, 3, 1),)
    assert kept[0].pack == pack_state(left).hex()
    assert any(row["dropped_root"] == 4 and row["kept_root"] == 1 for row in dominated)
    assert all(row["dropped_root"] != 1 or row["kept_g"] < 150 for row in dominated)


def test_tactical_paid_and_depth_caps_block_the_second_move():
    source = _foundation_board()
    paid = search_milestone(
        source,
        g0=10,
        suit="c",
        paid_moves=1,
        max_depth=6,
        max_unique=80,
        time_limit_s=2.0,
        rss_abort_mb=512,
    )
    assert not paid.met
    assert paid.cost_ceiling == 11
    assert paid.ceiling_prunes >= 1
    deep = search_milestone(
        source,
        g0=10,
        suit="c",
        paid_moves=4,
        max_depth=1,
        max_unique=80,
        time_limit_s=2.0,
        rss_abort_mb=512,
    )
    assert not deep.met
    assert deep.depth_skips >= 1


def test_origin_prefix_uses_that_roots_tactical_macro():
    state = _state({0: "5c"})
    first = _endpoint(state, 140, 10, 0, ((1, 2, 1),), ((2, 3, 1),))
    second = _endpoint(state.clone(), 141, 10, 1, ((3, 4, 1),), ((4, 5, 1),))
    canonical = [(0, 1, 1)] * CHECKPOINT_PREP + [(9, 8, 1)]
    route = route_for_endpoint(
        canonical,
        second,
        continuation=((5, 6, 1),),
        suffix=((6, 7, 1),),
    )
    assert route[:CHECKPOINT_PREP] == canonical[:CHECKPOINT_PREP]
    assert route[CHECKPOINT_PREP] == (3, 4, 1)
    assert route[CHECKPOINT_PREP + 1] == ("deal",)
    assert route[CHECKPOINT_PREP + 2] == (4, 5, 1)
    assert route[CHECKPOINT_PREP + 3] == (5, 6, 1)
    assert route[CHECKPOINT_PREP + 4] == (6, 7, 1)
    assert (1, 2, 1) not in route
    assert (2, 3, 1) not in route
    assert first.pre_deal_macro != second.pre_deal_macro


def test_a_milestone_path_is_not_a_complete_game():
    source = _foundation_board()
    found = search_milestone(
        source,
        g0=0,
        suit="c",
        paid_moves=3,
        max_depth=4,
        max_unique=80,
        time_limit_s=2.0,
        rss_abort_mb=512,
    )
    assert found.met
    assert accept_improved_route(source, found.actions, ceiling=171) is None
    assert len(source.foundations) == 0


def test_driver_gates_later_work_and_does_not_raise_caps():
    text = DRIVER.read_text(encoding="utf-8")
    assert text.index("if not control_succeeded") < text.index("discover_macros(")
    assert text.index("discover_macros(") < text.index("search_origin_fair(")
    assert "if not kept" in text
    assert "search_bridge_roots" not in text
    assert "search_post_sd5" not in text
    assert "search_route_bridge" not in text
    assert "80_000" not in text
    assert "80000" not in text
    assert "time_limit_s=90" not in text
    kernel = inspect.getsource(run_search)
    assert "proof_ceiling" in inspect.getsource(SearchLimits)
    assert "tableau_actions" in kernel
    assert "4925153" not in kernel
    assert "Clubs" not in kernel
