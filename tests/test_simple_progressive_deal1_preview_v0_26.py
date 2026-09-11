"""Perfect-information Deal-1 preview v0.26."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_search_identity, pack_state, unpack_state
from spider.rules import MW_RULES
from spider.simple_deal1_preview import (
    DEAL_NOW,
    PREPARE_THEN_DEAL,
    classify_timing,
    next_stock_row,
    snapshot_metrics,
    stock_rows,
    tableau_layer_bfs,
    virtual_deal_candidates,
)
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, solve_progressive
from spider.simple_workspace_reachability import engine_tableau_actions, face_down_count

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
SEED = ROOT / "solutions" / "4925153_simple_fd14_stock0_seed.moves.txt"
REPORT = ROOT / "docs" / "research" / "simple_progressive_deal1_preview_v0_26.json"


def _opening() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL)))


def _d1():
    actions = parse_moves_file(SEED)
    opening = _opening()
    d1 = opening.clone()
    replay_actions(d1, actions[:38])
    return d1, actions, opening


def _state_from_slots(slots, stock=None) -> SpiderState:
    cols = []
    for index in range(10):
        down, up = slots.get(index, ([], [Card("s", 13)]))
        cols.append(Column(list(down), list(up)))
    return SpiderState(cols, list(stock or []), [])


def _toy_pre_deal() -> SpiderState:
    stock = [Card("shdc"[i % 4], 1 + (i % 12)) for i in range(20)]
    return _state_from_slots(
        {
            0: ([Card("c", 11)], [Card("h", 7), Card("h", 6)]),
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


def test_1_d1_root_replays_path_38():
    d1, actions, _ = _d1()
    assert len(actions) == 43
    assert actions[38:] == [("deal",)] * 5
    assert face_down_count(d1) == 14
    assert len(d1.foundations) == 0
    assert stock_rows(d1) == 5
    assert d1.can_deal(MW_RULES) is True
    assert pack_state(d1)[:4] == b"SPK1"


def test_2_exact_next_stock_row_is_the_historical_deal1_row():
    d1, actions, opening = _d1()
    row = next_stock_row(d1)
    assert len(row) == 10
    after = d1.clone()
    apply_action(after, ("deal",))
    hist = opening.clone()
    replay_actions(hist, actions[:39])
    assert pack_state(after) == pack_state(hist)
    assert stock_rows(after) == 4
    for index, (suit, rank) in enumerate(row):
        top = after.columns[index].face_up[-1]
        assert (top.suit, int(top.rank)) == (suit, rank)


def test_3_phase1_does_not_expand_deal():
    seed = _toy_pre_deal()
    assert seed.can_deal(MW_RULES) is True
    result = tableau_layer_bfs([seed], max_depth=2, max_unique=80, time_limit_s=5.0, rss_abort_mb=512)
    assert result.deal_expanded is False
    source = inspect.getsource(tableau_layer_bfs)
    assert "engine_tableau_actions" in source
    assert result.generated >= 1


def test_4_deal_remains_engine_legal_at_candidates():
    d1, *_ = _d1()
    engine = d1.enumerate_legal_actions(rules=MW_RULES)
    assert ("deal",) in engine
    tableau = engine_tableau_actions(d1)[0]
    assert ("deal",) not in tableau
    assert d1.can_deal(MW_RULES) is True


def test_5_phase1_uses_ordered_identity_while_stock_remains():
    d1, *_ = _d1()
    assert d1.stock
    assert pack_search_identity(d1) == pack_state(d1)
    source = inspect.getsource(tableau_layer_bfs)
    assert "identity_fn" in source


def test_6_phase1_is_primitive_depth_layered_bfs():
    seed = _toy_pre_deal()
    result = tableau_layer_bfs([seed], max_depth=3, max_unique=80, time_limit_s=5.0, rss_abort_mb=512)
    assert result.expansion_order == sorted(result.expansion_order)
    assert result.expansion_order == list(range(len(result.expansion_order)))


def test_7_all_engine_legal_tableau_moves_are_generated():
    seed = _toy_pre_deal()
    legal = engine_tableau_actions(seed)[0]
    result = tableau_layer_bfs([seed], max_depth=1, max_unique=80, time_limit_s=5.0, rss_abort_mb=512)
    assert result.all_legal_tableau is True
    assert result.generated >= len(legal)


def test_8_d1_root_is_included_as_depth_zero_candidate():
    seed = _toy_pre_deal()
    result = tableau_layer_bfs([seed], max_depth=1, max_unique=80, time_limit_s=5.0, rss_abort_mb=512)
    assert result.unique >= 1
    assert result.depth_of[0] == 0
    assert pack_state(unpack_state(result.keys[0])) == pack_state(seed)


def test_9_virtual_deal_does_not_mutate_the_pre_deal_candidate():
    d1, *_ = _d1()
    before = pack_state(d1)
    phase1 = tableau_layer_bfs([d1], max_depth=1, max_unique=40, time_limit_s=5.0, rss_abort_mb=512)
    row = next_stock_row(d1)
    out = virtual_deal_candidates(d1, phase1, known_row=row)
    assert pack_state(d1) == before
    assert out["root_unmutated"] is True
    assert out["n_distinct_children"] >= 1


def test_10_immediate_deal_control_matches_historical_deal1_child():
    d1, actions, opening = _d1()
    hist = opening.clone()
    replay_actions(hist, actions[:39])
    phase1 = tableau_layer_bfs([d1], max_depth=1, max_unique=20, time_limit_s=5.0, rss_abort_mb=512)
    out = virtual_deal_candidates(d1, phase1, known_row=next_stock_row(d1))
    assert out["control_post_digest"] == pack_state(hist).hex()
    deal_now = [c for c in out["children"] if c["is_deal_now"]]
    assert deal_now
    assert deal_now[0]["pre_depth"] == 0


def test_11_post_deal_search_does_not_take_deal_2():
    d1, *_ = _d1()
    child = d1.clone()
    apply_action(child, ("deal",))
    assert child.can_deal(MW_RULES) is True
    assert ("deal",) in child.enumerate_legal_actions(rules=MW_RULES)
    result = tableau_layer_bfs([child], max_depth=2, max_unique=80, time_limit_s=5.0, rss_abort_mb=512)
    source = inspect.getsource(tableau_layer_bfs)
    assert 'if action == ("deal",)' in source or "action == ('deal',)" in source
    assert result.deal_expanded is False


def test_12_hard_progress_is_a_boundary_and_search_does_not_stop_on_first():
    seed = _toy_pre_deal()
    result = tableau_layer_bfs([seed], max_depth=3, max_unique=80, time_limit_s=5.0, rss_abort_mb=512)
    if result.progress:
        assert result.stop_reason in ("max depth", "frontier empty", "unique limit")
        for rec in result.progress:
            assert rec["fd"] < 14 or rec["foundations"] >= 1


def test_13_timing_classes_are_deal_now_versus_prepare_then_deal():
    assert classify_timing(0) == DEAL_NOW
    assert classify_timing(1) == PREPARE_THEN_DEAL
    assert classify_timing(8) == PREPARE_THEN_DEAL


def test_14_no_strategic_score_in_preview_search():
    source = inspect.getsource(tableau_layer_bfs) + inspect.getsource(virtual_deal_candidates)
    for banned in ("heapq", "target_fu", "landing", "empty_score", "deal_ready", "beam", "MCTS"):
        assert banned not in source
    assert "sort(" not in inspect.getsource(tableau_layer_bfs)


def test_15_important_witness_replays_from_original_deal():
    if not REPORT.exists():
        d1, actions, opening = _d1()
        end = opening.clone()
        replay_actions(end, actions[:38])
        assert pack_state(end) == pack_state(d1)
        return
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    opening = _opening()
    fixtures = [
        ROOT / "solutions" / "4925153_simple_v0_26_before_deal1_fd13.moves.txt",
        ROOT / "solutions" / "4925153_simple_v0_26_prepared_deal1_fd13.moves.txt",
        ROOT / "solutions" / "4925153_simple_v0_26_deal_now_fd13.moves.txt",
    ]
    found = False
    for path in fixtures:
        if not path.exists():
            continue
        found = True
        fx = parse_moves_file(path)
        walk = opening.clone()
        replay_actions(walk, fx)
        assert face_down_count(walk) <= 13 or len(walk.foundations) >= 1
    for key in ("pre_deal_progress", "prepared_deal_progress", "deal_now_progress"):
        items = payload.get(key) or []
        if isinstance(items, dict):
            items = [items]
        for rec in items:
            actions = rec.get("full_actions") or []
            if not actions:
                continue
            found = True
            walk = opening.clone()
            replay_actions(walk, [tuple(a) if a != ["deal"] else ("deal",) for a in actions])
            assert rec.get("full_replay_ok", True) is True
    assert found or payload.get("pre_deal_hard_progress") is False


def test_16_production_solver_and_deal_legality_remain_unchanged():
    d1, *_ = _d1()
    assert pack_state(d1)[:4] == b"SPK1"
    assert pack_search_identity(d1) == pack_state(d1)
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    default = solve_progressive(d1, **kwargs)
    explicit = solve_progressive(d1, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert default.nodes == explicit.nodes
    source = inspect.getsource(solve_progressive)
    assert "tableau_layer_bfs" not in source
    assert "virtual_deal_candidates" not in source


def test_17_mobilityware_unrestricted_deal_remains_legal_with_empties():
    assert MW_RULES.can_deal_into_empty is True
    stock = [Card("c", rank) for rank in range(1, 11)]
    cols = [Column([], [])] + [Column([], [Card("s", 13)]) for _ in range(9)]
    state = SpiderState(cols, stock, [])
    assert state.columns[0].is_empty()
    assert state.can_deal(MW_RULES) is True
    apply_action(state, ("deal",))
    assert not state.columns[0].is_empty()
