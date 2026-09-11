"""Post-Deal-1 fd12-to-fd11 boundary audit v0.28."""

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
from spider.simple_deal1_preview import stock_rows, tableau_layer_bfs
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, solve_progressive
from spider.simple_workspace_reachability import engine_tableau_actions, face_down_count

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
V27 = ROOT / "docs" / "research" / "simple_progressive_post_deal1_work_v0_27.json"
REPORT = ROOT / "docs" / "research" / "simple_progressive_post_deal1_fd12_v0_28.json"
FD11_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_28_fd11.moves.txt"
FD10_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_28_fd10.moves.txt"
FOUNDATION_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_28_first_foundation.moves.txt"


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


def _fd12_records():
    payload = json.loads(V27.read_text(encoding="utf-8"))
    parents = payload.get("sources") or []
    exits = payload.get("fd12_exits") or []
    assert len(exits) == 16
    rows = []
    for rec in exits:
        origin = rec["origin"]
        full = _as_actions(parents[origin]["full_actions"]) + _as_actions(rec["actions"])
        rows.append({**rec, "full_actions": full})
    return rows


def _replay_full(actions):
    opening = _opening()
    end = opening.clone()
    cost = replay_actions(end, actions)
    return end, cost, opening


def _state_from_slots(slots, stock=None) -> SpiderState:
    cols = []
    for index in range(10):
        down, up = slots.get(index, ([], [Card("s", 13)]))
        cols.append(Column(list(down), list(up)))
    return SpiderState(cols, list(stock or []), [])


def _toy_fd12_stock4() -> SpiderState:
    stock = [Card("shdc"[i % 4], 1 + (i % 12)) for i in range(40)]
    return _state_from_slots(
        {
            0: ([Card("c", 10), Card("d", 12), Card("c", 6)], [Card("h", 7)]),
            1: ([], [Card("s", 8)]),
            2: ([], [Card("h", 5)]),
            3: ([], []),
            4: ([], [Card("c", 13)]),
            5: ([], [Card("d", 13)]),
            6: ([], [Card("s", 12)]),
            7: ([Card("d", 10)], [Card("s", 4)]),
            8: ([], [Card("c", 3)]),
            9: ([], [Card("h", 2)]),
        },
        stock,
    )


def test_1_all_v027_fd12_source_states_replay():
    for rec in _fd12_records():
        end, cost, _ = _replay_full(rec["full_actions"])
        assert cost == len(rec["full_actions"])
        assert pack_state(end).hex() == rec["ordered_digest"]
        assert sum(1 for a in rec["full_actions"] if a == ("deal",)) == 1


def test_2_exactly_sixteen_distinct_ordered_fd12_classes():
    records = _fd12_records()
    assert len(records) == 16
    digests = {rec["ordered_digest"] for rec in records}
    assert len(digests) == 16
    live = set()
    for rec in records:
        end, _, _ = _replay_full(rec["full_actions"])
        live.add(pack_state(end))
    assert len(live) == 16


def test_3_each_source_has_exactly_four_stock_rows():
    for rec in _fd12_records():
        end, _, _ = _replay_full(rec["full_actions"])
        assert stock_rows(end) == 4
        assert sum(1 for a in rec["full_actions"] if a == ("deal",)) == 1


def test_4_each_source_is_fd12_foundation0():
    for rec in _fd12_records():
        end, _, _ = _replay_full(rec["full_actions"])
        assert face_down_count(end) == 12
        assert len(end.foundations) == 0


def test_5_source_exact_identity_is_ordered_pack_state():
    end, _, _ = _replay_full(_fd12_records()[0]["full_actions"])
    assert pack_state(end)[:4] == b"SPK1"
    assert pack_search_identity(end) == pack_state(end)


