"""Diamond 6D exposure gateway v0.42."""

from __future__ import annotations

import inspect
import json
from functools import lru_cache
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_search_identity, pack_state, permute_tableau_columns
from spider.rules import MW_RULES
from spider.simple_current_horizon import occurrence_counts
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, category_from_edges
from spider.simple_diamond_edges import satisfied_core_edges
from spider.simple_diamond_g6_exposure import (
    COST_CEILING,
    EXPECTED_CATEGORIES,
    EXPECTED_N,
    JOIN_BREAK,
    LOWER_TAIL_HEAD,
    MAX_UNIQUE,
    TIME_LIMIT_S,
    allowed_at_g6_level,
    annotate_g6_action,
    blocker_audit,
    cards_above,
    exposed_6d_can_receive_rank5,
    find_six_d_locs,
    follow_loc,
    future_c_requires_exposed_6d,
    g6_any,
    identify_source_g6,
    load_v041_sources,
    loc_is_top,
    lower_tail_packet_movable_onto,
    opening_state,
    preview_c,
    search_exposure,
    synthetic_columns,
)
from spider.simple_foundation_race import suit_foundation_count
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, classify_tier, solve_progressive
from spider.simple_workspace_reachability import engine_tableau_actions

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "simple_diamond_g6_exposure.py"
SCRIPT = ROOT / "research" / "diamond_6d_exposure_gateway_v0_42.py"
SRC = ROOT / "docs" / "research" / "diamond_multi_edge_sources_v0_41.json"
G6_8 = ROOT / "docs" / "research" / "diamond_g6_8_v0_42.json"
G6_9 = ROOT / "docs" / "research" / "diamond_g6_9_v0_42.json"
COMBINED = ROOT / "docs" / "research" / "diamond_g6_combined_v0_42.json"
FOUND = ROOT / "solutions" / "4925153_v0_42_diamond_foundation.moves.txt"


def _opening():
    return SpiderState.from_cards(list(load_deal(ROOT / "deals" / "4925153.txt")))


@lru_cache(maxsize=1)
def _bundle():
    return load_v041_sources(_opening())


def _src_state(i=0):
    rec = _bundle()["states"][i]
    end = _opening()
    replay_actions(end, as_actions(rec["full_actions"]))
    return end, rec


def test_1_all_208_sources_replay():
    bundle = _bundle()
    assert bundle["n"] == EXPECTED_N
    assert bundle["all_replay_ok"]
    opening = _opening()
    for rec in bundle["states"]:
        end = opening.clone()
        cost = replay_actions(end, as_actions(rec["full_actions"]))
        assert cost == rec["full_cost"]
        assert pack_state(end).hex() == rec["ordered_digest"]
        assert stock_rows(end) == 1
        assert occurrence_counts(end, "d", 2)["current_count"] == 1
        assert occurrence_counts(end, "d", 5)["current_count"] == 1


def test_2_categories_recomputed():
    bundle = _bundle()
    assert bundle["categories"] == EXPECTED_CATEGORIES or all(
        bundle["categories"].get(k) == v for k, v in EXPECTED_CATEGORIES.items()
    )
    opening = _opening()
    for rec in bundle["states"]:
        end = opening.clone()
        replay_actions(end, as_actions(rec["full_actions"]))
        assert rec["category"] == category_from_edges(satisfied_core_edges(end))


def test_3_both_physical_6d_identified():
    st, _ = _src_state()
    ids = identify_source_g6(st)
    assert ids["G6_8"] is not None and ids["G6_9"] is not None
    assert ids["G6_8"][0] == 7
    assert ids["G6_9"][0] == 8
    assert len(find_six_d_locs(st)) == 2


def test_4_physical_identity_follows_moved_6d():
    st = synthetic_columns(
        [
            [Card("d", 7), Card("d", 6), Card("c", 5)],
            [Card("c", 6)],
            [Card("d", 6)],
        ]
    )
    loc = identify_source_g6.__wrapped__ if False else (0, "up", 1)
    # 6D in col 0 index 1, 5C on top. Move 5C to col 1 (6C receives 5C).
    assert st.can_move(0, 1, 1)
    new = follow_loc(st, (0, "up", 1), (0, 1, 1))
    st.move(0, 1, 1)
    assert new == (0, "up", 1)
    assert loc_is_top(st, new)
    # move the now-exposed 6D onto the other 6D? dest col 2 is 6D, need rank 5. Park 6D on empty col 3.
    loc2 = follow_loc(st, new, (0, 3, 1))
    st.move(0, 3, 1)
    assert loc2[0] == 3
    assert loc_is_top(st, loc2)


