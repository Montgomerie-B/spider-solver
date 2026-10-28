"""v0.138 heart-run follow-through.

The canonical window and the recorded shortcut are oracles. The 4-second
control and the eight tactic searches stay in the driver.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.heart_run_followthrough import (
    CANONICAL_ASSEMBLY_G,
    CONTROL_PAID,
    CONTROL_PROOF,
    CONTROL_TIME_S,
    CONTROL_UNIQUE,
    HEART_RUN,
    REPAIR_PAID,
    REPAIR_UNIQUE,
    TACTIC_PAID,
    TACTIC_PROOF,
    TACTIC_UNIQUE,
    anywhere_same_suit_run_at_least,
    choose_heart_obligation,
    heart_goal,
    heart_route_actions,
    screen_heart_endpoint,
    select_heart_endpoints,
    top_same_suit_run_at_least,
)
from spider.human_strategy.anchored import build_checkpoints
from spider.metrics import parse_moves_file
from spider.packed_state import pack_state, pack_whole_game_identity, permute_tableau_columns
from spider.post_deal_milestone import MilestoneEndpoint, milestone_identity, search_milestone
from spider.purposeful_macro import CHECKPOINT_PREP
from spider.research_actions import apply_action, step_cost, tableau_actions

DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
DRIVER = ROOT / "tools" / "heart_run_followthrough_v0_138.py"
ADAPTER = ROOT / "src" / "spider" / "heart_run_followthrough.py"
RECORDED_SHORTCUT = ((4, 1, 1), (4, 8, 1), (3, 4, 1), (3, 0, 2), (3, 8, 1))


def _cards(text: str):
    return [Card.parse(token) for token in text.split() if token]


def _state(columns, stock: str = "", downs=None) -> SpiderState:
    downs = downs or {}
    cols = [
        Column(_cards(downs.get(index, "")), _cards(columns.get(index, "")))
        for index in range(10)
    ]
    return SpiderState(cols, _cards(stock), [])


def _hearts(high: int, low: int) -> str:
    names = {1: "ah", 10: "10h", 11: "jh", 12: "qh", 13: "kh"}
    return " ".join(names.get(rank, str(rank) + "h") for rank in range(high, low - 1, -1))


def _endpoint(state, g, h, root=0, macro=((1, 2, 1),), tactical=((2, 3, 1),), pack="p", symmetry="s"):
    return MilestoneEndpoint(
        root_index=root,
        g=g,
        h=h,
        actions=tuple(tactical),
        pre_deal_macro=tuple(macro),
        state=state,
        pack=pack,
        symmetry=symmetry,
        suit_gain=0,
        face_down_drop=0,
        zero_cost=0,
        paid=1,
    )


def test_a_heart_run_must_be_one_descending_top_stack():
    built = _state({0: _hearts(7, 1)})
    assert heart_goal(built)
    assert top_same_suit_run_at_least(built, "h", 7)
    buried = _state({0: _hearts(7, 1) + " ks"})
    assert anywhere_same_suit_run_at_least(buried, "h", 7)
    assert not heart_goal(buried)
    mixed = _state({0: "7h 6h 5h 4s 3h 2h ah"})
    assert not anywhere_same_suit_run_at_least(mixed, "h", 7)
    split = _state({0: _hearts(7, 4), 1: _hearts(3, 1)})
    assert not heart_goal(split)
    assert not anywhere_same_suit_run_at_least(split, "h", 7)
    other_suit = _state({0: "7s 6s 5s 4s 3s 2s as"})
    assert not heart_goal(other_suit)
    short = _state({0: _hearts(7, 2)})
    assert not heart_goal(short)
    rising = _state({0: "ah 2h 3h 4h 5h 6h 7h"})
    assert not anywhere_same_suit_run_at_least(rising, "h", 7)
    covered = _state({0: "ks " + _hearts(7, 1)})
    assert heart_goal(covered)


def test_checkpoint_160_needs_a_top_run_not_the_buried_one():
    opening = SpiderState.from_cards(list(load_deal(DEAL)))
    actions = parse_moves_file(CANONICAL)
    checkpoints = build_checkpoints(opening, actions)
    before = checkpoints[160].state
    after = before.clone()
    for action in actions[160:163]:
        apply_action(after, action)
    choice = choose_heart_obligation(before, after)
    assert checkpoints[160].g == 158
    assert checkpoints[163].g == CANONICAL_ASSEMBLY_G
    assert choice["buried_before"] is True
    assert choice["top_before"] is False
    assert choice["top_after"] is True
    assert choice["mode"] == "top_same_suit_run_at_least"
    assert choice["goal"] is heart_goal
    assert not heart_goal(before)
    assert heart_goal(after)
    assert choice["top_length_before"] < HEART_RUN
    assert choice["top_length_after"] >= HEART_RUN
    source = ADAPTER.read_text(encoding="utf-8")
    for action in list(actions[160:163]) + list(RECORDED_SHORTCUT):
        assert repr(action) not in source


def test_search_finds_a_top_run_without_a_seed_and_a_partial_is_open():
    source = _state({0: _hearts(7, 2), 1: "ah"})
    assert not heart_goal(source)
    found = search_milestone(
        source,
        g0=4,
        suit="h",
        paid_moves=1,
        max_depth=2,
        max_unique=30,
        time_limit_s=2.0,
        terminal_fn=heart_goal,
        stop_on_first=True,
        proof_ceiling=20,
    )
    assert found.met and found.replay_ok
    assert found.actions
    trial = source.clone()
    for action in found.actions:
        apply_action(trial, action)
    assert heart_goal(trial)
    assert len(trial.foundations) < 8
    assert not trial.is_solved()


def test_zero_cost_setup_remains_legal_before_the_heart_join():
    # One stock card keeps ordered physical identity. An empty stock would
    # treat the free park as a column permutation of the parent and skip it
    # before the column-specific goal is checked. The other columns stay
    # occupied so column 1 is the only empty landing.
    columns = {0: "kh", 2: _hearts(7, 2), 3: "ah"}
    for index in range(4, 10):
        columns[index] = "kd"
    source = _state(columns, stock="ad")
    park = (0, 1, 1)
    assert park in tableau_actions(source)
    assert step_cost(source, park) == 0
    assert source.stock
    hidden_goal = heart_goal

    def parked_run(state: SpiderState) -> bool:
        return state.columns[1].face_up[-1:] == _cards("kh") and hidden_goal(state)

    found = search_milestone(
        source,
        g0=3,
        suit="h",
        paid_moves=1,
        max_depth=4,
        max_unique=400,
        time_limit_s=2.0,
        terminal_fn=parked_run,
        stop_on_first=True,
    )
    assert found.met
    trial = source.clone()
    costs = []
    for action in found.actions:
        costs.append(step_cost(trial, action))
        apply_action(trial, action)
    assert 0 in costs
    assert 1 in costs
    assert parked_run(trial)


def test_stock_keeps_physical_identity_and_empty_stock_uses_symmetry():
    left = _state({0: _hearts(7, 1), 1: "ks"}, stock="ad")
    right = permute_tableau_columns(left, (1, 0, 2, 3, 4, 5, 6, 7, 8, 9))
    assert left.stock
    assert pack_state(left) != pack_state(right)
    assert milestone_identity(left) == pack_state(left)
    assert milestone_identity(left) != milestone_identity(right)
    assert heart_goal(left) and heart_goal(right)
    bare_left = _state({0: _hearts(7, 1), 1: "ks"})
    bare_right = permute_tableau_columns(bare_left, (1, 0, 2, 3, 4, 5, 6, 7, 8, 9))
    assert not bare_left.stock
    assert pack_whole_game_identity(bare_left) == pack_whole_game_identity(bare_right)
    assert milestone_identity(bare_left) == milestone_identity(bare_right)
    assert pack_state(bare_left) != pack_state(bare_right)


def test_proof_equality_stays_eligible_and_depth_is_separate():
    source = _state({0: _hearts(7, 2), 1: "ah"})
    root_pack = pack_state(source)

    def bound(state: SpiderState, _g: int) -> int:
        if pack_state(state) == root_pack:
            return 1
        return 0

    kept = search_milestone(
        source,
        g0=0,
        suit="h",
        paid_moves=1,
        max_depth=2,
        max_unique=20,
        time_limit_s=2.0,
        terminal_fn=heart_goal,
        stop_on_first=True,
        proof_ceiling=1,
        lower_bound_fn=bound,
    )
    assert kept.met
    assert kept.g == 1
    pruned = search_milestone(
        source,
        g0=0,
        suit="h",
        paid_moves=1,
        max_depth=2,
        max_unique=20,
        time_limit_s=2.0,
        terminal_fn=heart_goal,
        stop_on_first=True,
        proof_ceiling=0,
        lower_bound_fn=bound,
    )
    assert not pruned.met
    assert pruned.expanded == 0
    shallow = search_milestone(
        source,
        g0=0,
        suit="h",
        paid_moves=3,
        max_depth=0,
        max_unique=20,
        time_limit_s=2.0,
        terminal_fn=heart_goal,
        stop_on_first=True,
        proof_ceiling=10,
        lower_bound_fn=bound,
    )
    assert not shallow.met
    assert shallow.depth_skips >= 1


def test_lower_f_diversity_keeps_the_cheaper_prefix_macro():
    state = _state({0: _hearts(7, 1)})
    low_f = _endpoint(state, 154, 16, root=1, macro=((3, 4, 1),), tactical=((4, 5, 1),), pack="pack-f", symmetry="sym-f")
    low_g = _endpoint(
        state,
        150,
        21,
        root=2,
        macro=((1, 2, 1),),
        tactical=((0, 1, 1),),
        pack="pack-g",
        symmetry="sym-g",
    )
    twin = _endpoint(
        state,
        158,
        13,
        root=3,
        macro=((8, 9, 1),),
        tactical=((5, 6, 1),),
        pack="pack-twin",
        symmetry="sym-g",
    )
    assert low_f.f == 170
    assert low_g.f == 171
    chosen, dominated, info = select_heart_endpoints([twin, low_f, low_g], ceiling=171, limit=1, goal=heart_goal)
    assert chosen[0].f == 170
    assert chosen[0].pre_deal_macro == ((3, 4, 1),)
    assert info["truncated"] >= 1
    assert "proof" not in info["reason"]
    both, _dominated, _info = select_heart_endpoints([low_g, twin], ceiling=171, limit=2, goal=heart_goal)
    assert len(both) == 1
    assert both[0].g == 150
    assert both[0].pre_deal_macro == ((1, 2, 1),)
    assert dominated == [] or dominated[0]["kept_macro"] != dominated[0]["dropped_macro"]
    canonical = [(0, 1, 1)] * 145
    route = heart_route_actions(canonical, low_g, ((6, 7, 1),), ((7, 8, 1),))
    assert route[:CHECKPOINT_PREP] == canonical[:CHECKPOINT_PREP]
    assert tuple(route[CHECKPOINT_PREP:CHECKPOINT_PREP + 1]) == low_g.pre_deal_macro
    assert route[CHECKPOINT_PREP + 1] == ("deal",)
    assert tuple(route[CHECKPOINT_PREP + 2:CHECKPOINT_PREP + 3]) == low_g.actions
    assert route[CHECKPOINT_PREP + 3:] == [(6, 7, 1), (7, 8, 1)]


def test_screen_rejects_the_exhausted_identity_without_calling_it_a_proof():
    state = _state({0: "kh qh"})
    blocked = _endpoint(state, 5, 0, pack=pack_state(state).hex(), symmetry="sym-live")
    rejected = screen_heart_endpoint(blocked, ceiling=6, goal=lambda _state: True)
    assert rejected["accepted"] is False
    assert rejected["proof"] is False
    assert "no proof-eligible successor" in rejected["reasons"]
    above = _endpoint(state, 154, 17, pack="pack-171", symmetry="sym-171")
    above_screen = screen_heart_endpoint(above, ceiling=TACTIC_PROOF, goal=lambda _state: True)
    assert above_screen["screen_f"] == 170
    assert above_screen["accepted"] is False
    assert "f above screen" in above_screen["reasons"]
    exhausted = _endpoint(state, 150, 10, pack="exhausted-pack", symmetry="exhausted-sym")
    skipped = screen_heart_endpoint(
        exhausted,
        ceiling=171,
        excluded_packs=("exhausted-pack",),
        excluded_symmetries=(),
        goal=lambda _state: True,
    )
    assert skipped["accepted"] is False
    assert "previously exhausted identity" in skipped["reasons"]
    assert skipped["proof"] is False


def test_driver_keeps_the_shortcut_out_of_search_and_does_not_raise_caps():
    text = DRIVER.read_text(encoding="utf-8")
    assert text.rindex("RECORDED_SHORTCUT") < text.index("search_milestone(")
    assert text.index("if not control_succeeded") < text.index("discover_macros(")
    assert text.index("discover_macros(") < text.index("if not opened")
    assert text.index("if not opened") < text.index("search_origin_fair(")
    assert 'hit_policy="lower_f"' in text
    assert "phase_aware=True" not in text
    assert CONTROL_PAID == 3 and CONTROL_UNIQUE == 2_000 and CONTROL_TIME_S == 4.0
    assert CONTROL_PROOF == 172
    assert REPAIR_PAID == 6 and REPAIR_UNIQUE == 6_000
    assert TACTIC_PAID == 12 and TACTIC_UNIQUE == 6_000 and TACTIC_PROOF == 171
    for banned in (
        "search_bridge_roots",
        "search_post_sd5",
        "search_route_bridge",
        "80_000",
        "80000",
        "time_limit_s=90",
    ):
        assert banned not in text
        assert banned not in ADAPTER.read_text(encoding="utf-8")
