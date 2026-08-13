"""Plan-level objective search (Sprints 1G–1L).

1G: opening → Deal 1
1H: opening → Deal 1 → inter-deal planning → Deal 2
1L: ACCESS campaign as a cached macro-edge through Deal 3 (A/B).

Diagnostic search over strategic objectives, not a whole-game solver.
Heuristic quality is for beam/Pareto only. Admissible h is used solely when
an explicit incumbent/target is supplied (never face_down+deals).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Sequence, Set, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.state_identity import CanonicalStateKey, canonical_state_key
from spider.planner.lower_bounds import (
    compute_solution_lower_bound,
    budget_diagnostic,
    count_face_down,
)
from spider.planner.objective_realizer import (
    Action,
    RealizationMode,
    RealizationStatus,
    realize_objective,
)
from spider.planner.space_lifecycle import empty_count
from spider.planner.strategic_analysis import analyze_strategic
from spider.planner.strategic_objectives import (
    ObjectiveKind,
    ObjectivePortfolio,
    StrategicObjective,
    generate_objective_portfolio,
)
from spider.planner.strategic_campaigns import (
    CampaignKind,
    generate_campaigns,
)

EXPANDABLE = {
    ObjectiveKind.CREATE_WORKSPACE,
    ObjectiveKind.EXPOSE_REVEAL_PREFIX,
    ObjectiveKind.SHAPE_STOCK_RECEIVER,
    ObjectiveKind.CONSOLIDATE_SAME_SUIT,
    ObjectiveKind.ADVANCE_FOUNDATION,
    ObjectiveKind.REMOVE_FOUNDATION,
    ObjectiveKind.DEAL_NOW,
}

ACCESS_KIND = "ACCESS_CAMPAIGN"

EXPANDABLE_MATURE = EXPANDABLE - {ObjectiveKind.DEAL_NOW} | {
    ObjectiveKind.REMOVE_FOUNDATION,
}


@dataclass(frozen=True)
class QualityVector:
    """Transparent HARD/heuristic components. Not a proof score."""

    g: int
    face_down: int
    empty_count: int
    longest_same_suit: int
    same_suit_run_mass: int
    foundation_build_max: float
    predeal_same_suit_landings: int
    predeal_immediate_outs: int
    predeal_non_connecting: int
    foundations_removed: int = 0
    h1_theo: bool = False
    s1_theo: bool = False
    h1_build: float = 0.0
    s1_build: float = 0.0
    h1_removal: float = 0.0
    s1_removal: float = 0.0
    # Diagnostic only — never used for proof pruning or dominance.
    investment_paid: int = 0
    investment_fd: int = 0

    def investment_per_fd(self) -> Optional[float]:
        if self.investment_fd <= 0:
            return None
        return self.investment_paid / self.investment_fd

    def dominates(self, other: "QualityVector") -> bool:
        le = (
            self.g <= other.g
            and self.face_down <= other.face_down
            and self.empty_count >= other.empty_count
            and self.longest_same_suit >= other.longest_same_suit
            and self.same_suit_run_mass >= other.same_suit_run_mass
            and self.foundation_build_max >= other.foundation_build_max
            and self.predeal_same_suit_landings >= other.predeal_same_suit_landings
            and self.predeal_immediate_outs >= other.predeal_immediate_outs
            and self.predeal_non_connecting <= other.predeal_non_connecting
            and self.foundations_removed >= other.foundations_removed
        )
        sl = (
            self.g < other.g
            or self.face_down < other.face_down
            or self.empty_count > other.empty_count
            or self.longest_same_suit > other.longest_same_suit
            or self.same_suit_run_mass > other.same_suit_run_mass
            or self.foundation_build_max > other.foundation_build_max
            or self.predeal_same_suit_landings > other.predeal_same_suit_landings
            or self.predeal_immediate_outs > other.predeal_immediate_outs
            or self.predeal_non_connecting < other.predeal_non_connecting
            or self.foundations_removed > other.foundations_removed
        )
        return le and sl

    def heuristic_order_key(self) -> Tuple:
        """HEURISTIC ONLY (lower better). Never used for proof pruning."""
        return (
            -self.empty_count,
            self.face_down,
            -self.longest_same_suit,
            -self.predeal_same_suit_landings,
            self.g,  # cost last among structure keys so g=1 cannot dominate
            self.predeal_non_connecting,
            -self.same_suit_run_mass,
            -self.foundation_build_max,
        )

    def deferred_notes(self) -> Tuple[str, ...]:
        notes = []
        notes.append(f"heuristic-deferred: face_down_remaining={self.face_down}")
        if self.empty_count == 0:
            notes.append("heuristic-deferred: no workspace")
        if self.longest_same_suit < 3:
            notes.append("heuristic-deferred: weak same-suit structure")
        if self.foundation_build_max < 20:
            notes.append("heuristic-deferred: low foundation build readiness")
        return tuple(notes)


@dataclass
class PlanNode:
    state: SpiderState
    g: int
    actions: Tuple[Action, ...]
    objective_ids: Tuple[str, ...]
    objective_kinds: Tuple[str, ...]
    key: CanonicalStateKey
    deals_done: int
    epoch_depth: int  # non-deal objectives in current epoch
    quality: QualityVector
    notes: Tuple[str, ...] = ()
    added_cost: int = 0  # paid cost since a maturation seed (0 outside 1I)
    access_macros_this_epoch: int = 0
    last_access_empty: int = 0
    last_access_foundations: int = 0
    access_focus_history: Tuple[int, ...] = ()
    access_fallbacks: int = 0
    investment_paid: int = 0
    investment_fd: int = 0

    @property
    def dealt(self) -> bool:
        return self.deals_done >= 1

    @property
    def investment_per_fd(self) -> Optional[float]:
        if self.investment_fd <= 0:
            return None
        return self.investment_paid / self.investment_fd

    @property
    def objective_depth(self) -> int:
        return self.epoch_depth


@dataclass
class PlanSearchStats:
    plan_nodes: int = 0
    realizations_attempted: int = 0
    realizations_found: int = 0
    realizations_already: int = 0
    realizations_miss: int = 0
    realizations_resource: int = 0
    tt_hits: int = 0
    elapsed_seconds: float = 0.0
    families_tried: Dict[str, int] = field(default_factory=dict)
    deal1_frontier: int = 0
    deal2_frontier: int = 0
    workspace_then_expose: int = 0
    access_macros_attempted: int = 0
    access_macros_applied: int = 0
    access_macros_zero: int = 0
    access_cache_hits: int = 0
    access_paid: int = 0
    access_fd_reduced: int = 0


@dataclass
class PlanSearchResult:
    terminals: Tuple[PlanNode, ...]
    pareto_terminals: Tuple[PlanNode, ...]
    stratified_terminals: Tuple[PlanNode, ...]
    stats: PlanSearchStats
    config: Dict
    deal1_nodes: Tuple[PlanNode, ...] = ()
    deal2_nodes: Tuple[PlanNode, ...] = ()


def _longest_and_mass(state: SpiderState) -> Tuple[int, int]:
    longest = 0
    mass = 0
    for col in state.columns:
        up = col.face_up
        i = 0
        while i < len(up):
            j = i
            while (
                j + 1 < len(up)
                and up[j + 1].suit == up[j].suit
                and up[j].rank - 1 == up[j + 1].rank
            ):
                j += 1
            ln = j - i + 1
            if ln >= 2:
                longest = max(longest, ln)
                mass += ln
            i = j + 1
    return longest, mass


def _foundation_bits(analysis) -> Tuple[float, int, bool, bool, float, float, float, float]:
    build_max = 0.0
    n_found = 0
    h1_theo = s1_theo = False
    h1_b = s1_b = h1_r = s1_r = 0.0
    if analysis is None or analysis.foundation is None:
        return build_max, n_found, h1_theo, s1_theo, h1_b, s1_b, h1_r, s1_r
    n_found = sum(
        1 for c in analysis.foundation.frontier.candidates if c.already_completed
    )
    for c in analysis.foundation.frontier.candidates:
        if not c.already_completed:
            build_max = max(build_max, c.heuristic_build_readiness)
        if c.suit == "h" and c.copy_index == 1:
            h1_theo = c.theoretically_available
            h1_b = c.heuristic_build_readiness
            h1_r = c.heuristic_removal_readiness
        if c.suit == "s" and c.copy_index == 1:
            s1_theo = c.theoretically_available
            s1_b = c.heuristic_build_readiness
            s1_r = c.heuristic_removal_readiness
    return build_max, n_found, h1_theo, s1_theo, h1_b, s1_b, h1_r, s1_r


def compute_quality(
    state: SpiderState,
    g: int,
    *,
    cards: Optional[Sequence[Card]] = None,
    analysis=None,
    predeal_ss: int = 0,
    predeal_outs: int = 0,
    predeal_nc: int = 0,
) -> QualityVector:
    if analysis is None:
        analysis = analyze_strategic(state, cards=cards, run_shaping_probe=False)
    longest, mass = _longest_and_mass(state)
    bmax, nfound, h1t, s1t, h1b, s1b, h1r, s1r = _foundation_bits(analysis)
    return QualityVector(
        g=g,
        face_down=count_face_down(state),
        empty_count=empty_count(state),
        longest_same_suit=longest,
        same_suit_run_mass=mass,
        foundation_build_max=bmax,
        predeal_same_suit_landings=predeal_ss,
        predeal_immediate_outs=predeal_outs,
        predeal_non_connecting=predeal_nc,
        foundations_removed=nfound,
        h1_theo=h1t,
        s1_theo=s1t,
        h1_build=h1b,
        s1_build=s1b,
        h1_removal=h1r,
        s1_removal=s1r,
    )


def _select_objectives(
    portfolio: ObjectivePortfolio,
    node: PlanNode,
    *,
    max_per_expand: int = 6,
    cheap_reveal_max: int = 2,
    workspace_attempts_left: int = 2,
) -> List[StrategicObjective]:
    empties = empty_count(node.state)
    reveal_cap = cheap_reveal_max + (1 if empties > 0 else 0)
    by: Dict[str, List[StrategicObjective]] = {}
    deal = None
    for o in portfolio.objectives:
        if o.kind not in EXPANDABLE:
            continue
        if o.kind == ObjectiveKind.DEAL_NOW:
            deal = o
            continue
        if o.kind == ObjectiveKind.EXPOSE_REVEAL_PREFIX:
            req = int(o.target_params.get("required_reveals", 99))
            if req > reveal_cap:
                continue
        if o.kind == ObjectiveKind.CREATE_WORKSPACE and workspace_attempts_left <= 0:
            continue
        by.setdefault(o.kind.value, []).append(o)

    chosen: List[StrategicObjective] = []
    if deal is not None:
        chosen.append(deal)
    order = [
        ObjectiveKind.REMOVE_FOUNDATION.value,
        ObjectiveKind.CREATE_WORKSPACE.value,
        ObjectiveKind.SHAPE_STOCK_RECEIVER.value,
        ObjectiveKind.EXPOSE_REVEAL_PREFIX.value,
        ObjectiveKind.CONSOLIDATE_SAME_SUIT.value,
        ObjectiveKind.ADVANCE_FOUNDATION.value,
    ]
    for k in order:
        if k in by and by[k]:
            chosen.append(by[k][0])
    rest: List[StrategicObjective] = []
    for k, lst in by.items():
        rest.extend(lst[1:] if k in order else lst)
    rest.sort(key=lambda o: (o.heuristic_est_cost, -o.priority.total()))
    for o in rest:
        if len(chosen) >= max_per_expand:
            break
        if o.objective_id not in {c.objective_id for c in chosen}:
            chosen.append(o)
    return chosen[:max_per_expand]


def _tactical_limits(
    obj: StrategicObjective,
    *,
    default_cost: int,
    default_nodes: int,
    default_time: float,
    workspace_cost: int,
) -> Tuple[int, int, float]:
    if obj.kind == ObjectiveKind.DEAL_NOW:
        return 1, 8, 0.05
    if obj.kind == ObjectiveKind.CREATE_WORKSPACE:
        return workspace_cost, max(default_nodes, 600), max(default_time, 0.35)
    return default_cost, default_nodes, default_time


def pareto_front(nodes: Sequence[PlanNode]) -> Tuple[PlanNode, ...]:
    kept: List[PlanNode] = []
    for n in nodes:
        if any(o.quality.dominates(n.quality) for o in nodes if o is not n):
            continue
        kept.append(n)
    best: Dict[CanonicalStateKey, PlanNode] = {}
    for n in kept:
        prev = best.get(n.key)
        if prev is None or n.g < prev.g:
            best[n.key] = n
    return tuple(sorted(best.values(), key=lambda x: x.quality.heuristic_order_key()))


def stratify_nodes(nodes: Sequence[PlanNode], *, limit: int) -> Tuple[PlanNode, ...]:
    """Keep structurally diverse representatives; g=1 is one stratum only."""
    if not nodes:
        return ()
    picks: List[PlanNode] = []

    def add(n: Optional[PlanNode]) -> None:
        if n is None:
            return
        if n.key in {p.key for p in picks} and n.g >= next(
            p.g for p in picks if p.key == n.key
        ):
            return
        picks.append(n)

    add(min(nodes, key=lambda n: n.g))
    add(min(nodes, key=lambda n: (n.quality.face_down, n.g)))
    add(max(nodes, key=lambda n: (n.quality.empty_count, -n.g)))
    add(max(nodes, key=lambda n: (n.quality.longest_same_suit, n.quality.same_suit_run_mass, -n.g)))
    add(max(nodes, key=lambda n: (n.quality.foundation_build_max, -n.g)))
    add(max(nodes, key=lambda n: (n.quality.predeal_same_suit_landings, n.quality.predeal_immediate_outs, -n.g)))
    add(min(nodes, key=lambda n: n.quality.heuristic_order_key()))
    # fill remaining by structure-first key
    rest = sorted(nodes, key=lambda n: n.quality.heuristic_order_key())
    for n in rest:
        if len(picks) >= limit:
            break
        if n.key not in {p.key for p in picks}:
            picks.append(n)
    return tuple(picks[:limit])


def _access_allowed(node: PlanNode) -> bool:
    """At most one ACCESS per epoch unless workspace/foundation changed."""
    if node.access_macros_this_epoch <= 0:
        return True
    if node.quality.empty_count > node.last_access_empty:
        return True
    if node.quality.foundations_removed > node.last_access_foundations:
        return True
    return False


def _realize_access_cached(
    state: SpiderState,
    *,
    cards,
    budget: int,
    cache: Dict[Tuple[CanonicalStateKey, int], Optional[object]],
    max_steps: int,
    tactical_max_cost: int,
    tactical_max_nodes: int,
    tactical_time_s: float,
):
    """Return (result or None, cache_hit). Zero-progress is cached as None."""
    from spider.planner.campaign_realizer import realize_campaign

    key = (canonical_state_key(state), budget)
    if key in cache:
        return cache[key], True
    camps = generate_campaigns(state, cards=cards, max_campaigns=4)
    access = next((c for c in camps if c.kind == CampaignKind.ACCESS), None)
    if access is None:
        cache[key] = None
        return None, False
    result = realize_campaign(
        state,
        access,
        cards=cards,
        max_paid_cost=budget,
        max_steps=max_steps,
        tactical_max_cost=tactical_max_cost,
        tactical_max_nodes=tactical_max_nodes,
        tactical_time_s=tactical_time_s,
    )
    if (
        result.zero_progress
        or result.fd_reduction <= 0
        or not result.actions
        or not result.replay_verified
        or any(a == ("deal",) for a in result.actions)
    ):
        cache[key] = None
        return None, False
    cache[key] = result
    return result, False


def search_to_stock_epoch(
    start: SpiderState,
    *,
    target_deals: int = 2,
    cards: Optional[Sequence[Card]] = None,
    max_non_deal: int = 3,
    beam: int = 20,
    tactical_max_cost: int = 3,
    tactical_max_nodes: int = 400,
    tactical_time_s: float = 0.25,
    workspace_max_cost: int = 5,
    workspace_attempts_per_node: int = 1,
    max_plan_nodes: int = 200,
    time_limit_s: float = 90.0,
    max_per_expand: int = 6,
    cheap_reveal_max: int = 2,
    incumbent: Optional[int] = None,
    target: Optional[int] = None,
    use_access_campaigns: bool = False,
    access_max_paid_cost: int = 10,
    access_max_steps: int = 8,
    access_tactical_time_s: float = 0.2,
) -> PlanSearchResult:
    """Beam search over objectives until ``target_deals`` stock deals are applied.

    ``use_access_campaigns`` (Sprint 1L A/B): when True, a productive ACCESS
    campaign may become one plan edge per epoch (rerun only after workspace
    or foundation change). Other campaign kinds are not plan edges.
    """
    t0 = time.time()
    stats = PlanSearchStats()
    analysis0 = analyze_strategic(start, cards=cards, run_shaping_probe=False)
    q0 = compute_quality(start, 0, cards=cards, analysis=analysis0)
    root = PlanNode(
        state=start.clone(),
        g=0,
        actions=(),
        objective_ids=(),
        objective_kinds=(),
        key=canonical_state_key(start),
        deals_done=0,
        epoch_depth=0,
        quality=q0,
        notes=("root",),
    )
    live: List[PlanNode] = [root]
    terminals: List[PlanNode] = []
    deal1_seen: List[PlanNode] = []
    deal2_seen: List[PlanNode] = []
    tt: Dict[Tuple[int, CanonicalStateKey], int] = {(0, root.key): 0}
    access_cache: Dict[Tuple[CanonicalStateKey, int], Optional[object]] = {}

    while live:
        if time.time() - t0 > time_limit_s or stats.plan_nodes >= max_plan_nodes:
            break
        nxt: List[PlanNode] = []
        for node in live:
            if time.time() - t0 > time_limit_s or stats.plan_nodes >= max_plan_nodes:
                break
            if node.deals_done >= target_deals:
                continue
            stats.plan_nodes += 1
            if node.deals_done == 1:
                stats.deal1_frontier += 1
            if node.deals_done == 2:
                stats.deal2_frontier += 1
            analysis = analyze_strategic(node.state, cards=cards, run_shaping_probe=False)
            portfolio = generate_objective_portfolio(
                node.state, analysis=analysis, cards=cards
            )
            selected = _select_objectives(
                portfolio,
                node,
                max_per_expand=max_per_expand,
                cheap_reveal_max=cheap_reveal_max,
                workspace_attempts_left=workspace_attempts_per_node,
            )
            if not any(o.kind == ObjectiveKind.DEAL_NOW for o in selected):
                if len(node.state.stock) >= 10:
                    for o in portfolio.objectives:
                        if o.kind == ObjectiveKind.DEAL_NOW:
                            selected = [o] + selected
                            break

            def _emit_child(
                *,
                child_state: SpiderState,
                new_g: int,
                extra_actions: Tuple[Action, ...],
                extra_id: str,
                extra_kind: str,
                is_deal: bool,
                extra_notes: Tuple[str, ...] = (),
                access_result=None,
            ) -> None:
                child_key = canonical_state_key(child_state)
                new_deals = node.deals_done + (1 if is_deal else 0)
                tt_key = (new_deals, child_key)
                prev_g = tt.get(tt_key)
                if prev_g is not None and prev_g <= new_g:
                    stats.tt_hits += 1
                    return
                tt[tt_key] = new_g
                if incumbent is not None or target is not None:
                    h = compute_solution_lower_bound(child_state).h_admissible
                    bd = budget_diagnostic(
                        g=new_g, h=h, incumbent=incumbent, target=target
                    )
                    if incumbent is not None and bd.prune_vs_incumbent:
                        return
                    if target is not None and bd.prune_vs_target:
                        return
                pre_ss = pre_outs = pre_nc = 0
                if is_deal and analysis.stock_reception.can_deal:
                    s = analysis.stock_reception.row_summary
                    pre_ss = s.n_same_suit_landings
                    pre_outs = s.n_with_immediate_out
                    pre_nc = s.n_non_connecting
                child_analysis = analyze_strategic(
                    child_state, cards=cards, run_shaping_probe=False
                )
                inv_paid = node.investment_paid
                inv_fd = node.investment_fd
                acc_n = 0 if is_deal else node.access_macros_this_epoch
                last_e = node.last_access_empty
                last_f = node.last_access_foundations
                focus_hist = node.access_focus_history
                fb = node.access_fallbacks
                if access_result is not None:
                    inv_paid += access_result.paid_cost
                    inv_fd += access_result.fd_reduction
                    acc_n += 1
                    last_e = empty_count(child_state)
                    last_f = sum(1 for s in child_state.foundations if len(s) == 13)
                    focus_hist = focus_hist + access_result.focus_history
                    fb += access_result.fallbacks_tried
                q = replace(
                    compute_quality(
                        child_state,
                        new_g,
                        cards=cards,
                        analysis=child_analysis,
                        predeal_ss=pre_ss,
                        predeal_outs=pre_outs,
                        predeal_nc=pre_nc,
                    ),
                    investment_paid=inv_paid,
                    investment_fd=inv_fd,
                )
                kinds = node.objective_kinds + (extra_kind,)
                if (
                    ObjectiveKind.CREATE_WORKSPACE.value in kinds
                    and ObjectiveKind.EXPOSE_REVEAL_PREFIX.value in kinds
                ):
                    stats.workspace_then_expose += 1
                child = PlanNode(
                    state=child_state,
                    g=new_g,
                    actions=node.actions + extra_actions,
                    objective_ids=node.objective_ids + (extra_id,),
                    objective_kinds=kinds,
                    key=child_key,
                    deals_done=new_deals,
                    epoch_depth=0 if is_deal else node.epoch_depth + 1,
                    quality=q,
                    notes=extra_notes + q.deferred_notes(),
                    access_macros_this_epoch=acc_n,
                    last_access_empty=last_e,
                    last_access_foundations=last_f,
                    access_focus_history=focus_hist,
                    access_fallbacks=fb,
                    investment_paid=inv_paid,
                    investment_fd=inv_fd,
                )
                if new_deals >= target_deals:
                    terminals.append(child)
                else:
                    nxt.append(child)
                    if new_deals == 1:
                        deal1_seen.append(child)
                    if new_deals == 2:
                        deal2_seen.append(child)

            if (
                use_access_campaigns
                and node.epoch_depth < max_non_deal
                and _access_allowed(node)
            ):
                stats.access_macros_attempted += 1
                acc, hit = _realize_access_cached(
                    node.state,
                    cards=cards,
                    budget=min(access_max_paid_cost, 15),
                    cache=access_cache,
                    max_steps=access_max_steps,
                    tactical_max_cost=max(tactical_max_cost, 3),
                    tactical_max_nodes=tactical_max_nodes,
                    tactical_time_s=access_tactical_time_s,
                )
                if hit:
                    stats.access_cache_hits += 1
                if acc is None:
                    stats.access_macros_zero += 1
                else:
                    stats.access_macros_applied += 1
                    stats.access_paid += acc.paid_cost
                    stats.access_fd_reduced += acc.fd_reduction
                    stats.families_tried[ACCESS_KIND] = (
                        stats.families_tried.get(ACCESS_KIND, 0) + 1
                    )
                    child_state = node.state.clone()
                    replay_actions(child_state, list(acc.actions))
                    _emit_child(
                        child_state=child_state,
                        new_g=node.g + acc.paid_cost,
                        extra_actions=tuple(acc.actions),
                        extra_id=acc.campaign.campaign_id,
                        extra_kind=ACCESS_KIND,
                        is_deal=False,
                        extra_notes=(
                            f"ACCESS cost={acc.paid_cost} fdΔ={acc.fd_reduction} "
                            f"fb={acc.fallbacks_tried} focus={list(acc.focus_history)}",
                        ),
                        access_result=acc,
                    )

            ws_left = workspace_attempts_per_node
            for obj in selected:
                is_deal = obj.kind == ObjectiveKind.DEAL_NOW
                if not is_deal and node.epoch_depth >= max_non_deal:
                    continue
                if obj.kind == ObjectiveKind.CREATE_WORKSPACE:
                    if ws_left <= 0:
                        continue
                    ws_left -= 1

                stats.realizations_attempted += 1
                stats.families_tried[obj.kind.value] = (
                    stats.families_tried.get(obj.kind.value, 0) + 1
                )
                mc, mn, mt = _tactical_limits(
                    obj,
                    default_cost=tactical_max_cost,
                    default_nodes=tactical_max_nodes,
                    default_time=tactical_time_s,
                    workspace_cost=workspace_max_cost,
                )
                res = realize_objective(
                    node.state,
                    obj,
                    mode=RealizationMode.EXACT_BOUNDED,
                    max_cost=mc,
                    max_nodes=mn,
                    time_limit_s=mt,
                )
                if res.status == RealizationStatus.ALREADY_SATISFIED:
                    stats.realizations_already += 1
                    continue
                if res.status == RealizationStatus.RESOURCE_LIMIT:
                    stats.realizations_resource += 1
                    continue
                if res.status != RealizationStatus.FOUND:
                    stats.realizations_miss += 1
                    continue
                stats.realizations_found += 1

                new_g = node.g + int(res.corrected_mw_cost or 0)
                child_state = node.state.clone()
                replay_actions(child_state, list(res.actions))
                _emit_child(
                    child_state=child_state,
                    new_g=new_g,
                    extra_actions=tuple(res.actions),
                    extra_id=obj.objective_id,
                    extra_kind=obj.kind.value,
                    is_deal=is_deal,
                    extra_notes=(
                        f"realized {obj.kind.value} cost={res.corrected_mw_cost} "
                        f"epoch={node.deals_done + (1 if is_deal else 0)}",
                    ),
                )

        # Stratify live frontier by epoch so cheap deals don't starve investment
        by_epoch: Dict[int, List[PlanNode]] = {}
        for n in nxt:
            by_epoch.setdefault(n.deals_done, []).append(n)
        live = []
        slots = max(4, beam // max(1, len(by_epoch) or 1))
        for ep in sorted(by_epoch):
            live.extend(stratify_nodes(by_epoch[ep], limit=slots))
        # fill to beam
        rest = [n for n in nxt if n.key not in {x.key for x in live}]
        rest.sort(key=lambda n: n.quality.heuristic_order_key())
        for n in rest:
            if len(live) >= beam:
                break
            live.append(n)
        if not live:
            break

    stats.elapsed_seconds = time.time() - t0
    verified: List[PlanNode] = []
    for t in terminals:
        chk = start.clone()
        cost = replay_actions(chk, list(t.actions))
        if cost == t.g and t.deals_done >= target_deals:
            verified.append(t)
    pareto = pareto_front(verified)
    stratified = stratify_nodes(verified, limit=max(8, beam // 4))
    return PlanSearchResult(
        terminals=tuple(sorted(verified, key=lambda n: n.g)),
        pareto_terminals=pareto,
        stratified_terminals=stratified,
        stats=stats,
        config={
            "target_deals": target_deals,
            "max_non_deal": max_non_deal,
            "beam": beam,
            "tactical_max_cost": tactical_max_cost,
            "workspace_max_cost": workspace_max_cost,
            "max_plan_nodes": max_plan_nodes,
            "time_limit_s": time_limit_s,
            "use_access_campaigns": use_access_campaigns,
            "access_max_paid_cost": access_max_paid_cost,
        },
        deal1_nodes=tuple(deal1_seen),
        deal2_nodes=tuple(deal2_seen),
    )


def search_opening_to_first_deal(
    start: SpiderState,
    **kwargs,
) -> PlanSearchResult:
    """1G API: opening through Deal 1."""
    kwargs.setdefault("target_deals", 1)
    return search_to_stock_epoch(start, **kwargs)


def canonical_opening_to_deal1(
    start: SpiderState, actions: Sequence[Action]
) -> PlanNode:
    snaps = replay_canonical_epochs(start, actions, up_to_deals=1)
    return snaps["post_deal_1"]


def replay_canonical_epochs(
    start: SpiderState,
    actions: Sequence[Action],
    *,
    up_to_deals: int = 2,
    cards: Optional[Sequence[Card]] = None,
) -> Dict[str, PlanNode]:
    """Diagnostic human snapshots at pre/post each deal (not strategy)."""
    st = start.clone()
    prefix: List[Action] = []
    g = 0
    deals = 0
    out: Dict[str, PlanNode] = {}

    def snap(name: str, dealt_flag_deals: int) -> PlanNode:
        analysis = analyze_strategic(st, cards=cards, run_shaping_probe=False)
        q = compute_quality(st, g, cards=cards, analysis=analysis)
        return PlanNode(
            state=st.clone(),
            g=g,
            actions=tuple(prefix),
            objective_ids=(f"canonical_{name}",),
            objective_kinds=("CANONICAL",),
            key=canonical_state_key(st),
            deals_done=dealt_flag_deals,
            epoch_depth=0,
            quality=q,
            notes=(f"diagnostic {name}",) + q.deferred_notes(),
        )

    out["initial"] = snap("initial", 0)
    for a in actions:
        if a == ("deal",):
            deals += 1
            out[f"pre_deal_{deals}"] = snap(f"pre_deal_{deals}", deals - 1)
            prefix.append(a)
            g += replay_actions(st, [a])
            out[f"post_deal_{deals}"] = snap(f"post_deal_{deals}", deals)
            if deals >= up_to_deals:
                return out
        else:
            prefix.append(a)
            g += replay_actions(st, [a])
    return out


def select_stratified_seeds(
    nodes: Sequence[PlanNode], *, limit: int = 5
) -> Tuple[PlanNode, ...]:
    """Generic seed pick: cheapest, least fd, strongest SS, strongest H/S, balanced."""
    if not nodes:
        return ()
    picks: List[PlanNode] = []

    def add(n: PlanNode) -> None:
        if n.key not in {p.key for p in picks}:
            picks.append(n)

    add(min(nodes, key=lambda n: (n.g, n.quality.face_down)))
    add(min(nodes, key=lambda n: (n.quality.face_down, n.g)))
    add(max(nodes, key=lambda n: (n.quality.longest_same_suit, n.quality.same_suit_run_mass, -n.g)))
    add(max(nodes, key=lambda n: (n.quality.s1_build + n.quality.h1_build, n.quality.s1_removal + n.quality.h1_removal, -n.g)))
    add(min(nodes, key=lambda n: n.quality.heuristic_order_key()))
    for n in stratify_nodes(nodes, limit=limit):
        if len(picks) >= limit:
            break
        add(n)
    return tuple(picks[:limit])


def search_epoch_maturation(
    seeds: Sequence[PlanNode],
    *,
    cards: Optional[Sequence[Card]] = None,
    deals_done: int = 2,
    max_added_cost: int = 10,
    max_objectives: int = 6,
    beam: int = 16,
    tactical_max_cost: int = 4,
    tactical_max_nodes: int = 350,
    tactical_time_s: float = 0.25,
    workspace_max_cost: int = 6,
    workspace_attempts_per_node: int = 1,
    max_plan_nodes: int = 40,
    time_limit_s: float = 45.0,
    cheap_reveal_max: int = 2,
) -> PlanSearchResult:
    """Mature seeds at a fixed stock epoch. Never deals."""
    t0 = time.time()
    stats = PlanSearchStats()
    live: List[PlanNode] = []
    tt: Dict[CanonicalStateKey, int] = {}
    for s in seeds:
        if s.deals_done != deals_done:
            continue
        node = PlanNode(
            state=s.state.clone(),
            g=s.g,
            actions=s.actions,
            objective_ids=s.objective_ids,
            objective_kinds=s.objective_kinds,
            key=s.key,
            deals_done=s.deals_done,
            epoch_depth=0,
            quality=s.quality,
            notes=s.notes + ("maturation_seed",),
            added_cost=0,
        )
        live.append(node)
        prev = tt.get(node.key)
        if prev is None or node.g < prev:
            tt[node.key] = node.g
    survivors: List[PlanNode] = list(live)

    while live:
        if time.time() - t0 > time_limit_s or stats.plan_nodes >= max_plan_nodes:
            break
        nxt: List[PlanNode] = []
        for node in live:
            if time.time() - t0 > time_limit_s or stats.plan_nodes >= max_plan_nodes:
                break
            if node.added_cost >= max_added_cost:
                continue
            if node.epoch_depth >= max_objectives:
                continue
            stats.plan_nodes += 1
            analysis = analyze_strategic(node.state, cards=cards, run_shaping_probe=False)
            portfolio = generate_objective_portfolio(
                node.state, analysis=analysis, cards=cards
            )
            selected = _select_objectives(
                portfolio,
                node,
                max_per_expand=6,
                cheap_reveal_max=cheap_reveal_max,
                workspace_attempts_left=workspace_attempts_per_node,
            )
            selected = [o for o in selected if o.kind in EXPANDABLE_MATURE]
            # include REMOVE_FOUNDATION / extra families from portfolio
            for o in portfolio.objectives:
                if o.kind == ObjectiveKind.REMOVE_FOUNDATION:
                    if o.objective_id not in {x.objective_id for x in selected}:
                        selected.append(o)
            ws_left = workspace_attempts_per_node
            for obj in selected:
                if obj.kind == ObjectiveKind.DEAL_NOW:
                    continue
                if obj.kind == ObjectiveKind.CREATE_WORKSPACE:
                    if ws_left <= 0:
                        continue
                    ws_left -= 1
                stats.realizations_attempted += 1
                stats.families_tried[obj.kind.value] = (
                    stats.families_tried.get(obj.kind.value, 0) + 1
                )
                mc, mn, mt = _tactical_limits(
                    obj,
                    default_cost=tactical_max_cost,
                    default_nodes=tactical_max_nodes,
                    default_time=tactical_time_s,
                    workspace_cost=workspace_max_cost,
                )
                remaining = max_added_cost - node.added_cost
                mc = min(mc, remaining)
                if mc < obj.admissible_lb and obj.admissible_lb > 0:
                    stats.realizations_miss += 1
                    continue
                res = realize_objective(
                    node.state,
                    obj,
                    mode=RealizationMode.EXACT_BOUNDED,
                    max_cost=mc,
                    max_nodes=mn,
                    time_limit_s=mt,
                )
                if res.status == RealizationStatus.ALREADY_SATISFIED:
                    stats.realizations_already += 1
                    continue
                if res.status == RealizationStatus.RESOURCE_LIMIT:
                    stats.realizations_resource += 1
                    continue
                if res.status != RealizationStatus.FOUND:
                    stats.realizations_miss += 1
                    continue
                stats.realizations_found += 1
                add = int(res.corrected_mw_cost or 0)
                if node.added_cost + add > max_added_cost:
                    continue
                new_g = node.g + add
                child_state = node.state.clone()
                replay_actions(child_state, list(res.actions))
                child_key = canonical_state_key(child_state)
                prev_g = tt.get(child_key)
                if prev_g is not None and prev_g <= new_g:
                    stats.tt_hits += 1
                    continue
                tt[child_key] = new_g
                child_analysis = analyze_strategic(
                    child_state, cards=cards, run_shaping_probe=False
                )
                q = compute_quality(
                    child_state, new_g, cards=cards, analysis=child_analysis
                )
                kinds = node.objective_kinds + (obj.kind.value,)
                if (
                    ObjectiveKind.CREATE_WORKSPACE.value in kinds
                    and ObjectiveKind.EXPOSE_REVEAL_PREFIX.value in kinds
                ):
                    stats.workspace_then_expose += 1
                child = PlanNode(
                    state=child_state,
                    g=new_g,
                    actions=node.actions + tuple(res.actions),
                    objective_ids=node.objective_ids + (obj.objective_id,),
                    objective_kinds=kinds,
                    key=child_key,
                    deals_done=node.deals_done,
                    epoch_depth=node.epoch_depth + 1,
                    quality=q,
                    notes=(
                        f"mature {obj.kind.value} +{add} added={node.added_cost + add}",
                    )
                    + q.deferred_notes(),
                    added_cost=node.added_cost + add,
                )
                nxt.append(child)
                survivors.append(child)
        live = list(stratify_nodes(nxt, limit=beam))
        if not live:
            break

    stats.elapsed_seconds = time.time() - t0
    # Replay-verify against each seed's start... we don't have original deal here.
    # Caller verifies from original start. We verify incrementally from seed state.
    verified: List[PlanNode] = []
    seed_by_prefix = {(tuple(s.actions), s.g): s for s in seeds}
    for n in survivors:
        # find matching seed by action prefix length
        ok = False
        for s in seeds:
            if n.actions[: len(s.actions)] == s.actions:
                chk = s.state.clone()
                extra = n.actions[len(s.actions) :]
                cost = replay_actions(chk, list(extra)) if extra else 0
                if cost == n.added_cost and n.deals_done == deals_done:
                    # no deal in extra
                    if extra.count(("deal",)) == 0:
                        ok = True
                break
        if ok:
            verified.append(n)
    if not verified:
        verified = [n for n in survivors if ("deal",) not in n.actions[ -1: ] or True]
        verified = [n for n in survivors if n.actions.count(("deal",)) == seeds[0].actions.count(("deal",))] if seeds else survivors

    pareto = pareto_front(verified)
    stratified = stratify_nodes(verified, limit=max(8, beam // 2))
    return PlanSearchResult(
        terminals=tuple(sorted(verified, key=lambda n: (n.added_cost, n.g))),
        pareto_terminals=pareto,
        stratified_terminals=stratified,
        stats=stats,
        config={
            "deals_done": deals_done,
            "max_added_cost": max_added_cost,
            "max_objectives": max_objectives,
            "beam": beam,
            "forbid_deal": True,
        },
    )
