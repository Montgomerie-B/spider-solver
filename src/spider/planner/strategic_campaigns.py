"""Generic strategic campaigns generated from StrategicAnalysis (Sprint 1J).

Campaigns group related atomic objectives so the planner can reanalyse and
pursue several shallow steps in one epoch. No deal-number, suit, or column
constants in selection policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.planner.space_lifecycle import empty_count
from spider.planner.strategic_analysis import StrategicAnalysis, analyze_strategic
from spider.planner.strategic_objectives import (
    ObjectiveKind,
    StrategicObjective,
    generate_objective_portfolio,
)


class CampaignKind(str, Enum):
    ACCESS = "ACCESS"
    WORKSPACE_EXPLOIT = "WORKSPACE_EXPLOIT"
    FOUNDATION_BUILD = "FOUNDATION_BUILD"
    STOCK_PREP = "STOCK_PREP"


@dataclass(frozen=True)
class StrategicCampaign:
    kind: CampaignKind
    campaign_id: str
    description: str
    # Soft focus — not hard-coded identities
    focus_column: Optional[int]
    focus_suit: Optional[str]
    reason: str
    heuristic_priority: float


def generate_campaigns(
    state: SpiderState,
    *,
    analysis: Optional[StrategicAnalysis] = None,
    cards=None,
    max_campaigns: int = 6,
) -> Tuple[StrategicCampaign, ...]:
    """Build a small diverse campaign set from current analysis."""
    if analysis is None:
        analysis = analyze_strategic(state, cards=cards, run_shaping_probe=False)
    out: List[StrategicCampaign] = []

    # ACCESS: best reveal columns by 1B interest (shallow first)
    if analysis.reveal is not None:
        best_col: dict = {}
        for opp in analysis.reveal.opportunities:
            col = opp.prefix.column
            prev = best_col.get(col)
            if prev is None or opp.heuristic_interest > prev.heuristic_interest:
                best_col[col] = opp
        ranked = sorted(
            best_col.values(),
            key=lambda o: (-o.heuristic_interest, o.prefix.unavoidable_reveal_count),
        )
        for opp in ranked[:2]:
            col = opp.prefix.column
            seq = " -> ".join(str(c) for c in opp.prefix.cards_unlocked[:4])
            out.append(
                StrategicCampaign(
                    kind=CampaignKind.ACCESS,
                    campaign_id=f"access_c{col + 1}",
                    description=f"Sustained excavation of col {col + 1}: {seq}",
                    focus_column=col,
                    focus_suit=None,
                    reason=(
                        f"1B interest={opp.heuristic_interest} "
                        f"depth={opp.prefix.unavoidable_reveal_count}"
                    ),
                    heuristic_priority=opp.heuristic_interest,
                )
            )

    # WORKSPACE_EXPLOIT
    empties = empty_count(state)
    out.append(
        StrategicCampaign(
            kind=CampaignKind.WORKSPACE_EXPLOIT,
            campaign_id="workspace_exploit",
            description=(
                "Create workspace then spend it on reveals/consolidations"
                if empties == 0
                else "Use existing workspace productively"
            ),
            focus_column=None,
            focus_suit=None,
            reason=f"fact: empty_count={empties}",
            heuristic_priority=80.0 if empties == 0 else 50.0,
        )
    )

    # FOUNDATION_BUILD: pick from current 1A frontier (generic)
    if analysis.foundation is not None:
        cands = [
            c
            for c in analysis.foundation.frontier.candidates
            if not c.already_completed
        ]
        cands.sort(
            key=lambda c: (
                -c.heuristic_removal_readiness
                if c.theoretically_available
                else 0.0,
                -c.heuristic_build_readiness,
                c.earliest_epoch if c.earliest_epoch is not None else 99,
                c.suit,
                c.copy_index,
            )
        )
        for c in cands[:2]:
            why = []
            if c.theoretically_available:
                why.append("theoretically available now")
            why.append(f"build={c.heuristic_build_readiness:.0f}")
            why.append(f"removal={c.heuristic_removal_readiness:.0f}")
            why.append(f"fragment={c.longest_same_suit_fragment}")
            out.append(
                StrategicCampaign(
                    kind=CampaignKind.FOUNDATION_BUILD,
                    campaign_id=f"foundation_{c.suit}{c.copy_index}",
                    description=(
                        f"Build {c.suit.upper()}#{c.copy_index} from current frontier"
                    ),
                    focus_column=None,
                    focus_suit=c.suit,
                    reason="; ".join(why),
                    heuristic_priority=(
                        c.heuristic_removal_readiness
                        + c.heuristic_build_readiness
                        + (20.0 if c.theoretically_available else 0.0)
                    ),
                )
            )

    # STOCK_PREP
    if analysis.stock_reception.can_deal:
        ss = analysis.stock_reception.row_summary.n_same_suit_landings
        out.append(
            StrategicCampaign(
                kind=CampaignKind.STOCK_PREP,
                campaign_id="stock_prep",
                description="Improve receivers for the known next stock row",
                focus_column=None,
                focus_suit=None,
                reason=f"fact: current same-suit landings={ss}",
                heuristic_priority=30.0 + 5.0 * (3 - min(3, ss)),
            )
        )

    # Diversity: one of each kind first, then priority
    seen = set()
    diverse: List[StrategicCampaign] = []
    for kind in CampaignKind:
        for c in out:
            if c.kind == kind and c.campaign_id not in seen:
                diverse.append(c)
                seen.add(c.campaign_id)
                break
    rest = sorted(
        [c for c in out if c.campaign_id not in seen],
        key=lambda c: -c.heuristic_priority,
    )
    diverse.extend(rest)
    return tuple(diverse[:max_campaigns])


def campaign_subobjectives(
    state: SpiderState,
    campaign: StrategicCampaign,
    *,
    analysis: Optional[StrategicAnalysis] = None,
    cards=None,
) -> Tuple[StrategicObjective, ...]:
    """Filter/order the current portfolio for this campaign."""
    port = generate_objective_portfolio(
        state, analysis=analysis, cards=cards, max_objectives=12
    )
    picked: List[StrategicObjective] = []

    def add(o: StrategicObjective) -> None:
        if o.kind == ObjectiveKind.DEAL_NOW:
            return
        if o.objective_id not in {x.objective_id for x in picked}:
            picked.append(o)

    if campaign.kind == CampaignKind.ACCESS:
        col = campaign.focus_column
        for o in port.objectives:
            if o.kind != ObjectiveKind.EXPOSE_REVEAL_PREFIX:
                continue
            if col is not None and o.target_params.get("column") != col:
                continue
            # Prefer shallow
            if int(o.target_params.get("required_reveals", 99)) > 2:
                continue
            add(o)
        # allow workspace if it helps access
        for o in port.objectives:
            if o.kind == ObjectiveKind.CREATE_WORKSPACE:
                add(o)

    elif campaign.kind == CampaignKind.WORKSPACE_EXPLOIT:
        empties = empty_count(state)
        if empties == 0:
            for o in port.objectives:
                if o.kind == ObjectiveKind.CREATE_WORKSPACE:
                    add(o)
        for o in port.objectives:
            if o.kind in (
                ObjectiveKind.EXPOSE_REVEAL_PREFIX,
                ObjectiveKind.CONSOLIDATE_SAME_SUIT,
                ObjectiveKind.ADVANCE_FOUNDATION,
            ):
                if o.kind == ObjectiveKind.EXPOSE_REVEAL_PREFIX:
                    if int(o.target_params.get("required_reveals", 99)) > 3:
                        continue
                add(o)

    elif campaign.kind == CampaignKind.FOUNDATION_BUILD:
        suit = campaign.focus_suit
        for o in port.objectives:
            if o.kind == ObjectiveKind.REMOVE_FOUNDATION:
                if suit and o.target_params.get("suit") == suit:
                    add(o)
            if o.kind == ObjectiveKind.ADVANCE_FOUNDATION:
                if suit and o.target_params.get("suit") == suit:
                    add(o)
            if o.kind == ObjectiveKind.CONSOLIDATE_SAME_SUIT:
                if suit and o.target_params.get("suit") == suit:
                    add(o)
            if o.kind == ObjectiveKind.EXPOSE_REVEAL_PREFIX:
                if int(o.target_params.get("required_reveals", 99)) <= 2:
                    add(o)
        for o in port.objectives:
            if o.kind == ObjectiveKind.CREATE_WORKSPACE:
                add(o)

    elif campaign.kind == CampaignKind.STOCK_PREP:
        for o in port.objectives:
            if o.kind == ObjectiveKind.SHAPE_STOCK_RECEIVER:
                add(o)
        for o in port.objectives:
            if o.kind == ObjectiveKind.CREATE_WORKSPACE:
                add(o)

    return tuple(picked)
