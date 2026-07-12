import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState


DEAL = ROOT / "deals" / "4925153.txt"


def test_deal_has_104_cards():
    assert len(load_deal(DEAL)) == 104


def test_initial_top_row_matches_tableau_screenshot():
    """Face-up tops must match docs/Tableau.png (left to right)."""
    state = SpiderState.from_cards(load_deal(DEAL))
    tops = [str(c) for c in state.top_row()]
    assert tops == ["2s", "Kd", "4s", "7h", "Kc", "5s", "8d", "6s", "9c", "7c"]


def test_stock_count():
    state = SpiderState.from_cards(load_deal(DEAL))
    assert len(state.stock) == 50


def test_first_stock_deal_in_live_moves_file():
    """Live line includes deal #1; tops match user-confirmed row."""
    state = SpiderState.from_cards(load_deal(DEAL))
    for path in (
        ROOT / "solutions" / "4925153_through_jd.moves",
        ROOT / "solutions" / "4925153_live.moves",
    ):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if parts[0] == "move":
                state.move(int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3]))
            elif parts[0] == "deal":
                state.deal()
    tops = [str(c) for c in state.top_row()]
    assert tops == ["Js", "9d", "4d", "Kh", "4d", "6d", "9s", "7d", "8s", "5c"]


def test_suit_clearance_plan_basic():
    """The global pre-analysis (reverse-engineering eligibility + priorities) works on this deal."""
    from spider.deal_analysis import build_deal_analysis

    tokens = [t for t in (ROOT / "deals" / "4925153.txt").read_text(encoding="utf-8").replace(",", " ").split() if t.strip()]
    plan = build_deal_analysis(tokens)

    # Initial counts (from layout)
    assert plan.initial_count_by_suit["s"] == 14
    assert plan.initial_count_by_suit["h"] == 13
    assert plan.initial_count_by_suit["d"] == 11
    assert plan.initial_count_by_suit["c"] == 16

    # Cumulative after r0 (initial)
    assert plan.cumulative_by_suit["s"][0] == 14
    assert plan.cumulative_by_suit["d"][0] == 11

    # Eligible after r0: s,h,c have >=13; d does not yet
    elig0 = plan.eligible_suits_by_round[0]
    assert "s" in elig0 and "h" in elig0 and "c" in elig0
    assert "d" not in elig0

    # After r1, d becomes eligible
    elig1 = plan.eligible_suits_by_round[1]
    assert "d" in elig1

    # Priority order puts early ones first (s/h/c before or with d)
    assert plan.priority_clearance_order[0] in ("s", "h", "c")

    # Buried columns for an early suit (e.g. spades) has some columns
    assert len(plan.initial_buried_columns_by_suit.get("s", [])) > 0

    # plan_eligibility_score (from heuristics) should give non-negative and reward states
    # with tails on early-eligible suits (s/h/c after r0).
    from spider.heuristics import plan_eligibility_score
    state0 = SpiderState.from_cards(load_deal(DEAL))
    score0 = plan_eligibility_score(state0, plan, 0)
    assert score0 >= 0


def test_second_stock_deal_tops_after_live_prefix():
    """Deal 2 exposed row after live prefix (51 moves + deal 1) + deal 2."""
    state = SpiderState.from_cards(load_deal(DEAL))
    prefix = ROOT / "solutions" / "4925153_after_deal1.moves"
    for line in prefix.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] == "move":
            state.move(int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3]))
        elif parts[0] == "deal":
            state.deal()
    state.deal()
    tops = [str(c) for c in state.top_row()]
    assert tops == ["Ks", "As", "6h", "7s", "Ad", "Ad", "Ah", "10d", "Qh", "Jd"]


def test_first_stock_deal_matches_mobilityware_order():
    """First deal row is the last 10 stock tokens in the deal file."""
    state = SpiderState.from_cards(load_deal(DEAL))
    state.deal()
    tops = [str(c) for c in state.top_row()]
    assert tops == ["Js", "9d", "4d", "Kh", "4d", "6d", "9s", "7d", "8s", "5c"]