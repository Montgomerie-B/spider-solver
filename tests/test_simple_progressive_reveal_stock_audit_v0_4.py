"""Reveal/stock coupling diagnostics: telemetry only, search unchanged."""

from __future__ import annotations

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.packed_state import pack_state
from spider.rules import MobilityWareRules, MW_RULES
from spider.simple_progressive_solver import solve_progressive
from spider.simple_reveal_stock_audit import (
    cheap_structure,
    counterfactual_deal_now,
    counterfactual_prep_then_deal,
    pareto_dominates,
    run_strong_reveal_counterfactuals,
)
from spider.state_identity import canonical_state_key


def _filled(slots: dict[int, list[Card]], stock: list[Card] | None = None) -> SpiderState:
    cols = []
    for index in range(10):
        cards = slots.get(index, [Card("shdc"[index % 4], 13)])
        cols.append(Column([], list(cards)))
    return SpiderState(cols, stock or [])


def _deal_prep_opening() -> SpiderState:
    cols = [Column([], []) for _ in range(10)]
    cols[0].face_up = [Card("h", 7)]
    cols[1].face_up = [Card("s", 6)]
    for index in range(2, 10):
        cols[index].face_up = [Card("c", 13)]
    stock = [Card("s", 5)] + [Card("d", rank) for rank in range(2, 11)]
    return SpiderState(cols, stock)


def _almost_solved() -> SpiderState:
    foundations = []
    for copy in range(2):
        for suit in "shdc":
            if copy == 1 and suit == "c":
                continue
            foundations.append([Card(suit, rank) for rank in range(13, 0, -1)])
    cols = [Column([], []) for _ in range(10)]
    cols[0].face_up = [Card("c", rank) for rank in range(13, 1, -1)]
    cols[1].face_up = [Card("c", 1)]
    return SpiderState(cols, [], foundations)


def test_1_pareto_frontier_accounting():
    assert pareto_dominates((10, 4, 0), (12, 4, 0))
    assert not pareto_dominates((10, 5, 0), (12, 4, 0))
    result = solve_progressive(
        _almost_solved(), max_nodes=20, time_limit_s=1.0, depth_bands=(8,)
    )
    assert result.audit is not None
    assert result.audit.pareto_log
    assert result.audit.pareto_log[0]["fd"] >= 0
    fds = [item["fd"] for item in result.audit.pareto_log]
    assert fds[-1] <= fds[0]


def test_2_stock_depth_witness_identity():
    state = _deal_prep_opening()
    result = solve_progressive(
        state,
        max_nodes=400,
        time_limit_s=2.0,
        depth_bands=(8, 16),
        max_pass=3,
    )
    assert result.audit is not None
    best0 = result.audit.best_reveal[0]
    assert best0["fd"] is not None
    assert best0["path"] is not None
    end = state.clone()
    if best0["path"]:
        replay_actions(end, list(best0["path"]))
    assert sum(len(col.face_down) for col in end.columns) == best0["fd"]


def test_3_pre_post_deal_linkage():
    state = _deal_prep_opening()
    result = solve_progressive(
        state,
        max_nodes=800,
        time_limit_s=2.0,
        depth_bands=(12, 24),
        max_pass=3,
    )
    assert result.stats.deals_executed >= 1
    assert result.audit is not None
    pre = result.audit.pre_deal[0]
    post = result.audit.post_deal[0]
    assert pre["fd"] is not None
    assert post["fd"] is not None
    assert post["path"][-1] == ("deal",)
    assert post["path"][:-1] == pre["path"]
    end = state.clone()
    replay_actions(end, list(post["path"]))
    assert len(end.stock) // 10 == 0


def test_4_deal_legality_empty_and_filled():
    stock = [Card("c", rank) for rank in range(1, 11)]
    filled = _filled({index: [Card("s", 5)] for index in range(10)}, stock=stock)
    empty = filled.clone()
    empty.columns[3].face_up.clear()
    assert empty.columns[3].is_empty()
    assert filled.can_deal(rules=MW_RULES)
    assert empty.can_deal(rules=MW_RULES)
    restricted = MobilityWareRules(can_deal_into_empty=False)
    assert not empty.can_deal(rules=restricted)
    assert cheap_structure(empty)["empties"] == 1


def test_5_deal_order_position_telemetry():
    state = _deal_prep_opening()
    result = solve_progressive(
        state,
        max_nodes=800,
        time_limit_s=2.0,
        depth_bands=(12,),
        max_pass=3,
    )
    assert result.audit is not None
    assert result.audit.deal_ordinals
    assert all(item >= 0 for item in result.audit.deal_ordinals)
    order = result.audit.strong_order[0]
    if order is not None and order["deal_in_pass"]:
        assert order["deal_index"] is not None
        assert order["deal_index"] < order["n_children"]


def test_6_post_deal_expansion_lineage():
    state = _deal_prep_opening()
    result = solve_progressive(
        state,
        max_nodes=800,
        time_limit_s=2.0,
        depth_bands=(16,),
        max_pass=3,
    )
    assert result.audit is not None
    assert result.audit.deal_traces
    if result.audit.continuation:
        rec = result.audit.continuation[0]
        assert "subtree_exp" in rec
        assert rec["subtree_exp"] >= 0


def test_7_deal_now_counterfactual_does_not_mutate():
    state = _deal_prep_opening()
    before = canonical_state_key(state)
    packed = pack_state(state)
    probe = counterfactual_deal_now(state)
    assert canonical_state_key(state) == before
    assert pack_state(state) == packed
    assert probe is not None
    assert probe["structure"]["stock_rows"] == 0


def test_8_prep_then_deal_counterfactual_does_not_mutate():
    state = _deal_prep_opening()
    before = canonical_state_key(state)
    probe = counterfactual_prep_then_deal(state, (1, 0, 1))
    assert canonical_state_key(state) == before
    assert probe is not None and probe["dealt"] is True
    again = run_strong_reveal_counterfactuals(state, [])
    assert again["opening_unmutated"] is True
    assert canonical_state_key(state) == before


def test_9_replay_validation_of_stored_witnesses():
    state = _deal_prep_opening()
    result = solve_progressive(
        state,
        max_nodes=500,
        time_limit_s=2.0,
        depth_bands=(12, 24),
        max_pass=3,
    )
    assert result.replay_ok or not result.actions
    assert result.audit is not None
    for dealt, slot in enumerate(result.audit.best_reveal):
        if not slot["path"]:
            continue
        end = state.clone()
        replay_actions(end, list(slot["path"]))
        assert sum(len(col.face_down) for col in end.columns) == slot["fd"]


def test_10_no_search_order_behavioural_change():
    state = _deal_prep_opening()
    kwargs = dict(
        max_nodes=300,
        time_limit_s=2.0,
        depth_bands=(8, 16),
        max_pass=3,
        enable_saturation=True,
    )
    off = solve_progressive(state, enable_audit=False, **kwargs)
    on = solve_progressive(state, enable_audit=True, **kwargs)
    assert off.nodes == on.nodes
    assert off.stats.deals_executed == on.stats.deals_executed
    assert off.stats.unique_exact_states == on.stats.unique_exact_states
    assert off.best_reveal_actions == on.best_reveal_actions
    assert off.best_reveal_fd == on.best_reveal_fd
    assert on.audit is not None
    assert off.audit is None
