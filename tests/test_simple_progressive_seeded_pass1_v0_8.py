"""Seeded Pass-1 continuation v0.8: local A+B from the fd-14 stock-empty seed."""

from __future__ import annotations

from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_state
from spider.rules import MW_RULES
from spider.simple_post_deal_audit import census_legal_by_tier
from spider.simple_progressive_solver import (
    Tier,
    apply_action,
    classify_tier,
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
    assert FIXTURE.exists(), "seed fixture missing"
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


def test_1_exact_fd14_seed_prefix_replays():
    seed, actions, cost, opening = _seed()
    assert len(actions) == 43
    assert cost == 43
    assert pack_state(seed).hex() == EXPECTED_HEX
    again = opening.clone()
    paid = replay_actions(again, actions)
    assert paid == 43
    assert pack_state(again).hex() == EXPECTED_HEX


def test_2_seed_has_stock_0():
    seed, _actions, _cost, _opening = _seed()
    assert len(seed.stock) == 0
    assert seed.can_deal(MW_RULES) is False


def test_3_seed_has_fd_14():
    seed, _actions, _cost, _opening = _seed()
    assert sum(len(col.face_down) for col in seed.columns) == 14


def test_4_seed_has_foundations_0():
    seed, _actions, _cost, _opening = _seed()
    assert len(seed.foundations) == 0


def test_5_local_pass0_permits_only_a():
    seed, _actions, _cost, _opening = _seed()
    allowed = ordered_actions(seed, 0, prep_ply=0, stats=None)
    assert allowed
    assert all(int(classify_tier(seed, action)) == 0 for action in allowed)
    census = census_legal_by_tier(seed)
    assert census["tableau_a"] == 1
    assert census["tableau_b"] == 4


def test_6_local_pass1_permits_a_and_b():
    seed, _actions, _cost, _opening = _seed()
    allowed = ordered_actions(seed, 1, prep_ply=0, stats=None)
    tiers = {int(classify_tier(seed, action)) for action in allowed}
    assert 0 in tiers
    assert 1 in tiers
    assert census_legal_by_tier(seed)["tableau_a"] + census_legal_by_tier(seed)["tableau_b"] == len(
        allowed
    )


def test_7_cd_excluded_in_treatment():
    seed, _actions, _cost, _opening = _seed()
    allowed = ordered_actions(seed, 1, prep_ply=0, stats=None)
    assert all(int(classify_tier(seed, action)) <= 1 for action in allowed)
    census = census_legal_by_tier(seed)
    assert census["tableau_c"] == 0
    assert census["tableau_d"] == 0
    assert census["deal_legal"] is False


def test_8_local_pass1_starts_at_seed_not_original_deal():
    seed, _actions, _cost, _opening = _seed()
    seed_key = pack_state(seed)
    result = solve_progressive(
        seed,
        max_nodes=40,
        time_limit_s=2.0,
        depth_bands=(16,),
        start_pass=1,
        max_pass=1,
        enable_audit=False,
        enable_post_deal_audit=True,
        enable_best_reveal_deal_probe=False,
        enable_saturation=False,
        prep_ply=0,
        target_foundations=1,
    )
    assert result.stats.band_pass_reports
    assert all(row["pass"] == 1 for row in result.stats.band_pass_reports)
    assert seed_key in result.post_deal_audit.encounters
    first = result.post_deal_audit.encounters[seed_key][0]
    assert first["expanded"] is True
    assert first["depth"] == 0
    assert first["pass"] == 1


def test_9_local_search_uses_fresh_tt():
    seed, _actions, _cost, _opening = _seed()
    kwargs = dict(
        max_nodes=30,
        time_limit_s=2.0,
        depth_bands=(8,),
        start_pass=1,
        max_pass=1,
        enable_audit=False,
        enable_post_deal_audit=False,
        enable_saturation=False,
        prep_ply=0,
        target_foundations=1,
    )
    a = solve_progressive(seed, **kwargs)
    b = solve_progressive(seed, **kwargs)
    assert a.nodes == b.nodes
    assert a.stats.unique_exact_states == b.stats.unique_exact_states
    assert a.stats.unique_exact_states >= 1


def test_10_each_root_tier_b_child_is_legal_and_replayable():
    seed, _actions, _cost, _opening = _seed()
    allowed = ordered_actions(seed, 1, prep_ply=0, stats=None)
    b_moves = [action for action in allowed if classify_tier(seed, action) is Tier.B]
    assert len(b_moves) == 4
    for action in b_moves:
        child = seed.clone()
        apply_action(child, action)
        assert pack_state(child) != pack_state(seed)
        again = seed.clone()
        replay_actions(again, [action])
        assert pack_state(again) == pack_state(child)


def test_11_concatenated_prefix_plus_continuation_replays():
    seed, prefix, prefix_cost, opening = _seed()
    allowed = ordered_actions(seed, 1, prep_ply=0, stats=None)
    b_moves = [action for action in allowed if classify_tier(seed, action) is Tier.B]
    continuation = [b_moves[0]]
    combined = list(prefix) + continuation
    end = opening.clone()
    cost = replay_actions(end, combined)
    assert cost == prefix_cost + replay_actions(seed.clone(), continuation)
    local = seed.clone()
    replay_actions(local, continuation)
    assert pack_state(end) == pack_state(local)


def test_12_default_solve_progressive_unchanged():
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
    explicit = solve_progressive(state, start_pass=0, **kwargs)
    assert default.nodes == explicit.nodes
    assert default.stats.deals_executed == explicit.stats.deals_executed
    assert default.stats.probe_fires == explicit.stats.probe_fires
    assert default.min_face_down == explicit.min_face_down
    assert default.actions == explicit.actions
    assert MW_RULES.can_deal_into_empty is True
