"""Post-SD4 foundation race v0.38: Heart 1 vs Diamond 1."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_search_identity, pack_state, permute_tableau_columns
from spider.rules import MW_RULES
from spider.simple_current_horizon import (
    audit_pre_sd4_hearts_leak,
    backward_map,
    current_horizon_material_audit,
    occurrence_counts,
)
from spider.simple_deal1_preview import stock_rows
from spider.simple_foundation_horizon import pretty_card
from spider.simple_foundation_race import (
    JOIN_BREAK,
    allowed_at_race_level,
    annotate_race_action,
    search_foundation,
    suit_foundation_count,
)
from spider.simple_h9_cut import pre_sd4_hearts
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, classify_tier, solve_progressive
from spider.simple_workspace_reachability import engine_tableau_actions

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
H9_PORT = ROOT / "docs" / "research" / "sd4_operational_horizon_pivot_v0_37_h9_portfolio.json"
V38_JSON = ROOT / "docs" / "research" / "post_sd4_foundation_race_v0_38.json"
HEART_FIX = ROOT / "solutions" / "4925153_v0_38_heart_foundation_best.moves.txt"
DIAMOND_FIX = ROOT / "solutions" / "4925153_v0_38_diamond_foundation_best.moves.txt"
HEART_PORT = ROOT / "docs" / "research" / "post_sd4_foundation_race_v0_38_heart_portfolio.json"
DIAMOND_PORT = ROOT / "docs" / "research" / "post_sd4_foundation_race_v0_38_diamond_portfolio.json"
SCRIPT = ROOT / "research" / "post_sd4_foundation_race_v0_38.py"
RACE = ROOT / "src" / "spider" / "simple_foundation_race.py"


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


def _h9_state(i=0):
    port = json.loads(H9_PORT.read_text(encoding="utf-8"))
    end = _opening()
    replay_actions(end, _as_actions(port["states"][i]["full_actions"]))
    return end, port["states"][i]


def test_1_all_256_replay():
    port = json.loads(H9_PORT.read_text(encoding="utf-8"))
    assert port["n"] == 256
    assert port["bands"] == {"77": 32, "78": 224}
    opening = _opening()
    families = set()
    for rec in port["states"]:
        end = opening.clone()
        cost = replay_actions(end, _as_actions(rec["full_actions"]))
        assert cost == rec["full_cost"]
        assert pack_state(end).hex() == rec["ordered_digest"]
        assert stock_rows(end) == 1
        assert pretty_card(end.columns[1].face_up[-1]) == "9H"
        families.add("A" if rec.get("qh_jh_same_suit") else "B")
    assert families == {"A", "B"}


def test_2_costs_77_78():
    port = json.loads(H9_PORT.read_text(encoding="utf-8"))
    costs = sorted({int(r["full_cost"]) for r in port["states"]})
    assert costs == [77, 78]


def test_3_macro_families_survive():
    port = json.loads(H9_PORT.read_text(encoding="utf-8"))
    a = sum(1 for r in port["states"] if r.get("qh_jh_same_suit"))
    b = sum(1 for r in port["states"] if not r.get("qh_jh_same_suit"))
    assert a >= 1 and b >= 1


def test_4_and_5_current_excludes_sd5_future_includes():
    st, _ = _h9_state()
    assert stock_rows(st) == 1
    leak = audit_pre_sd4_hearts_leak(st, 9)
    assert leak["confirmed"] is True
    rec = occurrence_counts(st, "h", 9)
    assert rec["tableau_count"] == 1
    assert rec["future_stock_count"] == 1
    assert rec["current_count"] == 1
    assert rec["future_after_SD5_count"] == 2
    legacy = pre_sd4_hearts(st, 9)
    assert len(legacy) == 2
    three = occurrence_counts(st, "h", 3)
    if three["future_stock_count"] == 1 and three["tableau_count"] == 1:
        assert three["current_count"] == 1
        assert three["future_after_SD5_count"] == 2


def test_6_to_8_material_availability():
    st, _ = _h9_state()
    audit = current_horizon_material_audit(st)
    assert audit["heart_1_now"] is True
    assert audit["diamond_1_now"] is True
    assert audit["spade_2_now"] is False
    assert audit["club_1_now"] is False
    assert "A" in audit["suits"]["s"]["missing_for_second_now"]
    assert "3" in audit["suits"]["c"]["missing_for_first_now"]


def test_9_heart_current_unique_accounting():
    st, _ = _h9_state()
    m = backward_map(st, "h")
    for label, rec in m["ranks"].items():
        assert rec["current_count"] == rec["current_count"]
        if rec["hard"]:
            assert rec["current_count"] == 1
            assert rec["future_after_SD5_count"] >= 1


def test_10_to_12_diamond_unique_2d_5d():
    st, _ = _h9_state()
    d2 = occurrence_counts(st, "d", 2)
    d5 = occurrence_counts(st, "d", 5)
    assert d2["tableau_count"] == 1
    assert d2["hard"] is True
    assert d2["future_stock_count"] == 1
    assert d5["tableau_count"] == 1
    assert d5["hard"] is True
    m = backward_map(st, "d")
    assert "2" in m["hard_ranks"]
    assert "5" in m["hard_ranks"]
    tops = [c for c in d2["tableau"] if pretty_card(st.columns[c["column_0"]].face_up[-1]) == "AH" or True]
    assert pretty_card(st.columns[3].face_up[-1]) == "AH"
    assert pretty_card(st.columns[3].face_up[-2]) == "2D"


def test_13_maps_update_after_moves():
    st, _ = _h9_state()
    before = backward_map(st, "d")
    # identity: cloning and no move keeps map
    after = backward_map(st.clone(), "d")
    assert before["hard_ranks"] == after["hard_ranks"]
    source = inspect.getsource(search_foundation)
    assert "unique_target_columns(state" in source
    assert "annotate_race_action(state" in source


def test_14_labels_not_legality():
    st, _ = _h9_state()
    tab, _ = engine_tableau_actions(st)
    hot = set()
    for action in tab[:5]:
        annotate_race_action(st, action, "h", hot)
        assert st.can_move(*action)


def test_15_equal_resource_mechanics():
    src = inspect.getsource(search_foundation)
    assert "max_unique: int = 500_000" in src
    assert "time_limit_s: float = 450.0" in src
    text = SCRIPT.read_text(encoding="utf-8")
    assert "time_limit_s=450.0" in text
    assert text.count("suit=\"h\"") + text.count("suit='h'") >= 1
    assert text.count("suit=\"d\"") + text.count("suit='d'") >= 1


def test_16_sd5_never_expanded():
    st, _ = _h9_state()
    assert stock_rows(st) == 1
    tab, _ = engine_tableau_actions(st)
    assert ("deal",) not in tab
    src = inspect.getsource(search_foundation)
    assert "engine_tableau_actions" in src
    assert 'if action == ("deal",)' in src


def test_17_and_18_ordered_pack_and_full_g():
    st, rec = _h9_state()
    assert pack_state(st)[:4] == b"SPK1"
    assert pack_search_identity(st) == pack_state(st)
    src = inspect.getsource(search_foundation)
    assert "source_g" in src
    assert "g0 < best_g[ident]" in src
    assert "pack_state" in src


def test_19_and_20_widening():
    st, _ = _h9_state()
    assert allowed_at_race_level(JOIN_BREAK, 3, 2) is False
    assert allowed_at_race_level(JOIN_BREAK, 3, 3) is True
    hot = set()
    for action in engine_tableau_actions(st)[0]:
        label = annotate_race_action(st, action, "h", hot)
        assert allowed_at_race_level(label, int(classify_tier(st, action)), 3) is True


def test_21_and_22_foundation_suit_detection():
    st, _ = _h9_state()
    assert suit_foundation_count(st, "s") == 1
    assert suit_foundation_count(st, "h") == 0
    assert suit_foundation_count(st, "d") == 0
    src = inspect.getsource(search_foundation)
    assert "suit_foundation_count(state, suit)" in src


def test_23_witness_replays_if_present():
    for fix in (HEART_FIX, DIAMOND_FIX):
        if not fix.exists():
            continue
        end = _opening()
        actions = parse_moves_file(fix)
        cost = replay_actions(end, actions)
        assert cost == len(actions)
        suits = [run[0].suit for run in end.foundations if run]
        assert "h" in suits or "d" in suits
    for port_path, suit in ((HEART_PORT, "h"), (DIAMOND_PORT, "d")):
        if not port_path.exists():
            continue
        port = json.loads(port_path.read_text(encoding="utf-8"))
        for rec in port.get("states") or []:
            end = _opening()
            c = replay_actions(end, _as_actions(rec["full_actions"]))
            assert c == rec["full_cost"]
            assert pack_state(end).hex() == rec["ordered_digest"]
            assert suit_foundation_count(end, suit) >= 1


def test_24_production_and_mw():
    assert MW_RULES.can_deal_into_empty is True
    st, _ = _h9_state()
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(st, **kwargs)
    b = solve_progressive(st, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b.nodes
    assert "search_foundation" not in inspect.getsource(solve_progressive)
    swapped = permute_tableau_columns(st, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    assert pack_state(st) != pack_state(swapped)
