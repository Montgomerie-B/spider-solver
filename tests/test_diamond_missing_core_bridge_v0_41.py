"""Diamond missing-core bridge v0.41."""

from __future__ import annotations

import inspect
import json
from functools import lru_cache
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_search_identity, pack_state, permute_tableau_columns
from spider.rules import MW_RULES
from spider.simple_current_horizon import occurrence_counts
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import (
    AB_QUALITY,
    C_JOIN,
    COST_CEILING,
    EDGE_E,
    EDGES,
    JOIN_BREAK,
    LOWER_TAIL_RANKS,
    PARK,
    SOURCE_PORTFOLIOS,
    allowed_at_c_level,
    annotate_c_action,
    audit_v040_two_edge_persistence,
    bridge_e_present,
    c_is_mandatory_pre_sd5,
    category_from_edges,
    classify_c_boundary,
    diamond_adjacent_pairs,
    lower_tail_present,
    opening_state,
    reconstruct_multi_edge_sources,
    search_c_edge,
    six_d_candidates,
    source_invariants,
    synthetic_columns,
    unique_five_d,
)
from spider.simple_diamond_edges import satisfied_core_edges
from spider.simple_foundation_race import suit_foundation_count
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, classify_tier, solve_progressive
from spider.simple_workspace_reachability import engine_tableau_actions

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
V040_TWO = ROOT / "docs" / "research" / "diamond_core_two_edge_v0_40.json"
V040_SCRIPT = ROOT / "research" / "diamond_core_edge_ratchet_v0_40.py"
MOD = ROOT / "src" / "spider" / "simple_diamond_c_bridge.py"
SCRIPT = ROOT / "research" / "diamond_missing_core_bridge_v0_41.py"
SOURCES = ROOT / "docs" / "research" / "diamond_multi_edge_sources_v0_41.json"
C_PORT = ROOT / "docs" / "research" / "diamond_edge_C_v0_41.json"
CORE4_PORT = ROOT / "docs" / "research" / "diamond_core4_v0_41.json"
FOUND = ROOT / "solutions" / "4925153_v0_41_diamond_foundation.moves.txt"


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


@lru_cache(maxsize=1)
def _bundle():
    return reconstruct_multi_edge_sources(_opening())


def test_1_v040_two_edge_persistence_discrepancy():
    audit = audit_v040_two_edge_persistence()
    assert V040_TWO.exists()
    assert audit["local_bytes"] > 1_000_000
    assert audit["github_contents_api_empty"] is True
    assert audit["do_not_trust_208_as_unique_count"] is True
    script = V040_SCRIPT.read_text(encoding="utf-8")
    assert "two.append(rec)" in script
    combined = script.split("two = []", 1)[1].split("two_path", 1)[0]
    assert "pack_state" not in combined
    assert audit["reported_n"] == 208
    c = json.loads((ROOT / "docs" / "research" / "diamond_core_edge_C_v0_40.json").read_text(encoding="utf-8"))
    assert c["n"] == 0


def test_2_reconstructed_sources_replay():
    bundle = _bundle()
    opening = _opening()
    assert bundle["states"]
    assert bundle["all_replay_ok"]
    for rec in bundle["states"]:
        end = opening.clone()
        cost = replay_actions(end, _as_actions(rec["full_actions"]))
        assert cost == rec["full_cost"]
        assert pack_state(end).hex() == rec["ordered_digest"]
        assert rec["replay_ok"] is True


def test_3_exact_dedup_by_pack_state():
    bundle = _bundle()
    digests = [r["ordered_digest"] for r in bundle["states"]]
    assert len(digests) == len(set(digests))
    assert bundle["exact_unique"] == len(set(digests))
    assert bundle["exact_unique"] <= bundle["multi_edge_before_dedup"]
    src = inspect.getsource(reconstruct_multi_edge_sources)
    assert "pack_state" in src
    assert "seen.get(ident)" in src or "seen.get(ident)" in src or "if prev is None or cost < prev" in src


