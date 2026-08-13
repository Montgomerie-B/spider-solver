"""Sprint 1G — limited plan-level search over strategic objectives.

Scope: opening through the first stock deal only.
This is a diagnostic search, not a whole-game solver or optimality proof.

Heuristic quality vectors are for beam/Pareto only. Admissible h is used
solely when an explicit incumbent/target is supplied.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple, Union

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

EXPANDABLE = {
    ObjectiveKind.CREATE_WORKSPACE,
    ObjectiveKind.EXPOSE_REVEAL_PREFIX,
    ObjectiveKind.SHAPE_STOCK_RECEIVER,
    ObjectiveKind.CONSOLIDATE_SAME_SUIT,
    ObjectiveKind.ADVANCE_FOUNDATION,
    ObjectiveKind.DEAL_NOW,
}


@dataclass(frozen=True)
class QualityVector:
    """Transparent HARD/heuristic components. Not a proof score.

    Lower is better for cost/hidden/nonconnect; higher is better for
    workspace / same-suit / foundation / reception (stored as positives).
    """

    g: int
    face_down: int
    empty_count: int
    longest_same_suit: int
    same_suit_run_mass: int
    foundation_build_max: float  # heuristic from 1A
    predeal_same_suit_landings: int
    predeal_immediate_outs: int
    predeal_non_connecting: int

    def dominates(self, other: "QualityVector") -> bool:
        """Pareto: better-or-equal on all minimized/maximized axes, strict one."""
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
        )
        return le and sl

    def heuristic_order_key(self) -> Tuple:
        """HEURISTIC ONLY beam key (lower better). Components retained above."""
        return (
            self.g,
            self.face_down,
            -self.empty_count,
            -self.longest_same_suit,
            -self.predeal_same_suit_landings,
            self.predeal_non_connecting,
            -self.same_suit_run_mass,
            -self.foundation_build_max,
        )


@dataclass
class PlanNode:
    state: SpiderState
    g: int
    actions: Tuple[Action, ...]
    objective_ids: Tuple[str, ...]
    objective_kinds: Tuple[str, ...]
    key: CanonicalStateKey
    objective_depth: int  # non-deal objectives applied
    dealt: bool
    quality: QualityVector
    notes: Tuple[str, ...] = ()


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


@dataclass
class PlanSearchResult:
    terminals: Tuple[PlanNode, ...]
    pareto_terminals: Tuple[PlanNode, ...]
    stats: PlanSearchStats
    config: Dict


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


def _foundation_build_max(analysis) -> float:
    if analysis.foundation is None:
        return 0.0
    vals = [
        c.heuristic_build_readiness
        for c in analysis.foundation.frontier.candidates
        if not c.already_completed
    ]
    return max(vals) if vals else 0.0


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
    return QualityVector(
        g=g,
        face_down=count_face_down(state),
        empty_count=empty_count(state),
        longest_same_suit=longest,
        same_suit_run_mass=mass,
        foundation_build_max=_foundation_build_max(analysis),
        predeal_same_suit_landings=predeal_ss,
        predeal_immediate_outs=predeal_outs,
        predeal_non_connecting=predeal_nc,
    )


def _select_objectives(
    portfolio: ObjectivePortfolio,
    *,
    max_per_expand: int = 6,
    cheap_reveal_max: int = 2,
) -> List[StrategicObjective]:
    """Prefer cheap/actionable, keep family diversity, always keep DEAL_NOW."""
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
            if req > cheap_reveal_max:
                continue
        by.setdefault(o.kind.value, []).append(o)

    chosen: List[StrategicObjective] = []
    if deal is not None:
        chosen.append(deal)
    order = [
        ObjectiveKind.CREATE_WORKSPACE.value,
        ObjectiveKind.SHAPE_STOCK_RECEIVER.value,
        ObjectiveKind.EXPOSE_REVEAL_PREFIX.value,
        ObjectiveKind.CONSOLIDATE_SAME_SUIT.value,
        ObjectiveKind.ADVANCE_FOUNDATION.value,
    ]
    # one from each family
    for k in order:
        if k in by and by[k]:
            chosen.append(by[k][0])
    # fill remaining cheap ones
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


def pareto_front(nodes: Sequence[PlanNode]) -> Tuple[PlanNode, ...]:
    kept: List[PlanNode] = []
    for n in nodes:
        if any(o.quality.dominates(n.quality) for o in nodes if o is not n):
            continue
        kept.append(n)
    # unique by key, cheapest g
    best: Dict[CanonicalStateKey, PlanNode] = {}
    for n in kept:
        prev = best.get(n.key)
        if prev is None or n.g < prev.g:
            best[n.key] = n
    return tuple(sorted(best.values(), key=lambda x: x.quality.heuristic_order_key()))


def search_opening_to_first_deal(
    start: SpiderState,
    *,
    cards: Optional[Sequence[Card]] = None,
    max_non_deal: int = 3,
    beam: int = 20,
    tactical_max_cost: int = 3,
    tactical_max_nodes: int = 400,
    tactical_time_s: float = 0.25,
    max_plan_nodes: int = 200,
    time_limit_s: float = 60.0,
    max_per_expand: int = 6,
    cheap_reveal_max: int = 2,
    incumbent: Optional[int] = None,
    target: Optional[int] = None,
) -> PlanSearchResult:
    """Beam search over objectives until Deal 1.

    Conservative diagnostic defaults. DEAL_NOW is always attempted when legal.
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
        objective_depth=0,
        dealt=False,
        quality=q0,
        notes=("root",),
    )
    beam_nodes: List[PlanNode] = [root]
    terminals: List[PlanNode] = []
    tt: Dict[CanonicalStateKey, int] = {root.key: 0}

    while beam_nodes:
        if time.time() - t0 > time_limit_s or stats.plan_nodes >= max_plan_nodes:
            break
        nxt: List[PlanNode] = []
        for node in beam_nodes:
            if time.time() - t0 > time_limit_s or stats.plan_nodes >= max_plan_nodes:
                break
            if node.dealt:
                continue
            stats.plan_nodes += 1
            analysis = analyze_strategic(node.state, cards=cards, run_shaping_probe=False)
            portfolio = generate_objective_portfolio(
                node.state, analysis=analysis, cards=cards
            )
            selected = _select_objectives(
                portfolio,
                max_per_expand=max_per_expand,
                cheap_reveal_max=cheap_reveal_max,
            )
            # If no DEAL_NOW slipped through, add if legal
            if not any(o.kind == ObjectiveKind.DEAL_NOW for o in selected):
                if len(node.state.stock) >= 10:
                    for o in portfolio.objectives:
                        if o.kind == ObjectiveKind.DEAL_NOW:
                            selected = [o] + selected
                            break

            for obj in selected:
                if obj.kind == ObjectiveKind.DEAL_NOW:
                    # Always allow deal when legal
                    pass
                elif node.objective_depth >= max_non_deal:
                    continue

                stats.realizations_attempted += 1
                stats.families_tried[obj.kind.value] = (
                    stats.families_tried.get(obj.kind.value, 0) + 1
                )
                res = realize_objective(
                    node.state,
                    obj,
                    mode=RealizationMode.EXACT_BOUNDED,
                    max_cost=1 if obj.kind == ObjectiveKind.DEAL_NOW else tactical_max_cost,
                    max_nodes=8 if obj.kind == ObjectiveKind.DEAL_NOW else tactical_max_nodes,
                    time_limit_s=0.05
                    if obj.kind == ObjectiveKind.DEAL_NOW
                    else tactical_time_s,
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
                # Apply fragment to clone
                child_state = node.state.clone()
                replay_actions(child_state, list(res.actions))
                child_key = canonical_state_key(child_state)
                prev_g = tt.get(child_key)
                if prev_g is not None and prev_g <= new_g:
                    stats.tt_hits += 1
                    continue
                tt[child_key] = new_g

                if incumbent is not None or target is not None:
                    h = compute_solution_lower_bound(child_state).h_admissible
                    bd = budget_diagnostic(
                        g=new_g, h=h, incumbent=incumbent, target=target
                    )
                    if incumbent is not None and bd.prune_vs_incumbent:
                        continue
                    if target is not None and bd.prune_vs_target:
                        continue

                dealt = obj.kind == ObjectiveKind.DEAL_NOW
                pre_ss = pre_outs = pre_nc = 0
                if dealt and analysis.stock_reception.can_deal:
                    s = analysis.stock_reception.row_summary
                    pre_ss = s.n_same_suit_landings
                    pre_outs = s.n_with_immediate_out
                    pre_nc = s.n_non_connecting
                child_analysis = analyze_strategic(
                    child_state, cards=cards, run_shaping_probe=False
                )
                q = compute_quality(
                    child_state,
                    new_g,
                    cards=cards,
                    analysis=child_analysis,
                    predeal_ss=pre_ss,
                    predeal_outs=pre_outs,
                    predeal_nc=pre_nc,
                )
                child = PlanNode(
                    state=child_state,
                    g=new_g,
                    actions=node.actions + tuple(res.actions),
                    objective_ids=node.objective_ids + (obj.objective_id,),
                    objective_kinds=node.objective_kinds + (obj.kind.value,),
                    key=child_key,
                    objective_depth=node.objective_depth
                    + (0 if dealt else 1),
                    dealt=dealt,
                    quality=q,
                    notes=(f"realized {obj.kind.value} cost={res.corrected_mw_cost}",),
                )
                if dealt:
                    terminals.append(child)
                else:
                    nxt.append(child)

        nxt.sort(key=lambda n: n.quality.heuristic_order_key())
        # Diversity: keep best of each last-kind then fill
        diverse: List[PlanNode] = []
        seen_kind: Set[str] = set()
        for n in nxt:
            last = n.objective_kinds[-1] if n.objective_kinds else ""
            if last not in seen_kind:
                diverse.append(n)
                seen_kind.add(last)
        for n in nxt:
            if n not in diverse:
                diverse.append(n)
        beam_nodes = diverse[:beam]
        if not beam_nodes:
            break

    stats.elapsed_seconds = time.time() - t0
    # Replay-verify terminals
    verified: List[PlanNode] = []
    for t in terminals:
        chk = start.clone()
        cost = replay_actions(chk, list(t.actions))
        if cost == t.g and t.dealt:
            verified.append(t)
    pareto = pareto_front(verified)
    return PlanSearchResult(
        terminals=tuple(sorted(verified, key=lambda n: n.g)),
        pareto_terminals=pareto,
        stats=stats,
        config={
            "max_non_deal": max_non_deal,
            "beam": beam,
            "tactical_max_cost": tactical_max_cost,
            "max_plan_nodes": max_plan_nodes,
            "time_limit_s": time_limit_s,
        },
    )


def canonical_opening_to_deal1(
    start: SpiderState, actions: Sequence[Action]
) -> PlanNode:
    """Replay human/canonical prefix until first deal (diagnostic only)."""
    st = start.clone()
    prefix: List[Action] = []
    g = 0
    for a in actions:
        prefix.append(a)
        g += replay_actions(st, [a])
        if a == ("deal",):
            analysis = analyze_strategic(st, run_shaping_probe=False)
            q = compute_quality(st, g, analysis=analysis)
            return PlanNode(
                state=st,
                g=g,
                actions=tuple(prefix),
                objective_ids=("canonical_opening",),
                objective_kinds=("CANONICAL",),
                key=canonical_state_key(st),
                objective_depth=0,
                dealt=True,
                quality=q,
                notes=("diagnostic canonical opening only",),
            )
    raise RuntimeError("no deal in action list")
