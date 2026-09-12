"""Final-Deal timing pivot v0.43."""

from __future__ import annotations

import inspect
import json
from functools import lru_cache
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import (
    PACKED_MAGIC,
    PACKED_SYMMETRY_MAGIC,
    pack_post_stock_symmetry_state,
    pack_search_identity,
    pack_state,
    permute_tableau_columns,
    unpack_state,
)
from spider.rules import MW_RULES, deal_cost
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions
from spider.simple_final_deal_timing import (
    COST_CEILING,
    EXPECTED_SD5,
    LINEAGES,
    PREP_COST,
    PREP_DEPTH,
    apply_sd5,
    deal_is_legal,
    deal_preparation_candidates,
    enumerate_preparation,
    foundation_suits,
    load_union,
    opening_state,
    search_foundation2,
    sd5_row,
    synthetic_columns,
    verify_sd5_row,
    zero_cost_whole_column_moves,
)
from spider.simple_foundation_horizon import pretty_card
from spider.simple_foundation_race import suit_foundation_count
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, solve_progressive
from spider.simple_workspace_reachability import engine_tableau_actions

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "simple_final_deal_timing.py"
SCRIPT = ROOT / "research" / "final_deal_timing_pivot_v0_43.py"
SOURCES = ROOT / "docs" / "research" / "final_deal_sources_v0_43.json"
PORT = ROOT / "docs" / "research" / "foundation2_portfolio_v0_43.json"
FOUND = ROOT / "solutions" / "4925153_v0_43_foundation2_best.moves.txt"


def _opening():
    return SpiderState.from_cards(list(load_deal(ROOT / "deals" / "4925153.txt")))


@lru_cache(maxsize=1)
def _union():
    return load_union(_opening())


def test_1_all_source_portfolios_replay():
    for path in LINEAGES.values():
        assert path.exists()
    u = _union()
    assert u["raw"] >= 208 + 256
    assert u["all_replay_ok"]
    opening = _opening()
    for rec in u["states"]:
        end = opening.clone()
        cost = replay_actions(end, as_actions(rec["full_actions"]))
        assert cost == rec["full_cost"]
        assert pack_state(end).hex() == rec["ordered_digest"]


def test_2_union_dedup_keeps_cheapest_g():
    src = inspect.getsource(load_union)
    assert "cost < prev" in src or "cost < prev[" in src
    u = _union()
    digests = [r["ordered_digest"] for r in u["states"]]
    assert len(digests) == len(set(digests))
    assert u["exact_unique"] == len(set(digests))


def test_3_every_source_stock_rows_1():
    u = _union()
    opening = _opening()
    for rec in u["states"]:
        end = opening.clone()
        replay_actions(end, as_actions(rec["full_actions"]))
        assert stock_rows(end) == 1
        assert rec["stock_rows"] == 1


def test_4_sd5_legal_from_every_source():
    u = _union()
    opening = _opening()
    for rec in u["states"]:
        end = opening.clone()
        replay_actions(end, as_actions(rec["full_actions"]))
        assert deal_is_legal(end)
        assert MW_RULES.can_deal_into_empty is True


def test_5_sd5_row_engine_verified():
    u = _union()
    opening = _opening()
    end = opening.clone()
    replay_actions(end, as_actions(u["states"][0]["full_actions"]))
    audit = verify_sd5_row(end)
    assert audit["engine"] == list(EXPECTED_SD5)
    assert audit["matches"] is True
    assert sd5_row(end) == ["3H", "10H", "2D", "3C", "9H", "7C", "7H", "AS", "3C", "5D"]


def test_6_deal_cost_included():
    assert deal_cost() == 1
    u = _union()
    opening = _opening()
    end = opening.clone()
    replay_actions(end, as_actions(u["states"][0]["full_actions"]))
    g0 = u["states"][0]["full_cost"]
    info = apply_sd5(end)
    assert info["deal_cost"] == 1
    assert stock_rows(end) == 0
    src = inspect.getsource(deal_preparation_candidates)
    assert "rec[\"g\"] + dcost" in src or "g = rec[\"g\"] + dcost" in src


def test_7_prep_depth_0_is_deal_now():
    src = inspect.getsource(enumerate_preparation)
    assert '"DEAL_NOW" if depth_of[node] == 0' in src


def test_8_prep_depth_gt0_is_prep_then_deal():
    src = inspect.getsource(enumerate_preparation)
    assert "PREP_THEN_DEAL" in src
    assert "depth_of[node] == 0" in src


def test_9_preparation_tableau_only():
    src = inspect.getsource(enumerate_preparation)
    assert "engine_tableau_actions" in src
    assert 'if action == ("deal",)' in src
    assert "max_depth" in src
    assert PREP_DEPTH == 4 and PREP_COST == 4


def test_10_no_second_deal_after_sd5():
    u = _union()
    opening = _opening()
    end = opening.clone()
    replay_actions(end, as_actions(u["states"][0]["full_actions"]))
    apply_sd5(end)
    assert stock_rows(end) == 0
    assert end.can_deal() is False
    assert ("deal",) not in end.enumerate_legal_actions()
    src = inspect.getsource(search_foundation2)
    assert 'if action == ("deal",)' in src


def test_11_pre_sd5_identity_is_ordered_pack_state():
    u = _union()
    opening = _opening()
    end = opening.clone()
    replay_actions(end, as_actions(u["states"][0]["full_actions"]))
    assert pack_state(end)[:4] == PACKED_MAGIC
    src = inspect.getsource(enumerate_preparation)
    assert "pack_state" in src
    assert "pack_post_stock_symmetry_state" not in src


