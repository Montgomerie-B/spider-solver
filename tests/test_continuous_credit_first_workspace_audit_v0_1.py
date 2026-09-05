"""Continuous-credit first-workspace audit helpers and calibration."""

from __future__ import annotations

import heapq
import importlib.util
import inspect
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.planner.anytime_controller import StrategicCreditLevel, StrategicSearchNode


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "research" / "continuous_credit_first_workspace_audit_v0_1.py"
CONTROLLER = ROOT / "src" / "spider" / "planner" / "anytime_controller.py"
PLANNER = ROOT / "src" / "spider" / "planner" / "resource_excavation_planner.py"
DEAL = ROOT / "deals" / "4925153.txt"
RESULT = ROOT / "research" / "results" / "continuous_credit_first_workspace_audit_v0_1.json"


def _mod():
    spec = importlib.util.spec_from_file_location("cc_workspace_audit_v0_1", HARNESS)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _card(s, r):
    return Card(s, r)


def test_r_flags_on_synthetic_states():
    mod = _mod()
    buried = SpiderState(
        [Column([_card("s", 4)], [_card("h", 5)]) for _ in range(10)],
        [],
    )
    g = mod.geometry(buried)
    assert g["R2"] is False
    assert g["R4"] is False
    assert g["min_col_fd"] == 1

    revealed = SpiderState(
        [_card_col([], [_card("c", 5)]), _card_col([], [_card("d", 6)])]
        + [Column([_card("s", 13)], [_card("h", 12)]) for _ in range(8)],
        [],
    )
    g2 = mod.geometry(revealed)
    assert g2["R2"] is True
    assert g2["R3"] is True  # 5c onto 6d empties col 0

    empty = SpiderState(
        [Column([], [])] + [Column([_card("s", 4)], [_card("h", 5)]) for _ in range(9)],
        [],
    )
    assert mod.geometry(empty)["R4"] is True

    parent = buried
    child = SpiderState(
        [Column([], [_card("s", 4), _card("h", 5)])]
        + [Column([_card("s", 4)], [_card("h", 5)]) for _ in range(9)],
        [],
    )
    flags = mod.classify_transition(parent, child)["flags"]
    assert flags["R1"] is True  # flipped one face-down into up


def _card_col(down, up):
    return Column(list(down), list(up))


def test_lifecycle_and_raw_stage_helpers():
    mod = _mod()
    assert mod.successor_lifecycle(generated=True, retained=False, expanded=False) == "GENERATED"
    assert mod.successor_lifecycle(generated=True, retained=True, expanded=False) == "RETAINED"
    assert mod.successor_lifecycle(generated=True, retained=True, expanded=True) == "EXPANDED"
    assert mod.classify_raw_stage(in_raw=True, in_final=False, retained=False, expanded=False) == "P0"
    assert mod.classify_raw_stage(in_raw=True, in_final=True, retained=False, expanded=False) == "P1"
    assert mod.classify_raw_stage(in_raw=True, in_final=True, retained=True, expanded=False) == "P2"
    assert mod.classify_raw_stage(in_raw=True, in_final=True, retained=True, expanded=True) == "P3"


def test_widened_identity_keeps_credit_distinct():
    mod = _mod()
    fid = mod._load_fid()
    assert fid.continuation_identity("abcd", 0) != fid.continuation_identity("abcd", 1)


def test_starvation_ranking_counts_clean_nodes_ahead():
    mod = _mod()

    def node(credit, nid):
        return StrategicSearchNode(
            nid,
            SpiderState([Column([], [Card("s", 13)]) for _ in range(10)], []),
            0,
            (),
            None,
            None,
            0,
            StrategicCreditLevel(credit),
            None,
        )

    live = [
        ((0, 0), 1, node(0, 1)),
        ((0, 1), 2, node(0, 2)),
        ((1, 0), 3, node(1, 3)),
        ((2, 0), 4, node(2, 4)),
    ]
    rank = mod.starvation_ranking(live)
    assert rank["best"]["1"]["rank"] == 3
    assert rank["best"]["1"]["credit0_ahead"] == 2
    assert rank["best"]["2"]["lower_credit_ahead"] == 3


def test_observer_restore_leaves_heap_and_controller_unpatched():
    mod = _mod()
    import spider.planner.anytime_controller as controller

    push0, pop0 = heapq.heappush, heapq.heappop
    gen0, rec0 = controller.generate_strategic_successors, controller._record_transition
    obs = mod.WorkspaceAuditObserver()
    obs.install()
    assert heapq.heappush is not push0
    obs.restore()
    assert heapq.heappush is push0
    assert heapq.heappop is pop0
    assert controller.generate_strategic_successors is gen0
    assert controller._record_transition is rec0


def test_harness_does_not_call_resource_planner():
    mod = _mod()
    src = Path(inspect.getsourcefile(mod)).read_text(encoding="utf-8")
    assert "plan_resource_excavation(" not in src
    assert "resource_excavation_planner" not in CONTROLLER.read_text(encoding="utf-8")
    assert "MAX_OPERATORS = 8" in PLANNER.read_text(encoding="utf-8")


def test_first_event_path_replay_from_opening():
    mod = _mod()
    cards = tuple(load_deal(DEAL))
    opening = SpiderState.from_cards(list(cards))
    event = {
        "parent_path": [],
        "actions": ["deal"],
        "child_digest": "x",
    }
    # Replay a legal opening Deal; digest may not match placeholder.
    out = mod.replay_first_event(opening, event)
    assert out["replay_ok"] is True
    assert out["path_len"] == 1


def test_calibration_control_on_25_expansions():
    mod = _mod()
    cards = tuple(load_deal(DEAL))
    opening = SpiderState.from_cards(list(cards))
    result, observer, live = mod.run_observed_audit(opening, cards, expansions=25, seconds=180.0)
    ok, calib = mod.calibration_ok(result, observer, live)
    assert ok, calib["mismatches"]
    assert calib["metrics"]["expanded_credit"]["0"] == 25
    assert calib["metrics"]["live_credit"]["1"] == 25
    assert calib["metrics"]["widened_pushed"] == 25
    assert calib["metrics"]["widened_popped"] == 0


def test_milestones_are_from_one_continuous_run_in_artefact():
    import json

    if not RESULT.exists():
        return
    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    miles = payload.get("milestones") or {}
    ns = sorted(int(k) for k in miles)
    assert ns == sorted(ns)
    if len(ns) >= 2:
        assert ns[0] == 25
        for earlier, later in zip(ns, ns[1:]):
            assert later > earlier
            assert miles[str(later)]["expansions"] > miles[str(earlier)]["expansions"]
    assert payload["long_run"]["max_strategic_expansions"] == 400
    assert payload["calibration"]["mismatches"] == {}
    assert payload["geometry"]["R2"]["retained"] >= 1
    assert payload["geometry"]["R4"]["generated"] == 0
    assert payload["long_run"]["stop_reason"] == "strategic expansion limit"
    assert "1" not in payload["first_credit"]["pop"]
