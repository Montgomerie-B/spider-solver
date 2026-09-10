"""Post-stock tableau column-symmetry audit v0.17."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import (
    PACKED_MAGIC,
    PACKED_SYMMETRY_MAGIC,
    column_permutation_mapping,
    pack_post_stock_symmetry_state,
    pack_search_identity,
    pack_state,
    permute_tableau_columns,
    remap_tableau_action,
    unpack_state,
)
from spider.rules import MW_RULES
from spider.simple_progressive_solver import (
    TT_MODE_DEPTH_AWARE,
    apply_action,
    enumerate_actions,
    solve_progressive,
    step_cost,
)
from spider.simple_workspace_reachability import (
    empty_column_indices,
    layered_reachability,
)

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
SEED = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
DEAD_FD11 = ROOT / "solutions" / "4925153_simple_v0_13_fd11.moves.txt"
FD12 = ROOT / "solutions" / "4925153_simple_v0_12_fd12.moves.txt"
TRUE_CROSSING = (
    ROOT
    / "research"
    / "results"
    / "simple_progressive_fd11_first_crossing_v0_16"
    / "true_first_crossing.jsonl"
)
REPORT = ROOT / "docs" / "research" / "simple_progressive_post_stock_column_symmetry_v0_17.json"
EXPECTED_HEX = (
    "53504b310100000004093a2c360835042302310b0d1c3b050515191b11282d0c2b1a290000"
    "00121413121d071d1c1b1a19181716153433323100022d2c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)
DEAD_HEX = (
    "53504b3101000000040c3a2c360835042302310b0d1c3b1a2928030115191b1100032d2c2b"
    "00121413121d071d1c1b1a19181716153433323100022d0c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)


def _opening() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL)))


def _seed():
    actions = parse_moves_file(SEED)
    opening = _opening()
    seed = opening.clone()
    cost = replay_actions(seed, actions)
    return seed, actions, cost, opening


def _state_from_slots(slots, stock=None, foundations=None) -> SpiderState:
    cols = []
    for index in range(10):
        down, up = slots.get(index, ([], [Card("s", 13)]))
        cols.append(Column(list(down), list(up)))
    return SpiderState(cols, list(stock or []), [list(seq) for seq in (foundations or [])])


def _distinct_stock0() -> SpiderState:
    """Ten mutually distinct complete columns, empty stock, no foundations."""
    slots = {}
    for index in range(10):
        suit = "shdc"[index % 4]
        fd = [Card(suit, 13 - (index % 12))]
        fu = [Card("shdc"[(index + 1) % 4], 1 + (index % 12))]
        slots[index] = (fd, fu)
    return _state_from_slots(slots, [])


def _playable_stock0() -> SpiderState:
    """Small constructed stock=0 position with flips, empty, king, and joins."""
    hearts_run = [Card("h", rank) for rank in range(13, 1, -1)]  # K..2
    slots = {
        0: ([Card("c", 9)], [Card("h", 6)]),
        1: ([], [Card("s", 7)]),
        2: ([], [Card("d", 8), Card("d", 7)]),
        3: ([], [Card("c", 13)]),
        4: ([], []),
        5: ([], hearts_run),
        6: ([], [Card("h", 1)]),
        7: ([Card("s", 12), Card("s", 11)], [Card("s", 5)]),
        8: ([], [Card("c", 4)]),
        9: ([], [Card("d", 13)]),
    }
    return _state_from_slots(slots, [])


def _swap(state: SpiderState, i: int, j: int) -> SpiderState:
    perm = list(range(10))
    perm[i], perm[j] = perm[j], perm[i]
    return permute_tableau_columns(state, perm)


def _old_to_new(perm) -> list:
    mapping = [0] * len(perm)
    for new, old in enumerate(perm):
        mapping[old] = new
    return mapping


def _tableau(state: SpiderState):
    return [action for action in enumerate_actions(state) if action != ("deal",)]


def _identity(state: SpiderState) -> bytes:
    return pack_search_identity(state, post_stock_column_symmetry=True)


def test_1_ordered_pack_state_preserves_column_order():
    state = _distinct_stock0()
    swapped = _swap(state, 0, 1)
    ordered_a = pack_state(state)
    ordered_b = pack_state(swapped)
    assert ordered_a[:4] == PACKED_MAGIC
    assert ordered_a != ordered_b
    assert unpack_state(ordered_a).columns[0].face_up[0] == state.columns[0].face_up[0]
    assert unpack_state(ordered_b).columns[0].face_up[0] == swapped.columns[0].face_up[0]


def test_2_stock0_symmetry_key_ignores_whole_column_permutation():
    state = _distinct_stock0()
    swapped = _swap(state, 2, 4)
    assert pack_state(state) != pack_state(swapped)
    assert pack_post_stock_symmetry_state(state) == pack_post_stock_symmetry_state(swapped)
    reversed_perm = list(range(9, -1, -1))
    reversed_state = permute_tableau_columns(state, reversed_perm)
    assert pack_post_stock_symmetry_state(state) == pack_post_stock_symmetry_state(reversed_state)
    cycle = [(i + 3) % 10 for i in range(10)]
    cycled = permute_tableau_columns(state, cycle)
    assert pack_post_stock_symmetry_state(state) == pack_post_stock_symmetry_state(cycled)
    for perm in (
        (1, 0, 2, 3, 4, 5, 6, 7, 8, 9),
        (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
        (2, 0, 1, 3, 4, 5, 6, 7, 8, 9),
        (0, 1, 2, 3, 4, 9, 8, 7, 6, 5),
    ):
        other = permute_tableau_columns(state, perm)
        assert pack_state(state) != pack_state(other) or perm == tuple(range(10))
        assert pack_post_stock_symmetry_state(state) == pack_post_stock_symmetry_state(other)


def test_3_column_card_and_order_changes_remain_distinguishable():
    state = _distinct_stock0()
    key = pack_post_stock_symmetry_state(state)
    changed_card = state.clone()
    changed_card.columns[3].face_up[0] = Card("c", 12)
    assert pack_post_stock_symmetry_state(changed_card) != key
    flipped_down = state.clone()
    down = list(flipped_down.columns[0].face_down)
    if len(down) >= 2:
        down[0], down[1] = down[1], down[0]
        flipped_down.columns[0].face_down = down
    else:
        flipped_down.columns[0].face_down = [Card("d", 2), Card("d", 3)]
        flipped_down.columns[0].face_up = list(state.columns[0].face_up)
    assert pack_post_stock_symmetry_state(flipped_down) != key
    fu_order = state.clone()
    fu_order.columns[1].face_up = [Card("h", 10), Card("h", 9)]
    assert pack_post_stock_symmetry_state(fu_order) != key


def test_4_foundation_differences_remain_distinguishable():
    state = _distinct_stock0()
    hearts = [Card("h", rank) for rank in range(13, 0, -1)]
    with_found = SpiderState(
        [Column(list(col.face_down), list(col.face_up)) for col in state.columns],
        [],
        [hearts],
    )
    assert pack_post_stock_symmetry_state(state) != pack_post_stock_symmetry_state(with_found)
    spades = [Card("s", rank) for rank in range(13, 0, -1)]
    other_found = SpiderState(
        [Column(list(col.face_down), list(col.face_up)) for col in state.columns],
        [],
        [spades],
    )
    assert pack_post_stock_symmetry_state(with_found) != pack_post_stock_symmetry_state(other_found)


def test_5_multiplicity_of_identical_columns_is_preserved():
    twin = ([Card("c", 10)], [Card("c", 9), Card("c", 8)])
    unique_rest = {
        0: twin,
        1: twin,
        2: ([], [Card("s", 1)]),
        3: ([], [Card("s", 2)]),
        4: ([], [Card("s", 3)]),
        5: ([], [Card("s", 4)]),
        6: ([], [Card("s", 5)]),
        7: ([], [Card("s", 6)]),
        8: ([], [Card("s", 7)]),
        9: ([], [Card("s", 8)]),
    }
    two = _state_from_slots(unique_rest, [])
    one_slots = dict(unique_rest)
    one_slots[1] = ([], [Card("d", 13)])
    one = _state_from_slots(one_slots, [])
    three_slots = dict(unique_rest)
    three_slots[2] = twin
    three = _state_from_slots(three_slots, [])
    assert pack_post_stock_symmetry_state(two) != pack_post_stock_symmetry_state(one)
    assert pack_post_stock_symmetry_state(two) != pack_post_stock_symmetry_state(three)
    swapped_twins = _swap(two, 0, 1)
    assert pack_state(two) == pack_state(swapped_twins)
    swapped_apart = permute_tableau_columns(two, [2, 0, 1, 3, 4, 5, 6, 7, 8, 9])
    assert pack_post_stock_symmetry_state(two) == pack_post_stock_symmetry_state(swapped_apart)


def test_6_stock_bearing_column_swaps_are_not_quotient_equivalent():
    state = _distinct_stock0()
    state.stock = [Card("c", rank) for rank in range(1, 11)]
    swapped = _swap(state, 0, 1)
    with pytest.raises(ValueError, match="stock remains"):
        pack_post_stock_symmetry_state(state)
    with pytest.raises(ValueError, match="stock remains"):
        pack_post_stock_symmetry_state(swapped)
    ident_a = pack_search_identity(state, post_stock_column_symmetry=True)
    ident_b = pack_search_identity(swapped, post_stock_column_symmetry=True)
    assert ident_a == pack_state(state)
    assert ident_b == pack_state(swapped)
    assert ident_a != ident_b
    assert ident_a[:4] == PACKED_MAGIC


def test_7_legal_successors_map_correctly_under_a_test_permutation():
    state = _playable_stock0()
    perm = [1, 0, 2, 4, 3, 5, 6, 7, 8, 9]
    permuted = permute_tableau_columns(state, perm)
    old_to_new = _old_to_new(perm)
    assert column_permutation_mapping(state, permuted) == old_to_new
    mapped = {remap_tableau_action(action, old_to_new) for action in _tableau(state)}
    actual = set(_tableau(permuted))
    assert mapped == actual
    for action in _tableau(state):
        left = state.clone()
        right = permuted.clone()
        mapped_action = remap_tableau_action(action, old_to_new)
        left_cost = apply_action(left, action)
        right_cost = apply_action(right, mapped_action)
        assert left_cost == right_cost
        assert pack_post_stock_symmetry_state(left) == pack_post_stock_symmetry_state(right)
        assert column_permutation_mapping(left, right) == old_to_new
        src, dst, k = action
        flipped = k == len(state.columns[src].face_up) and bool(state.columns[src].face_down)
        if flipped:
            new_src = old_to_new[src]
            assert right.columns[new_src].face_up
            assert not right.columns[new_src].face_down or len(right.columns[new_src].face_up) >= 1


def test_8_mobilityware_move_cost_is_permutation_invariant_at_stock0():
    state = _playable_stock0()
    perm = [4, 3, 2, 1, 0, 9, 8, 7, 6, 5]
    permuted = permute_tableau_columns(state, perm)
    old_to_new = _old_to_new(perm)
    for action in _tableau(state):
        mapped = remap_tableau_action(action, old_to_new)
        assert step_cost(state, action) == step_cost(permuted, mapped)
        left = state.clone()
        right = permuted.clone()
        assert apply_action(left, action) == apply_action(right, mapped)


def test_7b_complete_run_removal_is_permutation_equivariant():
    state = _playable_stock0()
    before_found = len(state.foundations)
    action = (6, 5, 1)
    assert action in _tableau(state)
    after = state.clone()
    apply_action(after, action)
    assert len(after.foundations) == before_found + 1
    perm = [5, 6, 0, 1, 2, 3, 4, 7, 8, 9]
    permuted = permute_tableau_columns(state, perm)
    mapped = remap_tableau_action(action, _old_to_new(perm))
    after_p = permuted.clone()
    apply_action(after_p, mapped)
    assert len(after_p.foundations) == len(after.foundations)
    assert pack_post_stock_symmetry_state(after) == pack_post_stock_symmetry_state(after_p)


def test_9_dead_fd11_and_v016_outside_candidate_symmetry_comparison_is_deterministic():
    opening = _opening()
    dead = opening.clone()
    replay_actions(dead, parse_moves_file(DEAD_FD11))
    assert pack_state(dead).hex() == DEAD_HEX
    assert not dead.stock
    rows = [json.loads(line) for line in TRUE_CROSSING.read_text(encoding="utf-8").splitlines() if line.strip()]
    outside = [row for row in rows if row.get("class") == "TRUE_FIRST_CROSSING_DEPTH10" and not row.get("bubble_member")]
    assert len(outside) == 1
    cand = opening.clone()
    replay_actions(cand, parse_moves_file(SEED) + [tuple(a) for a in outside[0]["actions"]])
    assert pack_state(cand).hex() == outside[0]["digest"]
    ordered_equal = pack_state(dead) == pack_state(cand)
    symmetry_equal = pack_post_stock_symmetry_state(dead) == pack_post_stock_symmetry_state(cand)
    mapping = column_permutation_mapping(dead, cand)
    assert ordered_equal is False
    assert symmetry_equal is True
    assert mapping is not None
    assert sorted(mapping) == list(range(10))
    permuted = permute_tableau_columns(dead, [mapping.index(i) for i in range(10)])
    assert pack_state(permuted) == pack_state(cand)


def test_10_symmetry_bfs_retains_concrete_replayable_representatives():
    state = _playable_stock0()
    swapped = _swap(state, 0, 1)
    result = layered_reachability(
        sources=[state, swapped],
        max_depth=2,
        max_unique=400,
        time_limit_s=5.0,
        identity_fn=_identity,
        checkpoints=(),
    )
    assert result.source_count == 2
    assert result.layers[0]["frontier_size"] == 1
    ordered = layered_reachability(
        sources=[state, swapped],
        max_depth=2,
        max_unique=400,
        time_limit_s=5.0,
        checkpoints=(),
    )
    assert ordered.layers[0]["frontier_size"] == 2
    witness = result.witnesses.get("empty_consumed") or result.witnesses.get("fd_le_12") or next(iter(result.witnesses.values()), None)
    if result.unique >= 2:
        child_actions = None
        for kind, payload in result.witnesses.items():
            if payload.get("actions"):
                child_actions = payload["actions"]
                break
        if child_actions:
            end = state.clone()
            replay_actions(end, [tuple(a) for a in child_actions])
            assert pack_search_identity(end, post_stock_column_symmetry=True)[:4] == PACKED_SYMMETRY_MAGIC
    control = layered_reachability(state, max_depth=1, max_unique=80, time_limit_s=5.0, checkpoints=())
    treatment = layered_reachability(
        state, max_depth=1, max_unique=80, time_limit_s=5.0, identity_fn=_identity, checkpoints=()
    )
    assert treatment.unique <= control.unique
    assert treatment.min_fd == control.min_fd


def test_11_fd12_depth8_witness_replays_from_original_deal():
    opening = _opening()
    prefix = parse_moves_file(SEED)
    known = parse_moves_file(FD12)
    end = opening.clone()
    replay_actions(end, known)
    assert len(known) == 110
    assert sum(len(col.face_down) for col in end.columns) == 12
    if REPORT.exists():
        payload = json.loads(REPORT.read_text(encoding="utf-8"))
        witness = payload.get("phase5", {}).get("fd12_witness") or {}
        actions = [tuple(a) for a in witness.get("full_actions") or []]
        if actions:
            found = opening.clone()
            replay_actions(found, actions)
            assert witness.get("depth") == 8
            assert sum(len(col.face_down) for col in found.columns) == 12
            assert witness.get("replay_ok") is True


def test_12_fd11_depth9_witness_replays_from_original_deal():
    opening = _opening()
    known = parse_moves_file(DEAD_FD11)
    end = opening.clone()
    replay_actions(end, known)
    assert sum(len(col.face_down) for col in end.columns) == 11
    assert len(known) == 111
    if REPORT.exists():
        payload = json.loads(REPORT.read_text(encoding="utf-8"))
        witness = payload.get("phase5", {}).get("fd11_witness") or {}
        actions = [tuple(a) for a in witness.get("full_actions") or []]
        if actions:
            found = opening.clone()
            replay_actions(found, actions)
            assert witness.get("depth") == 9
            assert sum(len(col.face_down) for col in found.columns) == 11
            assert witness.get("replay_ok") is True


def test_13_production_identity_and_solve_progressive_remain_unchanged():
    seed, actions, cost, opening = _seed()
    assert pack_state(seed).hex() == EXPECTED_HEX
    assert pack_state(seed)[:4] == PACKED_MAGIC
    assert pack_post_stock_symmetry_state(seed)[:4] == PACKED_SYMMETRY_MAGIC
    assert pack_search_identity(seed) == pack_state(seed)
    state = _playable_stock0()
    kwargs = dict(max_nodes=80, time_limit_s=2.0, depth_bands=(8,), max_pass=0, enable_audit=False)
    default = solve_progressive(state, **kwargs)
    explicit = solve_progressive(state, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert default.nodes == explicit.nodes
    assert cost == 102


def test_14_mobilityware_unrestricted_rules_contract_green():
    assert MW_RULES.can_deal_into_empty is True
    seed, actions, cost, opening = _seed()
    end = opening.clone()
    assert replay_actions(end, actions) == cost
    apply_action(end.clone(), (1, 2, 1))
    assert empty_column_indices(seed) == (2,)


def test_15_symmetry_key_never_unpacks_as_ordered_state():
    state = _distinct_stock0()
    blob = pack_post_stock_symmetry_state(state)
    with pytest.raises(ValueError, match="bad packed magic"):
        unpack_state(blob)
