"""Strategic objective portfolio from StrategicAnalysis (Sprint 1E).

Converts 1A–1D analysis into a SMALL, DIVERSE set of machine-testable
objectives. Diversity is required: do not globally sort and take top-N only.

Layers:
  FACTS — preconditions and target predicates
  ADMISSIBLE — objective lower bounds from lower_bounds.py
  HEURISTIC — estimated cost / benefit for ordering only

No deal-number or leaderboard constants in strategy logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Sequence, Set, Tuple

from spider.cards import rank_str
from spider.engine import SpiderState
from spider.planner.strategic_analysis import StrategicAnalysis, analyze_strategic
from spider.planner.lower_bounds import (
    LowerBoundBreakdown,
    compute_objective_lower_bound,
    compute_solution_lower_bound,
)
from spider.planner.space_lifecycle import empty_count
from spider.planner.foundation_feasibility import epoch_name


class ObjectiveKind(str, Enum):
    EXPOSE_REVEAL_PREFIX = "EXPOSE_REVEAL_PREFIX"
    CREATE_WORKSPACE = "CREATE_WORKSPACE"
    CONSOLIDATE_SAME_SUIT = "CONSOLIDATE_SAME_SUIT"
    ADVANCE_FOUNDATION = "ADVANCE_FOUNDATION"
    REMOVE_FOUNDATION = "REMOVE_FOUNDATION"
    SHAPE_STOCK_RECEIVER = "SHAPE_STOCK_RECEIVER"
    DEAL_NOW = "DEAL_NOW"


@dataclass(frozen=True)
class PriorityComponents:
    """Transparent HEURISTIC priority parts (not for proof pruning)."""

    foundation: float = 0.0
    reveal: float = 0.0
    workspace: float = 0.0
    stock: float = 0.0
    urgency: float = 0.0

    def total(self) -> float:
        return (
            self.foundation
            + self.reveal
            + self.workspace
            + self.stock
            + self.urgency
        )


@dataclass
class StrategicObjective:
    """One machine-testable strategic objective."""

    kind: ObjectiveKind
    objective_id: str
    description: str
    # FACT: target predicate
    target_key: str
    target_params: Dict
    # FACT evidence / preconditions
    hard_preconditions: Tuple[str, ...]
    hard_evidence: Tuple[str, ...]
    # ADMISSIBLE
    admissible_lb: int
    admissible_breakdown: Optional[LowerBoundBreakdown]
    # HEURISTIC
    heuristic_est_cost: float
    heuristic_est_benefit: float
    priority: PriorityComponents
    # Relevance tags
    foundation_relevance: str
    workspace_relevance: str
    stock_relevance: str
    explanation: str

    def is_satisfied(self, state: SpiderState) -> bool:
        return evaluate_target(state, self.target_key, self.target_params)

    def dedupe_key(self) -> Tuple:
        return (self.kind.value, self.target_key, _freeze(self.target_params))


@dataclass
class ObjectivePortfolio:
    """Diverse portfolio of objectives for a state."""

    objectives: Tuple[StrategicObjective, ...]
    solution_lower_bound: LowerBoundBreakdown
    generation_notes: Tuple[str, ...]

    def by_kind(self) -> Dict[str, List[StrategicObjective]]:
        out: Dict[str, List[StrategicObjective]] = {}
        for o in self.objectives:
            out.setdefault(o.kind.value, []).append(o)
        return out


def _freeze(d: Dict) -> Tuple:
    items = []
    for k in sorted(d.keys()):
        v = d[k]
        if isinstance(v, dict):
            items.append((k, _freeze(v)))
        elif isinstance(v, (list, tuple)):
            items.append((k, tuple(v)))
        else:
            items.append((k, v))
    return tuple(items)


# ---------------------------------------------------------------------------
# Target predicates (FACT)
# ---------------------------------------------------------------------------


def evaluate_target(state: SpiderState, key: str, params: Dict) -> bool:
    if key == "expose_card":
        col = params["column"]
        suit = params["suit"]
        rank = params["rank"]
        # Card is face-up in that column (or already moved away — weaker:
        # no longer face-down at original depth). Satisfaction: not face-down
        # in that column with that identity, OR present face-up somewhere.
        col_obj = state.columns[col]
        for c in col_obj.face_down:
            if c.suit == suit and c.rank == rank:
                return False
        # If it was the next-to-flip target, being face-up on this column counts
        for c in col_obj.face_up:
            if c.suit == suit and c.rank == rank:
                return True
        # Card may have been moved face-up elsewhere
        for col2 in state.columns:
            for c in col2.face_up:
                if c.suit == suit and c.rank == rank:
                    return True
        # Or in foundations
        for seq in state.foundations:
            for c in seq:
                if c.suit == suit and c.rank == rank:
                    return True
        return False

    if key == "empty_count_ge":
        return empty_count(state) >= params["min_empty"]

    if key == "same_suit_run_at_least":
        suit = params["suit"]
        min_len = params["min_len"]
        for col in state.columns:
            up = col.face_up
            i = 0
            while i < len(up):
                if up[i].suit != suit:
                    i += 1
                    continue
                j = i
                while (
                    j + 1 < len(up)
                    and up[j + 1].suit == suit
                    and up[j].rank - 1 == up[j + 1].rank
                ):
                    j += 1
                if j - i + 1 >= min_len:
                    return True
                i = j + 1
        return False

    if key == "same_suit_adjacency":
        # High card rank of suit with lower rank immediately below in face-up
        suit = params["suit"]
        high = params["high_rank"]
        low = params["low_rank"]
        for col in state.columns:
            up = col.face_up
            for i in range(len(up) - 1):
                if (
                    up[i].suit == suit
                    and up[i].rank == high
                    and up[i + 1].suit == suit
                    and up[i + 1].rank == low
                ):
                    return True
        return False

    if key == "foundations_of_suit_ge":
        suit = params["suit"]
        need = params["min_count"]
        n = 0
        for seq in state.foundations:
            if len(seq) == 13 and all(c.suit == suit for c in seq):
                n += 1
        return n >= need

    if key == "column_top_is":
        col = params["column"]
        suit = params["suit"]
        rank = params["rank"]
        top = state.columns[col].top()
        return top is not None and top.suit == suit and top.rank == rank

    if key == "column_empty":
        return state.columns[params["column"]].is_empty()

    if key == "stock_deals_remaining_le":
        return (len(state.stock) // 10) <= params["max_deals"]

    if key == "stock_epoch_advanced":
        # epoch advanced if remaining deals decreased
        return (len(state.stock) // 10) < params["deals_before"]

    return False


# ---------------------------------------------------------------------------
# Portfolio generation
# ---------------------------------------------------------------------------


def generate_objective_portfolio(
    state: SpiderState,
    *,
    analysis: Optional[StrategicAnalysis] = None,
    cards: Optional[Sequence[Card]] = None,
    max_objectives: int = 12,
) -> ObjectivePortfolio:
    """Build a diverse portfolio (~6–12) without global top-N only.

    Does NOT run expensive 1D shaping BFS (uses analysis with probe off).
    """
    if analysis is None:
        analysis = analyze_strategic(
            state, cards=cards, run_shaping_probe=False
        )

    sol_lb = compute_solution_lower_bound(state)
    raw: List[StrategicObjective] = []
    notes: List[str] = []

    # --- DEAL_NOW ---
    if len(state.stock) >= 10:
        deals_before = len(state.stock) // 10
        lb = compute_objective_lower_bound(kind="DEAL_NOW", state=state)
        raw.append(
            StrategicObjective(
                kind=ObjectiveKind.DEAL_NOW,
                objective_id="deal_now",
                description="Deal the next known stock row",
                target_key="stock_epoch_advanced",
                target_params={"deals_before": deals_before},
                hard_preconditions=("stock has at least 10 cards",),
                hard_evidence=(
                    f"fact: remaining_deals={deals_before}",
                    f"fact: next_row_same_suit_landings="
                    f"{analysis.stock_reception.row_summary.n_same_suit_landings}",
                ),
                admissible_lb=lb.h_admissible,
                admissible_breakdown=lb,
                heuristic_est_cost=1.0,
                heuristic_est_benefit=float(
                    analysis.stock_reception.row_summary.n_same_suit_landings * 3
                    + analysis.stock_reception.row_summary.n_enables_foundation_epoch
                ),
                priority=PriorityComponents(
                    stock=5.0
                    + analysis.stock_reception.row_summary.n_same_suit_landings,
                    foundation=float(
                        analysis.stock_reception.row_summary.n_enables_foundation_epoch
                    ),
                    urgency=1.0 if empty_count(state) == 0 else 0.0,
                ),
                foundation_relevance="row may enable foundations",
                workspace_relevance="deal lands on empties if any",
                stock_relevance="exact next row known",
                explanation="Always offer DEAL_NOW when legal; cost exactly 1",
            )
        )

    # --- CREATE_WORKSPACE ---
    cur_e = empty_count(state)
    lb_w = compute_objective_lower_bound(kind="CREATE_WORKSPACE", state=state)
    raw.append(
        StrategicObjective(
            kind=ObjectiveKind.CREATE_WORKSPACE,
            objective_id=f"create_workspace_{cur_e + 1}",
            description=f"Increase empty columns to at least {cur_e + 1}",
            target_key="empty_count_ge",
            target_params={"min_empty": cur_e + 1},
            hard_preconditions=(),
            hard_evidence=(f"fact: current_empty_count={cur_e}",),
            admissible_lb=lb_w.h_admissible,
            admissible_breakdown=lb_w,
            heuristic_est_cost=3.0 if cur_e == 0 else 1.5,
            heuristic_est_benefit=8.0 if cur_e == 0 else 4.0,
            priority=PriorityComponents(
                workspace=10.0 if cur_e == 0 else 4.0,
                urgency=3.0 if cur_e == 0 else 0.0,
            ),
            foundation_relevance="indirect",
            workspace_relevance="primary",
            stock_relevance="enables recoverable empties pre-deal",
            explanation="Workspace is strategic capital (Sprint 1C)",
        )
    )

    # --- EXPOSE_REVEAL_PREFIX (diversify columns; prefer high interest + short) ---
    if analysis.reveal is not None:
        # One shallow + one deep per interesting column, cap columns
        seen_cols: Set[int] = set()
        # Sort opportunities by (interest desc, length asc) for candidates
        opps = list(analysis.reveal.opportunities)
        # Take best opportunity per column
        best_by_col: Dict[int, object] = {}
        for opp in opps:
            c = opp.prefix.column
            prev = best_by_col.get(c)
            if prev is None or opp.heuristic_interest > prev.heuristic_interest:
                best_by_col[c] = opp
        # Also shallowest high-interest
        ranked_cols = sorted(
            best_by_col.values(),
            key=lambda o: (-o.heuristic_interest, o.prefix.unavoidable_reveal_count),
        )
        for opp in ranked_cols[:4]:
            p = opp.prefix
            col = p.column
            if col in seen_cols and p.unavoidable_reveal_count > 1:
                # still allow one shallow if not yet
                pass
            # Target: expose last card of prefix (deepest of the stop)
            target_card = p.cards_unlocked[-1]
            min_rev = p.unavoidable_reveal_count
            lb = compute_objective_lower_bound(
                kind="EXPOSE_REVEAL_PREFIX",
                min_reveals=min_rev,
                state=state,
            )
            oid = f"expose_c{col + 1}_d{min_rev}_{target_card}"
            raw.append(
                StrategicObjective(
                    kind=ObjectiveKind.EXPOSE_REVEAL_PREFIX,
                    objective_id=oid,
                    description=(
                        f"Expose prefix on col {col + 1} depth {min_rev}: "
                        + " -> ".join(str(c) for c in p.cards_unlocked)
                    ),
                    target_key="expose_card",
                    target_params={
                        "column": col,
                        "suit": target_card.suit,
                        "rank": target_card.rank,
                    },
                    hard_preconditions=(f"col {col + 1} has face-down chain",),
                    hard_evidence=(
                        f"fact: min_reveals={min_rev}",
                        f"fact: sequence={tuple(str(c) for c in p.cards_unlocked)}",
                        f"heuristic_interest={opp.heuristic_interest}",
                    ),
                    admissible_lb=lb.h_admissible,
                    admissible_breakdown=lb,
                    heuristic_est_cost=float(min_rev + 2),
                    heuristic_est_benefit=float(opp.heuristic_interest / 10.0),
                    priority=PriorityComponents(
                        reveal=opp.heuristic_interest / 10.0,
                        foundation=2.0
                        if any(
                            t.code.startswith("foundation")
                            for t in p.structural_tags
                        )
                        else 0.0,
                        workspace=-1.0 if empty_count(state) == 0 else 0.0,
                    ),
                    foundation_relevance="see reveal structural tags",
                    workspace_relevance="may need empty to excavate",
                    stock_relevance="none direct",
                    explanation=opp.heuristic_reasons[0]
                    if opp.heuristic_reasons
                    else "reveal chain objective",
                )
            )
            seen_cols.add(col)
            # Also add shallow (depth 1) for same column if deep > 1
            if min_rev > 1:
                c0 = p.cards_unlocked[0]
                lb1 = compute_objective_lower_bound(
                    kind="EXPOSE_REVEAL_PREFIX", min_reveals=1, state=state
                )
                raw.append(
                    StrategicObjective(
                        kind=ObjectiveKind.EXPOSE_REVEAL_PREFIX,
                        objective_id=f"expose_c{col + 1}_d1_{c0}",
                        description=f"Expose next hidden card on col {col + 1}: {c0}",
                        target_key="expose_card",
                        target_params={
                            "column": col,
                            "suit": c0.suit,
                            "rank": c0.rank,
                        },
                        hard_preconditions=(f"col {col + 1} face-down frontier",),
                        hard_evidence=(f"fact: frontier={c0}",),
                        admissible_lb=lb1.h_admissible,
                        admissible_breakdown=lb1,
                        heuristic_est_cost=2.0,
                        heuristic_est_benefit=1.5,
                        priority=PriorityComponents(reveal=3.0, urgency=1.0),
                        foundation_relevance="unknown",
                        workspace_relevance="local",
                        stock_relevance="none",
                        explanation="shallow reveal alternative for diversity",
                    )
                )

    # --- CONSOLIDATE_SAME_SUIT ---
    # From face-up tops: if we see potential extend, propose run length goal
    for suit in "cshd":
        best = 0
        for col in state.columns:
            up = col.face_up
            n = 0
            for i in range(len(up) - 1, -1, -1):
                if up[i].suit != suit:
                    break
                if n > 0 and up[i].rank - 1 != up[i + 1].rank:
                    break
                n += 1
            best = max(best, n)
        if best >= 1:
            target_len = min(13, best + 2)
            if target_len > best:
                raw.append(
                    StrategicObjective(
                        kind=ObjectiveKind.CONSOLIDATE_SAME_SUIT,
                        objective_id=f"consolidate_{suit}_L{target_len}",
                        description=(
                            f"Grow same-suit {suit} run to length >= {target_len} "
                            f"(current best {best})"
                        ),
                        target_key="same_suit_run_at_least",
                        target_params={"suit": suit, "min_len": target_len},
                        hard_preconditions=(),
                        hard_evidence=(f"fact: best_{suit}_run={best}",),
                        admissible_lb=0,
                        admissible_breakdown=None,
                        heuristic_est_cost=float(target_len - best + 1),
                        heuristic_est_benefit=float(target_len),
                        priority=PriorityComponents(
                            foundation=1.0 if best >= 3 else 0.0,
                            reveal=0.5,
                        ),
                        foundation_relevance=f"builds {suit} material",
                        workspace_relevance="may use empty as park",
                        stock_relevance="none",
                        explanation="low-regret same-suit consolidation",
                    )
                )

    # --- ADVANCE_FOUNDATION / REMOVE_FOUNDATION ---
    if analysis.foundation is not None:
        for cand in analysis.foundation.frontier.candidates:
            if cand.already_completed:
                continue
            suit = cand.suit
            # ADVANCE: increase face-up mass / longest fragment
            target_len = min(13, max(3, cand.longest_same_suit_fragment + 2))
            raw.append(
                StrategicObjective(
                    kind=ObjectiveKind.ADVANCE_FOUNDATION,
                    objective_id=f"advance_{suit}_{cand.copy_index}_L{target_len}",
                    description=(
                        f"Advance {suit.upper()}#{cand.copy_index} build: "
                        f"same-suit run >= {target_len}"
                    ),
                    target_key="same_suit_run_at_least",
                    target_params={"suit": suit, "min_len": target_len},
                    hard_preconditions=(),
                    hard_evidence=(
                        f"fact: earliest={cand.earliest_epoch}",
                        f"fact: theo_available={cand.theoretically_available}",
                        f"fact: longest_fragment={cand.longest_same_suit_fragment}",
                    ),
                    admissible_lb=0,
                    admissible_breakdown=None,
                    heuristic_est_cost=5.0,
                    heuristic_est_benefit=float(cand.heuristic_build_readiness / 10.0),
                    priority=PriorityComponents(
                        foundation=cand.heuristic_build_readiness / 10.0,
                        urgency=2.0 if cand.theoretically_available else 0.0,
                    ),
                    foundation_relevance=(
                        f"{suit.upper()}#{cand.copy_index} build "
                        f"(no fixed physical copy assignment)"
                    ),
                    workspace_relevance="as needed",
                    stock_relevance="may wait for limiting ranks",
                    explanation="; ".join(cand.facts_reasons[:2]),
                )
            )
            if cand.theoretically_available:
                have = cand.foundations_of_suit_removed
                lb_r = compute_objective_lower_bound(
                    kind="REMOVE_FOUNDATION", state=state
                )
                raw.append(
                    StrategicObjective(
                        kind=ObjectiveKind.REMOVE_FOUNDATION,
                        objective_id=f"remove_{suit}_{have + 1}",
                        description=(
                            f"Remove a complete {suit.upper()} foundation "
                            f"(need foundations_of_suit >= {have + 1})"
                        ),
                        target_key="foundations_of_suit_ge",
                        target_params={"suit": suit, "min_count": have + 1},
                        hard_preconditions=(
                            f"theoretically available since "
                            f"{epoch_name(cand.earliest_epoch) if cand.earliest_epoch is not None else '?'}",
                        ),
                        hard_evidence=(
                            f"fact: theoretically_available=True",
                            f"fact: currently_removed={have}",
                        ),
                        admissible_lb=lb_r.h_admissible,
                        admissible_breakdown=lb_r,
                        heuristic_est_cost=15.0,
                        heuristic_est_benefit=float(
                            cand.heuristic_removal_readiness / 5.0
                        ),
                        priority=PriorityComponents(
                            foundation=cand.heuristic_removal_readiness / 8.0,
                            workspace=2.0,
                        ),
                        foundation_relevance="removal when available",
                        workspace_relevance="removal can repay space",
                        stock_relevance="none",
                        explanation="removal only if theo available (hard)",
                    )
                )

    # --- SHAPE_STOCK_RECEIVER (from 1D targets; no BFS) ---
    if analysis.stock_reception.can_deal:
        # Prefer same-suit receiver targets and create empty
        added_shape = 0
        for t in analysis.stock_reception.receiver_targets:
            if t.target_code != "same_suit_receiver":
                continue
            if t.incoming.rank >= 13:
                raw.append(
                    StrategicObjective(
                        kind=ObjectiveKind.SHAPE_STOCK_RECEIVER,
                        objective_id=f"shape_empty_c{t.column + 1}",
                        description=t.reason,
                        target_key="column_empty",
                        target_params={"column": t.column},
                        hard_preconditions=("next stock row known",),
                        hard_evidence=(f"fact: incoming={t.incoming}",),
                        admissible_lb=0,
                        admissible_breakdown=None,
                        heuristic_est_cost=2.0,
                        heuristic_est_benefit=4.0,
                        priority=PriorityComponents(stock=6.0, workspace=2.0),
                        foundation_relevance=str(t.foundation_relevant),
                        workspace_relevance=str(t.workspace_relevant),
                        stock_relevance="primary",
                        explanation=t.expected_effect,
                    )
                )
            else:
                raw.append(
                    StrategicObjective(
                        kind=ObjectiveKind.SHAPE_STOCK_RECEIVER,
                        objective_id=(
                            f"shape_c{t.column + 1}_"
                            f"{rank_str(t.incoming.rank + 1)}{t.incoming.suit}"
                        ),
                        description=t.reason,
                        target_key="column_top_is",
                        target_params={
                            "column": t.column,
                            "suit": t.incoming.suit,
                            "rank": t.incoming.rank + 1,
                        },
                        hard_preconditions=("next stock row known",),
                        hard_evidence=(
                            f"fact: incoming={t.incoming}",
                            f"fact: want_top={rank_str(t.incoming.rank + 1)}{t.incoming.suit}",
                        ),
                        admissible_lb=0,
                        admissible_breakdown=None,
                        heuristic_est_cost=3.0,
                        heuristic_est_benefit=5.0
                        if t.foundation_relevant
                        else 3.0,
                        priority=PriorityComponents(
                            stock=7.0,
                            foundation=2.0 if t.foundation_relevant else 0.0,
                        ),
                        foundation_relevance=str(t.foundation_relevant),
                        workspace_relevance=str(t.workspace_relevant),
                        stock_relevance="primary",
                        explanation=t.expected_effect,
                    )
                )
            added_shape += 1
            if added_shape >= 3:
                break

    # Deduplicate
    portfolio = _diversify_and_cap(raw, max_objectives=max_objectives)
    notes.append(
        f"fact: generated {len(raw)} raw -> {len(portfolio)} diversified "
        f"(max={max_objectives})"
    )
    notes.append(
        f"fact: solution h_admissible={sol_lb.h_admissible} "
        f"(naive={sol_lb.h_naive_face_down_plus_deals} not for pruning)"
    )
    return ObjectivePortfolio(
        objectives=tuple(portfolio),
        solution_lower_bound=sol_lb,
        generation_notes=tuple(notes),
    )


def _diversify_and_cap(
    raw: Sequence[StrategicObjective], *, max_objectives: int
) -> List[StrategicObjective]:
    """Keep diversity across kinds; not global top-N only."""
    # Dedupe
    seen: Set[Tuple] = set()
    uniq: List[StrategicObjective] = []
    for o in raw:
        k = o.dedupe_key()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(o)

    by_kind: Dict[str, List[StrategicObjective]] = {}
    for o in uniq:
        by_kind.setdefault(o.kind.value, []).append(o)

    # Sort within kind by heuristic priority total
    for k in by_kind:
        by_kind[k].sort(
            key=lambda o: (
                -o.priority.total(),
                o.admissible_lb,
                o.heuristic_est_cost,
                o.objective_id,
            )
        )

    # Round-robin across kinds for diversity
    kind_order = [
        ObjectiveKind.DEAL_NOW.value,
        ObjectiveKind.CREATE_WORKSPACE.value,
        ObjectiveKind.EXPOSE_REVEAL_PREFIX.value,
        ObjectiveKind.SHAPE_STOCK_RECEIVER.value,
        ObjectiveKind.ADVANCE_FOUNDATION.value,
        ObjectiveKind.REMOVE_FOUNDATION.value,
        ObjectiveKind.CONSOLIDATE_SAME_SUIT.value,
    ]
    # Ensure all kinds present in rotation
    for k in by_kind:
        if k not in kind_order:
            kind_order.append(k)

    out: List[StrategicObjective] = []
    idx = {k: 0 for k in by_kind}
    # First pass: take 1 from each kind if available
    for k in kind_order:
        if k in by_kind and idx[k] < len(by_kind[k]) and len(out) < max_objectives:
            out.append(by_kind[k][idx[k]])
            idx[k] += 1
    # Second pass: fill remaining by global priority among leftovers
    leftovers: List[StrategicObjective] = []
    for k, lst in by_kind.items():
        leftovers.extend(lst[idx[k] :])
    leftovers.sort(
        key=lambda o: (-o.priority.total(), o.admissible_lb, o.objective_id)
    )
    for o in leftovers:
        if len(out) >= max_objectives:
            break
        out.append(o)

    return out[:max_objectives]


def format_portfolio(portfolio: ObjectivePortfolio, *, title: str = "Objectives") -> str:
    lines = [
        title,
        "=" * len(title),
        f"h_admissible={portfolio.solution_lower_bound.h_admissible} "
        f"face_down={portfolio.solution_lower_bound.face_down_count} "
        f"deals={portfolio.solution_lower_bound.remaining_deals} "
        f"naive={portfolio.solution_lower_bound.h_naive_face_down_plus_deals}",
        "",
        f"{'Kind':<22} {'LB':>3} {'estC':>5} {'ben':>5} "
        f"{'F':>4} {'S':>4} {'K':>4} Target/reason",
        "-" * 100,
    ]
    for o in portfolio.objectives:
        lines.append(
            f"{o.kind.value:<22} {o.admissible_lb:>3} "
            f"{o.heuristic_est_cost:>5.1f} {o.heuristic_est_benefit:>5.1f} "
            f"{o.priority.foundation:>4.1f} {o.priority.workspace:>4.1f} "
            f"{o.priority.stock:>4.1f} {o.description[:60]}"
        )
    for n in portfolio.generation_notes:
        lines.append(n)
    return "\n".join(lines)
