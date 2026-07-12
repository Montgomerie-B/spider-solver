"""Metrics and MW cost baseline tests."""

from pathlib import Path

import pytest

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import (
    CANONICAL_MW_COST,
    RECORD_MW_COST,
    mw_cost_from_moves_file,
    parse_moves_file,
    replay_actions,
)

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
DEAL = ROOT / "deals" / "4925153.txt"


def test_canonical_mw_cost():
    """Corrected mobilityware_moves for the 174-command user trace is 172."""
    from spider.metrics import CANONICAL_MOBILITYWARE_MOVES, LEGACY_CANONICAL_MW_COST

    cost = mw_cost_from_moves_file(CANONICAL, DEAL)
    assert cost == CANONICAL_MW_COST == CANONICAL_MOBILITYWARE_MOVES == 172
    assert LEGACY_CANONICAL_MW_COST == 163  # defective historical total


def test_canonical_replay_wins():
    state = SpiderState.from_cards(load_deal(DEAL))
    actions = parse_moves_file(CANONICAL)
    replay_actions(state, actions)
    assert state.is_solved()


def test_record_target_documents_aspiration():
    assert RECORD_MW_COST < CANONICAL_MW_COST