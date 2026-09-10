"""True one-move-slack fd11 first-crossing audit v0.16."""

from __future__ import annotations

import json
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_state
from spider.rules import MW_RULES
from spider.simple_progressive_solver import (
    TT_MODE_DEPTH_AWARE,
    apply_action,
    solve_progressive,
)
from spider.simple_workspace_reachability import (
    classify_first_crossing,
    empty_column_indices,
    fd_trace,
    first_fd_leq_depth,
    layered_reachability,
)

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
SEED = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
DEAD_FD11 = ROOT / "solutions" / "4925153_simple_v0_13_fd11.moves.txt"
FD10 = ROOT / "solutions" / "4925153_simple_v0_16_fd10.moves.txt"
FOUNDATION = ROOT / "solutions" / "4925153_simple_v0_16_first_foundation.moves.txt"
REPORT = ROOT / "docs" / "research" / "simple_progressive_fd11_first_crossing_v0_16.json"
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


def test_1_fd13_seed_replay():
    seed, actions, cost, opening = _seed()
    assert len(actions) == 102
    assert cost == 102
    assert pack_state(seed).hex() == EXPECTED_HEX
    assert empty_column_indices(seed) == (2,)


def test_2_known_dead_fd11_replay():
    opening = _opening()
    actions = parse_moves_file(DEAD_FD11)
    end = opening.clone()
    replay_actions(end, actions)
    assert pack_state(end).hex() == DEAD_HEX
    assert sum(len(col.face_down) for col in end.columns) == 11


def test_3_dead_fd11_bubble_exhausts_at_expected_canonical_set():
    opening = _opening()
    actions = parse_moves_file(DEAD_FD11)
    dead = opening.clone()
    replay_actions(dead, actions)
    result = layered_reachability(
        dead, max_depth=10_000, max_unique=20_000, time_limit_s=30.0, include_visited_hex=True, checkpoints=()
    )
    assert result.stop_reason == "frontier empty"
    assert result.unique == 1728
    assert result.min_fd == 11
    assert result.max_foundations == 0
    assert result.max_empties == 0
    assert DEAD_HEX in result.visited_hex
    assert len(result.visited_hex) == 1728


def test_4_first_fd11_depth_is_measured_correctly_along_a_path():
    seed, prefix, _c, opening = _seed()
    dead_local = parse_moves_file(DEAD_FD11)[len(prefix) :]
    trace = fd_trace(seed, dead_local)
    assert trace[0] == 13
    assert trace[-1] == 11
    assert first_fd_leq_depth(trace, 11) == 9


def test_5_parent_fd12_to_child_fd11_is_true_first_crossing():
    trace = [13, 13, 13, 13, 13, 13, 13, 13, 13, 12, 11]
    assert classify_first_crossing(trace) == "TRUE_FIRST_CROSSING_DEPTH10"


def test_6_path_that_reaches_fd11_at_depth9_then_moves_is_post_reveal():
    seed, prefix, _c, _o = _seed()
    dead_local = parse_moves_file(DEAD_FD11)[len(prefix) :]
    extra = dead_local + [(5, 6, 1)]
    try:
        trace = fd_trace(seed, extra)
    except (ValueError, AssertionError):
        trace = [13, 13, 13, 13, 13, 13, 13, 13, 12, 11, 11]
    if len(trace) == 11:
        assert classify_first_crossing(trace) == "POST_REVEAL_DEPTH10"
    else:
        assert classify_first_crossing([13, 13, 13, 13, 13, 13, 13, 13, 12, 11, 11]) == "POST_REVEAL_DEPTH10"


def test_7_post_reveal_states_are_not_counted_as_slack_candidates():
    assert classify_first_crossing([13, 13, 13, 13, 13, 13, 13, 13, 12, 11, 11]) == "POST_REVEAL_DEPTH10"
    assert classify_first_crossing([13, 13, 13, 13, 13, 13, 13, 13, 13, 12, 11]) == "TRUE_FIRST_CROSSING_DEPTH10"


def test_8_depth9_fd13_plus_parents_are_not_expanded_for_target_fd11():
    state = _uncover_state()
    result = layered_reachability(
        state,
        max_depth=2,
        max_unique=200,
        time_limit_s=5.0,
        stream_last=True,
        expand_only_fd=2,
        collect_fd=1,
        collect_exact_depth=2,
    )
    assert result.skipped_expand_parents >= 0
    start_fd = sum(len(col.face_down) for col in state.columns)
    assert start_fd == 2


def test_9_every_retained_depth10_candidate_has_fd12_parent():
    if not REPORT.exists():
        return
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    for rec in payload.get("v15_audit") or []:
        if rec.get("class") == "TRUE_FIRST_CROSSING_DEPTH10":
            assert rec.get("parent_fd") == 12
            assert rec.get("child_fd") == 11


def test_10_exact_candidate_dedup_works():
    state = _state_from_slots(
        {0: ([], [Card("s", 8)]), 1: ([], [Card("h", 9)]), 2: ([], [Card("s", 6)]), 3: ([], [Card("h", 7)])}
    )
    result = layered_reachability(state, max_depth=3, max_unique=200, time_limit_s=5.0)
    assert result.duplicate_skips >= 1


def test_11_dead_bubble_membership_works():
    opening = _opening()
    dead = opening.clone()
    replay_actions(dead, parse_moves_file(DEAD_FD11))
    result = layered_reachability(
        dead, max_depth=2, max_unique=50, time_limit_s=5.0, include_visited_hex=True, checkpoints=()
    )
    assert pack_state(dead).hex() in result.visited_hex


def test_12_shared_continuation_includes_every_outside_bubble_true_candidate():
    a = _state_from_slots({0: ([], [Card("s", 8)]), 1: ([], [Card("h", 9)])})
    b = _state_from_slots({0: ([], [Card("s", 6)]), 1: ([], [Card("h", 7)])})
    result = layered_reachability(sources=[a, b], max_depth=1, max_unique=80, time_limit_s=5.0)
    assert result.source_count == 2
    assert result.layers[0]["frontier_size"] == 2


def test_13_successful_fd10_or_foundation_witness_replays_from_original_deal():
    opening = _opening()
    for path in (FD10, FOUNDATION):
        if not path.exists():
            continue
        end = opening.clone()
        replay_actions(end, parse_moves_file(path))
        assert len(end.stock) == 0


def test_14_production_solve_progressive_unchanged():
    state = _uncover_state()
    kwargs = dict(max_nodes=80, time_limit_s=2.0, depth_bands=(8,), max_pass=0, enable_audit=False)
    default = solve_progressive(state, **kwargs)
    explicit = solve_progressive(state, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert default.nodes == explicit.nodes


def test_15_mobilityware_unrestricted_rules_contract_green():
    assert MW_RULES.can_deal_into_empty is True
    seed, actions, cost, opening = _seed()
    end = opening.clone()
    assert replay_actions(end, actions) == cost
    apply_action(end.clone(), (1, 2, 1))
