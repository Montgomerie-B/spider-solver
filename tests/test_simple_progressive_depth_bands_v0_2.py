"""Simple progressive solver v0.2: depth-band and remaining-depth TT tests."""

from __future__ import annotations

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.simple_progressive_solver import (
    CoverageTT,
    DEFAULT_DEPTH_BANDS,
    deal_preparation,
    enumerate_actions,
    evaluate_deal_landings,
    ordered_actions,
    solve_progressive,
    unique_successor_actions,
    _clip_depth_bands,
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


def _two_move_foundation() -> SpiderState:
    foundations = []
    for copy in range(2):
        for suit in "shdc":
            if copy == 1 and suit == "c":
                continue
            foundations.append([Card(suit, rank) for rank in range(13, 0, -1)])
    cols = [Column([], []) for _ in range(10)]
    cols[0].face_up = [Card("c", rank) for rank in range(13, 2, -1)]
    cols[1].face_up = [Card("c", 2)]
    cols[2].face_up = [Card("c", 1)]
    return SpiderState(cols, [], foundations)


def test_1_depth_limit_obeyed():
    state = _filled({0: [Card("h", 7), Card("s", 6)], 1: [Card("d", 7)]})
    result = solve_progressive(
        state,
        max_nodes=800,
        time_limit_s=2.0,
        depth_bands=(3,),
        max_depth=3,
        target_foundations=8,
    )
    assert result.stats.max_depth <= 3
    assert result.depth_bands_used == [3]
    assert result.nodes <= 800


def test_2_shallow_remaining_reopens_under_deeper_budget():
    tt = CoverageTT()
    key = b"state-a"
    tt.mark_start(key, 0, 10)
    tt.mark_done(key, 0, 10)
    assert tt.skip(key, 0, 10)
    assert tt.skip(key, 0, 4)
    assert not tt.skip(key, 0, 80)
    assert tt.max_covered_remaining(key, 0) == 10


def test_3_coverage_dominates_equal_or_smaller_remaining():
    tt = CoverageTT()
    key = b"state-b"
    tt.mark_start(key, 2, 40)
    tt.mark_done(key, 2, 40)
    assert tt.skip(key, 2, 40)
    assert tt.skip(key, 2, 40)
    assert tt.skip(key, 2, 1)
    assert not tt.skip(key, 2, 41)


def test_4_relaxation_pass_remains_part_of_coverage():
    tt = CoverageTT()
    key = b"state-c"
    tt.mark_done(key, 0, 50)
    assert tt.skip(key, 0, 50)
    assert not tt.skip(key, 1, 50)
    tt.mark_done(key, 3, 50)
    assert tt.skip(key, 0, 50)
    assert tt.skip(key, 2, 50)
    assert tt.skip(key, 3, 50)
    assert not tt.skip(key, 3, 80)


def test_5_active_path_cycle_independent_of_tt():
    state = _filled({0: [Card("h", 7), Card("s", 6)], 1: [Card("d", 7)]})
    result = solve_progressive(
        state, max_nodes=400, time_limit_s=2.0, depth_bands=(20,), target_foundations=8
    )
    assert result.stats.path_cycles + result.stats.inverses >= 1
    tt = CoverageTT()
    key = b"on-path"
    assert not tt.skip(key, 0, 5)
    # Path membership is not stored in the TT.
    assert key not in tt.seen
    assert key not in tt.done


def test_6_child_dedup_unchanged():
    state = _filled({0: [Card("h", 8)], 1: [Card("c", 7)]})
    unique = unique_successor_actions(state, [(1, 0, 1), (1, 0, 1)])
    assert unique == [(1, 0, 1)]


def test_7_deal_behavior_unchanged():
    state = _deal_prep_opening()
    landing = evaluate_deal_landings(state)
    assert landing is not None and landing.legal and landing.same_suit == 0
    prep, after = deal_preparation(state, prep_ply=1)
    assert prep == (1, 0, 1)
    assert after is not None
    pass1 = ordered_actions(state, 1, prep_ply=1)
    assert pass1[0] == (1, 0, 1)
    assert ("deal",) not in pass1
    pass3 = ordered_actions(state, 3, prep_ply=1)
    assert ("deal",) in pass3
    assert pass3.index((1, 0, 1)) < pass3.index(("deal",))
    assert ("deal",) in enumerate_actions(state)


def test_8_replay_path_survives_iterative_bands():
    state = _two_move_foundation()
    result = solve_progressive(
        state,
        max_nodes=200,
        time_limit_s=2.0,
        depth_bands=(1, 2),
        target_foundations=8,
    )
    assert result.solved
    assert result.replay_ok
    assert result.depth_bands_used[-1] == 2
    end = state.clone()
    assert replay_actions(end, list(result.actions)) == result.cost
    assert end.is_solved()
    assert canonical_state_key(state) == canonical_state_key(_two_move_foundation())


def test_9_deterministic_band_sequence():
    assert DEFAULT_DEPTH_BANDS == (80, 160, 320, 640, 1280)
    assert _clip_depth_bands(None, 5000) == DEFAULT_DEPTH_BANDS
    assert _clip_depth_bands(None, 100) == (80,)
    assert _clip_depth_bands((80, 160), 80) == (80,)
    state = _filled({0: [Card("h", 10)], 1: [Card("h", 9)]})
    result = solve_progressive(
        state, max_nodes=30, time_limit_s=1.0, depth_bands=(80, 160, 320)
    )
    assert result.depth_bands_used
    assert result.depth_bands_used[0] == 80
    assert result.depth_bands_used == sorted(result.depth_bands_used)


def test_10_solution_at_earlier_band_stops_later_work():
    state = _almost_solved()
    result = solve_progressive(
        state,
        max_nodes=50,
        time_limit_s=1.0,
        depth_bands=(80, 160, 320),
        target_foundations=8,
    )
    assert result.solved
    assert result.replay_ok
    assert result.actions == [(1, 0, 1)]
    assert result.depth_bands_used == [80]
    assert result.stop_reason == "target reached"
    assert all(row["band"] == 80 for row in result.stats.band_pass_reports)