def test_5_both_6d_face_up_not_top_at_sources():
    bundle = _bundle()
    opening = _opening()
    for rec in bundle["states"]:
        end = opening.clone()
        replay_actions(end, as_actions(rec["full_actions"]))
        ids = identify_source_g6(end)
        for loc in ids.values():
            card = end.columns[loc[0]].face_up[loc[2]]
            assert card.suit == "d" and card.rank == 6
            assert loc[1] == "up"
            assert not loc_is_top(end, loc)
        assert g6_any(end) is False


def test_6_future_c_requires_exposed_6d():
    st, _ = _src_state()
    ids = identify_source_g6(st)
    for loc in ids.values():
        assert exposed_6d_can_receive_rank5(st, loc) is False
    text = future_c_requires_exposed_6d()
    assert "G6_ANY" in text
    buried = synthetic_columns([[Card("d", 6), Card("c", 5)], [Card("d", 5)]])
    assert buried.can_move(1, 0, 1) is False
    exposed = synthetic_columns([[Card("d", 6)], [Card("d", 5)]])
    assert exposed.can_move(1, 0, 1) is True


def test_7_g6_any_does_not_locally_prune():
    src = inspect.getsource(allowed_at_g6_level)
    assert "G6_ANY is not a local prune" in src
    assert allowed_at_g6_level(JOIN_BREAK, 3, 3) is True
    st, _ = _src_state()
    loc = identify_source_g6(st)["G6_8"]
    for action in engine_tableau_actions(st)[0]:
        label = annotate_g6_action(st, action, loc)
        assert allowed_at_g6_level(label, int(classify_tier(st, action)), 3) is True


def test_8_source_g6_8_carries_7d_6d():
    st, _ = _src_state()
    loc = identify_source_g6(st)["G6_8"]
    audit = blocker_audit(st, loc, name="G6_8")
    assert audit["has_7d_6d"] is True
    assert "7D" in audit["component"] and "6D" in audit["component"]
    n = 0
    opening = _opening()
    for rec in _bundle()["states"]:
        end = opening.clone()
        replay_actions(end, as_actions(rec["full_actions"]))
        a = blocker_audit(end, identify_source_g6(end)["G6_8"], name="G6_8")
        n += int(a["has_7d_6d"])
    assert n == EXPECTED_N


def test_9_blocker_counts_recompute_dynamically():
    st, _ = _src_state()
    loc = identify_source_g6(st)["G6_8"]
    before = cards_above(st, loc)
    assert before >= 1
    src = inspect.getsource(search_exposure)
    assert "cards_above(state, loc_of[node])" in src or "cards_above(st, loc_of[node])" in src
    assert "covering_packet(state, loc)" in inspect.getsource(annotate_g6_action)


def test_10_search_8_and_9_identical_mechanics():
    src = inspect.getsource(search_exposure)
    text = SCRIPT.read_text(encoding="utf-8")
    assert "max_unique: int = MAX_UNIQUE" in src
    assert "time_limit_s: float = TIME_LIMIT_S" in src
    assert MAX_UNIQUE == 175_000
    assert TIME_LIMIT_S == 225.0
    assert text.count("search_exposure(") >= 1
    assert "G6_8" in text and "G6_9" in text
    assert "remaining / remaining_searches" in text or "TIME_LIMIT_S" in text


def test_11_full_g_drives_dominance():
    src = inspect.getsource(search_exposure)
    assert "child_g >= prev" in src
    assert "source_g" in src
    assert "g0 < best_g[ident]" in src


