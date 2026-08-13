"""Sequential campaign execution via repeated shallow objective realisation.

Reanalyse after every successful sub-objective. Never deals. A miss/resource
limit is not impossibility.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.planner.lower_bounds import count_face_down
from spider.planner.objective_realizer import (
    Action,
    RealizationMode,
    RealizationStatus,
    realize_objective,
)
from spider.planner.space_lifecycle import empty_count
from spider.planner.strategic_analysis import StrategicAnalysis, analyze_strategic
from spider.planner.strategic_campaigns import (
    CampaignKind,
    StrategicCampaign,
    campaign_subobjectives,
    generate_campaigns,
)
from spider.planner.plan_search_v2 import _longest_and_mass


@dataclass
class CampaignStep:
    objective_id: str
    objective_kind: str
    status: str
    cost: int
    actions: Tuple[Action, ...]
    face_down_after: int
    empty_after: int
    ss_after: int


@dataclass
class CampaignResult:
    campaign: StrategicCampaign
    status: str  # success / plateau / budget / resource_limit / already
    paid_cost: int
    actions: Tuple[Action, ...]
    steps: Tuple[CampaignStep, ...]
    start_face_down: int
    end_face_down: int
    start_empty: int
    end_empty: int
    start_ss: int
    end_ss: int
    start_mass: int
    end_mass: int
    foundations_delta: int
    start_stock_ss: int
    end_stock_ss: int
    start_foundation_build: float
    end_foundation_build: float
    start_foundation_removal: float
    end_foundation_removal: float
    selected_foundation: Optional[str]
    stop_reason: str
    elapsed_seconds: float
    realizations_attempted: int
    nodes_expanded: int
    replay_verified: bool

    @property
    def fd_reduction(self) -> int:
        return self.start_face_down - self.end_face_down

    @property
    def fd_per_paid(self) -> Optional[float]:
        if self.paid_cost <= 0:
            return None
        return self.fd_reduction / self.paid_cost

    @property
    def productive(self) -> bool:
        """Heuristic: did workspace/access produce useful follow-on work?

        Consuming an empty after using it still counts as productive.
        Creating workspace with no follow-on reveal/join/foundation does not.
        """
        used = (
            self.fd_reduction > 0
            or self.end_ss > self.start_ss
            or self.end_mass > self.start_mass
            or self.foundations_delta > 0
        )
        if self.campaign.kind == CampaignKind.WORKSPACE_EXPLOIT:
            created = any(
                s.objective_kind == "CREATE_WORKSPACE" and s.status == "found"
                for s in self.steps
            )
            held = self.end_empty > 0 or self.end_empty > self.start_empty
            return (created or held) and used
        return used

    @property
    def productive_return_per_move(self) -> Optional[float]:
        """HEURISTIC diagnostic: useful events / paid cost.

        Useful events = face-down reductions + same-suit gains + foundation
        removals. Workspace creation alone does not count.
        """
        if self.paid_cost <= 0:
            return None
        useful = (
            max(0, self.fd_reduction)
            + max(0, self.end_ss - self.start_ss)
            + max(0, self.foundations_delta)
        )
        return useful / self.paid_cost


def _foundations_n(state: SpiderState) -> int:
    return sum(1 for s in state.foundations if len(s) == 13)


def _stock_ss(analysis: StrategicAnalysis) -> int:
    return int(analysis.stock_reception.row_summary.n_same_suit_landings)


def _foundation_scores(
    analysis: StrategicAnalysis, *, prefer_suit: Optional[str] = None
) -> Tuple[float, float, Optional[str]]:
    if analysis.foundation is None:
        return 0.0, 0.0, None
    cands = [
        c
        for c in analysis.foundation.frontier.candidates
        if not c.already_completed
    ]
    if prefer_suit:
        suited = [c for c in cands if c.suit == prefer_suit]
        if suited:
            cands = suited
    if not cands:
        return 0.0, 0.0, None
    c = max(
        cands,
        key=lambda x: (
            x.heuristic_removal_readiness if x.theoretically_available else 0.0,
            x.heuristic_build_readiness,
            -x.copy_index,
        ),
    )
    return (
        float(c.heuristic_build_readiness),
        float(c.heuristic_removal_readiness),
        c.label,
    )


def _is_deal_action(action: Action) -> bool:
    return action == ("deal",) or (
        isinstance(action, tuple) and len(action) == 1 and action[0] == "deal"
    )


def _campaign_success(campaign: StrategicCampaign, result_like: CampaignResult) -> bool:
    """Workspace creation alone is not a successful investment."""
    if campaign.kind == CampaignKind.WORKSPACE_EXPLOIT:
        return result_like.productive
    if campaign.kind == CampaignKind.STOCK_PREP:
        return (
            result_like.end_stock_ss > result_like.start_stock_ss
            or result_like.fd_reduction > 0
            or result_like.end_ss > result_like.start_ss
            or result_like.end_empty > result_like.start_empty
        )
    return (
        result_like.fd_reduction > 0
        or result_like.end_ss > result_like.start_ss
        or result_like.foundations_delta > 0
    )


def realize_campaign(
    state: SpiderState,
    campaign: StrategicCampaign,
    *,
    cards=None,
    max_paid_cost: int = 10,
    max_steps: int = 8,
    tactical_max_cost: int = 4,
    tactical_max_nodes: int = 400,
    tactical_time_s: float = 0.3,
    workspace_max_cost: int = 6,
) -> CampaignResult:
    """Repeatedly pick a related sub-objective and realise it cheaply."""
    t0 = time.time()
    st = state.clone()
    analysis0 = analyze_strategic(st, cards=cards, run_shaping_probe=False)
    fd0 = count_face_down(st)
    e0 = empty_count(st)
    ss0, mass0 = _longest_and_mass(st)
    f0 = _foundations_n(st)
    stock0 = _stock_ss(analysis0)
    fb0, fr0, flabel0 = _foundation_scores(
        analysis0, prefer_suit=campaign.focus_suit
    )
    actions: List[Action] = []
    steps: List[CampaignStep] = []
    paid = 0
    attempted = 0
    nodes = 0
    fail_streak = 0
    stop = "plateau"
    status = "plateau"
    any_progress = False

    while paid < max_paid_cost and len(steps) < max_steps:
        analysis = analyze_strategic(st, cards=cards, run_shaping_probe=False)
        subs = campaign_subobjectives(st, campaign, analysis=analysis, cards=cards)
        if not subs:
            stop = "plateau"
            status = "plateau"
            break
        progressed = False
        for obj in subs:
            remaining = max_paid_cost - paid
            if remaining <= 0:
                break
            if obj.kind.value == "CREATE_WORKSPACE":
                bound = min(workspace_max_cost, remaining)
            else:
                bound = min(tactical_max_cost, remaining)
            attempted += 1
            res = realize_objective(
                st,
                obj,
                mode=RealizationMode.EXACT_BOUNDED,
                max_cost=bound,
                max_nodes=tactical_max_nodes,
                time_limit_s=tactical_time_s,
            )
            nodes += int(getattr(res, "nodes_expanded", 0) or 0)
            if res.status == RealizationStatus.ALREADY_SATISFIED:
                continue
            if res.status == RealizationStatus.RESOURCE_LIMIT:
                steps.append(
                    CampaignStep(
                        obj.objective_id,
                        obj.kind.value,
                        res.status.value,
                        0,
                        (),
                        count_face_down(st),
                        empty_count(st),
                        _longest_and_mass(st)[0],
                    )
                )
                fail_streak += 1
                continue
            if res.status != RealizationStatus.FOUND:
                fail_streak += 1
                continue
            cost = int(res.corrected_mw_cost or 0)
            if paid + cost > max_paid_cost:
                fail_streak += 1
                continue
            if any(_is_deal_action(a) for a in res.actions):
                fail_streak += 1
                continue
            chk = st.clone()
            recost = replay_actions(chk, list(res.actions))
            if recost != cost or not obj.is_satisfied(chk):
                fail_streak += 1
                continue
            st = chk
            paid += cost
            actions.extend(res.actions)
            ss_now, _ = _longest_and_mass(st)
            steps.append(
                CampaignStep(
                    obj.objective_id,
                    obj.kind.value,
                    "found",
                    cost,
                    tuple(res.actions),
                    count_face_down(st),
                    empty_count(st),
                    ss_now,
                )
            )
            fail_streak = 0
            progressed = True
            any_progress = True
            break
        if not progressed:
            stop = "plateau" if fail_streak < 6 else "resource_limit"
            status = stop
            break
    else:
        if paid >= max_paid_cost or len(steps) >= max_steps:
            stop = "budget"
            status = "budget"

    analysis1 = analyze_strategic(st, cards=cards, run_shaping_probe=False)
    fd1 = count_face_down(st)
    e1 = empty_count(st)
    ss1, mass1 = _longest_and_mass(st)
    f1 = _foundations_n(st)
    stock1 = _stock_ss(analysis1)
    fb1, fr1, flabel1 = _foundation_scores(
        analysis1, prefer_suit=campaign.focus_suit
    )

    # Independent full replay from original start
    verify = state.clone()
    vcost = replay_actions(verify, list(actions)) if actions else 0
    verified = vcost == paid

    result = CampaignResult(
        campaign=campaign,
        status=status,
        paid_cost=paid,
        actions=tuple(actions),
        steps=tuple(steps),
        start_face_down=fd0,
        end_face_down=fd1,
        start_empty=e0,
        end_empty=e1,
        start_ss=ss0,
        end_ss=ss1,
        start_mass=mass0,
        end_mass=mass1,
        foundations_delta=f1 - f0,
        start_stock_ss=stock0,
        end_stock_ss=stock1,
        start_foundation_build=fb0,
        end_foundation_build=fb1,
        start_foundation_removal=fr0,
        end_foundation_removal=fr1,
        selected_foundation=flabel1 or flabel0,
        stop_reason=stop,
        elapsed_seconds=time.time() - t0,
        realizations_attempted=attempted,
        nodes_expanded=nodes,
        replay_verified=verified,
    )
    if any_progress and _campaign_success(campaign, result):
        if status in ("plateau", "budget"):
            result.status = "success"
            result.stop_reason = "success"
    return result


def prefix_at_budget(
    result: CampaignResult, start: SpiderState, budget: int
) -> Tuple[int, int, int, int, int]:
    """Replay found steps until ``budget``; return (paid, fd, empty, ss, mass)."""
    st = start.clone()
    paid = 0
    for step in result.steps:
        if step.status != "found" or not step.actions:
            continue
        if paid + step.cost > budget:
            break
        paid += replay_actions(st, list(step.actions))
    ss, mass = _longest_and_mass(st)
    return paid, count_face_down(st), empty_count(st), ss, mass


def pareto_campaign_results(
    results: Sequence[CampaignResult],
) -> Tuple[CampaignResult, ...]:
    """Non-dominated results on cost / excavation / structure / foundations."""
    kept: List[CampaignResult] = []
    for a in results:
        dominated = False
        for b in results:
            if b is a:
                continue
            le = (
                b.paid_cost <= a.paid_cost
                and b.end_face_down <= a.end_face_down
                and b.end_empty >= a.end_empty
                and b.end_ss >= a.end_ss
                and b.end_mass >= a.end_mass
                and b.foundations_delta >= a.foundations_delta
                and b.end_stock_ss >= a.end_stock_ss
            )
            sl = (
                b.paid_cost < a.paid_cost
                or b.end_face_down < a.end_face_down
                or b.end_empty > a.end_empty
                or b.end_ss > a.end_ss
                or b.end_mass > a.end_mass
                or b.foundations_delta > a.foundations_delta
                or b.end_stock_ss > a.end_stock_ss
            )
            if le and sl:
                dominated = True
                break
        if not dominated:
            kept.append(a)
    return tuple(kept)


def stratify_campaign_results(
    results: Sequence[CampaignResult], *, limit: int = 6
) -> Tuple[CampaignResult, ...]:
    """Cheapest, least fd, best efficiency, best ss, best foundation, productive."""
    if not results:
        return ()
    picks: List[CampaignResult] = []

    def add(r: CampaignResult) -> None:
        rid = (r.campaign.campaign_id, r.paid_cost, r.end_face_down, r.end_ss)
        if rid not in {
            (p.campaign.campaign_id, p.paid_cost, p.end_face_down, p.end_ss)
            for p in picks
        }:
            picks.append(r)

    add(min(results, key=lambda r: (r.paid_cost, r.end_face_down)))
    add(min(results, key=lambda r: (r.end_face_down, r.paid_cost)))
    with_cost = [r for r in results if r.paid_cost > 0]
    if with_cost:
        add(
            max(
                with_cost,
                key=lambda r: (
                    r.fd_per_paid or 0.0,
                    r.productive_return_per_move or 0.0,
                    -r.paid_cost,
                ),
            )
        )
    add(max(results, key=lambda r: (r.end_ss, r.end_mass, -r.paid_cost)))
    add(
        max(
            results,
            key=lambda r: (
                r.end_foundation_removal,
                r.end_foundation_build,
                r.foundations_delta,
                -r.paid_cost,
            ),
        )
    )
    productive = [r for r in results if r.productive]
    if productive:
        add(
            max(
                productive,
                key=lambda r: (
                    r.productive_return_per_move or 0.0,
                    r.fd_reduction,
                    -r.paid_cost,
                ),
            )
        )
    return tuple(picks[:limit])


@dataclass
class CampaignFrontier:
    results: Tuple[CampaignResult, ...]
    pareto: Tuple[CampaignResult, ...]
    stratified: Tuple[CampaignResult, ...]
    mix: Dict[str, int] = field(default_factory=dict)
    elapsed_seconds: float = 0.0
    nodes_expanded: int = 0


def run_campaign_frontier(
    state: SpiderState,
    *,
    cards=None,
    max_paid_cost: int = 10,
    max_campaigns: int = 4,
    **kwargs,
) -> CampaignFrontier:
    """Run each generated campaign independently from the same start (no deal)."""
    t0 = time.time()
    campaigns = generate_campaigns(state, cards=cards, max_campaigns=max_campaigns)
    results: List[CampaignResult] = []
    for c in campaigns:
        results.append(
            realize_campaign(
                state, c, cards=cards, max_paid_cost=max_paid_cost, **kwargs
            )
        )
    mix: Dict[str, int] = {}
    for r in results:
        mix[r.campaign.kind.value] = mix.get(r.campaign.kind.value, 0) + 1
    tup = tuple(results)
    return CampaignFrontier(
        results=tup,
        pareto=pareto_campaign_results(tup),
        stratified=stratify_campaign_results(tup),
        mix=mix,
        elapsed_seconds=time.time() - t0,
        nodes_expanded=sum(r.nodes_expanded for r in results),
    )
