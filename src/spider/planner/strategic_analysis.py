"""Thin generic StrategicAnalysis aggregator (Sprint 1C).

Aggregates Sprint 1A/1B/1C views without inventing a master score.
Future Sprint 1D stock-reception analysis should consume this object.
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


@dataclass(frozen=True)
class StrategicAnalysis:
    """Coherent multi-view analysis of a perfect-information Spider state.

    This is an AGGREGATOR, not a combined scoring oracle.
    """

    foundation: Optional[FoundationFeasibilityAnalysis]
    reveal: Optional[RevealGraphAnalysis]
    space: SpaceLifecycleAnalysis


def analyze_strategic(
    state: SpiderState,
    *,
    cards: Optional[Sequence[Card]] = None,
) -> StrategicAnalysis:
    """Build foundation + reveal + space analyses for ``state``."""
    foundation = None
    if cards is not None:
        foundation = analyze_foundation_feasibility(cards, state)
    reveal = analyze_reveal_graph(
        state, cards=cards, foundation_analysis=foundation
    )
    space = analyze_space_lifecycle(
        state, reveal_analysis=reveal, cards=cards, include_reveal_link=True
    )
    return StrategicAnalysis(foundation=foundation, reveal=reveal, space=space)
