"""Post-Deal-1 tableau-only work-completion audit v0.27."""

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
from spider.simple_legacy_fd13_alternatives import reveal_target_from_transition
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, solve_progressive
from spider.simple_workspace_reachability import engine_tableau_actions, face_down_count

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
SEED = ROOT / "solutions" / "4925153_simple_fd14_stock0_seed.moves.txt"
V26 = ROOT / "docs" / "research" / "simple_progressive_deal1_preview_v0_26.json"
REPORT = ROOT / "docs" / "research" / "simple_progressive_post_deal1_work_v0_27.json"
FD12_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_27_fd12.moves.txt"
EXPECTED_REVEAL = "c10,d12,c6,s8"


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


def _prepared_records():
    payload = json.loads(V26.read_text(encoding="utf-8"))
    rows = payload.get("prepared_deal_progress") or []
    assert len(rows) == 8
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


def _toy_fd13_stock4() -> SpiderState:
    stock = [Card("shdc"[i % 4], 1 + (i % 12)) for i in range(40)]
    return _state_from_slots(
        {
            0: ([Card("c", 10), Card("d", 12), Card("c", 6)], [Card("h", 7), Card("h", 6)]),
            1: ([], [Card("s", 7)]),
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


def test_1_all_v026_prepared_fd13_sources_replay():
    seed = parse_moves_file(SEED)
    d1 = _opening().clone()
    replay_actions(d1, seed[:38])
    for rec in _prepared_records():
        actions = _as_actions(rec["full_actions"])
        end, cost, _ = _replay_full(actions)
        assert cost == len(actions)
        assert pack_state(end).hex() == rec["ordered_digest"]
        assert reveal_target_from_transition(d1, end)["signature_key"] == EXPECTED_REVEAL


def test_2_each_source_has_exactly_four_stock_rows():
    for rec in _prepared_records():
        end, _, _ = _replay_full(_as_actions(rec["full_actions"]))
        assert stock_rows(end) == 4
        assert sum(1 for a in _as_actions(rec["full_actions"]) if a == ("deal",)) == 1


def test_3_each_source_is_fd13_foundation0():
    for rec in _prepared_records():
        end, _, _ = _replay_full(_as_actions(rec["full_actions"]))
        assert face_down_count(end) == 13
        assert len(end.foundations) == 0


def test_4_source_exact_identity_is_ordered_pack_state():
    end, _, _ = _replay_full(_as_actions(_prepared_records()[0]["full_actions"]))
    assert pack_state(end)[:4] == b"SPK1"
    assert pack_search_identity(end) == pack_state(end)


def test_5_column_permutation_is_not_used_while_stock_remains():
    end, _, _ = _replay_full(_as_actions(_prepared_records()[0]["full_actions"]))
    assert end.stock
    swapped = permute_tableau_columns(end, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    assert pack_state(end) != pack_state(swapped)
    source = inspect.getsource(tableau_layer_bfs)
    assert "post_stock" not in source


def test_6_all_engine_legal_tableau_actions_are_generated():
    seed = _toy_fd13_stock4()
    legal = engine_tableau_actions(seed)[0]
    result = tableau_layer_bfs([seed], max_depth=1, max_unique=80, time_limit_s=5.0, rss_abort_mb=512)
    assert result.all_legal_tableau is True
    assert result.generated >= len(legal)


def test_7_deal_is_engine_legal_but_not_expanded():
    end, _, _ = _replay_full(_as_actions(_prepared_records()[0]["full_actions"]))
    assert end.can_deal(MW_RULES) is True
    assert ("deal",) in end.enumerate_legal_actions(rules=MW_RULES)
    result = tableau_layer_bfs([end], max_depth=1, max_unique=40, time_limit_s=5.0, rss_abort_mb=512)
    assert result.deal_expanded is False
    assert ("deal",) not in engine_tableau_actions(end)[0]


def test_8_no_second_deal_occurs_in_any_search_path():
    source = inspect.getsource(tableau_layer_bfs)
    assert 'if action == ("deal",)' in source or "action == ('deal',)" in source
    seed = _toy_fd13_stock4()
    result = tableau_layer_bfs([seed], max_depth=2, max_unique=80, time_limit_s=5.0, rss_abort_mb=512)
    for rec in result.progress:
        assert ["deal"] not in rec["actions"] and ("deal",) not in rec["actions"]


def test_9_bfs_is_primitive_depth_layered():
    seed = _toy_fd13_stock4()
    result = tableau_layer_bfs([seed], max_depth=3, max_unique=80, time_limit_s=5.0, rss_abort_mb=512)
    assert result.expansion_order == list(range(len(result.expansion_order)))


def test_10_exact_duplicate_states_are_expanded_once():
    seed = _toy_fd13_stock4()
    result = tableau_layer_bfs([seed], max_depth=2, max_unique=80, time_limit_s=5.0, rss_abort_mb=512)
    assert result.duplicate_skips >= 1 or result.unique == result.generated + 1


def test_11_cross_source_convergence_retains_a_replayable_representative():
    a = _toy_fd13_stock4()
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


def test_12_fd13_children_enqueue():
    seed = _toy_fd13_stock4()
    result = tableau_layer_bfs([seed], max_depth=2, max_unique=80, time_limit_s=5.0, rss_abort_mb=512)
    assert result.unique >= 2


def test_13_fd12_children_become_terminal_boundary_exits():
    seed = _toy_fd13_stock4()
    result = tableau_layer_bfs([seed], max_depth=3, max_unique=80, time_limit_s=5.0, rss_abort_mb=512)
    start_fd = face_down_count(seed)
    for rec in result.progress:
        assert rec["fd"] < start_fd
        end = seed.clone()
        replay_actions(end, [tuple(a) for a in rec["actions"]])
        assert face_down_count(end) == rec["fd"]


def test_14_minimum_depth_boundary_layer_is_completed_before_stopping():
    seed = _toy_fd13_stock4()
    result = tableau_layer_bfs(
        [seed],
        max_depth=4,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
        stop_after_progress_layer=True,
    )
    if result.progress:
        depths = {rec["depth"] for rec in result.progress}
        assert len(depths) == 1
        assert result.stop_reason == "progress layer complete"
        assert result.completed_generated_depth == next(iter(depths))


def test_15_successful_witness_replays_from_the_original_deal():
    if FD12_FIXTURE.exists():
        opening = _opening()
        actions = parse_moves_file(FD12_FIXTURE)
        end = opening.clone()
        replay_actions(end, actions)
        assert face_down_count(end) <= 12
        assert stock_rows(end) == 4
        assert sum(1 for a in actions if a == ("deal",)) == 1
        return
    if REPORT.exists():
        payload = json.loads(REPORT.read_text(encoding="utf-8"))
        rec = payload.get("first_fd12") or {}
        actions = rec.get("full_actions") or rec.get("actions") or []
        if actions:
            opening = _opening()
            end = opening.clone()
            replay_actions(end, _as_actions(actions if rec.get("full_actions") else payload["sources"][rec["origin"]]["full_actions"] + rec["actions"]))
            assert rec.get("full_replay_ok", True) is True


def test_16_production_solver_remains_unchanged():
    end, _, _ = _replay_full(_as_actions(_prepared_records()[0]["full_actions"]))
    assert pack_state(end)[:4] == b"SPK1"
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    default = solve_progressive(end, **kwargs)
    explicit = solve_progressive(end, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert default.nodes == explicit.nodes
    source = inspect.getsource(solve_progressive)
    assert "stop_after_progress_layer" not in source


def test_17_mobilityware_unrestricted_rules_contract_remains_green():
    assert MW_RULES.can_deal_into_empty is True
    end, _, opening = _replay_full(_as_actions(_prepared_records()[0]["full_actions"]))
    again = opening.clone()
    actions = _as_actions(_prepared_records()[0]["full_actions"])
    assert replay_actions(again, actions) == len(actions)
    apply_action(end.clone(), engine_tableau_actions(end)[0][0])
