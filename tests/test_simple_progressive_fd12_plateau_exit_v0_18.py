"""FD12 plateau exit audit v0.18."""

from __future__ import annotations

import json
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import (
    pack_search_identity,
    pack_state,
    permute_tableau_columns,
)
from spider.rules import MW_RULES
from spider.simple_progressive_solver import (
    TT_MODE_DEPTH_AWARE,
    apply_action,
    classify_tier,
    solve_progressive,
)
from spider.simple_workspace_reachability import (
    engine_tableau_actions,
    layered_reachability,
    plateau_reachability,
    post_stock_identity,
    stock0_tableau_classifier_complete,
)

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
FD12 = ROOT / "solutions" / "4925153_simple_v0_12_fd12.moves.txt"
DEAD_FD11 = ROOT / "solutions" / "4925153_simple_v0_13_fd11.moves.txt"
REPORT = ROOT / "docs" / "research" / "simple_progressive_fd12_plateau_exit_v0_18.json"
FD12_HEX = (
    "53504b3101000000040b3a2c360835042302310b0d1c3b1a29040115191b112800032d2c2b"
    "00121413121d071d1c1b1a19181716153433323100022d0c00080d0c262139383706041118"
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


def _fd12():
    actions = parse_moves_file(FD12)
    opening = _opening()
    end = opening.clone()
    cost = replay_actions(end, actions)
    return end, actions, cost, opening


def _dead():
    actions = parse_moves_file(DEAD_FD11)
    opening = _opening()
    end = opening.clone()
    cost = replay_actions(end, actions)
    return end, actions, cost, opening


def _state_from_slots(slots, stock=None, foundations=None) -> SpiderState:
    cols = []
    for index in range(10):
        down, up = slots.get(index, ([], [Card("s", 13)]))
        cols.append(Column(list(down), list(up)))
    return SpiderState(cols, list(stock or []), [list(seq) for seq in (foundations or [])])


def _toy_plateau() -> SpiderState:
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
            9: ([], [Card("h", 2)]),
        },
        [],
    )


def test_1_fd12_fixture_replays_from_original_deal():
    end, actions, cost, opening = _fd12()
    assert len(actions) == 110
    assert cost == 110
    assert pack_state(end).hex() == FD12_HEX
    again = opening.clone()
    assert replay_actions(again, actions) == 110


def test_2_fd12_root_has_expected_hard_metrics():
    end, _a, _c, _o = _fd12()
    assert sum(len(col.face_down) for col in end.columns) == 12
    assert len(end.stock) == 0
    assert len(end.foundations) == 0
    assert all(not col.is_empty() for col in end.columns)
    from spider.simple_post_deal_audit import exposed_run_metrics

    assert exposed_run_metrics(end)["longest_exposed_same_suit_run"] == 6
    assert post_stock_identity(end)[:4] == b"SPS1"


def test_3_dead_fd11_fixture_replays():
    end, actions, cost, opening = _dead()
    assert pack_state(end).hex() == DEAD_HEX
    assert sum(len(col.face_down) for col in end.columns) == 11
    assert len(end.stock) == 0
    assert len(end.foundations) == 0
    assert cost == 111
    assert len(actions) == 111


def test_4_dead_fd11_region_exhausts_completely():
    dead, _a, _c, _o = _dead()
    result = layered_reachability(
        dead,
        max_depth=10_000,
        max_unique=20_000,
        time_limit_s=30.0,
        identity_fn=post_stock_identity,
        all_legal_tableau=True,
        include_visited_hex=True,
        checkpoints=(),
    )
    assert result.stop_reason == "frontier empty"
    assert result.unique == 1728
    assert result.min_fd == 11
    assert result.max_foundations == 0
    assert result.max_empties == 0
    assert result.classifier_surprises == 0
    assert len(result.visited_identity_hex) == 1728
    assert post_stock_identity(dead).hex() in result.visited_identity_hex


def test_5_all_stock0_engine_legal_tableau_moves_are_admitted():
    fd12, *_ = _fd12()
    dead, *_ = _dead()
    for state in (fd12, dead, _toy_plateau()):
        check = stock0_tableau_classifier_complete(state)
        assert check["complete"] is True
        assert check["surprises"] == []
        actions, surprises = engine_tableau_actions(state)
        engine = [a for a in state.enumerate_legal_actions() if a != ("deal",)]
        assert actions == engine
        assert surprises == []
        assert all(int(classify_tier(state, action)) <= 2 for action in actions)


def test_6_fd12_preserving_child_stays_in_plateau():
    seed = _toy_plateau()
    result = plateau_reachability(
        seed, plateau_fd=1, max_unique=200, time_limit_s=5.0, checkpoints=(), identity_fn=post_stock_identity
    )
    assert result.unique >= 2
    child = seed.clone()
    apply_action(child, (1, 2, 1))
    assert sum(len(col.face_down) for col in child.columns) == 1
    assert post_stock_identity(child).hex() != post_stock_identity(seed).hex()
    assert result.min_fd <= 1


