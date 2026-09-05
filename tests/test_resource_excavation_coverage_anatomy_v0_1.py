"""Coverage-anatomy diagnostics for the isolated resource excavation planner."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.planner.resource_excavation_planner import (
    CampaignTarget,
    ResourcePlanResult,
    plan_resource_excavation,
)
from spider.planner.whole_deal_scheduler import (
    build_whole_deal_blueprint,
    rebuild_whole_deal_schedule,
)

from test_resource_excavation_planner_v0_1_rework import rework_positive_fixture
from test_resource_excavation_planner_v0_1_workspace import (
    workspace_already_exposed_fixture,
    workspace_invest_fixture,
)


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "research" / "resource_excavation_coverage_anatomy_v0_1.py"
RESULT = ROOT / "research" / "results" / "resource_excavation_coverage_anatomy_v0_1.json"
CONTROLLER = ROOT / "src" / "spider" / "planner" / "anytime_controller.py"
PLANNER = ROOT / "src" / "spider" / "planner" / "resource_excavation_planner.py"
DEAL = ROOT / "deals" / "4925153.txt"


def _mod():
    spec = importlib.util.spec_from_file_location("coverage_anatomy_v0_1", HARNESS)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _card(suit: str, rank: int) -> Card:
    return Card(suit, rank)


def _filled(slots: dict[int, list[Card]], *, face_down: dict[int, list[Card]] | None = None) -> SpiderState:
    fd_map = face_down or {}
    cols = []
    for index in range(10):
        up = slots.get(index)
        down = fd_map.get(index, [])
        if up is None and not down:
            cols.append(Column([], [_card("shdc"[index % 4], 13)]))
        else:
            cols.append(Column(list(down), list(up or [])))
    return SpiderState(cols, [])


def test_create_blocker_face_down_is_source_has_face_down():
    mod = _mod()
    state = _filled(
        {i: [_card("h", 5)] for i in range(10)},
        face_down={i: [_card("s", 4)] for i in range(10)},
    )
    funnel = mod.diagnose_create(state, CampaignTarget("c", 12, 11))
    assert funnel["qualifies"] is False
    assert funnel["nearest_miss"] == "SOURCE_HAS_FACE_DOWN"
    assert funnel["zero_face_down_sources"] == 0


def test_create_blocker_not_one_movable_run():
    mod = _mod()
    state = _filled({i: [_card("h", 10), _card("c", 9)] for i in range(10)})
    funnel = mod.diagnose_create(state, CampaignTarget("s", 12, 11))
    assert funnel["qualifies"] is False
    assert funnel["nearest_miss"] == "NOT_ONE_MOVABLE_RUN"
    assert funnel["zero_face_down_sources"] == 10
    assert funnel["whole_movable_packets"] == 0


def test_invest_without_empty_is_blocked_by_no_idle_empty():
    mod = _mod()
    state, target = workspace_invest_fixture()
    assert sum(1 for col in state.columns if col.is_empty()) == 0
    funnel = mod.diagnose_invest(state, target)
    assert funnel["blocker"] == "BLOCKED_BY_NO_IDLE_EMPTY"
    assert funnel["qualifies"] is False


def test_reserve_taxonomy_no_high_and_threat():
    mod = _mod()
    no_high = _filled({0: [_card("c", 5)]})
    none = mod.diagnose_reserve(no_high, CampaignTarget("s", 12, 11))
    assert none["blocker"] == "NO_CAMPAIGN_HIGH_TOP"

    high_only = _filled({7: [_card("s", 12)], 0: [_card("c", 13)]})
    idle = mod.diagnose_reserve(high_only, CampaignTarget("s", 12, 11))
    assert idle["blocker"] == "HIGH_TOP_NO_CONSUMING_THREAT"

    threatened = _filled(
        {
            7: [_card("s", 12)],
            0: [_card("h", 11)],
        }
    )
    threat = mod.diagnose_reserve(threatened, CampaignTarget("s", 12, 11))
    assert threat["blocker"] in {"RESERVATION_GENERATED", "HIGH_TOP_NO_CONSUMING_THREAT"}
    if threat["qualifies"]:
        assert threat["raw"] >= 1


def test_realise_taxonomy_low_missing_then_realisable():
    mod = _mod()
    buried, target = workspace_invest_fixture()
    buried_funnel = mod.diagnose_realise(buried, target)
    assert buried_funnel["blocker"] == "CAMPAIGN_LOW_NOT_EXPOSED"

    exposed, target = workspace_already_exposed_fixture()
    ready = mod.diagnose_realise(exposed, target)
    assert ready["blocker"] == "REALISABLE"
    assert ready["qualifies"] is True


def test_rework_taxonomy_identifies_positive_fixture():
    mod = _mod()
    state, target = rework_positive_fixture()
    funnel = mod.diagnose_rework(state, target)
    assert funnel["same_suit_joins"] >= 1
    assert funnel["qualifies"] is True
    assert funnel["blocker"] == "QUALIFYING_REWORK"


def test_pla_targets_are_scheduler_native_and_deterministic():
    mod = _mod()
    cards = tuple(load_deal(DEAL))
    opening = SpiderState.from_cards(list(cards))
    first = mod.enumerate_pla_targets(opening)
    second = mod.enumerate_pla_targets(opening)
    assert first == second
    assert first, "opening state must have a lead missing edge"
    assert first[0]["class"] == "P"
    classes = [row["class"] for row in first]
    assert classes == sorted(classes, key=lambda label: {"P": 0, "L": 1, "A": 2}[label])

    schedule = rebuild_whole_deal_schedule(opening, build_whole_deal_blueprint(opening))
    native = set()
    for lane in schedule.lane_sequence_priority.ordered:
        for high, low in lane.missing_edges:
            native.add((lane.suit, high, low))
    for row in first:
        assert (row["suit"], row["high"], row["low"]) in native


def test_pla_order_does_not_depend_on_resource_plan_success():
    mod = _mod()
    cards = tuple(load_deal(DEAL))
    opening = SpiderState.from_cards(list(cards))
    rows = mod.enumerate_pla_targets(opening)
    # Enumeration must not consult plan_resource_excavation.
    assert "plan_resource_excavation" not in mod.enumerate_pla_targets.__code__.co_names
    # Later L/A rows stay in scheduler order even if P would realise.
    p = rows[0]
    later = [row for row in rows if row["class"] != "P"]
    target = CampaignTarget(p["suit"], p["high"], p["low"])
    plan_resource_excavation(opening, target)
    again = mod.enumerate_pla_targets(opening)
    assert [row for row in again if row["class"] != "P"] == later


def test_diagnostic_traversal_matches_real_planner_on_fixtures():
    mod = _mod()
    for state, target in (
        workspace_invest_fixture(),
        workspace_already_exposed_fixture(),
        rework_positive_fixture(),
    ):
        plan = plan_resource_excavation(state, target)
        diag = mod.diagnostic_traverse(state, target)
        assert diag["result"] == plan.result.value
        assert diag["operators"] == [kind.value for kind in plan.operators]
        assert diag["visited"] == plan.visited


def test_overlap_classification_matches_shadow_definitions():
    mod = _mod()
    children = [
        {"child": "aaaa", "cost": 4, "actions": [[0, 1, 1]]},
        {"child": "bbbb", "cost": 3, "actions": [[2, 3, 1]]},
    ]

    def row(end: str, cost: int, result="REALISED_CAMPAIGN_PROGRESS", first=None):
        return {
            "end_digest": end,
            "cost": cost,
            "result": result,
            "first_action": first if first is not None else [0, 1, 1],
        }

    assert mod.classify_overlap(row("aaaa", 4), children, expanded=True)["class"] == "EXACT_DUPLICATE"
    assert mod.classify_overlap(row("aaaa", 6), children, expanded=True)["class"] == "DOMINATED_DUPLICATE"
    assert mod.classify_overlap(row("aaaa", 2), children, expanded=True)["class"] == "BETTER_DUPLICATE"
    novel = mod.classify_overlap(row("cccc", 5, first=[9, 8, 1]), children, expanded=True)
    assert novel["class"] == "NOVEL_RESOURCE_SUCCESSOR"
    assert novel["first_action_known"] is False
    assert novel["complete_terminal_known"] is False
    assert (
        mod.classify_overlap(row("cccc", 5), children, expanded=False)["class"]
        == "PARENT_NOT_EXPANDED"
    )


def test_controller_and_planner_sources_untouched_by_this_branch():
    assert "resource_excavation" not in CONTROLLER.read_text(encoding="utf-8")
    text = PLANNER.read_text(encoding="utf-8")
    assert "MAX_OPERATORS = 8" in text
    assert "MAX_UNRESOLVED_OBLIGATIONS = 2" in text


def test_anatomy_artefact_records_create_face_down_bottleneck():
    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    assert payload["recapture_identities_match"] is True
    assert payload["captured_states"] == 58
    assert payload["anatomy_aggregate"]["states_with_any_empty"] == 0
    assert payload["anatomy_aggregate"]["states_with_zero_fd_column"] == 0
    assert payload["create_gateway_funnel"]["SOURCE_HAS_FACE_DOWN"] == 580
    assert payload["primary_operator_funnel"]["CREATE_WORKSPACE"]["raw"] == 0
    assert payload["primary_operator_funnel"]["INVEST_WORKSPACE"]["raw"] == 0
    assert payload["target_class_comparison"]["P"]["NONTRIVIAL_RESOURCE_PLAN"] == 0
    assert payload["target_class_comparison"]["L"]["nontrivial_novel"] == 0
    assert payload["mismatches"] == []
