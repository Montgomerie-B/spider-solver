"""Natural-state resource-planner shadow audit: collection isolation and overlap."""

from __future__ import annotations

import importlib.util
import inspect
import json
import random
from pathlib import Path
from types import SimpleNamespace

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.planner.resource_excavation_planner import CampaignTarget
from spider.state_identity import canonical_state_key


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "research" / "resource_excavation_natural_shadow_v0_1.py"
CONTROLLER = ROOT / "src" / "spider" / "planner" / "anytime_controller.py"
RESULT = ROOT / "research" / "results" / "resource_excavation_natural_shadow_v0_1.json"


def _harness():
    spec = importlib.util.spec_from_file_location("natural_shadow_v0_1", HARNESS)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _tiny_state() -> SpiderState:
    cols = [Column([], [Card("shdc"[i % 4], 13)]) for i in range(10)]
    cols[0] = Column([], [Card("h", 13)])
    cols[3] = Column([], [Card("h", 12)])
    return SpiderState(cols, [])


def test_collection_does_not_mutate_captured_states():
    mod = _harness()
    parent_state = _tiny_state()
    child_state = parent_state.clone()
    before = canonical_state_key(parent_state)
    collector = mod.PassiveCollector()
    collector.capture(
        SimpleNamespace(state=parent_state),
        SimpleNamespace(
            actions=((0, 3, 1),),
            corrected_cost=1,
            kind=SimpleNamespace(value="ECONOMIC_PROJECT"),
        ),
        SimpleNamespace(state=child_state),
    )
    parent_state.columns[0].face_up.pop()
    child_state.columns[3].face_up.append(Card("c", 2))
    stored = collector.states[mod._key_digest(before)]
    assert canonical_state_key(stored) == before
    assert stored.columns[0].face_up[-1] == Card("h", 13)


def test_shadow_evaluation_does_not_mutate_input_state():
    mod = _harness()
    state = _tiny_state()
    before = canonical_state_key(state)
    target = CampaignTarget("h", 13, 12)
    row = mod._evaluate_pair(state, target)
    assert canonical_state_key(state) == before
    assert row["proof_pruning_allowed"] is False


def test_controller_source_does_not_import_resource_planner():
    source = CONTROLLER.read_text(encoding="utf-8")
    assert "resource_excavation" not in source
    import spider.planner.anytime_controller as controller

    assert "resource_excavation_planner" not in inspect.getsource(controller)


def test_shadow_evaluation_cannot_feed_successors_into_production(monkeypatch):
    mod = _harness()
    import spider.planner.anytime_controller as controller

    calls: list[str] = []

    original_generate = controller.generate_strategic_successors
    original_record = controller._record_transition

    def generate_boom(*args, **kwargs):
        calls.append("generate")
        return original_generate(*args, **kwargs)

    def record_boom(*args, **kwargs):
        calls.append("record")
        return original_record(*args, **kwargs)

    monkeypatch.setattr(controller, "generate_strategic_successors", generate_boom)
    monkeypatch.setattr(controller, "_record_transition", record_boom)
    state = _tiny_state()
    mod._evaluate_pair(state, CampaignTarget("h", 13, 12))
    assert calls == []


def test_production_search_does_not_call_resource_planner(monkeypatch):
    mod = _harness()
    import spider.planner.resource_excavation_planner as planner

    def boom(*args, **kwargs):
        raise AssertionError("production search invoked the resource planner")

    monkeypatch.setattr(planner, "plan_resource_excavation", boom)
    result, collector = mod._run_production(collect=False, expansions=1)
    assert collector is None
    assert result.strategic_expansions == 1
    assert result.stop_reason == "strategic expansion limit"


def test_baseline_and_collection_runs_are_behaviourally_equivalent():
    mod = _harness()
    result_a, collector_a = mod._run_production(collect=False, expansions=2)
    result_b, collector_b = mod._run_production(collect=True, expansions=2)
    assert collector_a is None
    assert collector_b is not None
    fp_a = mod._fingerprint(result_a, None)
    fp_b = mod._fingerprint(result_b, collector_b.transitions)
    for key in (
        "status",
        "stop_reason",
        "strategic_expansions",
        "tactical_nodes",
        "incumbent_cost",
        "incumbent_actions",
        "best_g",
        "best_digest",
        "maximum_credit_reached",
        "telemetry",
    ):
        assert fp_a[key] == fp_b[key], key
    assert result_a.stop_reason == "strategic expansion limit"
    assert result_b.strategic_expansions == 2
    assert collector_b.transitions
    import spider.planner.anytime_controller as controller

    assert controller._record_transition.__name__ == "_record_transition"


