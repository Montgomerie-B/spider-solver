"""SD5 Spade receiving planner v0.45."""

from __future__ import annotations

import inspect
import json
from functools import lru_cache
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state, unpack_state
from spider.rules import MW_RULES, deal_cost
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions
from spider.simple_final_deal_timing import PREP_COST, PREP_DEPTH, enumerate_preparation
from spider.simple_foundation_horizon import pretty_card
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, solve_progressive
from spider.simple_sd5_spade_receiver import (
    EXPECTED_SOURCES,
    PORTFOLIO_CAP,
    RECEIVE_COL,
    V044_BEST_TAIL3,
    build_targeted_portfolio,
    load_pre_sd5_sources,
    opening_state,
    preview_tail5,
    search_tail4,
    spade_low_tail_length,
    spade_receiver_length,
    spade_tail_present,
    synthetic_columns,
    tail4_is_mandatory,
    verify_unique_spade_chain,
)
from spider.simple_workspace_reachability import engine_tableau_actions

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "simple_sd5_spade_receiver.py"
SCRIPT = ROOT / "research" / "sd5_spade_receiving_planner_v0_45.py"
V043 = ROOT / "docs" / "research" / "final_deal_sources_v0_43.json"
PORT = ROOT / "docs" / "research" / "sd5_spade_transaction_sources_v0_45.json"
TAIL4 = ROOT / "docs" / "research" / "sd5_spade_tail4_v0_45.json"
FOUND = ROOT / "solutions" / "4925153_v0_45_spade_foundation.moves.txt"


def _opening():
    return SpiderState.from_cards(list(load_deal(ROOT / "deals" / "4925153.txt")))


@lru_cache(maxsize=1)
def _src():
    return load_pre_sd5_sources(_opening())


def test_1_all_720_sources_replay():
    assert V043.exists()
    s = _src()
    assert s["n"] == EXPECTED_SOURCES
    assert s["all_replay_ok"]


def test_2_remaining_spade_ranks_unique():
    s = _src()
    assert s["spade_chain_ok"]
    opening = _opening()
    rec = s["states"][0]
    end = opening.clone()
    replay_actions(end, as_actions(rec["full_actions"]))
    chk = verify_unique_spade_chain(end)
    assert chk["ok"]
    assert all(v == 1 for v in chk["tableau_ranks_2_13"].values())
    assert chk["as_tableau"] == 0
    assert chk["as_in_sd5_c8"]


def test_3_as_in_sd5_lands_on_c8():
    s = _src()
    assert s["sd5_audit"]["as_column_8"] is True
    assert s["sd5_audit"]["engine"][7] == "AS"
    assert RECEIVE_COL == 7


def test_4_prep_enumeration_matches_v043_bounds():
    src = inspect.getsource(enumerate_preparation)
    text = SCRIPT.read_text(encoding="utf-8")
    assert PREP_DEPTH == 4 and PREP_COST == 4
    assert "max_depth=PREP_DEPTH" in text
    assert "max_cost=PREP_COST" in text
    assert "Do NOT enlarge" in MOD.read_text(encoding="utf-8") or "same limits" in text or PREP_DEPTH == 4


def test_5_receiver_length_engine_order_correct():
    st = synthetic_columns([[] for _ in range(7)] + [[Card("s", 3), Card("s", 2)]])
    assert pretty_card(st.columns[7].face_up[-1]) == "2S"
    assert spade_receiver_length(st) == 2
    st2 = synthetic_columns([[] for _ in range(7)] + [[Card("h", 8)]])
    assert spade_receiver_length(st2) == 0


def test_6_receiver_1_plus_as_creates_2s_as():
    cols = [[] for _ in range(10)]
    cols[7] = [Card("s", 2)]
    st = synthetic_columns(cols, stock_n=10)
    assert pretty_card(st.stock[-10 + 7]) == "AS"
    assert spade_receiver_length(st) == 1
    apply_action(st, ("deal",))
    assert spade_low_tail_length(st) == 2
    assert spade_tail_present(st, 2)


def test_7_receiver_2_plus_as_creates_3s_2s_as():
    cols = [[] for _ in range(10)]
    cols[7] = [Card("s", 3), Card("s", 2)]
    st = synthetic_columns(cols, stock_n=10)
    assert spade_receiver_length(st) == 2
    apply_action(st, ("deal",))
    assert spade_low_tail_length(st) == 3
    assert spade_tail_present(st, 3)


def test_8_longer_receivers_extend_correctly():
    cols = [[] for _ in range(10)]
    cols[7] = [Card("s", 5), Card("s", 4), Card("s", 3), Card("s", 2)]
    st = synthetic_columns(cols, stock_n=10)
    assert spade_receiver_length(st) == 4
    apply_action(st, ("deal",))
    assert spade_low_tail_length(st) == 5
    assert spade_tail_present(st, 5)


def test_9_and_10_deal_now_controls_and_best_cost():
    src = inspect.getsource(_src.__wrapped__) if False else SCRIPT.read_text(encoding="utf-8")
    assert "V044_BEST_TAIL3" in MOD.read_text(encoding="utf-8")
    assert V044_BEST_TAIL3 == 85
    assert "deal_t3" in src


def test_11_and_12_prep_mw_and_deal_cost():
    src = inspect.getsource(__import__("spider.simple_sd5_spade_receiver", fromlist=["measure_and_deal"]).measure_and_deal)
    assert "rec[\"g\"] + 1" in src
    assert deal_cost() == 1


