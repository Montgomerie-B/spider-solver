"""Focused semantic gates for state-local strategic credit."""

import inspect
from dataclasses import fields, replace

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    StrategicCreditLevel,
    StrategicCreditPropagation,
    StrategicSearchNode,
    _apply_ordinary_child_credit_semantics,
    analyze_stage0_state,
    solve_anytime,
)
from spider.state_identity import canonical_state_key


def _node(credit: StrategicCreditLevel = StrategicCreditLevel.ESCAPE):
    state = SpiderState(
        [Column([], [Card("s", 13 - index % 4)]) for index in range(10)],
        [],
    )
    return StrategicSearchNode(
        10,
        state,
        7,
        ((0, 1, 1),),
        4,
        None,
        3,
        credit,
        None,
        analyze_stage0_state(state, spent_cost=7, incumbent_cost=None),
    )


def test_default_and_inherited_child_keep_parent_credit_three():
    assert (
        AnytimeControllerConfig().strategic_credit_propagation
        is StrategicCreditPropagation.INHERITED
    )
    child = _node()
    result = _apply_ordinary_child_credit_semantics(
        child,
        parent_credit=StrategicCreditLevel.ESCAPE,
        propagation=StrategicCreditPropagation.INHERITED,
    )
    assert result is child
    assert result.credit_level is StrategicCreditLevel.ESCAPE


def test_state_local_child_from_credit_three_starts_clean():
    child = _node()
    result = _apply_ordinary_child_credit_semantics(
        child,
        parent_credit=StrategicCreditLevel.ESCAPE,
        propagation=StrategicCreditPropagation.STATE_LOCAL,
    )
    assert result.credit_level is StrategicCreditLevel.CLEAN


def test_same_exact_state_widens_under_both_propagation_modes():
    node = _node(StrategicCreditLevel.SPECULATIVE)
    for propagation in StrategicCreditPropagation:
        config = AnytimeControllerConfig(strategic_credit_propagation=propagation)
        next_credit = StrategicCreditLevel(int(node.credit_level) + 1)
        widened = replace(node, node_id=11, credit_level=next_credit)
        assert config.max_credit_level >= widened.credit_level
        assert widened.credit_level is StrategicCreditLevel.ESCAPE
        assert canonical_state_key(widened.state) == canonical_state_key(node.state)
        assert widened.g == node.g
        assert widened.actions == node.actions
    source = inspect.getsource(solve_anytime)
    assert "widened = replace(node, node_id=uid, credit_level=next_credit)" in source


def test_state_local_reset_preserves_every_other_node_field():
    sentinels = {name: object() for name in (
        "analysis",
        "continuation_credit",
        "active_milestone",
        "target_grant_lineage",
        "whole_deal_schedule",
        "incoming_edge",
    )}
    child = replace(
        _node(),
        analysis=sentinels["analysis"],
        continuation_credit=sentinels["continuation_credit"],
        active_milestone=sentinels["active_milestone"],
        target_grant_lineage=sentinels["target_grant_lineage"],
        whole_deal_schedule=sentinels["whole_deal_schedule"],
        incoming_edge=sentinels["incoming_edge"],
        post_deal_obligations=("obligation",),
    )
    result = _apply_ordinary_child_credit_semantics(
        child,
        parent_credit=StrategicCreditLevel.ESCAPE,
        propagation=StrategicCreditPropagation.STATE_LOCAL,
    )
    for field in fields(StrategicSearchNode):
        if field.name == "credit_level":
            continue
        assert getattr(result, field.name) is getattr(child, field.name)
    assert result.credit_level is StrategicCreditLevel.CLEAN
