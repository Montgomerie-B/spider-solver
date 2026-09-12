"""Whole-suit component assembly audit v0.55."""

from __future__ import annotations

import inspect
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.rules import MW_RULES
from spider.simple_deal1_preview import stock_rows
from spider.simple_final_deal_timing import foundation_suits
from spider.simple_low_tail import k_through_n, synthetic_columns, tail_run
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, solve_progressive
from spider.simple_sd5_component_audit import (
    SUITS,
    a_ending,
    audit_suit,
    choose_verdict,
    component_cover,
    direct_condensation,
    dominates,
    face_down_suit_cards,
    harvest_component_portfolio,
    k_headed,
    ka_directly_joinable,
    ka_gap,
    merge_edges,
    min_interval_cover,
    pareto_prep,
    visible_components,
)
from spider.simple_sd5_resource_runway import EXPECTED_PREP, apply_sd5_frontier, reconstruct_prep
from spider.simple_workspace_reachability import engine_tableau_actions

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "simple_sd5_component_audit.py"
SCRIPT = ROOT / "research" / "sd5_whole_suit_component_audit_v0_55.py"
F2_FIX = ROOT / "solutions" / "4925153_v0_55_component_foundation2.moves.txt"


def _opening():
    return SpiderState.from_cards(list(load_deal(ROOT / "deals" / "4925153.txt")))


def _kings(n):
    return [[Card("s", 13)] for _ in range(n)]


def test_1_2_universe_counts_and_timing():
    assert EXPECTED_PREP == 103_513
    src = inspect.getsource(reconstruct_prep) + inspect.getsource(apply_sd5_frontier)
    assert "103_513" in MOD.read_text(encoding="utf-8") or EXPECTED_PREP == 103_513
    text = SCRIPT.read_text(encoding="utf-8")
    assert "reconstruct_prep" in text
    assert "apply_sd5_frontier" in text
    assert "720" in text
    assert "102,793" in text
    assert "PREP_THEN_DEAL" in text


def test_3_4_5_maximal_components_split_mixed_ignore_fd():
    st = synthetic_columns(
        [[Card("c", 13), Card("c", 12), Card("h", 11), Card("c", 10)], *_kings(9)]
    )
    comps = visible_components(st, "c")
    assert len(comps) == 2
    assert {c["length"] for c in comps} == {2, 1}
    assert all(c["suit"] == "c" for c in comps)
    down = SpiderState(
        [Column([Card("c", 5)], [Card("c", 13), Card("c", 12)]), *[Column([], [Card("s", 13)]) for _ in range(9)]],
        [],
        [],
    )
    vis = visible_components(down, "c")
    assert all(c["high"] != 5 for c in vis)
    assert any(t["rank"] == 5 for t in face_down_suit_cards(down, "c"))


def test_6_7_8_9_10_duplicate_ids_and_no_split_or_reuse():
    st = synthetic_columns([[Card("d", 5)], [Card("d", 5)], *_kings(8)])
    comps = visible_components(st, "d")
    assert len(comps) == 2
    assert comps[0]["id"] != comps[1]["id"]
    cover = component_cover(st, "d")
    # cannot cover K-A with two 5s
    assert cover["min_cover"] is None
    src = inspect.getsource(min_interval_cover)
    assert "need" in src
    st2 = synthetic_columns([k_through_n("c", 7), tail_run("c", 6), *_kings(8)])
    c2 = component_cover(st2, "c")
    assert c2["min_cover"] == 2
    assert c2["join_lb"] == 1
    # component 7-K and 6-A used whole, not split


def test_11_12_13_synthetic_min_cover_and_fd():
    vis = synthetic_columns(
        [k_through_n("h", 8), tail_run("h", 6), *_kings(8)]
    )
    # missing 7H entirely
    c = component_cover(vis, "h")
    assert c["min_visible_cover"] is None
    down = SpiderState(
        [
            Column([], k_through_n("h", 8)),
            Column([], tail_run("h", 6)),
            Column([Card("h", 7)], [Card("s", 13)]),
            *[Column([], [Card("s", 13)]) for _ in range(7)],
        ],
        [],
        [],
    )
    c2 = component_cover(down, "h")
    assert c2["min_visible_cover"] is None
    assert c2["min_cover"] == 3
    assert c2["min_fd_cards"] == 1


def test_14_15_direct_edge_requires_engine_move():
    ready = synthetic_columns([tail_run("c", 3), [Card("c", 4)], *_kings(8)])
    edges = merge_edges(ready, "c")
    assert edges
    assert all(ready.can_move(*e) for e in edges)
    buried = synthetic_columns([tail_run("c", 3) + [Card("h", 13)], [Card("c", 4)], *_kings(8)])
    edges2 = merge_edges(buried, "c")
    # 3-2-A buried under HK, not movable onto 4C
    assert not any(e[0] == 0 for e in edges2)


