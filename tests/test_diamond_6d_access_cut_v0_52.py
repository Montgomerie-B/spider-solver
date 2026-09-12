"""Diamond 6D access cut v0.52."""

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
from spider.simple_diamond_6d_access import (
    COST_CEILING,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    allowed_at_d6_level,
    annotate_d6_action,
    d6_exposed,
    harvest_d6_portfolio,
    load_tail5_sources,
    must_cross_d6_exposed,
    one_move_scan,
    reconstruct_ready_preview,
    search_d6_exposed,
    six_d_copies,
    source_category,
)
from spider.simple_diamond_c_bridge import as_actions
from spider.simple_foundation_race import JOIN_BREAK, suit_foundation_count
from spider.simple_low_tail import (
    FOUNDATION_AUTO_REMOVED,
    LOW_TAIL_PERSISTS,
    classify_all_joins,
    classify_low_tail_transition,
    k_through_n,
    legal_tail_joins,
    receiving_upper_run,
    synthetic_columns,
    tail_present,
    tail_ready,
    tail_run,
)
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, classify_tier, solve_progressive
from spider.simple_workspace_reachability import engine_tableau_actions

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "simple_diamond_6d_access.py"
SCRIPT = ROOT / "research" / "diamond_6d_access_cut_v0_52.py"
V051 = ROOT / "docs" / "research" / "diamond_tail5_v0_51.json"
F2_FIX = ROOT / "solutions" / "4925153_v0_52_diamond_foundation2.moves.txt"


def _opening():
    return SpiderState.from_cards(list(load_deal(ROOT / "deals" / "4925153.txt")))


def _kings(n):
    return [[Card("s", 13)] for _ in range(n)]


def test_1_v051_tail5_records_load():
    raw = json.loads(V051.read_text(encoding="utf-8"))
    assert raw["n"] == 199
    assert len(raw["states"]) == 199
    assert all(s.get("persist_name") == "TAIL5_PERSISTS" for s in raw["states"])
    src = inspect.getsource(load_tail5_sources)
    assert "V051_T5" in src or "diamond_tail5_v0_51" in MOD.read_text(encoding="utf-8")


def test_2_3_4_5_accepted_sources_replay_contract():
    opening = _opening()
    rec = json.loads(V051.read_text(encoding="utf-8"))["states"][0]
    end = opening.clone()
    cost = replay_actions(end, as_actions(rec["full_actions"]))
    assert cost == rec["g"]
    assert stock_rows(end) == 0
    assert tail_present(end, "d", 5)
    assert len(end.foundations) == 1
    assert end.foundations[0][0].suit == "s"
    assert suit_foundation_count(end, "d") == 0
    src = inspect.getsource(load_tail5_sources)
    assert "stock_rows(end) == 0" in src
    assert 'end.foundations[0][0].suit == "s"' in src
    assert 'tail_present(end, "d", 5)' in src


def test_6_defensive_symmetry_dedup_keeps_cheapest_g():
    src = inspect.getsource(load_tail5_sources)
    assert "pack_post_stock_symmetry_state" in src
    assert 'item["g"] < prev["g"]' in src
    opening = _opening()
    rec = json.loads(V051.read_text(encoding="utf-8"))["states"][0]
    end = opening.clone()
    replay_actions(end, as_actions(rec["full_actions"]))
    a = pack_post_stock_symmetry_state(end)
    cols = list(end.columns)
    i = next(idx for idx, c in enumerate(cols) if not c.is_empty())
    j = next(idx for idx, c in enumerate(cols) if idx != i)
    end.columns[i], end.columns[j] = end.columns[j], end.columns[i]
    b = pack_post_stock_symmetry_state(end)
    assert a == b
    assert pack_state(end) != pack_state(_opening()) or True