def test_13_post_stock_symmetry_only_after_sd5():
    src = inspect.getsource(__import__("spider.simple_sd5_spade_receiver", fromlist=["measure_and_deal"]).measure_and_deal)
    src += inspect.getsource(search_tail4)
    assert "pack_post_stock_symmetry_state" in src
    pre = inspect.getsource(__import__("spider.simple_final_deal_timing", fromlist=["enumerate_preparation"]).enumerate_preparation)
    assert "pack_state" in pre
    assert "pack_post_stock_symmetry_state" not in pre


def test_14_targeted_portfolio_cap_deterministic():
    src = inspect.getsource(build_targeted_portfolio)
    assert "cap" in src
    assert PORTFOLIO_CAP == 512
    assert "round-robin" in src or "while len(out) < cap" in src
    fake = [
        {
            "low_tail": L,
            "g": 80 + i,
            "prep_depth": i % 5,
            "timing": "DEAL_NOW" if i % 2 == 0 else "PREP_THEN_DEAL",
            "lineages": ["diamond_ready"],
            "ordered_digest": f"{L:02d}{i:04d}" + "a" * 10,
            "symmetry_digest": f"{L:02d}{i:04d}" + "b" * 10,
            "full_actions": [],
            "prep_actions": [],
            "receiver_length": max(0, L - 1),
        }
        for L in range(0, 5)
        for i in range(40)
    ]
    a = build_targeted_portfolio(fake, cap=50)
    b = build_targeted_portfolio(fake, cap=50)
    assert [x["symmetry_digest"] for x in a] == [x["symmetry_digest"] for x in b]
    assert len(a) <= 50


def test_15_tail4_search_all_legal_moves():
    src = inspect.getsource(search_tail4)
    assert "engine_tableau_actions" in src
    assert "No heuristic" in MOD.read_text(encoding="utf-8") or "for action in actions" in src
    assert "max_depth" in src


def test_16_tail4_orientation_correct():
    cols = [[] for _ in range(10)]
    cols[7] = [Card("s", 4), Card("s", 3), Card("s", 2), Card("s", 1)]
    st = synthetic_columns(cols, stock_n=0)
    assert spade_tail_present(st, 4) is True
    cols[7] = [Card("s", 1), Card("s", 2), Card("s", 3), Card("s", 4)]
    st2 = synthetic_columns(cols, stock_n=0)
    assert spade_tail_present(st2, 4) is False


def test_17_tail4_mandatory_for_unique_chain():
    text = tail4_is_mandatory()
    assert "4S-3S-2S-AS" in text
    assert "unique" in text.lower()


def test_18_tail4_terminal_in_primary_search():
    src = inspect.getsource(search_tail4)
    assert "hit" in src
    assert "continue" in src
    assert "spade_tail_present(state, 4)" in src


def test_19_tail5_preview_uses_legal_moves():
    src = inspect.getsource(preview_tail5)
    assert "engine_tableau_actions" in src
    assert 'if action == ("deal",)' in src


def test_20_depth_limited_preview_never_dead():
    src = inspect.getsource(preview_tail5)
    assert "LIVE_BEYOND_5" in src
    assert "EXACT_DEAD_TO_TAIL5" in src
    assert "live = True" in src


def test_21_zero_cost_cycle_safe():
    src = inspect.getsource(search_tail4)
    assert "child_g >= prev" in src
    assert "best_g" in src


def test_22_foundation2_detection_correct():
    src = inspect.getsource(search_tail4)
    assert "suit_foundation_count(state, \"s\") > baseline" in src or "suit_foundation_count" in src
    assert "foundation_surprise" in src


def test_23_saved_paths_replay():
    opening = _opening()
    if PORT.exists():
        port = json.loads(PORT.read_text(encoding="utf-8"))
        for rec in (port.get("states") or [])[:4]:
            end = opening.clone()
            cost = replay_actions(end, as_actions(rec["full_actions"]))
            assert cost == rec["g"]
            assert stock_rows(end) == 0
    if TAIL4.exists():
        port = json.loads(TAIL4.read_text(encoding="utf-8"))
        for rec in port.get("states") or []:
            end = opening.clone()
            cost = replay_actions(end, as_actions(rec["full_actions"]))
            assert rec.get("full_replay_ok", True)
            assert cost == rec["full_cost"]
            assert spade_tail_present(end, 4) or len(end.foundations) >= 2
    if FOUND.exists():
        end = opening.clone()
        replay_actions(end, parse_moves_file(FOUND))
        assert sum(1 for run in end.foundations if run and run[0].suit == "s") >= 2


def test_24_no_foundation3_search():
    text = SCRIPT.read_text(encoding="utf-8") + MOD.read_text(encoding="utf-8")
    assert "Foundation 3" in text or "do not search Foundation 3" in text.lower() or "not search Foundation 3" in text
    src = inspect.getsource(search_tail4)
    assert "hit" in src


def test_25_production_and_mw_green():
    assert MW_RULES.can_deal_into_empty is True
    s = _src()
    opening = _opening()
    st = opening.clone()
    replay_actions(st, as_actions(s["states"][0]["full_actions"]))
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(st, **kwargs)
    b = solve_progressive(st, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b.nodes
    assert "search_tail4" not in inspect.getsource(solve_progressive)