def test_deterministic_sampling_ignores_input_order():
    mod = _harness()
    items = []
    for i in range(200):
        digest = f"{i:016x}"
        suit = "hcds"[i % 4]
        items.append(
            {
                "digest": digest,
                "target": CampaignTarget(suit, 13 - (i % 3), 12 - (i % 3)),
                "pair_hash": mod.pair_identity_hash(
                    digest, suit, 13 - (i % 3), 12 - (i % 3)
                ),
            }
        )
    reversed_items = list(reversed(items))
    shuffled = list(items)
    random.Random(7).shuffle(shuffled)
    _, a = mod.select_state_target_pairs(items, 128)
    _, b = mod.select_state_target_pairs(reversed_items, 128)
    _, c = mod.select_state_target_pairs(shuffled, 128)
    ident = lambda rows: [
        (row["digest"], row["target"].suit, row["target"].high_rank, row["target"].low_rank)
        for row in rows
    ]
    assert ident(a) == ident(b) == ident(c)
    assert len(a) == 128
    hashes = [row["pair_hash"] for row in a]
    assert hashes == sorted(hashes)


def test_overlap_classification_duplicate_dominated_better_and_novel():
    mod = _harness()
    children = [
        {"child": "aaaa", "cost": 4, "actions": [[0, 1, 1]]},
        {"child": "bbbb", "cost": 3, "actions": [[2, 3, 1]]},
    ]

    def row(end: str, cost: int, result: str = "REALISED_CAMPAIGN_PROGRESS", first=None):
        return {
            "end_digest": end,
            "cost": cost,
            "result": result,
            "first_action": first if first is not None else [0, 1, 1],
        }

    exact = mod._classify_overlap(row("aaaa", 4), children, expanded=True)
    assert exact["class"] == "EXACT_DUPLICATE"
    assert exact["first_action_known"] is True

    dominated = mod._classify_overlap(row("aaaa", 6), children, expanded=True)
    assert dominated["class"] == "DOMINATED_DUPLICATE"

    better = mod._classify_overlap(row("aaaa", 2), children, expanded=True)
    assert better["class"] == "BETTER_DUPLICATE"

    novel = mod._classify_overlap(row("cccc", 5, first=[9, 8, 1]), children, expanded=True)
    assert novel["class"] == "NOVEL_RESOURCE_SUCCESSOR"
    assert novel["first_action_known"] is False

    unexpanded = mod._classify_overlap(row("cccc", 5), children, expanded=False)
    assert unexpanded["class"] == "PARENT_NOT_EXPANDED"

    none = mod._classify_overlap(
        row("cccc", 0, result="NO_BOUNDED_PLAN"), children, expanded=True
    )
    assert none["class"] == "NO_SUCCESS"


def test_audit_artefact_records_reproducible_identities_and_classifications():
    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    assert payload["collection_inert"] is True
    assert payload["production_config"]["max_strategic_expansions"] == 25
    assert payload["production_config"]["max_tactical_nodes"] == 300000
    assert payload["production_config"]["stop_reason"] == "strategic expansion limit"
    assert payload["sampled"] == payload["eligible_unique_pairs"]
    assert payload["sampled"] >= 32
    assert "evaluations" in payload
    assert len(payload["evaluations"]) == payload["sampled"]
    for row in payload["evaluations"]:
        assert "parent_digest" in row
        assert "target" in row
        assert "result" in row
        assert "overlap" in row
        assert row["proof_pruning_allowed"] is False
    assert payload["novel_terminal_states"] == 0
    assert payload["result_histogram"]["REALISED_CAMPAIGN_PROGRESS"] == 4
    assert payload["overlap_histogram"]["EXACT_DUPLICATE"] == 4
    assert payload["correctness_failures"] == []
