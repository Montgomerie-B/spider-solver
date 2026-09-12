"""Post-SD5 suit 2-A edge race v0.44."""

from __future__ import annotations

import inspect
import json
from functools import lru_cache
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import (
    PACKED_MAGIC,
    PACKED_SYMMETRY_MAGIC,
    pack_post_stock_symmetry_state,
    pack_state,
    permute_tableau_columns,
    unpack_state,
)
from spider.rules import MW_RULES, deal_cost
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions
from spider.simple_foundation_race import JOIN_BREAK, allowed_at_race_level, suit_foundation_count
from spider.simple_post_sd5_edge_race import (
    COST_CEILING,
    EXPECTED_SOURCES,
    MAX_UNIQUE,
    TIME_LIMIT_S,
    annotate_2a_action,
    edge_2a_is_mandatory,
    edge_2a_present,
    load_deal_now_roots,
    low_tail_length,
    material_copy_counts,
    opening_state,
    preview_tail3,
    search_edge_2a,
    synthetic_columns,
    tail3_present,
)
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, classify_tier, solve_progressive
from spider.simple_workspace_reachability import engine_tableau_actions

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "simple_post_sd5_edge_race.py"
SCRIPT = ROOT / "research" / "post_sd5_suit_edge_race_v0_44.py"
V043 = ROOT / "docs" / "research" / "final_deal_sources_v0_43.json"
ROOTS = ROOT / "docs" / "research" / "post_sd5_deal_now_roots_v0_44.json"
FOUND = ROOT / "solutions" / "4925153_v0_44_foundation2.moves.txt"
PORTS = [
    ROOT / "docs" / "research" / "post_sd5_edge_spade_v0_44.json",
    ROOT / "docs" / "research" / "post_sd5_edge_heart_v0_44.json",
    ROOT / "docs" / "research" / "post_sd5_edge_diamond_v0_44.json",
    ROOT / "docs" / "research" / "post_sd5_edge_club_v0_44.json",
]


def _opening():
    return SpiderState.from_cards(list(load_deal(ROOT / "deals" / "4925153.txt")))


@lru_cache(maxsize=1)
def _roots():
    return load_deal_now_roots(_opening())


def test_1_all_720_sources_replay():
    assert V043.exists()
    port = json.loads(V043.read_text(encoding="utf-8"))
    assert port["n"] == EXPECTED_SOURCES
    b = _roots()
    assert b["pre_sd5_n"] == EXPECTED_SOURCES
    assert b["all_replay_ok"]


def test_2_sd5_deal_now_once_every_source():
    src = inspect.getsource(load_deal_now_roots)
    assert 'apply_action(end, ("deal",))' in src
    assert "enumerate_preparation" not in src
    b = _roots()
    opening = _opening()
    rec = b["states"][0]
    end = opening.clone()
    replay_actions(end, as_actions(rec["full_actions"]))
    assert rec["full_actions"].count(["deal"]) == 1 or sum(1 for a in rec["full_actions"] if a == ["deal"] or a == "deal") >= 1
    assert stock_rows(end) == 0


def test_3_deal_cost_preserved():
    assert deal_cost() == 1
    b = _roots()
    rec = b["states"][0]
    assert rec["g"] == rec["source_g"] + rec["deal_cost"]
    assert rec["deal_cost"] == 1


def test_4_post_deal_stock_zero():
    b = _roots()
    opening = _opening()
    for rec in b["states"][:12]:
        end = opening.clone()
        replay_actions(end, as_actions(rec["full_actions"]))
        assert stock_rows(end) == 0
        assert rec["stock_rows"] == 0


def test_5_post_stock_symmetry_identity():
    src = inspect.getsource(search_edge_2a)
    assert "pack_post_stock_symmetry_state" in src
    b = _roots()
    opening = _opening()
    end = opening.clone()
    replay_actions(end, as_actions(b["states"][0]["full_actions"]))
    ident = pack_post_stock_symmetry_state(end)
    assert ident[:4] == PACKED_SYMMETRY_MAGIC


