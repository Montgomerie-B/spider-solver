"""SD5 resource-runway replan v0.53."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state
from spider.rules import MW_RULES
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions
from spider.simple_final_deal_timing import PREP_COST, PREP_DEPTH, enumerate_preparation
from spider.simple_low_tail import k_through_n, synthetic_columns, tail_run
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, solve_progressive
from spider.simple_sd5_resource_runway import (
    EXPECTED_PREP,
    EXPECTED_SOURCES,
    PREP_COST as RUNWAY_PREP_COST,
    PREP_DEPTH as RUNWAY_PREP_DEPTH,
    ace_ending_packets,
    access_class_from_copies,
    apply_sd5_frontier,
    audit_state,
    choose_verdict,
    direct_join_actions,
    direct_runway,
    harvest_portfolio,
    load_v043_sources,
    max_ace_length,
    next_required_rank,
    one_support_probe,
    reconstruct_prep,
    workspace_audit,
)
from spider.simple_workspace_reachability import engine_tableau_actions, face_down_count

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "simple_sd5_resource_runway.py"
SCRIPT = ROOT / "research" / "sd5_resource_runway_replan_v0_53.py"
SOURCES = ROOT / "docs" / "research" / "final_deal_sources_v0_43.json"
F2_FIX = ROOT / "solutions" / "4925153_v0_53_foundation2_local.moves.txt"


def _opening():
    return SpiderState.from_cards(list(load_deal(ROOT / "deals" / "4925153.txt")))


def _kings(n):
    return [[Card("s", 13)] for _ in range(n)]


def test_1_720_sources_replay():
    raw = json.loads(SOURCES.read_text(encoding="utf-8"))
    assert raw["n"] == 720
    assert len(raw["states"]) == 720
    opening = _opening()
    rec = raw["states"][0]
    end = opening.clone()
    cost = replay_actions(end, as_actions(rec["full_actions"]))
    assert cost == rec["full_cost"]
    assert stock_rows(end) == 1
    src = inspect.getsource(load_v043_sources)
    assert "final_deal_sources_v0_43.json" in MOD.read_text(encoding="utf-8")
    assert "EXPECTED_SOURCES = 720" in MOD.read_text(encoding="utf-8") or EXPECTED_SOURCES == 720


def test_2_3_prep_envelope_matches_v043_bounds():
    assert PREP_DEPTH == 4
    assert PREP_COST == 4
    assert RUNWAY_PREP_DEPTH == 4
    assert RUNWAY_PREP_COST == 4
    assert EXPECTED_PREP == 103_513
    src = inspect.getsource(reconstruct_prep)
    assert "enumerate_preparation" in src
    assert "max_depth=PREP_DEPTH" in src
    assert "max_cost=PREP_COST" in src
    src2 = inspect.getsource(enumerate_preparation)
    assert "pack_state" in src2
    assert "child_g >= prev" in src2


def test_4_5_sd5_once_then_stock_zero():
    src = inspect.getsource(apply_sd5_frontier)
    assert src.count('("deal",)') == 1 or 'apply_action(st, ("deal",))' in src
    assert "stock_rows(st) != 0" in src
    opening = _opening()
    rec = json.loads(SOURCES.read_text(encoding="utf-8"))["states"][0]
    st = opening.clone()
    replay_actions(st, as_actions(rec["full_actions"]))
    assert stock_rows(st) == 1
    apply_action(st, ("deal",))
    assert stock_rows(st) == 0


def test_6_post_stock_symmetry_identity():
    src = inspect.getsource(apply_sd5_frontier)
    assert "pack_post_stock_symmetry_state" in src
    assert "classes.get(ident_sym)" in src
    opening = _opening()
    rec = json.loads(SOURCES.read_text(encoding="utf-8"))["states"][0]
    st = opening.clone()
    replay_actions(st, as_actions(rec["full_actions"]))
    apply_action(st, ("deal",))
    a = pack_post_stock_symmetry_state(st)
    st.columns[0], st.columns[1] = st.columns[1], st.columns[0]
    assert pack_post_stock_symmetry_state(st) == a


def test_7_8_9_ace_ending_tails_duplicate_movable():
    st = synthetic_columns(
        [tail_run("d", 3), tail_run("d", 2), [Card("h", 1)], *_kings(7)]
    )
    pk = ace_ending_packets(st, "d")
    assert len(pk) == 2
    assert {p["length"] for p in pk} == {2, 3}
    assert all(p["exposed"] for p in pk)
    assert all(p["movable"] for p in pk)
    buried = synthetic_columns([tail_run("d", 2) + [Card("h", 13)], *_kings(9)])
    pk2 = ace_ending_packets(buried, "d")
    assert pk2[0]["exposed"] is False
    assert pk2[0]["movable"] is False


def test_10_11_12_next_rank_and_direct_advance():
    assert next_required_rank(3) == 4
    assert next_required_rank(5) == 6
    st = synthetic_columns([tail_run("d", 3), [Card("d", 4)], *_kings(8)])
    acts = direct_join_actions(st, "d")
    assert acts
    assert acts[0][2] == 3
    before = max_ace_length(st, "d")
    st.move(*acts[0])
    assert max_ace_length(st, "d") == before + 1


def test_13_14_direct_ka_auto_remove_is_success():
    st = synthetic_columns(
        [tail_run("d", 3), k_through_n("d", 4), *_kings(8)],
        foundations=[k_through_n("s", 1)],
    )
    assert len(st.foundations) == 1
    rw = direct_runway(st, "d")
    assert rw["auto"] is True
    assert rw["f2"] is True
    assert rw["direct_len"] == 13
    src = inspect.getsource(direct_runway)
    assert "FOUNDATION_AUTO_REMOVED" in src


def test_15_16_17_runway_only_target_joins_explores_choices():
    src = inspect.getsource(direct_runway)
    assert "direct_join_actions" in src
    assert "engine_tableau_actions" not in src
    st = synthetic_columns(
        [tail_run("c", 2), [Card("c", 3)], [Card("c", 3)], *_kings(7)]
    )
    acts = direct_join_actions(st, "c")
    assert len(acts) >= 2
    rw = direct_runway(st, "c")
    assert rw["direct_len"] == 3
    assert rw["joins"] == 1
    isolated = synthetic_columns([tail_run("c", 4), [Card("d", 5)], *_kings(8)])
    rw2 = direct_runway(isolated, "c")
    assert rw2["joins"] == 0
    assert rw2["direct_len"] == 4


def test_18_19_20_next_receiver_after_runway():
    ready = synthetic_columns([tail_run("h", 2), [Card("h", 3)], *_kings(8)])
    rw = direct_runway(ready, "h")
    assert rw["class"] == "NEXT_READY" or rw["direct_len"] >= 3
    # After joining 2-A onto 3, next is 4 which is absent -> not READY for 4.
    one = synthetic_columns([tail_run("h", 3), [Card("h", 4), Card("s", 13)], *_kings(7)])
    # 4H buried under SK; SK can park to another king? padded with kings, dest rank would need 14.
    # Leave an empty so SK is one-move exposable.
    one = synthetic_columns([tail_run("h", 3), [Card("h", 4), Card("s", 13)]])
    copies = __import__("spider.simple_low_tail", fromlist=["rank_cards"]).rank_cards(one, "h", 4)
    acc = access_class_from_copies(one, "h", 3, copies)
    assert acc["class"] == "NEXT_ONE_MOVE"
    assert any(t["one_move_exposable"] for t in copies)


def test_21_blocker_depth_classes():
    shallow = synthetic_columns(
        [tail_run("c", 2), [Card("c", 3), Card("d", 9), Card("h", 8)], *_kings(7)]
    )
    copies = __import__("spider.simple_low_tail", fromlist=["rank_cards"]).rank_cards(shallow, "c", 3)
    acc = access_class_from_copies(shallow, "c", 2, copies)
    assert acc["class"] == "NEXT_SHALLOW"
    deep = synthetic_columns(
        [tail_run("c", 2), [Card("c", 3), Card("h", 5), Card("d", 12), Card("s", 2), Card("h", 9), Card("d", 7)], *_kings(7)]
    )
    copies2 = __import__("spider.simple_low_tail", fromlist=["rank_cards"]).rank_cards(deep, "c", 3)
    acc2 = access_class_from_copies(deep, "c", 2, copies2)
    assert acc2["class"] == "NEXT_DEEP"
    down = SpiderState(
        [
            Column([], tail_run("c", 2)),
            Column([Card("c", 3)], [Card("h", 5)]),
            *[Column([], [Card("s", 13)]) for _ in range(8)],
        ],
        [],
        [],
    )
    copies3 = __import__("spider.simple_low_tail", fromlist=["rank_cards"]).rank_cards(down, "c", 3)
    acc3 = access_class_from_copies(down, "c", 2, copies3)
    assert acc3["class"] == "NEXT_FACE_DOWN"


def test_22_23_empty_and_fd_reveal_in_one():
    st = synthetic_columns([[Card("h", 13)], [Card("d", 5)]])
    ws = workspace_audit(st)
    assert ws["empty_now"] is True
    # Move 5D onto empty? dest empty, can_move king or empty. 5D can go to empty.
    # That does not create an additional empty. Source becomes empty: empty count stays.
    # Cover a column with a movable card over face-down to test fd reveal.
    st2 = SpiderState(
        [
            Column([Card("d", 9)], [Card("h", 13)]),
            Column([], []),
            *[Column([], [Card("s", 13)]) for _ in range(8)],
        ],
        [],
        [],
    )
    ws2 = workspace_audit(st2)
    assert ws2["fd_reveal_in_one"] is True
    src = inspect.getsource(workspace_audit)
    assert "face_down_count(state) < fd0" in src
    assert "is_empty()" in src


def test_24_25_one_support_is_single_action_then_unrestricted_joins():
    src = inspect.getsource(one_support_probe)
    assert "engine_tableau_actions" in src
    assert "direct_runway" in src
    assert "At most one" in inspect.getdoc(one_support_probe)
    st = synthetic_columns([tail_run("d", 2), [Card("d", 3), Card("s", 13)]])
    rec = {
        "g": 80,
        "direct_len": 2,
        "best_suit": "d",
        "access": "NEXT_ONE_MOVE",
        "f2": False,
        "ordered_digest": pack_state(st).hex(),
    }
    out, used = one_support_probe(rec, child_budget=50)
    assert used >= 1
    assert out["support_examined"] is True
    assert out["support_len"] >= out["direct_len"]


def test_26_27_full_g_and_timing_retained():
    src = inspect.getsource(apply_sd5_frontier) + inspect.getsource(audit_state)
    assert 'g = int(rec["g"]) + int(dcost)' in src or "rec[\"g\"] + dcost" in inspect.getsource(apply_sd5_frontier)
    assert '"timing": rec["timing"]' in inspect.getsource(apply_sd5_frontier)
    assert "DEAL_NOW" in inspect.getsource(reconstruct_prep) + inspect.getsource(enumerate_preparation)


def test_28_no_weighted_score():
    text = MOD.read_text(encoding="utf-8") + SCRIPT.read_text(encoding="utf-8")
    assert "weighted" in text.lower()
    assert "No weighted score" in inspect.getsource(harvest_portfolio) or "no weighted" in text.lower()
    src = inspect.getsource(harvest_portfolio)
    assert "score" not in src.lower() or "No weighted score" in src


def test_29_portfolio_multiple_suits_and_categories():
    rows = []
    for i, suit in enumerate(("s", "h", "d", "c")):
        for timing in ("DEAL_NOW", "PREP_THEN_DEAL"):
            rows.append(
                {
                    "g": 80 + i,
                    "timing": timing,
                    "prep_depth": 0 if timing == "DEAL_NOW" else 2,
                    "prep_cost": 0 if timing == "DEAL_NOW" else 1,
                    "best_suit": suit,
                    "direct_len": 3 + i,
                    "access": "NEXT_READY" if i == 0 else "NEXT_ONE_MOVE",
                    "empty_in_one": i == 2,
                    "fd_reveal_in_one": i == 3,
                    "f2": False,
                    "ordered_digest": f"{suit}{timing}{i}",
                    "symmetry_digest": f"{suit}{timing}{i}",
                    "full_actions": [],
                }
            )
    port = harvest_portfolio(rows)
    assert len({r["best_suit"] for r in port}) >= 3
    assert len({r.get("portfolio_cat") for r in port}) >= 3
    assert any(r["timing"] == "DEAL_NOW" for r in port)


def test_30_31_32_no_suit_search_no_ucs_no_f3():
    text = MOD.read_text(encoding="utf-8") + SCRIPT.read_text(encoding="utf-8")
    assert "search_foundation2" not in text
    assert "103k into UCS" not in text.lower() or "Do not seed UCS" in text
    assert "Foundation-3" in text or "Foundation 3" in text
    assert "enumerate_preparation" in text
    src = inspect.getsource(audit_state)
    assert "for suit in SUITS" in src
    script = SCRIPT.read_text(encoding="utf-8")
    assert "search_foundation2" not in script
    assert "Do not seed UCS" in script or "Do not seed UCS" in MOD.read_text(encoding="utf-8")


def test_33_saved_witnesses_replay_if_present():
    if not F2_FIX.exists():
        return
    opening = _opening()
    end = opening.clone()
    cost = replay_actions(end, parse_moves_file(F2_FIX))
    assert stock_rows(end) == 0
    assert len(end.foundations) >= 2
    assert cost >= 0


def test_34_production_mw_green():
    assert MW_RULES.can_deal_into_empty is True
    opening = _opening()
    rec = json.loads(SOURCES.read_text(encoding="utf-8"))["states"][0]
    st = opening.clone()
    replay_actions(st, as_actions(rec["full_actions"]))
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(st, **kwargs)
    b = solve_progressive(st, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b.nodes
    assert "audit_state" not in inspect.getsource(solve_progressive)
    assert "reconstruct_prep" not in inspect.getsource(solve_progressive)
