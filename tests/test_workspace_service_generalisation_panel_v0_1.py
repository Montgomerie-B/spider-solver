"""Focused gates for the frozen workspace-service generalisation panel."""

from __future__ import annotations

import inspect
import json
from collections import Counter

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.state_identity import canonical_state_key

import workspace_opportunity_service_lane_v0_1 as service
import workspace_service_generalisation_panel_v0_1 as experiment
import workspace_service_panel_v0_1 as panel


EXPECTED_SEEDS = {
    "P1": 12858661474814657433,
    "P2": 17037747615682187675,
    "P3": 3511299091343336564,
    "P4": 6782576163807013305,
    "P5": 5347712971617699974,
    "P6": 323099503300668895,
    "P7": 1454277106742966837,
    "P8": 719590085337095586,
    "P9": 11599763336346334964,
}

EXPECTED_DIGESTS = {
    "P0": "c06565c127ccbc7a",
    "P1": "4985999558684dba",
    "P2": "4d67539f2e5b6949",
    "P3": "116e16a36fb97d8d",
    "P4": "d8ce5c96ef47d786",
    "P5": "2a38b6842db9491d",
    "P6": "a76f1d0eaa918477",
    "P7": "3e1bac697f14bb19",
    "P8": "c30d6533e8e80ff6",
    "P9": "b280e024873cb6de",
}


def _definition():
    return json.loads(panel.PANEL_PATH.read_text(encoding="utf-8"))


def test_deterministic_panel_generation():
    for panel_entry, seed in EXPECTED_SEEDS.items():
        first = panel.generate_cards(seed)
        second = panel.generate_cards(seed)
        frozen = tuple(load_deal(panel.FIXTURE_DIR / f"{panel_entry}.txt"))
        assert first == second == frozen


def test_exact_sha256_seed_derivation():
    assert {
        panel_entry: panel.derive_seed(panel_entry)
        for panel_entry in EXPECTED_SEEDS
    } == EXPECTED_SEEDS


def test_valid_104_card_two_deck_composition():
    expected = Counter(
        {(suit, rank): 2 for suit in panel.SUIT_ORDER for rank in range(1, 14)}
    )
    for panel_entry in EXPECTED_SEEDS:
        cards = tuple(load_deal(panel.FIXTURE_DIR / f"{panel_entry}.txt"))
        assert len(cards) == 104
        assert Counter((card.suit, card.rank) for card in cards) == expected


def test_standard_tableau_and_stock_geometry():
    for panel_entry in EXPECTED_SEEDS:
        cards = tuple(load_deal(panel.FIXTURE_DIR / f"{panel_entry}.txt"))
        state = panel.validate_cards(cards)
        assert [len(col.face_down) for col in state.columns] == [5] * 4 + [4] * 6
        assert [len(col.face_up) for col in state.columns] == [1] * 10
        assert len(state.stock) == 50


def test_opening_digests_are_frozen_and_deterministic():
    definition = _definition()
    actual = {entry["panel_entry"]: entry["opening_digest"] for entry in definition["entries"]}
    assert actual == EXPECTED_DIGESTS
    assert panel.build_panel_definition() == definition


def test_panel_freeze_is_independent_of_search_results():
    definition = _definition()
    rendered = inspect.getsource(panel.build_panel_definition)
    assert "result" not in rendered and "solve" not in rendered
    assert "runs" not in definition and "verdict" not in definition
    assert [entry["panel_entry"] for entry in definition["entries"]] == [
        f"P{index}" for index in range(10)
    ]


def test_control_and_treatment_receive_identical_initial_states():
    for entry in _definition()["entries"]:
        cards = experiment.load_entry_cards(entry)
        control = SpiderState.from_cards(list(cards))
        treatment = SpiderState.from_cards(list(cards))
        assert canonical_state_key(control) == canonical_state_key(treatment)
        assert experiment.common.digest(control) == entry["opening_digest"]


def test_alternating_arm_order_is_exact():
    definition = _definition()
    assert [entry["run_order"] for entry in definition["entries"]] == [
        list(panel.arm_order(index)) for index in range(10)
    ]
    assert definition["entries"][0]["run_order"] == ["WORKSPACE_SERVICE_1", "CONTROL"]
    assert definition["entries"][1]["run_order"] == ["CONTROL", "WORKSPACE_SERVICE_1"]


def test_workspace_policy_remains_one_representative_at_n8():
    lane = service.WorkspaceServiceLane(enabled=True)
    assert service.SERVICE_INTERVAL == experiment.CONFIG["workspace_service_interval"] == 8
    assert lane.interval == 8 and lane.current_node_id is None and lane.max_outstanding == 0
    assert experiment.service.WorkspaceServiceLane is service.WorkspaceServiceLane


def test_operation_remains_benchmark_neutral():
    policy_source = inspect.getsource(service.workspace_class) + inspect.getsource(
        service.legal_empty_creating_moves
    )
    assert "4925153" not in policy_source
    assert "digest" not in policy_source
    assert "P0" not in policy_source
    assert "Card(" not in policy_source
    runner_source = inspect.getsource(experiment.run_arm)
    assert "workspace_class" not in runner_source
    assert "fixture_path" not in runner_source