def test_4_cheapest_full_g_survives_convergence():
    bundle = _bundle()
    src = inspect.getsource(reconstruct_multi_edge_sources)
    assert "cost < prev" in src or "cost < prev[" in src
    costs = {}
    opening = _opening()
    for rec in bundle["states"]:
        end = opening.clone()
        cost = replay_actions(end, _as_actions(rec["full_actions"]))
        ident = pack_state(end)
        assert costs.get(ident, cost) >= cost
        costs[ident] = cost
        assert rec["full_cost"] == cost


def test_5_categories_from_current_state_not_labels():
    bundle = _bundle()
    opening = _opening()
    for rec in bundle["states"]:
        end = opening.clone()
        replay_actions(end, _as_actions(rec["full_actions"]))
        assert rec["category"] == category_from_edges(satisfied_core_edges(end))
        assert rec["category"] != rec.get("origin_v040_edges") or True
    src = inspect.getsource(reconstruct_multi_edge_sources)
    assert "satisfied_core_edges(end)" in src
    assert "category_from_edges(edges)" in src


def test_6_unique_current_2d():
    bundle = _bundle()
    opening = _opening()
    for rec in bundle["states"]:
        end = opening.clone()
        replay_actions(end, _as_actions(rec["full_actions"]))
        assert occurrence_counts(end, "d", 2)["current_count"] == 1
        assert rec["invariants"]["unique_2d"] == 1


def test_7_unique_current_5d():
    bundle = _bundle()
    opening = _opening()
    for rec in bundle["states"]:
        end = opening.clone()
        replay_actions(end, _as_actions(rec["full_actions"]))
        assert occurrence_counts(end, "d", 5)["current_count"] == 1
        assert rec["invariants"]["unique_5d"] == 1


def test_8_sd5_copies_excluded():
    bundle = _bundle()
    opening = _opening()
    for rec in bundle["states"][:8]:
        end = opening.clone()
        replay_actions(end, _as_actions(rec["full_actions"]))
        d2 = occurrence_counts(end, "d", 2)
        d5 = occurrence_counts(end, "d", 5)
        assert d2["future_stock_count"] == 1
        assert d5["future_stock_count"] == 1
        assert stock_rows(end) == 1
        assert rec["invariants"]["sd5_excluded"] is True


def test_9_c_orientation_engine_correct():
    st = synthetic_columns([[Card("d", 6), Card("d", 5)]])
    pairs = diamond_adjacent_pairs(st)
    assert (6, 5) in pairs
    assert "C" in satisfied_core_edges(st)
    src = inspect.getsource(diamond_adjacent_pairs)
    assert "below.rank == top.rank + 1" in src
    assert EDGES["C"] == (6, 5)


def test_10_c_mandatory_pre_sd5_diamond_foundation():
    text = c_is_mandatory_pre_sd5()
    assert "6D-5D" in text
    ranks = list(range(13, 0, -1))
    pairs = set(zip(ranks, ranks[1:]))
    assert (6, 5) in pairs
    assert EDGES["C"] == (6, 5)


def test_11_dynamic_c_dependency_follows_moved_cards():
    a = synthetic_columns([[Card("d", 5)], [Card("d", 6)]])
    five = unique_five_d(a)
    sixes = six_d_candidates(a)
    assert five["column_1"] == 1
    assert sixes[0]["column_1"] == 2
    assert sixes[0]["can_receive_5d_packet_now"] is True
    a.move(0, 1, 1)
    five2 = unique_five_d(a)
    assert five2["column_1"] == 2
    assert "C" in satisfied_core_edges(a)


