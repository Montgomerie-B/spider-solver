"""CREATE_WORKSPACE suit-aware singleton-high guard counterfactual helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.planner.resource_excavation_planner import CampaignTarget
import spider.planner.resource_excavation_planner as planner_mod


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "research" / "create_workspace_suit_aware_guard_counterfactual_v0_1.py"
CONTROLLER = ROOT / "src" / "spider" / "planner" / "anytime_controller.py"
PLANNER = ROOT / "src" / "spider" / "planner" / "resource_excavation_planner.py"
DEAL = ROOT / "deals" / "4925153.txt"
RESULT = ROOT / "research" / "results" / "create_workspace_suit_aware_guard_counterfactual_v0_1.json"


def _mod():
    spec = importlib.util.spec_from_file_location("create_guard_cf_v0_1", HARNESS)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _opening():
    return SpiderState.from_cards(list(load_deal(DEAL)))


def test_exact_high_same_suit_remains_rejected():
    mod = _mod()
    target = CampaignTarget("c", 12, 11)
    state = mod._filled({0: [Card("c", 12)], 1: [Card("h", 13)]})
    assert mod.create_reject_reason(state, target, (0, 1, 1), "G0") == "EXCLUDED_SINGLETON_CAMPAIGN_HIGH"
    assert mod.create_reject_reason(state, target, (0, 1, 1), "G1") == "EXCLUDED_SINGLETON_CAMPAIGN_HIGH"
    assert (0, 1, 1) not in mod.create_actions(state, target, "G1")


def test_off_suit_same_rank_differs_g0_g1():
    mod = _mod()
    target = CampaignTarget("c", 12, 11)
    state = mod._filled(
        {0: [Card("s", 12)], 1: [Card("h", 13)], 2: [Card("c", 12), Card("d", 2)]}
    )
    assert mod.create_reject_reason(state, target, (0, 1, 1), "G0") == "EXCLUDED_SINGLETON_CAMPAIGN_HIGH"
    assert mod.create_reject_reason(state, target, (0, 1, 1), "G1") is None
    assert (0, 1, 1) in mod.create_actions(state, target, "G1")
    assert (0, 1, 1) not in mod.create_actions(state, target, "G0")


def test_unrelated_rank_unchanged():
    mod = _mod()
    target = CampaignTarget("c", 12, 11)
    state = mod._filled({0: [Card("s", 5)], 1: [Card("h", 6)], 2: [Card("c", 12)]})
    g0 = mod.create_reject_reason(state, target, (0, 1, 1), "G0")
    g1 = mod.create_reject_reason(state, target, (0, 1, 1), "G1")
    assert g0 == g1


def test_other_create_guards_unchanged():
    mod = _mod()
    target = CampaignTarget("c", 12, 11)
    uniq = mod._filled({0: [Card("s", 11)], 1: [Card("c", 12)]})
    assert mod.create_reject_reason(uniq, target, (0, 1, 1), "G0") == "OCCUPIES_UNIQUE_RECEIVER"
    assert mod.create_reject_reason(uniq, target, (0, 1, 1), "G1") == "OCCUPIES_UNIQUE_RECEIVER"
    mixed = mod._filled({0: [Card("s", 13), Card("h", 5)], 1: [Card("c", 12)]})
    assert mod.create_reject_reason(mixed, target, (0, 1, 2), "G0") == "NOT_ONE_MOVABLE_RUN"
    assert mod.create_reject_reason(mixed, target, (0, 1, 2), "G1") == "NOT_ONE_MOVABLE_RUN"
    idle = mod._filled({0: [Card("s", 12)], 1: [Card("h", 13)]}, empty=(3,))
    assert mod.create_reject_reason(idle, target, (0, 1, 1), "G0") == "HAS_IDLE_EMPTY"
    assert mod.create_reject_reason(idle, target, (0, 1, 1), "G1") == "HAS_IDLE_EMPTY"


def test_natural_r3_p_g0_rejection_reproduced():
    mod = _mod()
    state = mod.reconstruct_first_r2(_opening())
    check = mod.verify_natural_r3(state)
    assert check["ok"]
    reason = mod.create_reject_reason(state, mod.P_TARGET, (5, 1, 1), "G0")
    assert reason == "EXCLUDED_SINGLETON_CAMPAIGN_HIGH"


def test_natural_r3_p_g1_create_acceptance():
    mod = _mod()
    state = mod.reconstruct_first_r2(_opening())
    reason = mod.create_reject_reason(state, mod.P_TARGET, (5, 1, 1), "G1")
    assert reason is None
    assert (5, 1, 1) in mod.create_actions(state, mod.P_TARGET, "G1")


def test_g0_s_established_trace_reproduced():
    mod = _mod()
    state = mod.reconstruct_first_r2(_opening())
    plan = mod.run_plan(state, mod.S_TARGET, "G0")
    assert plan["result"] == "PREPAID_DEPENDENCY"
    assert plan["operators"] == ["CREATE_WORKSPACE", "INVEST_WORKSPACE", "RECOVER_WORKSPACE"]
    assert plan["actions"] == [[5, 1, 1], [9, 5, 1], [5, 6, 1]]
    assert plan["end_digest"] == mod.S_TERMINAL
    assert plan["replay_ok"]
    assert plan["unresolved"] == 0


def test_production_function_restored_after_counterfactual():
    mod = _mod()
    original = planner_mod._realise_create
    state = mod._filled({0: [Card("s", 12)], 1: [Card("h", 13)]})
    target = CampaignTarget("c", 12, 11)
    with mod.create_guard_mode("G1"):
        assert planner_mod._realise_create is not original
        list(planner_mod._realise_create(state, mod.empty_obligations(), target))
    assert planner_mod._realise_create is original
    assert planner_mod._realise_create is mod._ORIG_REALISE_CREATE
    mod.run_plan(state, target, "G1")
    assert planner_mod._realise_create is original


def test_production_files_unchanged():
    controller = CONTROLLER.read_text(encoding="utf-8")
    planner = PLANNER.read_text(encoding="utf-8")
    assert "resource_excavation" not in controller
    assert "if len(col.face_up) == 1 and col.face_up[0].rank == target.high_rank:" in planner
    assert "col.face_up[0].suit == target.suit" not in planner.split("def _realise_create")[1].split("def _realise_invest")[0]


def test_artefact_prefixes_and_no_same_suit_high_leak():
    import json

    if not RESULT.exists():
        return
    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    assert payload["r3"]["digest"] == "1c3d3ec77bf164ad"
    assert payload["controls"]["C1"]["match"]
    assert payload["controls"]["C2"]["match"]
    assert payload["unexpected_delta_count"] == 0
    assert payload["production_restored"] is True
    assert payload["decision"] in {"A", "B", "C", "D", "E"}
