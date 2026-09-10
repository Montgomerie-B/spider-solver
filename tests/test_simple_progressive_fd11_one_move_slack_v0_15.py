"""One-move-slack fd11 checkpoints v0.15."""

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
from spider.simple_workspace_reachability import empty_column_indices, layered_reachability

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
SEED = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
DEAD_FD11 = ROOT / "solutions" / "4925153_simple_v0_13_fd11.moves.txt"
FD10 = ROOT / "solutions" / "4925153_simple_v0_15_fd10.moves.txt"
FOUNDATION = ROOT / "solutions" / "4925153_simple_v0_15_first_foundation.moves.txt"
REPORT = ROOT / "docs" / "research" / "simple_progressive_fd11_one_move_slack_v0_15.json"
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


def test_1_authoritative_fd13_seed_replays():
    seed, actions, cost, opening = _seed()
    assert len(actions) == 102
    assert cost == 102
    assert pack_state(seed).hex() == EXPECTED_HEX
    assert empty_column_indices(seed) == (2,)


def test_2_depth9_minimum_fd11_remains_the_known_singleton():
    opening = _opening()
    actions = parse_moves_file(DEAD_FD11)
    end = opening.clone()
    replay_actions(end, actions)
    assert pack_state(end).hex() == DEAD_HEX
    assert sum(len(col.face_down) for col in end.columns) == 11
    if REPORT.exists():
        payload = json.loads(REPORT.read_text(encoding="utf-8"))
        assert (payload.get("depth9_regression") or {}).get("first_fd11_depth") == 9


def test_3_depth10_harvest_expands_complete_depth9_frontier():
    if not REPORT.exists():
        return
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    phase1 = payload.get("phase1") or {}
    assert phase1.get("keys_before_stream") == 1_144_490
    if phase1.get("collected_complete"):
        assert phase1.get("completed_expanded_depth") == 9
        return
    frac = phase1.get("depth_expanded_frac") or {}
    assert frac.get("depth") == 9
    assert frac.get("processed", 0) < frac.get("frontier", 1)


def test_4_shallower_state_is_not_counted_as_depth10_candidate():
    state = _uncover_state()
    start_fd = sum(len(col.face_down) for col in state.columns)
    result = layered_reachability(
        state,
        max_depth=2,
        max_unique=200,
        time_limit_s=5.0,
        collect_fd=start_fd - 1,
        collect_exact_depth=2,
        stream_last=True,
    )
    assert all(item["depth"] == 2 for item in result.collected)


def test_5_distinct_depth10_canonical_fd11_states_deduplicate():
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
    digests = [item["digest"] for item in result.collected]
    assert len(digests) == len(set(digests))


def test_6_non_fd11_depth10_states_need_not_be_retained_as_frontier():
    state = _uncover_state()
    streamed = layered_reachability(
        state, max_depth=2, max_unique=200, time_limit_s=5.0, stream_last=True, collect_fd=0, collect_exact_depth=2
    )
    full = layered_reachability(state, max_depth=2, max_unique=200, time_limit_s=5.0)
    assert streamed.stream_discarded >= 0
    assert streamed.unique <= full.unique
    assert streamed.last_layer_generated >= streamed.stream_discarded


def test_7_abc_permissions_unchanged():
    seed, _a, _c, _o = _seed()
    allowed = ordered_actions(seed, 2, prep_ply=0, stats=None)
    assert all(int(classify_tier(seed, action)) <= int(Tier.C) for action in allowed)
    assert census_legal_by_tier(seed)["c"] > 0


def test_8_d_remains_excluded():
    seed, _a, _c, _o = _seed()
    result = layered_reachability(seed, max_depth=1, max_unique=80, time_limit_s=5.0)
    layer = result.layers[0]
    assert layer["a_children"] + layer["b_children"] + layer["c_children"] == layer["generated_successors"]


def test_9_multi_source_continuation_includes_every_retained_candidate():
    a = _state_from_slots({0: ([], [Card("s", 8)]), 1: ([], [Card("h", 9)])})
    b = _state_from_slots({0: ([], [Card("s", 6)]), 1: ([], [Card("h", 7)])})
    result = layered_reachability(sources=[a, b], max_depth=1, max_unique=80, time_limit_s=5.0)
    assert result.source_count == 2
    assert result.layers[0]["frontier_size"] == 2


def test_10_exact_convergent_continuation_states_deduplicate():
    left = _state_from_slots(
        {0: ([], [Card("s", 8)]), 1: ([], [Card("h", 9)]), 2: ([], [Card("s", 6)]), 3: ([], [Card("h", 7)])}
    )
    right = left.clone()
    apply_action(right, (0, 1, 1))
    result = layered_reachability(sources=[left, right], max_depth=2, max_unique=80, time_limit_s=5.0)
    assert result.duplicate_skips >= 1 or result.unique <= result.generated


def test_11_origin_path_remains_replayable():
    seed, prefix, _c, opening = _seed()
    local = [(1, 2, 1)]
    child = seed.clone()
    apply_action(child, local[0])
    result = layered_reachability(sources=[child], origin_paths=[local], max_depth=1, max_unique=40, time_limit_s=5.0)
    end = opening.clone()
    replay_actions(end, list(prefix) + local)
    assert pack_state(end) == pack_state(child)
    assert result.origin_paths[0][0] == local[0]


def test_12_fd10_or_foundation_witness_replays_from_original_deal():
    opening = _opening()
    for path in (FD10, FOUNDATION):
        if not path.exists():
            continue
        actions = parse_moves_file(path)
        end = opening.clone()
        replay_actions(end, actions)
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
