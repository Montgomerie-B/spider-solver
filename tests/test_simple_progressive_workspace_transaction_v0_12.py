"""Shallow workspace-transaction reachability v0.12."""

from __future__ import annotations

from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_state
from spider.rules import MW_RULES
from spider.simple_post_deal_audit import census_legal_by_tier
from spider.simple_progressive_solver import (
    TT_MODE_DEPTH_AWARE,
    Tier,
    apply_action,
    classify_tier,
    enumerate_actions,
    ordered_actions,
    solve_progressive,
)
from spider.simple_workspace_reachability import (
    empty_column_indices,
    empty_transition_events,
    first_empty_use_on_path,
    layered_reachability,
)

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
FIXTURE = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
EXPECTED_HEX = (
    "53504b310100000004093a2c360835042302310b0d1c3b050515191b11282d0c2b1a290000"
    "00121413121d071d1c1b1a19181716153433323100022d2c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)


def _opening() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL)))


def _seed():
    actions = parse_moves_file(FIXTURE)
    opening = _opening()
    seed = opening.clone()
    cost = replay_actions(seed, actions)
    return seed, actions, cost, opening


def _state_from_slots(slots: dict[int, tuple[list[Card], list[Card]]], stock=None) -> SpiderState:
    cols = []
    for index in range(10):
        down, up = slots.get(index, ([], [Card("s", 13)]))
        cols.append(Column(list(down), list(up)))
    return SpiderState(cols, list(stock or []))


def _uncover_state() -> SpiderState:
    return _state_from_slots(
        {
            0: ([Card("d", 9)], [Card("h", 6)]),
            1: ([], [Card("c", 7)]),
            2: ([Card("s", 8)], [Card("d", 5)]),
            3: ([], [Card("h", 6)]),
        },
        [Card("c", rank) for rank in range(1, 11)],
    )


def test_1_authoritative_fd13_empty1_seed_replays():
    seed, actions, cost, opening = _seed()
    assert len(actions) == 102
    assert cost == 102
    assert pack_state(seed).hex() == EXPECTED_HEX
    again = opening.clone()
    assert replay_actions(again, actions) == 102
    assert pack_state(again).hex() == EXPECTED_HEX
    assert sum(len(col.face_down) for col in seed.columns) == 13
    assert len(seed.stock) == 0
    assert len(seed.foundations) == 0
    assert sum(1 for col in seed.columns if col.is_empty()) == 1


def test_2_initial_empty_column_identity_recorded():
    seed, _a, _c, _o = _seed()
    empties = empty_column_indices(seed)
    assert len(empties) == 1
    result = layered_reachability(seed, max_depth=1, max_unique=200, time_limit_s=5.0)
    assert result.initial_empty == empties
    assert seed.columns[empties[0]].is_empty()


def test_3_layer_n_processed_before_n_plus_1():
    seed, _a, _c, _o = _seed()
    result = layered_reachability(seed, max_depth=3, max_unique=5000, time_limit_s=10.0)
    assert result.expansion_order == sorted(result.expansion_order)
    assert result.expansion_order == list(range(len(result.expansion_order)))
    depths = [item["depth"] for item in result.processing_log]
    assert depths == list(range(len(depths)))


def test_4_first_canonical_encounter_is_minimum_depth():
    state = _state_from_slots(
        {
            0: ([], [Card("s", 8)]),
            1: ([], [Card("h", 9)]),
            2: ([], [Card("s", 6)]),
            3: ([], [Card("h", 7)]),
        }
    )
    result = layered_reachability(state, max_depth=3, max_unique=200, time_limit_s=5.0)
    assert result.expansion_order[0] == 0
    assert result.duplicate_skips >= 1
    child = state.clone()
    apply_action(child, (0, 1, 1))
    apply_action(child, (2, 3, 1))
    other = state.clone()
    apply_action(other, (2, 3, 1))
    apply_action(other, (0, 1, 1))
    assert pack_state(child) == pack_state(other)
    assert result.unique < result.generated


def test_5_later_same_or_deeper_duplicates_are_skipped():
    state = _state_from_slots(
        {
            0: ([], [Card("s", 8)]),
            1: ([], [Card("h", 9)]),
            2: ([], [Card("s", 6)]),
            3: ([], [Card("h", 7)]),
        }
    )
    result = layered_reachability(state, max_depth=3, max_unique=200, time_limit_s=5.0)
    assert result.duplicate_skips >= 1
    assert result.path_cycle_skips == 0
    depths = [item["depth"] for item in result.processing_log]
    assert depths == sorted(depths)


def test_6_abc_are_permitted():
    seed, _a, _c, _o = _seed()
    census = census_legal_by_tier(seed)
    result = layered_reachability(seed, max_depth=1, max_unique=200, time_limit_s=5.0)
    layer0 = result.layers[0]
    assert census["c"] > 0
    assert layer0["c_children"] > 0
    assert layer0["a_children"] + layer0["b_children"] > 0
    allowed = ordered_actions(seed, 2, prep_ply=0, stats=None)
    assert all(int(classify_tier(seed, action)) <= int(Tier.C) for action in allowed)


