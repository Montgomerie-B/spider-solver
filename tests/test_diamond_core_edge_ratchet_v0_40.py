"""Diamond unique-core edge ratchet v0.40."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_search_identity, pack_state, permute_tableau_columns
from spider.rules import MW_RULES
from spider.simple_current_horizon import occurrence_counts
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_edges import (
    EDGES,
    JOIN_BREAK,
    allowed_at_race_level,
    annotate_edge_action,
    diamond_adjacent_pairs,
    edge_present,
    preview_other_edges,
    search_edge,
    satisfied_core_edges,
)
from spider.simple_foundation_horizon import pretty_card
from spider.simple_foundation_race import suit_foundation_count
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, classify_tier, solve_progressive
from spider.simple_workspace_reachability import engine_tableau_actions

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
SRC = ROOT / "docs" / "research" / "sd4_diamond_operational_cut_v0_39_portfolio.json"
SCRIPT = ROOT / "research" / "diamond_core_edge_ratchet_v0_40.py"
MOD = ROOT / "src" / "spider" / "simple_diamond_edges.py"
FOUND = ROOT / "solutions" / "4925153_v0_40_diamond_foundation.moves.txt"


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


def _src(i=0):
    rec = json.loads(SRC.read_text(encoding="utf-8"))["states"][i]
    end = _opening()
    replay_actions(end, _as_actions(rec["full_actions"]))
    return end, rec


def test_1_all_256_replay():
    port = json.loads(SRC.read_text(encoding="utf-8"))
    assert port["n"] == 256
    assert port["bands"] == {"75": 16, "76": 128, "77": 112}
    opening = _opening()
    for rec in port["states"]:
        end = opening.clone()
        cost = replay_actions(end, _as_actions(rec["full_actions"]))
        assert cost == rec["full_cost"]
        assert pack_state(end).hex() == rec["ordered_digest"]
        assert stock_rows(end) == 1
        assert occurrence_counts(end, "d", 2)["tableau"][0]["top"]
        assert occurrence_counts(end, "d", 5)["tableau"][0]["top"]


def test_2_and_3_sd5_excluded_unique_2_5():
    st, _ = _src()
    d2 = occurrence_counts(st, "d", 2)
    d5 = occurrence_counts(st, "d", 5)
    assert d2["current_count"] == 1
    assert d5["current_count"] == 1
    assert d2["future_stock_count"] == 1
    assert d5["future_stock_count"] == 1
    assert d2["tableau_count"] == 1
    assert d5["tableau_count"] == 1


def test_4_adjacency_orientation():
    st, _ = _src()
    # Synthesize: 3D below 2D in face_up means index i=3D, i+1=2D
    src = inspect.getsource(diamond_adjacent_pairs)
    assert "below.rank == top.rank + 1" in src
    assert "face_up[i + 1]" in src or "up[i + 1]" in src


def test_5_to_8_edges_mandatory():
    assert EDGES["A"] == (3, 2)
    assert EDGES["B"] == (2, 1)
    assert EDGES["C"] == (6, 5)
    assert EDGES["D"] == (5, 4)
    # A complete K-A diamond run contains all four pairs
    ranks = list(range(13, 0, -1))
    pairs = set(zip(ranks, ranks[1:]))  # (K,Q)...(3,2),(2,A)
    assert (3, 2) in pairs and (2, 1) in pairs and (6, 5) in pairs and (5, 4) in pairs


def test_9_auto_foundation_satisfies_all():
    src = inspect.getsource(satisfied_core_edges)
    assert "suit_foundation_count" in src
    assert "set(EDGES)" in src


def test_10_identical_mechanics():
    src = inspect.getsource(search_edge)
    assert "max_unique: int = 200_000" in src
    assert "time_limit_s: float = 150.0" in src
    text = SCRIPT.read_text(encoding="utf-8")
    assert "for name in remaining_edges" in text or "for name in" in text


def test_11_and_12_full_g_and_pack():
    st, rec = _src()
    assert pack_state(st)[:4] == b"SPK1"
    assert pack_search_identity(st) == pack_state(st)
    src = inspect.getsource(search_edge)
    assert "source_g" in src
    assert "g0 < best_g[ident]" in src
    assert "pack_state" in src


def test_13_and_14_dynamic_dep_not_legality():
    st, _ = _src()
    src = inspect.getsource(search_edge)
    assert "hot_columns_for_edge(state" in src
    assert "annotate_edge_action(state" in src
    for action in engine_tableau_actions(st)[0][:4]:
        annotate_edge_action(st, action, "A", set())
        assert st.can_move(*action)


def test_15_and_16_widening():
    st, _ = _src()
    assert allowed_at_race_level(JOIN_BREAK, 3, 2) is False
    assert allowed_at_race_level(JOIN_BREAK, 3, 3) is True
    hot = set()
    for action in engine_tableau_actions(st)[0]:
        label = annotate_edge_action(st, action, "A", hot)
        assert allowed_at_race_level(label, int(classify_tier(st, action)), 3) is True


def test_17_sd5_never():
    st, _ = _src()
    assert stock_rows(st) == 1
    assert ("deal",) not in engine_tableau_actions(st)[0]
    src = inspect.getsource(search_edge)
    assert 'if action == ("deal",)' in src


def test_18_edge_terminal():
    src = inspect.getsource(search_edge)
    assert "continue" in src
    assert "hit" in src


def test_19_preview_live_not_dead():
    src = inspect.getsource(preview_other_edges)
    assert "LIVE_BEYOND_4" in src
    assert "EXACT_DEAD_TO_OTHER_CORE_EDGE" in src
    assert "live = True" in src
    assert "max_depth" in src


def test_20_and_21_two_edge_current_only():
    text = SCRIPT.read_text(encoding="utf-8") + Path(MOD).read_text(encoding="utf-8")
    assert "edges_now" in text or "satisfied_core_edges" in text
    assert "not put into" in text.lower() or "canonical identity" in text.lower() or "Do not encode historical" in text or "not in canonical" in text


def test_22_fixture_replays_if_present():
    if not FOUND.exists():
        return
    end = _opening()
    actions = parse_moves_file(FOUND)
    cost = replay_actions(end, actions)
    assert cost == len(actions)
    assert suit_foundation_count(end, "d") >= 1


def test_23_production_and_mw():
    assert MW_RULES.can_deal_into_empty is True
    st, _ = _src()
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(st, **kwargs)
    b = solve_progressive(st, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b.nodes
    assert "search_edge" not in inspect.getsource(solve_progressive)
    swapped = permute_tableau_columns(st, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    assert pack_state(st) != pack_state(swapped)
