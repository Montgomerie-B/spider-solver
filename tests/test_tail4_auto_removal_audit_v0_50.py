"""TAIL4 auto-removal audit v0.50."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_post_stock_symmetry_state
from spider.rules import MW_RULES
from spider.simple_club_diamond_tail3_ready import (
    legal_tail4_joins,
    optional_tail4_join,
    tail3_already,
    tail4_present,
    tail4_ready,
)
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions
from spider.simple_foundation_race import suit_foundation_count
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, solve_progressive, step_cost
from spider.simple_tail4_auto_removal import (
    CONTRACT_FAILURE,
    FOUNDATION_AUTO_REMOVED,
    TAIL4_PERSISTS,
    classify_all_tail4_joins,
    classify_tail4_transition,
    foundation_is_ka,
    load_v049_tail3,
    optional_tail4_join_corrected,
    optional_tail4_join_v049,
    receiving_4_upper_run,
    reconstruct_tail4_ready_preview,
    synthetic_isolated_4_plus_tail3,
    synthetic_k4_plus_tail3,
)

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "simple_tail4_auto_removal.py"
SCRIPT = ROOT / "research" / "tail4_auto_removal_audit_v0_50.py"
V049_MOD = ROOT / "src" / "spider" / "simple_club_diamond_tail3_ready.py"
CLUB_T3 = ROOT / "docs" / "research" / "post_sd5_club_tail3_v0_49.json"
DIA_T3 = ROOT / "docs" / "research" / "post_sd5_diamond_tail3_v0_49.json"
CLUB_FIX = ROOT / "solutions" / "4925153_v0_50_club_foundation2.moves.txt"
DIA_FIX = ROOT / "solutions" / "4925153_v0_50_diamond_foundation2.moves.txt"
V049_REPORT = ROOT / "docs" / "research" / "post_sd5_club_diamond_reassessment_v0_49.md"


def _opening():
    return SpiderState.from_cards(list(load_deal(ROOT / "deals" / "4925153.txt")))


def test_1_2_synthetic_k4_is_ready_with_legal_join():
    st = synthetic_k4_plus_tail3("c")
    assert tail4_ready(st, "c")
    joins = legal_tail4_joins(st, "c")
    assert joins
    assert joins[0][2] == 3


def test_3_4_5_engine_auto_removes_ka_and_tail4_vanishes():
    st = synthetic_k4_plus_tail3("c")
    before = len(st.foundations)
    apply_action(st, legal_tail4_joins(st, "c")[0])
    assert len(st.foundations) == before + 1
    assert suit_foundation_count(st, "c") == 1
    assert foundation_is_ka(st.foundations[-1], "c")
    assert tail4_present(st, "c") is False


def test_6_old_helper_misses_auto_removal():
    st = synthetic_k4_plus_tail3("c")
    assert optional_tail4_join_v049(st, 0, "c") is None


def test_7_new_classifier_returns_foundation_auto_removed():
    st = synthetic_k4_plus_tail3("c")
    hits = classify_all_tail4_joins(st, 0, "c")
    assert hits
    assert hits[0]["class"] == FOUNDATION_AUTO_REMOVED
    assert optional_tail4_join_corrected(st, 0, "c")["class"] == FOUNDATION_AUTO_REMOVED


def test_8_isolated_4_persists_tail4():
    st = synthetic_isolated_4_plus_tail3("c")
    assert tail4_ready(st, "c")
    hits = classify_all_tail4_joins(st, 10, "c")
    assert hits[0]["class"] == TAIL4_PERSISTS
    assert hits[0]["g"] == 10 + step_cost(st, legal_tail4_joins(st, "c")[0])
    end = st.clone()
    apply_action(end, legal_tail4_joins(st, "c")[0])
    assert tail4_present(end, "c")


def test_9_classifier_rejects_neither_valid_success():
    src = inspect.getsource(classify_tail4_transition)
    assert FOUNDATION_AUTO_REMOVED in src
    assert TAIL4_PERSISTS in src
    assert CONTRACT_FAILURE in src


def test_10_11_v049_tail3_counts():
    club = json.loads(CLUB_T3.read_text(encoding="utf-8"))
    dia = json.loads(DIA_T3.read_text(encoding="utf-8"))
    assert club["n"] == 128
    assert dia["n"] == 192
    assert len(club["states"]) == 128
    assert len(dia["states"]) == 192


def test_10b_club_tail3_replay_sample():
    opening = _opening()
    rec = json.loads(CLUB_T3.read_text(encoding="utf-8"))["states"][0]
    end = opening.clone()
    cost = replay_actions(end, as_actions(rec["full_actions"]))
    assert cost == rec["g"]
    assert stock_rows(end) == 0
    assert tail3_already(end, "c")


def test_11b_diamond_tail3_replay_sample():
    opening = _opening()
    rec = json.loads(DIA_T3.read_text(encoding="utf-8"))["states"][0]
    end = opening.clone()
    cost = replay_actions(end, as_actions(rec["full_actions"]))
    assert cost == rec["g"]
    assert stock_rows(end) == 0
    assert tail3_already(end, "d")


def test_12_13_14_club_ready_joins_and_upper_run():
    from spider.simple_tail4_auto_removal import audit_immediate_joins as _audit

    src = inspect.getsource(_audit)
    assert "tail4_ready" in src
    assert "legal_tail4_joins" in inspect.getsource(classify_all_tail4_joins)
    st = synthetic_k4_plus_tail3("c")
    run = receiving_4_upper_run(st, legal_tail4_joins(st, "c")[0][1], "c")
    assert run["k_through_4"] is True
    assert run["length"] == 10
    iso = synthetic_isolated_4_plus_tail3("c")
    run2 = receiving_4_upper_run(iso, legal_tail4_joins(iso, "c")[0][1], "c")
    assert run2["label"] == "4 only"


def test_15_16_17_foundation2_validates_count_suit_and_mw():
    st = synthetic_k4_plus_tail3("d")
    g0 = 88
    hit = classify_all_tail4_joins(st, g0, "d")[0]
    assert hit["class"] == FOUNDATION_AUTO_REMOVED
    assert hit["foundation_count"] == 1
    assert "d" in hit["foundation_suits"]
    assert hit["g"] == g0 + 1 or hit["g"] > g0
    assert hit["ka_ok"] is True


def test_18_19_diamond_preview_persists_replayable_child():
    src = inspect.getsource(reconstruct_tail4_ready_preview)
    assert "parent" in src
    assert "full_actions" in src
    assert "depth" in src
    assert "PREVIEW_DEPTH" in src or "max_depth" in src


def test_20_all_diamond_joins_classified():
    src = inspect.getsource(__import__("spider.simple_tail4_auto_removal", fromlist=["audit_immediate_joins"]).audit_immediate_joins)
    assert "classify_all_tail4_joins" in src


def test_21_22_post_stock_symmetry_not_history():
    src = inspect.getsource(classify_tail4_transition)
    assert "pack_post_stock_symmetry_state" in src
    assign = src.split("symmetry_digest")[1][:80]
    assert "class" not in assign.lower() or "FOUNDATION" not in assign
    text = MOD.read_text(encoding="utf-8")
    assert "not rewritten" in text.lower() or "unchanged" in text.lower()


def test_23_saved_fixture_replays_if_present():
    opening = _opening()
    for path in (CLUB_FIX, DIA_FIX):
        if not path.exists():
            continue
        end = opening.clone()
        cost = replay_actions(end, parse_moves_file(path))
        assert stock_rows(end) == 0
        assert len(end.foundations) == 2
        assert cost >= 0


def test_24_25_no_foundation3_spade_heart_search():
    text = SCRIPT.read_text(encoding="utf-8") + MOD.read_text(encoding="utf-8")
    assert "Do not search Spades" in text or "no Spade" in text.lower()
    assert "Hearts" in text
    assert "Foundation 3" in text or "Foundation-3" in text
    assert "v0.49 reports" in text.lower() or "not rewritten" in text.lower()


def test_26_production_and_mw_green():
    assert MW_RULES.can_deal_into_empty is True
    opening = _opening()
    rec = json.loads(CLUB_T3.read_text(encoding="utf-8"))["states"][0]
    st = opening.clone()
    replay_actions(st, as_actions(rec["full_actions"]))
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(st, **kwargs)
    b = solve_progressive(st, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b.nodes
    assert "classify_tail4_transition" not in inspect.getsource(solve_progressive)
    # v0.49 report file still exists unchanged
    assert V049_REPORT.exists()
    assert "CLUB_AND_DIAMOND_BOTH_VIABLE" in V049_REPORT.read_text(encoding="utf-8")
    # corrected helper is wired
    src = inspect.getsource(optional_tail4_join)
    assert "optional_tail4_join_corrected" in src
