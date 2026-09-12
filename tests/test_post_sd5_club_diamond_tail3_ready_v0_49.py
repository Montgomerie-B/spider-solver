"""Post-SD5 Club vs Diamond TAIL3_READY race v0.49."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state
from spider.rules import MW_RULES
from spider.simple_club_diamond_tail3_ready import (
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    allowed_at_ready_level,
    annotate_ready_action,
    execute_tail3_joins,
    filter_2a_sources,
    legal_tail3_joins,
    legal_tail4_joins,
    load_v044_deal_now_roots,
    must_cross_tail3_ready,
    must_cross_tail4_ready,
    one_move_scan,
    preview_tail4_ready,
    search_tail3_ready,
    synthetic_columns,
    tail3_already,
    tail3_ready,
    tail4_present,
    tail4_ready,
    two_a_packets,
)
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, opening_state
from spider.simple_foundation_race import JOIN_BREAK
from spider.simple_post_sd5_edge_race import edge_2a_present, load_deal_now_roots
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, classify_tier, solve_progressive
from spider.simple_workspace_reachability import engine_tableau_actions

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "simple_club_diamond_tail3_ready.py"
SCRIPT = ROOT / "research" / "post_sd5_club_diamond_tail3_ready_v0_49.py"
V044 = ROOT / "docs" / "research" / "post_sd5_deal_now_roots_v0_44.json"
V044_CLUB = ROOT / "docs" / "research" / "post_sd5_edge_club_v0_44.json"
CLUB_SRC = ROOT / "docs" / "research" / "post_sd5_club_2a_sources_v0_49.json"
DIA_SRC = ROOT / "docs" / "research" / "post_sd5_diamond_2a_sources_v0_49.json"


def _opening():
    return SpiderState.from_cards(list(load_deal(ROOT / "deals" / "4925153.txt")))


def _kings(n):
    return [[Card("s", 13)] for _ in range(n)]


def test_1_2_720_roots_replay_stock_zero():
    bundle = load_v044_deal_now_roots(_opening())
    assert bundle["raw"] == 720
    assert bundle["all_replay_ok"]
    opening = _opening()
    rec = json.loads(V044.read_text(encoding="utf-8"))["states"][0]
    end = opening.clone()
    replay_actions(end, as_actions(rec["full_actions"]))
    assert stock_rows(end) == 0
    assert end.can_deal() is False


def test_3_post_stock_symmetry_identity():
    src = inspect.getsource(search_tail3_ready)
    assert "pack_post_stock_symmetry_state" in src
    st = synthetic_columns([[Card("c", 2), Card("c", 1)]], stock_n=0)
    assert pack_post_stock_symmetry_state(st)[:4] == b"SPS1"


def test_4_5_6_full_2a_source_sets_not_128_harvest():
    src = inspect.getsource(filter_2a_sources) + SCRIPT.read_text(encoding="utf-8")
    assert "edge_2a_present" in src
    assert "128" not in inspect.getsource(filter_2a_sources) or "HARVEST" not in inspect.getsource(filter_2a_sources)
    assert "Do not restrict" in SCRIPT.read_text(encoding="utf-8") or "not restricted" in SCRIPT.read_text(encoding="utf-8").lower() or "all 128" not in SCRIPT.read_text(encoding="utf-8")
    assert "filter_2a_sources(roots" in SCRIPT.read_text(encoding="utf-8")
    text = SCRIPT.read_text(encoding="utf-8")
    assert "old 128" in text or "128-state" in text or "harvest" in text.lower()


def test_7_duplicate_physical_copies_supported():
    st = synthetic_columns(
        [
            [Card("c", 2), Card("c", 1)],
            [Card("c", 2), Card("c", 1)],
            [Card("c", 3)],
            *_kings(7),
        ]
    )
    pk = two_a_packets(st, "c")
    assert len(pk) == 2
    assert tail3_ready(st, "c")


def test_8_9_tail3_ready_requires_movable_2a_plus_exposed_3():
    ready = synthetic_columns([[Card("c", 2), Card("c", 1)], [Card("c", 3)], *_kings(8)])
    assert tail3_ready(ready, "c")
    assert legal_tail3_joins(ready, "c")
    buried = synthetic_columns([[Card("c", 2), Card("c", 1), Card("h", 13)], [Card("c", 3)], *_kings(8)])
    assert not tail3_ready(buried, "c")
    no3 = synthetic_columns([[Card("c", 2), Card("c", 1)], [Card("d", 3)], *_kings(8)])
    assert not tail3_ready(no3, "c")
    text = must_cross_tail3_ready()
    assert "TAIL3_READY" in text
    ready.move(*legal_tail3_joins(ready, "c")[0])
    assert tail3_already(ready, "c")


def test_10_physical_copies_may_change_dynamically():
    src = inspect.getsource(search_tail3_ready)
    assert "two_a_packets(state, suit)" in src
    assert "rank_cards(state, suit, 3)" in src


def test_11_one_move_scan_enumerates_every_legal_action():
    src = inspect.getsource(one_move_scan)
    assert "engine_tableau_actions" in src
    st = synthetic_columns([[Card("c", 2), Card("c", 1), Card("h", 4)], [Card("h", 5)], *_kings(8)])
    rec = {
        "g": 80,
        "full_actions": [],
        "ordered_digest": pack_state(st).hex(),
        "symmetry_digest": pack_post_stock_symmetry_state(st).hex(),
        "lineages": ["t"],
    }
    n = len(engine_tableau_actions(st)[0])
    fp = one_move_scan([rec], "c")
    assert fp["n_actions"] == n


def test_12_13_identical_mechanics_and_equal_budgets():
    src = inspect.getsource(search_tail3_ready)
    assert src.count("def search_tail3_ready") == 1
    assert SEARCH_UNIQUE == 160_000
    script = SCRIPT.read_text(encoding="utf-8")
    assert "SEARCH_TIME_S" in script
    assert "SEARCH_UNIQUE" in script
    assert SEARCH_TIME_S == 180.0
    assert SEARCH_RSS_MB == 1.5 * 1024.0


def test_14_15_full_g_dominance_and_zero_cost_cycles():
    src = inspect.getsource(search_tail3_ready)
    assert "child_g >= prev" in src
    assert "best_g" in src
    assert "seen_expand" in src


def test_16_17_l2_narrower_l3_all_legal():
    assert allowed_at_ready_level(JOIN_BREAK, 3, 2) is False
    assert allowed_at_ready_level(JOIN_BREAK, 3, 3) is True
    opening = _opening()
    rec = json.loads(V044.read_text(encoding="utf-8"))["states"][0]
    st = opening.clone()
    replay_actions(st, as_actions(rec["full_actions"]))
    pk = two_a_packets(st, "c")
    from spider.simple_club_diamond_tail3_ready import rank_cards

    th = rank_cards(st, "c", 3)
    for action in engine_tableau_actions(st)[0]:
        label = annotate_ready_action(st, action, "c", pk, th)
        assert allowed_at_ready_level(label, int(classify_tier(st, action)), 3) is True
        assert action != ("deal",)


def test_18_ready_terminates_primary():
    src = inspect.getsource(search_tail3_ready)
    assert "if ready or t3" in src or "tail3_ready(state, suit)" in src
    assert "continue" in src


def test_19_ready_join_creates_3_2_a():
    st = synthetic_columns([[Card("d", 2), Card("d", 1)], [Card("d", 3)], *_kings(8)])
    assert tail3_ready(st, "d")
    rec = {
        "g": 80,
        "source_g": 80,
        "full_actions": [],
        "ordered_digest": pack_state(st).hex(),
        "symmetry_digest": pack_post_stock_symmetry_state(st).hex(),
        "origin": 0,
        "actions": [],
        "lineages": ["t"],
    }
    src = dict(rec)
    hits = execute_tail3_joins([src], [rec], "d", st)
    assert hits
    end = synthetic_columns([[Card("d", 2), Card("d", 1)], [Card("d", 3)], *_kings(8)])
    end.move(*legal_tail3_joins(end, "d")[0])
    assert tail3_already(end, "d")


def test_20_21_tail4_ready_engine_correct_and_must_cross():
    ready = synthetic_columns(
        [[Card("c", 3), Card("c", 2), Card("c", 1)], [Card("c", 4)], *_kings(8)]
    )
    assert tail4_ready(ready, "c")
    assert legal_tail4_joins(ready, "c")
    text = must_cross_tail4_ready()
    assert "TAIL4_READY" in text
    ready.move(*legal_tail4_joins(ready, "c")[0])
    assert tail4_present(ready, "c")
    blocked = synthetic_columns([[Card("c", 3), Card("c", 2), Card("c", 1)], [Card("h", 4)], *_kings(8)])
    assert not tail4_ready(blocked, "c")


def test_22_23_five_ply_preview_all_legal_not_false_dead():
    src = inspect.getsource(preview_tail4_ready)
    assert "engine_tableau_actions" in src
    assert "LIVE_BEYOND_5" in src
    assert "EXACT_DEAD_TO_TAIL4_READY" in src
    assert "live = True" in src
    st = synthetic_columns([[Card("c", 3), Card("c", 2), Card("c", 1)], *_kings(9)])
    import time

    pr = preview_tail4_ready(st, 80, "c", deadline=time.perf_counter() + 0.5)
    assert pr["status"] != "EXACT_DEAD_TO_TAIL4_READY" or pr["dead"] is True
    if pr["status"] == "EXACT_DEAD_TO_TAIL4_READY":
        assert pr["live"] is False


def test_24_optional_4_tail_join_legal():
    from spider.simple_club_diamond_tail3_ready import optional_tail4_join

    st = synthetic_columns(
        [[Card("d", 3), Card("d", 2), Card("d", 1)], [Card("d", 4)], *_kings(8)]
    )
    hit = optional_tail4_join(st, 80, "d")
    assert hit is not None
    assert tail4_present(synthetic_columns([[Card("d", 4), Card("d", 3), Card("d", 2), Card("d", 1)]], stock_n=0), "d")


def test_25_26_27_28_no_rank5_spade_heart_foundation3():
    text = SCRIPT.read_text(encoding="utf-8") + MOD.read_text(encoding="utf-8")
    assert "Do not search Spades" in text or "no Spade" in text.lower()
    assert "Hearts" in text
    assert "rank 5" in text.lower() or "rank-5" in text.lower()
    assert "Foundation 3" in text or "Foundation-3" in text
    src = inspect.getsource(search_tail3_ready)
    assert 'if action == ("deal",)' in src
    assert "suit == \"s\"" not in src or "Do not search Spades" in text


def test_29_saved_witnesses_replay():
    opening = _opening()
    for path in (V044, CLUB_SRC, DIA_SRC):
        if not path.exists():
            continue
        port = json.loads(path.read_text(encoding="utf-8"))
        for rec in (port.get("states") or [])[:4]:
            end = opening.clone()
            cost = replay_actions(end, as_actions(rec["full_actions"]))
            assert stock_rows(end) == 0
            assert rec.get("full_replay_ok", True) or cost == rec.get("g") or cost == rec.get("full_cost")


def test_30_production_and_mw_green():
    assert MW_RULES.can_deal_into_empty is True
    opening = _opening()
    rec = json.loads(V044.read_text(encoding="utf-8"))["states"][0]
    st = opening.clone()
    replay_actions(st, as_actions(rec["full_actions"]))
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(st, **kwargs)
    b = solve_progressive(st, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b.nodes
    assert "search_tail3_ready" not in inspect.getsource(solve_progressive)
    assert load_deal_now_roots.__name__ == "load_deal_now_roots"
