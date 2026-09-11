"""Foundation material horizons and first-foundation Deal-2 audit v0.30."""

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
from spider.simple_deal1_preview import next_stock_row, stock_rows, tableau_layer_bfs
from spider.simple_foundation_horizon import (
    EXPECTED_FIRST,
    EXPECTED_MAX_BY_HORIZON,
    EXPECTED_SD5,
    EXPECTED_SECOND,
    material_horizon_audit,
)
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, solve_progressive
from spider.simple_workspace_reachability import engine_tableau_actions, face_down_count

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
V26 = ROOT / "docs" / "research" / "simple_progressive_deal1_preview_v0_26.json"
V27 = ROOT / "docs" / "research" / "simple_progressive_post_deal1_work_v0_27.json"
V28 = ROOT / "docs" / "research" / "simple_progressive_post_deal1_fd12_v0_28.json"
REPORT = ROOT / "docs" / "research" / "simple_progressive_foundation_horizon_v0_30.json"
HARNESS = ROOT / "research" / "simple_progressive_foundation_horizon_v0_30.py"
FIXTURES = [
    ROOT / "solutions" / "4925153_simple_v0_30_early_first_foundation.moves.txt",
    ROOT / "solutions" / "4925153_simple_v0_30_middle_first_foundation.moves.txt",
    ROOT / "solutions" / "4925153_simple_v0_30_late_first_foundation.moves.txt",
]


def _opening() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL)))


def _as_actions(raw):
    out = []
    for item in raw:
        if item == "deal" or item == ["deal"] or item == ("deal",):
            out.append(("deal",))
        else:
            src, dst, k = item
            out.append((int(src), int(dst), int(k)))
    return out


def _replay_full(actions):
    opening = _opening()
    end = opening.clone()
    cost = replay_actions(end, actions)
    return end, cost, opening


def _fd13_paths():
    payload = json.loads(V26.read_text(encoding="utf-8"))
    rows = payload.get("prepared_deal_progress") or []
    assert len(rows) == 8
    return [_as_actions(rec["full_actions"]) for rec in rows]


def _fd12_paths():
    payload = json.loads(V27.read_text(encoding="utf-8"))
    parents = payload.get("sources") or []
    exits = payload.get("fd12_exits") or []
    assert len(exits) == 16
    return [
        _as_actions(parents[rec["origin"]]["full_actions"]) + _as_actions(rec["actions"])
        for rec in exits
    ]


def _fd11_paths():
    payload = json.loads(V28.read_text(encoding="utf-8"))
    exits = payload.get("fd11_exits") or []
    assert len(exits) == 16
    return [_as_actions(rec["full_actions"]) for rec in exits]


def _state_from_slots(slots, stock=None) -> SpiderState:
    cols = []
    for index in range(10):
        down, up = slots.get(index, ([], [Card("s", 13)]))
        cols.append(Column(list(down), list(up)))
    return SpiderState(cols, list(stock or []), [])


def _toy_reveal_stock3() -> SpiderState:
    stock = [Card("shdc"[i % 4], 1 + (i % 12)) for i in range(30)]
    slots = {0: ([Card("c", 10)], [Card("h", 7)]), 1: ([], [Card("s", 8)])}
    for index in range(2, 10):
        slots[index] = ([], [Card("h", 13)])
    return _state_from_slots(slots, stock)


def _toy_spade_foundation_stock3() -> SpiderState:
    stock = [Card("h", 1 + (i % 12)) for i in range(30)]
    run = [Card("s", rank) for rank in range(13, 1, -1)]
    slots = {0: ([], run), 1: ([], [Card("s", 1)])}
    for index in range(2, 10):
        slots[index] = ([], [Card("h", 13)])
    return _state_from_slots(slots, stock)


def test_1_material_horizons_match_expected_4925153_map():
    audit = material_horizon_audit(_opening())
    assert audit["expected_ok"] is True
    for suit, first in EXPECTED_FIRST.items():
        assert audit["suits"][suit]["first_horizon"] == first
    for suit, second in EXPECTED_SECOND.items():
        assert audit["suits"][suit]["second_horizon"] == second


