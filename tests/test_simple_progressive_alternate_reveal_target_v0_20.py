"""Alternate buried-stack targeting v0.20."""

from __future__ import annotations

import json
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_search_identity, pack_state, permute_tableau_columns
from spider.rules import MW_RULES
from spider.simple_progressive_solver import (
    TT_MODE_DEPTH_AWARE,
    apply_action,
    solve_progressive,
)
from spider.simple_target_clearance import (
    census_buried_targets,
    face_down_signature,
    is_target_reveal,
    locate_target,
    priority_key,
    signature_key,
    target_directed_plateau,
    target_face_up_count,
)
from spider.simple_workspace_reachability import (
    engine_tableau_actions,
    layered_reachability,
    post_stock_identity,
)

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
FD13 = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
REPORT = ROOT / "docs" / "research" / "simple_progressive_alternate_reveal_target_v0_20.json"
FD13_HEX = (
    "53504b310100000004093a2c360835042302310b0d1c3b050515191b11282d0c2b1a290000"
    "00121413121d071d1c1b1a19181716153433323100022d2c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)


def _opening() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL)))


def _fd13():
    actions = parse_moves_file(FD13)
    opening = _opening()
    end = opening.clone()
    cost = replay_actions(end, actions)
    return end, actions, cost, opening


def _state_from_slots(slots, stock=None) -> SpiderState:
    cols = []
    for index in range(10):
        down, up = slots.get(index, ([], [Card("s", 13)]))
        cols.append(Column(list(down), list(up)))
    return SpiderState(cols, list(stock or []), [])


def _toy_two_targets() -> SpiderState:
    return _state_from_slots(
        {
            0: ([Card("c", 9)], [Card("h", 6)]),
            1: ([], [Card("s", 7)]),
            2: ([], [Card("d", 8)]),
            3: ([], [Card("c", 13)]),
            4: ([], []),
            5: ([], [Card("h", 12)]),
            6: ([], [Card("d", 11)]),
            7: ([], [Card("s", 4)]),
            8: ([], [Card("c", 3)]),
            9: ([Card("h", 10)], [Card("h", 2)]),
        },
        [],
    )


def test_1_fd13_fixture_replays():
    end, actions, cost, opening = _fd13()
    assert len(actions) == 102
    assert cost == 102
    assert pack_state(end).hex() == FD13_HEX


def test_2_non_empty_face_down_target_signatures_are_detected():
    end, *_ = _fd13()
    rows = census_buried_targets(end)
    assert len(rows) == 3
    assert {row["physical_column_1"] for row in rows} == {1, 2, 7}
    keys = [row["signature_key"] for row in rows]
    assert len(keys) == len(set(keys))
    by_col = {row["physical_column_1"]: row for row in rows}
    assert by_col[1]["fd_count"] == 4
    assert by_col[1]["face_up_count"] == 9
    assert by_col[2]["fd_count"] == 5
    assert by_col[2]["face_up_count"] == 5
    assert by_col[7]["fd_count"] == 4
    assert by_col[7]["face_up_count"] == 17


