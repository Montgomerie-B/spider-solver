"""Structural diversity protection before the first foundation removal."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional, Tuple

from spider.engine import SpiderState
from spider.planner.economic_project_realizer import StructuralMeasurement
from spider.planner.economic_projects import EconomicAnalysisResult
from spider.state_identity import CanonicalStateKey, canonical_state_key


class PreFoundationDimension(str, Enum):
    BEST_REMOVAL_READINESS = "BEST_REMOVAL_READINESS"
    BEST_PERMANENT_STRUCTURE = "BEST_PERMANENT_STRUCTURE"
    LOWEST_REHANDLING_LIABILITY = "LOWEST_REHANDLING_LIABILITY"
    BEST_REVEAL_DEPENDENCY_GEOMETRY = "BEST_REVEAL_DEPENDENCY_GEOMETRY"
    ALTERNATE_CAMPAIGN = "ALTERNATE_CAMPAIGN"
    DISTINCT_DEAL_RECEIVER_GEOMETRY = "DISTINCT_DEAL_RECEIVER_GEOMETRY"


@dataclass(frozen=True)
class PreFoundationGeometry:
    state_key: CanonicalStateKey
    g: int
    campaign_identity: Optional[str]
    campaign_readiness_rank: int
    bounded_first_removal_estimate: float
    stock_epoch: int
    face_down_count: int
    dependency_burden: int
    stable_same_suit_joins: int
    same_suit_run_topology: Tuple[Tuple[Tuple[str, int, int], ...], ...]
    empty_columns: Tuple[int, ...]
    fully_open_columns: Tuple[int, ...]
    exposed_top_layout: Tuple[Optional[Tuple[str, int]], ...]
    receiver_geometry: Tuple[Tuple[int, str, int, str], ...]
    mixed_boundary_topology: Tuple[Tuple[int, ...], ...]
    rehandling_debt: float
    proof_pruning_allowed: bool = False

    def geometry_key(self) -> Tuple:
        """Material outcome geometry; paid cost and action history are absent."""
        return (
            self.campaign_identity,
            self.campaign_readiness_rank,
            self.stock_epoch,
            self.face_down_count,
            self.dependency_burden,
            self.same_suit_run_topology,
            self.empty_columns,
            self.fully_open_columns,
            self.exposed_top_layout,
            self.receiver_geometry,
            self.mixed_boundary_topology,
        )


@dataclass(frozen=True)
class PreFoundationPortfolio:
    geometries: Tuple[PreFoundationGeometry, ...]
    represented_dimensions: Tuple[Tuple[PreFoundationDimension, Tuple], ...]
    exact_state_suppressions: int
    geometry_suppressions: int
    maximum: int
    proof_pruning_allowed: bool = False


def _same_suit_topology(state: SpiderState) -> Tuple[Tuple[Tuple[str, int, int], ...], ...]:
    result = []
    for column in state.columns:
        runs = []
        cards = column.face_up
        if cards:
            suit = cards[0].suit
            high = low = cards[0].rank
            for lower, upper in zip(cards, cards[1:]):
                if lower.suit == upper.suit and lower.rank - 1 == upper.rank:
                    low = upper.rank
                else:
                    runs.append((suit, high, low))
                    suit = upper.suit
                    high = low = upper.rank
            runs.append((suit, high, low))
        result.append(tuple(runs))
    return tuple(result)


def _mixed_topology(state: SpiderState) -> Tuple[Tuple[int, ...], ...]:
    return tuple(
        tuple(
            index
            for index, (lower, upper) in enumerate(zip(column.face_up, column.face_up[1:]))
            if lower.suit != upper.suit
        )
        for column in state.columns
    )


def _receiver_geometry(state: SpiderState, analysis: Optional[EconomicAnalysisResult]) -> Tuple[Tuple[int, str, int, str], ...]:
    if analysis is None:
        return ()
    row = analysis.facts.exact_next_stock_row
    values = []
    for column, incoming in enumerate(row):
        top = state.columns[column].top()
        if top is None:
            relation = "empty"
        elif top.rank - 1 == incoming.rank and top.suit == incoming.suit:
            relation = "same-suit"
        elif top.rank - 1 == incoming.rank:
            relation = "mixed-rank"
        else:
            relation = "non-connecting"
        values.append((column, incoming.suit, incoming.rank, relation))
    return tuple(values)


def build_pre_foundation_geometry(
    state: SpiderState,
    *,
    g: int,
    analysis: Optional[EconomicAnalysisResult] = None,
    measurement: Optional[StructuralMeasurement] = None,
    campaign_hint: Optional[str] = None,
) -> PreFoundationGeometry:
    if state.foundations:
        raise ValueError("pre-foundation geometry requires zero foundations")
    primary = analysis.campaign_portfolio.primary if analysis is not None else None
    campaign = campaign_hint or (primary.label if primary is not None else None)
    readiness_rank = 9
    estimate = float("inf")
    if primary is not None:
        readiness_rank = {
            "ready_now": 0,
            "assembly_led": 1,
            "excavation_led": 2,
            "stock_gated": 3,
            "deferred": 4,
            "blocked": 5,
        }[primary.readiness.value]
        estimate = primary.estimated_campaign_cost
    face_down = (
        measurement.face_down_count
        if measurement is not None
        else sum(len(column.face_down) for column in state.columns)
    )
    dependency = (
        measurement.critical_dependencies_pending
        if measurement is not None
        else face_down
    )
    stable = measurement.stable_same_suit_joins if measurement is not None else sum(
        lower.suit == upper.suit and lower.rank - 1 == upper.rank
        for column in state.columns
        for lower, upper in zip(column.face_up, column.face_up[1:])
    )
    empties = tuple(index for index, column in enumerate(state.columns) if column.is_empty())
    open_columns = tuple(
        index
        for index, column in enumerate(state.columns)
        if column.face_up and not column.face_down
    )
    tops = tuple(
        (column.top().suit, column.top().rank) if column.top() is not None else None
        for column in state.columns
    )
    debt = measurement.rehandling_debt if measurement is not None else float(
        sum(len(items) for items in _mixed_topology(state))
    )
    stock_epoch = 5 - len(state.stock) // 10
    return PreFoundationGeometry(
        state_key=canonical_state_key(state),
        g=g,
        campaign_identity=campaign,
        campaign_readiness_rank=readiness_rank,
        bounded_first_removal_estimate=estimate,
        stock_epoch=stock_epoch,
        face_down_count=face_down,
        dependency_burden=dependency,
        stable_same_suit_joins=stable,
        same_suit_run_topology=_same_suit_topology(state),
        empty_columns=empties,
        fully_open_columns=open_columns,
        exposed_top_layout=tops,
        receiver_geometry=_receiver_geometry(state, analysis),
        mixed_boundary_topology=_mixed_topology(state),
        rehandling_debt=debt,
    )


def _dimension_key(profile: PreFoundationGeometry, dimension: PreFoundationDimension) -> Tuple:
    if dimension == PreFoundationDimension.BEST_REMOVAL_READINESS:
        return (
            profile.campaign_readiness_rank,
            profile.bounded_first_removal_estimate,
            profile.dependency_burden,
            profile.g,
        )
    if dimension == PreFoundationDimension.BEST_PERMANENT_STRUCTURE:
        return (-profile.stable_same_suit_joins, profile.rehandling_debt, profile.g)
    if dimension == PreFoundationDimension.LOWEST_REHANDLING_LIABILITY:
        return (profile.rehandling_debt, -len(profile.empty_columns), profile.g)
    if dimension == PreFoundationDimension.BEST_REVEAL_DEPENDENCY_GEOMETRY:
        return (profile.dependency_burden, profile.face_down_count, profile.g)
    if dimension == PreFoundationDimension.ALTERNATE_CAMPAIGN:
        return (
            profile.campaign_identity is None,
            profile.campaign_identity or "",
            profile.campaign_readiness_rank,
            profile.g,
        )
    useful = sum(item[3] in ("same-suit", "mixed-rank", "empty") for item in profile.receiver_geometry)
    return (-useful, profile.stock_epoch, profile.receiver_geometry, profile.g)


def retain_pre_foundation_portfolio(
    profiles: Iterable[PreFoundationGeometry],
    *,
    maximum: int = 6,
) -> PreFoundationPortfolio:
    if not 3 <= maximum <= 6:
        raise ValueError("pre-foundation portfolio maximum must be between three and six")
    exact = {}
    exact_suppressions = 0
    for profile in profiles:
        previous = exact.get(profile.state_key)
        if previous is None or profile.g < previous.g:
            if previous is not None:
                exact_suppressions += 1
            exact[profile.state_key] = profile
        else:
            exact_suppressions += 1
    by_geometry = {}
    geometry_suppressions = 0
    for profile in exact.values():
        key = profile.geometry_key()
        previous = by_geometry.get(key)
        if previous is None or profile.g < previous.g:
            if previous is not None:
                geometry_suppressions += 1
            by_geometry[key] = profile
        else:
            geometry_suppressions += 1
    candidates = tuple(
        sorted(
            by_geometry.values(),
            key=lambda item: (
                item.campaign_readiness_rank,
                item.bounded_first_removal_estimate,
                item.dependency_burden,
                item.g,
                repr(item.geometry_key()),
            ),
        )
    )
    selected = []
    represented = []
    for dimension in PreFoundationDimension:
        if not candidates:
            break
        winner = min(candidates, key=lambda item: _dimension_key(item, dimension))
        represented.append((dimension, winner.geometry_key()))
        if winner not in selected:
            selected.append(winner)
        if len(selected) >= maximum:
            break
    for candidate in candidates:
        if candidate not in selected:
            selected.append(candidate)
        if len(selected) >= maximum:
            break
    return PreFoundationPortfolio(
        geometries=tuple(selected),
        represented_dimensions=tuple(represented),
        exact_state_suppressions=exact_suppressions,
        geometry_suppressions=geometry_suppressions + max(0, len(candidates) - len(selected)),
        maximum=maximum,
    )
