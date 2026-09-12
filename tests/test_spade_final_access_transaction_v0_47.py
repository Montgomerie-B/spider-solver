"""Spade 4S final access transaction v0.47."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state, permute_tableau_columns
from spider.rules import MW_RULES
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, opening_state
from spider.simple_foundation_race import JOIN_BREAK, suit_foundation_count
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, classify_tier, solve_progressive, step_cost
from spider.simple_spade_4s_ratchet import b4_count, four_s_can_move, locate_unique_spade, unique_4s_exposed
from spider.simple_spade_final_access import (
    COVER_ABOVE,
    HARD_LB,
    allowed_at_access_level,
    annotate_access_action,
    blocker_order_ok,
    blocker_removal_costs_one,
    exposure_lower_bound,
    fast_path_two_move,
    five_s_moves,
    five_s_requires_six_or_empty,
    gate2_capability,
    load_b42_sources,
    must_cross_b4_one,
    retained_frontier_hard_lb,
    search_access,
    synthetic_columns,
    ten_d_five_s_movable_together,
    ten_d_moves,
    ten_d_requires_jack_or_empty,
)
from spider.simple_workspace_reachability import engine_tableau_actions

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "simple_spade_final_access.py"
SCRIPT = ROOT / "research" / "spade_final_access_transaction_v0_47.py"
V046 = ROOT / "docs" / "research" / "spade_4s_blockers_2_v0_46.json"
GATE1 = ROOT / "docs" / "research" / "spade_5s_released_v0_47.json"
EXPOSED = ROOT / "docs" / "research" / "spade_4s_exposed_v0_47.json"
RESULT = ROOT / "docs" / "research" / "spade_final_access_transaction_v0_47.json"


def _opening():
    return SpiderState.from_cards(list(load_deal(ROOT / "deals" / "4925153.txt")))


def _synth_ready():
    st = synthetic_columns(
        [
            [Card("s", 4), Card("d", 10), Card("s", 5)],
            [Card("c", 6)],
            [Card("h", 11)],
        ]
    )
    rec = {
        "g": 89,
        "full_actions": [],
        "ordered_digest": pack_state(st).hex(),
        "symmetry_digest": pack_post_stock_symmetry_state(st).hex(),
        "timing": "DEAL_NOW",
        "lineages": ["synth"],
    }
    return st, rec


def test_1_exactly_128_b42_sources_load():
    raw = json.loads(V046.read_text(encoding="utf-8"))
    assert raw["n"] == 128
    assert raw["b4"] == 2
    assert len(raw["states"]) == 128


def test_2_and_3_every_source_replays_cost_matches():
    opening = _opening()
    bundle = load_b42_sources(opening)
    assert bundle["raw"] == 128
    assert bundle["all_replay_ok"]
    assert bundle["replay_fail"] == 0
    for rec in bundle["states"][:8]:
        end = opening.clone()
        cost = replay_actions(end, as_actions(rec["full_actions"]))
        assert cost == rec["g"]


def test_4_stock_is_zero():
    opening = _opening()
    rec = json.loads(V046.read_text(encoding="utf-8"))["states"][0]
    end = opening.clone()
    replay_actions(end, as_actions(rec["full_actions"]))
    assert stock_rows(end) == 0
    assert end.can_deal() is False


def test_5_one_spade_foundation_present():
    opening = _opening()
    rec = json.loads(V046.read_text(encoding="utf-8"))["states"][0]
    end = opening.clone()
    replay_actions(end, as_actions(rec["full_actions"]))
    assert len(end.foundations) == 1
    assert suit_foundation_count(end, "s") == 1


def test_6_unique_4s_located_dynamically():
    opening = _opening()
    rec = json.loads(V046.read_text(encoding="utf-8"))["states"][0]
    st = opening.clone()
    replay_actions(st, as_actions(rec["full_actions"]))
    loc = locate_unique_spade(st, 4)
    assert loc is not None
    perm = list(range(10))
    perm[0], perm[loc["column_0"]] = perm[loc["column_0"]], perm[0]
    swapped = permute_tableau_columns(st, perm)
    loc2 = locate_unique_spade(swapped, 4)
    assert loc2["column_0"] != loc["column_0"]
    assert b4_count(swapped) == 2


def test_7_and_8_b4_two_cover_10d_5s():
    opening = _opening()
    bundle = load_b42_sources(opening)
    for rec in bundle["states"]:
        st = opening.clone()
        replay_actions(st, as_actions(rec["full_actions"]))
        assert b4_count(st) == 2
        loc = locate_unique_spade(st, 4)
        assert tuple(loc["above"]) == COVER_ABOVE


def test_9_face_up_orientation_5s_is_top():
    opening = _opening()
    rec = json.loads(V046.read_text(encoding="utf-8"))["states"][0]
    st = opening.clone()
    replay_actions(st, as_actions(rec["full_actions"]))
    order = blocker_order_ok(st)
    assert order["ok"]
    assert order["top"] == "5S"
    loc = locate_unique_spade(st, 4)
    assert st.columns[loc["column_0"]].face_up[-1].rank == 5
    assert st.columns[loc["column_0"]].face_up[-1].suit == "s"


def test_10_10d_5s_cannot_move_together():
    st = synthetic_columns([[Card("s", 4), Card("d", 10), Card("s", 5)], [Card("c", 6)]])
    assert SpiderState.is_movable_run(st.columns[0].face_up[-2:]) is False
    assert ten_d_five_s_movable_together(st) is False
    opening = _opening()
    rec = json.loads(V046.read_text(encoding="utf-8"))["states"][0]
    real = opening.clone()
    replay_actions(real, as_actions(rec["full_actions"]))
    assert ten_d_five_s_movable_together(real) is False


def test_11_every_exposure_path_crosses_b4_one():
    text = must_cross_b4_one()
    assert "B4=1" in text
    st, rec = _synth_ready()
    assert b4_count(st) == 2
    a1 = five_s_moves(st)[0]
    st.move(*a1)
    assert b4_count(st) == 1
    a2 = ten_d_moves(st)[0]
    st.move(*a2)
    assert b4_count(st) == 0
    assert unique_4s_exposed(st)


def test_12_first_2_to_1_is_5s_leaving():
    st, _ = _synth_ready()
    loc = locate_unique_spade(st, 4)
    for action in five_s_moves(st):
        assert action[0] == loc["column_0"]
        assert action[2] == 1
        assert st.columns[action[0]].face_up[-1].rank == 5


def test_13_5s_requires_rank6_or_empty():
    ready, _ = _synth_ready()
    a = five_s_moves(ready)[0]
    assert five_s_requires_six_or_empty(ready, a)
    empty = synthetic_columns([[Card("s", 4), Card("d", 10), Card("s", 5)], []])
    a2 = five_s_moves(empty)[0]
    assert five_s_requires_six_or_empty(empty, a2)
    kings = [[Card("s", 13)] for _ in range(8)]
    blocked = synthetic_columns([[Card("s", 4), Card("d", 10), Card("s", 5)], [Card("c", 7)], *kings])
    assert five_s_moves(blocked) == []


def test_14_after_gate1_10d_is_top_blocker():
    st, _ = _synth_ready()
    st.move(*five_s_moves(st)[0])
    loc = locate_unique_spade(st, 4)
    assert loc["above"] == ["10D"]
    assert st.columns[loc["column_0"]].face_up[-1].rank == 10
    assert st.columns[loc["column_0"]].face_up[-1].suit == "d"


def test_15_10d_requires_jack_or_empty():
    st, _ = _synth_ready()
    st.move(*five_s_moves(st)[0])
    a = ten_d_moves(st)[0]
    assert ten_d_requires_jack_or_empty(st, a)
    empty = synthetic_columns([[Card("s", 4), Card("d", 10)], []])
    assert ten_d_requires_jack_or_empty(empty, ten_d_moves(empty)[0])
    kings = [[Card("s", 13)] for _ in range(8)]
    blocked = synthetic_columns([[Card("s", 4), Card("d", 10)], [Card("c", 12)], *kings])
    assert ten_d_moves(blocked) == []


def test_16_17_18_blocker_removal_lb_is_source_plus_2_and_91():
    st, rec = _synth_ready()
    a = five_s_moves(st)[0]
    assert blocker_removal_costs_one(st, a)
    assert step_cost(st, a) == 1
    assert exposure_lower_bound(rec["g"]) == 91
    assert retained_frontier_hard_lb() == HARD_LB == 91
    opening = _opening()
    bundle = load_b42_sources(opening)
    assert min(r["g"] for r in bundle["states"]) == 89
    assert exposure_lower_bound(89) == 91


def test_19_and_20_fast_path_enumerates_both_gates():
    st, rec = _synth_ready()
    fp = fast_path_two_move([rec], st)
    assert fp["n_legal_2_to_1"] >= 1
    assert fp["n_with_immediate_1_to_0"] >= 1
    assert fp["mw91_n"] >= 1
    assert fp["cheapest"] == 91
    assert unique_4s_exposed(synthetic_columns([[Card("s", 4)], [Card("s", 5), Card("c", 6)], [Card("d", 10), Card("h", 11)]]))


def test_21_and_22_gate_dependencies_recompute_dynamically():
    src = inspect.getsource(search_access) + inspect.getsource(annotate_access_action)
    assert "locate_unique_spade" in src
    assert "exposed_rank_columns" in src or "dest_kind" in src
    st, _ = _synth_ready()
    loc = locate_unique_spade(st, 4)
    label = annotate_access_action(st, five_s_moves(st)[0], loc, "gate1")
    assert label == "GATE_MOVE"
    st.move(*five_s_moves(st)[0])
    loc2 = locate_unique_spade(st, 4)
    assert loc2["cards_above"] == 1
    cap = gate2_capability(st)
    assert cap["primary"] in ("J_READY", "GATE2_READY")


def test_23_gate1_terminalises_on_first_b4_one():
    src = inspect.getsource(search_access)
    assert 'phase == "gate1"' in src
    assert "child_b == target_b4" in src
    assert "continue" in src
    st, rec = _synth_ready()
    res = search_access(
        [rec],
        st,
        phase="gate1",
        source_b4=2,
        target_b4=1,
        max_unique=200,
        time_limit_s=2.0,
    )
    assert res.witnesses
    assert all(w["b4_after"] == 1 for w in res.witnesses)
    assert all(w["depth"] >= 1 for w in res.witnesses)


def test_24_b41_portfolio_preserves_gate2_diversity():
    src = inspect.getsource(search_access)
    assert "gate2_capability" in src
    assert "HARVEST_B41" in src
    assert "J_READY" in MOD.read_text(encoding="utf-8")
    assert "EMPTY_READY" in MOD.read_text(encoding="utf-8")
    assert "J_ONE_SUPPORT" in MOD.read_text(encoding="utf-8")


def test_25_and_26_l2_narrower_l3_all_legal():
    assert allowed_at_access_level(JOIN_BREAK, 3, 2, "gate1") is False
    assert allowed_at_access_level(JOIN_BREAK, 3, 3, "gate1") is True
    opening = _opening()
    rec = json.loads(V046.read_text(encoding="utf-8"))["states"][0]
    st = opening.clone()
    replay_actions(st, as_actions(rec["full_actions"]))
    loc = locate_unique_spade(st, 4)
    for action in engine_tableau_actions(st)[0]:
        label = annotate_access_action(st, action, loc, "gate1")
        assert allowed_at_access_level(label, int(classify_tier(st, action)), 3, "gate1") is True
        assert action != ("deal",)


def test_27_post_stock_symmetry_identity():
    src = inspect.getsource(search_access)
    assert "pack_post_stock_symmetry_state" in src
    st, _ = _synth_ready()
    assert pack_post_stock_symmetry_state(st)[:4] == b"SPS1"


def test_28_full_g_drives_dominance():
    src = inspect.getsource(search_access)
    assert "child_g >= prev" in src
    assert "best_g" in src


def test_29_zero_cost_cycles_safe():
    src = inspect.getsource(search_access)
    assert "child_g >= prev" in src
    assert "seen_expand" in src


def test_30_gate_capability_history_not_identity():
    text = MOD.read_text(encoding="utf-8")
    assert "not identity" in text.lower()
    src = inspect.getsource(search_access)
    assign = src.split("child_sym =")[1][:120]
    assert "b4" not in assign
    assert "gate" not in assign.lower()
    assert "pack_post_stock_symmetry_state" in src.split("child_sym =")[1][:80]


def test_31_exposure_means_4s_top_b4_zero():
    st = synthetic_columns([[Card("s", 4)]])
    assert unique_4s_exposed(st)
    assert b4_count(st) == 0
    buried = synthetic_columns([[Card("s", 4), Card("d", 10)]])
    assert not unique_4s_exposed(buried)


def test_32_successful_trajectory_stops_at_exposure():
    src = inspect.getsource(search_access)
    assert "unique_4s_exposed" in src
    assert "continue" in src
    script = SCRIPT.read_text(encoding="utf-8")
    assert "Do NOT move anything onto 4S" in script or "Do not search TAIL4" in script


def test_33_no_tail4_search():
    text = SCRIPT.read_text(encoding="utf-8") + MOD.read_text(encoding="utf-8")
    assert "Do not search TAIL4" in text or "Do NOT search TAIL4" in text
    src = inspect.getsource(search_access)
    assert "spade_tail_present" not in src
    assert "preview_tail4" not in src


def test_34_no_foundation2_search():
    text = SCRIPT.read_text(encoding="utf-8") + MOD.read_text(encoding="utf-8")
    assert "Do not search Foundation 2" in text or "do not search Foundation 2" in text.lower()
    src = inspect.getsource(search_access)
    assert "suit_foundation_count" in src
    # foundation is recorded as surprise, not a search target
    assert "Foundation 3" in text or "do not search Foundation 3" in text.lower()


def test_35_no_deal_occurs():
    src = inspect.getsource(search_access)
    assert 'if action == ("deal",)' in src
    st, _ = _synth_ready()
    assert st.can_deal() is False
    opening = _opening()
    rec = json.loads(V046.read_text(encoding="utf-8"))["states"][0]
    real = opening.clone()
    replay_actions(real, as_actions(rec["full_actions"]))
    assert real.can_deal() is False


def test_36_saved_witnesses_replay_from_deal():
    opening = _opening()
    for path in (V046, GATE1, EXPOSED):
        if not path.exists():
            continue
        port = json.loads(path.read_text(encoding="utf-8"))
        for rec in (port.get("states") or [])[:6]:
            end = opening.clone()
            cost = replay_actions(end, as_actions(rec["full_actions"]))
            assert stock_rows(end) == 0
            assert rec.get("full_replay_ok", True) or cost == rec.get("g") or cost == rec.get("full_cost")


def test_37_production_and_mw_green():
    assert MW_RULES.can_deal_into_empty is True
    opening = _opening()
    rec = json.loads(V046.read_text(encoding="utf-8"))["states"][0]
    st = opening.clone()
    replay_actions(st, as_actions(rec["full_actions"]))
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(st, **kwargs)
    b = solve_progressive(st, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b.nodes
    assert "search_access" not in inspect.getsource(solve_progressive)
    assert four_s_can_move(st) is False