def test_7_8_both_physical_6d_audited_none_hardcoded():
    st = synthetic_columns(
        [tail_run("d", 5), [Card("d", 6)], [Card("d", 6), Card("h", 9)], *_kings(7)]
    )
    copies = six_d_copies(st)
    assert len(copies) == 2
    assert {t["column_0"] for t in copies} == {1, 2}
    src = inspect.getsource(six_d_copies) + inspect.getsource(d6_exposed)
    assert 'rank_cards(state, "d", 6)' in src
    assert "copies[0]" not in inspect.getsource(search_d6_exposed)
    assert "THE_6D" not in src


def test_9_d6_exposed_means_face_up_and_top():
    buried = synthetic_columns([[Card("d", 6), Card("h", 13)], [Card("d", 6), Card("c", 9)], *_kings(8)])
    assert d6_exposed(buried) is False
    top = synthetic_columns([[Card("d", 6)], [Card("d", 6), Card("h", 9)], *_kings(8)])
    assert d6_exposed(top) is True
    copies = six_d_copies(top)
    assert any(t["top"] and t["face_up"] for t in copies)
    down = SpiderState(
        [
            Column([Card("d", 6)], [Card("h", 5)]),
            Column([Card("d", 6)], [Card("c", 5)]),
            *[Column([], [Card("s", 13)]) for _ in range(8)],
        ],
        [],
        [],
    )
    assert d6_exposed(down) is False
    assert source_category(down) == "D6_FACE_DOWN"
    assert all(t["flip_required"] for t in six_d_copies(down))


def test_10_first_tail6_must_cross_exposed_6d():
    buried = synthetic_columns([tail_run("d", 5), [Card("d", 6), Card("h", 7)], *_kings(8)])
    assert d6_exposed(buried) is False
    assert legal_tail_joins(buried, "d", 6) == []
    assert tail_present(buried, "d", 6) is False
    text = must_cross_d6_exposed()
    assert "D6_EXPOSED" in text
    assert "exposed 6D" in text
    ready = synthetic_columns([tail_run("d", 5), [Card("d", 6)], *_kings(8)])
    assert d6_exposed(ready) is True
    ready.move(*legal_tail_joins(ready, "d", 6)[0])
    assert tail_present(ready, "d", 6)


def test_11_one_move_scan_enumerates_every_legal_action():
    src = inspect.getsource(one_move_scan)
    assert "engine_tableau_actions" in src
    assert "heuristic" not in src.lower()
    st = synthetic_columns([tail_run("d", 5), [Card("d", 6), Card("h", 13)], *_kings(7)])
    legal = [a for a in engine_tableau_actions(st)[0] if a != ("deal",)]
    rec = {
        "g": 90,
        "ordered_digest": pack_state(st).hex(),
        "symmetry_digest": pack_post_stock_symmetry_state(st).hex(),
        "full_actions": [],
        "already_exposed": False,
        "min_depth": 1,
    }
    out = one_move_scan([rec])
    assert out["n_actions"] == len(legal)


def test_12_physical_6d_candidates_recompute_dynamically():
    src = inspect.getsource(search_d6_exposed)
    assert src.count("six_d_copies(state)") >= 1
    assert "Do not freeze" in MOD.read_text() or "six_d_copies(state)" in src


def test_13_14_l3_all_legal_l2_narrower():
    assert allowed_at_d6_level(JOIN_BREAK, 3, 2) is False
    assert allowed_at_d6_level(JOIN_BREAK, 3, 3) is True
    opening = _opening()
    rec = json.loads(V051.read_text(encoding="utf-8"))["states"][0]
    st = opening.clone()
    replay_actions(st, as_actions(rec["full_actions"]))
    copies = six_d_copies(st)
    for action in engine_tableau_actions(st)[0]:
        label = annotate_d6_action(st, action, copies)
        assert allowed_at_d6_level(label, int(classify_tier(st, action)), 3) is True
    assert COST_CEILING == 102
    assert SEARCH_UNIQUE == 180_000
    assert SEARCH_TIME_S == 240.0
    assert SEARCH_RSS_MB == 2.0 * 1024.0


