"""FD14 plateau boundary search v0.24."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_search_identity, pack_state, permute_tableau_columns
from spider.rules import MW_RULES
from spider.simple_fd14_boundary import (
    CURRENT_FD13_EXIT,
    NEW_FD13_EXIT,
    enumerate_root_child_classes,
    face_down_column_census,
    fd14_boundary_search,
)
from spider.simple_legacy_fd13_alternatives import reveal_target_from_transition
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, solve_progressive
from spider.simple_workspace_reachability import (
    engine_tableau_actions,
    face_down_count,
    post_stock_identity,
)

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
FD14 = ROOT / "solutions" / "4925153_simple_fd14_stock0_seed.moves.txt"
FD13 = ROOT / "solutions" / "4925153_simple_v0_23_b281_fd13.moves.txt"
REPORT = ROOT / "docs" / "research" / "simple_progressive_fd14_boundary_search_v0_24.json"
FD14_HEX = (
    "53504b3101000000040a3a2c360835042302310b0d322913050915191b11282d0c2b1a2901"
    "0a0b1a010c3b2706153423323124162c1c2200081413121d071d223300062d242118341900"
    "070d0c2621393c37040c18360a2a280706050403020911033d17000612272a053801000d3d"
    "3c3b3a39383726081c251b3300071716352b140925"
)
EXPECTED_ROOT = {(2, 0, 1), (2, 3, 1), (2, 8, 1), (4, 1, 1), (7, 2, 1)}


def _opening() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL)))


def _replay(path: Path):
    actions = parse_moves_file(path)
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


def _plateau2() -> SpiderState:
    """fd=2 stock=0 toy with plateau moves and a reveal."""
    return _state_from_slots(
        {
            0: ([Card("c", 11)], [Card("h", 7), Card("h", 6)]),
            1: ([], [Card("s", 7)]),
            2: ([], [Card("h", 5)]),
            3: ([], []),
            4: ([], [Card("c", 13)]),
            5: ([], [Card("d", 13)]),
            6: ([], [Card("s", 12)]),
            7: ([Card("d", 10)], [Card("s", 4)]),
            8: ([], [Card("c", 3)]),
            9: ([], [Card("h", 2)]),
        },
        [],
    )


def _two_empty_plateau() -> SpiderState:
    return _state_from_slots(
        {
            0: ([Card("c", 11)], [Card("s", 13), Card("s", 12)]),
            1: ([], []),
            2: ([], []),
            3: ([], [Card("h", 6)]),
            4: ([], [Card("c", 5)]),
            5: ([], [Card("d", 4)]),
            6: ([], [Card("s", 3)]),
            7: ([Card("d", 10)], [Card("h", 2)]),
            8: ([], [Card("c", 8)]),
            9: ([], [Card("h", 9)]),
        },
        [],
    )


def test_1_fd14_fixture_replays():
    end, actions, cost, _ = _replay(FD14)
    assert len(actions) == 43
    assert cost == 43
    assert face_down_count(end) == 14
    assert len(end.stock) == 0
    assert len(end.foundations) == 0
    assert not any(col.is_empty() for col in end.columns)
    assert pack_state(end).hex() == FD14_HEX


def test_2_current_fd13_fixture_replays():
    end, actions, cost, _ = _replay(FD13)
    assert len(actions) == 101
    assert cost == 101
    assert face_down_count(end) == 13
    assert len(end.stock) == 0
    assert len(end.foundations) == 0
    assert not any(col.is_empty() for col in end.columns)
    fd14, *_ = _replay(FD14)
    rec = reveal_target_from_transition(fd14, end)
    assert rec["signature_key"] == "c11"


def test_3_all_root_legal_actions_are_enumerated():
    seed, *_ = _replay(FD14)
    info = enumerate_root_child_classes(seed)
    engine = [a for a in seed.enumerate_legal_actions(rules=MW_RULES) if a != ("deal",)]
    got = {tuple(a) for a in info["legal_actions"]}
    assert got == set(engine)
    assert got == EXPECTED_ROOT
    assert info["n_legal"] == 5


def test_4_root_children_deduplicate_correctly_under_symmetry():
    seed = _two_empty_plateau()
    info = enumerate_root_child_classes(seed)
    actions = {tuple(a) for a in info["legal_actions"]}
    assert (0, 1, 1) in actions and (0, 2, 1) in actions
    assert info["n_classes"] < info["n_legal"]
    pair = [
        rec
        for rec in info["classes"]
        if [0, 1, 1] in rec["equivalent_actions"] or [0, 2, 1] in rec["equivalent_actions"]
    ]
    assert len(pair) == 1
    assert [0, 1, 1] in pair[0]["equivalent_actions"]
    assert [0, 2, 1] in pair[0]["equivalent_actions"]


def test_5_search_domain_contains_only_plateau_states():
    seed = _plateau2()
    dummy = b"not-current"
    result = fd14_boundary_search(
        seed,
        current_fd13_symmetry=dummy,
        plateau_fd=2,
        slice_size=4,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
    )
    assert result.domain_violations == 0
    assert result.min_fd >= 1
    assert result.plateau_fd == 2
    assert result.max_foundations == 0 or result.foundation_witness is not None


def test_6_fd_preserving_children_are_enqueued():
    seed = _plateau2()
    result = fd14_boundary_search(
        seed,
        current_fd13_symmetry=b"x",
        plateau_fd=2,
        slice_size=8,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
    )
    assert result.unique >= 2
    assert result.expanded >= 1


def test_7_fd13_children_are_recorded_and_not_enqueued():
    seed = _plateau2()
    result = fd14_boundary_search(
        seed,
        current_fd13_symmetry=b"x",
        plateau_fd=2,
        slice_size=16,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
    )
    assert result.exit_edges >= 1
    assert result.exit_classes >= 1
    for rec in result.exits:
        assert rec["fd"] == 1
        end = seed.clone()
        replay_actions(end, [tuple(a) for a in rec["actions"]])
        assert face_down_count(end) == 1
        assert rec["class"] in (CURRENT_FD13_EXIT, NEW_FD13_EXIT)


def test_8_all_legal_tableau_moves_are_generated():
    seed = _plateau2()
    legal = engine_tableau_actions(seed)[0]
    info = enumerate_root_child_classes(seed)
    assert info["n_legal"] == len(legal)
    result = fd14_boundary_search(
        seed,
        current_fd13_symmetry=b"x",
        plateau_fd=2,
        slice_size=8,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
    )
    assert result.all_legal_tableau is True
    assert result.generated >= len(legal)
    source = inspect.getsource(fd14_boundary_search)
    assert "engine_tableau_actions" in source


def test_9_round_robin_rotates_among_live_frontiers():
    seed = _plateau2()
    result = fd14_boundary_search(
        seed,
        current_fd13_symmetry=b"x",
        plateau_fd=2,
        slice_size=1,
        max_unique=40,
        time_limit_s=5.0,
        rss_abort_mb=512,
    )
    assert result.n_root_classes >= 2
    prefix = result.rotation_prefix
    assert prefix
    if len(set(prefix[:4])) >= 2:
        assert prefix[0] != prefix[1] or len(prefix) == 1
    # With slice_size 1, consecutive expansions from a still-live pair should rotate.
    if len(prefix) >= 2 and result.n_root_classes >= 2:
        assert prefix[0] != prefix[1] or prefix.count(prefix[0]) < len(prefix)


def test_10_global_symmetry_seen_set_deduplicates_cross_frontier_convergence():
    seed = _plateau2()
    result = fd14_boundary_search(
        seed,
        current_fd13_symmetry=b"x",
        plateau_fd=2,
        slice_size=8,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
    )
    assert result.fresh_tt is True
    assert result.duplicate_skips >= 1


def test_11_no_strategic_score_affects_successor_or_frontier_priority():
    source = inspect.getsource(fd14_boundary_search)
    for banned in ("heapq", "target_fu", "landing", "empty_score", "beam", "MCTS"):
        assert banned not in source
    assert "engine_tableau_actions" in source
    assert "sort(" not in source
    assert "reversed(" in source


def test_12_exit_reveal_target_signature_is_identified_correctly():
    fd14, *_ = _replay(FD14)
    fd13, *_ = _replay(FD13)
    rec = reveal_target_from_transition(fd14, fd13)
    assert rec["signature_key"] == "c11"
    census = face_down_column_census(fd14)
    keys = {row["signature_key"] for row in census}
    assert "c11" in keys
    seed = _plateau2()
    result = fd14_boundary_search(
        seed,
        current_fd13_symmetry=b"x",
        plateau_fd=2,
        slice_size=16,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
    )
    assert result.reveal_target_counts
    assert any(result.reveal_target_counts.values())


def test_13_current_fd13_equality_uses_exact_symmetry_identity():
    fd13, *_ = _replay(FD13)
    key = post_stock_identity(fd13)
    swapped = permute_tableau_columns(fd13, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    assert pack_state(fd13) != pack_state(swapped)
    assert post_stock_identity(swapped) == key
    seed = _plateau2()
    child = seed.clone()
    apply_action(child, (0, 3, 2))
    current = post_stock_identity(child)
    result = fd14_boundary_search(
        seed,
        current_fd13_symmetry=current,
        plateau_fd=2,
        slice_size=16,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
    )
    if result.exit_classes:
        classes = {rec["class"] for rec in result.exits}
        if result.current_exit_classes:
            assert CURRENT_FD13_EXIT in classes


def test_14_new_fd13_exits_retain_concrete_replayable_paths():
    seed = _plateau2()
    result = fd14_boundary_search(
        seed,
        current_fd13_symmetry=b"x",
        plateau_fd=2,
        slice_size=16,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
    )
    assert result.new_exit_classes >= 1
    rec = result.new_exits[0]
    assert rec["replay_ok"] is True
    end = seed.clone()
    replay_actions(end, [tuple(a) for a in rec["actions"]])
    assert pack_state(end).hex() == rec["ordered_digest"]
    assert face_down_count(end) == 1
    if REPORT.exists():
        payload = json.loads(REPORT.read_text(encoding="utf-8"))
        first = payload.get("first_new_exit") or {}
        actions = first.get("full_actions") or []
        if actions:
            opening = _opening()
            walk = opening.clone()
            replay_actions(walk, [tuple(a) if a != ["deal"] else ("deal",) for a in actions])
            assert face_down_count(walk) == 13


def test_15_production_solver_remains_unchanged():
    end, *_ = _replay(FD14)
    assert pack_state(end)[:4] == b"SPK1"
    assert pack_search_identity(end) == pack_state(end)
    kwargs = dict(max_nodes=80, time_limit_s=2.0, depth_bands=(8,), max_pass=0, enable_audit=False)
    default = solve_progressive(end, **kwargs)
    explicit = solve_progressive(end, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert default.nodes == explicit.nodes
    source = inspect.getsource(solve_progressive)
    assert "post_stock_column_symmetry" not in source
    assert "fd14_boundary_search" not in source


def test_16_mobilityware_unrestricted_rules_contract_remains_green():
    assert MW_RULES.can_deal_into_empty is True
    end, actions, cost, opening = _replay(FD14)
    again = opening.clone()
    assert replay_actions(again, actions) == cost
    legal = [a for a in end.enumerate_legal_actions(rules=MW_RULES) if a != ("deal",)]
    assert legal
    apply_action(end.clone(), legal[0])