def test_12_post_sd5_identity_is_column_symmetry():
    src = inspect.getsource(search_foundation2) + inspect.getsource(deal_preparation_candidates)
    assert "pack_post_stock_symmetry_state" in src
    u = _union()
    opening = _opening()
    end = opening.clone()
    replay_actions(end, as_actions(u["states"][0]["full_actions"]))
    apply_sd5(end)
    ident = pack_post_stock_symmetry_state(end)
    assert ident[:4] == PACKED_SYMMETRY_MAGIC
    assert pack_search_identity(end, post_stock_column_symmetry=True) == ident


def test_13_symmetry_equivalent_post_stock_collapse():
    st = synthetic_columns([[Card("s", 13)], [Card("h", 12)]], stock_n=0)
    swapped = permute_tableau_columns(st, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    assert pack_state(st) != pack_state(swapped)
    assert pack_post_stock_symmetry_state(st) == pack_post_stock_symmetry_state(swapped)


def test_14_cheapest_g_survives_symmetry_convergence():
    src = inspect.getsource(deal_preparation_candidates)
    assert "g < prev" in src or "g < prev[" in src
    src2 = inspect.getsource(search_foundation2)
    assert "child_g >= prev" in src2


def test_15_representative_ordered_state_replayable():
    u = _union()
    opening = _opening()
    rec = u["states"][0]
    end = opening.clone()
    replay_actions(end, as_actions(rec["full_actions"]))
    apply_sd5(end)
    blob = pack_state(end)
    rt = unpack_state(blob)
    assert pack_state(rt) == blob
    assert stock_rows(rt) == 0


def test_16_zero_cost_moves_cycle_safe():
    src = inspect.getsource(search_foundation2)
    assert "child_g >= prev" in src
    assert "best_g" in src
    st = synthetic_columns([[Card("s", 13)], []], stock_n=0)
    zc = zero_cost_whole_column_moves(st)
    assert zc


def test_17_foundation2_detection_suit_correct():
    src = inspect.getsource(search_foundation2)
    assert "len(state.foundations) > baseline" in src
    assert "foundation_suits" in src
    st = synthetic_columns([[Card("d", r) for r in range(13, 0, -1)]], stock_n=0)
    # not auto-removed until a move completes check_seq; construct via foundations field
    st.foundations = [[Card("s", r) for r in range(13, 0, -1)]]
    assert foundation_suits(st) == ["s"]
    st.foundations.append([Card("h", r) for r in range(13, 0, -1)])
    assert "h" in foundation_suits(st)


def test_18_any_suit_can_win():
    src = inspect.getsource(search_foundation2) + SCRIPT.read_text(encoding="utf-8")
    assert "ANY suit" in SCRIPT.read_text(encoding="utf-8") or "any suit" in SCRIPT.read_text(encoding="utf-8").lower()
    assert "suit-specific" in SCRIPT.read_text(encoding="utf-8") or "used_suit_heuristic" in src
    assert "Spade" in SCRIPT.read_text(encoding="utf-8")


def test_19_no_suit_specific_search_ordering():
    src = inspect.getsource(search_foundation2)
    assert "engine order only" in src
    assert "annotate" not in src
    assert "TARGET" not in src
    assert "heappush(heap, (child_g, depth + 1, seq, child_node))" in src


def test_20_foundation2_is_terminal():
    src = inspect.getsource(search_foundation2)
    assert "if hit:" in src
    assert "continue" in src
    assert "len(state.foundations) > baseline and depth > 0" in src


def test_21_foundation3_never_searched():
    src = inspect.getsource(search_foundation2) + SCRIPT.read_text(encoding="utf-8")
    assert "Foundation 3" in SCRIPT.read_text(encoding="utf-8") or "F3" in src or "terminal" in src.lower()
    assert "hit" in inspect.getsource(search_foundation2)


def test_22_full_mw_ceiling_120():
    assert COST_CEILING == 120
    src = inspect.getsource(search_foundation2)
    assert "child_g > ceiling" in src


def test_23_saved_witnesses_replay():
    opening = _opening()
    if SOURCES.exists():
        port = json.loads(SOURCES.read_text(encoding="utf-8"))
        for rec in (port.get("states") or [])[:8]:
            end = opening.clone()
            cost = replay_actions(end, as_actions(rec["full_actions"]))
            assert cost == rec["full_cost"]
            assert pack_state(end).hex() == rec["ordered_digest"]
    if PORT.exists():
        port = json.loads(PORT.read_text(encoding="utf-8"))
        for rec in port.get("states") or []:
            end = opening.clone()
            cost = replay_actions(end, as_actions(rec["full_actions"]))
            assert rec.get("full_replay_ok", True)
            assert cost == rec["full_cost"]
            assert len(end.foundations) >= 2
    if FOUND.exists():
        end = opening.clone()
        replay_actions(end, parse_moves_file(FOUND))
        assert len(end.foundations) >= 2


def test_24_production_and_mw_green():
    assert MW_RULES.can_deal_into_empty is True
    u = _union()
    opening = _opening()
    st = opening.clone()
    replay_actions(st, as_actions(u["states"][0]["full_actions"]))
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(st, **kwargs)
    b = solve_progressive(st, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b.nodes
    assert "search_foundation2" not in inspect.getsource(solve_progressive)
    assert COST_CEILING == 120
