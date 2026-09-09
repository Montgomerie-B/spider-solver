"""Best-reveal Deal probe v0.5: child-order exception only."""

from __future__ import annotations

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.rules import MW_RULES
from spider.simple_progressive_solver import (
    Tier,
    classify_tier,
    evaluate_deal_landings,
    solve_progressive,
)


def _ten(slots: dict[int, tuple], stock: list[Card] | None = None) -> SpiderState:
    cols = []
    for index in range(10):
        down, up = slots.get(index, ([], [Card("s", 13)]))
        cols.append(Column(list(down), list(up)))
    return SpiderState(cols, stock or [Card("c", rank) for rank in range(1, 11)])


def _uncover_state() -> SpiderState:
    return _ten(
        {
            0: ([Card("d", 9)], [Card("h", 6)]),
            1: ([], [Card("c", 7)]),
            2: ([Card("s", 8)], [Card("d", 5)]),
            3: ([], [Card("h", 6)]),
        }
    )


def test_1_strict_face_down_record_triggers_one_probe():
    result = solve_progressive(
        _uncover_state(),
        max_nodes=80,
        time_limit_s=2.0,
        depth_bands=(8,),
        max_pass=0,
        enable_best_reveal_deal_probe=True,
        enable_audit=False,
    )
    assert sum(result.stats.probe_fires) >= 1
    assert result.stats.probe_fires[0] >= 1


def test_2_equal_face_down_does_not_retrigger():
    result = solve_progressive(
        _uncover_state(),
        max_nodes=200,
        time_limit_s=2.0,
        depth_bands=(8,),
        max_pass=0,
        enable_best_reveal_deal_probe=True,
        enable_audit=False,
    )
    # Two sibling uncovers both leave one face-down: second is equal, not a new record.
    assert result.stats.reveal_records[0] >= 2
    assert result.stats.probe_fires[0] == 1


def test_3_worse_face_down_does_not_trigger():
    result = solve_progressive(
        _uncover_state(),
        max_nodes=80,
        time_limit_s=2.0,
        depth_bands=(8,),
        max_pass=0,
        enable_best_reveal_deal_probe=True,
        enable_audit=False,
    )
    assert all(event["pre_fd"] <= 2 for event in result.probe_events)


def test_4_records_independent_by_stock_depth():
    result = solve_progressive(
        _uncover_state(),
        max_nodes=300,
        time_limit_s=2.0,
        depth_bands=(12,),
        max_pass=3,
        enable_best_reveal_deal_probe=True,
        enable_audit=False,
    )
    assert result.stats.reveal_records[0] >= 1
    if result.stats.deals_executed:
        assert result.stats.reveal_records[1] >= 1 or result.stats.states_by_stock_dealt[1] >= 1


def test_5_probe_operates_in_pass_0_when_deal_is_tier_d():
    state = _uncover_state()
    landing = evaluate_deal_landings(state)
    assert landing is not None
    assert classify_tier(state, ("deal",), landing=landing) is Tier.D
    result = solve_progressive(
        state,
        max_nodes=80,
        time_limit_s=2.0,
        depth_bands=(8,),
        max_pass=0,
        enable_best_reveal_deal_probe=True,
        enable_audit=False,
    )
    assert result.stats.probe_fires[0] >= 1
    assert any(event["pass"] == 0 for event in result.probe_events)
    assert result.stats.deals_executed >= 1 or result.stats.probe_tt_suppressed[0] >= 1


def test_6_ordinary_deal_tier_unchanged():
    state = _uncover_state()
    landing = evaluate_deal_landings(state)
    assert classify_tier(state, ("deal",), landing=landing) is Tier.D
    assert MW_RULES.can_deal_into_empty is True


def test_7_probe_can_fire_with_empty_columns():
    state = _uncover_state()
    state.columns[9] = Column([], [])
    assert state.columns[9].is_empty()
    assert state.can_deal(MW_RULES)
    result = solve_progressive(
        state,
        max_nodes=80,
        time_limit_s=2.0,
        depth_bands=(8,),
        max_pass=0,
        enable_best_reveal_deal_probe=True,
        enable_audit=False,
    )
    assert result.stats.probe_fires[0] >= 1


def test_8_probe_fires_while_tableau_moves_remain():
    state = _uncover_state()
    assert state.enumerate_moves()
    assert ("deal",) in state.enumerate_legal_actions(MW_RULES)
    result = solve_progressive(
        state,
        max_nodes=80,
        time_limit_s=2.0,
        depth_bands=(8,),
        max_pass=0,
        enable_best_reveal_deal_probe=True,
        enable_audit=False,
    )
    events = [event for event in result.probe_events if event["dealt"] == 0]
    assert events
    assert events[0]["n_tableau"] >= 1


def test_9_probe_child_uses_ordinary_tt_coverage():
    result = solve_progressive(
        _uncover_state(),
        max_nodes=120,
        time_limit_s=2.0,
        depth_bands=(8,),
        max_pass=0,
        enable_best_reveal_deal_probe=True,
        enable_audit=False,
    )
    assert result.stats.tt_hits >= 0
    for event in result.probe_events:
        assert "tt_skip" in event
        assert "expanded" in event


def test_10_post_deal_search_remains_in_same_pass():
    result = solve_progressive(
        _uncover_state(),
        max_nodes=80,
        time_limit_s=2.0,
        depth_bands=(8,),
        max_pass=0,
        enable_best_reveal_deal_probe=True,
        enable_audit=False,
    )
    assert result.pass_reached == 0
    for event in result.probe_events:
        assert event["pass"] == 0


def test_11_feature_off_reproduces_ordinary_search():
    state = _uncover_state()
    kwargs = dict(
        max_nodes=100,
        time_limit_s=2.0,
        depth_bands=(8,),
        max_pass=0,
        enable_audit=False,
        enable_saturation=True,
    )
    off = solve_progressive(state, enable_best_reveal_deal_probe=False, **kwargs)
    default = solve_progressive(state, **kwargs)
    assert off.nodes == default.nodes
    assert off.stats.deals_executed == default.stats.deals_executed
    assert off.stats.unique_exact_states == default.stats.unique_exact_states
    assert off.stats.probe_fires == [0, 0, 0, 0, 0, 0]
    assert default.stats.probe_fires == [0, 0, 0, 0, 0, 0]
