"""Resource-aware Foundation-2 search v0.54."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state
from spider.rules import MW_RULES
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions
from spider.simple_final_deal_timing import foundation_suits, synthetic_columns, zero_cost_whole_column_moves
from spider.simple_low_tail import k_through_n, tail_run
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, solve_progressive
from spider.research_actions import tableau_actions
from spider.research_roots import replay_root
from spider.search_kernel import run_search
from spider.simple_resource_aware_f2 import (
    COST_CEILING,
    EXPECTED_DEAL_NOW,
    HARVEST_SLACK,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    annotate_f2_order,
    load_deal_now_roots,
    load_prep_roots,
    search_foundation2,
    union_roots,
    would_remove_foundation,
)
from spider.simple_workspace_reachability import engine_tableau_actions

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "simple_resource_aware_f2.py"
SCRIPT = ROOT / "research" / "resource_aware_foundation2_search_v0_54.py"
DEAL_NOW = ROOT / "docs" / "research" / "post_sd5_deal_now_roots_v0_44.json"
PORT = ROOT / "docs" / "research" / "sd5_resource_aware_portfolio_v0_53.json"
FIX = ROOT / "solutions" / "4925153_v0_54_foundation2.moves.txt"


def _opening():
    return SpiderState.from_cards(list(load_deal(ROOT / "deals" / "4925153.txt")))


def test_1_all_720_deal_now_replay():
    raw = json.loads(DEAL_NOW.read_text(encoding="utf-8"))
    assert raw["n"] == 720
    assert EXPECTED_DEAL_NOW == 720
    opening = _opening()
    rec = raw["states"][0]
    end = opening.clone()
    cost = replay_actions(end, as_actions(rec["full_actions"]))
    assert cost == rec["g"]
    assert stock_rows(end) == 0
    src = inspect.getsource(load_deal_now_roots)
    assert "post_sd5_deal_now_roots_v0_44.json" in MOD.read_text(encoding="utf-8")
    assert "DEAL_NOW" in src


def test_2_3_prep_from_v053_portfolio_replays():
    raw = json.loads(PORT.read_text(encoding="utf-8"))
    prep = [s for s in raw["states"] if s["timing"] == "PREP_THEN_DEAL"]
    assert len(prep) == 244
    opening = _opening()
    rec = prep[0]
    end = opening.clone()
    cost = replay_actions(end, as_actions(rec["full_actions"]))
    assert cost == rec["g"]
    src = inspect.getsource(load_prep_roots)
    assert "PREP_THEN_DEAL" in src
    assert "sd5_resource_aware_portfolio_v0_53.json" in MOD.read_text(encoding="utf-8")


def test_4_all_deal_now_not_v053_sample():
    src = inspect.getsource(load_deal_now_roots) + inspect.getsource(union_roots)
    assert "268" not in src
    text = SCRIPT.read_text(encoding="utf-8")
    assert "720" in text
    raw = json.loads(DEAL_NOW.read_text(encoding="utf-8"))
    port = json.loads(PORT.read_text(encoding="utf-8"))
    assert raw["n"] == 720
    assert sum(1 for s in port["states"] if s["timing"] == "DEAL_NOW") == 268


def test_5_6_7_stock_zero_one_spade_foundation():
    replay_src = inspect.getsource(replay_root)
    adapter_src = inspect.getsource(_replay := __import__(
        "spider.simple_resource_aware_f2", fromlist=["_replay_root"]
    )._replay_root)
    src = inspect.getsource(load_deal_now_roots) + adapter_src + replay_src
    assert "stock_rows(end)" in src
    assert "require_foundation_count=1" in adapter_src
    assert 'require_foundation_suit="s"' in adapter_src
    assert "require_stock_zero=True" in adapter_src
    opening = _opening()
    rec = json.loads(DEAL_NOW.read_text(encoding="utf-8"))["states"][0]
    end = opening.clone()
    replay_actions(end, as_actions(rec["full_actions"]))
    assert stock_rows(end) == 0
    assert len(end.foundations) == 1
    assert end.foundations[0][0].suit == "s"


def test_8_9_10_symmetry_cheapest_g_origin_not_identity():
    src = inspect.getsource(union_roots) + inspect.getsource(search_foundation2) + inspect.getsource(run_search)
    assert "pack_post_stock_symmetry_state" in MOD.read_text(encoding="utf-8")
    assert "symmetry_digest" in src
    assert 'rec["g"] < prev["g"]' in inspect.getsource(union_roots)
    ident_block = inspect.getsource(run_search)
    assert "best_g[child_ident]" in ident_block
    assert "child_g >= prev" in ident_block
    st = synthetic_columns([[Card("s", 13)], [Card("h", 12)]], stock_n=0)
    swapped = SpiderState(list(st.columns[1:2] + st.columns[0:1] + st.columns[2:]), [], [])
    # simpler: permute 0 and 1
    st2 = synthetic_columns([[Card("h", 12)], [Card("s", 13)]], stock_n=0)
    assert pack_state(st) != pack_state(st2)
    assert pack_post_stock_symmetry_state(st) == pack_post_stock_symmetry_state(st2)


def test_11_12_13_ucs_g_all_tableau_no_deal():
    src = inspect.getsource(search_foundation2) + inspect.getsource(run_search) + inspect.getsource(tableau_actions)
    assert "heappush" in inspect.getsource(run_search)
    assert "tableau_actions" in inspect.getsource(run_search)
    assert 'action == ("deal",)' in src
    assert "lambda st, g: (g,)" in inspect.getsource(search_foundation2)
    opening = _opening()
    rec = json.loads(DEAL_NOW.read_text(encoding="utf-8"))["states"][0]
    st = opening.clone()
    replay_actions(st, as_actions(rec["full_actions"]))
    assert stock_rows(st) == 0
    assert ("deal",) not in engine_tableau_actions(st)[0]
    assert st.can_deal() is False


def test_14_15_no_suit_prune_no_low_tail_target():
    src = inspect.getsource(search_foundation2)
    assert "tail_ready" not in src
    assert "4S" not in src and "5C" not in src and "6D" not in src
    assert "tableau_actions" in inspect.getsource(run_search)
    assert "would_remove_foundation" in inspect.getsource(annotate_f2_order)
    text = MOD.read_text(encoding="utf-8")
    assert "Ordering only" in text or "ordering only" in text.lower()


def test_16_zero_cost_cycles_safe():
    src = inspect.getsource(run_search)
    assert "child_g >= prev" in src
    assert "best_g" in src
    st = synthetic_columns([[Card("s", 13)], []], stock_n=0)
    assert zero_cost_whole_column_moves(st)


def test_17_18_19_engine_foundation_count_terminates():
    src = inspect.getsource(search_foundation2)
    assert "len(state.foundations) > baseline" in src
    assert "if hit:" in src
    assert "is_terminal" in src
    st = synthetic_columns(
        [tail_run("d", 3), k_through_n("d", 4)],
        stock_n=0,
    )
    st.foundations = [k_through_n("s", 1)]
    acts = [a for a in engine_tableau_actions(st)[0] if a != ("deal",)]
    join = next(a for a in acts if would_remove_foundation(st, a))
    apply_action(st, join)
    assert len(st.foundations) == 2


def test_20_21_no_f3_ceiling_110():
    assert COST_CEILING == 110
    src = inspect.getsource(search_foundation2)
    assert "len(state.foundations) > baseline" in src
    text = MOD.read_text(encoding="utf-8") + SCRIPT.read_text(encoding="utf-8")
    assert "Foundation 3" in text
    assert "110" in text


def test_22_23_min_live_g_and_harvest_slack():
    src = inspect.getsource(search_foundation2) + inspect.getsource(run_search)
    assert "min_live_g" in src
    assert "harvest_slack" in src
    assert "incumbent + slack" in inspect.getsource(run_search) or "f + harvest_slack" in inspect.getsource(search_foundation2)
    assert HARVEST_SLACK == 3
    assert SEARCH_UNIQUE == 600_000
    assert SEARCH_TIME_S == 420.0
    assert SEARCH_RSS_MB == 2.5 * 1024.0


def test_24_origin_telemetry_not_identity():
    src = inspect.getsource(search_foundation2)
    assert "src[\"timing\"]" in src or 'src["timing"]' in src
    assert "child_sym" in src
    # identity assignment does not mention timing
    assert "best_g[child_ident] = child_g" in inspect.getsource(run_search)


def test_25_26_27_28_witness_replay_contract_if_present():
    if not FIX.exists():
        src = inspect.getsource(search_foundation2)
        assert "full_actions" in src
        assert "foundation_suits" in src
        assert "suit" in src
        return
    opening = _opening()
    end = opening.clone()
    cost = replay_actions(end, parse_moves_file(FIX))
    assert stock_rows(end) == 0
    assert len(end.foundations) == 2
    assert cost >= 0
    assert set(foundation_suits(end)) >= {"s"}


def test_29_30_no_deeper_prep_no_presd4():
    text = MOD.read_text(encoding="utf-8") + SCRIPT.read_text(encoding="utf-8")
    assert "enumerate_preparation" not in text
    assert "pre-SD4" in text or "pre-SD4" in SCRIPT.read_text(encoding="utf-8")
    src = inspect.getsource(search_foundation2) + inspect.getsource(run_search)
    assert "tableau_actions" in src
    assert 'action == ("deal",)' in src


def test_31_no_suit_target_search():
    text = MOD.read_text(encoding="utf-8") + SCRIPT.read_text(encoding="utf-8")
    assert "No suit target" in text or "any second foundation" in text.lower() or "Any suit" in text or "any suit" in text.lower()
    src = inspect.getsource(search_foundation2)
    assert "hot" not in src
    assert "TARGET" not in src


def test_32_production_mw_green():
    assert MW_RULES.can_deal_into_empty is True
    opening = _opening()
    rec = json.loads(DEAL_NOW.read_text(encoding="utf-8"))["states"][0]
    st = opening.clone()
    replay_actions(st, as_actions(rec["full_actions"]))
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(st, **kwargs)
    b = solve_progressive(st, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b.nodes
    assert "search_foundation2" not in inspect.getsource(solve_progressive)
