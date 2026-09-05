"""Later-phase resource-planner shadow: restart fidelity, forest bounds, novelty."""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.planner.whole_deal_scheduler import (
    build_whole_deal_blueprint,
    rebuild_whole_deal_schedule,
)


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "research" / "resource_excavation_later_phase_shadow_v0_1.py"
CONTROLLER = ROOT / "src" / "spider" / "planner" / "anytime_controller.py"
PLANNER = ROOT / "src" / "spider" / "planner" / "resource_excavation_planner.py"
DEAL = ROOT / "deals" / "4925153.txt"


def _mod():
    spec = importlib.util.spec_from_file_location("later_phase_shadow_v0_1", HARNESS)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _card(suit: str, rank: int) -> Card:
    return Card(suit, rank)


def _filled(slots: dict[int, list[Card]], *, face_down=None, empty=(), foundations=None) -> SpiderState:
    fd_map = face_down or {}
    cols = []
    for index in range(10):
        if index in empty:
            cols.append(Column([], []))
            continue
        up = slots.get(index)
        down = fd_map.get(index, [])
        if up is None and not down:
            cols.append(Column([], [_card("shdc"[index % 4], 13)]))
        else:
            cols.append(Column(list(down), list(up or [])))
    return SpiderState(cols, [], foundations or [])


def test_restart_equivalence_compares_generated_successor_signatures():
    mod = _mod()
    original = [
        {"kind": "ECONOMIC_PROJECT", "actions": [[0, 1, 1]], "cost": 1, "child": "aaaa"},
        {"kind": "RAW_DEAL", "actions": ["deal"], "cost": 0, "child": "bbbb"},
    ]
    same = mod.compare_successor_sets(original, original)
    assert same["generated_equal"] is True
    assert same["generated_multiset_equal"] is True
    different = mod.compare_successor_sets(
        original,
        [original[0], {"kind": "RAW_DEAL", "actions": ["deal"], "cost": 1, "child": "bbbb"}],
    )
    assert different["generated_multiset_equal"] is False


def test_frontier_root_selection_is_priority_then_digest_not_geometry():
    mod = _mod()
    candidates = [
        {
            "digest": "cccc",
            "restart_identity": "cccc",
            "priority": [2, 0],
            "path": [],
            "g": 4,
        },
        {
            "digest": "aaaa",
            "restart_identity": "aaaa",
            "priority": [1, 9],
            "path": [],
            "g": 9,
        },
        {
            "digest": "bbbb",
            "restart_identity": "bbbb",
            "priority": [1, 0],
            "path": [],
            "g": 1,
        },
        {
            "digest": "dddd",
            "restart_identity": "dddd",
            "priority": [0, 5],
            "path": [],
            "g": 8,
        },
        {
            "digest": "eeee",
            "restart_identity": "eeee",
            "priority": [3, 0],
            "path": [],
            "g": 0,
        },
    ]
    # Geometry-looking fields must not affect order; lowest priority tuple wins.
    selected = mod.select_frontier_roots(candidates, width=4)
    assert [row["digest"] for row in selected] == ["dddd", "bbbb", "aaaa", "cccc"]
    skipped = mod.select_frontier_roots(candidates, width=4, used={"dddd"})
    assert skipped[0]["digest"] == "bbbb"
    assert "plan_resource_excavation" not in mod.select_frontier_roots.__code__.co_names


def test_width_and_depth_bounds():
    mod = _mod()
    assert mod.WIDTH == 4
    assert mod.MAX_CONTINUATION_GENERATIONS == 6
    assert mod.GATE1_SAMPLE == 8


def test_trigger_classification_g1_to_g5():
    mod = _mod()
    empty = _filled({0: [_card("h", 5)]}, empty=(1,))
    g = mod.classify_triggers(empty)
    assert g["G1"] is True

    revealed = _filled({0: [_card("h", 10), _card("h", 9)]}, face_down={})
    # fillers are also fully revealed kings
    g2 = mod.classify_triggers(revealed)
    assert g2["G2"] is True

    creatable = _filled(
        {
            0: [_card("c", 5)],
            1: [_card("d", 6)],
        }
    )
    g3 = mod.classify_triggers(creatable)
    assert g3["G2"] is True
    assert g3["G3"] is True  # 5c onto 6d empties col 0

    foundation = _filled({0: [_card("s", 13)]}, foundations=[[_card("h", r) for r in range(13, 0, -1)]])
    g4 = mod.classify_triggers(foundation)
    assert g4["G4"] is True

    buried = _filled(
        {i: [_card("h", 5)] for i in range(10)},
        face_down={i: [_card("s", 4)] for i in range(10)},
    )
    g5 = mod.classify_triggers(buried)
    assert g5["G1"] is False
    assert g5["G2"] is False
    assert g5["G5"] is True  # min fd == 1
    deep = _filled(
        {i: [_card("h", 5)] for i in range(10)},
        face_down={i: [_card("s", 4), _card("s", 3)] for i in range(10)},
    )
    deep_g = mod.classify_triggers(deep)
    assert deep_g["G5"] is False
    assert deep_g["triggered"] is False


