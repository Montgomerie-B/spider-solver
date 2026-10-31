"""Cold campaign contracts. These tests do not run a long search."""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.autonomous_solve_campaign import (
    SCHEMA,
    assert_cold_document,
    campaign_category,
    run_campaign_attempt,
    verified_prefix,
)
from spider.global_search_experiment import replay_cost, search_suit_ordered
from spider.metrics import format_action
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.research_actions import all_legal_actions, face_down_count, is_deal, opening_from_deal, step_cost
from spider.search_kernel import SearchLimits, run_search

DEAL = ROOT / "deals" / "4925153.txt"


def _opening():
    return opening_from_deal(DEAL)


def test_opening_generates_a_deal_and_more_than_one_successor():
    opening = _opening()
    actions = all_legal_actions(opening)
    assert any(is_deal(action) for action in actions)
    assert len(actions) > 1
    assert sum(1 for action in actions if step_cost(opening, action) == 0) >= 0


def test_lower_g_opening_is_the_retained_root():
    opening = _opening()
    store = pack_state(opening).hex()
    result = run_search(
        [{"g": 5, "ordered_digest": store}, {"g": 0, "ordered_digest": store}],
        limits=SearchLimits(max_unique=4, time_limit_s=1.0, rss_abort_mb=512, cost_ceiling=0),
        identity_fn=pack_whole_game_identity,
        actions_fn=all_legal_actions,
        is_terminal=lambda state: state.is_solved(),
        lane_names=("cost",),
        lane_key_fns=[lambda state, g: (g,)],
    )
    roots = [node for node in result.nodes if node.parent < 0]
    assert len(roots) == 1
    assert roots[0].g == 0
    assert "child_g >= prev" in inspect.getsource(run_search)


def test_paid_ceiling_is_not_a_proof_and_zero_cost_stays_visible(tmp_path):
    status = tmp_path / "status.json"
    document = run_campaign_attempt(
        _opening(),
        status_path=status,
        time_limit_s=2.0,
        max_unique=30,
        rss_abort_mb=512,
        cost_ceiling=0,
        checkpoint_s=0,
    )
    attempt = document["attempts"][0]
    assert attempt["ceiling_prunes"] > 0
    assert attempt["lower_bound_prunes"] == 0
    assert attempt["ceiling_is_proof"] is False
    assert attempt["stop_class"] == "heap_empty_under_paid_ceiling"
    assert attempt["restart_inherits_exhaustion"] is False
    assert attempt["exact_frontier_retained"] is False
    assert attempt["deal_policy"] == "all_legal_actions"
    assert "zero_cost_actions" in attempt
    assert document["category"] == "NO_NEW_COMPLETE_GAME_YET"
    loaded = json.loads(status.read_text(encoding="utf-8"))
    assert loaded["schema"] == SCHEMA
    assert loaded["exact_frontier_retained"] is False


def test_short_cold_search_admits_a_deal_and_reloads_a_physical_path(tmp_path):
    status = tmp_path / "status.json"
    document = run_campaign_attempt(
        _opening(),
        status_path=status,
        time_limit_s=4.0,
        max_unique=40,
        rss_abort_mb=1024,
        cost_ceiling=400,
        checkpoint_s=0,
    )
    attempt = document["attempts"][0]
    assert attempt["deal_admissions"] > 0
    assert attempt["generated"] > 1
    assert attempt["legal_actions_dropped"] == 0
    assert attempt["heuristic_exclusions"] == 0
    branch = document["best_branch"]
    assert branch["replay_ok"] is True
    actions = [item if item == "deal" else item for item in branch["actions"]]
    prefix = verified_prefix(_opening(), document, "best")
    assert [format_action(action) for action in prefix] == actions
    end, cost = replay_cost(_opening(), prefix)
    assert cost == branch["g"]
    assert pack_state(end).hex() == branch["pack"]
    assert face_down_count(end) == branch["face_down"]


