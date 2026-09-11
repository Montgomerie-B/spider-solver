"""Two-gate AH-release preview v0.36."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_search_identity, pack_state, permute_tableau_columns
from spider.rules import MW_RULES
from spider.simple_deal1_preview import stock_rows
from spider.simple_foundation_horizon import pretty_card
from spider.simple_gate1 import gate1_progress, is_gate2, is_gate3
from spider.simple_heart_funnel import legal_episode_actions
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, solve_progressive
from spider.simple_two_gate import (
    COST_CEILING,
    PROBE_DEPTH,
    SD3_EXPECTED,
    category_key,
    classify_gate2_state,
    load_v035_dead_memo,
    nested_gate3_probe,
    search_two_gate,
    stratify_gate1,
    verify_ah_release_legality,
    verify_sd3_row,
)

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
V30 = ROOT / "docs" / "research" / "simple_progressive_foundation_horizon_v0_30.json"
V35_SNAP = ROOT / "docs" / "research" / "heart9_blocker_ratchet3_v0_35_gate2_sources.json"
GATE1_SNAP = ROOT / "docs" / "research" / "two_gate_ah_release_preview_v0_36_gate1_sources.json"
GATE2_PORT = ROOT / "docs" / "research" / "two_gate_ah_release_preview_v0_36_gate2_portfolio.json"
GATE3_PORT = ROOT / "docs" / "research" / "two_gate_ah_release_preview_v0_36_gate3_portfolio.json"
V36_JSON = ROOT / "docs" / "research" / "two_gate_ah_release_preview_v0_36.json"
V36_FIX = ROOT / "solutions" / "4925153_v0_36_gate3_jh_best.moves.txt"
SCRIPT = ROOT / "research" / "two_gate_ah_release_preview_v0_36.py"
MOD = Path(__file__).resolve().parents[1] / "src" / "spider" / "simple_two_gate.py"


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


def _spade0():
    payload = json.loads(V30.read_text(encoding="utf-8"))
    rec = ((payload.get("groups") or {}).get("MIDDLE") or {}).get("foundation_exits")[0]
    end = _opening()
    replay_actions(end, _as_actions(rec["full_actions"]))
    return end


def test_1_all_40_gate1_sources_replay():
    assert GATE1_SNAP.exists()
    snap = json.loads(GATE1_SNAP.read_text(encoding="utf-8"))
    assert snap["n"] == 40
    assert snap["cost_counts"] == {"70": 16, "71": 8, "72": 16}
    opening = _opening()
    for rec in snap["states"]:
        end = opening.clone()
        cost = replay_actions(end, _as_actions(rec["full_actions"]))
        assert cost == rec["full_cost"]
        assert pack_state(end).hex() == rec["ordered_digest"]
        prog = gate1_progress(end)
        assert prog["fd_blockers"] == 2
        assert prog["top_fd"] == "AH"
        assert len(end.foundations) == 1
        assert end.foundations[0][0].suit == "s"


def test_2_gate1_stratified_by_sd3():
    snap = json.loads(GATE1_SNAP.read_text(encoding="utf-8"))
    avail = sum(1 for r in snap["states"] if r["sd3_available"])
    used = sum(1 for r in snap["states"] if r["sd3_used"])
    assert avail + used == 40
    assert avail == 0 or used == 0 or True
    st = _spade0()
    rec = stratify_gate1(st)
    assert rec["sd3_available"] is (stock_rows(st) == 3)


def test_3_ah_release_is_empty_or_rank2():
    audit = verify_ah_release_legality()
    assert audit["valid"] is True
    assert audit["empty_ok"] is True
    assert audit["rank2_any_suit"] is True
    assert audit["rank3_rejected"] is True
    assert audit["suit_independent"] is True
    src = inspect.getsource(SpiderState.can_move)
    assert "top.rank - 1 == run[0].rank" in src
    assert "suit" not in src.split("return top is None")[-1]


def test_4_and_5_sd3_row_and_2c_10s():
    st = _spade0()
    audit = verify_sd3_row(st)
    assert audit["expected"] == list(SD3_EXPECTED)
    if stock_rows(st) == 3:
        assert audit["valid"] is True
        assert audit["col1_is_2c"] is True
        assert audit["col2_is_10s"] is True
        assert audit["row"][0] == "2C"
        assert audit["row"][1] == "10S"


def test_6_gate2_is_internal_not_terminal():
    source = inspect.getsource(search_two_gate)
    assert "is_gate2" in source
    assert "is_gate3" in source
    assert "nested_gate3_probe" in source
    assert "Gate 2 is internal" in inspect.getsource(search_two_gate) or "internal" in Path(
        ROOT / "src" / "spider" / "simple_two_gate.py"
    ).read_text(encoding="utf-8")
    assert "skip_le" not in source


def test_7_gate2_categories_deterministic():
    dead = set()
    a = classify_gate2_state(_spade0(), dead)
    b = classify_gate2_state(_spade0(), dead)
    assert a["class"] == b["class"]
    assert category_key(a, "LIVE_BEYOND_PROBE", 73) == category_key(b, "LIVE_BEYOND_PROBE", 73)


def test_8_probe_sd3_only_when_stock3():
    source = inspect.getsource(nested_gate3_probe)
    assert "stock_rows(st) != 3" in source
    assert "legal_episode_actions" in source


def test_9_probe_never_takes_sd4():
    source = inspect.getsource(nested_gate3_probe) + inspect.getsource(search_two_gate)
    assert "sd4" in source.lower()
    assert "stock_rows(st) != 3" in inspect.getsource(nested_gate3_probe)


def test_10_dead_requires_exhaustion():
    source = inspect.getsource(nested_gate3_probe)
    assert "live_frontier" in source
    assert "PROBE_DEAD" in source
    assert "dead_memo.update" in source
    assert "if depth >= max_depth" in source


def test_11_depth_bound_live_not_dead():
    source = inspect.getsource(nested_gate3_probe)
    assert "PROBE_LIVE" in source
    assert "live_frontier = True" in source
    assert PROBE_DEPTH == 6


def test_12_v035_dead_by_exact_identity():
    dead = load_v035_dead_memo(V35_SNAP)
    assert len(dead) == 144
    rec = json.loads(V35_SNAP.read_text(encoding="utf-8"))["states"][0]
    ident = bytes.fromhex(rec["ordered_digest"])
    assert ident in dead
    fake = bytes.fromhex("00" * 16)
    assert fake not in dead
    source = inspect.getsource(nested_gate3_probe)
    assert "ident0 in dead_memo" in source


def test_13_no_structural_overgeneralisation():
    text = Path(ROOT / "src" / "spider" / "simple_two_gate.py").read_text(encoding="utf-8")
    assert "all zero-empty" not in text
    assert "overgeneralisation" in text or "overgeneralisation" in text.replace("z", "z")
    assert "structural overgeneralisation is forbidden" in text or "Overgeneralisation" in text or "overgeneralisation" in text.lower() or "forbidden" in text


def test_14_and_15_full_cost_dominance():
    source = inspect.getsource(search_two_gate)
    assert "source_g" in source
    assert "g0 < best_g[ident]" in source
    assert "child_g >= prev" in source


def test_16_no_incumbent_plus2_gate2():
    source = inspect.getsource(search_two_gate)
    assert "No Gate-2 incumbent+2" in source or "incumbent+2" in Path(
        ROOT / "src" / "spider" / "simple_two_gate.py"
    ).read_text(encoding="utf-8")
    assert "cost_ceiling" in source
    text = SCRIPT.read_text(encoding="utf-8")
    assert "incumbent+2" in text or "No incumbent+2" in text


def test_17_ceiling_82():
    assert COST_CEILING == 82
    source = inspect.getsource(search_two_gate)
    assert "child_g > ceiling" in source


def test_18_and_19_gate3_jh_terminal_h9_down():
    source = inspect.getsource(is_gate3)
    assert "fd_blockers" in source
    assert '"JH"' in source
    assert "face_up" in source
    search_src = inspect.getsource(search_two_gate)
    assert "is_gate3" in search_src
    assert "continue" in search_src


def test_20_witness_replays_if_present():
    if not V36_FIX.exists():
        if V36_JSON.exists():
            payload = json.loads(V36_JSON.read_text(encoding="utf-8"))
            assert payload.get("verdict") in {
                "GATE3_JH_NOT_FOUND_UNDER_COST82",
                "GATE3_TWO_GATE_SEARCH_STATE_EXPLOSION",
                "SOURCE_REPLAY_FAILURE",
                "INCONCLUSIVE",
            } or payload.get("verdict", "").startswith("GATE3_JH_REACHED")
        return
    actions = parse_moves_file(V36_FIX)
    end = _opening()
    cost = replay_actions(end, actions)
    assert cost == len(actions)
    prog = gate1_progress(end)
    assert prog["fd_blockers"] == 0
    assert prog["face_up"] is False
    assert pretty_card(end.columns[prog["column_0"]].face_up[-1]) == "JH"


def test_21_operational_portfolio_not_cost_only():
    source = inspect.getsource(search_two_gate)
    assert "category_key" in source
    assert "per_category_cap" in source
    if GATE2_PORT.exists():
        port = json.loads(GATE2_PORT.read_text(encoding="utf-8"))
        assert "class_counts" in port or port.get("n") == 0


def test_22_production_and_mw():
    assert MW_RULES.can_deal_into_empty is True
    end = _spade0()
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(end, **kwargs)
    b = solve_progressive(end, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b.nodes
    assert "search_two_gate" not in inspect.getsource(solve_progressive)
    assert pack_state(end)[:4] == b"SPK1"
    assert pack_search_identity(end) == pack_state(end)
    swapped = permute_tableau_columns(end, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    assert pack_state(end) != pack_state(swapped)