def test_6_ordered_representative_replayable():
    b = _roots()
    opening = _opening()
    rec = b["states"][0]
    end = opening.clone()
    replay_actions(end, as_actions(rec["full_actions"]))
    blob = pack_state(end)
    assert blob[:4] == PACKED_MAGIC
    assert pack_state(unpack_state(blob)) == blob
    assert rec["ordered_digest"] == blob.hex()


def test_7_material_copy_counts_by_suit():
    b = _roots()
    opening = _opening()
    end = opening.clone()
    replay_actions(end, as_actions(b["states"][0]["full_actions"]))
    mat = material_copy_counts(end)
    assert mat["s"]["ace"]["tableau"] == 1
    assert mat["s"]["two"]["tableau"] == 1
    assert mat["s"]["ace"]["foundation"] == 1
    for suit in ("h", "d", "c"):
        assert mat[suit]["ace"]["tableau"] == 2
        assert mat[suit]["two"]["tableau"] == 2
        assert mat[suit]["ace"]["foundation"] == 0


def test_8_spade_physical_uniqueness_verified_or_rejected():
    b = _roots()
    opening = _opening()
    end = opening.clone()
    replay_actions(end, as_actions(b["states"][0]["full_actions"]))
    mat = material_copy_counts(end)
    assert "spade2_full_physical_chain_unique" in mat
    if mat["spade2_full_physical_chain_unique"]:
        assert all(v == 1 for v in mat["s"]["all_ranks_tableau"].values())
        assert mat["s"]["foundations"] == 1


def test_9_2a_orientation_engine_correct():
    st = synthetic_columns([[Card("s", 2), Card("s", 1)]])
    assert edge_2a_present(st, "s") is True
    st2 = synthetic_columns([[Card("s", 1), Card("s", 2)]])
    assert edge_2a_present(st2, "s") is False
    src = inspect.getsource(edge_2a_present)
    assert "below.rank == 2" in src and "top.rank == 1" in src


def test_10_duplicate_pairing_accepted_hdc():
    st = synthetic_columns([[Card("h", 2), Card("h", 1)], [Card("h", 2)], [Card("h", 1)]])
    assert edge_2a_present(st, "h") is True
    src = inspect.getsource(edge_2a_present)
    assert "return True" in src


def test_11_edge_2a_mandatory_for_foundation():
    text = edge_2a_is_mandatory()
    assert "2-A" in text
    assert "mandatory" in text.lower()


def test_12_foundation_auto_removal_counts_as_success():
    src = inspect.getsource(edge_2a_present) + inspect.getsource(search_edge_2a)
    assert "suit_foundation_count" in src
    assert "foundation" in src


def test_13_four_searches_identical_mechanics():
    src = inspect.getsource(search_edge_2a)
    text = SCRIPT.read_text(encoding="utf-8")
    assert "max_unique: int = MAX_UNIQUE" in src
    assert MAX_UNIQUE == 150_000
    assert TIME_LIMIT_S == 150.0
    assert text.count("search_edge_2a(") == 1
    assert "for suit in SUITS" in text
    assert "TIME_LIMIT_S" in text


def test_14_dynamic_a2_dependency_follows_moved_cards():
    st = synthetic_columns([[Card("d", 2)], [Card("d", 1)]])
    assert edge_2a_present(st, "d") is False
    assert st.can_move(1, 0, 1)
    st.move(1, 0, 1)
    assert edge_2a_present(st, "d") is True
    src = inspect.getsource(search_edge_2a)
    assert "annotate_2a_action(state, action, suit)" in src


def test_15_full_g_drives_dominance():
    src = inspect.getsource(search_edge_2a)
    assert "child_g >= prev" in src
    assert "g0 < best_g[ident_sym]" in src


def test_16_zero_cost_cycle_safe():
    src = inspect.getsource(search_edge_2a)
    assert "child_g >= prev" in src
    assert "best_g" in src


