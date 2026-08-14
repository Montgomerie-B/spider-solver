"""Sequential campaign execution via repeated shallow objective realisation.

Sprint 1K: ACCESS falls through blocked reveal columns; semantic integrity
per campaign kind; zero-progress results stay out of the productive frontier.
Reanalyse after every successful sub-objective. Never deals. A miss/resource
limit is not impossibility and is not proof pruning.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.state_identity import CanonicalStateKey, canonical_state_key
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
    objective_is_suit_relevant,
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
    focus_column: Optional[int] = None
    fallback: bool = False


@dataclass
class CampaignResult:
    campaign: StrategicCampaign
    status: str
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
    fallbacks_tried: int = 0
    resource_count: int = 0
    miss_count: int = 0
    productive_steps: int = 0
    focus_history: Tuple[int, ...] = ()
    access_focus_changes: int = 0

    @property
    def fd_reduction(self) -> int:
        return self.start_face_down - self.end_face_down

    @property
    def fd_per_paid(self) -> Optional[float]:
        if self.paid_cost <= 0:
            return None
        return self.fd_reduction / self.paid_cost

    @property
    def zero_progress(self) -> bool:
        return (
            self.paid_cost == 0
            and self.fd_reduction == 0
            and self.end_ss == self.start_ss
            and self.end_mass == self.start_mass
            and self.end_empty == self.start_empty
            and self.foundations_delta == 0
            and self.end_stock_ss == self.start_stock_ss
        )

    @property
    def productive(self) -> bool:
        """Heuristic: did this campaign produce kind-appropriate follow-on work?

        Creating workspace with no follow-on reveal/join/foundation does not
        count. Consuming an empty after using it still counts.
        """
        if self.zero_progress:
            return False
        used = (
            self.fd_reduction > 0
            or self.end_ss > self.start_ss
            or self.end_mass > self.start_mass
            or self.foundations_delta > 0
        )
        if self.campaign.kind == CampaignKind.ACCESS:
            return self.fd_reduction > 0
        if self.campaign.kind == CampaignKind.WORKSPACE_EXPLOIT:
            created = any(
                s.objective_kind == "CREATE_WORKSPACE" and s.status == "found"
                for s in self.steps
            )
            held = self.start_empty > 0 or self.end_empty > 0 or created
            return held and used
        if self.campaign.kind == CampaignKind.FOUNDATION_BUILD:
            return (
                self.foundations_delta > 0
                or self.end_ss > self.start_ss
                or self.end_foundation_build > self.start_foundation_build
                or self.end_foundation_removal > self.start_foundation_removal
                or self.fd_reduction > 0
            )
        if self.campaign.kind == CampaignKind.STOCK_PREP:
            return (
                self.end_stock_ss > self.start_stock_ss
                or self.end_empty > self.start_empty
            )
        return used

    @property
    def productive_return_per_move(self) -> Optional[float]:
        """HEURISTIC diagnostic: useful events / paid cost."""
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
    return result_like.productive


def realize_campaign(
    state: SpiderState,
    campaign: StrategicCampaign,
    *,
    cards=None,
    max_paid_cost: int = 10,
    max_steps: int = 16,
    tactical_max_cost: int = 4,
    tactical_max_nodes: int = 400,
    tactical_time_s: float = 0.3,
    workspace_max_cost: int = 6,
    max_access_candidates: int = 5,
    prefer_open_completion: bool = False,
) -> CampaignResult:
    """Repeatedly pick a related sub-objective and realise it cheaply.

    Strategic rank first, then a small bounded actionability probe. A blocked
    probe is not impossibility; ACCESS falls through to the next ranked
    reveal. Failed (state, objective) pairs are cached for the campaign.
    """
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
    fallbacks = 0
    resource_n = 0
    miss_n = 0
    productive_n = 0
    focus_hist: List[int] = []
    focus_changes = 0
    stop = "plateau"
    status = "plateau"
    any_progress = False
    failed_probes: Set[Tuple[CanonicalStateKey, str]] = set()
    blocked_oids: Set[str] = set()
    last_empty = e0

    while paid < max_paid_cost and len([s for s in steps if s.status == "found"]) < max_steps:
        analysis = analyze_strategic(st, cards=cards, run_shaping_probe=False)
        if empty_count(st) != last_empty:
            blocked_oids.clear()
            last_empty = empty_count(st)
        subs = campaign_subobjectives(
            st,
            campaign,
            analysis=analysis,
            cards=cards,
            max_access_candidates=max_access_candidates,
            prefer_open_completion=prefer_open_completion,
        )
        if not subs:
            stop = "no_relevant_subobjective"
            status = "zero_progress" if not any_progress else "plateau"
            break
        key = canonical_state_key(st)
        progressed = False
        tried_this_round = 0
        res_this_round = 0
        miss_this_round = 0
        for obj in subs:
            remaining = max_paid_cost - paid
            if remaining <= 0:
                break
            if (key, obj.objective_id) in failed_probes:
                continue
            if obj.objective_id in blocked_oids:
                continue
            if obj.kind.value == "CREATE_WORKSPACE":
                bound = min(workspace_max_cost, remaining)
            else:
                bound = min(tactical_max_cost, remaining)
            attempted += 1
            tried_this_round += 1
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
            col = obj.target_params.get("column") if obj.target_params else None
            if res.status == RealizationStatus.RESOURCE_LIMIT:
                resource_n += 1
                res_this_round += 1
                failed_probes.add((key, obj.objective_id))
                blocked_oids.add(obj.objective_id)
                fallbacks += 1
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
                        focus_column=col,
                        fallback=True,
                    )
                )
                continue
            if res.status != RealizationStatus.FOUND:
                miss_n += 1
                miss_this_round += 1
                failed_probes.add((key, obj.objective_id))
                blocked_oids.add(obj.objective_id)
                fallbacks += 1
                continue
            cost = int(res.corrected_mw_cost or 0)
            if paid + cost > max_paid_cost:
                miss_n += 1
                miss_this_round += 1
                failed_probes.add((key, obj.objective_id))
                continue
            if any(_is_deal_action(a) for a in res.actions):
                miss_n += 1
                failed_probes.add((key, obj.objective_id))
                blocked_oids.add(obj.objective_id)
                continue
            if (
                campaign.kind == CampaignKind.FOUNDATION_BUILD
                and campaign.focus_suit
                and not objective_is_suit_relevant(
                    obj, campaign.focus_suit, st, analysis
                )
            ):
                miss_n += 1
                failed_probes.add((key, obj.objective_id))
                blocked_oids.add(obj.objective_id)
                continue
            chk = st.clone()
            recost = replay_actions(chk, list(res.actions))
            if recost != cost or not obj.is_satisfied(chk):
                miss_n += 1
                miss_this_round += 1
                failed_probes.add((key, obj.objective_id))
                blocked_oids.add(obj.objective_id)
                continue
            st = chk
            paid += cost
            actions.extend(res.actions)
            ss_now, _ = _longest_and_mass(st)
            if col is not None:
                if focus_hist and focus_hist[-1] != col:
                    focus_changes += 1
                focus_hist.append(int(col))
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
                    focus_column=col,
                    fallback=tried_this_round > 1,
                )
            )
            productive_n += 1
            progressed = True
            any_progress = True
            break
        if not progressed:
            if not any_progress:
                if tried_this_round == 0 and attempted == 0:
                    stop = "no_relevant_subobjective"
                elif res_this_round > 0 and miss_this_round == 0:
                    stop = "resource_limit"
                else:
                    stop = "all_candidates_blocked"
                status = "zero_progress"
            else:
                stop = "plateau"
                status = "plateau"
            break
    else:
        if paid >= max_paid_cost or productive_n >= max_steps:
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
        fallbacks_tried=fallbacks,
        resource_count=resource_n,
        miss_count=miss_n,
        productive_steps=productive_n,
        focus_history=tuple(focus_hist),
        access_focus_changes=focus_changes,
    )
    if result.zero_progress:
        result.status = "zero_progress"
        if result.stop_reason in ("plateau", "budget"):
            if attempted == 0:
                result.stop_reason = "no_relevant_subobjective"
            else:
                result.stop_reason = "all_candidates_blocked"
    elif any_progress and _campaign_success(campaign, result):
        if result.status in ("plateau", "budget", "zero_progress"):
            result.status = "success"
            if stop in ("budget",):
                result.stop_reason = "budget"
            else:
                result.stop_reason = "success"
    elif any_progress and not _campaign_success(campaign, result):
        # e.g. workspace created but never used
        result.status = "plateau"
        if result.stop_reason in ("success", "zero_progress"):
            result.stop_reason = "plateau"
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


def productive_campaign_results(
    results: Sequence[CampaignResult],
) -> Tuple[CampaignResult, ...]:
    return tuple(r for r in results if r.productive and not r.zero_progress)


def pareto_campaign_results(
    results: Sequence[CampaignResult],
) -> Tuple[CampaignResult, ...]:
    """Non-dominated *productive* results on cost / excavation / structure."""
    pool = list(productive_campaign_results(results))
    if not pool:
        return ()
    kept: List[CampaignResult] = []
    for a in pool:
        dominated = False
        for b in pool:
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
    pool = list(productive_campaign_results(results))
    if not pool:
        return ()
    picks: List[CampaignResult] = []

    def add(r: CampaignResult) -> None:
        rid = (r.campaign.campaign_id, r.paid_cost, r.end_face_down, r.end_ss)
        if rid not in {
            (p.campaign.campaign_id, p.paid_cost, p.end_face_down, p.end_ss)
            for p in picks
        }:
            picks.append(r)

    add(min(pool, key=lambda r: (r.paid_cost, r.end_face_down)))
    add(min(pool, key=lambda r: (r.end_face_down, r.paid_cost)))
    with_cost = [r for r in pool if r.paid_cost > 0]
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
    add(max(pool, key=lambda r: (r.end_ss, r.end_mass, -r.paid_cost)))
    add(
        max(
            pool,
            key=lambda r: (
                r.end_foundation_removal,
                r.end_foundation_build,
                r.foundations_delta,
                -r.paid_cost,
            ),
        )
    )
    add(
        max(
            pool,
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
    productive: Tuple[CampaignResult, ...] = ()
    blocked: Tuple[CampaignResult, ...] = ()
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
    prod = productive_campaign_results(tup)
    blocked = tuple(r for r in tup if r.zero_progress or not r.productive)
    return CampaignFrontier(
        results=tup,
        pareto=pareto_campaign_results(tup),
        stratified=stratify_campaign_results(tup),
        productive=prod,
        blocked=blocked,
        mix=mix,
        elapsed_seconds=time.time() - t0,
        nodes_expanded=sum(r.nodes_expanded for r in results),
    )
