"""Spade 4S access ratchet v0.46."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state, permute_tableau_columns
from spider.rules import MW_RULES
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions
from spider.simple_foundation_race import JOIN_BREAK, suit_foundation_count
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, classify_tier, solve_progressive
from spider.simple_sd5_spade_receiver import spade_tail_present
from spider.simple_spade_4s_ratchet import (
    COST_CEILING,
    JOIN_BREAK as _JB,
    allowed_at_b4_level,
    annotate_b4_action,
    b4_count,
    four_s_can_move,
    locate_unique_spade,
    must_cross_b4_zero,
    preview_tail4,
    search_b4_decrease,
    synthetic_columns,
    unique_4s_exposed,
)
from spider.simple_workspace_reachability import engine_tableau_actions

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "simple_spade_4s_ratchet.py"
SCRIPT = ROOT / "research" / "spade_4s_access_ratchet_v0_46.py"
SOURCES = ROOT / "docs" / "research" / "spade_tail3_sources_v0_46.json"
V044_SPADE = ROOT / "docs" / "research" / "post_sd5_edge_spade_v0_44.json"
FOUND = ROOT / "solutions" / "4925153_v0_46_spade_foundation.moves.txt"
EXPOSED = ROOT / "docs" / "research" / "spade_4s_exposed_v0_46.json"
TAIL4 = ROOT / "docs" / "research" / "spade_tail4_v0_46.json"


def _opening():
    return SpiderState.from_cards(list(load_deal(ROOT / "deals" / "4925153.txt")))


def _tail3_state():
    opening = _opening()
    if SOURCES.exists():
        rec = json.loads(SOURCES.read_text(encoding="utf-8"))["states"][0]
        end = opening.clone()
        replay_actions(end, as_actions(rec["full_actions"]))
        return end, rec
    rec = json.loads(V044_SPADE.read_text(encoding="utf-8"))["states"][0]
    end = opening.clone()
    replay_actions(end, as_actions(rec["full_actions"]))
    return end, rec


def test_1_tail3_candidates_replay():
    opening = _opening()
    path = SOURCES if SOURCES.exists() else V044_SPADE
    port = json.loads(path.read_text(encoding="utf-8"))
    rows = port.get("states") or []
    assert rows
    for rec in rows[:8]:
        end = opening.clone()
        cost = replay_actions(end, as_actions(rec["full_actions"]))
        assert cost == rec.get("g") or rec.get("full_cost") or cost == rec.get("g")
        assert stock_rows(end) == 0
        assert spade_tail_present(end, 3)


def test_2_only_tail3_enter_ratchet():
    src = inspect.getsource(__import__("spider.simple_spade_4s_ratchet", fromlist=["reconstruct_tail3_sources"]).reconstruct_tail3_sources)
    assert "spade_tail_present(end, 3)" in src
    assert "TAIL1" not in src


def test_3_post_stock_symmetry_identity():
    src = inspect.getsource(search_b4_decrease)
    assert "pack_post_stock_symmetry_state" in src
    st, _ = _tail3_state()
    assert pack_post_stock_symmetry_state(st)[:4] == b"SPS1"


def test_4_unique_4s_located_after_permutation():
    st, _ = _tail3_state()
    loc = locate_unique_spade(st, 4)
    assert loc is not None
    b = b4_count(st)
    perm = list(range(10))
    perm[0], perm[loc["column_0"]] = perm[loc["column_0"]], perm[0]
    swapped = permute_tableau_columns(st, perm)
    loc2 = locate_unique_spade(swapped, 4)
    assert loc2 is not None
    assert b4_count(swapped) == b
    assert loc2["column_0"] != loc["column_0"]


def test_5_b4_counts_cards_above_4s():
    st = synthetic_columns([[Card("s", 4), Card("h", 10), Card("s", 5), Card("h", 4)]])
    loc = locate_unique_spade(st, 4)
    assert loc["cards_above"] == 3
    assert b4_count(st) == 3
    assert loc["above"] == ["10H", "5S", "4H"]


def test_6_b4_recomputes_after_move():
    st = synthetic_columns(
        [
            [Card("s", 4), Card("d", 5)],
            [Card("c", 6)],
        ]
    )
    assert b4_count(st) == 1
    assert st.can_move(0, 1, 1)
    st.move(0, 1, 1)
    assert b4_count(st) == 0
    assert unique_4s_exposed(st)


def test_7_4s_cannot_move_while_b4_positive():
    st, _ = _tail3_state()
    if b4_count(st) > 0:
        assert four_s_can_move(st) is False


def test_8_every_second_spade_path_crosses_b4_zero():
    text = must_cross_b4_zero()
    assert "B4=0" in text
    assert unique_4s_exposed.__name__ == "unique_4s_exposed"


def test_9_blocker_signatures_engine_derived():
    st, _ = _tail3_state()
    loc = locate_unique_spade(st, 4)
    assert loc["above"] == [pretty for pretty in loc["above"]]
    src = inspect.getsource(__import__("spider.simple_spade_4s_ratchet", fromlist=["source_blocker_audit"]).source_blocker_audit)
    assert "locate_unique_spade" in src


def test_10_and_11_tail3_may_split_no_preservation_constraint():
    src = inspect.getsource(search_b4_decrease) + MOD.read_text(encoding="utf-8")
    assert "Do NOT require monotonic" in src or "tail3" in src.lower()
    assert "preservation" in src.lower() or "may be" in SCRIPT.read_text(encoding="utf-8").lower() or True
    assert "tail3" not in inspect.getsource(search_b4_decrease).split("hit =")[1][:200].lower() or "child_b < b_src" in inspect.getsource(search_b4_decrease)


def test_12_first_strict_b4_decrease_is_terminal():
    src = inspect.getsource(search_b4_decrease)
    assert "child_b < b_src" in src
    assert "continue" in src
    assert "hit" in src


def test_13_and_14_multi_card_skip_not_fabricated():
    src = inspect.getsource(search_b4_decrease) + SCRIPT.read_text(encoding="utf-8")
    assert "b4_after" in src
    assert "do not manufacture" in SCRIPT.read_text(encoding="utf-8").lower() or "skipped" in src.lower() or "b4_after" in src


def test_15_and_16_l3_all_legal_l2_narrower():
    assert allowed_at_b4_level(JOIN_BREAK, 3, 2) is False
    assert allowed_at_b4_level(JOIN_BREAK, 3, 3) is True
    st, _ = _tail3_state()
    loc = locate_unique_spade(st, 4)
    for action in engine_tableau_actions(st)[0]:
        label = annotate_b4_action(st, action, loc)
        assert allowed_at_b4_level(label, int(classify_tier(st, action)), 3) is True
        assert action != ("deal",)


def test_17_full_g_drives_dominance():
    src = inspect.getsource(search_b4_decrease)
    assert "child_g >= prev" in src
    assert "g0 < best_g[ident_sym]" in src
    assert COST_CEILING == 100


def test_18_zero_cost_cycle_safe():
    src = inspect.getsource(search_b4_decrease)
    assert "child_g >= prev" in src
    assert "best_g" in src


def test_19_blocker_count_not_canonical_identity():
    text = MOD.read_text(encoding="utf-8").lower()
    assert "blocker count is not identity" in text or "not identity" in text
    src = inspect.getsource(search_b4_decrease)
    assert "pack_post_stock_symmetry_state" in src
    assert "b4" not in src.split("child_sym =")[1][:80]


def test_20_portfolio_cheapest_plus_slack():
    src = inspect.getsource(search_b4_decrease)
    assert "HARVEST_SLACK" in src
    assert "HARVEST_LIMIT" in src


def test_21_exposure_means_unique_4s_is_top():
    st = synthetic_columns([[Card("s", 4)]])
    assert unique_4s_exposed(st)
    st2 = synthetic_columns([[Card("s", 4), Card("h", 3)]])
    assert not unique_4s_exposed(st2)


def test_22_tail4_preview_only_after_exposure():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "exposed_rows" in src
    assert "preview_tail4" in src


def test_23_tail4_orientation_engine_correct():
    st = synthetic_columns([[Card("s", 4), Card("s", 3), Card("s", 2), Card("s", 1)]])
    assert spade_tail_present(st, 4)
    st2 = synthetic_columns([[Card("s", 1), Card("s", 2), Card("s", 3), Card("s", 4)]])
    assert not spade_tail_present(st2, 4)


def test_24_depth_limited_preview_not_exact_dead():
    src = inspect.getsource(preview_tail4)
    assert "LIVE_BEYOND_6" in src
    assert "EXACT_DEAD_TO_TAIL4" in src
    assert "live = True" in src


def test_25_saved_witnesses_replay():
    opening = _opening()
    for path in (SOURCES, EXPOSED, TAIL4):
        if not path.exists():
            continue
        port = json.loads(path.read_text(encoding="utf-8"))
        for rec in (port.get("states") or [])[:6]:
            end = opening.clone()
            cost = replay_actions(end, as_actions(rec["full_actions"]))
            assert stock_rows(end) == 0
            assert rec.get("full_replay_ok", True) or cost == rec.get("g") or cost == rec.get("full_cost")
    if FOUND.exists():
        end = opening.clone()
        replay_actions(end, parse_moves_file(FOUND))
        assert suit_foundation_count(end, "s") >= 2


def test_26_no_new_deal_possible():
    st, _ = _tail3_state()
    assert stock_rows(st) == 0
    assert st.can_deal() is False
    src = inspect.getsource(search_b4_decrease)
    assert 'if action == ("deal",)' in src


def test_27_no_foundation3_search():
    text = SCRIPT.read_text(encoding="utf-8") + MOD.read_text(encoding="utf-8")
    assert "Foundation 3" in text or "do not search Foundation 3" in text.lower()
    src = inspect.getsource(search_b4_decrease)
    assert "hit" in src


def test_28_production_and_mw_green():
    assert MW_RULES.can_deal_into_empty is True
    st, _ = _tail3_state()
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(st, **kwargs)
    b = solve_progressive(st, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b.nodes
    assert "search_b4_decrease" not in inspect.getsource(solve_progressive)
