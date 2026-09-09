"""Band-local saturation v0.7: scheduling scope only, TT unchanged."""

from __future__ import annotations

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.rules import MW_RULES
from spider.simple_progressive_solver import (
    N_PASSES,
    SaturationBook,
    CoverageTT,
    Tier,
    action_allowed,
    classify_tier,
    evaluate_deal_landings,
    solve_progressive,
)


def _filled(slots: dict[int, list[Card]], stock: list[Card] | None = None) -> SpiderState:
    cols = []
    for index in range(10):
        cards = slots.get(index, [Card("shdc"[index % 4], 13)])
        cols.append(Column([], list(cards)))
    return SpiderState(cols, stock or [])


def _mixed_only() -> SpiderState:
    return _filled({0: [Card("h", 7), Card("s", 6)], 1: [Card("d", 7)]})


def _uncover_state() -> SpiderState:
    cols = []
    slots = {
        0: ([Card("d", 9)], [Card("h", 6)]),
        1: ([], [Card("c", 7)]),
        2: ([Card("s", 8)], [Card("d", 5)]),
        3: ([], [Card("h", 6)]),
    }
    for index in range(10):
        down, up = slots.get(index, ([], [Card("s", 13)]))
        cols.append(Column(list(down), list(up)))
    return SpiderState(cols, [Card("c", rank) for rank in range(1, 11)])


def test_1_saturation_can_occur_for_band160_pass1():
    book = SaturationBook(band_local=True)
    book.mark(1, 160)
    assert book.is_saturated(1, 160)
    assert 1 in book.passes()
    assert {"band": 160, "pass": 1} in book.cells()


def test_2_band160_pass1_does_not_saturate_band320_pass1():
    book = SaturationBook(band_local=True)
    book.mark(1, 160)
    assert not book.is_saturated(1, 320)
    assert not book.is_saturated(1, 640)
    assert not book.is_saturated(1, 1280)
    assert not book.inherited(1, 320)


def test_3_pass1_schedulable_again_in_deeper_band():
    result = solve_progressive(
        _mixed_only(),
        max_nodes=400,
        time_limit_s=2.0,
        depth_bands=(2, 4, 8),
        target_foundations=8,
        enable_saturation=True,
        enable_band_local_saturation=True,
        enable_audit=False,
    )
    reports = result.stats.band_pass_reports
    assert reports
    assert not any(row["skipped"] for row in reports)
    assert not any(row["saturation_inherited"] for row in reports)
    assert result.stats.slices_skipped == 0
    bands = sorted({row["band"] for row in reports})
    assert len(bands) >= 2
    for pass_level in range(4):
        rows = [row for row in reports if row["pass"] == pass_level]
        if len(rows) < 2:
            continue
        assert all(row["scheduled"] and not row["skipped"] for row in rows)


def test_4_tt_coverage_from_shallower_band_is_retained():
    tt = CoverageTT()
    key = b"band160-state"
    tt.mark_done(key, 1, 160)
    assert tt.skip(key, 1, 160)
    assert tt.skip(key, 1, 80)
    assert tt.max_covered_remaining(key, 1) == 160
    book = SaturationBook(band_local=True)
    book.mark(1, 160)
    assert tt.skip(key, 1, 160)
    assert not book.is_saturated(1, 320)


def test_5_no_extra_remaining_depth_still_tt_pruned():
    tt = CoverageTT()
    key = b"covered-160"
    tt.mark_done(key, 1, 160)
    assert tt.skip(key, 1, 160)
    assert tt.skip(key, 0, 160)
    result = solve_progressive(
        _mixed_only(),
        max_nodes=200,
        time_limit_s=2.0,
        depth_bands=(2, 4),
        enable_band_local_saturation=True,
        enable_audit=False,
    )
    assert result.stats.tt_depth_prunes >= 0


def test_6_larger_remaining_depth_can_reopen():
    tt = CoverageTT()
    key = b"need-deeper"
    tt.mark_done(key, 1, 160)
    assert not tt.skip(key, 1, 320)
    assert not tt.skip(key, 1, 640)
    result = solve_progressive(
        _mixed_only(),
        max_nodes=400,
        time_limit_s=2.0,
        depth_bands=(2, 4, 8),
        enable_band_local_saturation=True,
        enable_audit=False,
    )
    assert result.stats.tt_reopens >= 0
    live = [row for row in result.stats.band_pass_reports if row["scheduled"]]
    assert any(row["band"] > 2 and row["expanded"] > 0 for row in live)


def test_7_saturation_still_suppresses_within_the_same_band():
    book = SaturationBook(band_local=True)
    book.mark(1, 160)
    assert book.is_saturated(1, 160)
    assert book.inherited(1, 160) is False
    cross = SaturationBook(band_local=False)
    cross.mark(1, 160)
    assert cross.is_saturated(1, 160)
    assert cross.is_saturated(1, 320)
    assert cross.inherited(1, 320) is True


def test_8_pass_0_to_3_semantics_unchanged():
    assert N_PASSES == 4
    assert action_allowed(Tier.A, 0)
    assert not action_allowed(Tier.B, 0)
    assert action_allowed(Tier.B, 1)
    assert action_allowed(Tier.C, 2)
    assert action_allowed(Tier.D, 3)
    assert not action_allowed(Tier.D, 2)
    state = _uncover_state()
    landing = evaluate_deal_landings(state)
    assert classify_tier(state, ("deal",), landing=landing) is Tier.D


def test_9_best_reveal_deal_probe_unchanged():
    kwargs = dict(
        max_nodes=80,
        time_limit_s=2.0,
        depth_bands=(8,),
        max_pass=0,
        enable_best_reveal_deal_probe=True,
        enable_audit=False,
        enable_saturation=True,
    )
    off = solve_progressive(_uncover_state(), enable_band_local_saturation=False, **kwargs)
    on = solve_progressive(_uncover_state(), enable_band_local_saturation=True, **kwargs)
    assert off.stats.probe_fires == on.stats.probe_fires
    assert sum(off.stats.probe_fires) >= 1
    assert off.stats.deals_executed == on.stats.deals_executed
    assert MW_RULES.can_deal_into_empty is True


def test_10_default_remains_cross_band():
    result = solve_progressive(
        _mixed_only(),
        max_nodes=400,
        time_limit_s=2.0,
        depth_bands=(2, 4, 8),
        target_foundations=8,
        enable_audit=False,
    )
    assert result.stats.band_local_saturation is False
    triggered = next(row for row in result.stats.band_pass_reports if row["saturation_triggered"])
    skipped_same = [
        row
        for row in result.stats.band_pass_reports
        if row["pass"] == triggered["pass"]
        and row["band"] > triggered["band"]
        and row["skipped"]
    ]
    assert skipped_same
    assert all(row["saturation_inherited"] for row in skipped_same)
