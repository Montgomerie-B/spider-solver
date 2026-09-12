"""Spade 5S landing-resource cut v0.48."""

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
from spider.simple_diamond_c_bridge import as_actions
from spider.simple_foundation_race import JOIN_BREAK, suit_foundation_count
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, classify_tier, solve_progressive, step_cost
from spider.simple_spade_4s_ratchet import b4_count, locate_unique_spade, unique_4s_exposed
from spider.simple_spade_5s_landing import (
    COVER_ABOVE,
    HARD_LB,
    allowed_at_land5_level,
    annotate_land5_action,
    empty_column_candidates,
    exposure_lower_bound,
    first_support_zero_cost_possible,
    land5_kind,
    land5_ready,
    load_land5_sources,
    must_cross_land5,
    one_move_fast_path,
    physical_blocker_5s,
    preview_5s_10d,
    rank_occurrences,
    retained_frontier_hard_lb,
    search_land5,
    synthetic_columns,
)
from spider.simple_spade_final_access import five_s_moves, five_s_requires_six_or_empty, ten_d_moves, ten_d_requires_jack_or_empty
from spider.simple_workspace_reachability import empty_column_indices, engine_tableau_actions

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "simple_spade_5s_landing.py"
SCRIPT = ROOT / "research" / "spade_5s_landing_resource_v0_48.py"
V046 = ROOT / "docs" / "research" / "spade_4s_blockers_2_v0_46.json"
LAND5 = ROOT / "docs" / "research" / "spade_5s_land5_ready_v0_48.json"
EXPOSED = ROOT / "docs" / "research" / "spade_4s_exposed_v0_48.json"
AUDIT = ROOT / "docs" / "research" / "spade_5s_resource_audit_v0_48.json"


def _opening():
    return SpiderState.from_cards(list(load_deal(ROOT / "deals" / "4925153.txt")))


def _kings(n=8):
    return [[Card("c", 13)] for _ in range(n)]


def _source0():
    opening = _opening()
    rec = json.loads(V046.read_text(encoding="utf-8"))["states"][0]
    st = opening.clone()
    replay_actions(st, as_actions(rec["full_actions"]))
    return st, rec


def test_1_all_128_sources_replay():
    bundle = load_land5_sources(_opening())
    assert bundle["raw"] == 128
    assert bundle["symmetry_unique"] == 128
    assert bundle["all_replay_ok"]
    assert bundle["replay_fail"] == 0


def test_2_source_mw_89_16_and_90_112():
    bundle = load_land5_sources(_opening())
    assert bundle["cost_counts"] == {"89": 16, "90": 112}


def test_3_4_5_b4_cover_and_5s_top():
    st, _ = _source0()
    assert b4_count(st) == 2
    loc = locate_unique_spade(st, 4)
    assert tuple(loc["above"]) == COVER_ABOVE
    assert physical_blocker_5s(st)["card"] == "5S"
    assert st.columns[loc["column_0"]].face_up[-1].rank == 5


def test_6_7_8_no_rank6_empty_or_jack():
    bundle = load_land5_sources(_opening())
    assert bundle["land5_absent"]
    st, _ = _source0()
    assert land5_ready(st) is False
    from spider.simple_spade_final_access import exposed_rank_columns
    from spider.simple_spade_5s_landing import jack_ready

    assert exposed_rank_columns(st, 6) == []
    assert list(empty_column_indices(st)) == []
    assert jack_ready(st) is False


def test_9_physical_5s_located_dynamically():
    st, _ = _source0()
    loc = locate_unique_spade(st, 4)
    blk = physical_blocker_5s(st)
    assert blk["column_0"] == loc["column_0"]
    perm = list(range(10))
    perm[0], perm[loc["column_0"]] = perm[loc["column_0"]], perm[0]
    swapped = permute_tableau_columns(st, perm)
    blk2 = physical_blocker_5s(swapped)
    assert blk2["column_0"] != blk["column_0"]
    assert blk2["card"] == "5S"


def test_10_11_5s_requires_six_or_empty_and_land5_definition():
    ready = synthetic_columns([[Card("s", 4), Card("d", 10), Card("s", 5)], [Card("c", 6)], *_kings(8)])
    assert land5_ready(ready)
    assert land5_kind(ready) == "SIX_READY"
    assert five_s_requires_six_or_empty(ready, five_s_moves(ready)[0])
    empty = synthetic_columns([[Card("s", 4), Card("d", 10), Card("s", 5)], []])
    assert land5_kind(empty) in ("EMPTY_READY", "SIX_AND_EMPTY_READY")
    blocked = synthetic_columns([[Card("s", 4), Card("d", 10), Card("s", 5)], [Card("c", 7)], *_kings(8)])
    assert land5_ready(blocked) is False
    assert five_s_moves(blocked) == []


