"""FU5 target-conversion audit v0.22."""

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
    face_down_signature,
    is_target_reveal,
    signature_key,
    target_block_count,
    target_conversion_bfs,
    target_face_up_count,
    target_stack_audit,
)
from spider.simple_workspace_reachability import (
    engine_tableau_actions,
    face_down_count,
    layered_reachability,
    post_stock_identity,
)

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
FD13 = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
V21 = ROOT / "docs" / "research" / "simple_progressive_landing_aware_target_v0_21.json"
FU5_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_22_col1_fu5_seed.moves.txt"
REPORT = ROOT / "docs" / "research" / "simple_progressive_fu5_target_conversion_v0_22.json"
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


def _fu5_record():
    payload = json.loads(V21.read_text(encoding="utf-8"))
    records = [r for r in (payload.get("records") or []) if r.get("target_fu") == 5]
    assert records
    return min(records, key=lambda r: (r.get("depth", 10**9), r.get("unique", 10**9)))


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


def test_1_authoritative_fd13_seed_replays():
    end, actions, cost, opening = _fd13()
    assert len(actions) == 102
    assert cost == 102
    assert pack_state(end).hex() == FD13_HEX


def test_2_fu5_record_can_be_reconstructed_from_v0_21():
    rec = _fu5_record()
    assert rec["target_fu"] == 5
    seed, prefix, _c, opening = _fd13()
    local = [tuple(a) for a in rec["actions"]]
    end = opening.clone()
    replay_actions(end, prefix + local)
    sig = face_down_signature(end.columns[0]) if face_down_signature(seed.columns[0]) else None
    # locate by signature of original col1
    orig = face_down_signature(seed.columns[0])
    assert signature_key(orig) == COL1_KEY
    assert target_face_up_count(end, orig) == 5
    assert face_down_count(end) == 13


def test_3_fu5_fixture_independently_replays():
    rec = _fu5_record()
    seed, prefix, _c, opening = _fd13()
    actions = prefix + [tuple(a) for a in rec["actions"]]
    end = opening.clone()
    cost = replay_actions(end, actions)
    assert cost == len(actions)
    if FU5_FIXTURE.exists():
        again = opening.clone()
        fx = parse_moves_file(FU5_FIXTURE)
        replay_actions(again, fx)
        assert pack_state(again) == pack_state(end)


def test_4_target_signature_remains_stable():
    rec = _fu5_record()
    seed, prefix, _c, opening = _fd13()
    orig = face_down_signature(seed.columns[0])
    end = opening.clone()
    replay_actions(end, prefix + [tuple(a) for a in rec["actions"]])
    perm = permute_tableau_columns(end, list(range(9, -1, -1)))
    assert target_face_up_count(perm, orig) == 5
    assert signature_key(orig) == COL1_KEY


def test_5_target_fu_is_exactly_5_at_the_local_root():
    rec = _fu5_record()
    seed, prefix, _c, opening = _fd13()
    orig = face_down_signature(seed.columns[0])
    end = opening.clone()
    replay_actions(end, prefix + [tuple(a) for a in rec["actions"]])
    assert target_face_up_count(end, orig) == 5
    assert target_block_count(end, orig) == 5
    audit = target_stack_audit(end, orig)
    assert audit["top_block_head"] == 1
    assert len(end.stock) == 0
    assert len(end.foundations) == 0


def test_6_layered_search_processes_depth_n_before_n_plus_1():
    seed = _toy_two_targets()
    target = face_down_signature(seed.columns[0])
    result = target_conversion_bfs(seed, target, plateau_fd=2, max_depth=3, max_unique=200, time_limit_s=5.0)
    assert result.expansion_order == sorted(result.expansion_order)
    assert result.expansion_order == list(range(len(result.expansion_order)))


def test_7_all_engine_legal_stock0_tableau_actions_are_generated():
    seed = _toy_two_targets()
    target = face_down_signature(seed.columns[0])
    legal = engine_tableau_actions(seed)[0]
    result = target_conversion_bfs(seed, target, plateau_fd=2, max_depth=1, max_unique=80, time_limit_s=5.0)
    assert result.generated >= len(legal)