def test_2_final_stock_row_is_the_engine_sd5_row():
    audit = material_horizon_audit(_opening())
    assert audit["sd5"] == EXPECTED_SD5
    opening = _opening()
    stock = list(opening.stock)
    for _ in range(4):
        stock = stock[:-10]
    assert audit["stock_rows"][4] == EXPECTED_SD5
    assert len(stock) == 10


def test_3_foundations_impossible_before_sd5():
    audit = material_horizon_audit(_opening())
    assert "first Clubs" in audit["impossible_before_sd5"]
    assert "second Spades" in audit["impossible_before_sd5"]
    assert "second Hearts" in audit["impossible_before_sd5"]
    assert "second Diamonds" in audit["impossible_before_sd5"]
    assert "second Clubs" in audit["impossible_before_sd5"]
    assert "first Spades" not in audit["impossible_before_sd5"]
    assert "first Hearts" not in audit["impossible_before_sd5"]
    assert "first Diamonds" not in audit["impossible_before_sd5"]


def test_4_maximum_material_foundation_count_by_horizon():
    audit = material_horizon_audit(_opening())
    assert audit["max_foundations_by_horizon"] == EXPECTED_MAX_BY_HORIZON


def test_5_all_three_deal2_source_groups_replay():
    for actions, fd in [(_fd13_paths()[0], 13), (_fd12_paths()[0], 12), (_fd11_paths()[0], 11)]:
        end, cost, _ = _replay_full(actions)
        assert cost == len(actions)
        assert face_down_count(end) == fd
        assert len(end.foundations) == 0
        assert sum(1 for a in actions if a == ("deal",)) == 1
    assert len(_fd13_paths()) == 8
    assert len(_fd12_paths()) == 16
    assert len(_fd11_paths()) == 16


def test_6_sources_have_four_stock_rows_and_same_deal2_row():
    rows = []
    for paths in (_fd13_paths(), _fd12_paths(), _fd11_paths()):
        for actions in paths:
            end, _, _ = _replay_full(actions)
            assert stock_rows(end) == 4
            rows.append(tuple(next_stock_row(end)))
    assert len(set(rows)) == 1


def test_7_virtual_deal2_does_not_mutate_and_leaves_three_stock_rows():
    end, _, _ = _replay_full(_fd11_paths()[0])
    before = pack_state(end)
    child = end.clone()
    apply_action(child, ("deal",))
    assert pack_state(end) == before
    assert stock_rows(child) == 3
    assert len(child.foundations) == 0
    assert sum(1 for a in _fd11_paths()[0] if a == ("deal",)) + 1 == 2