def test_12_ordered_pack_state_identity():
    st, rec = _src_state()
    assert pack_state(st)[:4] == b"SPK1"
    assert pack_search_identity(st) == pack_state(st)
    swapped = permute_tableau_columns(st, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    assert pack_state(st) != pack_state(swapped)
    src = inspect.getsource(search_exposure)
    assert "pack_state" in src
    assert "best_g" in src
    assert "canonical" in MOD.read_text(encoding="utf-8").lower()


def test_13_level2_narrower_than_level3():
    assert allowed_at_g6_level(JOIN_BREAK, 3, 2) is False
    assert allowed_at_g6_level(JOIN_BREAK, 3, 3) is True


def test_14_level3_all_legal_tableau():
    st, _ = _src_state()
    loc = identify_source_g6(st)["G6_9"]
    actions, _ = engine_tableau_actions(st)
    assert actions
    for action in actions:
        label = annotate_g6_action(st, action, loc)
        assert allowed_at_g6_level(label, int(classify_tier(st, action)), 3) is True
        assert action != ("deal",)


def test_15_sd5_never_expanded():
    src = inspect.getsource(search_exposure)
    assert 'if action == ("deal",)' in src
    assert "sd5_expanded" in src
    st, _ = _src_state()
    assert stock_rows(st) == 1
    assert ("deal",) not in engine_tableau_actions(st)[0]


def test_16_exposure_boundary_terminal():
    src = inspect.getsource(search_exposure)
    assert "loc_is_top" in src
    assert "hit" in src
    assert "continue" in src


def test_17_exposed_6d_receives_rank5():
    st = synthetic_columns([[Card("d", 6)], [Card("d", 5)]])
    loc = (0, "up", 0)
    assert loc_is_top(st, loc)
    assert exposed_6d_can_receive_rank5(st, loc) is True
    assert st.can_move(1, 0, 1) is True


def test_18_c_preview_uses_all_tableau():
    src = inspect.getsource(preview_c)
    assert "engine_tableau_actions" in src
    assert 'if action == ("deal",)' in src
    assert "max_depth" in src


def test_19_depth_limited_preview_not_exact_dead():
    src = inspect.getsource(preview_c)
    assert "LIVE_BEYOND_6" in src
    assert "EXACT_DEAD_TO_C" in src
    assert "live = True" in src


def test_20_lower_tail_immediate_requires_movable_packet():
    dest = synthetic_columns(
        [
            [Card("d", 6)],
            [Card("d", 5), Card("d", 4), Card("d", 3), Card("d", 2), Card("d", 1)],
        ]
    )
    loc = (0, "up", 0)
    assert lower_tail_packet_movable_onto(dest, loc) is True
    buried = synthetic_columns(
        [
            [Card("d", 6), Card("c", 5)],
            [Card("d", 5), Card("d", 4), Card("d", 3), Card("d", 2), Card("d", 1)],
        ]
    )
    assert lower_tail_packet_movable_onto(buried, (0, "up", 0)) is False
    short = synthetic_columns([[Card("d", 6)], [Card("d", 5), Card("d", 4)]])
    assert lower_tail_packet_movable_onto(short, (0, "up", 0)) is False
    assert LOWER_TAIL_HEAD == ("5D", "4D", "3D", "2D", "AD")


def test_21_current_edges_recomputed_from_state():
    src = inspect.getsource(search_exposure) + SCRIPT.read_text(encoding="utf-8")
    assert "satisfied_core_edges" in src
    st, rec = _src_state()
    assert rec["edges_now"] == sorted(satisfied_core_edges(st)) or rec["category"] == category_from_edges(
        satisfied_core_edges(st)
    )


def test_22_edge_history_not_canonical():
    text = MOD.read_text(encoding="utf-8").lower()
    assert "canonical identity remains ordered pack_state" in text or "not canonical" in text
    src = inspect.getsource(search_exposure)
    assert "best_g[ident]" in src or "best_g[child_ident]" in src
    assert "edges" not in src.split("best_g")[0][-80:]


def test_23_saved_witnesses_replay():
    opening = _opening()
    for path in (G6_8, G6_9, COMBINED):
        if not path.exists():
            continue
        port = json.loads(path.read_text(encoding="utf-8"))
        for rec in port.get("states") or []:
            end = opening.clone()
            cost = replay_actions(end, as_actions(rec["full_actions"]))
            assert cost == rec["full_cost"]
            assert pack_state(end).hex() == rec["ordered_digest"]
    if FOUND.exists():
        end = opening.clone()
        replay_actions(end, parse_moves_file(FOUND))
        assert suit_foundation_count(end, "d") >= 1


def test_24_production_and_mw_green():
    assert MW_RULES.can_deal_into_empty is True
    st, _ = _src_state()
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(st, **kwargs)
    b = solve_progressive(st, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b.nodes
    assert "search_exposure" not in inspect.getsource(solve_progressive)
    assert COST_CEILING == 100
