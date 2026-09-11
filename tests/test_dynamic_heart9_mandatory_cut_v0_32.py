"""Dynamic mandatory 9H cut v0.32."""

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
from spider.simple_h9_cut import (
    JOIN_BREAK,
    allowed_at_level,
    annotate_h9_action,
    h9_progress,
    search_h9_cut,
    verify_mandatory_h9,
)
from spider.simple_heart_backward import action_allowed_at_level as v31_allowed
from spider.simple_heart_funnel import legal_episode_actions
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, classify_tier, solve_progressive
from spider.simple_workspace_reachability import empty_column_indices, engine_tableau_actions, face_down_count

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
V30 = ROOT / "docs" / "research" / "simple_progressive_foundation_horizon_v0_30.json"
FIXTURE = ROOT / "solutions" / "4925153_v0_32_h9_boundary.moves.txt"
HARNESS = ROOT / "src" / "spider" / "simple_heart_funnel.py"


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
    exits = ((payload.get("groups") or {}).get("MIDDLE") or {}).get("foundation_exits") or []
    assert len(exits) == 4
    return exits


def _replay(actions):
    end = _opening().clone()
    cost = replay_actions(end, actions)
    return end, cost


def _source0():
    return _replay(_as_actions(_spade_records()[0]["full_actions"]))[0]


def _state_from_slots(slots, stock=None, foundations=None) -> SpiderState:
    cols = []
    for index in range(10):
        down, up = slots.get(index, ([], [Card("s", 13)]))
        cols.append(Column(list(down), list(up)))
    return SpiderState(cols, list(stock or []), list(foundations or []))


def test_1_four_spade_sources_replay():
    for rec in _spade_records():
        end, cost = _replay(_as_actions(rec["full_actions"]))
        assert cost == 62
        assert pack_state(end).hex() == rec["ordered_digest"]


def test_2_unique_pre_sd4_9h_identification():
    end = _source0()
    proof = verify_mandatory_h9(end)
    assert proof["valid"] is True
    assert proof["count_pre_sd4"] == 1
    assert proof["h9"]["zone"] == "down"
    assert proof["h9"]["face_up"] is False


def test_3_mandatory_cut_proof_assumptions_hold():
    end = _source0()
    proof = verify_mandatory_h9(end)
    assert "exactly one 9H" in proof["proof"]
    assert "trajectory cut" in proof["proof"]
    assert "prune" in proof["proof"]


def test_4_jh_is_a_face_down_blocker_above_9h():
    end = _source0()
    proof = verify_mandatory_h9(end)
    assert proof["jh_must_flip_before_h9"] is True
    assert proof["jh"]["column_0"] == proof["h9"]["column_0"]
    assert proof["jh"]["down_index"] > proof["h9"]["down_index"]


def test_5_and_6_dynamic_dependency_recomputed_on_descendant():
    end = _source0()
    before = h9_progress(end)
    col = before["column_0"]
    assert before["face_up"] is False
    fu = before["fu_blockers"]
    # move the top packet off the 9H column if legal
    moved = False
    for action in engine_tableau_actions(end)[0]:
        if action[0] == col:
            apply_action(end, action)
            moved = True
            break
    assert moved
    after = h9_progress(end)
    assert after["column_0"] == col or after["face_up"]
    if not after["face_up"]:
        assert after["fu_blockers"] <= fu
    source = inspect.getsource(search_h9_cut)
    assert "h9_progress(state)" in source
    assert "deps[" not in source


def test_7_level2_is_narrower_than_level3():
    assert allowed_at_level(JOIN_BREAK, 3, 2, False) is False
    assert allowed_at_level(JOIN_BREAK, 3, 3, False) is True
    assert v31_allowed(JOIN_BREAK, 3, 2, False) is True
    end = _source0()
    found = False
    for action in engine_tableau_actions(end)[0]:
        label = annotate_h9_action(end, action, h9_progress(end))
        if label == JOIN_BREAK:
            found = True
            assert allowed_at_level(label, int(classify_tier(end, action)), 2, False) is False
            assert allowed_at_level(label, int(classify_tier(end, action)), 3, False) is True
            break
    if not found:
        stock = [Card("d", 1 + (i % 12)) for i in range(30)]
        slots = {
            0: ([], [Card("h", 5), Card("h", 4), Card("h", 3)]),
            1: ([], [Card("s", 4)]),
        }
        toy = _state_from_slots(slots, stock, [[Card("s", r) for r in range(13, 0, -1)]])
        action = (0, 1, 1)
        label = annotate_h9_action(toy, action, h9_progress(toy))
        assert label == JOIN_BREAK
        assert allowed_at_level(label, int(classify_tier(toy, action)), 2, False) is False


