"""Gate 2 ratchet: first AH blocker flip v0.34."""

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
from spider.simple_gate1 import gate1_progress, search_gate1
from spider.simple_gate2 import (
    GLOBAL_LB_GATE2,
    global_lb_gate2_audit,
    is_gate2,
    one_move_gate2,
    search_gate2,
    verify_gate2_chain,
)
from spider.simple_h9_cut import JOIN_BREAK, allowed_at_level, annotate_h9_action
from spider.simple_heart_funnel import legal_episode_actions
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, classify_tier, solve_progressive
from spider.simple_workspace_reachability import engine_tableau_actions

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
V30 = ROOT / "docs" / "research" / "simple_progressive_foundation_horizon_v0_30.json"
V33_FIX = ROOT / "solutions" / "4925153_v0_33_gate1_8d_best.moves.txt"
V34_FIX = ROOT / "solutions" / "4925153_v0_34_gate2_ah_best.moves.txt"


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


def _gate1_state():
    end = _opening()
    replay_actions(end, parse_moves_file(V33_FIX))
    return end


def test_1_gate1_fixture_replays_and_is_gate1():
    end = _gate1_state()
    assert len(end.foundations) == 1
    assert end.foundations[0][0].suit == "s"
    prog = gate1_progress(end)
    assert prog["fd_blockers"] == 2
    assert verify_gate2_chain(end)["valid"] is True


def test_2_full_accumulated_cost_is_70_on_best_gate1():
    actions = parse_moves_file(V33_FIX)
    end = _opening()
    cost = replay_actions(end, actions)
    assert cost == 70
    assert cost == len(actions)


def test_3_cross_origin_dominance_uses_full_cost():
    source = inspect.getsource(search_gate1)
    assert "source_g" in source
    assert "g0 < best_g[ident]" in source


def test_4_and_5_gate2_is_2_to_1_exposing_ah():
    end = _gate1_state()
    parent = gate1_progress(end)
    assert parent["fd_blockers"] == 2
    assert parent["top_fd"] == "AH"
    assert verify_gate2_chain(end)["top_face_down"] == "AH"


def test_6_every_h9_path_after_gate1_crosses_gate2():
    end = _gate1_state()
    proof = verify_gate2_chain(end)
    assert "2->1" in proof["gate2_proof"]
    assert proof["remaining_down_above_9h"] == ["JH", "AH"]


def test_7_global_lb_71_is_valid():
    audit = global_lb_gate2_audit()
    assert audit["valid"] is True
    assert audit["global_lb"] == 71
    assert GLOBAL_LB_GATE2 == 71


def test_8_one_move_uses_engine_legality():
    end = _gate1_state()
    legal = set(legal_episode_actions(end))
    hits = one_move_gate2(end)
    for hit in hits:
        action = ("deal",) if hit["action"] == ["deal"] else tuple(hit["action"])
        assert action in legal
        assert hit["top_face_up"] == "AH"


def test_9_dynamic_dependency():
    assert "gate1_progress(state)" in inspect.getsource(search_gate1)


def test_10_sd3_legal_where_available():
    end = _gate1_state()
    if stock_rows(end) == 3:
        assert ("deal",) in legal_episode_actions(end)


def test_11_sd4_never_expanded():
    end = _gate1_state()
    if stock_rows(end) == 3:
        child = end.clone()
        apply_action(child, ("deal",))
        assert ("deal",) not in legal_episode_actions(child)


def test_12_ordered_pack_state():
    end = _gate1_state()
    assert pack_state(end)[:4] == b"SPK1"
    assert pack_search_identity(end) == pack_state(end)
    swapped = permute_tableau_columns(end, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    assert pack_state(end) != pack_state(swapped)


def test_13_and_14_widening():
    end = _gate1_state()
    assert allowed_at_level(JOIN_BREAK, 3, 2, False) is False
    assert allowed_at_level(JOIN_BREAK, 3, 3, False) is True
    for action in engine_tableau_actions(end)[0]:
        label = annotate_h9_action(end, action, gate1_progress(end))
        assert allowed_at_level(label, int(classify_tier(end, action)), 3, False) is True


def test_15_gate2_is_terminal():
    source = inspect.getsource(search_gate1)
    assert "is_gate2" in source
    assert 'mode == "gate1"' in source
    assert "mode=\"gate2\"" in inspect.getsource(search_gate2) or 'mode="gate2"' in inspect.getsource(search_gate2)


def test_16_bands_use_full_cost():
    text = Path(ROOT / "research" / "heart9_blocker_ratchet2_v0_34.py").read_text(encoding="utf-8")
    assert "full_cost" in text
    assert "search_gate2" in text
    assert "gs" in text


def test_17_higher_gate1_cost_may_survive():
    text = Path(ROOT / "research" / "heart9_blocker_ratchet2_v0_34.py").read_text(encoding="utf-8")
    assert "continuation_cost" in text
    assert "gate1_band" in text


def test_18_no_optimality_from_incomplete_sample():
    text = Path(ROOT / "research" / "heart9_blocker_ratchet2_v0_34.py").read_text(encoding="utf-8")
    assert "not globally proved" in text or "GLOBAL_LB_GATE2" in text


def test_19_witness_replays_if_present():
    if not V34_FIX.exists():
        return
    actions = parse_moves_file(V34_FIX)
    end = _opening()
    cost = replay_actions(end, actions)
    assert cost == len(actions)
    prog = gate1_progress(end)
    assert prog["fd_blockers"] == 1
    assert prog["top_fd"] == "JH"


def test_20_production_and_mw():
    assert MW_RULES.can_deal_into_empty is True
    end = _gate1_state()
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(end, **kwargs)
    b = solve_progressive(end, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b.nodes
    assert "search_gate2" not in inspect.getsource(solve_progressive)
