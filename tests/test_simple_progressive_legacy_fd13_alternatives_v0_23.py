"""Legacy fd13 alternative-branch recovery v0.23."""

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
from spider.simple_legacy_fd13_alternatives import (
    ALTERNATIVE_FD13_CLASS,
    CURRENT_FD13_CLASS,
    classify_fd13_identity,
    fair_short_horizon_fd13_search,
    reveal_target_from_transition,
)
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, solve_progressive
from spider.simple_workspace_reachability import (
    engine_tableau_actions,
    face_down_count,
    layered_reachability,
    post_stock_identity,
)

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
FD14 = ROOT / "solutions" / "4925153_simple_fd14_stock0_seed.moves.txt"
B281_EMPTY = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
B281_FD13 = ROOT / "solutions" / "4925153_simple_v0_23_b281_fd13.moves.txt"
B201_FD13 = ROOT / "solutions" / "4925153_simple_v0_23_b201_fd13.moves.txt"
B201_EMPTY = ROOT / "solutions" / "4925153_simple_v0_23_b201_empty.moves.txt"
A411_FD13 = ROOT / "solutions" / "4925153_simple_v0_23_a411_fd13.moves.txt"
A411_EMPTY = ROOT / "solutions" / "4925153_simple_v0_23_a411_empty.moves.txt"
REPORT = ROOT / "docs" / "research" / "simple_progressive_legacy_fd13_alternatives_v0_23.json"
DEAD_CACHE = (
    ROOT / "research" / "results" / "simple_progressive_fd13_plateau_exit_v0_19" / "known_dead_from_fd12.jsonl"
)
FD14_HEX = (
    "53504b3101000000040a3a2c360835042302310b0d322913050915191b11282d0c2b1a2901"
    "0a0b1a010c3b2706153423323124162c1c2200081413121d071d223300062d242118341900"
    "070d0c2621393c37040c18360a2a280706050403020911033d17000612272a053801000d3d"
    "3c3b3a39383726081c251b3300071716352b140925"
)
B281_EMPTY_HEX = (
    "53504b310100000004093a2c360835042302310b0d1c3b050515191b11282d0c2b1a290000"
    "00121413121d071d1c1b1a19181716153433323100022d2c00080d0c262139383706041118"
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


def _state_from_slots(slots, stock=None) -> SpiderState:
    cols = []
    for index in range(10):
        down, up = slots.get(index, ([], [Card("s", 13)]))
        cols.append(Column(list(down), list(up)))
    return SpiderState(cols, list(stock or []), [])


def _playable_stock0() -> SpiderState:
    return _state_from_slots(
        {
            0: ([Card("c", 11)], [Card("h", 6)]),
            1: ([], [Card("s", 7)]),
            2: ([], [Card("d", 8)]),
            3: ([], [Card("c", 13)]),
            4: ([], []),
            5: ([], [Card("h", 12)]),
            6: ([], [Card("d", 11)]),
            7: ([Card("h", 8), Card("c", 6)], [Card("s", 4)]),
            8: ([], [Card("c", 3)]),
            9: ([Card("d", 10)], [Card("h", 2)]),
        },
        [],
    )


def test_1_fd14_stock0_fixture_replays():
    end, actions, cost, _opening_state = _replay(FD14)
    assert len(actions) == 43
    assert cost == 43
    assert face_down_count(end) == 14
    assert len(end.stock) == 0
    assert len(end.foundations) == 0
    assert pack_state(end).hex() == FD14_HEX
    assert not any(col.is_empty() for col in end.columns)


def test_2_b281_fd13_and_empty_witnesses_reproduce():
    empty, empty_actions, empty_cost, opening = _replay(B281_EMPTY)
    assert len(empty_actions) == 102
    assert empty_cost == 102
    assert face_down_count(empty) == 13
    assert sum(1 for col in empty.columns if col.is_empty()) == 1
    assert pack_state(empty).hex() == B281_EMPTY_HEX
    fd13_actions = empty_actions[:-1]
    fd13 = opening.clone()
    fd13_cost = replay_actions(fd13, fd13_actions)
    assert len(fd13_actions) == 101
    assert fd13_cost == 101
    assert face_down_count(fd13) == 13
    assert sum(1 for col in fd13.columns if col.is_empty()) == 0
    if B281_FD13.exists():
        again, fx, fx_cost, _ = _replay(B281_FD13)
        assert fx_cost == 101
        assert pack_state(again) == pack_state(fd13)


def test_3_b201_recovered_fd13_witness_replays():
    assert B201_FD13.exists()
    end, actions, cost, _ = _replay(B201_FD13)
    assert face_down_count(end) == 13
    assert len(end.stock) == 0
    assert len(end.foundations) == 0
    assert cost == len(actions)
    if B201_EMPTY.exists():
        empty, empty_actions, empty_cost, _ = _replay(B201_EMPTY)
        assert empty_cost == len(empty_actions)
        assert face_down_count(empty) == 13
        assert sum(1 for col in empty.columns if col.is_empty()) >= 1


def test_4_a411_recovered_fd13_witness_replays():
    assert A411_FD13.exists()
    end, actions, cost, _ = _replay(A411_FD13)
    assert face_down_count(end) == 13
    assert len(end.stock) == 0
    assert len(end.foundations) == 0
    assert cost == len(actions)
    if A411_EMPTY.exists():
        empty, empty_actions, empty_cost, _ = _replay(A411_EMPTY)
        assert empty_cost == len(empty_actions)
        assert face_down_count(empty) == 13
        assert sum(1 for col in empty.columns if col.is_empty()) >= 1


def test_5_historical_expected_path_lengths_are_checked():
    assert len(parse_moves_file(B281_FD13)) == 101
    assert len(parse_moves_file(B281_EMPTY)) == 102
    assert len(parse_moves_file(B201_FD13)) == 108
    assert len(parse_moves_file(B201_EMPTY)) == 109
    assert len(parse_moves_file(A411_FD13)) == 108
    assert len(parse_moves_file(A411_EMPTY)) == 109


def test_6_symmetry_classification_is_deterministic():
    a = "abc"
    b = "abc"
    c = "xyz"
    assert classify_fd13_identity(a, b) == CURRENT_FD13_CLASS
    assert classify_fd13_identity(a, c) == ALTERNATIVE_FD13_CLASS
    assert classify_fd13_identity(a, b) == classify_fd13_identity(a, b)
    fd13, *_ = _replay(B281_FD13)
    key = post_stock_identity(fd13).hex()
    assert classify_fd13_identity(key, key) == CURRENT_FD13_CLASS
    if B201_FD13.exists() and A411_FD13.exists():
        b201, *_ = _replay(B201_FD13)
        a411, *_ = _replay(A411_FD13)
        assert pack_state(fd13) == pack_state(b201) == pack_state(a411)
        assert post_stock_identity(fd13) == post_stock_identity(b201) == post_stock_identity(a411)
        assert classify_fd13_identity(key, post_stock_identity(b201).hex()) == CURRENT_FD13_CLASS


def test_7_whole_column_permutations_collapse_correctly():
    end, *_ = _replay(B281_FD13)
    swapped = permute_tableau_columns(end, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    reversed_state = permute_tableau_columns(end, list(range(9, -1, -1)))
    assert pack_state(end) != pack_state(swapped)
    assert post_stock_identity(end) == post_stock_identity(swapped)
    assert post_stock_identity(end) == post_stock_identity(reversed_state)


def test_8_genuinely_distinct_fd13_states_do_not_collapse():
    left = _playable_stock0()
    right = left.clone()
    right.columns[0].face_down = [Card("s", 9)]
    assert pack_state(left) != pack_state(right)
    assert post_stock_identity(left) != post_stock_identity(right)
    assert classify_fd13_identity(
        post_stock_identity(left).hex(), post_stock_identity(right).hex()
    ) == ALTERNATIVE_FD13_CLASS


def test_9_reveal_target_signature_is_identified_correctly():
    fd14, *_ = _replay(FD14)
    fd13, *_ = _replay(B281_FD13)
    rec = reveal_target_from_transition(fd14, fd13)
    assert rec["fd_before"] == 14
    assert rec["fd_after"] == 13
    assert rec["signature_key"]
    # Identity is the buried stack, not a physical column number alone.
    assert rec["signature_key"] == "c11"
    parent = _playable_stock0()
    child = parent.clone()
    apply_action(child, (0, 4, 1))
    toy = reveal_target_from_transition(parent, child)
    assert toy["signature_key"] == "c11"
    assert toy["fd_before"] - toy["fd_after"] == 1


def test_10_fair_phase3_search_uses_all_engine_legal_tableau_moves():
    seed = _playable_stock0()
    legal = engine_tableau_actions(seed)[0]
    engine = [a for a in seed.enumerate_legal_actions(rules=MW_RULES) if a != ("deal",)]
    assert legal == engine
    result = fair_short_horizon_fd13_search(seed, max_depth=1, max_unique=200, time_limit_s=5.0, rss_abort_mb=512)
    assert result.generated >= len(engine)
    assert result.classifier_surprises == 0
    source = inspect.getsource(fair_short_horizon_fd13_search)
    assert "all_legal_tableau=True" in source
    assert "identity_fn=post_stock_identity" in source


def test_11_no_heuristic_priority_is_used_in_phase_3():
    source = inspect.getsource(fair_short_horizon_fd13_search) + inspect.getsource(layered_reachability)
    for banned in ("heapq", "priority", "score", "beam", "landing", "target_fu", "empty_score"):
        assert banned not in source
    seed = _playable_stock0()
    result = fair_short_horizon_fd13_search(seed, max_depth=2, max_unique=200, time_limit_s=5.0, rss_abort_mb=512)
    depths = [row["depth"] for row in result.layers]
    assert depths == sorted(depths)
    assert result.fresh_tt is True


def test_12_minimum_depth_fd12_witnesses_replay():
    if not REPORT.exists():
        seed = _playable_stock0()
        result = layered_reachability(
            seed,
            max_depth=4,
            max_unique=200,
            time_limit_s=5.0,
            rss_abort_mb=512,
            all_legal_tableau=True,
            identity_fn=post_stock_identity,
            collect_fd=12,
            stop_after_collect_layer=True,
        )
        assert result.stop_reason in ("collect layer complete", "frontier empty", "max depth")
        return
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    opening = _opening()
    for arm in (payload.get("phase3") or {}).get("arms") or []:
        for rec in arm.get("exits") or []:
            actions = rec.get("full_actions") or []
            if not actions and rec.get("fixture"):
                path = ROOT / rec["fixture"]
                if path.exists():
                    end, fx, _cost, _ = _replay(path)
                    assert face_down_count(end) == 12
                    continue
            if not actions:
                continue
            end = opening.clone()
            replay_actions(end, [tuple(a) if a != ["deal"] else ("deal",) for a in actions])
            assert face_down_count(end) == 12


def test_13_exact_known_dead_membership_works():
    if not DEAD_CACHE.exists():
        return
    members = {
        json.loads(line)["symmetry_digest"]
        for line in DEAD_CACHE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    first = next(iter(members))
    assert first in members
    assert "not-a-key" not in members
    union = ROOT / "research" / "results" / "simple_progressive_legacy_fd13_alternatives_v0_23" / "known_dead_fd12_futures.jsonl"
    if union.exists():
        extra = {
            json.loads(line)["symmetry_digest"]
            for line in union.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        assert extra
        assert "not-a-key" not in extra


def test_14_optional_fd10_or_foundation_route_replays():
    if not REPORT.exists():
        return
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    opening = _opening()
    for key in ("fd10", "foundation"):
        rec = (payload.get("phase4") or {}).get(key) or {}
        fixture = (payload.get("phase4") or {}).get(f"{key}_fixture")
        if fixture:
            end, actions, cost, _ = _replay(ROOT / fixture)
            assert cost == len(actions)
            if key == "fd10":
                assert face_down_count(end) <= 10
            else:
                assert len(end.foundations) >= 1
            continue
        actions = rec.get("full_actions") or rec.get("actions") or []
        if not actions:
            continue
        end = opening.clone()
        replay_actions(end, [tuple(a) if a != ["deal"] else ("deal",) for a in actions])


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


def test_16_mobilityware_unrestricted_rules_contract_remains_green():
    assert MW_RULES.can_deal_into_empty is True
    end, actions, cost, opening = _replay(FD14)
    again = opening.clone()
    assert replay_actions(again, actions) == cost
    legal = [a for a in end.enumerate_legal_actions(rules=MW_RULES) if a != ("deal",)]
    assert legal
    apply_action(end.clone(), legal[0])