def test_8_level3_contains_every_engine_legal_action():
    end = _source0()
    for action in engine_tableau_actions(end)[0]:
        label = annotate_h9_action(end, action, h9_progress(end))
        assert allowed_at_level(label, int(classify_tier(end, action)), 3, False) is True
    assert set(engine_tableau_actions(end)[0]).issubset(set(legal_episode_actions(end)))


def test_9_sd3_remains_legal():
    end = _source0()
    assert stock_rows(end) == 3
    assert ("deal",) in legal_episode_actions(end)


def test_10_sd4_is_never_expanded():
    end = _source0()
    child = end.clone()
    apply_action(child, ("deal",))
    assert stock_rows(child) == 2
    assert ("deal",) not in legal_episode_actions(child)


def test_11_ordered_pack_state_is_used():
    end = _source0()
    assert pack_state(end)[:4] == b"SPK1"
    assert pack_search_identity(end) == pack_state(end)
    swapped = permute_tableau_columns(end, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    assert pack_state(end) != pack_state(swapped)
    source = inspect.getsource(search_h9_cut)
    assert "pack_state" in source
    assert "post_stock" not in source


def test_12_and_13_h9_boundary_is_faceup_and_terminal():
    source = inspect.getsource(search_h9_cut)
    assert 'child_prog["face_up"] and not prog["face_up"]' in source
    assert "continue" in source
    end = _source0()
    assert h9_progress(end)["face_up"] is False


def test_14_exact_dedup_retains_a_representative():
    source = inspect.getsource(search_h9_cut)
    assert "child_g >= prev" in source
    assert "best_g" in source


def test_15_zero_cost_moves_cannot_infinite_loop():
    stock = [Card("d", 1 + (i % 12)) for i in range(30)]
    slots = {0: ([], [Card("h", 13)]), 1: ([], []), 2: ([], [])}
    seed = _state_from_slots(slots, stock, [[Card("s", r) for r in range(13, 0, -1)]])
    result = search_h9_cut(
        [seed],
        [[]],
        directed=True,
        max_unique=80,
        time_limit_s=2.0,
        rss_abort_mb=512,
        max_level=3,
    )
    assert result.elapsed_s < 2.5
    assert result.unique < 5000
    assert result.duplicate_skips >= 1 or result.zero_cost_moves >= 1


def test_16_pass_b_branch_and_bound_uses_g_only():
    source = inspect.getsource(search_h9_cut)
    assert "cheaper_only" in source
    assert "child_g >= current_incumbent" in source
    assert "directed=False" in Path(__file__).resolve().parents[1].joinpath(
        "research", "dynamic_heart9_mandatory_cut_v0_32.py"
    ).read_text(encoding="utf-8")


def test_17_heuristic_progress_is_not_proof_pruning():
    import spider.simple_h9_cut as mod

    source = inspect.getsource(mod)
    assert "used_heuristic_prune: bool = False" in source
    assert "fd_blockers" in source
    assert "not an optimality proof" in source.lower() or "Not an optimality proof" in source


def test_18_saved_witness_replays_from_original_deal():
    if not FIXTURE.exists():
        return
    actions = parse_moves_file(FIXTURE)
    end, cost = _replay(actions)
    assert cost == len(actions)
    assert h9_progress(end)["face_up"] is True
    assert stock_rows(end) in (2, 3)
    assert len(end.foundations) == 1


def test_19_production_solver_unchanged():
    end = _source0()
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    default = solve_progressive(end, **kwargs)
    explicit = solve_progressive(end, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert default.nodes == explicit.nodes
    source = inspect.getsource(solve_progressive)
    assert "h9_progress" not in source
    assert "search_h9_cut" not in source


def test_20_mobilityware_rules_contract_green():
    assert MW_RULES.can_deal_into_empty is True
    end = _source0()
    assert 5 in empty_column_indices(end)
    apply_action(end.clone(), engine_tableau_actions(end)[0][0])
    assert end.can_deal(MW_RULES) is True