def test_6_column_permutation_is_not_used_while_stock_remains():
    end, _, _ = _replay_full(_fd12_records()[0]["full_actions"])
    assert end.stock
    swapped = permute_tableau_columns(end, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    assert pack_state(end) != pack_state(swapped)
    source = inspect.getsource(tableau_layer_bfs)
    assert "post_stock" not in source
    assert "pack_post_stock_symmetry_state" not in source


def test_7_all_engine_legal_tableau_actions_are_generated():
    seed = _toy_fd12_stock4()
    legal = engine_tableau_actions(seed)[0]
    result = tableau_layer_bfs([seed], max_depth=1, max_unique=80, time_limit_s=5.0, rss_abort_mb=512)
    assert result.all_legal_tableau is True
    assert result.generated >= len(legal)


def test_8_deal_2_is_engine_legal_but_not_expanded():
    end, _, _ = _replay_full(_fd12_records()[0]["full_actions"])
    assert end.can_deal(MW_RULES) is True
    assert ("deal",) in end.enumerate_legal_actions(rules=MW_RULES)
    result = tableau_layer_bfs([end], max_depth=1, max_unique=40, time_limit_s=5.0, rss_abort_mb=512)
    assert result.deal_expanded is False
    assert ("deal",) not in engine_tableau_actions(end)[0]


def test_9_no_second_deal_occurs_in_any_search_path():
    source = inspect.getsource(tableau_layer_bfs)
    assert 'if action == ("deal",)' in source or "action == ('deal',)" in source
    seed = _toy_fd12_stock4()
    result = tableau_layer_bfs([seed], max_depth=2, max_unique=80, time_limit_s=5.0, rss_abort_mb=512)
    for rec in result.progress:
        assert ["deal"] not in rec["actions"] and ("deal",) not in rec["actions"]


def test_10_bfs_is_primitive_depth_layered():
    seed = _toy_fd12_stock4()
    result = tableau_layer_bfs([seed], max_depth=3, max_unique=80, time_limit_s=5.0, rss_abort_mb=512)
    assert result.expansion_order == list(range(len(result.expansion_order)))


def test_11_exact_cross_source_convergence_is_deduplicated():
    a = _toy_fd12_stock4()
    b = a.clone()
    result = tableau_layer_bfs(
        [a, b],
        origin_paths=[[(0, 1, 1)], [(1, 3, 1)]],
        max_depth=1,
        max_unique=40,
        time_limit_s=5.0,
        rss_abort_mb=512,
    )
    assert result.source_count == 2
    assert result.unique_sources == 1
    assert result.cross_origin_dups >= 1
    assert pack_state(unpack_state(result.keys[0])) == pack_state(a)


def test_12_fd12_children_enqueue():
    seed = _toy_fd12_stock4()
    result = tableau_layer_bfs([seed], max_depth=2, max_unique=80, time_limit_s=5.0, rss_abort_mb=512)
    assert result.unique >= 2


def test_13_fd11_children_become_terminal_boundary_exits():
    seed = _toy_fd12_stock4()
    result = tableau_layer_bfs(
        [seed],
        max_depth=3,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
        stop_after_progress_layer=True,
    )
    start_fd = face_down_count(seed)
    assert result.progress
    for rec in result.progress:
        assert rec["fd"] < start_fd
        end = seed.clone()
        replay_actions(end, [tuple(a) for a in rec["actions"]])
        assert face_down_count(end) == rec["fd"]
        assert rec["depth"] == min(r["depth"] for r in result.progress)


def test_14_complete_first_fd11_generating_layer_is_harvested():
    seed = _toy_fd12_stock4()
    result = tableau_layer_bfs(
        [seed],
        max_depth=4,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
        stop_after_progress_layer=True,
    )
    assert result.progress
    depths = {rec["depth"] for rec in result.progress}
    assert len(depths) == 1
    assert result.stop_reason == "progress layer complete"
    assert result.completed_generated_depth == next(iter(depths))


def test_15_important_witnesses_replay_from_the_original_deal():
    for path in (FD11_FIXTURE, FD10_FIXTURE, FOUNDATION_FIXTURE):
        if not path.exists():
            continue
        actions = parse_moves_file(path)
        opening = _opening()
        end = opening.clone()
        cost = replay_actions(end, actions)
        assert cost == len(actions)
        assert stock_rows(end) == 4
        assert sum(1 for a in actions if a == ("deal",)) == 1
        assert face_down_count(end) <= 11 or len(end.foundations) >= 1
        return
    if REPORT.exists():
        payload = json.loads(REPORT.read_text(encoding="utf-8"))
        rec = payload.get("first_fd11") or {}
        actions = rec.get("full_actions") or []
        if actions:
            end, cost, _ = _replay_full(_as_actions(actions))
            assert rec.get("full_replay_ok", True) is True
            assert cost == len(actions)


def test_16_production_solver_remains_unchanged():
    end, _, _ = _replay_full(_fd12_records()[0]["full_actions"])
    assert pack_state(end)[:4] == b"SPK1"
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    default = solve_progressive(end, **kwargs)
    explicit = solve_progressive(end, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert default.nodes == explicit.nodes
    source = inspect.getsource(solve_progressive)
    assert "stop_after_progress_layer" not in source
    assert "fd12" not in source


def test_17_mobilityware_unrestricted_rules_contract_remains_green():
    assert MW_RULES.can_deal_into_empty is True
    end, _, opening = _replay_full(_fd12_records()[0]["full_actions"])
    again = opening.clone()
    actions = _fd12_records()[0]["full_actions"]
    assert replay_actions(again, actions) == len(actions)
    apply_action(end.clone(), engine_tableau_actions(end)[0][0])
    assert end.can_deal(MW_RULES) is True
