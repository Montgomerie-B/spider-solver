"""Hard-progress reveal ratchet v0.13."""

from __future__ import annotations

import inspect
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
    classify_tier,
    ordered_actions,
    solve_progressive,
)
from spider.simple_workspace_reachability import (
    empty_column_indices,
    empty_transition_events,
    is_hard_progress,
    layered_reachability,
)

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
SEED = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
FD11 = ROOT / "solutions" / "4925153_simple_v0_13_fd11.moves.txt"
FD10 = ROOT / "solutions" / "4925153_simple_v0_13_fd10.moves.txt"
FD9 = ROOT / "solutions" / "4925153_simple_v0_13_fd9.moves.txt"
EXPECTED_HEX = (
    "53504b310100000004093a2c360835042302310b0d1c3b050515191b11282d0c2b1a290000"
    "00121413121d071d1c1b1a19181716153433323100022d2c00080d0c262139383706041118"
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


def _state_from_slots(slots, stock=None) -> SpiderState:
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


def test_1_v012_fd13_empty1_seed_replays():
    seed, actions, cost, opening = _seed()
    assert len(actions) == 102
    assert cost == 102
    assert pack_state(seed).hex() == EXPECTED_HEX
    assert empty_column_indices(seed) == (2,)
    again = opening.clone()
    assert replay_actions(again, actions) == 102


def test_2_phase1_layered_search_can_stop_on_fd_le_11():
    state = _uncover_state()
    start_fd = sum(len(col.face_down) for col in state.columns)
    result = layered_reachability(
        state, max_depth=4, max_unique=200, time_limit_s=5.0, stop_fd=start_fd - 1
    )
    assert result.min_fd <= start_fd - 1
    assert result.stop_reason.startswith("fd <=")
    assert result.fresh_tt is True


def test_3_fd11_witness_replays_from_original_deal():
    if not FD11.exists():
        return
    opening = _opening()
    actions = parse_moves_file(FD11)
    end = opening.clone()
    replay_actions(end, actions)
    assert sum(len(col.face_down) for col in end.columns) <= 11
    assert len(end.stock) == 0


def test_4_ratchet_restart_uses_fresh_tt():
    seed, _a, _c, _o = _seed()
    first = layered_reachability(seed, max_depth=1, max_unique=80, time_limit_s=5.0)
    second = layered_reachability(seed, max_depth=1, max_unique=80, time_limit_s=5.0)
    assert first.fresh_tt is True
    assert second.fresh_tt is True
    assert first.imported_keys == 0
    assert second.imported_keys == 0
    assert first.unique == second.unique
    assert first.root_digest == second.root_digest == pack_state(seed).hex()


def test_5_earlier_visited_states_are_not_imported():
    params = inspect.signature(layered_reachability).parameters
    assert "imported_keys" not in params
    assert "seen" not in params
    assert "tt" not in params
    seed, _a, _c, _o = _seed()
    a = layered_reachability(seed, max_depth=1, max_unique=80, time_limit_s=5.0)
    child = _uncover_state()
    b = layered_reachability(child, max_depth=1, max_unique=80, time_limit_s=5.0)
    assert a.root_digest != b.root_digest
    assert b.imported_keys == 0
    assert b.unique <= 80


def test_6_abc_permissions_unchanged():
    seed, _a, _c, _o = _seed()
    allowed = ordered_actions(seed, 2, prep_ply=0, stats=None)
    assert allowed
    assert all(int(classify_tier(seed, action)) <= int(Tier.C) for action in allowed)
    census = census_legal_by_tier(seed)
    assert census["c"] > 0


def test_7_d_remains_excluded():
    seed, _a, _c, _o = _seed()
    result = layered_reachability(seed, max_depth=1, max_unique=80, time_limit_s=5.0)
    layer = result.layers[0]
    assert layer["a_children"] + layer["b_children"] + layer["c_children"] == layer["generated_successors"]
    for action in ordered_actions(seed, 2, prep_ply=0, stats=None):
        assert int(classify_tier(seed, action)) != int(Tier.D)


def test_8_hard_progress_triggers_only_on_lower_fd_or_higher_foundation():
    assert is_hard_progress(start_fd=13, start_foundations=0, fd=11, foundations=0) is True
    assert is_hard_progress(start_fd=13, start_foundations=0, fd=13, foundations=1) is True
    assert is_hard_progress(start_fd=13, start_foundations=0, fd=13, foundations=0) is False


def test_9_empty_run_adjacency_do_not_trigger_ratchet():
    assert (
        is_hard_progress(
            start_fd=13,
            start_foundations=0,
            fd=13,
            foundations=0,
            empties=2,
            longest_run=12,
            adjacencies=40,
            blocks=8,
        )
        is False
    )


def test_10_workspace_lifecycle_telemetry_is_observational():
    before = (2,)
    after = ()
    events = empty_transition_events(before, after, dest_was_empty=True, source_became_empty=False)
    assert "EMPTY_CONSUMED" in events
    assert is_hard_progress(start_fd=13, start_foundations=0, fd=13, foundations=0, empties=0) is False
    src = inspect.getsource(empty_transition_events)
    assert "score" not in src.lower()
    assert "heuristic" not in src.lower()


def test_11_fd10_witness_replays_from_original_deal():
    if not FD10.exists():
        return
    opening = _opening()
    actions = parse_moves_file(FD10)
    end = opening.clone()
    replay_actions(end, actions)
    assert sum(len(col.face_down) for col in end.columns) <= 10
    assert len(end.stock) == 0


def test_12_optional_fd9_witness_replays_if_run():
    if not FD9.exists():
        return
    opening = _opening()
    actions = parse_moves_file(FD9)
    end = opening.clone()
    replay_actions(end, actions)
    assert sum(len(col.face_down) for col in end.columns) <= 9
    assert len(end.stock) == 0


def test_13_production_solve_progressive_unchanged():
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


def test_14_mobilityware_unrestricted_rules_contract_remains():
    assert MW_RULES.can_deal_into_empty is True
    seed, actions, cost, opening = _seed()
    end = opening.clone()
    assert replay_actions(end, actions) == cost
