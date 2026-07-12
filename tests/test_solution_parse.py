import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.solution_parse import (
    ParsedMove,
    _cards_from_notation,
    _match_move,
    _run_size_for_anchor,
    apply_parsed_move,
    extract_moves_from_text,
)


def test_parse_5_plus_4s():
    cards = _cards_from_notation("5+4S")
    assert len(cards) == 2
    assert str(cards[0]) == "5s"
    assert str(cards[1]) == "4s"


def test_run_size_requires_anchor_run_to_reach_top():
    """Named runs (e.g. QS run) only apply when the same-suit chain reaches the pile top."""
    up = [
        Card.parse("kd"),
        Card.parse("qs"),
        Card.parse("js"),
        Card.parse("10c"),
        Card.parse("as"),
    ]
    import pytest

    with pytest.raises(ValueError, match="does not reach top"):
        _run_size_for_anchor(up, Card.parse("qs"), use_run=True)


def test_same_suit_run_through_ace():
    up = [Card.parse(f"{r}s") for r in "kqjt98765432a".replace("t", "10")]
    # Build Ks..As: use helper
    up = [Card("s", r) for r in (13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1)]
    assert _run_size_for_anchor(up, Card.parse("qs"), use_run=True) == 12


def test_buried_anchor_infers_same_suit_run():
    """JD col 3 to col 4 without 'run' when diamonds Jd..6d sit on Qd."""
    from spider.engine import Column

    state = SpiderState([Column([], []) for _ in range(10)], [])
    state.columns[2].face_up = [
        Card.parse("jd"),
        Card.parse("10d"),
        Card.parse("9d"),
        Card.parse("8d"),
        Card.parse("7d"),
        Card.parse("6d"),
    ]
    state.columns[3].face_up = [Card.parse("10h"), Card.parse("kh"), Card.parse("qd")]
    pm = ParsedMove(
        kind="move",
        src=2,
        dst=3,
        anchor=Card.parse("jd"),
        use_run=False,
        raw="JD col 3 to col 4",
    )
    src, dst, k = _match_move(state, pm)
    assert (src, dst, k) == (2, 3, 6)


def test_top_anchor_still_moves_single_card():
    from spider.engine import Column

    state = SpiderState([Column([], []) for _ in range(10)], [])
    state.columns[5].face_up = [Card.parse("qs"), Card.parse("jc"), Card.parse("10s"), Card.parse("6d")]
    state.columns[7].face_up = [
        Card.parse("8s"),
        Card.parse("7s"),
        Card.parse("6s"),
        Card.parse("5s"),
        Card.parse("4s"),
        Card.parse("3s"),
        Card.parse("2s"),
        Card.parse("7d"),
    ]
    pm = ParsedMove(kind="move", src=5, dst=7, anchor=Card.parse("6d"), raw="6D col6 to col8")
    src, dst, k = _match_move(state, pm)
    assert (src, dst, k) == (5, 7, 1)


def test_extract_finds_deals():
    text = "move 2s col 1 to col 2. Deal from stock. Deal from stock."
    # minimal text won't match all patterns; use real snippet
    snippet = "5H col 10 to col 4, Deal from stock, 6D col6 to col8"
    moves = extract_moves_from_text(snippet)
    assert any(m.kind == "deal" for m in moves)