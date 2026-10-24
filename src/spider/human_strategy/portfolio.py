"""Small objective portfolio and one-ply strategic candidates.

Concrete legal moves are scored by the estimated remaining cost of the
position they produce. Portfolio objectives from the existing generator are
added as search targets. They do not outrank a concrete move that already
improves the estimate, except for one optimistic workspace stretch when no
concrete move improves the position. That stretch is how a failing objective
can be attempted and then abandoned.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from spider.cards import rank_str
from spider.engine import SpiderState
from spider.metrics import Action, format_action
from spider.move_lifecycle import assess_tableau_move
from spider.planner.lower_bounds import compute_objective_lower_bound
from spider.planner.space_lifecycle import empty_count
from spider.planner.stock_reception import next_stock_row
from spider.planner.strategic_objectives import (
    ObjectiveKind,
    PriorityComponents,
    StrategicObjective,
    generate_objective_portfolio,
)
from spider.research_actions import all_legal_actions, apply_action, face_down_count, step_cost

from .context import StrategicContext, build_context
from .evaluation import (
    admissible_remaining,
    bury_risk,
    estimate_remaining,
    goodness_score,
    reveals,
    same_suit_bonds,
    same_suit_landings,
    splits_same_suit_run,
    unproductive_empty_move,
    useless_king_relocate,
)
from .profiles import Profile


@dataclass
class Candidate:
    candidate_id: str
    kind: str
    purpose: str
    principles: Tuple[int, ...]
    actions: Tuple[Action, ...]
    objective: Optional[StrategicObjective]
    immediate_cost: int
    cost_is_exact: bool
    expected_benefit: float
    structural_risk: float
    horizon: str
    feasibility: str
    evidence: Tuple[str, ...]
    admissible_lb: int
    projected: float
    solves: bool
    attractiveness: float = 0.0
    hold: bool = False

    def rank_key(self) -> tuple:
        # Projected cost first. A solved terminal wins a tie. Attractiveness
        # orders unfinished positions that share a projected cost. It is not
        # allowed to cancel a full move of projected cost.
        return (
            self.projected,
            0 if self.solves else 1,
            -self.attractiveness,
            self.structural_risk,
            self.candidate_id,
        )


def _principle_tags(kind: str, action: Action, state: SpiderState) -> Tuple[int, ...]:
    tags = {1, 4, 5}
    if kind == "DEAL_NOW":
        tags.update({2, 8, 24, 25, 27})
    elif kind == "PREPARE":
        tags.update({2, 8, 9, 23, 24, 25, 26})
    elif kind == "FOUNDATION":
        tags.update({8, 11, 12, 15})
    elif kind == "REVEAL":
        tags.update({2, 3, 7, 13, 17, 18, 19, 23})
    elif kind == "ZERO_COST":
        tags.update({7, 22})
    elif kind == "SAME_SUIT":
        tags.update({9, 10, 11, 12, 14})
    elif kind == "WORKSPACE":
        tags.update({17, 18, 19})
    elif kind == "PARK":
        tags.update({7, 18, 20, 21, 23})
    elif kind == "STRETCH":
        tags.update({6, 17, 28})
    if action != ("deal",) and action is not None and useless_king_relocate(state, action):
        tags.add(16)
    if action != ("deal",) and action is not None and reveals(state, action):
        head = state.columns[action[0]].face_up[0] if state.columns[action[0]].face_up else None
        if head is not None and head.rank == 13:
            tags.add(16)
    if action != ("deal",) and splits_same_suit_run(state, action):
        tags.update({10, 14})
    return tuple(sorted(tags))


def _incoming_note(state: SpiderState, column: int) -> str:
    row = next_stock_row(state)
    if row is None:
        return "no incoming stock row"
    card = row[column]
    top = state.columns[column].top()
    label = f"{rank_str(card.rank)}{card.suit.upper()}"
    if top is None:
        landing = "empty column"
    elif top.suit == card.suit and top.rank == card.rank + 1:
        landing = "same-suit landing"
    elif top.rank == card.rank + 1:
        landing = "mixed landing"
    else:
        landing = "covers the current top"
    return f"estimate: incoming column {column + 1} is {label}; {landing}"


def _classify(state: SpiderState, action: Action, before_bury: int, after: SpiderState) -> str:
    if action == ("deal",):
        return "DEAL_NOW"
    if len(after.foundations) > len(state.foundations):
        return "FOUNDATION"
    if bury_risk(after) < before_bury:
        return "PREPARE"
    if face_down_count(after) < face_down_count(state):
        return "REVEAL"
    if step_cost(state, action) == 0 and (
        same_suit_landings(after) > same_suit_landings(state) or same_suit_bonds(after) > same_suit_bonds(state)
    ):
        return "ZERO_COST"
    if same_suit_bonds(after) > same_suit_bonds(state) and not splits_same_suit_run(state, action):
        return "SAME_SUIT"
    if empty_count(after) > empty_count(state):
        return "WORKSPACE"
    if action != ("deal",):
        try:
            life = assess_tableau_move(state, action)
        except ValueError:
            life = None
        if life is not None and life.placement_class.value in {"MIXED_SUIT_PARK", "WORKSPACE_PARK"}:
            if life.exit_route_bounded:
                return "PARK"
    return "TACTICAL"


def _score_action(state: SpiderState, g: int, action: Action, ctx: StrategicContext) -> Candidate:
    cost = step_cost(state, action)
    after = state.clone()
    apply_action(after, action)
    estimate = estimate_remaining(after)
    penalty = 0.0
    risk_notes: List[str] = []
    if action == ("deal",) and ctx.bury_risk > 0:
        penalty += 2.0 * ctx.bury_risk
        risk_notes.append(
            "estimate: dealing now covers a card that still has a same-suit home"
        )
    if action != ("deal",) and same_suit_landings(after) < same_suit_landings(state):
        penalty += 3.0
        risk_notes.append("estimate: the move destroys a same-suit stock landing")
    if (
        bury_risk(after) < bury_risk(state)
        and same_suit_bonds(after) <= same_suit_bonds(state)
        and not reveals(state, action)
    ):
        penalty += 1.5
        risk_notes.append("estimate: the card left a same-suit home without joining it")
    if unproductive_empty_move(state, action, after):
        penalty += 1.5
        risk_notes.append(
            "estimate: empty-column relocate does not reveal, join, or improve a landing"
        )
    if splits_same_suit_run(state, action) and not reveals(state, action):
        penalty += 1.6
        risk_notes.append("estimate: splitting a same-suit run costs later reconstruction")
    if useless_king_relocate(state, action):
        penalty += 1.2
        risk_notes.append(
            "estimate: king relocate consumes the empty column without a reveal or a better landing"
        )
    structural_risk = penalty
    if action != ("deal",) and not reveals(state, action):
        try:
            life = assess_tableau_move(state, action)
        except ValueError:
            life = None
        if life is not None and not life.exit_route_bounded and life.estimated_rehandling_cost > 0:
            structural_risk += min(2.0, float(life.estimated_rehandling_cost))
            risk_notes.append(
                f"estimate: rehandling {life.estimated_rehandling_cost:.2f} is ordering-only, not a proof bound"
            )
    before_bury = ctx.bury_risk
    kind = _classify(state, action, before_bury, after)
    good_after = goodness_score(after)
    benefit = (ctx.estimate_remaining - estimate) + (good_after - goodness_score(state))
    projected = float(g + cost) + estimate + structural_risk
    evidence = [
        "estimate: projected completion uses admissible remainder plus structural signals",
        f"estimate: expected benefit {benefit:.2f}",
        f"fact: immediate corrected cost {cost}",
        f"admissible remaining after the action {admissible_remaining(after)}",
    ]
    if action != ("deal",):
        evidence.append(_incoming_note(state, action[0]))
    else:
        evidence.append(
            f"estimate: {same_suit_landings(state)} same-suit landing(s) and bury risk {before_bury}"
        )
        row = next_stock_row(state)
        landing_labels = []
        for index, card in enumerate(row or []):
            top = state.columns[index].top()
            if top is not None and top.suit == card.suit and top.rank == card.rank + 1:
                landing_labels.append(
                    f"{rank_str(card.rank)}{card.suit.upper()} onto "
                    f"{rank_str(top.rank)}{top.suit.upper()}"
                )
        if landing_labels:
            evidence.append("estimate: same-suit landing " + ", ".join(landing_labels))
    for note in ctx.notes:
        if kind in {"REVEAL", "PREPARE", "FOUNDATION"}:
            evidence.append(note)
    evidence.extend(risk_notes)
    actions: Tuple[Action, ...] = (action,)
    purpose = {
        "DEAL_NOW": "Deal the known next stock row now.",
        "PREPARE": "Make a productive join before the deal covers it.",
        "FOUNDATION": "Complete a same-suit sequence and remove it.",
        "REVEAL": "Expose a known face-down card.",
        "ZERO_COST": "Use a free whole-column transfer because its landing is better.",
        "SAME_SUIT": "Extend a same-suit run.",
        "WORKSPACE": "Create an empty column as working space.",
        "PARK": "Park temporarily where an exit is still legal.",
        "TACTICAL": "Legal step that does not yet meet a stronger objective.",
    }[kind]
    if kind == "PREPARE" and after.can_deal():
        actions = (action, ("deal",))
        purpose = "Prepare the landing, then deal. The deal stays part of this objective."
    candidate_id = f"{kind}:{format_action(action)}"
    return Candidate(
        candidate_id=candidate_id,
        kind=kind,
        purpose=purpose,
        principles=_principle_tags(kind, action, state),
        actions=actions,
        objective=None,
        immediate_cost=cost,
        cost_is_exact=True,
        expected_benefit=float(benefit),
        structural_risk=float(structural_risk),
        horizon="next stock row" if stock_rows_positive(state) else "stock empty",
        feasibility="legal now",
        evidence=tuple(evidence),
        admissible_lb=admissible_remaining(after),
        projected=projected,
        solves=after.is_solved(),
        attractiveness=good_after,
    )


def stock_rows_positive(state: SpiderState) -> bool:
    return len(state.stock) >= 10


def _defer_unhelpful_shuffles(concrete: List[Candidate]) -> None:
    """Keep a zero-benefit shuffle from delaying a deal that must happen.

    A park or tactical step with no estimated improvement does not prepare
    the incoming row. Ranking it ahead of DEAL_NOW repeats the v0.106
    failure in reverse: the controller spends moves to avoid a cost that
    the deal will pay anyway. The adjustment is ordering only.
    """

    deal = next((item for item in concrete if item.kind == "DEAL_NOW"), None)
    if deal is None:
        return
    offset = 0
    for item in concrete:
        if item.solves or item.expected_benefit > 0:
            continue
        if item.kind not in {"PARK", "TACTICAL", "WORKSPACE"}:
            continue
        offset += 1
        item.projected = max(item.projected, deal.projected + 0.01 * offset)
        item.evidence = item.evidence + (
            "estimate: no measured improvement, so this shuffle ranks behind dealing",
        )


def _dedupe(candidates: Sequence[Candidate]) -> List[Candidate]:
    best: Dict[str, Candidate] = {}
    for candidate in candidates:
        previous = best.get(candidate.candidate_id)
        if previous is None or candidate.rank_key() < previous.rank_key():
            best[candidate.candidate_id] = candidate
    return sorted(best.values(), key=lambda item: item.rank_key())


def _stretch_workspace(state: SpiderState, g: int, best_projected: float) -> Candidate:
    objective_lb = compute_objective_lower_bound(kind="CREATE_WORKSPACE", state=state)
    current_empty = empty_count(state)
    objective = StrategicObjective(
        kind=ObjectiveKind.CREATE_WORKSPACE,
        objective_id="stretch_create_workspace",
        description="Create one empty column when no one-ply move improves the estimate",
        target_key="empty_count_ge",
        target_params={"min_empty": current_empty + 1},
        hard_preconditions=("an empty column is not available yet",),
        hard_evidence=(f"fact: empty_columns={current_empty}",),
        admissible_lb=objective_lb.h_admissible,
        admissible_breakdown=objective_lb,
        heuristic_est_cost=2.0,
        heuristic_est_benefit=1.0,
        priority=PriorityComponents(workspace=1.0),
        foundation_relevance="indirect",
        workspace_relevance="primary",
        stock_relevance="none",
        explanation="Optimistic stretch. Failure is a failed objective, not proof that no workspace exists.",
    )
    return Candidate(
        candidate_id="STRETCH:create_workspace",
        kind="STRETCH",
        purpose="Search briefly for an empty column before accepting a worsening one-ply move.",
        principles=(4, 6, 17, 19, 28),
        actions=(),
        objective=objective,
        immediate_cost=0,
        cost_is_exact=False,
        expected_benefit=1.0,
        structural_risk=0.0,
        horizon="one tactical budget",
        feasibility="unproven",
        evidence=(
            "estimate: workspace value is optimistic and is not an admissible bound",
            "fact: no concrete legal move improved the heuristic estimate",
        ),
        admissible_lb=int(objective_lb.h_admissible),
        projected=best_projected - 1.0,
        solves=False,
    )


def _from_portfolio(objective: StrategicObjective, ctx: StrategicContext) -> Candidate:
    benefit = min(1.5, max(0.0, float(objective.heuristic_est_benefit)))
    cost = max(0.0, float(objective.heuristic_est_cost))
    projected = float(ctx.cumulative_g) + cost + ctx.estimate_remaining - benefit
    return Candidate(
        candidate_id=f"PORTFOLIO:{objective.objective_id}",
        kind=objective.kind.value,
        purpose=objective.description,
        principles=(1, 2, 4),
        actions=(),
        objective=objective,
        immediate_cost=int(round(cost)),
        cost_is_exact=False,
        expected_benefit=benefit,
        structural_risk=0.0,
        horizon=objective.stock_relevance or "portfolio",
        feasibility="predicate",
        evidence=(
            "estimate: portfolio benefit is capped so it cannot erase a concrete improvement",
            f"admissible objective lower bound {objective.admissible_lb}",
            objective.explanation,
        ),
        admissible_lb=int(objective.admissible_lb),
        projected=projected + 0.5,
        solves=False,
    )


def build_candidates(
    ctx: StrategicContext,
    profile: Profile,
    *,
    blocked_ids: Sequence[str] = (),
) -> List[Candidate]:
    state = ctx.state
    g = ctx.cumulative_g
    blocked = set(blocked_ids)
    concrete = [
        _score_action(state, g, action, ctx)
        for action in all_legal_actions(state)
    ]
    _defer_unhelpful_shuffles(concrete)
    improving = [item for item in concrete if item.expected_benefit > 0.05 and item.kind != "TACTICAL"]
    chosen = list(concrete)
    if not improving and concrete and empty_count(state) == 0:
        best = min(item.projected for item in concrete)
        stretch = _stretch_workspace(state, g, best)
        if stretch.candidate_id not in blocked:
            chosen.append(stretch)
    if profile.consult_portfolio:
        try:
            portfolio = generate_objective_portfolio(state, max_objectives=8)
        except Exception as exc:  # existing analyser can reject odd partial layouts
            portfolio = None
            chosen.append(
                Candidate(
                    candidate_id="PORTFOLIO:unavailable",
                    kind="NOTE",
                    purpose="Existing objective generator did not return a portfolio.",
                    principles=(),
                    actions=(),
                    objective=None,
                    immediate_cost=0,
                    cost_is_exact=True,
                    expected_benefit=0.0,
                    structural_risk=0.0,
                    horizon="",
                    feasibility="unavailable",
                    evidence=(f"fact: portfolio error {type(exc).__name__}",),
                    admissible_lb=ctx.admissible_remaining,
                    projected=10**9,
                    solves=False,
                )
            )
        if portfolio is not None:
            have = {item.kind for item in concrete}
            # Search targets stay behind concrete legal moves. An optimistic
            # portfolio benefit must not displace a move the controller can play now.
            floor = max((item.projected for item in concrete), default=float(ctx.estimate_remaining))
            extra_index = 0
            for objective in portfolio.objectives:
                if objective.kind.value in have and objective.kind != ObjectiveKind.CREATE_WORKSPACE:
                    continue
                candidate = _from_portfolio(objective, ctx)
                candidate.projected = floor + 1.0 + extra_index * 0.01
                extra_index += 1
                if candidate.candidate_id not in blocked:
                    chosen.append(candidate)
    visible = [item for item in chosen if item.candidate_id not in blocked and item.kind != "NOTE"]
    return _dedupe(visible)


def select_candidate(
    ranked: Sequence[Candidate],
    *,
    active_id: Optional[str],
    active_projected: Optional[float],
    active_open: bool,
    margin: float,
    force_id: Optional[str] = None,
) -> Tuple[Candidate, str]:
    """Pick the principal candidate.

    An open plan survives a challenger that is only marginally better.
    ``force_id`` is a dormant alternative selected by backtracking.
    """

    if not ranked:
        raise ValueError("no candidates")
    by_id = {item.candidate_id: item for item in ranked}
    if force_id and force_id in by_id:
        return by_id[force_id], "backtrack: dormant alternative"
    best = ranked[0]
    if active_open and active_id and active_projected is not None and active_id in by_id:
        held = by_id[active_id]
        if held.candidate_id == best.candidate_id:
            return held, "continued: principal objective remains best"
        from .evaluation import should_switch

        if best.expected_benefit <= 0 and not best.solves:
            return held, "held: challenger does not improve the estimate"
        if not should_switch(active_projected, best.projected, False, margin):
            return held, "held: challenger is inside the commitment margin"
        return best, "switched: challenger improved the estimate by more than the margin"
    return best, "selected: best estimated completion cost"


def context_for(state: SpiderState, g: int) -> StrategicContext:
    return build_context(state, g)
