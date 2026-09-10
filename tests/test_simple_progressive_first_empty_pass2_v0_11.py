"""First-empty Pass-2 workspace experiment v0.11."""

from __future__ import annotations

from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_state
from spider.rules import MW_RULES
from spider.simple_post_deal_audit import (
    census_legal_by_tier,
    describe_legal_actions,
)
from spider.simple_progressive_solver import (
    CoverageTT,
    TT_MODE_DEPTH_AWARE,
    TT_MODE_FIRST_VISIT,
    Tier,
    apply_action,
    classify_tier,
    enumerate_actions,
    ordered_actions,
    solve_progressive,
)

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
PREFIX = ROOT / "solutions" / "4925153_simple_fd14_stock0_seed.moves.txt"
FIXTURE = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"


def _opening() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL)))


def _seed():
    assert FIXTURE.exists(), "fd13/empty1 seed fixture missing"
    actions = parse_moves_file(FIXTURE)
    opening = _opening()
    seed = opening.clone()
    cost = replay_actions(seed, actions)
    return seed, actions, cost, opening


def _state_from_slots(slots: dict[int, tuple[list[Card], list[Card]]], stock=None) -> SpiderState:
    cols = []
    for index in range(10):
        down, up = slots.get(index, ([], [Card("s", 13)]))
        cols.append(Column(list(down), list(up)))
    return SpiderState(cols, list(stock or []))


def _uncover_state() -> SpiderState:
    return _state_from_slots(
        {
            0: ([Card("d", 9)], [Card("h", 6)]),
            1: ([], [Card("c", 7)]),
            2: ([Card("s", 8)], [Card("d", 5)]),
            3: ([], [Card("h", 6)]),
        },
        [Card("c", rank) for rank in range(1, 11)],
    )


def test_1_fd13_empty1_seed_replays_from_original_deal():
    seed, actions, cost, opening = _seed()
    again = opening.clone()
    paid = replay_actions(again, actions)
    assert paid == cost
    assert pack_state(again) == pack_state(seed)
    assert len(actions) >= 44


def test_2_seed_has_fd_13():
    seed, _a, _c, _o = _seed()
    assert sum(len(col.face_down) for col in seed.columns) == 13


def test_3_seed_has_exactly_one_empty_column():
    seed, _a, _c, _o = _seed()
    assert sum(1 for col in seed.columns if col.is_empty()) == 1


def test_4_seed_has_stock_0_and_foundations_0():
    seed, _a, _c, _o = _seed()
    assert len(seed.stock) == 0
    assert len(seed.foundations) == 0
    assert seed.can_deal(MW_RULES) is False


def test_5_legal_root_census_from_engine():
    seed, _a, _c, _o = _seed()
    engine = list(seed.enumerate_legal_actions(rules=MW_RULES))
    rows = describe_legal_actions(seed)
    census = census_legal_by_tier(seed)
    assert len(rows) == len(engine) == census["legal"]
    assert census["legal"] == census["a"] + census["b"] + census["c"] + census["d"]


def test_6_pass1_permits_a_and_b_only():
    seed, _a, _c, _o = _seed()
    allowed = ordered_actions(seed, 1, prep_ply=0, stats=None)
    assert allowed
    assert all(int(classify_tier(seed, action)) <= int(Tier.B) for action in allowed)


def test_7_pass2_permits_a_b_c():
    seed, _a, _c, _o = _seed()
    allowed = ordered_actions(seed, 2, prep_ply=0, stats=None)
    tiers = {int(classify_tier(seed, action)) for action in allowed}
    assert int(Tier.A) in tiers or int(Tier.B) in tiers
    census = census_legal_by_tier(seed)
    if census["c"] > 0:
        assert int(Tier.C) in tiers
    assert all(tier <= int(Tier.C) for tier in tiers)


def test_8_d_remains_excluded_at_pass2():
    seed, _a, _c, _o = _seed()
    allowed = ordered_actions(seed, 2, prep_ply=0, stats=None)
    assert all(int(classify_tier(seed, action)) != int(Tier.D) for action in allowed)


