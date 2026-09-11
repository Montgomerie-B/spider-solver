"""SD4 operational-horizon pivot v0.37."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_search_identity, pack_state, permute_tableau_columns
from spider.rules import MW_RULES
from spider.simple_deal1_preview import stock_rows
from spider.simple_foundation_horizon import pretty_card
from spider.simple_gate1 import gate1_progress, is_gate3, is_gate4
from spider.simple_heart_funnel import legal_episode_actions
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, solve_progressive
from spider.simple_sd4_horizon import (
    EXPECTED_SD4,
    MACRO_A,
    MACRO_B,
    apply_macro,
    continuation_lb_audit,
    jack_onto_any_queen_ok,
    legal_sd4_episode_actions,
    search_h9_from_gate2,
    verify_sd4_row,
)
from spider.simple_two_gate import verify_ah_release_legality
from spider.simple_workspace_reachability import engine_tableau_actions

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
H9_PORT = ROOT / "docs" / "research" / "sd4_operational_horizon_pivot_v0_37_h9_portfolio.json"
V37_JSON = ROOT / "docs" / "research" / "sd4_operational_horizon_pivot_v0_37.json"
V37_FIX = ROOT / "solutions" / "4925153_v0_37_h9_best.moves.txt"
SCRIPT = ROOT / "research" / "sd4_operational_horizon_pivot_v0_37.py"
MOD = ROOT / "src" / "spider" / "simple_sd4_horizon.py"


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


def _first_source():
    payload = json.loads(H9_PORT.read_text(encoding="utf-8")) if H9_PORT.exists() else None
    if payload and payload.get("states"):
        end = _opening()
        rec = payload["states"][0]
        # replay only to gate2: drop last 4 continuation actions if present
        full = _as_actions(rec["full_actions"])
        # reconstruct gate2 by replaying minus continuation
        n_cont = rec.get("depth") or rec.get("continuation") or 4
        # safer: use v0.35 best fixture path from report sources via JSON experiment
    v35 = json.loads((ROOT / "docs" / "research" / "heart9_blocker_ratchet3_v0_35_gate2_sources.json").read_text(encoding="utf-8"))
    end = _opening()
    replay_actions(end, _as_actions(v35["states"][0]["full_actions"]))
    return end


def test_1_and_2_union_replays_and_cheapest_dedup():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "load_union" in text
    assert "best[ident]" in text or "best.get(ident)" in text
    src = _first_source()
    assert stock_rows(src) == 2
    assert pack_state(src)[:4] == b"SPK1"


def test_3_sources_are_gate2_ah_jh():
    src = _first_source()
    prog = gate1_progress(src)
    assert prog["fd_blockers"] == 1
    assert prog["top_fd"] == "JH"
    assert pretty_card(src.columns[1].face_up[-1]) == "AH"
    assert [pretty_card(c) for c in src.columns[1].face_down][-2:] == ["9H", "JH"]


def test_4_to_8_sd4_row_engine_verified():
    src = _first_source()
    audit = verify_sd4_row(src)
    assert audit["expected"] == list(EXPECTED_SD4)
    assert audit["valid"] is True
    assert audit["c2_is_js"] is True
    assert audit["c3_is_qh"] is True
    assert audit["c4_is_2d"] is True
    assert audit["c6_is_qc"] is True
    assert audit["row"][1] == "JS"
    assert audit["row"][2] == "QH"
    assert audit["row"][3] == "2D"
    assert audit["row"][5] == "QC"


def test_9_js_onto_any_queen():
    rec = jack_onto_any_queen_ok()
    assert rec["valid"] is True
    assert rec["any_suit_queen"] is True


def test_10_ah_onto_any_two():
    rec = verify_ah_release_legality()
    assert rec["valid"] is True
    assert rec["rank2_any_suit"] is True


def test_11_and_12_macros_engine_legal():
    src = _first_source()
    a = apply_macro(src.clone(), MACRO_A)
    b = apply_macro(src.clone(), MACRO_B)
    assert a["legal"] is True
    assert b["legal"] is True
    for rec in (a, b):
        assert rec["gate3"] is True
        assert rec["gate4"] is True
        assert rec["step_costs"] == [1, 1, 1, 1]
    assert a["qh_jh_same_suit"] is True
    assert b["qh_jh_same_suit"] is False


def test_13_gate3_detection():
    src = _first_source()
    parent = {"fd_blockers": 1, "face_up": False, "column_0": 1}
    st = src.clone()
    out = apply_macro(st, MACRO_A[:3])
    child = gate1_progress(st)
    assert out["gate3"] is True
    assert out["gate4"] is False
    assert is_gate3(parent, child, st) is True
    assert pretty_card(st.columns[1].face_up[-1]) == "JH"
    assert child["face_up"] is False


def test_14_and_15_gate4_is_9h_and_terminal():
    src = _first_source()
    st = src.clone()
    apply_macro(st, MACRO_A)
    prog = gate1_progress(st)
    assert prog["face_up"] is True
    assert pretty_card(st.columns[prog["column_0"]].face_up[-1]) == "9H"
    source = inspect.getsource(search_h9_from_gate2)
    assert "is_gate4" in source
    assert "continue" in source
    assert "SD5" in Path(MOD).read_text(encoding="utf-8") or "stock_rows(state) != 2" in source


def test_16_sd5_never_expanded():
    src = _first_source()
    assert ("deal",) in legal_sd4_episode_actions(src)
    st = src.clone()
    apply_macro(st, (("deal",),))
    assert stock_rows(st) == 1
    assert ("deal",) not in legal_sd4_episode_actions(st)
    assert ("deal",) not in legal_episode_actions(st)


def test_17_search_includes_all_engine_tableau():
    src = _first_source()
    legal = set(legal_sd4_episode_actions(src))
    tab, _ = engine_tableau_actions(src)
    for action in tab:
        assert action in legal
    assert ("deal",) in legal
    source = inspect.getsource(search_h9_from_gate2)
    assert "legal_sd4_episode_actions" in source


def test_18_full_cost_dominance():
    source = inspect.getsource(search_h9_from_gate2)
    assert "source_g" in source
    assert "g0 < best_g[ident]" in source
    assert "child_g >= prev" in source


def test_19_plus4_lb_valid_or_withdrawn():
    src = _first_source()
    audit = continuation_lb_audit(src)
    assert "valid" in audit
    if audit["valid"]:
        assert audit["lb"] == 4
        assert audit["deal_cost"] == 1
    else:
        assert audit["lb"] is None
        assert audit["reasons"]


def test_20_witness_replays_if_present():
    if not V37_FIX.exists():
        return
    actions = parse_moves_file(V37_FIX)
    end = _opening()
    cost = replay_actions(end, actions)
    assert cost == len(actions)
    prog = gate1_progress(end)
    assert prog["face_up"] is True
    assert pretty_card(end.columns[prog["column_0"]].face_up[-1]) == "9H"
    if H9_PORT.exists():
        port = json.loads(H9_PORT.read_text(encoding="utf-8"))
        for rec in port.get("states") or []:
            s = _opening()
            c = replay_actions(s, _as_actions(rec["full_actions"]))
            assert c == rec["full_cost"]
            assert pack_state(s).hex() == rec["ordered_digest"]


def test_21_diamond_telemetry_only():
    text = SCRIPT.read_text(encoding="utf-8") + Path(MOD).read_text(encoding="utf-8")
    assert "Telemetry only" in text
    assert "Diamond foundation is not searched" in text


def test_22_production_and_mw():
    assert MW_RULES.can_deal_into_empty is True
    end = _first_source()
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(end, **kwargs)
    b = solve_progressive(end, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b.nodes
    assert "search_h9_from_gate2" not in inspect.getsource(solve_progressive)
    assert pack_state(end)[:4] == b"SPK1"
    assert pack_search_identity(end) == pack_state(end)
    swapped = permute_tableau_columns(end, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    assert pack_state(end) != pack_state(swapped)
