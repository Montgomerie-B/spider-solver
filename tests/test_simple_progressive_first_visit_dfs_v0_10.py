"""First-visit exact DFS v0.10: heuristic coverage, default TT unchanged."""

from __future__ import annotations

from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_state
from spider.rules import MW_RULES
from spider.simple_post_deal_audit import canonical_root_children, census_legal_by_tier
from spider.simple_progressive_solver import (
    CoverageTT,
    TT_MODE_DEPTH_AWARE,
    TT_MODE_FIRST_VISIT,
    apply_action,
    classify_tier,
    enumerate_actions,
    ordered_actions,
    solve_progressive,
)

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
FIXTURE = ROOT / "solutions" / "4925153_simple_fd14_stock0_seed.moves.txt"
EXPECTED_HEX = (
    "53504b3101000000040a3a2c360835042302310b0d322913050915191b11282d0c2b1a2901"
    "0a0b1a010c3b2706153423323124162c1c2200081413121d071d223300062d242118341900"
    "070d0c2621393c37040c18360a2a280706050403020911033d17000612272a053801000d3d"
    "3c3b3a39383726081c251b3300071716352b140925"
)


def _opening() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL)))


def _seed():
    actions = parse_moves_file(FIXTURE)
    opening = _opening()
    seed = opening.clone()
    cost = replay_actions(seed, actions)
    return seed, actions, cost, opening


def _uncover_state() -> SpiderState:
    cols = []
    slots = {
        0: ([Card("d", 9)], [Card("h", 6)]),
        1: ([], [Card("c", 7)]),
        2: ([Card("s", 8)], [Card("d", 5)]),
        3: ([], [Card("h", 6)]),
    }
    for index in range(10):
        down, up = slots.get(index, ([], [Card("s", 13)]))
        cols.append(Column(list(down), list(up)))
    return SpiderState(cols, [Card("c", rank) for rank in range(1, 11)])


def test_1_first_visit_expands_canonical_state_once():
    tt = CoverageTT(first_visit=True)
    key = b"once"
    assert not tt.skip(key, 1, 80)
    tt.mark_start(key, 1, 80)
    assert tt.skip(key, 1, 80)
    assert tt.first_visit is True


def test_2_later_arrival_with_greater_remaining_still_skipped():
    tt = CoverageTT(first_visit=True)
    key = b"shallow-then-deep"
    tt.mark_start(key, 1, 10)
    assert tt.skip(key, 1, 2000)
    assert tt.skip(key, 0, 2000)


def test_3_depth_aware_still_reopens_when_appropriate():
    tt = CoverageTT(first_visit=False)
    key = b"need-deeper"
    tt.mark_done(key, 1, 80)
    assert tt.skip(key, 1, 80)
    assert not tt.skip(key, 1, 320)


def test_4_default_mode_is_depth_aware():
    assert TT_MODE_DEPTH_AWARE == "depth_aware"
    result = solve_progressive(
        _uncover_state(),
        max_nodes=40,
        time_limit_s=2.0,
        depth_bands=(8,),
        max_pass=0,
        enable_audit=False,
    )
    assert result.stats.tt_mode == TT_MODE_DEPTH_AWARE
    tt = CoverageTT()
    assert tt.first_visit is False


def test_5_first_visit_is_explicitly_non_proof():
    assert "NO proof" in CoverageTT.__doc__
    tt = CoverageTT(first_visit=True)
    assert tt.first_visit is True
    result = solve_progressive(
        _uncover_state(),
        max_nodes=40,
        time_limit_s=2.0,
        depth_bands=(8,),
        max_pass=0,
        tt_mode=TT_MODE_FIRST_VISIT,
        enable_audit=False,
    )
    assert result.stats.tt_mode == TT_MODE_FIRST_VISIT
    assert result.stats.tt_reopens == 0


def test_6_exact_identity_unchanged():
    seed, actions, _cost, opening = _seed()
    a = pack_state(seed)
    b = pack_state(seed)
    assert a == b
    again = opening.clone()
    replay_actions(again, actions)
    assert pack_state(again) == a


def test_7_ab_permissions_unchanged():
    seed, _a, _c, _o = _seed()
    allowed = ordered_actions(seed, 1, prep_ply=0, stats=None)
    assert any(int(classify_tier(seed, action)) == 0 for action in allowed)
    assert any(int(classify_tier(seed, action)) == 1 for action in allowed)
    assert all(int(classify_tier(seed, action)) <= 1 for action in allowed)


def test_8_cd_remain_excluded():
    seed, _a, _c, _o = _seed()
    census = census_legal_by_tier(seed)
    assert census["tableau_c"] == 0
    assert census["tableau_d"] == 0


def test_9_seed_and_all_root_actions_replay():
    seed, prefix, prefix_cost, opening = _seed()
    assert pack_state(seed).hex() == EXPECTED_HEX
    groups = canonical_root_children(seed)
    assert len(groups) == 5
    for group in groups:
        combined = list(prefix) + [group["representative"]]
        end = opening.clone()
        cost = replay_actions(end, combined)
        child = seed.clone()
        apply_action(child, group["representative"])
        assert pack_state(end) == pack_state(child)
        assert cost == prefix_cost + replay_actions(seed.clone(), [group["representative"]])


def test_10_combined_treatment_witness_replays():
    seed, prefix, _cost, opening = _seed()
    group = next(g for g in canonical_root_children(seed) if g["tier"] == 1)
    child = seed.clone()
    apply_action(child, group["representative"])
    result = solve_progressive(
        child,
        max_nodes=40,
        time_limit_s=2.0,
        depth_bands=(16,),
        start_pass=1,
        max_pass=1,
        tt_mode=TT_MODE_FIRST_VISIT,
        enable_audit=False,
        enable_post_deal_audit=True,
        enable_saturation=False,
        prep_ply=0,
        target_foundations=1,
        max_depth=32,
    )
    local = list(result.actions)
    combined = list(prefix) + [group["representative"]] + local
    end = opening.clone()
    replay_actions(end, combined)
    assert len(end.stock) == 0


def test_11_production_defaults_unchanged():
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
    assert default.stats.first_visit_skips == 0
    assert default.stats.probe_fires == explicit.stats.probe_fires
    assert MW_RULES.can_deal_into_empty is True
    assert enumerate_actions(state)