def test_9_ordinary_non_king_move_to_empty_is_tier_c():
    state = _state_from_slots(
        {
            0: ([], [Card("h", 8), Card("s", 7)]),
            1: ([], []),
        }
    )
    action = (0, 1, 1)
    assert classify_tier(state, action) == Tier.C
    assert state.columns[1].is_empty()
    assert action in enumerate_actions(state)


def test_10_join_breaking_move_is_tier_c():
    state = _state_from_slots(
        {
            0: ([], [Card("h", 9), Card("h", 8)]),
            1: ([], [Card("s", 9)]),
        }
    )
    action = (0, 1, 1)
    assert classify_tier(state, action) == Tier.C
    assert action in enumerate_actions(state)


def test_11_first_visit_behaviour_unchanged():
    tt = CoverageTT(first_visit=True)
    key = b"once"
    assert not tt.skip(key, 1, 80)
    tt.mark_start(key, 1, 80)
    assert tt.skip(key, 1, 80)
    assert tt.skip(key, 1, 2000)
    depth = CoverageTT(first_visit=False)
    depth.mark_done(b"need-deeper", 1, 80)
    assert depth.skip(b"need-deeper", 1, 80)
    assert not depth.skip(b"need-deeper", 1, 320)
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


def test_12_forced_tier_c_branch_does_not_change_legality():
    seed, prefix, _cost, opening = _seed()
    rows = [row for row in describe_legal_actions(seed) if row["tier"] == int(Tier.C)]
    if not rows:
        return
    action = tuple(rows[0]["action"])
    child = seed.clone()
    apply_action(child, action)
    engine_child = list(child.enumerate_legal_actions(rules=MW_RULES))
    pass2 = ordered_actions(child, 2, prep_ply=0, stats=None)
    assert all(act in engine_child for act in pass2)
    combined = list(prefix) + [action]
    end = opening.clone()
    replay_actions(end, combined)
    assert pack_state(end) == pack_state(child)


def test_13_hard_progress_combined_witness_replays():
    seed, actions, cost, opening = _seed()
    end = opening.clone()
    paid = replay_actions(end, actions)
    assert paid == cost
    assert sum(len(col.face_down) for col in end.columns) == 13
    assert sum(1 for col in end.columns if col.is_empty()) == 1
    reports = ROOT / "docs" / "research" / "simple_progressive_first_empty_pass2_v0_11.json"
    if not reports.exists():
        return
    import json

    payload = json.loads(reports.read_text(encoding="utf-8"))
    for arm_name in ("pass1", "pass2"):
        arm = payload.get(arm_name) or {}
        for event in arm.get("progress_events") or []:
            replay = event.get("combined_replay") or {}
            if event.get("kind") in (
                "fd_le_12",
                "fd_le_11",
                "second_empty",
                "run_ge_10",
                "run_ge_11",
                "run_ge_12",
                "complete_ka_run",
                "first_foundation",
            ):
                assert replay.get("ok") is True
    route = ROOT / "solutions" / "4925153_simple_v0_11_first_foundation.moves.txt"
    if route.exists():
        fnd_actions = parse_moves_file(route)
        fnd_state = opening.clone()
        replay_actions(fnd_state, fnd_actions)
        assert len(fnd_state.foundations) >= 1
        assert len(fnd_state.stock) == 0


def test_14_production_default_solve_progressive_unchanged():
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
    explicit = solve_progressive(
        state, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs
    )
    assert default.nodes == explicit.nodes
    assert default.stats.tt_mode == TT_MODE_DEPTH_AWARE
    assert default.stats.first_visit_skips == 0
    assert default.pass_reached == explicit.pass_reached
    assert default.stats.empty_into_moves == explicit.stats.empty_into_moves
    no_stop = solve_progressive(state, **kwargs)
    assert no_stop.stop_reason != "first empty"


def test_15_mobilityware_unrestricted_rules_contract_remains():
    assert MW_RULES.can_deal_into_empty is True
    seed_prefix = parse_moves_file(PREFIX)
    opening = _opening()
    fd14 = opening.clone()
    replay_actions(fd14, seed_prefix)
    assert len(fd14.stock) == 0
    seed, _a, _c, _o = _seed()
    for action in enumerate_actions(seed):
        child = seed.clone()
        apply_action(child, action, rules=MW_RULES)
        pack_state(child)