def test_resume_rejects_a_tampered_or_foreign_checkpoint():
    opening = _opening()
    action = all_legal_actions(opening)[0]
    end, cost = replay_cost(opening, [action])
    document = {
        "schema": SCHEMA,
        "provenance": "cold_opening",
        "reference_seed": False,
        "exact_frontier_retained": False,
        "restart_inherits_exhaustion": False,
        "attempts": [
            {
                "branches": [
                    {
                        "id": "b0",
                        "role": "leader",
                        "g": cost,
                        "pack": pack_state(end).hex(),
                        "actions": [format_action(action)],
                        "replay_ok": True,
                        "foundations": len(end.foundations),
                        "face_down": face_down_count(end),
                        "stock_rows": len(end.stock) // 10,
                        "expanded": True,
                    }
                ]
            }
        ],
        "best_branch": None,
    }
    assert verified_prefix(opening, document, "best") == [action]
    broken = json.loads(json.dumps(document))
    broken["attempts"][0]["branches"][0]["g"] = int(cost) + 9
    broken["best_branch"] = None
    with pytest.raises(ValueError, match="does not match"):
        verified_prefix(opening, broken, "foundations")
    foreign = json.loads(json.dumps(document))
    foreign["provenance"] = "imported"
    with pytest.raises(ValueError, match="provenance"):
        assert_cold_document(foreign)
    seeded = json.loads(json.dumps(document))
    seeded["reference_seed"] = True
    with pytest.raises(ValueError, match="reference"):
        assert_cold_document(seeded)
    assert campaign_category(document) == "NO_NEW_COMPLETE_GAME_YET"


def test_resume_of_a_cold_branch_is_a_descendant_not_a_new_reference(tmp_path):
    opening = _opening()
    action = next(item for item in all_legal_actions(opening) if not is_deal(item))
    end, cost = replay_cost(opening, [action])
    branch = {
        "id": "b0",
        "role": "leader",
        "g": cost,
        "pack": pack_state(end).hex(),
        "actions": [format_action(action)],
        "replay_ok": True,
        "foundations": len(end.foundations),
        "face_down": face_down_count(end),
        "stock_rows": len(end.stock) // 10,
        "expanded": True,
    }
    resume = {
        "schema": SCHEMA,
        "deal_id": "4925153",
        "provenance": "cold_opening",
        "reference_seed": False,
        "exact_frontier_retained": False,
        "restart_inherits_exhaustion": False,
        "attempts": [{"branches": [branch]}],
        "best_branch": branch,
    }
    document = run_campaign_attempt(
        opening,
        status_path=tmp_path / "resume.json",
        time_limit_s=2.0,
        max_unique=12,
        rss_abort_mb=1024,
        cost_ceiling=400,
        checkpoint_s=0,
        resume=resume,
        resume_from="best",
    )
    attempt = document["attempts"][-1]
    assert attempt["campaign_provenance"] == "cold_descendant"
    assert attempt["reference_seed"] is False
    assert attempt["prefix_len"] == 1
    assert attempt["search_provenance"] == "checkpoint_continuation"
    assert document["provenance"] == "cold_descendant"
    assert document["restart_inherits_exhaustion"] is False


def test_cold_campaign_source_does_not_name_stored_routes():
    module = inspect.getsource(run_campaign_attempt)
    tool = (ROOT / "tools" / "autonomous_solve_campaign.py").read_text(encoding="utf-8")
    search = inspect.getsource(search_suit_ordered)
    for banned in (
        "4925153_autonomous_185",
        "4925153_canonical",
        "4925153_autonomous_v0_74",
        "known_g123",
        "practical_witness_play_pilot",
    ):
        assert banned not in module
        assert banned not in tool
        assert banned not in search
    assert "all_legal_actions" in search
    assert "lower_bound_fn=bound" in search
    assert "production_ceiling" not in module