def test_ps_targets_are_scheduler_native_and_p_is_lead_first_edge():
    mod = _mod()
    cards = tuple(load_deal(DEAL))
    opening = SpiderState.from_cards(list(cards))
    rows = mod.enumerate_ps_targets(opening)
    assert rows[0]["class"] == "P"
    assert all(row["class"] in {"P", "S"} for row in rows)
    schedule = rebuild_whole_deal_schedule(opening, build_whole_deal_blueprint(opening))
    lead = schedule.lane_sequence_priority.lead
    assert rows[0]["suit"] == lead.suit
    assert (rows[0]["high"], rows[0]["low"]) == lead.missing_edges[0]
    native = {
        (lane.suit, high, low)
        for lane in schedule.lane_sequence_priority.ordered
        for high, low in lane.missing_edges
    }
    for row in rows:
        assert (row["suit"], row["high"], row["low"]) in native


def test_parent_not_expanded_is_never_novel():
    mod = _mod()
    assert (
        mod.classify_novelty("NOVEL_RESOURCE_SUCCESSOR", True, False)
        == "PARENT_NOT_EXPANDED"
    )
    assert (
        mod.classify_novelty("PARENT_NOT_EXPANDED", True, True)
        == "PARENT_NOT_EXPANDED"
    )


def test_nontrivial_novelty_requires_expanded_parent_and_nontrivial_plan():
    mod = _mod()
    assert (
        mod.classify_novelty("NOVEL_RESOURCE_SUCCESSOR", True, True)
        == "NONTRIVIAL_NOVEL_RESOURCE_SUCCESSOR"
    )
    assert (
        mod.classify_novelty("NOVEL_RESOURCE_SUCCESSOR", False, True)
        == "NOVEL_RESOURCE_SUCCESSOR"
    )
    assert (
        mod.classify_novelty("EXACT_DUPLICATE", True, True) == "EXACT_DUPLICATE"
    )


def test_resource_evaluation_is_not_invoked_during_corpus_generation():
    mod = _mod()
    source = inspect.getsource(mod.generate_continuation_corpus)
    assert "plan_resource_excavation" not in source
    assert "evaluate_resource" not in source
    audit_src = inspect.getsource(mod.audit_harvested)
    assert "plan_resource_excavation" in inspect.getsource(mod.evaluate_resource)
    assert "evaluate_resource" in audit_src


def test_controller_and_planner_remain_unwired():
    assert "resource_excavation" not in CONTROLLER.read_text(encoding="utf-8")
    text = PLANNER.read_text(encoding="utf-8")
    assert "MAX_OPERATORS = 8" in text


def test_later_phase_artefact_records_restart_fidelity_and_empty_geometry_corpus():
    import json

    payload = json.loads(
        (ROOT / "research" / "results" / "resource_excavation_later_phase_shadow_v0_1.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["restart_mode"] == "state_only"
    assert payload["fidelity"]
    assert all(
        row["classification"] == "STATE_ONLY_RESTART_EQUIVALENT" for row in payload["fidelity"]
    )
    assert payload["width"] == 4
    assert payload["max_continuation_generations"] == 6
    assert payload["generations_executed"] == 7
    assert payload["harvested_identities"] == []
    assert payload["earliest_triggers"] == {
        "G1": None,
        "G2": None,
        "G3": None,
        "G4": None,
        "G5": None,
    }
    assert payload["audit"]["P"]["NONTRIVIAL_NOVEL_RESOURCE_SUCCESSOR"] == 0
    assert payload["audit"]["S"]["NONTRIVIAL_NOVEL_RESOURCE_SUCCESSOR"] == 0
