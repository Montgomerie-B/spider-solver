"""v0.130 post-SD5 completion fixtures.

Identity, cost, and replay checks use a tiny stock-empty endgame. The
80,000-state experiment is not part of this suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.human_strategy.anchored import build_checkpoints
from spider.human_strategy.evaluation import admissible_remaining, same_suit_bonds
from spider.human_strategy.incumbent import verify_complete_solution
from spider.metrics import parse_moves_file
from spider.packed_state import (
    pack_post_stock_symmetry_state,
    pack_state,
    pack_whole_game_identity,
)
from spider.post_sd5_completion import (
    completion_lane_key,
    cost_lane_key,
    search_post_sd5,
)
from spider.research_actions import all_legal_actions, apply_action, face_down_count, step_cost
from spider.assembly_lower_bound import stock_empty_assembly_h


def _run(suit: str) -> list:
    return [Card(suit, rank) for rank in range(13, 0, -1)]


def _almost_solved() -> SpiderState:
    """Seven foundations home. Hearts K–2 in column 1 and Ah in column 2.

    Column 1 can move onto an empty column for corrected cost 0. Ah onto
    the heart 2 completes the eighth foundation.
    """

    hearts = [Card("h", rank) for rank in range(13, 1, -1)]
    columns = []
    for index in range(10):
        if index == 0:
            columns.append(Column([], hearts))
        elif index == 1:
            columns.append(Column([], [Card("h", 1)]))
        else:
            columns.append(Column([], []))
    foundations = [
        _run("h"),
        _run("s"),
        _run("s"),
        _run("d"),
        _run("d"),
        _run("c"),
        _run("c"),
    ]
    return SpiderState(columns, [], foundations)


def _stock_state(left: str, right: str) -> SpiderState:
    columns = [Column([], []) for _ in range(10)]
    columns[0] = Column([], [Card.parse(left)])
    columns[1] = Column([], [Card.parse(right)])
    stock = [Card("s", rank) for rank in range(1, 11)]
    return SpiderState(columns, stock, [])


def test_stock_bearing_columns_are_not_symmetrised():
    left = _stock_state("Kh", "Qh")
    right = _stock_state("Qh", "Kh")
    assert pack_whole_game_identity(left) == pack_state(left)
    assert pack_whole_game_identity(left) != pack_whole_game_identity(right)
    with pytest.raises(ValueError, match="stock"):
        pack_post_stock_symmetry_state(left)


def test_empty_stock_permutation_shares_whole_game_identity():
    state = _almost_solved()
    moved = state.clone()
    cost = apply_action(moved, (0, 2, 12))
    assert cost == 0
    assert pack_whole_game_identity(state) == pack_whole_game_identity(moved)
    assert pack_state(state) != pack_state(moved)
    assert pack_whole_game_identity(state) == pack_post_stock_symmetry_state(state)


def test_completion_order_is_admissible_f_and_cost_order_is_g():
    state = _almost_solved()
    h = admissible_remaining(state)
    assert h == stock_empty_assembly_h(state)
    assert h >= 1
    assert completion_lane_key(state, 10) == (10 + h, h, -7, 10)
    assert cost_lane_key(state, 10) == (10,)


def test_zero_cost_transfer_stays_legal_and_deal_is_absent():
    state = _almost_solved()
    actions = all_legal_actions(state)
    assert ("deal",) not in actions
    assert any(step_cost(state, action) == 0 for action in actions)
    assert state.can_deal() is False


def test_symmetry_replays_the_direct_solution_on_the_original_columns():
    state = _almost_solved()
    found = search_post_sd5(
        state,
        g0=10,
        ceiling=11,
        ordering="completion",
        max_unique=400,
        time_limit_s=5,
        rss_abort_mb=512,
    )
    assert found.solved is True
    assert found.replay_ok is True
    assert found.suffix == ((1, 0, 1),)
    assert found.suffix_cost == 1
    assert found.solution_g == 11
    assert found.zero_cost_actions >= 1
    assert found.duplicate_skips >= 1
    assert found.symmetry_collapses >= 1
    assert found.negative_proof is False
    verified = verify_complete_solution(
        state,
        found.suffix,
        expected_cost=1,
        source="test",
        source_id="post-sd5-fixture",
    )
    assert verified.solved is True
    assert verified.foundations == 8


def test_ordered_identity_spends_the_same_cap_on_the_free_transfer():
    """The free column relocation is a new ordered state and the same symmetry state."""

    state = _almost_solved()
    # The search helper always uses whole-game identity. This test calls the
    # kernel directly so the cap contrast is visible.
    from spider.search_kernel import SearchLimits, run_search
    from spider.packed_state import unpack_state

    kernel = run_search(
        [{"ordered_digest": pack_state(state).hex(), "g": 10}],
        limits=SearchLimits(max_unique=2, time_limit_s=5, rss_abort_mb=512, cost_ceiling=11),
        identity_fn=pack_state,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=("cost",),
        lane_key_fns=(cost_lane_key,),
        is_terminal=lambda item: item.is_solved(),
        actions_fn=all_legal_actions,
        action_order=lambda _state, actions: sorted(
            actions, key=lambda action: (step_cost(_state, action), str(action))
        ),
        lower_bound_fn=lambda item, _g: admissible_remaining(item),
        stop_on_first_terminal=True,
    )
    assert kernel.stop_reason == "unique limit"
    assert kernel.terminals == []
    assert kernel.zero_cost_actions >= 1


def test_bound_keeps_an_equal_ceiling_and_prunes_above_it():
    state = _almost_solved()
    kept = search_post_sd5(
        state,
        g0=10,
        ceiling=11,
        ordering="cost",
        max_unique=400,
        time_limit_s=5,
    )
    assert kept.solved is True
    assert kept.solution_g == 11
    pruned = search_post_sd5(
        state,
        g0=10,
        ceiling=10,
        ordering="cost",
        max_unique=20,
        time_limit_s=5,
    )
    assert pruned.solved is False
    assert pruned.negative_proof is True
    assert pruned.stop_reason == "complete"
    assert pruned.expanded == 0
    assert pruned.lower_bound_prunes >= 1
    assert pruned.terminals == 0


def test_unknown_ordering_is_rejected():
    with pytest.raises(ValueError, match="orbit"):
        search_post_sd5(_almost_solved(), g0=0, ceiling=1, ordering="orbit")


def test_canonical_post_sd5_contract_is_recomputed():
    opening = SpiderState.from_cards(list(load_deal(ROOT / "deals" / "4925153.txt")))
    actions = parse_moves_file(ROOT / "solutions" / "4925153_canonical.moves")
    checkpoints = build_checkpoints(opening, actions)
    deals = 0
    index = None
    for action_index, action in enumerate(actions):
        if action == ("deal",):
            deals += 1
            if deals == 5:
                index = action_index + 1
                break
    assert index == 152
    checkpoint = checkpoints[index]
    assert checkpoint.g == 150
    assert checkpoint.stock_cards == 0
    assert checkpoint.face_down == face_down_count(checkpoint.state) == 1
    assert checkpoint.bonds == same_suit_bonds(checkpoint.state) == 54
    assert stock_empty_assembly_h(checkpoint.state) == 18
    assert admissible_remaining(checkpoint.state) == 18
    assert checkpoints[-1].g - checkpoint.g == 22
    assert checkpoints[-1].g == 172
    work = checkpoint.state.clone()
    g = checkpoint.g
    for action in actions[index:]:
        remain = 172 - g
        assert stock_empty_assembly_h(work) <= remain
        assert admissible_remaining(work) <= remain
        g += apply_action(work, action)
    assert g == 172
    assert work.is_solved()