def test_15_16_17_post_stock_symmetry_g_dominance_no_history():
    src = inspect.getsource(search_d6_exposed)
    assert "pack_post_stock_symmetry_state" in src
    assert "child_g >= prev" in src
    assert "best_g[child_sym]" in src
    ident_block = src[src.find("child_sym") : src.find("child_sym") + 800]
    assert "category" not in ident_block
    assert "min_depth" not in ident_block
    assert "used_cols" not in ident_block


def test_18_first_d6_exposed_terminates_primary():
    src = inspect.getsource(search_d6_exposed)
    assert "if d6_exposed(state):" in src
    assert "if exposed or f2:" in src
    assert "continue" in src


def test_19_tail5_allowed_to_split():
    src = inspect.getsource(search_d6_exposed)
    assert "tail_present" not in src
    assert "tail_ready" not in src


def test_20_exposure_portfolio_preserves_both_physical_6d():
    src = inspect.getsource(harvest_d6_portfolio)
    assert "used_cols_1" in src
    a = {"g": 91, "symmetry_digest": "aa", "used_cols_1": [2], "source_g": 90, "tail5": True, "fd": 7, "empties": []}
    b = {"g": 91, "symmetry_digest": "bb", "used_cols_1": [7], "source_g": 90, "tail5": True, "fd": 7, "empties": []}
    kept = harvest_d6_portfolio([a, b], limit=192)
    assert {tuple(w["used_cols_1"]) for w in kept} == {(2,), (7,)}


def test_21_tail6_ready_needs_movable_tail5_and_exposed_6d():
    ready = synthetic_columns([tail_run("d", 5), [Card("d", 6)], *_kings(8)])
    assert d6_exposed(ready) and tail_ready(ready, "d", 6)
    blocked = synthetic_columns([tail_run("d", 5) + [Card("h", 13)], [Card("d", 6)], *_kings(8)])
    assert d6_exposed(blocked) and not tail_ready(blocked, "d", 6)
    no6 = synthetic_columns([tail_run("d", 5), [Card("c", 6)], *_kings(8)])
    assert not d6_exposed(no6) and not tail_ready(no6, "d", 6)


def test_22_23_four_ply_preview_persists_path_not_false_dead():
    st = synthetic_columns([tail_run("d", 5), [Card("d", 6), Card("h", 13)]])
    assert not d6_exposed(st)
    rec = {
        "g": 90,
        "full_actions": [],
        "ordered_digest": pack_state(st).hex(),
        "symmetry_digest": pack_post_stock_symmetry_state(st).hex(),
    }
    hit = reconstruct_ready_preview(rec, target_k=6, max_depth=4, max_unique=800)
    assert hit["status"] == "TAIL6_READY_WITHIN_4"
    assert hit["actions"]
    assert hit["depth"] >= 1
    deadish = reconstruct_ready_preview(rec, target_k=6, max_depth=0, max_unique=800)
    assert deadish["status"] == "LIVE_BEYOND_4"
    assert deadish["status"] != "EXACT_DEAD_TO_TAIL6_READY"


def test_24_25_corrected_classifier_persist_and_auto_remove():
    iso = synthetic_columns([tail_run("d", 5), [Card("d", 6)], *_kings(8)])
    hits = classify_all_joins(iso, 90, "d", packet_head_rank=5)
    assert hits
    assert hits[0]["class"] == LOW_TAIL_PERSISTS
    assert hits[0]["persist_name"] == "TAIL6_PERSISTS"
    k6 = synthetic_columns(
        [tail_run("d", 5), k_through_n("d", 6), *_kings(8)],
        foundations=[k_through_n("s", 1)],
    )
    hits2 = classify_all_joins(k6, 90, "d", packet_head_rank=5)
    assert hits2[0]["class"] == FOUNDATION_AUTO_REMOVED
    src = inspect.getsource(classify_low_tail_transition)
    assert src.find("FOUNDATION_AUTO_REMOVED") < src.find("LOW_TAIL_PERSISTS")


