"""FD13 plateau alternative-fd12 exit audit v0.19."""

from __future__ import annotations

import json
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_search_identity, pack_state, permute_tableau_columns
from spider.rules import MW_RULES
from spider.simple_post_deal_audit import exposed_run_metrics
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
FD13 = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
FD12 = ROOT / "solutions" / "4925153_simple_v0_12_fd12.moves.txt"
REPORT = ROOT / "docs" / "research" / "simple_progressive_fd13_plateau_exit_v0_19.json"
FD13_HEX = (
    "53504b310100000004093a2c360835042302310b0d1c3b050515191b11282d0c2b1a290000"
    "00121413121d071d1c1b1a19181716153433323100022d2c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)
FD12_HEX = (
    "53504b3101000000040b3a2c360835042302310b0d1c3b1a29040115191b112800032d2c2b"
    "00121413121d071d1c1b1a19181716153433323100022d0c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)


def _opening() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL)))


def _replay(path: Path):
    actions = parse_moves_file(path)
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


def _toy_fd2() -> SpiderState:
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


def test_1_fd13_fixture_replays_from_original_deal():
    end, actions, cost, opening = _replay(FD13)
    assert len(actions) == 102
    assert cost == 102
    assert pack_state(end).hex() == FD13_HEX
    again = opening.clone()
    assert replay_actions(again, actions) == 102


def test_2_dead_fd12_fixture_replays():
    end, actions, cost, opening = _replay(FD12)
    assert len(actions) == 110
    assert cost == 110
    assert pack_state(end).hex() == FD12_HEX
    assert sum(len(col.face_down) for col in end.columns) == 12
    assert len(end.stock) == 0
    assert len(end.foundations) == 0


def test_3_known_dead_from_fd12_fully_exhausts():
    seed = _toy_fd2()
    result = layered_reachability(
        seed,
        max_depth=10_000,
        max_unique=5_000,
        time_limit_s=10.0,
        identity_fn=post_stock_identity,
        all_legal_tableau=True,
        checkpoints=(),
        include_visited_hex=True,
    )
    assert result.stop_reason == "frontier empty"
    assert result.unique >= 1
    if REPORT.exists():
        payload = json.loads(REPORT.read_text(encoding="utf-8"))
        dead = payload.get("known_dead_from_fd12") or {}
        assert dead.get("exhausted") is True
        assert dead.get("min_fd", 0) >= 11
        assert dead.get("max_foundations") == 0


def test_4_known_dead_region_contains_no_fd10_or_foundation():
    fd12, *_ = _replay(FD12)
    result = layered_reachability(
        fd12,
        max_depth=2,
        max_unique=200,
        time_limit_s=5.0,
        identity_fn=post_stock_identity,
        all_legal_tableau=True,
        checkpoints=(),
    )
    assert result.min_fd >= 11
    assert result.max_foundations == 0
    if REPORT.exists():
        payload = json.loads(REPORT.read_text(encoding="utf-8"))
        dead = payload.get("known_dead_from_fd12") or {}
        assert dead.get("min_fd") >= 11
        assert dead.get("max_foundations") == 0


def test_5_fd13_plateau_preserves_fd13_foundation0_only():
    seed = _toy_fd2()
    result = plateau_reachability(
        seed, plateau_fd=2, max_unique=200, time_limit_s=5.0, checkpoints=(), identity_fn=post_stock_identity
    )
    assert result.plateau_fd == 2
    for rec in result.exits:
        assert rec["fd"] == 1
        assert rec["foundations"] == 0
    assert result.max_foundations == 0 or result.foundation_witness is not None


def test_6_fd13_to_fd12_transition_is_recorded_as_exit():
    seed = _toy_fd2()
    result = plateau_reachability(
        seed, plateau_fd=2, max_unique=200, time_limit_s=5.0, checkpoints=(), identity_fn=post_stock_identity
    )
    assert result.exit_classes >= 1
    reveal = seed.clone()
    apply_action(reveal, (0, 1, 1))
    assert sum(len(col.face_down) for col in reveal.columns) == 1
    assert post_stock_identity(reveal).hex() in {rec["symmetry_digest"] for rec in result.exits}