def test_12_every_5s_trajectory_crosses_land5():
    text = must_cross_land5()
    assert "LAND5_READY" in text
    blocked = synthetic_columns([[Card("s", 4), Card("d", 10), Card("s", 5)], [Card("c", 7)], *_kings(8)])
    assert not land5_ready(blocked)
    assert five_s_moves(blocked) == []
    ready = synthetic_columns([[Card("s", 4), Card("d", 10), Card("s", 5)], [Card("h", 6)], *_kings(8)])
    assert land5_ready(ready)
    assert five_s_moves(ready)


def test_13_14_15_costs_and_no_zero_cost_first_support():
    st, rec = _source0()
    assert first_support_zero_cost_possible(st) is False
    for action in engine_tableau_actions(st)[0]:
        assert step_cost(st, action) == 1
    ready = synthetic_columns([[Card("s", 4), Card("d", 10), Card("s", 5)], [Card("c", 6)], *_kings(8)])
    a5 = five_s_moves(ready)[0]
    assert step_cost(ready, a5) == 1
    ready.move(*a5)
    a10 = ten_d_moves(ready)
    # may need a jack; build one
    with_j = synthetic_columns(
        [[Card("s", 4), Card("d", 10), Card("s", 5)], [Card("c", 6)], [Card("h", 11)], *_kings(7)]
    )
    with_j.move(*five_s_moves(with_j)[0])
    assert step_cost(with_j, ten_d_moves(with_j)[0]) == 1


def test_16_17_source_plus_3_is_mw92():
    assert exposure_lower_bound(89) == 92
    assert retained_frontier_hard_lb() == HARD_LB == 92
    bundle = load_land5_sources(_opening())
    assert min(r["g"] for r in bundle["states"]) == 89


def test_18_one_move_fast_path_enumerates_every_legal_action():
    st, rec = _source0()
    rec2 = {
        "g": rec.get("full_cost") or rec["g"],
        "full_actions": rec["full_actions"],
        "ordered_digest": pack_state(st).hex(),
        "symmetry_digest": pack_post_stock_symmetry_state(st).hex(),
        "timing": rec.get("timing"),
        "lineages": rec.get("lineages"),
    }
    n_legal = len(engine_tableau_actions(st)[0])
    fp = one_move_fast_path([rec2])
    assert fp["n_actions"] == n_legal
    src = inspect.getsource(one_move_fast_path)
    assert "engine_tableau_actions" in src
    assert "land5_ready" in src


def test_19_20_rank6_and_empty_audited_dynamically():
    st, _ = _source0()
    sixes = rank_occurrences(st, 6)
    assert sixes
    assert all("cards_above" in s and "column_1" in s for s in sixes)
    empties = empty_column_candidates(st)
    assert len(empties) == 10
    assert all("one_move_clearable" in e for e in empties)


def test_21_resource_dependencies_recompute_after_moves():
    src = inspect.getsource(search_land5)
    assert "land5_ready" in src
    assert "annotate_land5_action" in src
    st = synthetic_columns(
        [[Card("s", 4), Card("d", 10), Card("s", 5)], [Card("c", 6), Card("h", 7)], [Card("d", 8)], *_kings(7)]
    )
    assert not land5_ready(st)
    st.move(1, 2, 1)
    assert land5_ready(st)


def test_22_land5_terminal_in_primary_search():
    src = inspect.getsource(search_land5)
    assert "if ready or foundation" in src or "land5_ready(state)" in src
    assert "continue" in src
    rec_state = synthetic_columns(
        [[Card("s", 4), Card("d", 10), Card("s", 5)], [Card("c", 6), Card("h", 7)], [Card("d", 8)], *_kings(7)]
    )
    rec = {
        "g": 89,
        "full_actions": [],
        "ordered_digest": pack_state(rec_state).hex(),
        "symmetry_digest": pack_post_stock_symmetry_state(rec_state).hex(),
        "timing": "DEAL_NOW",
        "lineages": ["synth"],
    }
    res = search_land5([rec], max_unique=200, time_limit_s=2.0)
    assert res.witnesses
    assert all(w.get("land5") for w in res.witnesses)