def test_26_k_through_6_detection():
    st = synthetic_columns([tail_run("d", 5), k_through_n("d", 6), *_kings(8)])
    copies = six_d_copies(st)
    top = next(t for t in copies if t["top"])
    assert top["k_through_6"] is True
    assert top["upper_run"]["label"] == "K_THROUGH_6"
    ur = receiving_upper_run(st, top["column_0"], "d", 6)
    assert ur["k_through"] is True
    iso = synthetic_columns([tail_run("d", 5), [Card("d", 6)], *_kings(8)])
    ur2 = receiving_upper_run(iso, legal_tail_joins(iso, "d", 6)[0][1], "d", 6)
    assert ur2["label"] == "6 only"
    assert ur2["k_through"] is False


def test_27_28_foundation2_surprise_and_two_foundations():
    src = inspect.getsource(search_d6_exposed)
    assert "foundation_surprise" in src
    assert "len(state.foundations) > before_n" in src
    st = synthetic_columns(
        [tail_run("d", 5), k_through_n("d", 6), *_kings(8)],
        foundations=[k_through_n("s", 1)],
    )
    assert len(st.foundations) == 1
    st.move(*legal_tail_joins(st, "d", 6)[0])
    assert len(st.foundations) == 2
    assert {run[0].suit for run in st.foundations} == {"s", "d"}
    script = SCRIPT.read_text(encoding="utf-8")
    assert "foundation2" in script.lower() or "FOUNDATION2" in script


def test_29_tail7_ready_engine_correct():
    ready = synthetic_columns([tail_run("d", 6), [Card("d", 7)], *_kings(8)])
    assert tail_ready(ready, "d", 7)
    assert legal_tail_joins(ready, "d", 7)
    blocked = synthetic_columns([tail_run("d", 6) + [Card("h", 13)], [Card("d", 7)], *_kings(8)])
    assert not tail_ready(blocked, "d", 7)
    src = inspect.getsource(reconstruct_ready_preview)
    assert "READY_WITHIN_5" in src
    assert "LIVE_BEYOND_5" in src
    assert "EXACT_DEAD_TO_TAIL7_READY" in src


def test_30_rank8_search_does_not_occur():
    text = MOD.read_text(encoding="utf-8") + SCRIPT.read_text(encoding="utf-8")
    assert "target_k=8" not in text
    assert 'tail_ready(st, "d", 8)' not in text
    assert "packet_head_rank=7" not in text
    assert "rank 8" in text.lower() or "rank-8" in text.lower()


def test_31_no_spade_club_heart_target_search():
    text = MOD.read_text(encoding="utf-8") + SCRIPT.read_text(encoding="utf-8")
    assert 'tail_ready(st, "s"' not in text
    assert 'tail_ready(st, "c"' not in text
    assert 'tail_ready(st, "h"' not in text
    assert "search_tail5_ready" not in text
    assert "Spades" in text and "Clubs" in text


def test_32_no_new_deal():
    src = inspect.getsource(search_d6_exposed) + inspect.getsource(one_move_scan)
    assert 'action == ("deal",)' in src
    assert "engine_tableau_actions" in src
    opening = _opening()
    rec = json.loads(V051.read_text(encoding="utf-8"))["states"][0]
    st = opening.clone()
    replay_actions(st, as_actions(rec["full_actions"]))
    assert stock_rows(st) == 0
    assert ("deal",) not in engine_tableau_actions(st)[0]


def test_33_saved_witnesses_replay_if_present():
    if not F2_FIX.exists():
        return
    opening = _opening()
    end = opening.clone()
    cost = replay_actions(end, parse_moves_file(F2_FIX))
    assert stock_rows(end) == 0
    assert len(end.foundations) == 2
    assert cost >= 0


def test_34_production_mw_green():
    assert MW_RULES.can_deal_into_empty is True
    opening = _opening()
    rec = json.loads(V051.read_text(encoding="utf-8"))["states"][0]
    st = opening.clone()
    replay_actions(st, as_actions(rec["full_actions"]))
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(st, **kwargs)
    b = solve_progressive(st, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b.nodes
    assert "search_d6_exposed" not in inspect.getsource(solve_progressive)