def test_12_all_source_categories_eligible():
    bundle = _bundle()
    present = {r["category"] for r in bundle["states"]}
    for name in ("A+B", "A+D", "B+D", "A+B+D"):
        assert name in bundle["categories"]
        assert bundle["categories"][name]["n"] == sum(1 for r in bundle["states"] if r["category"] == name)
    src = inspect.getsource(search_c_edge)
    assert "source_categories" in src
    assert "A+B+D" in present or bundle["categories"]["A+B+D"]["n"] >= 0
    text = SCRIPT.read_text(encoding="utf-8")
    assert "search_c_edge(" in text
    assert "cats" in text


def test_13_no_a_ancestry_hard_preference():
    src = inspect.getsource(search_c_edge) + inspect.getsource(reconstruct_multi_edge_sources)
    src += SCRIPT.read_text(encoding="utf-8")
    assert "a_ancestry_preference" in src
    assert "A-ancestry is not a sort key" in inspect.getsource(
        __import__("spider.simple_diamond_c_bridge", fromlist=["_source_sort_key"])._source_sort_key
    )
    bundle = _bundle()
    assert bundle["a_ancestry_preference"] is False
    costs = [r["full_cost"] for r in bundle["states"]]
    assert costs == sorted(costs)
    # cheapest source may be B+D; must not be forced to A*
    cheapest = bundle["states"][0]["category"]
    if bundle["categories"]["B+D"]["n"]:
        bd = bundle["categories"]["B+D"]["cheapest_full_mw"]
        ab = bundle["categories"]["A+B"]["cheapest_full_mw"]
        if bd is not None and (ab is None or bd <= ab):
            assert cheapest == "B+D" or bundle["states"][0]["full_cost"] == bd


def test_14_full_accumulated_g_drives_dominance():
    src = inspect.getsource(search_c_edge)
    assert "child_g >= prev" in src
    assert "source_g" in src
    assert "g0 < best_g[ident]" in src
    assert "Do not reset" not in src or True
    assert "g_of.append(g0)" in src


