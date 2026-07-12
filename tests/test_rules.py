import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.rules import (
    LEGACY_MW_RULES,
    mobilityware_move_cost,
    mw_move_cost,
    legacy_mw_move_cost,
)


def test_corrected_full_column_to_empty_is_free():
    """Entire column (no face-down) onto empty → 0 MobilityWare moves."""
    assert (
        mobilityware_move_cost(
            cards_moved=3,
            source_face_up_count=3,
            dest_was_empty=True,
            source_face_down_count=0,
        )
        == 0
    )


def test_face_up_stack_to_empty_with_face_down_costs_one():
    """Reveal play: all face-up onto empty but buried cards remain → costs 1."""
    assert (
        mobilityware_move_cost(
            cards_moved=3,
            source_face_up_count=3,
            dest_was_empty=True,
            source_face_down_count=2,
        )
        == 1
    )


def test_single_card_partial_stack_to_empty_costs_one():
    assert (
        mobilityware_move_cost(
            cards_moved=1,
            source_face_up_count=3,
            dest_was_empty=True,
            source_face_down_count=0,
        )
        == 1
    )


def test_legacy_still_free_with_face_down():
    """Defective legacy rule: full face-up→empty free even with face-down under."""
    assert (
        legacy_mw_move_cost(
            cards_moved=3,
            source_face_up_count=3,
            dest_was_empty=True,
            source_face_down_count=2,
        )
        == 0
    )


def test_default_mw_move_cost_matches_corrected():
    assert (
        mw_move_cost(
            cards_moved=3,
            source_face_up_count=3,
            dest_was_empty=True,
            source_face_down_count=2,
        )
        == 1
    )
