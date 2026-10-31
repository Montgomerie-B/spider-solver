"""Replay the saved 4925153 play traces. This does not launch either arm."""

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

TRACE = ROOT / "docs" / "practical_witness_play_pilot.json"
FREEZE_SHA = "69cf172f0221be01fcf97f36bf8018191eb7163e"
IMPLEMENTATION_SHA = "f2356985dfc39e697f09c7b6d244f95e04ec0ed9"


def _action(raw):
    if raw == ["deal"]:
        return ("deal",)
    return (int(raw[0]), int(raw[1]), int(raw[2]))


def _load():
    return json.loads(TRACE.read_text(encoding="utf-8"))


def test_saved_traces_replay_from_the_opening():
    data = _load()
    assert data["freeze_sha"] == FREEZE_SHA
    assert data["implementation_sha"] == IMPLEMENTATION_SHA
    assert data["deal_sha256"] == "C0B70979B3E6B90E266691DF956026629C890F49C12ED519801D6779434734DF"
    assert data["canonical_sha256"] == "18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33"
    assert data["checks_ok"] is True
    assert data["verdict"] == "NO_CLEAR_BENEFIT"
    assert data["recommendation"] == "Leave the probe caps, budgets, and selector unchanged."
    assert data["independent_cold_complete"] is False
    assert [pair["label"] for pair in data["pairs"]] == ["tie", "tie", "tie", "tie"]
    assert all(row["optimal"] is False for pair in data["pairs"] for row in pair["trajectory"])

    by_root = {}
    assert len(data["episodes"]) == 8
    for episode in data["episodes"]:
        by_root.setdefault(episode["root_id"], {})[episode["mode"]] = episode
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
        for step in episode["actions"]:
            action = _action(step["action"])
            paid += int(step_cost(state, action))
            apply_action(state, action)
            assert pack_state(state).hex() == step["pack"]
            assert paid == step["paid"]
        assert paid == episode["paid"]
        assert pack_state(state).hex() == episode["final_pack"]
        assert face_down_count(state) == episode["hidden"]
        assert len(state.foundations) == episode["foundations"]
        assert len(state.stock) == episode["stock"]
        assert episode["solved"] is False
        assert episode["independent_cold_complete"] is False
        assert episode["optimality_claim"] is False
        for decision in episode["decision_records"]:
            selection = decision["selection"]
            assert selection["optimality_claim"] is False
            assert selection["full_game_optimum"] is False
            if selection["witness_status"] == "upper-unfinished":
                assert selection["admissible_bound"] is False

    for root_id, modes in by_root.items():
        baseline = [step["action"] for step in modes["baseline"]["actions"]]
        witness = [step["action"] for step in modes["witness"]["actions"]]
        assert baseline == witness, root_id
        assert modes["baseline"]["foundations"] == modes["witness"]["foundations"]
        assert modes["baseline"]["hidden"] == modes["witness"]["hidden"]
