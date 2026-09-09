"""Root-branch sweep v0.9: isolate each seed root action under matched A+B budgets."""

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


def test_1_exact_fd14_seed_reproduces():
    seed, actions, cost, opening = _seed()
    assert len(actions) == 43
    assert cost == 43
    assert pack_state(seed).hex() == EXPECTED_HEX
    again = opening.clone()
    replay_actions(again, actions)
    assert pack_state(again).hex() == EXPECTED_HEX


def test_2_legal_root_census_is_one_a_four_b():
    seed, _actions, _cost, _opening = _seed()
    census = census_legal_by_tier(seed)
    assert census["tableau_a"] == 1
    assert census["tableau_b"] == 4
    assert census["tableau_c"] == 0
    assert census["tableau_d"] == 0
    groups = canonical_root_children(seed)
    assert len(groups) == 5
    tiers = [group["tier"] for group in groups]
    assert tiers.count(0) == 1
    assert tiers.count(1) == 4


def test_3_each_root_action_is_legal():
    seed, _actions, _cost, _opening = _seed()
    actions = enumerate_actions(seed)
    assert len(actions) == 5
    for action in actions:
        child = seed.clone()
        apply_action(child, action)
        assert pack_state(child) != pack_state(seed)


def test_4_each_combined_seed_plus_root_replays():
    seed, prefix, prefix_cost, opening = _seed()
    for action in enumerate_actions(seed):
        combined = list(prefix) + [action]
        end = opening.clone()
        cost = replay_actions(end, combined)
        local = seed.clone()
        apply_action(local, action)
        assert pack_state(end) == pack_state(local)
        assert cost == prefix_cost + replay_actions(seed.clone(), [action])


def test_5_branch_arms_use_fresh_tt():
    seed, _actions, _cost, _opening = _seed()
    action = canonical_root_children(seed)[0]["representative"]
    child = seed.clone()
    apply_action(child, action)
    kwargs = dict(
        max_nodes=25,
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
    a = solve_progressive(child, **kwargs)
    b = solve_progressive(child, **kwargs)
    assert a.stats.unique_exact_states == b.stats.unique_exact_states
    assert a.nodes == b.nodes


def test_6_branch_arms_start_at_pass_1():
    seed, _actions, _cost, _opening = _seed()
    action = next(
        group["representative"]
        for group in canonical_root_children(seed)
        if group["tier"] == 1
    )
    child = seed.clone()
    apply_action(child, action)
    result = solve_progressive(
        child,
        max_nodes=30,
        time_limit_s=2.0,
        depth_bands=(16,),
        start_pass=1,
        max_pass=1,
        enable_audit=False,
        enable_post_deal_audit=True,
        enable_saturation=False,
        prep_ply=0,
        target_foundations=1,
    )
    assert result.stats.band_pass_reports
    assert all(row["pass"] == 1 for row in result.stats.band_pass_reports)


def test_7_only_ab_actions_permitted():
    seed, _actions, _cost, _opening = _seed()
    allowed = ordered_actions(seed, 1, prep_ply=0, stats=None)
    assert allowed
    assert all(int(classify_tier(seed, action)) <= 1 for action in allowed)
    assert any(int(classify_tier(seed, action)) == 0 for action in allowed)
    assert any(int(classify_tier(seed, action)) == 1 for action in allowed)


def test_8_cd_remain_excluded():
    seed, _actions, _cost, _opening = _seed()
    census = census_legal_by_tier(seed)
    assert census["tableau_c"] == 0
    assert census["tableau_d"] == 0
    allowed = ordered_actions(seed, 1, prep_ply=0, stats=None)
    assert all(int(classify_tier(seed, action)) <= 1 for action in allowed)


def test_9_root_isolation_does_not_alter_successor_legality():
    seed, _actions, _cost, _opening = _seed()
    before = list(enumerate_actions(seed))
    groups = canonical_root_children(seed)
    after = list(enumerate_actions(seed))
    assert before == after
    child = seed.clone()
    apply_action(child, groups[0]["representative"])
    assert enumerate_actions(seed) == before
    assert pack_state(seed).hex() == EXPECTED_HEX


def test_10_canonical_equivalent_children_are_detected():
    from unittest.mock import patch

    seed, _actions, _cost, _opening = _seed()
    groups = canonical_root_children(seed)
    digests = [group["key_hex"] for group in groups]
    assert len(digests) == 5
    assert len(set(digests)) == 5
    assert all(group["equivalent"] is False for group in groups)
    action = enumerate_actions(seed)[0]
    with patch(
        "spider.simple_progressive_solver.enumerate_actions",
        return_value=[action, action],
    ):
        dup = canonical_root_children(seed)
    assert len(dup) == 1
    assert dup[0]["equivalent"] is True
    assert len(dup[0]["actions"]) == 2


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
    explicit = solve_progressive(state, start_pass=0, **kwargs)
    assert default.nodes == explicit.nodes
    assert default.stats.probe_fires == explicit.stats.probe_fires
    assert default.actions == explicit.actions
    assert MW_RULES.can_deal_into_empty is True