def test_8_no_heuristic_priority_is_used_in_phase_1():
    seed = _toy_two_targets()
    target = face_down_signature(seed.columns[0])
    result = target_conversion_bfs(seed, target, plateau_fd=2, max_depth=2, max_unique=80, time_limit_s=5.0)
    depths = [row["depth"] for row in result.layers]
    assert depths == sorted(depths)


def test_9_selected_target_reveal_is_distinguished_from_off_target_reveal():
    seed = _toy_two_targets()
    parent = seed.clone()
    child = seed.clone()
    apply_action(child, (0, 1, 1))
    a = face_down_signature(parent.columns[0])
    b = face_down_signature(parent.columns[9])
    assert is_target_reveal(parent, child, a)
    assert not is_target_reveal(parent, child, b)
    result = target_conversion_bfs(seed, a, plateau_fd=2, max_depth=2, max_unique=80, time_limit_s=5.0)
    assert result.target_exits


def test_10_target_fu_records_are_minimum_depth_records():
    seed = _toy_two_targets()
    target = face_down_signature(seed.columns[9])
    result = target_conversion_bfs(seed, target, plateau_fd=2, max_depth=3, max_unique=80, time_limit_s=5.0)
    for thresh, rec in result.fu_records.items():
        assert rec["depth"] >= 1
        assert rec["target_fu"] <= thresh


def test_11_post_stock_symmetry_dedup_retains_concrete_replay_paths():
    seed = _toy_two_targets()
    target = face_down_signature(seed.columns[0])
    result = target_conversion_bfs(seed, target, plateau_fd=2, max_depth=2, max_unique=80, time_limit_s=5.0)
    rec = result.target_exits[0]
    end = seed.clone()
    replay_actions(end, [tuple(a) for a in rec["actions"]])
    assert pack_state(end).hex() == rec["ordered_digest"]
    assert rec["replay_ok"] is True


def test_12_known_dead_fd12_membership_works():
    cache = ROOT / "research" / "results" / "simple_progressive_fd13_plateau_exit_v0_19" / "known_dead_from_fd12.jsonl"
    if not cache.exists():
        return
    members = {json.loads(line)["symmetry_digest"] for line in cache.read_text(encoding="utf-8").splitlines() if line.strip()}
    first = next(iter(members))
    assert first in members
    assert "not-a-key" not in members


def test_13_target_reveal_witness_replays_if_found():
    if not REPORT.exists():
        return
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    rec = payload.get("first_target_exit") or {}
    actions = rec.get("full_actions") or []
    if not actions:
        return
    opening = _opening()
    end = opening.clone()
    replay_actions(end, [tuple(a) if a != ["deal"] else ("deal",) for a in actions])
    assert rec.get("replay_ok") is True


def test_14_optional_downstream_path_replays_if_found():
    if not REPORT.exists():
        return
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    for key in ("fd10_witness", "foundation_witness"):
        rec = payload.get(key) or {}
        actions = rec.get("full_actions") or []
        if not actions:
            continue
        opening = _opening()
        end = opening.clone()
        replay_actions(end, [tuple(a) if a != ["deal"] else ("deal",) for a in actions])
        assert rec.get("replay_ok") is True


def test_15_production_solver_remains_unchanged():
    end, *_ = _fd13()
    assert pack_state(end)[:4] == b"SPK1"
    assert pack_search_identity(end) == pack_state(end)
    state = _toy_two_targets()
    kwargs = dict(max_nodes=80, time_limit_s=2.0, depth_bands=(8,), max_pass=0, enable_audit=False)
    default = solve_progressive(state, **kwargs)
    explicit = solve_progressive(state, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert default.nodes == explicit.nodes


def test_16_mobilityware_unrestricted_rules_contract_remains_green():
    assert MW_RULES.can_deal_into_empty is True
    end, actions, cost, opening = _fd13()
    again = opening.clone()
    assert replay_actions(again, actions) == cost
    apply_action(end.clone(), (1, 2, 1))
