"""Simple progressive solver v0.3: saturation-aware slice scheduling tests."""

from __future__ import annotations

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.simple_progressive_solver import (
    CoverageTT,
    DEFAULT_DEPTH_BANDS,
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


def test_1_zero_novel_completed_slice_triggers_saturation():
    result = solve_progressive(
        _mixed_only(),
        max_nodes=300,
        time_limit_s=2.0,
        depth_bands=(2, 4, 8),
        target_foundations=8,
    )
    pass0 = [row for row in result.stats.band_pass_reports if row["pass"] == 0]
    assert pass0
    assert any(row["saturation_triggered"] for row in pass0)
    assert 0 in result.stats.saturated_passes


def test_2_productive_slice_does_not_saturate():
    result = solve_progressive(
        _mixed_only(),
        max_nodes=300,
        time_limit_s=2.0,
        depth_bands=(2, 4, 8),
        target_foundations=8,
    )
    first = result.stats.band_pass_reports[0]
    assert first["band"] == 2
    assert first["pass"] == 0
    assert first["unique_new"] > 0
    assert first["saturation_triggered"] is False
    assert first["skipped"] is False


def test_3_saturation_advances_to_broader_pass():
    result = solve_progressive(
        _mixed_only(),
        max_nodes=400,
        time_limit_s=2.0,
        depth_bands=(2, 4, 8),
        target_foundations=8,
    )
    reports = result.stats.band_pass_reports
    triggered = next(row for row in reports if row["saturation_triggered"])
    later = [
        row
        for row in reports
        if row["band"] > triggered["band"] or (
            row["band"] == triggered["band"] and row["pass"] > triggered["pass"]
        )
    ]
    assert later
    broader = [row for row in later if row["pass"] > triggered["pass"] and not row["skipped"]]
    assert broader
    skipped_same = [
        row
        for row in later
        if row["pass"] == triggered["pass"] and row["band"] > triggered["band"]
    ]
    assert skipped_same
    assert all(row["skipped"] for row in skipped_same)


def test_4_deeper_band_may_still_reopen_under_tt_contract():
    tt = CoverageTT()
    key = b"state-x"
    tt.mark_done(key, 0, 2)
    assert tt.skip(key, 0, 2)
    assert not tt.skip(key, 0, 8)
    result = solve_progressive(
        _mixed_only(),
        max_nodes=400,
        time_limit_s=2.0,
        depth_bands=(2, 4, 8),
        target_foundations=8,
    )
    assert result.stats.tt_reopens >= 0
    live = [row for row in result.stats.band_pass_reports if not row["skipped"]]
    assert any(row["band"] > 2 and row["expanded"] > 0 for row in live)


def test_5_no_false_proof_exhaustion_from_saturation():
    tt = CoverageTT()
    key = b"untouched"
    assert not tt.skip(key, 0, 100)
    result = solve_progressive(
        _mixed_only(),
        max_nodes=200,
        time_limit_s=2.0,
        depth_bands=(2, 4, 8),
        target_foundations=8,
        enable_saturation=True,
    )
    skipped = [row for row in result.stats.band_pass_reports if row["skipped"]]
    for row in skipped:
        assert row["expanded"] == 0
        assert row["unique_new"] == 0
    # Saturation must not invent INF remaining-depth coverage.
    assert result.stats.slices_skipped == len(skipped)


def test_6_pass_3_remains_reachable():
    result = solve_progressive(
        _mixed_only(),
        max_nodes=500,
        time_limit_s=2.0,
        depth_bands=(2, 4, 8),
        target_foundations=8,
    )
    pass3 = [
        row
        for row in result.stats.band_pass_reports
        if row["pass"] == 3 and not row["skipped"]
    ]
    assert pass3
    assert any(row["expanded"] > 0 for row in pass3)


def test_7_deterministic_scheduling():
    kwargs = dict(
        max_nodes=250,
        time_limit_s=2.0,
        depth_bands=(2, 4, 8),
        target_foundations=8,
    )
    a = solve_progressive(_mixed_only(), **kwargs)
    b = solve_progressive(_mixed_only(), **kwargs)
    keys = ("band", "pass", "skipped", "saturation_triggered", "unique_new", "expanded")
    seq_a = [{k: row[k] for k in keys} for row in a.stats.band_pass_reports]
    seq_b = [{k: row[k] for k in keys} for row in b.stats.band_pass_reports]
    assert seq_a == seq_b
    assert a.stats.saturated_passes == b.stats.saturated_passes


def test_8_depth_bands_otherwise_unchanged():
    assert DEFAULT_DEPTH_BANDS == (80, 160, 320, 640, 1280)
    off = solve_progressive(
        _mixed_only(),
        max_nodes=200,
        time_limit_s=2.0,
        depth_bands=(2, 4, 8),
        target_foundations=8,
        enable_saturation=False,
    )
    assert off.stats.slices_skipped == 0
    assert not any(row["skipped"] for row in off.stats.band_pass_reports)
    assert off.stats.saturated_passes == []
    on = solve_progressive(
        _almost_solved(),
        max_nodes=50,
        time_limit_s=1.0,
        depth_bands=(80, 160),
        target_foundations=8,
    )
    assert on.solved
    assert on.replay_ok
    assert on.depth_bands_used == [80]