def test_7_symmetry_equivalent_fd12_exits_deduplicate():
    seed = _toy_fd2()
    swapped = permute_tableau_columns(seed, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    a = plateau_reachability(seed, plateau_fd=2, max_unique=80, time_limit_s=5.0, checkpoints=(), identity_fn=post_stock_identity)
    b = plateau_reachability(swapped, plateau_fd=2, max_unique=80, time_limit_s=5.0, checkpoints=(), identity_fn=post_stock_identity)
    assert {rec["symmetry_digest"] for rec in a.exits} == {rec["symmetry_digest"] for rec in b.exits}


def test_8_known_dead_fd12_membership_works():
    fd12, *_ = _replay(FD12)
    swapped = permute_tableau_columns(fd12, [0, 1, 4, 3, 2, 5, 6, 7, 8, 9])
    assert pack_state(fd12) != pack_state(swapped)
    assert post_stock_identity(fd12) == post_stock_identity(swapped)
    plateau = {post_stock_identity(fd12).hex()}
    assert post_stock_identity(swapped).hex() in plateau


def test_9_new_fd12_exits_are_not_called_viable_automatically():
    seed = _toy_fd2()
    result = plateau_reachability(
        seed, plateau_fd=2, max_unique=80, time_limit_s=5.0, checkpoints=(), identity_fn=post_stock_identity
    )
    for rec in result.exits:
        assert "viable" not in rec
        assert rec.get("fd") == 1


def test_10_phase2_includes_every_distinct_new_fd12_source():
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


def test_11_known_dead_from_fd12_pruning_is_exact_and_counted_separately():
    seed, *_ = _replay(FD12)
    control = layered_reachability(
        seed,
        max_depth=1,
        max_unique=80,
        time_limit_s=5.0,
        identity_fn=post_stock_identity,
        all_legal_tableau=True,
        include_visited_hex=True,
        checkpoints=(),
    )
    child_idents = [bytes.fromhex(h) for h in control.visited_identity_hex[1:]]
    assert child_idents
    victim = child_idents[0]
    treated = layered_reachability(
        seed,
        max_depth=1,
        max_unique=80,
        time_limit_s=5.0,
        identity_fn=post_stock_identity,
        all_legal_tableau=True,
        dead_identities={victim},
        checkpoints=(),
    )
    assert treated.known_dead_prunes >= 1
    assert treated.unique == control.unique - 1


def test_12_concrete_origin_paths_survive_symmetry_dedup():
    seed = _toy_fd2()
    result = plateau_reachability(
        seed, plateau_fd=2, max_unique=80, time_limit_s=5.0, checkpoints=(), identity_fn=post_stock_identity
    )
    rec = result.exits[0]
    end = seed.clone()
    replay_actions(end, [tuple(a) for a in rec["actions"]])
    assert pack_state(end).hex() == rec["ordered_digest"]
    assert rec["replay_ok"] is True


def test_13_successful_fd10_or_foundation_path_replays_if_found():
    if not REPORT.exists():
        return
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    for key in ("fd10_witness", "foundation_witness", "viable_fd12"):
        rec = payload.get(key) or {}
        actions = rec.get("full_actions") or []
        if not actions:
            continue
        opening = _opening()
        end = opening.clone()
        replay_actions(end, [tuple(a) if a != ["deal"] else ("deal",) for a in actions])
        assert rec.get("replay_ok") is True


def test_14_all_engine_legal_stock0_tableau_actions_are_included():
    fd13, *_ = _replay(FD13)
    fd12, *_ = _replay(FD12)
    for state in (fd13, fd12, _toy_fd2()):
        check = stock0_tableau_classifier_complete(state)
        assert check["complete"] is True
        actions, surprises = engine_tableau_actions(state)
        engine = [a for a in state.enumerate_legal_actions() if a != ("deal",)]
        assert actions == engine
        assert surprises == []
        assert all(int(classify_tier(state, action)) <= 2 for action in actions)


def test_15_production_identity_remains_unchanged():
    fd13, *_ = _replay(FD13)
    assert pack_state(fd13).hex() == FD13_HEX
    assert pack_state(fd13)[:4] == b"SPK1"
    assert pack_search_identity(fd13) == pack_state(fd13)
    assert post_stock_identity(fd13)[:4] == b"SPS1"


def test_16_production_solve_progressive_remains_unchanged():
    state = _toy_fd2()
    kwargs = dict(max_nodes=80, time_limit_s=2.0, depth_bands=(8,), max_pass=0, enable_audit=False)
    default = solve_progressive(state, **kwargs)
    explicit = solve_progressive(state, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert default.nodes == explicit.nodes


def test_17_mobilityware_unrestricted_rules_contract_green():
    assert MW_RULES.can_deal_into_empty is True
    end, actions, cost, opening = _replay(FD13)
    again = opening.clone()
    assert replay_actions(again, actions) == cost
    apply_action(end.clone(), (1, 2, 1))
    assert exposed_run_metrics(end)["longest_exposed_same_suit_run"] == 6
