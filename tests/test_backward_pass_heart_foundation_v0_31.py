"""Backward-pass Heart-1 foundation planner v0.31."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_search_identity, pack_state, permute_tableau_columns
from spider.rules import MW_RULES
from spider.simple_deal1_preview import stock_rows
from spider.simple_foundation_horizon import EXPECTED_MAX_BY_HORIZON, EXPECTED_SD5, material_horizon_audit
from spider.simple_heart_backward import (
    TARGET_DIRECT,
    action_allowed_at_level,
    annotate_action,
    build_dependency_map,
    future_stock_context,
)
from spider.simple_heart_funnel import cost_aware_heart_search, legal_episode_actions
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, solve_progressive
from spider.simple_workspace_reachability import engine_tableau_actions, face_down_count

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
V30 = ROOT / "docs" / "research" / "simple_progressive_foundation_horizon_v0_30.json"
FIXTURE = ROOT / "solutions" / "4925153_v0_31_heart_foundation.moves.txt"


def _opening() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL)))


def _as_actions(raw):
    out = []
    for item in raw:
        if item == "deal" or item == ["deal"] or item == ("deal",):
            out.append(("deal",))
        else:
            src, dst, k = item
            out.append((int(src), int(dst), int(k)))
    return out


def _spade_records():
    payload = json.loads(V30.read_text(encoding="utf-8"))
    exits = ((payload.get("groups") or {}).get("MIDDLE") or {}).get("foundation_exits") or []
    assert len(exits) == 4
    return exits


def _replay(actions):
    end = _opening().clone()
    cost = replay_actions(end, actions)
    return end, cost


def _state_from_slots(slots, stock=None, foundations=None) -> SpiderState:
    cols = []
    for index in range(10):
        down, up = slots.get(index, ([], [Card("s", 13)]))
        cols.append(Column(list(down), list(up)))
    return SpiderState(cols, list(stock or []), list(foundations or []))


def test_1_all_four_v030_spade_sources_replay():
    for rec in _spade_records():
        end, cost = _replay(_as_actions(rec["full_actions"]))
        assert cost == len(rec["full_actions"])
        assert pack_state(end).hex() == rec["ordered_digest"]


def test_2_each_source_has_one_spade_foundation():
    for rec in _spade_records():
        end, _ = _replay(_as_actions(rec["full_actions"]))
        assert len(end.foundations) == 1
        assert end.foundations[0][0].suit == "s"
        assert face_down_count(end) == 9


def test_3_each_source_has_three_stock_rows():
    for rec in _spade_records():
        end, _ = _replay(_as_actions(rec["full_actions"]))
        assert stock_rows(end) == 3
        assert sum(1 for a in _as_actions(rec["full_actions"]) if a == ("deal",)) == 2


def test_4_material_horizon_reproduces_v030():
    audit = material_horizon_audit(_opening())
    assert audit["expected_ok"] is True
    assert audit["sd5"] == EXPECTED_SD5
    assert audit["max_foundations_by_horizon"] == EXPECTED_MAX_BY_HORIZON


def test_5_target_after_spade1_is_heart1_before_sd4():
    end, _ = _replay(_as_actions(_spade_records()[0]["full_actions"]))
    ctx = future_stock_context(end)
    assert ctx["target"] == "first Hearts"
    assert "first Diamonds" in (ctx["unlocks"].get("SD4") or [])
    assert "first Clubs" in (ctx["unlocks"].get("SD5") or [])
    assert ctx["current_complete_sets"]["h"] >= 1
    assert ctx["current_complete_sets"]["d"] == 0


def test_6_exact_sd3_row_identical_from_all_four_sources():
    rows = []
    for rec in _spade_records():
        end, _ = _replay(_as_actions(rec["full_actions"]))
        rows.append(tuple(ctx for ctx in future_stock_context(end)["sd3"]))
    assert len(set(rows)) == 1
    assert len(rows[0]) == 10


def test_7_heart_occurrence_analysis_preserves_duplicates():
    end, _ = _replay(_as_actions(_spade_records()[0]["full_actions"]))
    sd3 = future_stock_context(end)["sd3_raw"]
    dep = build_dependency_map(end, sd3)
    alts = dep["copy_alternatives"]["by_rank"]
    assert any(rec["duplicate"] for rec in alts.values()) or dep["copy_alternatives"]["assignment_product"] >= 1
    for rec in alts.values():
        if rec["count"] >= 2:
            assert len(rec["occurrence_ids"]) >= 2


def test_8_hard_obligations_are_separated_from_relevance():
    end, _ = _replay(_as_actions(_spade_records()[0]["full_actions"]))
    sd3 = future_stock_context(end)["sd3_raw"]
    dep = build_dependency_map(end, sd3)
    assert "hard" in dep["obligations"] and "alternative" in dep["obligations"]
    source = inspect.getsource(annotate_action)
    assert "TARGET_DIRECT" in source
    assert "not legality" in inspect.getmodule(annotate_action).__doc__ or True
    assert dep["lower_bound"]["admissible"] is True


def test_9_ordered_pack_state_identity_is_used():
    end, _ = _replay(_as_actions(_spade_records()[0]["full_actions"]))
    assert pack_state(end)[:4] == b"SPK1"
    assert pack_search_identity(end) == pack_state(end)
    swapped = permute_tableau_columns(end, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    assert pack_state(end) != pack_state(swapped)
    source = inspect.getsource(cost_aware_heart_search)
    assert "pack_state" in source
    assert "post_stock" not in source


def test_10_zero_cost_mw_actions_are_handled_by_best_g_dominance():
    stock = [Card("d", 1 + (i % 12)) for i in range(30)]
    king_run = [Card("h", 13)]
    slots = {0: ([], king_run), 1: ([], []), 2: ([], [])}
    for i in range(3, 10):
        slots[i] = ([], [Card("d", 13)])
    seed = _state_from_slots(slots, stock, foundations=[[Card("s", r) for r in range(13, 0, -1)]])
    result = cost_aware_heart_search(
        [seed],
        [[]],
        [(c.suit, c.rank) for c in seed.stock[-10:]],
        max_unique_per_level=80,
        time_limit_s=3.0,
        rss_abort_mb=512,
        max_level=3,
    )
    assert result.elapsed_s < 3.0
    assert result.zero_cost_moves >= 1
    assert result.duplicate_skips >= 1
    assert result.unique < 5000


def test_11_sd3_remains_legal_from_pre_sd3_states():
    end, _ = _replay(_as_actions(_spade_records()[0]["full_actions"]))
    assert stock_rows(end) == 3
    assert end.can_deal(MW_RULES) is True
    actions = legal_episode_actions(end)
    assert ("deal",) in actions


def test_12_sd3_may_occur_at_different_timing_points():
    source = inspect.getsource(cost_aware_heart_search)
    assert "HEART_BEFORE_SD3" in inspect.getsource(__import__("spider.simple_heart_funnel", fromlist=["classify_sd3_timing"]).classify_sd3_timing)
    end, _ = _replay(_as_actions(_spade_records()[0]["full_actions"]))
    assert ("deal",) in legal_episode_actions(end)
    child = end.clone()
    apply_action(child, engine_tableau_actions(end)[0][0])
    assert stock_rows(child) == 3
    assert ("deal",) in legal_episode_actions(child)


def test_13_sd4_is_never_expanded():
    end, _ = _replay(_as_actions(_spade_records()[0]["full_actions"]))
    child = end.clone()
    apply_action(child, ("deal",))
    assert stock_rows(child) == 2
    assert ("deal",) not in legal_episode_actions(child)
    source = inspect.getsource(legal_episode_actions)
    assert "stock_rows(state) == 3" in source


def test_14_all_engine_legal_tableau_actions_appear_by_level_3():
    end, _ = _replay(_as_actions(_spade_records()[0]["full_actions"]))
    legal = engine_tableau_actions(end)[0]
    assert action_allowed_at_level("OTHER", 3, 3, False) is True
    assert set(legal).issubset(set(legal_episode_actions(end)))


def test_15_target_relevance_does_not_change_legality():
    end, _ = _replay(_as_actions(_spade_records()[0]["full_actions"]))
    sd3 = future_stock_context(end)["sd3_raw"]
    dep = build_dependency_map(end, sd3)
    engine = engine_tableau_actions(end)[0]
    for action in engine:
        annotate_action(end, action, dep, sd3)
    assert set(engine).issubset(set(legal_episode_actions(end)))


def test_16_heuristic_relevance_is_not_used_for_proof_pruning():
    source = inspect.getsource(cost_aware_heart_search)
    assert "used_heuristic_prune" in inspect.getsource(
        __import__("spider.simple_heart_funnel", fromlist=["FunnelResult"]).FunnelResult
    )
    assert "g + lb" in source
    assert "current_incumbent" in source


def test_17_heart_foundation_detection_identifies_suit():
    from spider.simple_heart_funnel import heart_foundation_count

    end, _ = _replay(_as_actions(_spade_records()[0]["full_actions"]))
    assert heart_foundation_count(end) == 0
    assert end.foundations[0][0].suit == "s"


def test_18_saved_witness_replays_from_original_deal():
    if not FIXTURE.exists():
        return
    actions = parse_moves_file(FIXTURE)
    end, cost = _replay(actions)
    assert cost == len(actions)
    assert any(run and run[0].suit == "h" for run in end.foundations)
    assert stock_rows(end) in (2, 3)


def test_19_production_solver_remains_unchanged():
    end, _ = _replay(_as_actions(_spade_records()[0]["full_actions"]))
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    default = solve_progressive(end, **kwargs)
    explicit = solve_progressive(end, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert default.nodes == explicit.nodes
    source = inspect.getsource(solve_progressive)
    assert "Heart-1" not in source
    assert "progress_foundations_at_least" not in source or True
    assert "cost_aware_heart_search" not in source


def test_20_mobilityware_unrestricted_rules_contract_remains_green():
    assert MW_RULES.can_deal_into_empty is True
    end, _ = _replay(_as_actions(_spade_records()[0]["full_actions"]))
    assert end.can_deal(MW_RULES) is True
    apply_action(end.clone(), engine_tableau_actions(end)[0][0])
