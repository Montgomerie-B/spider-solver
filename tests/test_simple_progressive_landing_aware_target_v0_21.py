"""Landing-aware target clearance v0.21."""

from __future__ import annotations

import json
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_search_identity, pack_state, permute_tableau_columns
from spider.rules import MW_RULES
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, solve_progressive
from spider.simple_target_clearance import (
    LANDING_SENTINEL,
    blocks_above_rank,
    census_buried_targets,
    face_down_signature,
    is_target_reveal,
    landing_priority_key,
    legal_target_landings,
    movable_blocks,
    next_landing_obstruction,
    relaxed_clearance,
    target_block_count,
    target_directed_plateau,
    target_face_up_count,
    target_stack_audit,
)
from spider.simple_workspace_reachability import (
    engine_tableau_actions,
    layered_reachability,
    post_stock_identity,
)

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
FD13 = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
REPORT = ROOT / "docs" / "research" / "simple_progressive_landing_aware_target_v0_21.json"
FD13_HEX = (
    "53504b310100000004093a2c360835042302310b0d1c3b050515191b11282d0c2b1a290000"
    "00121413121d071d1c1b1a19181716153433323100022d2c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)
COL1_KEY = "c10,d12,c6,s8"


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


def _locked(slots) -> SpiderState:
    filled = {index: ([Card("d", 2)], [Card("s", 13)]) for index in range(10)}
    filled.update(slots)
    return _state_from_slots(filled, [])


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


def test_1_fd13_root_fixture_replays():
    end, actions, cost, opening = _fd13()
    assert len(actions) == 102
    assert cost == 102
    assert pack_state(end).hex() == FD13_HEX


def test_2_target_signature_survives_whole_column_permutation():
    end, *_ = _fd13()
    rows = census_buried_targets(end)
    col1 = next(row for row in rows if row["signature_key"] == COL1_KEY)
    assert col1["fd_count"] == 4
    assert col1["face_up_count"] == 9
    assert col1["exposed_run"] == 1
    sig = face_down_signature(end.columns[0])
    perm = permute_tableau_columns(end, list(range(9, -1, -1)))
    assert target_face_up_count(perm, sig) == 9
    assert {row["signature_key"] for row in census_buried_targets(perm)} == {
        row["signature_key"] for row in rows
    }


def test_3_target_movable_block_partition_is_correct():
    cards = [Card("s", 13), Card("s", 12), Card("h", 9), Card("h", 8), Card("d", 3)]
    blocks = movable_blocks(cards)
    assert len(blocks) == 3
    assert [int(c.rank) for c in blocks[0]] == [3]
    assert [int(c.rank) for c in blocks[1]] == [9, 8]
    assert [int(c.rank) for c in blocks[2]] == [13, 12]
    end, *_ = _fd13()
    sig = face_down_signature(end.columns[0])
    audit = target_stack_audit(end, sig)
    assert audit["block_count"] == target_block_count(end, sig)
    assert audit["block_count"] >= 1


def test_4_currently_legal_target_landing_gives_obstruction_0():
    seed = _toy_two_targets()
    target = face_down_signature(seed.columns[0])
    assert next_landing_obstruction(seed, target) == 0
    dests = legal_target_landings(seed, 0, 6)
    assert 1 in dests


def test_5_king_target_block_treats_only_an_empty_as_a_landing():
    king = _locked(
        {
            0: ([Card("c", 9)], [Card("s", 13)]),
            1: ([Card("h", 8)], [Card("d", 5)]),
            2: ([Card("s", 7)], [Card("c", 4)]),
        }
    )
    target = face_down_signature(king.columns[0])
    assert legal_target_landings(king, 0, 13) == []
    assert next_landing_obstruction(king, target) == LANDING_SENTINEL
    with_empty = _locked(
        {
            0: ([Card("c", 9)], [Card("s", 13)]),
            1: ([Card("h", 8)], [Card("d", 5)]),
            4: ([], []),
        }
    )
    t2 = face_down_signature(with_empty.columns[0])
    assert next_landing_obstruction(with_empty, t2) == 0
    assert 4 in legal_target_landings(with_empty, 0, 13)


def test_6_buried_face_down_rank_r_plus_1_is_not_an_available_landing():
    state = _locked(
        {
            0: ([Card("c", 9)], [Card("h", 6)]),
            1: ([Card("s", 7)], [Card("d", 2)]),
        }
    )
    target = face_down_signature(state.columns[0])
    assert legal_target_landings(state, 0, 6) == []
    assert blocks_above_rank(state.columns[1].face_up, 7) is None


def test_7_obstruction_to_face_up_r_plus_1_counts_blocks_above_it():
    cards = [Card("s", 7), Card("h", 5), Card("d", 4)]
    assert blocks_above_rank(cards, 7) == 2
    state = _locked(
        {
            0: ([Card("c", 9)], [Card("h", 6)]),
            1: ([], [Card("s", 7), Card("h", 5), Card("d", 4)]),
        }
    )
    target = face_down_signature(state.columns[0])
    assert next_landing_obstruction(state, target) == 2


def test_8_empty_creation_estimate_considers_only_columns_without_face_down():
    state = _locked(
        {
            0: ([Card("c", 9)], [Card("s", 13)]),
            1: ([Card("h", 2)], [Card("d", 5), Card("d", 4)]),
            2: ([], [Card("c", 8), Card("h", 3)]),
        }
    )
    target = face_down_signature(state.columns[0])
    assert next_landing_obstruction(state, target) == 2


def test_9_relaxed_clearance_and_queue_tuple_are_deterministic():
    end, *_ = _fd13()
    sig = face_down_signature(end.columns[0])
    a = relaxed_clearance(end, sig)
    b = relaxed_clearance(end, sig)
    assert a == b
    blocks = target_block_count(end, sig)
    obst = next_landing_obstruction(end, sig)
    assert a == blocks + obst
    k1 = landing_priority_key(a, blocks, obst, 9, 0, 0)
    k2 = landing_priority_key(a, blocks, obst, 9, 0, 1)
    assert k1 < k2
    assert k1[:4] == (a, blocks, obst, 9)


def test_10_worse_heuristic_states_are_ordered_later_but_never_pruned():
    seed = _toy_two_targets()
    target = face_down_signature(seed.columns[0])
    legal = engine_tableau_actions(seed)[0]
    worse = landing_priority_key(20, 10, 10, 12, 1, 0)
    better = landing_priority_key(1, 1, 0, 2, 5, 0)
    assert better < worse
    result = target_directed_plateau(
        seed, target, plateau_fd=2, max_unique=80, time_limit_s=5.0, max_exits=8, mode="landing"
    )
    assert result.generated >= len(legal)


def test_11_selected_target_reveal_is_identified_correctly():
    seed = _toy_two_targets()
    parent = seed.clone()
    child = seed.clone()
    apply_action(child, (0, 1, 1))
    target = face_down_signature(parent.columns[0])
    assert is_target_reveal(parent, child, target)


def test_12_off_target_reveal_is_not_target_success():
    seed = _toy_two_targets()
    target = face_down_signature(seed.columns[9])
    result = target_directed_plateau(
        seed, target, plateau_fd=2, max_unique=80, time_limit_s=5.0, max_exits=8, mode="landing"
    )
    easy = seed.clone()
    apply_action(easy, (0, 1, 1))
    assert all(rec["ordered_digest"] != pack_state(easy).hex() for rec in result.exits)


def test_13_concrete_paths_remain_replayable_under_symmetry():
    seed = _toy_two_targets()
    target = face_down_signature(seed.columns[0])
    result = target_directed_plateau(
        seed, target, plateau_fd=2, max_unique=80, time_limit_s=5.0, max_exits=8, mode="landing"
    )
    assert result.exits
    rec = result.exits[0]
    end = seed.clone()
    replay_actions(end, [tuple(a) for a in rec["actions"]])
    assert pack_state(end).hex() == rec["ordered_digest"]
    assert rec["replay_ok"] is True


def test_14_downstream_search_uses_all_legal_tableau_moves():
    a = _state_from_slots({0: ([], [Card("s", 8)]), 1: ([], [Card("h", 9)]), 2: ([Card("d", 4)], [Card("c", 6)])})
    result = layered_reachability(
        a,
        max_depth=1,
        max_unique=80,
        time_limit_s=5.0,
        identity_fn=post_stock_identity,
        all_legal_tableau=True,
        checkpoints=(),
    )
    assert result.classifier_surprises == 0
    assert result.generated >= 1


def test_15_production_solver_remains_unchanged():
    end, *_ = _fd13()
    assert pack_state(end)[:4] == b"SPK1"
    assert pack_search_identity(end) == pack_state(end)
    state = _toy_two_targets()
    kwargs = dict(max_nodes=80, time_limit_s=2.0, depth_bands=(8,), max_pass=0, enable_audit=False)
    default = solve_progressive(state, **kwargs)
    explicit = solve_progressive(state, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert default.nodes == explicit.nodes


def test_16_mobilityware_unrestricted_contract_remains_green():
    assert MW_RULES.can_deal_into_empty is True
    end, actions, cost, opening = _fd13()
    again = opening.clone()
    assert replay_actions(again, actions) == cost
    apply_action(end.clone(), (1, 2, 1))
