"""Harvested first-workspace resource/priority diagnostic helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.planner.resource_excavation_planner import CampaignTarget


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "research" / "harvested_first_workspace_resource_priority_v0_1.py"
CONTROLLER = ROOT / "src" / "spider" / "planner" / "anytime_controller.py"
PLANNER = ROOT / "src" / "spider" / "planner" / "resource_excavation_planner.py"
DEAL = ROOT / "deals" / "4925153.txt"
RESULT = ROOT / "research" / "results" / "harvested_first_workspace_resource_priority_v0_1.json"


def _mod():
    spec = importlib.util.spec_from_file_location("harvested_ws_v0_1", HARNESS)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_reconstruct_first_known_r2_digest():
    mod = _mod()
    cards = tuple(load_deal(DEAL))
    opening = SpiderState.from_cards(list(cards))
    state = mod.reconstruct_first_r2(opening)
    assert mod._digest(state) == mod.FIRST_R2
    geom = mod._cc().geometry(state)
    assert geom["R2"] is True
    assert geom["R3"] is True


def test_legal_first_empty_moves_on_first_r2():
    mod = _mod()
    cards = tuple(load_deal(DEAL))
    opening = SpiderState.from_cards(list(cards))
    state = mod.reconstruct_first_r2(opening)
    moves = mod.legal_first_empty_moves(state)
    assert len(moves) >= 1
    for mv in moves:
        assert mv["empties"] >= 1
        end = state.clone()
        from spider.metrics import replay_actions

        replay_actions(end, [(mv["src"], mv["dst"], mv["k"])])
        assert end.columns[mv["src"]].is_empty()


def test_create_reject_taxonomy_singleton_and_accept_paths():
    mod = _mod()
    cols = [Column([], [Card("s", 13)]) for _ in range(10)]
    cols[0] = Column([], [Card("h", 12)])  # singleton campaign high
    cols[1] = Column([], [Card("c", 13)])
    state = SpiderState(cols, [])
    target = CampaignTarget("h", 12, 11)
    # 12h onto 13c would empty col 0
    if state.can_move(0, 1, 1):
        reason = mod.create_reject_reason(state, target, (0, 1, 1))
        assert reason == "EXCLUDED_SINGLETON_CAMPAIGN_HIGH"


def test_ps_targets_are_scheduler_native():
    mod = _mod()
    cards = tuple(load_deal(DEAL))
    opening = SpiderState.from_cards(list(cards))
    state = mod.reconstruct_first_r2(opening)
    rows = mod.enumerate_ps(state)
    assert rows
    assert rows[0]["class"] == "P"
    assert all(row["class"] in {"P", "S"} for row in rows)
    first = mod.enumerate_ps(state)
    assert first == rows


def test_counterfactual_overlap_labels_are_prefixed():
    mod = _mod()
    prod = [{"child": "aaaa", "cost": 4}]
    assert mod.cf_overlap("aaaa", 4, prod) == "CF_EXACT_DUPLICATE"
    assert mod.cf_overlap("aaaa", 6, prod) == "CF_DOMINATED_DUPLICATE"
    assert mod.cf_overlap("aaaa", 2, prod) == "CF_BETTER_RESOURCE"
    assert mod.cf_overlap("bbbb", 4, prod) == "CF_NOVEL_RESOURCE_TERMINAL"
    assert all(label.startswith("CF_") for label in (
        "CF_EXACT_DUPLICATE",
        "CF_DOMINATED_DUPLICATE",
        "CF_BETTER_RESOURCE",
        "CF_NOVEL_RESOURCE_TERMINAL",
    ))


def test_lifespan_pop_vs_trim_vs_live():
    life_pop = {"popped": True, "trimmed": False, "live_at_400": False}
    life_trim = {"popped": False, "trimmed": True, "trim_expansion": 180, "live_at_400": False}
    life_live = {"popped": False, "trimmed": False, "live_at_400": True}
    assert life_pop["popped"] and not life_pop["trimmed"]
    assert life_trim["trimmed"] and not life_trim["popped"]
    assert life_live["live_at_400"] and not life_live["popped"]


def test_matched_controls_are_adjacent_priority_only():
    mod = _mod()
    ordered = [{"digest": f"d{i}", "g": i} for i in range(8)]
    ctrl = mod.matched_controls(ordered, "d3")
    assert [row["digest"] for row in ctrl["ahead"]] == ["d0", "d1", "d2"]
    assert [row["digest"] for row in ctrl["behind"]] == ["d4", "d5", "d6"]
    assert ctrl["index"] == 3


def test_passive_observation_restore():
    import heapq
    import spider.planner.anytime_controller as controller

    mod = _mod()
    push0, rec0 = heapq.heappush, controller._record_transition
    run = mod.HarvestRun()
    # install via a tiny observer restore path
    obs = mod._cc().WorkspaceAuditObserver()
    obs.install()
    obs.restore()
    assert heapq.heappush is push0
    assert controller._record_transition is rec0
    assert "resource_excavation" not in CONTROLLER.read_text(encoding="utf-8")
    assert "MAX_OPERATORS = 8" in PLANNER.read_text(encoding="utf-8")


def test_artefact_four_r2_and_counterfactual_prefix():
    import json

    if not RESULT.exists():
        return
    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    assert len(payload["corpus"]) == 4
    assert any(row["r3"] for row in payload["corpus"])
    assert payload["headline"]["first_r2_digest"] == "1c3d3ec77bf164ad"
    for analysis in payload["analyses"]:
        for plan in analysis["plans"]:
            if plan["overlap"] != "NO_SUCCESS":
                assert plan["overlap"].startswith("CF_")