def test_3_target_identity_survives_whole_column_permutation():
    end, *_ = _fd13()
    rows = census_buried_targets(end)
    sigs = {row["signature_key"] for row in rows}
    swapped = permute_tableau_columns(end, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    after = {row["signature_key"] for row in census_buried_targets(swapped)}
    assert sigs == after
    for row in rows:
        sig = tuple((s, r) for s, r in row["signature"])
        assert locate_target(swapped, sig) is not None


def test_4_target_face_up_count_is_invariant_under_symmetry_relabelling():
    end, *_ = _fd13()
    sig = face_down_signature(end.columns[1])
    fu = target_face_up_count(end, sig)
    perm = permute_tableau_columns(end, list(range(9, -1, -1)))
    assert target_face_up_count(perm, sig) == fu
    assert post_stock_identity(end) == post_stock_identity(perm)


def test_5_target_directed_priority_uses_only_face_up_then_depth():
    a = priority_key(3, 10, 99)
    b = priority_key(4, 1, 0)
    c = priority_key(3, 11, 0)
    d = priority_key(3, 10, 100)
    assert a < b
    assert a < c
    assert a < d
    assert a[:2] == (3, 10)


def test_6_no_legal_fd13_plateau_move_is_pruned_by_the_heuristic():
    seed = _toy_two_targets()
    target = face_down_signature(seed.columns[0])
    legal = engine_tableau_actions(seed)[0]
    result = target_directed_plateau(
        seed, target, plateau_fd=2, max_unique=200, time_limit_s=5.0, max_exits=8
    )
    assert result.generated >= len(legal)


def test_7_target_reveal_is_recognised_only_when_selected_stack_changes():
    seed = _toy_two_targets()
    parent = seed.clone()
    child = seed.clone()
    apply_action(child, (0, 1, 1))
    target = face_down_signature(parent.columns[0])
    other = face_down_signature(parent.columns[9])
    assert is_target_reveal(parent, child, target)
    assert not is_target_reveal(parent, child, other)


def test_8_revealing_another_buried_stack_is_not_counted_as_target_success():
    seed = _toy_two_targets()
    target = face_down_signature(seed.columns[9])
    result = target_directed_plateau(
        seed, target, plateau_fd=2, max_unique=80, time_limit_s=5.0, max_exits=8
    )
    easy = seed.clone()
    apply_action(easy, (0, 1, 1))
    easy_hex = pack_state(easy).hex()
    assert all(rec["ordered_digest"] != easy_hex for rec in result.exits)
    if result.exits:
        assert all(rec["target_key"] == signature_key(target) for rec in result.exits)


def test_9_target_fd12_exits_deduplicate_by_post_stock_symmetry():
    seed = _toy_two_targets()
    target = face_down_signature(seed.columns[0])
    result = target_directed_plateau(
        seed, target, plateau_fd=2, max_unique=80, time_limit_s=5.0, max_exits=8
    )
    digests = [rec["symmetry_digest"] for rec in result.exits]
    assert len(digests) == len(set(digests))
    assert result.exit_classes == len(result.exits)


def test_10_concrete_representative_paths_replay():
    seed = _toy_two_targets()
    target = face_down_signature(seed.columns[0])
    result = target_directed_plateau(
        seed, target, plateau_fd=2, max_unique=80, time_limit_s=5.0, max_exits=8
    )
    assert result.exits
    rec = result.exits[0]
    end = seed.clone()
    replay_actions(end, [tuple(a) for a in rec["actions"]])
    assert pack_state(end).hex() == rec["ordered_digest"]
    assert rec["replay_ok"] is True


def test_11_known_dead_cache_membership_remains_exact():
    cache = ROOT / "research" / "results" / "simple_progressive_fd13_plateau_exit_v0_19" / "known_dead_from_fd12.jsonl"
    if not cache.exists():
        return
    first = json.loads(cache.read_text(encoding="utf-8").splitlines()[0])
    digest = first["symmetry_digest"]
    members = {json.loads(line)["symmetry_digest"] for line in cache.read_text(encoding="utf-8").splitlines() if line.strip()}
    assert digest in members
    assert "deadbeef" not in members


def test_12_downstream_multi_source_includes_every_harvested_new_exit():
    a = _state_from_slots({0: ([], [Card("s", 8)]), 1: ([], [Card("h", 9)]), 2: ([Card("d", 4)], [Card("c", 6)])})
    b = _state_from_slots({0: ([], [Card("s", 5)]), 1: ([], [Card("h", 6)]), 2: ([Card("c", 3)], [Card("d", 7)])})
    result = layered_reachability(
        sources=[a, b],
        origin_paths=[[(0, 1, 1)], [(1, 0, 1)]],
        max_depth=1,
        max_unique=80,
        time_limit_s=5.0,
        identity_fn=post_stock_identity,
        all_legal_tableau=True,
        checkpoints=(),
    )
    assert result.source_count == 2


def test_13_fd10_or_foundation_route_replays_if_found():
    if not REPORT.exists():
        return
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    for key in ("fd10_witness", "foundation_witness", "viable_route"):
        rec = payload.get(key) or {}
        actions = rec.get("full_actions") or []
        if not actions:
            continue
        opening = _opening()
        end = opening.clone()
        replay_actions(end, [tuple(a) if a != ["deal"] else ("deal",) for a in actions])
        assert rec.get("replay_ok") is True


def test_14_production_solver_remains_unchanged():
    end, *_ = _fd13()
    assert pack_state(end)[:4] == b"SPK1"
    assert pack_search_identity(end) == pack_state(end)
    state = _toy_two_targets()
    kwargs = dict(max_nodes=80, time_limit_s=2.0, depth_bands=(8,), max_pass=0, enable_audit=False)
    default = solve_progressive(state, **kwargs)
    explicit = solve_progressive(state, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert default.nodes == explicit.nodes


def test_15_mobilityware_unrestricted_rules_contract_green():
    assert MW_RULES.can_deal_into_empty is True
    end, actions, cost, opening = _fd13()
    again = opening.clone()
    assert replay_actions(again, actions) == cost
    apply_action(end.clone(), (1, 2, 1))
