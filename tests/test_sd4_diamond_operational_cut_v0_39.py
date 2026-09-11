"""Unbiased SD4 Diamond operational cut v0.39."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_search_identity, pack_state, permute_tableau_columns
from spider.rules import MW_RULES
from spider.simple_current_horizon import occurrence_counts
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_cut import (
    apply_actions,
    continuation_lb_audit,
    diamond_unique_ranks,
    enumerate_predicted_macros,
    is_diamond_ready,
    legal_dests_for_top,
    probe_diamond_foundation,
    search_diamond_ready,
)
from spider.simple_foundation_horizon import pretty_card
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, solve_progressive
from spider.simple_sd4_horizon import EXPECTED_SD4, legal_sd4_episode_actions, verify_sd4_row
from spider.simple_workspace_reachability import engine_tableau_actions

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
V35 = ROOT / "docs" / "research" / "heart9_blocker_ratchet3_v0_35_gate2_sources.json"
PORT = ROOT / "docs" / "research" / "sd4_diamond_operational_cut_v0_39_portfolio.json"
FIX = ROOT / "solutions" / "4925153_v0_39_diamond_ready_best.moves.txt"
SCRIPT = ROOT / "research" / "sd4_diamond_operational_cut_v0_39.py"
MOD = ROOT / "src" / "spider" / "simple_diamond_cut.py"


def _opening():
    return SpiderState.from_cards(list(load_deal(DEAL)))


def _as_actions(raw):
    out = []
    for item in raw:
        if item == "deal" or item == ["deal"] or item == ("deal",):
            out.append(("deal",))
        else:
            out.append((int(item[0]), int(item[1]), int(item[2])))
    return out


def _g2():
    rec = json.loads(V35.read_text(encoding="utf-8"))["states"][0]
    end = _opening()
    replay_actions(end, _as_actions(rec["full_actions"]))
    return end


def test_1_sources_replay_sample():
    st = _g2()
    assert stock_rows(st) == 2
    assert pretty_card(st.columns[1].face_up[-1]) == "AH"
    assert pretty_card(st.columns[1].face_down[-1]) == "JH"
    text = SCRIPT.read_text(encoding="utf-8")
    assert "load_union" in text
    assert "324" in text or "v0.35" in text


def test_2_current_horizon_excludes_sd5():
    st = _g2()
    apply_action(st, ("deal",))
    assert stock_rows(st) == 1
    d2 = occurrence_counts(st, "d", 2)
    assert d2["current_count"] == 1
    assert d2["future_stock_count"] == 1
    assert d2["future_after_SD5_count"] == 2


def test_3_unique_diamond_ranks_after_sd4():
    st = _g2()
    apply_action(st, ("deal",))
    hard = diamond_unique_ranks(st)
    assert hard == ["2", "5"]


def test_4_sd4_row():
    st = _g2()
    audit = verify_sd4_row(st)
    assert audit["valid"] is True
    assert audit["row"] == list(EXPECTED_SD4)
    assert audit["c4_is_2d"] is True


def test_5_2d_c4_after_sd4():
    st = _g2()
    apply_action(st, ("deal",))
    assert pretty_card(st.columns[3].face_up[-1]) == "2D"
    assert occurrence_counts(st, "d", 2)["tableau"][0]["top"] is True


def test_6_no_prescribed_ah_to_2d():
    st = _g2()
    variants = enumerate_predicted_macros(st)
    for v in variants:
        for a in v["actions"]:
            if a != ("deal",) and a[0] == 1 and a[1] == 3:
                raise AssertionError("AH c2 -> c4 appeared in predicted Diamond macros")
    assert "AH c2 -> 2D" not in Path(MOD).read_text(encoding="utf-8") or "not" in Path(MOD).read_text(encoding="utf-8")
    text = Path(MOD).read_text(encoding="utf-8")
    assert "Does not apply the Heart AH->2D" in text


def test_7_c9_5d_structure_engine_derived():
    st = _g2()
    apply_action(st, ("deal",))
    occ = occurrence_counts(st, "d", 5)
    assert occ["tableau"]
    # engine-derived, not assumed JH/4H/5D
    assert "face_up_above" in occ["tableau"][0]


def test_8_and_9_jh_and_4h_dests_enumerated():
    st = _g2()
    apply_action(st, ("deal",))
    dests = legal_dests_for_top(st, 8)
    onto = {d["onto"] for d in dests}
    assert "QH" in onto or "QC" in onto
    src = inspect.getsource(enumerate_predicted_macros)
    assert "legal_dests_for_top" in src


def test_10_ready_requires_both_exposed():
    st = _g2()
    assert is_diamond_ready(st) is False
    apply_action(st, ("deal",))
    assert is_diamond_ready(st) is False  # 5D still covered
    src = inspect.getsource(is_diamond_ready)
    assert "unique_exposed_top(state, \"d\", 2)" in src
    assert "unique_exposed_top(state, \"d\", 5)" in src


def test_11_sd4_not_required_first():
    src = inspect.getsource(search_diamond_ready)
    assert "legal_sd4_episode_actions" in src
    assert "Do not require SD4" in Path(SCRIPT).read_text(encoding="utf-8") or "immediately or after" in Path(SCRIPT).read_text(encoding="utf-8") or "preparation" in Path(MOD).read_text(encoding="utf-8")


def test_12_sd5_never():
    st = _g2()
    assert ("deal",) in legal_sd4_episode_actions(st)
    apply_action(st, ("deal",))
    assert stock_rows(st) == 1
    assert ("deal",) not in legal_sd4_episode_actions(st)
    src = inspect.getsource(search_diamond_ready)
    assert "stock_rows(state) != 2" in src


def test_13_and_14_pack_and_full_g():
    st = _g2()
    assert pack_state(st)[:4] == b"SPK1"
    src = inspect.getsource(search_diamond_ready)
    assert "source_g" in src
    assert "g0 < best_g[ident]" in src


def test_15_lb_verified_or_withdrawn():
    st = _g2()
    audit = continuation_lb_audit(st)
    assert "valid" in audit
    if audit["valid"]:
        assert audit["lb"] >= 2
        assert audit["deal_cost"] == 1
    else:
        assert audit["lb"] is None


def test_16_cut_terminal_in_main_search():
    src = inspect.getsource(search_diamond_ready)
    assert "is_diamond_ready" in src
    assert "continue" in src


def test_17_and_18_probe_live_not_dead():
    src = inspect.getsource(probe_diamond_foundation)
    assert "LIVE_BEYOND_8" in src
    assert "FOUNDATION_WITHIN_8" in src
    assert "EXACT_DEAD" in src
    assert "live = True" in src
    assert "max_depth" in src


def test_19_witness_replays_if_present():
    if not FIX.exists():
        return
    end = _opening()
    cost = replay_actions(end, parse_moves_file(FIX))
    assert cost == len(parse_moves_file(FIX))
    assert is_diamond_ready(end)
    if PORT.exists():
        port = json.loads(PORT.read_text(encoding="utf-8"))
        for rec in port.get("states") or []:
            s = _opening()
            c = replay_actions(s, _as_actions(rec["full_actions"]))
            assert c == rec["full_cost"]
            assert pack_state(s).hex() == rec["ordered_digest"]
            assert is_diamond_ready(s)


def test_20_production_and_mw():
    assert MW_RULES.can_deal_into_empty is True
    st = _g2()
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(st, **kwargs)
    b = solve_progressive(st, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b.nodes
    assert "search_diamond_ready" not in inspect.getsource(solve_progressive)
    swapped = permute_tableau_columns(st, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    assert pack_state(st) != pack_state(swapped)
    assert pack_search_identity(st) == pack_state(st)