def test_7_d_remains_excluded():
    seed, _a, _c, _o = _seed()
    result = layered_reachability(seed, max_depth=2, max_unique=2000, time_limit_s=10.0)
    for layer in result.layers:
        assert layer.get("a_children", 0) + layer.get("b_children", 0) + layer.get("c_children", 0) == layer.get(
            "generated_successors", 0
        ) or layer["depth"] == result.completed_generated_depth
        assert "d_children" not in layer or layer["d_children"] == 0
    for action in enumerate_actions(seed):
        assert int(classify_tier(seed, action)) != int(Tier.D)


def test_8_empty_consumed_detected():
    state = _state_from_slots(
        {
            0: ([], [Card("h", 8), Card("s", 7)]),
            1: ([], []),
        }
    )
    before = empty_column_indices(state)
    action = (0, 1, 1)
    dest_was_empty = state.columns[1].is_empty()
    source_becomes = False
    child = state.clone()
    apply_action(child, action)
    events = empty_transition_events(
        before,
        empty_column_indices(child),
        dest_was_empty=dest_was_empty,
        source_became_empty=source_becomes,
    )
    assert "EMPTY_CONSUMED" in events
    result = layered_reachability(state, max_depth=1, max_unique=50, time_limit_s=5.0)
    assert "empty_consumed" in result.witnesses


def test_9_empty_transferred_detected():
    state = _state_from_slots(
        {
            0: ([], [Card("s", 7)]),
            1: ([], []),
        }
    )
    before = empty_column_indices(state)
    child = state.clone()
    apply_action(child, (0, 1, 1))
    events = empty_transition_events(
        before,
        empty_column_indices(child),
        dest_was_empty=True,
        source_became_empty=True,
    )
    assert "EMPTY_TRANSFERRED" in events
    result = layered_reachability(state, max_depth=1, max_unique=50, time_limit_s=5.0)
    assert "empty_transferred" in result.witnesses


def test_10_empty_recreated_detected():
    state = _state_from_slots(
        {
            0: ([], [Card("h", 8), Card("s", 7)]),
            1: ([], []),
            2: ([], [Card("c", 6)]),
        }
    )
    consume = state.clone()
    apply_action(consume, (0, 1, 1))
    assert empty_column_indices(consume) == ()
    recreate = consume.clone()
    apply_action(recreate, (2, 1, 1))
    events = empty_transition_events(
        empty_column_indices(consume),
        empty_column_indices(recreate),
        dest_was_empty=False,
        source_became_empty=True,
    )
    assert "EMPTY_RECREATED" in events
    result = layered_reachability(state, max_depth=2, max_unique=80, time_limit_s=5.0)
    assert "empty_recreated" in result.witnesses or "empty_consumed" in result.witnesses


def test_11_second_empty_detected():
    state = _state_from_slots(
        {
            0: ([], [Card("s", 7)]),
            1: ([], [Card("h", 8)]),
            2: ([], []),
        }
    )
    child = state.clone()
    apply_action(child, (0, 1, 1))
    events = empty_transition_events(
        empty_column_indices(state),
        empty_column_indices(child),
        dest_was_empty=False,
        source_became_empty=True,
    )
    assert "SECOND_EMPTY" in events
    assert len(empty_column_indices(child)) == 2
    result = layered_reachability(state, max_depth=1, max_unique=50, time_limit_s=5.0)
    assert "second_empty" in result.witnesses


def test_12_hard_progress_witness_concatenates_from_original_deal():
    seed, prefix, _cost, opening = _seed()
    action = next(
        act for act in enumerate_actions(seed) if int(classify_tier(seed, act)) <= int(Tier.C)
    )
    combined = list(prefix) + [action]
    end = opening.clone()
    replay_actions(end, combined)
    child = seed.clone()
    apply_action(child, action)
    assert pack_state(end) == pack_state(child)
    report = ROOT / "docs" / "research" / "simple_progressive_workspace_transaction_v0_12.json"
    route = ROOT / "solutions" / "4925153_simple_v0_12_fd12.moves.txt"
    if route.exists():
        fd12 = parse_moves_file(route)
        fd12_state = opening.clone()
        replay_actions(fd12_state, fd12)
        assert sum(len(col.face_down) for col in fd12_state.columns) <= 12
        assert len(fd12_state.stock) == 0
    if report.exists():
        import json

        payload = json.loads(report.read_text(encoding="utf-8"))
        for name in ("fd_le_12", "foundation", "empty_transferred", "empty_recreated", "second_empty", "run_ge_10"):
            witness = (payload.get("witnesses") or {}).get(name)
            if not witness or not witness.get("combined_replay"):
                continue
            assert witness["combined_replay"].get("ok") is True


def test_13_production_default_solve_progressive_unchanged():
    state = _uncover_state()
    kwargs = dict(
        max_nodes=80,
        time_limit_s=2.0,
        depth_bands=(8,),
        max_pass=0,
        enable_audit=False,
        enable_best_reveal_deal_probe=True,
        enable_saturation=True,
    )
    default = solve_progressive(state, **kwargs)
    explicit = solve_progressive(state, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert default.nodes == explicit.nodes
    assert default.stats.tt_mode == TT_MODE_DEPTH_AWARE
    assert default.pass_reached == explicit.pass_reached


def test_14_mobilityware_unrestricted_rules_contract_remains():
    assert MW_RULES.can_deal_into_empty is True
    seed, actions, cost, opening = _seed()
    end = opening.clone()
    assert replay_actions(end, actions) == cost
    use = first_empty_use_on_path(seed, [])
    assert use is None
    assert empty_column_indices(seed)
