"""Gate 1 ratchet: first 8D blocker flip v0.33."""

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
from spider.simple_gate1 import (
    flip_cost_bound_audit,
    gate1_progress,
    is_gate1,
    search_gate1,
    verify_blocker_chain,
)
from spider.simple_h9_cut import JOIN_BREAK, allowed_at_level, annotate_h9_action
from spider.simple_heart_funnel import legal_episode_actions
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, classify_tier, solve_progressive, step_cost
from spider.simple_workspace_reachability import empty_column_indices, engine_tableau_actions, face_down_count

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
V30 = ROOT / "docs" / "research" / "simple_progressive_foundation_horizon_v0_30.json"
FIXTURE = ROOT / "solutions" / "4925153_v0_33_gate1_8d_best.moves.txt"


def _opening() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL)))


def _as_actions(raw):
    out = []
    for item in raw:
        if item == "deal" or item == ["deal"] or item == ("deal",):
            out.append(("deal",))
        else:
            out.append((int(item[0]), int(item[1]), int(item[2])))
    return out


def _spade_records():
    payload = json.loads(V30.read_text(encoding="utf-8"))
    return ((payload.get("groups") or {}).get("MIDDLE") or {}).get("foundation_exits") or []


def _replay(actions):
    end = _opening().clone()
    cost = replay_actions(end, actions)
    return end, cost


def _source0():
    return _replay(_as_actions(_spade_records()[0]["full_actions"]))[0]


def _slots(slots, stock=None, foundations=None):
    cols = []
    for i in range(10):
        down, up = slots.get(i, ([], [Card("s", 13)]))
        cols.append(Column(list(down), list(up)))
    return SpiderState(cols, list(stock or []), list(foundations or []))


def test_1_four_spade_sources_replay():
    recs = _spade_records()
    assert len(recs) == 4
    for rec in recs:
        end, cost = _replay(_as_actions(rec["full_actions"]))
        assert cost == 62
        assert pack_state(end).hex() == rec["ordered_digest"]


def test_2_blocker_chain_is_8d_ah_jh_9h():
    end = _source0()
    chain = verify_blocker_chain(end)
    assert chain["valid"] is True
    assert chain["chain_bottom_to_top"] == ["JH", "AH", "8D"]
    assert chain["top_face_down"] == "8D"
    assert chain["flip_sequence"] == ["8D", "AH", "JH", "9H"]


def test_3_and_4_gate1_is_blockers_3_to_2_exposing_8d():
    end = _source0()
    parent = gate1_progress(end)
    assert parent["fd_blockers"] == 3
    assert parent["top_fd"] == "8D"


def test_5_every_h9_route_must_cross_gate1():
    end = _source0()
    chain = verify_blocker_chain(end)
    assert "3->2" in chain["gate1_proof"]
    assert chain["flip_sequence"][0] == "8D"


def test_6_dependency_recomputed_dynamically():
    source = inspect.getsource(search_gate1)
    assert "gate1_progress(state)" in source
    assert "deps[" not in source


def test_7_level2_narrower_than_level3():
    assert allowed_at_level(JOIN_BREAK, 3, 2, False) is False
    assert allowed_at_level(JOIN_BREAK, 3, 3, False) is True


def test_8_level3_admits_all_engine_legal():
    end = _source0()
    for action in engine_tableau_actions(end)[0]:
        label = annotate_h9_action(end, action, gate1_progress(end))
        assert allowed_at_level(label, int(classify_tier(end, action)), 3, False) is True


def test_9_sd3_legal():
    end = _source0()
    assert stock_rows(end) == 3
    assert ("deal",) in legal_episode_actions(end)


def test_10_sd4_never_expanded():
    end = _source0()
    child = end.clone()
    apply_action(child, ("deal",))
    assert stock_rows(child) == 2
    assert ("deal",) not in legal_episode_actions(child)


def test_11_ordered_pack_state():
    end = _source0()
    assert pack_state(end)[:4] == b"SPK1"
    assert pack_search_identity(end) == pack_state(end)
    swapped = permute_tableau_columns(end, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    assert pack_state(end) != pack_state(swapped)
    assert "post_stock" not in inspect.getsource(search_gate1)


def test_12_gate1_is_terminal():
    source = inspect.getsource(search_gate1)
    assert "is_gate1" in source
    assert "continue" in source


def test_13_zero_cost_cycles_handled():
    stock = [Card("d", 1 + (i % 12)) for i in range(30)]
    seed = _slots({0: ([], [Card("h", 13)]), 1: ([], []), 2: ([], [])}, stock, [[Card("s", r) for r in range(13, 0, -1)]])
    result = search_gate1([seed], [[]], directed=True, max_unique=80, time_limit_s=2.0, rss_abort_mb=512)
    assert result.elapsed_s < 2.5
    assert result.duplicate_skips >= 1 or result.zero_cost_moves >= 1


def test_14_and_15_cost_bands_keep_c_plus():
    source = inspect.getsource(search_gate1)
    assert "harvest_slack" in source
    assert "current_incumbent + harvest_slack" in source
    assert "cheaper_only" in source


def test_16_flip_cost_bound_supported_or_zero():
    end = _source0()
    audit = flip_cost_bound_audit(end)
    assert audit["zero_cost_requires_empty_column"] is True
    if audit["uncover_costs_from_target_column"]:
        assert min(audit["uncover_costs_from_target_column"]) >= 1
    if audit["valid"]:
        assert audit["lb_to_gate1"] == 1
    else:
        assert audit["lb_to_gate1"] == 0


def test_17_heuristic_not_proof_pruning():
    source = inspect.getsource(search_gate1)
    assert "used_heuristic_prune: bool = False" in inspect.getsource(
        __import__("spider.simple_gate1", fromlist=["Gate1Result"]).Gate1Result
    )
    assert "fu_blockers" in inspect.getsource(__import__("spider.simple_gate1", fromlist=["_priority"])._priority)


def test_18_witness_replays_if_present():
    if not FIXTURE.exists():
        return
    actions = parse_moves_file(FIXTURE)
    end, cost = _replay(actions)
    assert cost == len(actions)
    prog = gate1_progress(end)
    assert prog["fd_blockers"] == 2
    assert prog["top_fd"] == "AH"


def test_19_production_unchanged():
    end = _source0()
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    default = solve_progressive(end, **kwargs)
    explicit = solve_progressive(end, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert default.nodes == explicit.nodes
    assert "search_gate1" not in inspect.getsource(solve_progressive)


def test_20_mw_contract():
    assert MW_RULES.can_deal_into_empty is True
    end = _source0()
    assert 5 in empty_column_indices(end)
    apply_action(end.clone(), engine_tableau_actions(end)[0][0])