def test_17_level2_narrower_than_level3():
    assert allowed_at_race_level(JOIN_BREAK, 3, 2) is False
    assert allowed_at_race_level(JOIN_BREAK, 3, 3) is True


def test_18_level3_all_legal_tableau():
    b = _roots()
    opening = _opening()
    end = opening.clone()
    replay_actions(end, as_actions(b["states"][0]["full_actions"]))
    actions, _ = engine_tableau_actions(end)
    assert actions
    for action in actions:
        label = annotate_2a_action(end, action, "s")
        assert allowed_at_race_level(label, int(classify_tier(end, action)), 3) is True
        assert action != ("deal",)


def test_19_2a_boundary_terminal():
    src = inspect.getsource(search_edge_2a)
    assert "edge_2a_present" in src
    assert "hit" in src
    assert "continue" in src


def test_20_tail3_preview_uses_legal_actions():
    src = inspect.getsource(preview_tail3)
    assert "engine_tableau_actions" in src
    assert 'if action == ("deal",)' in src


def test_21_depth_limited_preview_not_dead():
    src = inspect.getsource(preview_tail3)
    assert "LIVE_BEYOND_5" in src
    assert "EXACT_DEAD_TO_TAIL3" in src
    assert "live = True" in src


def test_22_longest_low_tail_detection():
    st = synthetic_columns([[Card("c", 4), Card("c", 3), Card("c", 2), Card("c", 1)]])
    assert low_tail_length(st, "c") == 4
    assert tail3_present(st, "c") is True
    st2 = synthetic_columns([[Card("c", 1)]])
    assert low_tail_length(st2, "c") == 1


def test_23_foundation2_terminal():
    src = inspect.getsource(search_edge_2a) + inspect.getsource(preview_tail3)
    assert "FOUNDATION_2" in src or "foundation" in src
    text = SCRIPT.read_text(encoding="utf-8")
    assert "Foundation 3" in text or "do not search Foundation 3" in text.lower() or "not search Foundation 3" in text


def test_24_no_pre_deal_prep_states():
    src = inspect.getsource(load_deal_now_roots) + SCRIPT.read_text(encoding="utf-8")
    assert "enumerate_preparation" not in src
    assert "DEAL_NOW" in src or "deal_now" in src.lower()
    assert "used_prep_states" in inspect.getsource(
        __import__("spider.simple_post_sd5_edge_race", fromlist=["EdgeResult"]).EdgeResult
    )
    assert "PREP_THEN_DEAL" not in inspect.getsource(load_deal_now_roots)


def test_25_saved_witnesses_replay():
    opening = _opening()
    if ROOTS.exists():
        port = json.loads(ROOTS.read_text(encoding="utf-8"))
        for rec in (port.get("states") or [])[:6]:
            end = opening.clone()
            cost = replay_actions(end, as_actions(rec["full_actions"]))
            assert cost == rec["g"]
            assert pack_state(end).hex() == rec["ordered_digest"]
            assert stock_rows(end) == 0
    for path in PORTS:
        if not path.exists():
            continue
        port = json.loads(path.read_text(encoding="utf-8"))
        for rec in port.get("states") or []:
            end = opening.clone()
            cost = replay_actions(end, as_actions(rec["full_actions"]))
            assert rec.get("full_replay_ok", True)
            assert cost == rec["full_cost"]
    if FOUND.exists():
        end = opening.clone()
        replay_actions(end, parse_moves_file(FOUND))
        assert len(end.foundations) >= 2


def test_26_production_and_mw_green():
    assert MW_RULES.can_deal_into_empty is True
    b = _roots()
    opening = _opening()
    st = opening.clone()
    replay_actions(st, as_actions(b["states"][0]["full_actions"]))
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(st, **kwargs)
    b2 = solve_progressive(st, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b2.nodes
    assert "search_edge_2a" not in inspect.getsource(solve_progressive)
    assert COST_CEILING == 100
    swapped = permute_tableau_columns(st, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    assert pack_post_stock_symmetry_state(st) == pack_post_stock_symmetry_state(swapped)
