"""Generic strategic campaigns generated from StrategicAnalysis (Sprints 1J–1K).

Campaigns group related atomic objectives so the planner can reanalyse and
pursue several shallow steps in one epoch. No deal-number, suit, or column
constants in selection policy.

Sprint 1K: ACCESS tries several ranked reveal columns with fallback;
FOUNDATION_BUILD stays suit-specific; WORKSPACE_EXPLOIT cannot degenerate
into a generic reveal campaign.
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


def _column_interest(analysis: Optional[StrategicAnalysis], col: int) -> float:
    if analysis is None or analysis.reveal is None:
        return 0.0
    best = 0.0
    for opp in analysis.reveal.opportunities:
        if opp.prefix.column == col:
            best = max(best, float(opp.heuristic_interest))
    return best


def foundation_candidate_is_actionable(cand) -> bool:
    """True when a 1A candidate has real suit-specific work, not a label.

    Heuristic gate for *generation* only. Not a proof prune.
    """
    if cand.already_completed:
        return False
    if cand.theoretically_available:
        return True
    if cand.longest_same_suit_fragment >= 2:
        return True
    if cand.heuristic_removal_readiness > 0:
        return True
    return False


def objective_is_suit_relevant(
    obj: StrategicObjective,
    suit: str,
    state: SpiderState,
    analysis: Optional[StrategicAnalysis] = None,
) -> bool:
    """Whether ``obj`` is genuinely about ``suit`` (duplicates interchangeable)."""
    if obj.kind == ObjectiveKind.DEAL_NOW:
        return False
    params = obj.target_params or {}
    if params.get("suit") == suit:
        return True
    if obj.kind in (
        ObjectiveKind.REMOVE_FOUNDATION,
        ObjectiveKind.ADVANCE_FOUNDATION,
        ObjectiveKind.CONSOLIDATE_SAME_SUIT,
    ):
        return params.get("suit") == suit
    if obj.kind == ObjectiveKind.EXPOSE_REVEAL_PREFIX:
        col = params.get("column")
        if col is None or col < 0 or col >= len(state.columns):
            return False
        pile = state.columns[col]
        if any(c.suit == suit for c in pile.face_down):
            return True
        if analysis is not None and analysis.reveal is not None:
            for opp in analysis.reveal.opportunities:
                if opp.prefix.column != col:
                    continue
                if any(c.suit == suit for c in opp.prefix.cards_unlocked):
                    return True
                if any(
                    getattr(t, "code", "").startswith("foundation")
                    and suit in str(t).lower()
                    for t in opp.prefix.structural_tags
                ):
                    return True
        return False
    if obj.kind == ObjectiveKind.SHAPE_STOCK_RECEIVER:
        if params.get("suit") == suit:
            return True
        col = params.get("column")
        if analysis is None or analysis.stock_reception is None:
            return False
        for inc in analysis.stock_reception.incoming_row:
            if inc.column == col and inc.card.suit == suit:
                return True
        for t in analysis.stock_reception.receiver_targets:
            if t.column == col and t.incoming.suit == suit:
                return True
        return False
    return False


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

    # ACCESS: one multi-column excavation campaign (fallback inside realizer)
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
        if ranked:
            top = ranked[0]
            ranked_txt = ", ".join(
                f"c{o.prefix.column + 1}({o.heuristic_interest:.0f}/d{o.prefix.unavoidable_reveal_count})"
                for o in ranked[:4]
            )
            out.append(
                StrategicCampaign(
                    kind=CampaignKind.ACCESS,
                    campaign_id="access",
                    description=(
                        "Sustained excavation with fallback across ranked "
                        f"reveal columns: {ranked_txt}"
                    ),
                    focus_column=top.prefix.column,
                    focus_suit=None,
                    reason=f"1B ranked {ranked_txt}",
                    heuristic_priority=float(top.heuristic_interest),
                )
            )

    # WORKSPACE_EXPLOIT — generated even if later blocked (diagnostic)
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

    # FOUNDATION_BUILD: only when a candidate has real suit-specific work
    if analysis.foundation is not None:
        cands = [
            c
            for c in analysis.foundation.frontier.candidates
            if foundation_candidate_is_actionable(c)
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
    max_access_candidates: int = 5,
    prefer_open_completion: bool = False,
) -> Tuple[StrategicObjective, ...]:
    """Filter/order the current portfolio for this campaign."""
    port = generate_objective_portfolio(
        state, analysis=analysis, cards=cards, max_objectives=16
    )
    if analysis is None:
        analysis = analyze_strategic(state, cards=cards, run_shaping_probe=False)
    picked: List[StrategicObjective] = []

    def add(o: StrategicObjective) -> None:
        if o.kind == ObjectiveKind.DEAL_NOW:
            return
        if o.objective_id not in {x.objective_id for x in picked}:
            picked.append(o)

    if campaign.kind == CampaignKind.ACCESS:
        exposes = [
            o
            for o in port.objectives
            if o.kind == ObjectiveKind.EXPOSE_REVEAL_PREFIX
            and int(o.target_params.get("required_reveals", 99)) <= 2
        ]
        def _access_key(o: StrategicObjective):
            col = int(o.target_params.get("column", -1))
            interest = _column_interest(analysis, col)
            req = int(o.target_params.get("required_reveals", 99))
            # Secondary heuristic only: among comparable interest, prefer
            # a column closer to becoming fully open. Never overrides interest.
            remain_fd = 99
            if prefer_open_completion and 0 <= col < len(state.columns):
                remain_fd = len(state.columns[col].face_down)
            return (-interest, req, remain_fd if prefer_open_completion else 0, col)

        exposes.sort(key=_access_key)
        # Keep a small ranked set; several columns, shallow first within a col
        seen_cols = []
        for o in exposes:
            col = o.target_params.get("column")
            if col not in seen_cols:
                if len(seen_cols) >= max_access_candidates:
                    continue
                seen_cols.append(col)
            # allow the shallow (and at most one extra) for each kept column
            n_for_col = sum(
                1 for x in picked if x.target_params.get("column") == col
            )
            if n_for_col >= 2:
                continue
            add(o)
        # workspace is a helper after ranked reveals, not a replacement
        if empty_count(state) == 0:
            for o in port.objectives:
                if o.kind == ObjectiveKind.CREATE_WORKSPACE:
                    add(o)

    elif campaign.kind == CampaignKind.WORKSPACE_EXPLOIT:
        empties = empty_count(state)
        if empties == 0:
            # Must create first. Do not silently become a generic reveal campaign.
            for o in port.objectives:
                if o.kind == ObjectiveKind.CREATE_WORKSPACE:
                    add(o)
        else:
            for o in port.objectives:
                if o.kind in (
                    ObjectiveKind.EXPOSE_REVEAL_PREFIX,
                    ObjectiveKind.CONSOLIDATE_SAME_SUIT,
                    ObjectiveKind.ADVANCE_FOUNDATION,
                ):
                    if o.kind == ObjectiveKind.EXPOSE_REVEAL_PREFIX:
                        if int(o.target_params.get("required_reveals", 99)) > 2:
                            continue
                    add(o)

    elif campaign.kind == CampaignKind.FOUNDATION_BUILD:
        suit = campaign.focus_suit
        if not suit:
            return ()
        for o in port.objectives:
            if o.kind == ObjectiveKind.DEAL_NOW:
                continue
            if o.kind == ObjectiveKind.CREATE_WORKSPACE:
                continue
            if not objective_is_suit_relevant(o, suit, state, analysis):
                continue
            if o.kind == ObjectiveKind.EXPOSE_REVEAL_PREFIX:
                if int(o.target_params.get("required_reveals", 99)) > 2:
                    continue
            add(o)

    elif campaign.kind == CampaignKind.STOCK_PREP:
        for o in port.objectives:
            if o.kind == ObjectiveKind.SHAPE_STOCK_RECEIVER:
                add(o)

    return tuple(picked)
