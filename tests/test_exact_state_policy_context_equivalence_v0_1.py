"""Focused gates for the exact-state policy-context equivalence audit."""

from __future__ import annotations

import dataclasses
import inspect

import pytest

from spider.deal import load_deal
from spider.engine import SpiderState
import spider.planner.anytime_controller as controller
from spider.state_identity import canonical_state_key

import common_priority_schema_ab_v0_1 as common
import exact_state_policy_context_equivalence_v0_1 as audit


@pytest.fixture(scope="module")
def captured():
    cards = tuple(load_deal(common.DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    config = audit._production_config()
    observer = audit.reproduce_pair(opening, cards, config)
    cheap = observer.cheap_node
    parent = observer.empty_parent
    edge = observer.return_successor
    assert cheap is not None and parent is not None and edge is not None
    returned = audit.materialize_returned_context(
        parent, edge, observer._empty_final_successors, opening, config
    )
    definitions = {
        "A1": (cheap, 7),
        "A2": (cheap, 9),
        "B1": (returned, 9),
        "B2": (returned, 7),
    }
    prepared = {
        label: audit.prepare_variant(context, g, cards, config)[0]
        for label, (context, g) in definitions.items()
    }
    pipelines = {
        label: audit.generate_pipeline(node, cards, config)
        for label, node in prepared.items()
    }
    return {
        "cards": cards,
        "config": config,
        "observer": observer,
        "cheap": cheap,
        "returned": returned,
        "prepared": prepared,
        "pipelines": pipelines,
    }


def test_naturally_captured_nodes_have_identical_exact_game_state(captured):
    cheap = captured["cheap"]
    returned = captured["returned"]
    assert common.digest(cheap.state) == audit.CHEAP_ANCHOR
    assert common.digest(returned.state) == audit.CHEAP_ANCHOR
    assert canonical_state_key(cheap.state) == canonical_state_key(returned.state)
    assert cheap.g == 7 and returned.g == 9


def test_g_normalisation_recomputes_stage0_and_stage1_cost_facts(captured):
    for label, expected in {"A1": 7, "A2": 9, "B1": 9, "B2": 7}.items():
        proof = audit._analysis_g_proof(captured["prepared"][label], expected)
        assert proof["all_match"]
    assert captured["prepared"]["A1"].analysis is not captured["prepared"]["A2"].analysis
    assert captured["prepared"]["B1"].stage0 is not captured["prepared"]["B2"].stage0


def test_primary_successor_comparison_does_not_use_tt_or_frontier(captured):
    source = inspect.getsource(audit.generate_pipeline)
    assert "Transposition" not in source and ".admit(" not in source
    assert "heapq" not in audit.generate_pipeline.__code__.co_names
    assert "solve_anytime" not in audit.generate_pipeline.__code__.co_names
    assert captured["observer"].empty_tt_pipeline == []


def test_resource_excavation_planner_is_not_invoked(captured):
    assert captured["observer"].resource_planner_calls == 0
    assert "resource_excavation" not in inspect.getsource(controller)
    assert "plan_resource_excavation" not in inspect.getsource(audit.generate_pipeline)


def test_equal_g_coverage_comparison_is_deterministic(captured):
    expected = captured["pipelines"]
    for label in ("A2", "B1"):
        rerun = audit.generate_pipeline(
            captured["prepared"][label], captured["cards"], captured["config"]
        )
        assert rerun["coverage_fingerprint"] == expected[label]["coverage_fingerprint"]
    assert expected["A2"]["coverage_fingerprint"] == expected["B1"]["coverage_fingerprint"]
    assert expected["A1"]["coverage_fingerprint"] == expected["B2"]["coverage_fingerprint"]


def test_benchmark_digests_validate_capture_but_do_not_change_generation():
    for function in (
        audit._production_config,
        audit.prepare_variant,
        audit.generate_pipeline,
        audit.materialize_returned_context,
    ):
        source = inspect.getsource(function)
        assert audit.CHEAP_ANCHOR not in source
        assert audit.EMPTY_ANCHOR not in source
        assert "4925153" not in source


def test_production_defaults_and_sources_remain_unchanged(captured):
    default_before = controller.AnytimeControllerConfig()
    audit_config = captured["config"]
    default_after = controller.AnytimeControllerConfig()
    assert dataclasses.asdict(default_before) == dataclasses.asdict(default_after)
    assert audit_config.frontier_priority_schema.value == "COMMON_STAGE0"
    assert audit_config.strategic_credit_propagation.value == "STATE_LOCAL"
    assert audit.BASE_SHA == "740adabf7fc96bd48ecf7f9753cde12de4eacd12"
