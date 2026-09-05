"""Continuation-credit fidelity: frontier observation and credit identity."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from dataclasses import replace

from spider.planner.anytime_controller import StrategicCreditLevel, StrategicSearchNode


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "research" / "continuation_credit_fidelity_v0_1.py"
CONTROLLER = ROOT / "src" / "spider" / "planner" / "anytime_controller.py"
PLANNER = ROOT / "src" / "spider" / "planner" / "resource_excavation_planner.py"
DEAL = ROOT / "deals" / "4925153.txt"
RESULT = ROOT / "research" / "results" / "continuation_credit_fidelity_v0_1.json"


def _mod():
    spec = importlib.util.spec_from_file_location("credit_fidelity_v0_1", HARNESS)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_static_audit_declares_previous_forest_dropped_credit():
    mod = _mod()
    audit = mod.static_audit()
    assert audit["widening_located"] is True
    assert audit["widening_uses_record_transition"] is False
    assert audit["widening_uses_tt_admit"] is False
    assert audit["raw_fallback_credit"] == 4
    assert audit["verdict"] == "PREVIOUS_FOREST_DROPPED_CREDIT"


def test_continuation_identity_distinguishes_same_tableau_at_different_credits():
    mod = _mod()
    assert mod.continuation_identity("abcd", 0) != mod.continuation_identity("abcd", 4)
    assert mod.continuation_identity("abcd", 1) == "abcd|c1"


def test_priority_strip_drops_only_trailing_node_id():
    mod = _mod()
    assert mod.strip_priority((0, 1, "lead", 7)) == [0, 1, "lead"]
    assert mod.strip_priority((1, 2, 3)) == [1, 2]


def test_strategic_frontier_item_recognition():
    mod = _mod()
    dummy = StrategicSearchNode(
        1,
        SpiderState([Column([], [Card("s", 13)]) for _ in range(10)], []),
        0,
        (),
        None,
        None,
        0,
        StrategicCreditLevel.CLEAN,
        None,
    )
    assert mod.is_strategic_frontier_item(((0,), 1, dummy)) is True
    assert mod.is_strategic_frontier_item((1, 2)) is False
    assert mod.is_strategic_frontier_item("not a node") is False


def test_widening_origin_separated_from_transition():
    mod = _mod()
    obs = mod.FrontierObserver()
    dummy = StrategicSearchNode(
        1,
        SpiderState([Column([], [Card("s", 13)]) for _ in range(10)], []),
        5,
        (),
        None,
        None,
        2,
        StrategicCreditLevel.CLEAN,
        None,
    )
    obs.last_popped = {
        "digest": mod._digest(dummy.state),
        "credit": 0,
        "g": 5,
        "depth": 2,
    }
    widened = replace(
        dummy,
        credit_level=StrategicCreditLevel.POSITIVE_INVESTMENT,
        node_id=9,
    )
    assert obs._origin_for_push(widened) == "credit_widening"
    other = replace(dummy, g=6, depth=3, credit_level=StrategicCreditLevel.CLEAN)
    assert obs._origin_for_push(other) == "transition"


def test_passive_frontier_observation_does_not_change_two_expansion_search():
    mod = _mod()
    cards = tuple(load_deal(DEAL))
    opening = SpiderState.from_cards(list(cards))
    shadow = mod._load_shadow()
    import spider.planner.anytime_controller as controller

    def run(observe: bool):
        import random

        random.seed(0)
        config = shadow._production_config(expansions=2)
        observer = None
        if observe:
            observer = mod.FrontierObserver()
            observer.install()
        try:
            result = controller.solve_anytime(opening.clone(), cards, None, config)
        finally:
            if observer is not None:
                observer.restore()
        return result

    a = run(False)
    b = run(True)
    assert a.stop_reason == b.stop_reason
    assert a.strategic_expansions == b.strategic_expansions
    assert a.status == b.status
    assert a.telemetry.generated == b.telemetry.generated
    assert a.telemetry.retained == b.telemetry.retained
    assert dict(sorted(a.telemetry.successor_kinds.items())) == dict(
        sorted(b.telemetry.successor_kinds.items())
    )
    assert controller._record_transition.__name__ == "_record_transition"


def test_clean_reset_compare_detects_kind_loss():
    mod = _mod()
    original = [
        {"kind": "RAW_TABLEAU_MOVE", "actions": [[0, 1, 1]], "cost": 1, "child": "aa"},
        {"kind": "RAW_DEAL", "actions": ["deal"], "cost": 0, "child": "bb"},
    ]
    clean = [{"kind": "RAW_DEAL", "actions": ["deal"], "cost": 0, "child": "bb"}]
    cmp = mod.compare_sigs(original, clean)
    assert cmp["equal"] is False
    assert "RAW_TABLEAU_MOVE" in cmp["missing_from_right"]


def test_exact_credit_reconstruction_matches_observed_clean_expansion():
    mod = _mod()
    cards = tuple(load_deal(DEAL))
    opening = SpiderState.from_cards(list(cards))
    result, observer, _live = mod.run_observed(opening, cards, expansions=2)
    assert result.strategic_expansions == 2
    rec = observer.expanded[0]
    assert rec["credit"] == 0
    original = observer.generated[rec["identity"]]
    replay = mod.reconstruct_and_generate(
        observer.states[(rec["digest"], rec["credit"])],
        cards,
        credit=0,
        g=rec["g"],
    )
    assert mod.compare_sigs(original, replay)["equal"] is True


def test_raw_move_classification_does_not_require_planner():
    mod = _mod()
    cols = [Column([], [Card("s", 13)]) for _ in range(10)]
    cols[0] = Column([Card("h", 9)], [Card("c", 5)])
    cols[1] = Column([], [Card("d", 6)])
    state = SpiderState(cols, [])
    anatomy = mod.classify_raw_move(state, (0, 1, 1))
    assert anatomy["flips_face_down_immediately"] is True
    assert anatomy["reduces_total_face_down"] is True
    assert "resource_excavation" not in CONTROLLER.read_text(encoding="utf-8")
    assert "MAX_OPERATORS = 8" in PLANNER.read_text(encoding="utf-8")


def test_artefact_records_dropped_credit_and_unexpanded_widening():
    import json

    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    assert payload["static"]["verdict"] == "PREVIOUS_FOREST_DROPPED_CREDIT"
    assert payload["expanded_credit_histogram"]["0"] == 25
    assert payload["widened"]["live"] == 25
    assert payload["widened"]["expanded"] == 0
    assert payload["raw_fallback"]["credit4_nodes"] == 0
    assert payload["c_counts"]["C3_omitted_widened_pushes"] == 25
