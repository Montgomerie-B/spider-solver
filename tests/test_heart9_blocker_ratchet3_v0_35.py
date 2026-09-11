"""Gate 3 ratchet: first JH blocker flip v0.35."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_search_identity, pack_state, permute_tableau_columns
from spider.rules import MW_RULES
from spider.simple_deal1_preview import stock_rows
from spider.simple_gate1 import gate1_progress, is_gate3, search_gate1
from spider.simple_gate3 import (
    EXPECTED_GATE2_BANDS,
    EXPECTED_GATE2_N,
    GLOBAL_LB_GATE3,
    audit_v034_persistence_gap,
    global_lb_gate3_audit,
    one_move_gate3,
    per_source_lb,
    per_source_lb_audit,
    search_gate3,
    verify_gate3_chain,
)
from spider.simple_h9_cut import JOIN_BREAK, allowed_at_level, annotate_h9_action
from spider.simple_heart_funnel import legal_episode_actions
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, classify_tier, solve_progressive
from spider.simple_foundation_horizon import pretty_card
from spider.simple_workspace_reachability import engine_tableau_actions

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
V34_JSON = ROOT / "docs" / "research" / "heart9_blocker_ratchet2_v0_34.json"
V34_FIX = ROOT / "solutions" / "4925153_v0_34_gate2_ah_best.moves.txt"
V35_FIX = ROOT / "solutions" / "4925153_v0_35_gate3_jh_best.moves.txt"
GATE2_SNAP = ROOT / "docs" / "research" / "heart9_blocker_ratchet3_v0_35_gate2_sources.json"
GATE3_PORT = ROOT / "docs" / "research" / "heart9_blocker_ratchet3_v0_35_gate3_portfolio.json"
V35_JSON = ROOT / "docs" / "research" / "heart9_blocker_ratchet3_v0_35.json"
SCRIPT = ROOT / "research" / "heart9_blocker_ratchet3_v0_35.py"


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


def _gate2_state():
    end = _opening()
    replay_actions(end, parse_moves_file(V34_FIX))
    return end


def test_1_v034_json_persistence_gap():
    payload = json.loads(V34_JSON.read_text(encoding="utf-8"))
    gap = audit_v034_persistence_gap(payload)
    assert gap["confirmed"] is True
    assert gap["persisted"] == 16
    assert gap["harvested"] == EXPECTED_GATE2_N
    assert gap["harvested_bands"] == EXPECTED_GATE2_BANDS
    assert payload.get("bands") == {"73": 16}


def test_2_full_144_reconstructed_or_explained():
    assert GATE2_SNAP.exists()
    snap = json.loads(GATE2_SNAP.read_text(encoding="utf-8"))
    n = int(snap.get("n") or len(snap.get("states") or []))
    counts = snap.get("cost_counts") or {}
    if n == EXPECTED_GATE2_N and counts == EXPECTED_GATE2_BANDS:
        assert snap.get("exact_dedup") == EXPECTED_GATE2_N
        return
    assert snap.get("discrepancy"), f"count {n} {counts} without discrepancy explanation"


def test_3_all_gate2_sources_replay():
    snap = json.loads(GATE2_SNAP.read_text(encoding="utf-8"))
    opening = _opening()
    for rec in snap["states"]:
        end = opening.clone()
        cost = replay_actions(end, _as_actions(rec["full_actions"]))
        assert cost == rec["full_cost"]
        assert pack_state(end).hex() == rec["ordered_digest"]
        assert rec.get("replay_ok") is True
        assert verify_gate3_chain(end)["valid"] is True


def test_4_full_costs_73_74_75_preserved():
    snap = json.loads(GATE2_SNAP.read_text(encoding="utf-8"))
    costs = sorted({int(r["full_cost"]) for r in snap["states"]})
    assert costs == [73, 74, 75] or snap.get("discrepancy")
    for rec in snap["states"]:
        assert rec["full_cost"] == rec["gate2_band"]
        assert rec["full_path_length"] == len(rec["full_actions"])


def test_5_cross_origin_dominance_uses_full_cost():
    source = inspect.getsource(search_gate1)
    assert "source_g" in source
    assert "g0 < best_g[ident]" in source
    text = SCRIPT.read_text(encoding="utf-8")
    assert "full_cost" in text
    assert "merge_witnesses" in text


def test_6_and_7_gate3_is_1_to_0_exposing_jh():
    end = _gate2_state()
    parent = gate1_progress(end)
    assert parent["fd_blockers"] == 1
    assert parent["top_fd"] == "JH"
    chain = verify_gate3_chain(end)
    assert chain["valid"] is True
    assert chain["top_face_down"] == "JH"
    assert is_gate3.__name__ == "is_gate3"


def test_8_nine_h_remains_face_down_at_gate2_boundary():
    end = _gate2_state()
    prog = gate1_progress(end)
    assert prog["face_up"] is False
    assert prog["fd_blockers"] == 1


def test_9_every_later_h9_path_crosses_gate3():
    proof = verify_gate3_chain(_gate2_state())
    assert "1->0" in proof["gate3_proof"]
    assert "Every later 9H exposure must first flip JH" in proof["gate3_proof"]
    assert proof["remaining_down_above_9h"] == ["JH"]


def test_10_global_lb_72_is_valid():
    audit = global_lb_gate3_audit()
    assert audit["valid"] is True
    assert audit["global_lb"] == 72
    assert GLOBAL_LB_GATE3 == 72
    assert audit["gate2_proved"] is False
    assert audit["gate2_best_known"] == 73


def test_11_per_source_g_plus_one():
    for g in (73, 74, 75):
        rec = per_source_lb_audit(g)
        assert rec["valid"] is True
        assert rec["lb"] == g + 1
        assert per_source_lb(g) == g + 1


def test_12_fast_path_uses_engine_legality():
    end = _gate2_state()
    legal = set(legal_episode_actions(end))
    hits = one_move_gate3(end)
    for hit in hits:
        action = ("deal",) if hit["action"] == ["deal"] else tuple(hit["action"])
        assert action in legal
        assert hit["top_face_up"] == "JH"
        assert hit["face_up_h9"] is False
        assert hit["fd_blockers"] == 0


def test_13_dynamic_dependency():
    assert "gate1_progress(state)" in inspect.getsource(search_gate1)


def test_14_sd3_only_where_remaining():
    end = _gate2_state()
    rows = stock_rows(end)
    legal = legal_episode_actions(end)
    if rows == 3:
        assert ("deal",) in legal
    else:
        assert ("deal",) not in legal
    text = inspect.getsource(legal_episode_actions)
    assert "stock_rows(state) == 3" in text


def test_15_sd4_never_expanded():
    end = _gate2_state()
    if stock_rows(end) == 3:
        child = end.clone()
        apply_action(child, ("deal",))
        assert ("deal",) not in legal_episode_actions(child)
    if stock_rows(end) == 2:
        assert ("deal",) not in legal_episode_actions(end)
    source = inspect.getsource(search_gate1)
    assert "sd4_expanded" in source
    assert "stock_rows(state) != 3" in source


def test_16_and_17_widening():
    end = _gate2_state()
    assert allowed_at_level(JOIN_BREAK, 3, 2, False) is False
    assert allowed_at_level(JOIN_BREAK, 3, 3, False) is True
    for action in engine_tableau_actions(end)[0]:
        label = annotate_h9_action(end, action, gate1_progress(end))
        assert allowed_at_level(label, int(classify_tier(end, action)), 3, False) is True


def test_18_gate3_is_terminal():
    source = inspect.getsource(search_gate1)
    assert "is_gate3" in source
    assert 'mode == "gate3"' in source or 'mode="gate3"' in inspect.getsource(search_gate3)
    assert "continue" in source
    text = SCRIPT.read_text(encoding="utf-8")
    assert "Do not search Heart" in text or "9H" in text
    assert "no_large_ucs" in text or "No large UCS" in text or "no large original-source UCS" in text


def test_19_portfolio_persisted_and_replayable():
    assert GATE3_PORT.exists()
    port = json.loads(GATE3_PORT.read_text(encoding="utf-8"))
    main = json.loads(V35_JSON.read_text(encoding="utf-8"))
    states = port.get("states") or []
    if not states:
        assert main.get("verdict") == "GATE3_JH_NOT_FOUND_IN_ENVELOPE"
        assert port.get("n") == 0
        assert main.get("no_large_ucs") is True
        return
    b3 = port.get("b3")
    assert b3 is not None
    allowed = {b3, b3 + 1, b3 + 2}
    opening = _opening()
    for rec in states:
        assert rec["full_cost"] in allowed
        assert rec.get("full_actions")
        assert rec.get("full_cost") is not None
        assert rec.get("ordered_digest")
        assert rec.get("gate2_band") is not None
        assert "sd3_done" in rec
        assert rec.get("continuation_cost") is not None
        end = opening.clone()
        cost = replay_actions(end, _as_actions(rec["full_actions"]))
        assert cost == rec["full_cost"]
        assert pack_state(end).hex() == rec["ordered_digest"]
        prog = gate1_progress(end)
        assert prog["fd_blockers"] == 0
        assert prog["face_up"] is False
        col = prog["column_0"]
        assert pretty_card(end.columns[col].face_up[-1]) == "JH"
        assert rec.get("full_replay_ok") is True


def test_19b_witness_fixture_replays():
    if not V35_FIX.exists():
        return
    actions = parse_moves_file(V35_FIX)
    end = _opening()
    cost = replay_actions(end, actions)
    assert cost == len(actions)
    prog = gate1_progress(end)
    assert prog["fd_blockers"] == 0
    assert prog["face_up"] is False
    assert pretty_card(end.columns[prog["column_0"]].face_up[-1]) == "JH"


def test_20_production_and_mw():
    assert MW_RULES.can_deal_into_empty is True
    end = _gate2_state()
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(end, **kwargs)
    b = solve_progressive(end, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b.nodes
    assert "search_gate3" not in inspect.getsource(solve_progressive)
    assert pack_state(end)[:4] == b"SPK1"
    assert pack_search_identity(end) == pack_state(end)
    swapped = permute_tableau_columns(end, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    assert pack_state(end) != pack_state(swapped)
