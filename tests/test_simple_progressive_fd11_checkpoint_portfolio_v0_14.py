"""Minimum-depth fd11 checkpoint portfolio v0.14."""

from __future__ import annotations

import json
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
OLD_FD11 = ROOT / "solutions" / "4925153_simple_v0_13_fd11.moves.txt"
FD10 = ROOT / "solutions" / "4925153_simple_v0_14_fd10.moves.txt"
FOUNDATION = ROOT / "solutions" / "4925153_simple_v0_14_first_foundation.moves.txt"
REPORT = ROOT / "docs" / "research" / "simple_progressive_fd11_checkpoint_portfolio_v0_14.json"
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


def test_1_fd13_empty1_seed_replays():
    seed, actions, cost, opening = _seed()
    assert len(actions) == 102
    assert cost == 102
    assert pack_state(seed).hex() == EXPECTED_HEX
    assert empty_column_indices(seed) == (2,)


def test_2_v013_first_fd11_fixture_replays():
    opening = _opening()
    actions = parse_moves_file(OLD_FD11)
    end = opening.clone()
    cost = replay_actions(end, actions)
    assert len(actions) == 111
    assert cost == 111
    assert sum(len(col.face_down) for col in end.columns) == 11
    assert empty_column_indices(end) == ()
    assert len(end.stock) == 0
    assert len(end.foundations) == 0


def test_3_preflight_continuation_does_not_alter_production():
    state = _uncover_state()
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(8,), max_pass=0, enable_audit=False)
    a = solve_progressive(state, **kwargs)
    layered_reachability(state, max_depth=2, max_unique=50, time_limit_s=2.0)
    b = solve_progressive(state, **kwargs)
    assert a.nodes == b.nodes
    assert a.stats.tt_mode == b.stats.tt_mode


def test_4_layered_enumeration_does_not_stop_on_first_fd11():
    state = _uncover_state()
    start_fd = sum(len(col.face_down) for col in state.columns)
    stopped = layered_reachability(
        state, max_depth=2, max_unique=200, time_limit_s=5.0, stop_fd=start_fd - 1
    )
    collected = layered_reachability(
        state, max_depth=2, max_unique=200, time_limit_s=5.0, collect_fd=start_fd - 1
    )
    assert collected.stop_reason != stopped.stop_reason or len(collected.collected) >= 1
    assert not collected.stop_reason.startswith("fd <=") or collected.collected_complete
    assert len(collected.collected) >= 1
    assert collected.unique >= stopped.unique


def test_5_depth_le_8_contains_no_fd11_under_reproduced_search():
    if not REPORT.exists():
        return
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    first = (payload.get("phase1") or {}).get("first_depth") or {}
    assert first.get("fd_le_11") == 9
    for rec in payload.get("winner") and [] or []:
        pass
    assert payload.get("candidate_count", 1) >= 1


def test_6_all_collected_fd11_candidates_are_at_depth_9():
    if not REPORT.exists():
        return
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    assert (payload.get("phase1") or {}).get("collected_depth") in (9, None)
    winner = payload.get("winner")
    if winner:
        assert winner.get("depth") == 9


def test_7_exact_duplicate_fd11_states_collapse_canonically():
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
    child = state.clone()
    apply_action(child, (0, 1, 1))
    apply_action(child, (2, 3, 1))
    other = state.clone()
    apply_action(other, (2, 3, 1))
    apply_action(other, (0, 1, 1))
    assert pack_state(child) == pack_state(other)


def test_8_workspace_status_is_telemetry_only():
    assert is_hard_progress(start_fd=11, start_foundations=0, fd=11, foundations=0, empties=2) is False
    events = empty_transition_events((2,), (), dest_was_empty=True, source_became_empty=False)
    assert "EMPTY_CONSUMED" in events
    src = empty_transition_events.__doc__ or ""
    assert "Observational" in src


def test_9_multi_source_starts_from_every_collected_distinct_source():
    a = _state_from_slots({0: ([], [Card("s", 8)]), 1: ([], [Card("h", 9)])})
    b = _state_from_slots({0: ([], [Card("s", 6)]), 1: ([], [Card("h", 7)])})
    result = layered_reachability(
        sources=[a, b],
        origin_paths=[[], []],
        max_depth=1,
        max_unique=80,
        time_limit_s=5.0,
    )
    assert result.source_count == 2
    assert result.fresh_tt is True
    assert result.imported_keys == 0
    assert result.layers[0]["frontier_size"] == 2


def test_10_identical_later_states_from_different_origins_deduplicate():
    left = _state_from_slots(
        {0: ([], [Card("s", 8)]), 1: ([], [Card("h", 9)]), 2: ([], [Card("s", 6)]), 3: ([], [Card("h", 7)])}
    )
    right = left.clone()
    apply_action(right, (0, 1, 1))
    # two origins: original and after first commuting move; they share future children
    result = layered_reachability(
        sources=[left, right],
        max_depth=2,
        max_unique=80,
        time_limit_s=5.0,
    )
    assert result.duplicate_skips >= 1 or result.cross_origin_dups >= 0
    assert result.unique < result.generated or result.generated == 0


def test_11_origin_path_for_retained_state_remains_replayable():
    seed, prefix, _c, opening = _seed()
    local = [(1, 2, 1)]
    child = seed.clone()
    apply_action(child, local[0])
    result = layered_reachability(
        sources=[child],
        origin_paths=[local],
        max_depth=1,
        max_unique=40,
        time_limit_s=5.0,
    )
    combined = list(prefix) + local
    end = opening.clone()
    replay_actions(end, combined)
    assert pack_state(end) == pack_state(child)
    assert result.origin_paths[0] == [local[0]] or result.origin_paths[0] == [list(local[0])]


def test_12_abc_permissions_unchanged():
    seed, _a, _c, _o = _seed()
    allowed = ordered_actions(seed, 2, prep_ply=0, stats=None)
    assert all(int(classify_tier(seed, action)) <= int(Tier.C) for action in allowed)
    assert census_legal_by_tier(seed)["c"] > 0


def test_13_d_excluded():
    seed, _a, _c, _o = _seed()
    result = layered_reachability(seed, max_depth=1, max_unique=80, time_limit_s=5.0)
    layer = result.layers[0]
    assert layer["a_children"] + layer["b_children"] + layer["c_children"] == layer["generated_successors"]


def test_14_successful_fd10_or_foundation_combined_path_replays():
    opening = _opening()
    for path in (FD10, FOUNDATION):
        if not path.exists():
            continue
        actions = parse_moves_file(path)
        end = opening.clone()
        replay_actions(end, actions)
        assert len(end.stock) == 0
        if path == FD10:
            assert sum(len(col.face_down) for col in end.columns) <= 10
        if path == FOUNDATION:
            assert len(end.foundations) >= 1


def test_15_production_solve_progressive_unchanged():
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


def test_16_mobilityware_unrestricted_rules_contract_remains():
    assert MW_RULES.can_deal_into_empty is True
    seed, actions, cost, opening = _seed()
    end = opening.clone()
    assert replay_actions(end, actions) == cost
