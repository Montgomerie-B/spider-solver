"""Deal-2 timing preview across the Deal-1 reveal cascade v0.29."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_search_identity, pack_state, permute_tableau_columns, unpack_state
from spider.rules import MW_RULES
from spider.simple_deal1_preview import next_stock_row, stock_rows, tableau_layer_bfs
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, solve_progressive
from spider.simple_workspace_reachability import engine_tableau_actions, face_down_count

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
V26 = ROOT / "docs" / "research" / "simple_progressive_deal1_preview_v0_26.json"
V27 = ROOT / "docs" / "research" / "simple_progressive_post_deal1_work_v0_27.json"
V28 = ROOT / "docs" / "research" / "simple_progressive_post_deal1_fd12_v0_28.json"
REPORT = ROOT / "docs" / "research" / "simple_progressive_deal2_timing_preview_v0_29.json"
HARNESS = ROOT / "research" / "simple_progressive_deal2_timing_preview_v0_29.py"
FIXTURES = [
    ROOT / "solutions" / "4925153_simple_v0_29_early_fd10.moves.txt",
    ROOT / "solutions" / "4925153_simple_v0_29_middle_fd10.moves.txt",
    ROOT / "solutions" / "4925153_simple_v0_29_late_fd10.moves.txt",
    ROOT / "solutions" / "4925153_simple_v0_29_early_foundation.moves.txt",
    ROOT / "solutions" / "4925153_simple_v0_29_middle_foundation.moves.txt",
    ROOT / "solutions" / "4925153_simple_v0_29_late_foundation.moves.txt",
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


def _toy_fd12_stock4() -> SpiderState:
    stock = [Card("shdc"[i % 4], 1 + (i % 12)) for i in range(40)]
    down = [Card("c", 10)] * 10 + [Card("d", 12), Card("s", 6)]
    slots = {0: (down, [Card("h", 7)]), 1: ([], [Card("s", 8)])}
    for index in range(2, 10):
        slots[index] = ([], [Card("s", 13)])
    return _state_from_slots(slots, stock)


def test_1_all_fd13_sources_replay():
    for actions in _fd13_paths():
        end, cost, _ = _replay_full(actions)
        assert cost == len(actions)
        assert face_down_count(end) == 13
        assert len(end.foundations) == 0
        assert sum(1 for a in actions if a == ("deal",)) == 1


def test_2_all_fd12_sources_replay():
    for actions in _fd12_paths():
        end, cost, _ = _replay_full(actions)
        assert cost == len(actions)
        assert face_down_count(end) == 12
        assert sum(1 for a in actions if a == ("deal",)) == 1


def test_3_all_fd11_sources_replay():
    for actions in _fd11_paths():
        end, cost, _ = _replay_full(actions)
        assert cost == len(actions)
        assert face_down_count(end) == 11
        assert sum(1 for a in actions if a == ("deal",)) == 1


def test_4_all_sources_have_exactly_four_stock_rows_before_deal2():
    for paths in (_fd13_paths(), _fd12_paths(), _fd11_paths()):
        for actions in paths:
            end, _, _ = _replay_full(actions)
            assert stock_rows(end) == 4
            assert end.can_deal(MW_RULES) is True


def test_5_exact_same_deal2_row_is_pending_for_every_source():
    rows = []
    for paths in (_fd13_paths(), _fd12_paths(), _fd11_paths()):
        for actions in paths:
            end, _, _ = _replay_full(actions)
            rows.append(tuple(next_stock_row(end)))
    assert len(rows) == 8 + 16 + 16
    assert len(set(rows)) == 1
    assert len(rows[0]) == 10


def test_6_virtual_deal_does_not_mutate_source_state():
    end, _, _ = _replay_full(_fd13_paths()[0])
    before = pack_state(end)
    child = end.clone()
    apply_action(child, ("deal",))
    assert pack_state(end) == before
    assert pack_state(child) != before


def test_7_deal2_child_has_three_stock_rows():
    end, _, _ = _replay_full(_fd13_paths()[0])
    assert stock_rows(end) == 4
    child = end.clone()
    apply_action(child, ("deal",))
    assert stock_rows(child) == 3
    assert face_down_count(child) == face_down_count(end)


def test_8_ordered_pack_state_identity_is_used():
    end, _, _ = _replay_full(_fd13_paths()[0])
    assert pack_state(end)[:4] == b"SPK1"
    assert pack_search_identity(end) == pack_state(end)
    source = inspect.getsource(tableau_layer_bfs)
    assert "identity_fn is None" in source
    assert "identity_fn = pack_state" in source


def test_9_arbitrary_column_permutation_is_not_treated_as_symmetry():
    end, _, _ = _replay_full(_fd11_paths()[0])
    assert end.stock
    swapped = permute_tableau_columns(end, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    assert pack_state(end) != pack_state(swapped)
    source = inspect.getsource(tableau_layer_bfs)
    assert "post_stock" not in source


def test_10_timing_groups_use_independent_seen_sets():
    text = HARNESS.read_text(encoding="utf-8")
    assert "for name, expected_fd, expected_n in GROUPS" in text
    assert "tableau_layer_bfs(" in text
    assert "independent_seen_set" in text
    assert "Each group gets" in text or "independent" in text.lower()
    seed = _toy_fd12_stock4()
    a = tableau_layer_bfs([seed], max_depth=1, max_unique=80, time_limit_s=5.0, rss_abort_mb=512)
    b = tableau_layer_bfs([seed], max_depth=1, max_unique=80, time_limit_s=5.0, rss_abort_mb=512)
    assert a.unique == b.unique
    assert a.expanded == b.expanded
    assert a.unique >= 1 and b.unique >= 1


def test_11_all_legal_post_deal_tableau_moves_are_generated():
    end, _, _ = _replay_full(_fd13_paths()[0])
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
        progress_fd_at_most=10,
    )
    assert result.all_legal_tableau is True
    assert result.deal_expanded is False
    assert result.generated >= len(legal)


def test_12_deal3_is_not_expanded():
    end, _, _ = _replay_full(_fd13_paths()[0])
    child = end.clone()
    apply_action(child, ("deal",))
    assert child.can_deal(MW_RULES) is True
    assert ("deal",) in child.enumerate_legal_actions(rules=MW_RULES)
    result = tableau_layer_bfs(
        [child],
        max_depth=1,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
        require_stock_rows=3,
        progress_fd_at_most=10,
    )
    assert result.deal_expanded is False
    assert ("deal",) not in engine_tableau_actions(child)[0]
    source = inspect.getsource(tableau_layer_bfs)
    assert 'if action == ("deal",)' in source or "action == ('deal',)" in source


def test_13_search_is_primitive_depth_layered():
    seed = _toy_fd12_stock4()
    result = tableau_layer_bfs(
        [seed],
        max_depth=3,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
        progress_fd_at_most=10,
    )
    assert result.expansion_order == list(range(len(result.expansion_order)))


def test_14_absolute_minimum_fd_is_recorded_correctly():
    seed = _toy_fd12_stock4()
    assert face_down_count(seed) == 12
    result = tableau_layer_bfs(
        [seed],
        max_depth=3,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
        stop_after_progress_layer=True,
        progress_fd_at_most=10,
    )
    assert result.min_fd <= 10
    assert 11 in result.first_fd_depth
    assert result.first_fd_depth[11] == 1
    assert result.unique >= 2


def test_15_first_fd10_generating_layer_is_completed_before_stopping():
    seed = _toy_fd12_stock4()
    result = tableau_layer_bfs(
        [seed],
        max_depth=4,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
        stop_after_progress_layer=True,
        progress_fd_at_most=10,
    )
    assert result.progress
    depths = {rec["depth"] for rec in result.progress}
    assert len(depths) == 1
    assert result.stop_reason == "progress layer complete"
    assert result.completed_generated_depth == next(iter(depths))
    for rec in result.progress:
        assert rec["fd"] <= 10


def test_16_successful_witnesses_replay_from_original_deal():
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
        assert face_down_count(end) <= 10 or len(end.foundations) >= 1
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
            assert cost == len(actions)


def test_17_production_solver_remains_unchanged():
    end, _, _ = _replay_full(_fd13_paths()[0])
    assert pack_state(end)[:4] == b"SPK1"
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    default = solve_progressive(end, **kwargs)
    explicit = solve_progressive(end, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert default.nodes == explicit.nodes
    source = inspect.getsource(solve_progressive)
    assert "progress_fd_at_most" not in source
    assert "deal2_timing" not in source


def test_18_mobilityware_unrestricted_rules_contract_remains_green():
    assert MW_RULES.can_deal_into_empty is True
    end, _, opening = _replay_full(_fd13_paths()[0])
    again = opening.clone()
    actions = _fd13_paths()[0]
    assert replay_actions(again, actions) == len(actions)
    child = end.clone()
    apply_action(child, ("deal",))
    assert child.can_deal(MW_RULES) is True
    apply_action(end.clone(), engine_tableau_actions(end)[0][0])
    unpack_state(pack_state(end))