def test_8_ordered_pack_state_identity_is_used():
    end, _, _ = _replay_full(_fd11_paths()[0])
    assert pack_state(end)[:4] == b"SPK1"
    assert pack_search_identity(end) == pack_state(end)
    swapped = permute_tableau_columns(end, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    assert pack_state(end) != pack_state(swapped)
    source = inspect.getsource(tableau_layer_bfs)
    assert "post_stock" not in source


def test_9_timing_groups_use_independent_seen_sets():
    text = HARNESS.read_text(encoding="utf-8")
    assert "for name, expected_fd, expected_n in GROUPS" in text
    assert "tableau_layer_bfs(" in text
    assert "independent_seen_set" in text
    seed = _toy_reveal_stock3()
    a = tableau_layer_bfs([seed], max_depth=1, max_unique=40, time_limit_s=5.0, rss_abort_mb=512)
    b = tableau_layer_bfs([seed], max_depth=1, max_unique=40, time_limit_s=5.0, rss_abort_mb=512)
    assert a.unique == b.unique >= 1


def test_10_all_legal_tableau_moves_are_generated_and_deal3_is_not_expanded():
    end, _, _ = _replay_full(_fd11_paths()[0])
    child = end.clone()
    apply_action(child, ("deal",))
    legal = engine_tableau_actions(child)[0]
    result = tableau_layer_bfs(
        [child],
        max_depth=1,
        max_unique=200,
        time_limit_s=5.0,
        rss_abort_mb=512,
        require_stock_rows=3,
        progress_foundations_at_least=1,
    )
    assert result.all_legal_tableau is True
    assert result.deal_expanded is False
    assert result.generated >= len(legal)
    assert child.can_deal(MW_RULES) is True
    assert ("deal",) in child.enumerate_legal_actions(rules=MW_RULES)
    assert ("deal",) not in legal


def test_11_search_is_primitive_depth_layered():
    seed = _toy_reveal_stock3()
    result = tableau_layer_bfs(
        [seed],
        max_depth=3,
        max_unique=40,
        time_limit_s=5.0,
        rss_abort_mb=512,
        progress_foundations_at_least=1,
    )
    assert result.expansion_order == list(range(len(result.expansion_order)))


def test_12_fd_reduction_is_telemetry_not_the_stop_target():
    seed = _toy_reveal_stock3()
    start_fd = face_down_count(seed)
    result = tableau_layer_bfs(
        [seed],
        max_depth=3,
        max_unique=40,
        time_limit_s=5.0,
        rss_abort_mb=512,
        stop_after_progress_layer=True,
        progress_foundations_at_least=1,
    )
    assert result.min_fd < start_fd
    assert result.progress == []
    assert result.stop_reason != "progress layer complete"
    assert result.unique >= 2


def test_13_first_foundation_generating_layer_is_completed():
    seed = _toy_spade_foundation_stock3()
    result = tableau_layer_bfs(
        [seed],
        max_depth=3,
        max_unique=40,
        time_limit_s=5.0,
        rss_abort_mb=512,
        stop_after_progress_layer=True,
        progress_foundations_at_least=1,
    )
    assert result.progress
    assert result.max_foundations >= 1
    depths = {rec["depth"] for rec in result.progress}
    assert len(depths) == 1
    assert result.stop_reason == "progress layer complete"
    for rec in result.progress:
        assert rec["foundations"] >= 1
        assert "s" in rec.get("foundation_suits", [])


def test_14_successful_witnesses_replay_from_the_original_deal():
    found = False
    for path in FIXTURES:
        if not path.exists():
            continue
        found = True
        actions = parse_moves_file(path)
        end, cost, _ = _replay_full(actions)
        assert cost == len(actions)
        assert sum(1 for a in actions if a == ("deal",)) == 2
        assert stock_rows(end) == 3
        assert len(end.foundations) >= 1
        assert end.foundations[0][0].suit in "sh"
    if found:
        return
    if REPORT.exists():
        payload = json.loads(REPORT.read_text(encoding="utf-8"))
        for group in (payload.get("groups") or {}).values():
            rec = group.get("first_witness") or {}
            actions = rec.get("full_actions") or []
            if not actions:
                continue
            end, cost, _ = _replay_full(_as_actions(actions))
            assert rec.get("full_replay_ok", True) is True
            assert len(end.foundations) >= 1


def test_15_production_solver_remains_unchanged():
    end, _, _ = _replay_full(_fd13_paths()[0])
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    default = solve_progressive(end, **kwargs)
    explicit = solve_progressive(end, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert default.nodes == explicit.nodes
    source = inspect.getsource(solve_progressive)
    assert "progress_foundations_at_least" not in source
    assert "foundation_horizon" not in source


def test_16_mobilityware_unrestricted_rules_contract_remains_green():
    assert MW_RULES.can_deal_into_empty is True
    end, _, opening = _replay_full(_fd13_paths()[0])
    again = opening.clone()
    actions = _fd13_paths()[0]
    assert replay_actions(again, actions) == len(actions)
    child = end.clone()
    apply_action(child, ("deal",))
    assert child.can_deal(MW_RULES) is True
    apply_action(end.clone(), engine_tableau_actions(end)[0][0])