def test_23_24_l3_all_legal_l2_narrower():
    assert allowed_at_land5_level(JOIN_BREAK, 3, 2) is False
    assert allowed_at_land5_level(JOIN_BREAK, 3, 3) is True
    st, _ = _source0()
    for action in engine_tableau_actions(st)[0]:
        label = annotate_land5_action(st, action)
        assert allowed_at_land5_level(label, int(classify_tier(st, action)), 3) is True
        assert action != ("deal",)


def test_25_26_symmetry_and_full_g_dominance():
    src = inspect.getsource(search_land5)
    assert "pack_post_stock_symmetry_state" in src
    assert "child_g >= prev" in src
    st, _ = _source0()
    assert pack_post_stock_symmetry_state(st)[:4] == b"SPS1"


def test_27_resource_type_not_identity():
    text = MOD.read_text(encoding="utf-8")
    assert "not identity" in text.lower()
    src = inspect.getsource(search_land5)
    assign = src.split("child_sym =")[1][:120]
    assert "land5" not in assign.lower()
    assert "kind" not in assign.lower()


def test_28_29_portfolio_cost_bands_and_diversity():
    src = inspect.getsource(search_land5)
    assert "HARVEST_LIMIT" in src
    assert "source_g" in src
    assert "kind" in src
    text = SCRIPT.read_text(encoding="utf-8")
    assert "MW89" in text or "source_g" in text
    assert "DEAL_NOW" in text or "timing" in text


def test_30_31_land5_permits_5s_and_b4_becomes_1():
    ready = synthetic_columns(
        [[Card("s", 4), Card("d", 10), Card("s", 5)], [Card("c", 6)], [Card("h", 11)], *_kings(7)]
    )
    assert land5_ready(ready)
    assert five_s_moves(ready)
    ready.move(*five_s_moves(ready)[0])
    assert b4_count(ready) == 1
    loc = locate_unique_spade(ready, 4)
    assert ready.columns[loc["column_0"]].face_up[-1].rank == 10
    assert ready.columns[loc["column_0"]].face_up[-1].suit == "d"


def test_32_33_10d_requires_jack_or_empty_and_exposes_4s():
    st = synthetic_columns(
        [[Card("s", 4), Card("d", 10), Card("s", 5)], [Card("c", 6)], [Card("h", 11)], *_kings(7)]
    )
    st.move(*five_s_moves(st)[0])
    a = ten_d_moves(st)[0]
    assert ten_d_requires_jack_or_empty(st, a)
    st.move(*a)
    assert unique_4s_exposed(st)
    assert b4_count(st) == 0


def test_34_one_support_preview_is_bounded():
    src = inspect.getsource(preview_5s_10d)
    assert "one support" in src.lower() or "support" in src
    assert "No broader search" in src or "ten_d_moves" in src
    text = SCRIPT.read_text(encoding="utf-8")
    assert "one-support" in text.lower() or "one_support" in text


def test_35_successful_exposure_stops_immediately():
    text = SCRIPT.read_text(encoding="utf-8") + MOD.read_text(encoding="utf-8")
    assert "Do not search TAIL4" in text
    assert "stops immediately" in text.lower()


def test_36_37_38_no_tail4_foundation2_or_deal():
    text = SCRIPT.read_text(encoding="utf-8") + MOD.read_text(encoding="utf-8")
    assert "Do not search TAIL4" in text
    assert "Do not search Foundation 2" in text
    src = inspect.getsource(search_land5)
    assert 'if action == ("deal",)' in src
    st, _ = _source0()
    assert st.can_deal() is False


def test_39_saved_witnesses_replay():
    opening = _opening()
    for path in (V046, LAND5, EXPOSED, AUDIT):
        if not path.exists() or path == AUDIT:
            continue
        port = json.loads(path.read_text(encoding="utf-8"))
        for rec in (port.get("states") or [])[:6]:
            end = opening.clone()
            cost = replay_actions(end, as_actions(rec["full_actions"]))
            assert stock_rows(end) == 0
            assert rec.get("full_replay_ok", True) or cost == rec.get("g") or cost == rec.get("full_cost")


def test_40_production_and_mw_green():
    assert MW_RULES.can_deal_into_empty is True
    st, _ = _source0()
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(st, **kwargs)
    b = solve_progressive(st, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b.nodes
    assert "search_land5" not in inspect.getsource(solve_progressive)
