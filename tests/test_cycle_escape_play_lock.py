"""Replay the saved cycle-escape traces. This does not launch the official arm."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.packed_state import pack_state
from spider.practical_witness_manifest import FrozenRoot
from spider.practical_witness_play import materialize_root
from spider.research_actions import apply_action, face_down_count, step_cost

TRACE = ROOT / "docs" / "cycle_escape_play_pilot.json"
CONTROL = ROOT / "docs" / "practical_witness_play_pilot.json"
SPEC_SHA = "7a48471f0eb14223bbde582b558f386a5dd48b6b"


def _action(raw):
    if raw == ["deal"]:
        return ("deal",)
    return (int(raw[0]), int(raw[1]), int(raw[2]))


def test_saved_escape_traces_replay_and_keep_the_benefit_rule():
    data = json.loads(TRACE.read_text(encoding="utf-8"))
    control = json.loads(CONTROL.read_text(encoding="utf-8"))
    assert data["specification_sha"] == SPEC_SHA
    assert data["implementation_sha"] == SPEC_SHA
    assert data["deal_sha256"] == "C0B70979B3E6B90E266691DF956026629C890F49C12ED519801D6779434734DF"
    assert data["canonical_sha256"] == "18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33"
    assert data["checks_ok"] is True
    assert data["verdict"] == "ESCAPE_ONLY_NO_CLEAR_GAME_BENEFIT"
    assert data["recommendation"] == (
        "Leave the default cycle guard unchanged. The opt-in escape did not "
        "show a clear foundation or hidden-card benefit."
    )
    assert data["independent_cold_complete"] is False
    assert data["cycle_escape"] is True
    assert data["mode"] == "witness"
    assert control["verdict"] == "NO_CLEAR_BENEFIT"
    assert [row["label"] for row in data["comparisons"]] == [
        "tie",
        "improved",
        "tie",
        "tie",
    ]
    assert all(row["optimal"] is False for pair in data["comparisons"] for row in pair["trajectory"])

    control_actions = {}
    for episode in control["episodes"]:
        if episode["mode"] == "witness":
            control_actions[episode["root_id"]] = [
                _action(step["action"]) for step in episode["actions"]
            ]
    assert len(data["episodes"]) == 4
    for episode, comparison in zip(data["episodes"], data["comparisons"]):
        assert episode["root_id"] == comparison["root_id"]
        assert episode["solved"] is False
        assert episode["independent_cold_complete"] is False
        assert episode["optimality_claim"] is False
        assert episode["checks_ok"] is True
        start = episode["progress"][0]
        root = FrozenRoot(
            root_id=episode["root_id"],
            deal_ordinal=int(episode["deal_ordinal"]),
            prefix_actions=tuple(_action(action) for action in episode["imported_prefix"]),
            corrected_cost=int(episode["imported_cost"]),
            pack_hex=episode["source_pack"],
            stock=int(start["stock"]),
            foundations=int(start["foundations"]),
            hidden=int(start["hidden"]),
            duplicate_of=None,
            counts_as_evidence=True,
        )
        state = materialize_root(root)
        paid = 0
        played = []
        for step in episode["actions"]:
            action = _action(step["action"])
            played.append(action)
            paid += int(step_cost(state, action))
            apply_action(state, action)
            assert pack_state(state).hex() == step["pack"]
            assert paid == step["paid"]
        assert paid == episode["paid"]
        assert pack_state(state).hex() == episode["final_pack"]
        assert face_down_count(state) == episode["hidden"]
        assert len(state.foundations) == episode["foundations"]
        assert len(state.stock) == episode["stock"]
        old = control_actions[episode["root_id"]]
        assert played[: len(old)] == old
        assert comparison["actions_match_through_old_stop"] is True
        triggered = [
            record["recovery"]
            for record in episode["decision_records"]
            if record.get("recovery", {}).get("triggered")
        ]
        assert len(triggered) == comparison["recovery_events"]
        for record in episode["decision_records"]:
            selection = record["selection"]
            assert selection["optimality_claim"] is False
            assert selection["full_game_optimum"] is False
            recovery = record.get("recovery") or {}
            if recovery.get("triggered") and recovery.get("selected_option_id"):
                assert recovery["proved_strategy"] is False
                assert recovery["admissible_bound"] is False
                assert recovery["used_witness"] is False
                assert str(recovery["uncertainty"]).endswith("legal-fallback")
        if episode["root_id"] != "opening":
            assert triggered
            assert played[len(old)] == _action(triggered[0]["selected_action"])
            assert _action(triggered[0]["original_action"]) != played[len(old)]