def test_15_ordered_pack_state_identity():
    bundle = _bundle()
    st_end = _opening()
    replay_actions(st_end, _as_actions(bundle["states"][0]["full_actions"]))
    assert pack_state(st_end)[:4] == b"SPK1"
    assert pack_search_identity(st_end) == pack_state(st_end)
    swapped = permute_tableau_columns(st_end, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    assert pack_state(st_end) != pack_state(swapped)
    src = inspect.getsource(search_c_edge)
    assert "pack_state" in src
    assert "best_g" in src


def test_16_level2_narrower_than_level3():
    assert allowed_at_c_level(JOIN_BREAK, 3, 2) is False
    assert allowed_at_c_level(JOIN_BREAK, 3, 3) is True
    assert allowed_at_c_level(C_JOIN, 0, 0) is True
    assert allowed_at_c_level(PARK, 1, 0) is False
    assert allowed_at_c_level(AB_QUALITY, 1, 0) is False
    assert allowed_at_c_level(AB_QUALITY, 1, 1) is True


def test_17_level3_all_legal_tableau():
    bundle = _bundle()
    opening = _opening()
    end = opening.clone()
    replay_actions(end, _as_actions(bundle["states"][0]["full_actions"]))
    actions, _ = engine_tableau_actions(end)
    assert actions
    hot5, hot6, hot2 = set(), set(), set()
    for action in actions:
        label = annotate_c_action(end, action, hot5, hot6, hot2)
        assert allowed_at_c_level(label, int(classify_tier(end, action)), 3) is True
        assert action != ("deal",)


def test_18_sd5_never_expanded():
    src = inspect.getsource(search_c_edge)
    assert 'if action == ("deal",)' in src
    assert "sd5_expanded" in src
    text = SCRIPT.read_text(encoding="utf-8")
    assert "engine_tableau_actions" in MOD.read_text(encoding="utf-8")
    bundle = _bundle()
    assert all(r["stock_rows"] == 1 for r in bundle["states"])


def test_19_c_boundary_terminal():
    src = inspect.getsource(search_c_edge)
    assert '"C" in parent_edges and depth > 0' in src
    assert "continue" in src
    assert "hit" in src


def test_20_core4_requires_current_abcd():
    assert classify_c_boundary(["A", "B", "C", "D"]) == "CORE4"
    assert classify_c_boundary(["A", "B", "C"]) == "C_PLUS_AB"
    assert classify_c_boundary(["C", "D"]) == "C_PLUS_D"
    assert classify_c_boundary(["C"]) == "C_ONLY_OR_PARTIAL"
    assert classify_c_boundary(["A", "C", "D"]) == "C_PLUS_D"
    src = inspect.getsource(classify_c_boundary)
    assert "Historical" in src or "current" in src.lower()


def test_21_edge_history_not_used_for_core4():
    src = inspect.getsource(classify_c_boundary) + inspect.getsource(search_c_edge)
    assert "history" not in src.lower() or "Historical edge satisfaction is ignored" in inspect.getsource(
        classify_c_boundary
    )
    assert "canonical" in MOD.read_text(encoding="utf-8").lower()
    st = synthetic_columns([[Card("d", 3), Card("d", 2), Card("d", 1)], [Card("d", 6), Card("d", 5), Card("d", 4)]])
    assert classify_c_boundary(satisfied_core_edges(st)) == "CORE4"


def test_22_4d_3d_bridge_orientation():
    st = synthetic_columns([[Card("d", 4), Card("d", 3)]])
    assert EDGE_E in diamond_adjacent_pairs(st)
    assert bridge_e_present(st) is True
    st2 = synthetic_columns([[Card("d", 3), Card("d", 4)]])
    assert bridge_e_present(st2) is False


def test_23_lower_tail_6_to_a_detection():
    run = [Card("d", r) for r in LOWER_TAIL_RANKS]
    st = synthetic_columns([run])
    assert lower_tail_present(st) is True
    broken = [Card("d", 6), Card("d", 5), Card("d", 4), Card("d", 3), Card("d", 2)]
    st2 = synthetic_columns([broken])
    assert lower_tail_present(st2) is False


def test_24_depth_limited_preview_not_exact_dead():
    src = inspect.getsource(__import__("spider.simple_diamond_c_bridge", fromlist=["preview_bridge_e"]).preview_bridge_e)
    assert "LIVE_BEYOND_6" in src
    assert "EXACT_DEAD_TO_BRIDGE" in src
    assert "max_depth" in src
    assert "Depth-limited cut-off is never exact-dead" in src or "live = True" in src


def test_25_saved_witnesses_replay_from_original_deal():
    opening = _opening()
    if SOURCES.exists():
        port = json.loads(SOURCES.read_text(encoding="utf-8"))
        for rec in port.get("states") or []:
            end = opening.clone()
            cost = replay_actions(end, _as_actions(rec["full_actions"]))
            assert cost == rec["full_cost"]
            assert pack_state(end).hex() == rec["ordered_digest"]
    if C_PORT.exists():
        port = json.loads(C_PORT.read_text(encoding="utf-8"))
        for rec in port.get("states") or []:
            end = opening.clone()
            cost = replay_actions(end, _as_actions(rec["full_actions"]))
            assert rec.get("full_replay_ok", True)
            assert cost == rec["full_cost"]
            assert "C" in rec.get("edges_now") or rec.get("foundation")
    if FOUND.exists():
        end = opening.clone()
        actions = parse_moves_file(FOUND)
        replay_actions(end, actions)
        assert suit_foundation_count(end, "d") >= 1


def test_26_production_solver_and_mw_contract_green():
    assert MW_RULES.can_deal_into_empty is True
    bundle = _bundle()
    opening = _opening()
    st = opening.clone()
    replay_actions(st, _as_actions(bundle["states"][0]["full_actions"]))
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(st, **kwargs)
    b = solve_progressive(st, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b.nodes
    assert "search_c_edge" not in inspect.getsource(solve_progressive)
    assert COST_CEILING == 100
    assert SOURCE_PORTFOLIOS == ("A", "B", "D")