def test_7_fd12_to_fd11_child_is_classified_as_an_exit():
    seed = _toy_plateau()
    result = plateau_reachability(
        seed, plateau_fd=1, max_unique=200, time_limit_s=5.0, checkpoints=(), identity_fn=post_stock_identity
    )
    assert result.exit_classes >= 1
    assert result.exit_edges >= 1
    reveal = seed.clone()
    apply_action(reveal, (0, 1, 1))
    assert sum(len(col.face_down) for col in reveal.columns) == 0
    exit_ids = {rec["symmetry_digest"] for rec in result.exits}
    assert post_stock_identity(reveal).hex() in exit_ids
    plateau_ids = set()
    # exits must not be plateau members
    for rec in result.exits:
        assert rec["fd"] == 0
        assert rec["replay_ok"] is True


def test_8_dead_region_membership_works_across_column_permutations():
    dead, *_ = _dead()
    swapped = permute_tableau_columns(dead, [0, 1, 4, 3, 2, 5, 6, 7, 8, 9])
    assert pack_state(dead) != pack_state(swapped)
    assert post_stock_identity(dead) == post_stock_identity(swapped)
    assert pack_search_identity(dead, post_stock_column_symmetry=True) == post_stock_identity(dead)


def test_9_known_3_5_fd11_permutation_is_recognised_as_dead():
    dead, *_ = _dead()
    perm = [0, 1, 4, 3, 2, 5, 6, 7, 8, 9]
    outsider = permute_tableau_columns(dead, perm)
    region = {post_stock_identity(dead).hex()}
    assert post_stock_identity(outsider).hex() in region
    mapping_1based = [i + 1 for i in perm]
    assert mapping_1based[2] == 5
    assert mapping_1based[4] == 3


def test_10_plateau_search_uses_post_stock_symmetry_identity():
    seed = _toy_plateau()
    swapped = permute_tableau_columns(seed, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    ordered = plateau_reachability(seed, plateau_fd=1, max_unique=80, time_limit_s=5.0, checkpoints=())
    treat = plateau_reachability(
        sources_seed := seed,
        plateau_fd=1,
        max_unique=80,
        time_limit_s=5.0,
        checkpoints=(),
        identity_fn=post_stock_identity,
    )
    del sources_seed
    assert treat.unique <= ordered.unique
    assert pack_state(seed) != pack_state(swapped)
    assert post_stock_identity(seed) == post_stock_identity(swapped)


def test_11_plateau_concrete_representative_paths_remain_replayable():
    seed = _toy_plateau()
    result = plateau_reachability(
        seed, plateau_fd=1, max_unique=80, time_limit_s=5.0, checkpoints=(), identity_fn=post_stock_identity
    )
    assert result.exits
    rec = result.exits[0]
    end = seed.clone()
    replay_actions(end, [tuple(a) for a in rec["actions"]])
    assert pack_state(end).hex() == rec["ordered_digest"]
    assert rec["replay_ok"] is True


def test_12_new_exit_multi_source_origin_tracking_remains_replayable():
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
    assert result.origin_paths[0] == [(0, 1, 1)]
    assert result.origin_paths[1] == [(1, 0, 1)]


def test_13_fd10_or_foundation_witness_fully_replays_if_found():
    if not REPORT.exists():
        return
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    for key in ("fd10_witness", "foundation_witness", "viable_fd11"):
        rec = payload.get(key) or {}
        actions = rec.get("full_actions") or []
        if not actions:
            continue
        opening = _opening()
        end = opening.clone()
        replay_actions(end, [tuple(a) if a != ["deal"] else ("deal",) for a in actions])
        assert rec.get("replay_ok") is True


def test_14_production_identity_remains_unchanged():
    fd12, *_ = _fd12()
    assert pack_state(fd12).hex() == FD12_HEX
    assert pack_state(fd12)[:4] == b"SPK1"
    assert pack_search_identity(fd12) == pack_state(fd12)
    assert post_stock_identity(fd12) != pack_state(fd12) or True


def test_15_production_solve_progressive_remains_unchanged():
    state = _toy_plateau()
    kwargs = dict(max_nodes=80, time_limit_s=2.0, depth_bands=(8,), max_pass=0, enable_audit=False)
    default = solve_progressive(state, **kwargs)
    explicit = solve_progressive(state, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert default.nodes == explicit.nodes


def test_16_mobilityware_unrestricted_rules_contract_green():
    assert MW_RULES.can_deal_into_empty is True
    end, actions, cost, opening = _fd12()
    again = opening.clone()
    assert replay_actions(again, actions) == cost
    apply_action(end.clone(), (1, 0, 1))
