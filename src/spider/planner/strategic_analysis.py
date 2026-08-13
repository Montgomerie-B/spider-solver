"""Thin generic StrategicAnalysis aggregator (Sprints 1A–1D).

Aggregates foundation, reveal, space, and stock-reception views without a
master score. Future objective generation should inspect components directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from spider.cards import Card
from spider.engine import SpiderState
from spider.planner.foundation_feasibility import (
    FoundationFeasibilityAnalysis,
    analyze_foundation_feasibility,
)
from spider.planner.reveal_graph import RevealGraphAnalysis, analyze_reveal_graph
from spider.planner.space_lifecycle import (
    SpaceLifecycleAnalysis,
    analyze_space_lifecycle,
)
from spider.planner.stock_reception import (
    StockReceptionAnalysis,
    analyze_stock_reception,
)


@dataclass(frozen=True)
class StrategicAnalysis:
    """Coherent multi-view analysis of a perfect-information Spider state.

    This is an AGGREGATOR, not a combined scoring oracle.
    """

    foundation: Optional[FoundationFeasibilityAnalysis]
    reveal: Optional[RevealGraphAnalysis]
    space: SpaceLifecycleAnalysis
    stock_reception: StockReceptionAnalysis


def analyze_strategic(
    state: SpiderState,
    *,
    cards: Optional[Sequence[Card]] = None,
    shaping_max_cost: int = 2,
    run_shaping_probe: bool = False,
) -> StrategicAnalysis:
    """Build foundation + reveal + space + stock reception analyses.

    ``run_shaping_probe`` defaults False for speed when used as a frequent
    aggregate; diagnostics may enable it.
    """
    foundation = None
    if cards is not None:
        foundation = analyze_foundation_feasibility(cards, state)
    reveal = analyze_reveal_graph(
        state, cards=cards, foundation_analysis=foundation
    )
    space = analyze_space_lifecycle(
        state, reveal_analysis=reveal, cards=cards, include_reveal_link=True
    )
    stock = analyze_stock_reception(
        state,
        cards=cards,
        foundation_analysis=foundation,
        shaping_max_cost=shaping_max_cost,
        run_shaping_probe=run_shaping_probe,
    )
    return StrategicAnalysis(
        foundation=foundation,
        reveal=reveal,
        space=space,
        stock_reception=stock,
    )