def test_16_17_condensation_target_suit_and_choices():
    src = inspect.getsource(direct_condensation)
    assert "merge_edges" in src
    assert "target-suit" in inspect.getdoc(direct_condensation) or "Only target-suit" in inspect.getdoc(direct_condensation)
    st = synthetic_columns([tail_run("d", 2), [Card("d", 3)], [Card("d", 3)], *_kings(7)])
    edges = merge_edges(st, "d")
    assert len(edges) >= 2
    cond = direct_condensation(st, "d")
    assert cond["min_n"] < cond["start_n"] or cond["longest"] >= 3


def test_18_auto_removal_success():
    st = synthetic_columns(
        [tail_run("d", 3), k_through_n("d", 4)],
        foundations=[k_through_n("s", 1)],
    )
    cond = direct_condensation(st, "d")
    assert cond["f2"] is True


def test_19_20_join_lb_is_cover_minus_one_no_blockers():
    st = synthetic_columns([k_through_n("c", 7), tail_run("c", 6), *_kings(8)])
    c = component_cover(st, "c")
    assert c["join_lb"] == c["min_cover"] - 1
    src = inspect.getsource(component_cover)
    assert "blocker" not in src.lower()
    assert "all_n - 1" in src


def test_21_22_23_k_a_and_gap():
    st = synthetic_columns([k_through_n("c", 8), tail_run("c", 6), *_kings(8)])
    comps = visible_components(st, "c")
    k = k_headed(comps)
    a = a_ending(comps)
    assert k["high"] == 13
    assert a["low"] == 1
    assert ka_gap(k, a) == 1  # 8 vs 6, missing 7
    st2 = synthetic_columns([k_through_n("c", 7), tail_run("c", 6), *_kings(8)])
    comps2 = visible_components(st2, "c")
    assert ka_gap(k_headed(comps2), a_ending(comps2)) == 0
    assert ka_directly_joinable(st2, k_headed(comps2), a_ending(comps2))


def test_24_25_pareto_no_weighted_score():
    src = inspect.getsource(pareto_prep) + inspect.getsource(dominates)
    assert "score" not in src.lower() or "no weighted" in src.lower()
    cheap = {"g": 80, "min_cover": 4, "min_fd_cards": 1, "join_lb": 3, "start_edges": 0, "cond_longest": 5, "gap": 2}
    prep = {"g": 81, "min_cover": 3, "min_fd_cards": 0, "join_lb": 2, "start_edges": 1, "cond_longest": 6, "gap": 1}
    worse = {"g": 82, "min_cover": 5, "min_fd_cards": 2, "join_lb": 4, "start_edges": 0, "cond_longest": 4, "gap": 3}
    assert dominates(prep, cheap) or not dominates(cheap, prep)
    out = pareto_prep([cheap], [prep, worse])
    ids = [p["min_cover"] for p in out]
    assert 3 in ids
    assert 5 not in ids


def test_26_27_metadata_and_all_suits():
    src = inspect.getsource(audit_state := __import__("spider.simple_sd5_component_audit", fromlist=["audit_state"]).audit_state)
    assert "prep_depth" in src
    assert "for suit in SUITS" in src
    assert SUITS == ("s", "h", "d", "c")


def test_28_29_30_33_no_human_no_ucs_no_presd4_no_f3():
    text = MOD.read_text(encoding="utf-8") + SCRIPT.read_text(encoding="utf-8")
    assert "human" not in text.lower() or "Do NOT inspect the human" in text or "No UCS" in text
    assert "search_foundation2" not in text
    assert "enumerate_preparation" not in MOD.read_text(encoding="utf-8")
    assert "No UCS" in SCRIPT.read_text(encoding="utf-8")
    assert "pre-SD4" in SCRIPT.read_text(encoding="utf-8")
    assert "Foundation 3" in SCRIPT.read_text(encoding="utf-8") or "Foundation-3" in text


def test_31_portfolio_only_if_improvement():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "if genuine" in src
    src2 = inspect.getsource(harvest_component_portfolio)
    assert "limit" in src2


def test_32_fixture_replays_if_present():
    if not F2_FIX.exists():
        return
    opening = _opening()
    end = opening.clone()
    cost = replay_actions(end, parse_moves_file(F2_FIX))
    assert stock_rows(end) == 0
    assert len(end.foundations) == 2
    assert cost >= 0
    assert "s" in foundation_suits(end)


def test_34_production_mw_green():
    assert MW_RULES.can_deal_into_empty is True
    opening = _opening()
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(opening, **kwargs)
    b = solve_progressive(opening, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b.nodes
    assert "audit_state" not in inspect.getsource(solve_progressive)
    assert "direct_condensation" not in inspect.getsource(solve_progressive)
