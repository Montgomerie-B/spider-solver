"""Club vs Diamond TAIL5_READY race v0.51."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state
from spider.rules import MW_RULES
from spider.simple_club_diamond_tail5 import (
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    allowed_at_tail5_level,
    annotate_tail5_action,
    load_tail4_persists,
    reconstruct_tail6_preview,
    search_tail5_ready,
    source_category,
    tail5_present,
    tail5_ready,
    tail6_ready,
)
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions
from spider.simple_foundation_race import JOIN_BREAK
from spider.simple_low_tail import (
    FOUNDATION_AUTO_REMOVED,
    LOW_TAIL_PERSISTS,
    classify_all_joins,
    classify_low_tail_transition,
    k_through_n,
    legal_tail_joins,
    must_cross_tail_ready,
    receiving_upper_run,
    synthetic_columns,
    tail_present,
    tail_ready,
    tail_run,
)
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, classify_tier, solve_progressive, step_cost
from spider.simple_workspace_reachability import engine_tableau_actions

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "simple_club_diamond_tail5.py"
LOW = ROOT / "src" / "spider" / "simple_low_tail.py"
SCRIPT = ROOT / "research" / "post_sd5_club_diamond_tail5_v0_51.py"
CLUB_T4 = ROOT / "docs" / "research" / "club_tail4_transition_v0_50.json"
DIA_T4 = ROOT / "docs" / "research" / "diamond_tail4_transition_v0_50.json"
CLUB_FIX = ROOT / "solutions" / "4925153_v0_51_club_foundation2.moves.txt"
DIA_FIX = ROOT / "solutions" / "4925153_v0_51_diamond_foundation2.moves.txt"


def _opening():
    return SpiderState.from_cards(list(load_deal(ROOT / "deals" / "4925153.txt")))


def _kings(n):
    return [[Card("s", 13)] for _ in range(n)]


def test_1_2_3_v050_persists_load():
    club = json.loads(CLUB_T4.read_text(encoding="utf-8"))
    dia = json.loads(DIA_T4.read_text(encoding="utf-8"))
    assert all(t["class"] == "TAIL4_PERSISTS" for t in club["transitions"])
    assert all(t["class"] == "TAIL4_PERSISTS" for t in dia["transitions"])
    assert len(club["transitions"]) == 96
    assert len(dia["transitions"]) == 125
    src = inspect.getsource(load_tail4_persists)
    assert "TAIL4_PERSISTS" in src


def test_1b_club_replay_sample():
    opening = _opening()
    rec = json.loads(CLUB_T4.read_text(encoding="utf-8"))["transitions"][0]
    end = opening.clone()
    cost = replay_actions(end, as_actions(rec["full_actions"]))
    assert cost == rec["g"]
    assert stock_rows(end) == 0
    assert tail_present(end, "c", 4)


def test_2b_diamond_replay_sample():
    opening = _opening()
    rec = json.loads(DIA_T4.read_text(encoding="utf-8"))["transitions"][0]
    end = opening.clone()
    cost = replay_actions(end, as_actions(rec["full_actions"]))
    assert cost == rec["g"]
    assert tail_present(end, "d", 4)


def test_4_5_tail4_exists_and_cheapest_dedup():
    src = inspect.getsource(load_tail4_persists)
    assert "tail4_present" in src
    assert "item[\"g\"] < prev[\"g\"]" in src


def test_6_duplicate_physical_5s():
    st = synthetic_columns(
        [tail_run("c", 4), [Card("c", 5)], [Card("c", 5)], *_kings(7)]
    )
    assert tail5_ready(st, "c")
    assert len(legal_tail_joins(st, "c", 5)) >= 2


def test_7_8_tail5_ready_and_must_cross():
    ready = synthetic_columns([tail_run("c", 4), [Card("c", 5)], *_kings(8)])
    assert tail5_ready(ready, "c")
    buried = synthetic_columns([tail_run("c", 4) + [Card("h", 13)], [Card("c", 5)], *_kings(8)])
    assert not tail5_ready(buried, "c")
    no5 = synthetic_columns([tail_run("c", 4), [Card("d", 5)], *_kings(8)])
    assert not tail5_ready(no5, "c")
    text = must_cross_tail_ready(5)
    assert "TAIL5_READY" in text
    ready.move(*legal_tail_joins(ready, "c", 5)[0])
    assert tail5_present(ready, "c")


def test_9_10_11_category_and_upper_run_k_through_5():
    st = synthetic_columns([tail_run("c", 4), [Card("c", 5)], *_kings(8)])
    assert source_category(st, "c") == "TAIL5_READY_AT_SOURCE"
    ur = receiving_upper_run(st, legal_tail_joins(st, "c", 5)[0][1], "c", 5)
    assert ur["label"] == "5 only"
    k5 = synthetic_columns([tail_run("c", 4), k_through_n("c", 5), *_kings(8)])
    ur2 = receiving_upper_run(k5, legal_tail_joins(k5, "c", 5)[0][1], "c", 5)
    assert ur2["k_through"] is True
    assert ur2["k_through_5"] is True


def test_12_one_move_enumerates_all():
    from spider.simple_club_diamond_tail5 import one_move_scan

    src = inspect.getsource(one_move_scan)
    assert "engine_tableau_actions" in src


def test_13_14_identical_mechanics_equal_budgets():
    assert SEARCH_UNIQUE == 160_000
    assert SEARCH_TIME_S == 180.0
    assert SEARCH_RSS_MB == 1.5 * 1024.0
    src = inspect.getsource(search_tail5_ready)
    assert src.count("def search_tail5_ready") == 1


def test_15_16_g_dominance_and_cycles():
    src = inspect.getsource(search_tail5_ready)
    assert "child_g >= prev" in src
    assert "seen_expand" in src


def test_17_18_l2_narrower_l3_all():
    assert allowed_at_tail5_level(JOIN_BREAK, 3, 2) is False
    assert allowed_at_tail5_level(JOIN_BREAK, 3, 3) is True
    opening = _opening()
    rec = json.loads(CLUB_T4.read_text(encoding="utf-8"))["transitions"][0]
    st = opening.clone()
    replay_actions(st, as_actions(rec["full_actions"]))
    from spider.simple_low_tail import rank_cards, tail_packets

    pk = tail_packets(st, "c", 4)
    fives = rank_cards(st, "c", 5)
    for action in engine_tableau_actions(st)[0]:
        label = annotate_tail5_action(st, action, "c", pk, fives)
        assert allowed_at_tail5_level(label, int(classify_tier(st, action)), 3) is True


def test_19_ready_terminates():
    src = inspect.getsource(search_tail5_ready)
    assert "if ready or f2" in src
    assert "continue" in src


def test_20_21_22_23_24_join_classifier():
    iso = synthetic_columns([tail_run("c", 4), [Card("c", 5)], *_kings(8)])
    hits = classify_all_joins(iso, 90, "c", packet_head_rank=4)
    assert hits
    assert hits[0]["class"] == LOW_TAIL_PERSISTS
    assert hits[0]["g"] > 90
    k5 = synthetic_columns([tail_run("d", 4), k_through_n("d", 5), *_kings(8)])
    hits2 = classify_all_joins(k5, 90, "d", packet_head_rank=4)
    assert hits2[0]["class"] == FOUNDATION_AUTO_REMOVED
    assert hits2[0]["target_foundations"] == 1
    assert hits2[0]["ka_ok"] is True
    src = inspect.getsource(classify_low_tail_transition)
    assert "FOUNDATION_AUTO_REMOVED" in src
    assert src.find("FOUNDATION_AUTO_REMOVED") < src.find("LOW_TAIL_PERSISTS")


def test_25_26_27_28_tail6_preview_statuses():
    src = inspect.getsource(reconstruct_tail6_preview)
    assert "READY_AT_SOURCE" in src
    assert "READY_WITHIN_5" in src
    assert "LIVE_BEYOND_5" in src
    assert "EXACT_DEAD_TO_TAIL6_READY" in src
    assert "found[\"depth\"] == 0" in src.replace(" ", "") or 'found["depth"] == 0' in src
    rec_state = synthetic_columns([tail_run("c", 5), [Card("c", 6)], *_kings(8)])
    rec = {
        "g": 92,
        "full_actions": [],
        "ordered_digest": pack_state(rec_state).hex(),
        "symmetry_digest": pack_post_stock_symmetry_state(rec_state).hex(),
    }
    hit = reconstruct_tail6_preview(rec, "c")
    assert hit["status"] == "READY_AT_SOURCE"
    assert tail6_ready(rec_state, "c")


def test_29_optional_t5_t6_uses_classifier():
    src = Path(ROOT / "research" / "post_sd5_club_diamond_tail5_v0_51.py").read_text(encoding="utf-8")
    assert "classify_low_tail_transition" in src
    assert "packet_head_rank=5" in src


def test_30_31_32_no_rank7_f3_spade_heart():
    text = SCRIPT.read_text(encoding="utf-8") + MOD.read_text(encoding="utf-8")
    assert "rank 7" in text.lower() or "rank-7" in text.lower()
    assert "Foundation 3" in text or "Foundation-3" in text
    assert "Spades" in text
    assert "Hearts" in text


def test_33_fixture_replays_if_present():
    opening = _opening()
    for path in (CLUB_FIX, DIA_FIX):
        if not path.exists():
            continue
        end = opening.clone()
        cost = replay_actions(end, parse_moves_file(path))
        assert stock_rows(end) == 0
        assert len(end.foundations) == 2
        assert cost >= 0


def test_34_production_mw_green():
    assert MW_RULES.can_deal_into_empty is True
    opening = _opening()
    rec = json.loads(CLUB_T4.read_text(encoding="utf-8"))["transitions"][0]
    st = opening.clone()
    replay_actions(st, as_actions(rec["full_actions"]))
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(st, **kwargs)
    b = solve_progressive(st, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b.nodes
    assert "search_tail5_ready" not in inspect.getsource(solve_progressive)
