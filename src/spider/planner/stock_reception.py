"""Generic known-stock reception / pre-deal tableau shaping (Sprint 1D).

The solver knows the exact next ten stock cards and which column each lands on.
Strategic question is not only "deal now?" but:

    What low-cost tableau shape should we prefer BEFORE dealing these
    exact ten known cards?

HARD facts come from engine simulation + corrected MobilityWare cost.
HEURISTIC assessments are labelled and not for proof pruning.

No deal-number or column-special-case strategy constants.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Sequence, Set, Tuple

from spider.cards import Card, rank_str
from spider.engine import SpiderState
from spider.rules import MW_RULES, deal_cost
from spider.planner.foundation_feasibility import (
    FoundationAvailability,
    FoundationFeasibilityAnalysis,
    analyze_foundation_feasibility,
    current_stock_epoch,
    epoch_name,
)
from spider.planner.space_lifecycle import (
    ImmediateRecoveryKind,
    SpaceMoveEffect,
    WorkspaceEffectKind,
    empty_columns,
    empty_count,
    simulate_move_effect,
)


# ---------------------------------------------------------------------------
# Classifications
# ---------------------------------------------------------------------------


class LandingKind(str, Enum):
    """HARD relation of incoming card to pre-deal column top."""

    SAME_SUIT_CONNECT = "same_suit_connect"  # top.rank - 1 == card.rank, same suit
    MIXED_RANK_CONNECT = "mixed_rank_connect"  # rank connects, different suit
    NON_CONNECTING = "non_connecting"
    EMPTY_LANDING = "empty_landing"
    NO_STOCK = "no_stock"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IncomingCardFact:
    """HARD: one card of the next stock row and its destination column."""

    column: int  # 0-based
    card: Card
    deal_index_in_row: int  # 0..9 left-to-right = columns 0..9


@dataclass(frozen=True)
class ImmediateOutMove:
    """HARD: one-move relocation of the just-dealt top card."""

    src: int
    dst: int
    k: int
    corrected_mw_cost: int
    same_suit_destination: bool
    source_became_empty: bool
    workspace_effect: WorkspaceEffectKind


@dataclass(frozen=True)
class ColumnReceptionFact:
    """HARD + tagged features for one destination column of the next deal."""

    column: int
    incoming: Card
    pre_deal_top: Optional[Card]
    pre_deal_empty: bool
    pre_deal_same_suit_run_len: int  # trailing same-suit descending length
    landing: LandingKind
    post_deal_top: Card
    # After deal: legal k=1 moves of the incoming card (now top)
    immediate_out_moves: Tuple[ImmediateOutMove, ...]
    same_suit_out_count: int
    mixed_suit_out_count: int
    creates_or_extends_same_suit_run_on_landing: bool
    # Empty recovery (Sprint 1C link)
    empty_recovery: Optional[ImmediateRecoveryKind]
    # Foundation tags (conservative)
    foundation_notes: Tuple[str, ...]
    is_foundation_limiting_card: bool
    enables_foundation_this_epoch: bool
    facts_notes: Tuple[str, ...]


@dataclass(frozen=True)
class ReceptionConflict:
    """HARD conflict: two or more incoming tops share a post-deal destination."""

    destination: int
    competitors: Tuple[Tuple[int, Card], ...]  # (source_col, card)
    note: str


@dataclass(frozen=True)
class RowReceptionSummary:
    """Row-level HARD counts; joint realisability flagged separately."""

    n_same_suit_landings: int
    n_mixed_rank_landings: int
    n_non_connecting: int
    n_empty_landings: int
    n_with_immediate_out: int
    n_with_same_suit_out: int
    n_foundation_limiting: int
    n_enables_foundation_epoch: int
    conflicts: Tuple[ReceptionConflict, ...]
    joint_out_move_status: str  # exact_independent | unknown_joint | n/a
    joint_out_move_note: str


@dataclass(frozen=True)
class ReceiverTarget:
    """Candidate pre-deal shape objective for one column (not a move sequence)."""

    column: int
    incoming: Card
    target_code: str
    desired_pre_deal_top: Optional[str]  # human-readable condition
    expected_effect: str
    is_exact_predicate: bool  # True if checkable exactly on a state
    foundation_relevant: bool
    workspace_relevant: bool
    reason: str


@dataclass(frozen=True)
class PreDealShapingObjective:
    """A shaping goal for the bounded probe."""

    code: str
    description: str
    target_column: Optional[int]
    incoming: Optional[Card]
    # Predicate: (pre_deal_state) -> bool  implemented as code string keys
    predicate_key: str
    max_cost: int


@dataclass(frozen=True)
class BoundedShapingResult:
    """Result of a small pre-deal shaping probe."""

    objective: PreDealShapingObjective
    found: bool
    path: Tuple[Tuple[int, int, int], ...]  # (src,dst,k)
    path_labels: Tuple[str, ...]
    corrected_mw_cost: int
    status: str  # found | not_found_within_bound | no_stock | already_satisfied
    notes: Tuple[str, ...]


@dataclass(frozen=True)
class PrePostDealComparison:
    """HARD comparison of pre-deal vs post-deal snapshots."""

    pre_empty_count: int
    post_empty_count: int
    pre_empties: Tuple[int, ...]
    post_empties: Tuple[int, ...]
    deal_cost: int
    post_state_available: bool


@dataclass(frozen=True)
class StockReceptionAnalysis:
    """Full Sprint 1D analysis for a state."""

    can_deal: bool
    stock_remaining: int
    current_epoch: int
    epoch_after_deal: int
    incoming_row: Tuple[IncomingCardFact, ...]
    columns: Tuple[ColumnReceptionFact, ...]
    row_summary: RowReceptionSummary
    receiver_targets: Tuple[ReceiverTarget, ...]
    shaping_results: Tuple[BoundedShapingResult, ...]
    pre_post: Optional[PrePostDealComparison]
    foundation_analysis: Optional[FoundationFeasibilityAnalysis]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def next_stock_row(state: SpiderState) -> Optional[Tuple[Card, ...]]:
    """Exact next ten cards in column order 0..9, or None if cannot deal."""
    if len(state.stock) < 10:
        return None
    chunk = state.stock[-10:]
    return tuple(chunk)


def _trailing_same_suit_run_len(col) -> int:
    up = col.face_up
    if not up:
        return 0
    n = 1
    for i in range(len(up) - 2, -1, -1):
        if up[i].suit == up[i + 1].suit and up[i].rank - 1 == up[i + 1].rank:
            n += 1
        else:
            break
    return n


def _landing_kind(pre_top: Optional[Card], incoming: Card, pre_empty: bool) -> LandingKind:
    if pre_empty:
        return LandingKind.EMPTY_LANDING
    assert pre_top is not None
    if pre_top.rank - 1 == incoming.rank:
        if pre_top.suit == incoming.suit:
            return LandingKind.SAME_SUIT_CONNECT
        return LandingKind.MIXED_RANK_CONNECT
    return LandingKind.NON_CONNECTING


def _foundations_removed(state: SpiderState) -> Dict[str, int]:
    counts: Dict[str, int] = {"s": 0, "h": 0, "d": 0, "c": 0}
    for seq in state.foundations:
        if len(seq) == 13 and all(c.suit == seq[0].suit for c in seq):
            counts[seq[0].suit] = counts.get(seq[0].suit, 0) + 1
    return counts


def _foundation_tags_for_card(
    card: Card,
    *,
    epoch_before: int,
    epoch_after: int,
    availability: Sequence[FoundationAvailability],
    foundations_removed: Dict[str, int],
) -> Tuple[Tuple[str, ...], bool, bool]:
    """Return (notes, is_limiting, enables_foundation_this_epoch)."""
    notes: List[str] = []
    is_limiting = False
    enables = False
    for a in availability:
        if a.suit != card.suit:
            continue
        if foundations_removed.get(a.suit, 0) >= a.copy_index:
            continue
        label = f"{a.suit.upper()}#{a.copy_index}"
        if a.earliest_epoch is None:
            continue
        # Limiting ranks for earliest epoch
        if card.rank in a.limiting_ranks and a.earliest_epoch == epoch_after:
            # card rank limited the jump to epoch_after
            if epoch_before < a.earliest_epoch <= epoch_after:
                is_limiting = True
                notes.append(
                    f"fact: {card} is among limiting ranks for {label} "
                    f"(earliest {epoch_name(a.earliest_epoch)})"
                )
        # Completing theoretical availability at this deal
        if epoch_before < a.earliest_epoch <= epoch_after:
            # Check if this rank was short before deal
            counts_before = a.cumulative_counts_by_epoch[
                min(epoch_before, len(a.cumulative_counts_by_epoch) - 1)
            ]
            need = a.copy_index
            if counts_before[card.rank - 1] < need:
                enables = True
                notes.append(
                    f"fact: {card} contributes to {label} becoming theoretically "
                    f"available at {epoch_name(a.earliest_epoch)}"
                )
        elif a.earliest_epoch <= epoch_before:
            notes.append(
                f"fact: {card} contributes to already-available {label} rank demand"
            )
        else:
            notes.append(
                f"fact: {card} is for {label} (first available {epoch_name(a.earliest_epoch)})"
            )
    if not notes:
        notes.append("fact: no incomplete foundation candidate tags for this suit")
    return tuple(notes), is_limiting, enables


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------


def analyze_stock_reception(
    state: SpiderState,
    *,
    cards: Optional[Sequence[Card]] = None,
    foundation_analysis: Optional[FoundationFeasibilityAnalysis] = None,
    shaping_max_cost: int = 3,
    run_shaping_probe: bool = True,
) -> StockReceptionAnalysis:
    """Analyse next-stock reception and optional bounded pre-deal shaping."""
    stock_rem = len(state.stock)
    row = next_stock_row(state)
    deal_legal = state.can_deal(MW_RULES)

    fa = foundation_analysis
    if fa is None and cards is not None:
        fa = analyze_foundation_feasibility(cards, state)

    if fa is not None:
        epoch_before = fa.current_epoch
        deals_total = fa.stock_deals_total
        availability = fa.static_availability
    else:
        deals_total = 5
        epoch_before = current_stock_epoch(state, deals_total)
        availability = ()

    epoch_after = epoch_before + 1 if row is not None else epoch_before
    foundations_removed = _foundations_removed(state)

    if row is None:
        empty_sum = RowReceptionSummary(
            n_same_suit_landings=0,
            n_mixed_rank_landings=0,
            n_non_connecting=0,
            n_empty_landings=0,
            n_with_immediate_out=0,
            n_with_same_suit_out=0,
            n_foundation_limiting=0,
            n_enables_foundation_epoch=0,
            conflicts=(),
            joint_out_move_status="n/a",
            joint_out_move_note="fact: cannot deal",
        )
        return StockReceptionAnalysis(
            can_deal=False,
            stock_remaining=stock_rem,
            current_epoch=epoch_before,
            epoch_after_deal=epoch_before,
            incoming_row=(),
            columns=(),
            row_summary=empty_sum,
            receiver_targets=(),
            shaping_results=(),
            pre_post=None,
            foundation_analysis=fa,
        )

    incoming_facts = tuple(
        IncomingCardFact(column=i, card=row[i], deal_index_in_row=i)
        for i in range(10)
    )

    # Simulate the exact incoming row once under the active rules profile.
    st_post = state.clone()
    dcost = st_post.deal(MW_RULES)
    assert dcost == deal_cost()

    col_facts: List[ColumnReceptionFact] = []
    for i in range(10):
        pre_col = state.columns[i]
        pre_empty = pre_col.is_empty()
        pre_top = pre_col.top()
        run_len = _trailing_same_suit_run_len(pre_col)
        inc = row[i]
        landing = _landing_kind(pre_top, inc, pre_empty)
        post_top = st_post.columns[i].top()
        assert post_top is not None

        # Immediate out-moves of top card
        out_moves: List[ImmediateOutMove] = []
        for src, dst, k in st_post.enumerate_moves():
            if src != i or k != 1:
                continue
            eff = simulate_move_effect(st_post, src, dst, k)
            dest_top = st_post.columns[dst].top()
            # Before move, dest top for same-suit check: if empty, not same-suit dest
            same_suit_dest = False
            if not st_post.columns[dst].is_empty():
                # top is dest_top; run attaches if dest_top.rank-1 == inc.rank
                same_suit_dest = dest_top is not None and dest_top.suit == inc.suit
            out_moves.append(
                ImmediateOutMove(
                    src=src,
                    dst=dst,
                    k=k,
                    corrected_mw_cost=eff.corrected_mw_cost,
                    same_suit_destination=same_suit_dest,
                    source_became_empty=eff.source_became_empty,
                    workspace_effect=eff.effect,
                )
            )

        ss_out = sum(1 for m in out_moves if m.same_suit_destination)
        mx_out = len(out_moves) - ss_out

        extends = landing == LandingKind.SAME_SUIT_CONNECT

        empty_rec: Optional[ImmediateRecoveryKind] = None
        if pre_empty:
            if out_moves:
                empty_rec = ImmediateRecoveryKind.RECOVERS_SAME_COLUMN
            else:
                empty_rec = ImmediateRecoveryKind.NO_LEGAL_ONE_MOVE

        fnotes, is_lim, enables = _foundation_tags_for_card(
            inc,
            epoch_before=epoch_before,
            epoch_after=epoch_after,
            availability=availability,
            foundations_removed=foundations_removed,
        )

        facts: List[str] = [
            f"fact: incoming {inc} -> col {i + 1}",
            f"fact: landing={landing.value}",
            f"fact: pre_top={pre_top}",
            f"fact: immediate_out_dests={[m.dst + 1 for m in out_moves]}",
        ]
        col_facts.append(
            ColumnReceptionFact(
                column=i,
                incoming=inc,
                pre_deal_top=pre_top,
                pre_deal_empty=pre_empty,
                pre_deal_same_suit_run_len=run_len,
                landing=landing,
                post_deal_top=post_top,
                immediate_out_moves=tuple(out_moves),
                same_suit_out_count=ss_out,
                mixed_suit_out_count=mx_out,
                creates_or_extends_same_suit_run_on_landing=extends,
                empty_recovery=empty_rec,
                foundation_notes=fnotes,
                is_foundation_limiting_card=is_lim,
                enables_foundation_this_epoch=enables,
                facts_notes=tuple(facts),
            )
        )

    # Conflicts: destinations competed for by multiple incoming tops
    dest_map: Dict[int, List[Tuple[int, Card]]] = {}
    for cf in col_facts:
        for m in cf.immediate_out_moves:
            dest_map.setdefault(m.dst, []).append((cf.column, cf.incoming))
    conflicts: List[ReceptionConflict] = []
    for dst, comps in sorted(dest_map.items()):
        # unique sources
        uniq: Dict[int, Card] = {}
        for col, card in comps:
            uniq[col] = card
        if len(uniq) >= 2:
            conflicts.append(
                ReceptionConflict(
                    destination=dst,
                    competitors=tuple((c, uniq[c]) for c in sorted(uniq)),
                    note=(
                        f"fact: columns {[c+1 for c in sorted(uniq)]} all have a "
                        f"one-move out to col {dst + 1}; joint success not assumed"
                    ),
                )
            )

    n_ss = sum(1 for c in col_facts if c.landing == LandingKind.SAME_SUIT_CONNECT)
    n_mx = sum(1 for c in col_facts if c.landing == LandingKind.MIXED_RANK_CONNECT)
    n_nc = sum(1 for c in col_facts if c.landing == LandingKind.NON_CONNECTING)
    n_em = sum(1 for c in col_facts if c.landing == LandingKind.EMPTY_LANDING)
    n_out = sum(1 for c in col_facts if c.immediate_out_moves)
    n_ss_out = sum(1 for c in col_facts if c.same_suit_out_count > 0)
    n_lim = sum(1 for c in col_facts if c.is_foundation_limiting_card)
    n_en = sum(1 for c in col_facts if c.enables_foundation_this_epoch)

    if conflicts:
        joint_status = "unknown_joint"
        joint_note = (
            f"heuristic/unknown: {len(conflicts)} destination conflict(s); "
            "do not count all out-moves as simultaneously realisable"
        )
    elif n_out <= 1:
        joint_status = "exact_trivial"
        joint_note = "fact: at most one column has an immediate out-move"
    else:
        joint_status = "unknown_joint"
        joint_note = (
            "heuristic/unknown: multiple independent-looking out-moves; "
            "joint legality not simulated"
        )

    row_summary = RowReceptionSummary(
        n_same_suit_landings=n_ss,
        n_mixed_rank_landings=n_mx,
        n_non_connecting=n_nc,
        n_empty_landings=n_em,
        n_with_immediate_out=n_out,
        n_with_same_suit_out=n_ss_out,
        n_foundation_limiting=n_lim,
        n_enables_foundation_epoch=n_en,
        conflicts=tuple(conflicts),
        joint_out_move_status=joint_status,
        joint_out_move_note=joint_note,
    )

    targets = _generate_receiver_targets(state, tuple(col_facts))
    shaping: Tuple[BoundedShapingResult, ...] = ()
    if run_shaping_probe:
        shaping = tuple(
            run_bounded_shaping_probe(
                state, obj, max_cost=shaping_max_cost
            )
            for obj in _default_shaping_objectives(tuple(col_facts), shaping_max_cost)
        )

    pre_post = PrePostDealComparison(
        pre_empty_count=empty_count(state),
        post_empty_count=empty_count(st_post),
        pre_empties=empty_columns(state),
        post_empties=empty_columns(st_post),
        deal_cost=dcost,
        post_state_available=deal_legal,
    )

    return StockReceptionAnalysis(
        can_deal=deal_legal,
        stock_remaining=stock_rem,
        current_epoch=epoch_before,
        epoch_after_deal=epoch_after,
        incoming_row=incoming_facts,
        columns=tuple(col_facts),
        row_summary=row_summary,
        receiver_targets=targets,
        shaping_results=shaping,
        pre_post=pre_post,
        foundation_analysis=fa,
    )


def _generate_receiver_targets(
    state: SpiderState, cols: Sequence[ColumnReceptionFact]
) -> Tuple[ReceiverTarget, ...]:
    targets: List[ReceiverTarget] = []
    for c in cols:
        inc = c.incoming
        if c.landing != LandingKind.SAME_SUIT_CONNECT:
            targets.append(
                ReceiverTarget(
                    column=c.column,
                    incoming=inc,
                    target_code="same_suit_receiver",
                    desired_pre_deal_top=(
                        f"top == {rank_str(inc.rank + 1)}{inc.suit}"
                        if inc.rank < 13
                        else "empty (King)"
                    ),
                    expected_effect="same-suit one-rank landing on deal",
                    is_exact_predicate=True,
                    foundation_relevant=c.is_foundation_limiting_card
                    or c.enables_foundation_this_epoch,
                    workspace_relevant=False,
                    reason=(
                        f"incoming {inc} currently {c.landing.value}; "
                        f"prefer same-suit receiver {rank_str(inc.rank + 1) if inc.rank < 13 else 'empty'}{inc.suit if inc.rank < 13 else ''}"
                    ),
                )
            )
        if c.landing == LandingKind.MIXED_RANK_CONNECT:
            targets.append(
                ReceiverTarget(
                    column=c.column,
                    incoming=inc,
                    target_code="avoid_mixed_boundary",
                    desired_pre_deal_top="different top or same-suit alternative",
                    expected_effect="avoid mixed-suit rank boundary under incoming",
                    is_exact_predicate=False,
                    foundation_relevant=False,
                    workspace_relevant=False,
                    reason=f"incoming {inc} forms mixed boundary on {c.pre_deal_top}",
                )
            )
        if c.pre_deal_empty:
            targets.append(
                ReceiverTarget(
                    column=c.column,
                    incoming=inc,
                    target_code="recoverable_empty",
                    desired_pre_deal_top="empty with post-deal out-move for incoming",
                    expected_effect="preserve recoverable workspace through deal",
                    is_exact_predicate=True,
                    foundation_relevant=False,
                    workspace_relevant=True,
                    reason=f"col {c.column + 1} empty; ensure {inc} can leave after deal",
                )
            )
        if not c.immediate_out_moves and c.landing == LandingKind.EMPTY_LANDING:
            targets.append(
                ReceiverTarget(
                    column=c.column,
                    incoming=inc,
                    target_code="prepare_out_destination",
                    desired_pre_deal_top="create a legal dest for the incoming card",
                    expected_effect="incoming can immediately leave empty after deal",
                    is_exact_predicate=False,
                    foundation_relevant=False,
                    workspace_relevant=True,
                    reason=f"{inc} lands on empty with no immediate out",
                )
            )
    return tuple(targets)


def _default_shaping_objectives(
    cols: Sequence[ColumnReceptionFact], max_cost: int
) -> Tuple[PreDealShapingObjective, ...]:
    objs: List[PreDealShapingObjective] = []
    for c in cols:
        if c.landing == LandingKind.SAME_SUIT_CONNECT:
            continue
        if c.incoming.rank >= 13:
            # King wants empty
            objs.append(
                PreDealShapingObjective(
                    code="king_empty_receiver",
                    description=f"make col {c.column + 1} empty for King {c.incoming}",
                    target_column=c.column,
                    incoming=c.incoming,
                    predicate_key="column_empty",
                    max_cost=max_cost,
                )
            )
        else:
            objs.append(
                PreDealShapingObjective(
                    code="same_suit_receiver",
                    description=(
                        f"top of col {c.column + 1} = "
                        f"{rank_str(c.incoming.rank + 1)}{c.incoming.suit} "
                        f"for incoming {c.incoming}"
                    ),
                    target_column=c.column,
                    incoming=c.incoming,
                    predicate_key="same_suit_receiver",
                    max_cost=max_cost,
                )
            )
        # Cap number of objectives for speed
        if len(objs) >= 6:
            break
    # Also try create one empty if none
    if sum(1 for c in cols if c.pre_deal_empty) == 0:
        objs.append(
            PreDealShapingObjective(
                code="create_one_empty",
                description="create at least one empty column before deal",
                target_column=None,
                incoming=None,
                predicate_key="has_empty",
                max_cost=max_cost,
            )
        )
    return tuple(objs)


def _predicate_holds(
    state: SpiderState, obj: PreDealShapingObjective
) -> bool:
    if obj.predicate_key == "has_empty":
        return empty_count(state) >= 1
    if obj.predicate_key == "column_empty":
        assert obj.target_column is not None
        return state.columns[obj.target_column].is_empty()
    if obj.predicate_key == "same_suit_receiver":
        assert obj.target_column is not None and obj.incoming is not None
        top = state.columns[obj.target_column].top()
        inc = obj.incoming
        if inc.rank >= 13:
            return state.columns[obj.target_column].is_empty()
        return (
            top is not None
            and top.suit == inc.suit
            and top.rank - 1 == inc.rank
        )
    return False


def run_bounded_shaping_probe(
    state: SpiderState,
    objective: PreDealShapingObjective,
    *,
    max_cost: Optional[int] = None,
) -> BoundedShapingResult:
    """BFS over legal moves with corrected MW cost <= bound.

    Failure means not found within bound, NOT impossible.
    """
    bound = max_cost if max_cost is not None else objective.max_cost
    if _predicate_holds(state, objective):
        return BoundedShapingResult(
            objective=objective,
            found=True,
            path=(),
            path_labels=(),
            corrected_mw_cost=0,
            status="already_satisfied",
            notes=("fact: pre-deal state already satisfies objective",),
        )

    # BFS by paid cost; free moves expand at same cost
    from collections import deque

    # state key: simple structural fingerprint
    def sk(st: SpiderState) -> tuple:
        parts = []
        for c in st.columns:
            parts.append(
                (
                    tuple((x.suit, x.rank) for x in c.face_down),
                    tuple((x.suit, x.rank) for x in c.face_up),
                )
            )
        return (tuple(parts), len(st.stock), len(st.foundations))

    # queue items: (cost, state, path)
    q: deque = deque()
    q.append((0, state.clone(), ()))
    seen: Dict[tuple, int] = {sk(state): 0}
    expanded = 0
    max_expand = 4000  # hard cap for diagnostic speed

    while q:
        cost, st, path = q.popleft()
        expanded += 1
        if expanded > max_expand:
            break
        if cost > bound:
            continue
        for src, dst, k in st.enumerate_moves():
            st2 = st.clone()
            try:
                c2 = st2.move(src, dst, k, rules=MW_RULES)
            except Exception:
                continue
            ncost = cost + c2
            if ncost > bound:
                continue
            npath = path + ((src, dst, k),)
            key = sk(st2)
            if key in seen and seen[key] <= ncost:
                continue
            seen[key] = ncost
            if _predicate_holds(st2, objective):
                labels = tuple(f"move {s+1} {d+1} {kk}" for s, d, kk in npath)
                return BoundedShapingResult(
                    objective=objective,
                    found=True,
                    path=npath,
                    path_labels=labels,
                    corrected_mw_cost=ncost,
                    status="found",
                    notes=(
                        f"fact: found within corrected cost {ncost} <= {bound}",
                        f"fact: expanded={expanded} nodes",
                    ),
                )
            q.append((ncost, st2, npath))

    return BoundedShapingResult(
        objective=objective,
        found=False,
        path=(),
        path_labels=(),
        corrected_mw_cost=-1,
        status="not_found_within_bound",
        notes=(
            f"fact: no path found within corrected cost <= {bound}",
            "fact: this does NOT prove impossibility",
            f"fact: expanded={expanded} nodes, seen={len(seen)}",
        ),
    )


def apply_deal_and_compare(state: SpiderState) -> Tuple[SpiderState, PrePostDealComparison]:
    """Clone, deal, return post state and comparison."""
    pre_e = empty_columns(state)
    st = state.clone()
    if not st.can_deal(MW_RULES):
        return st, PrePostDealComparison(
            pre_empty_count=len(pre_e),
            post_empty_count=len(pre_e),
            pre_empties=pre_e,
            post_empties=pre_e,
            deal_cost=0,
            post_state_available=False,
        )
    dcost = st.deal()
    return st, PrePostDealComparison(
        pre_empty_count=len(pre_e),
        post_empty_count=empty_count(st),
        pre_empties=pre_e,
        post_empties=empty_columns(st),
        deal_cost=dcost,
        post_state_available=True,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def format_reception_report(
    analysis: StockReceptionAnalysis,
    *,
    title: str = "Stock reception",
) -> str:
    lines = [
        title,
        "=" * len(title),
        f"can_deal={analysis.can_deal} stock={analysis.stock_remaining} "
        f"epoch {analysis.current_epoch}->{analysis.epoch_after_deal}",
    ]
    if not analysis.can_deal:
        lines.append("(no next stock row)")
        return "\n".join(lines)

    row = " ".join(str(f.card) for f in analysis.incoming_row)
    lines.append(f"incoming row (cols 1-10): {row}")
    lines.append("")
    lines.append("PER-COLUMN RECEPTION (HARD)")
    for c in analysis.columns:
        pre = str(c.pre_deal_top) if c.pre_deal_top else "empty"
        outs = [m.dst + 1 for m in c.immediate_out_moves]
        lines.append(
            f"  col {c.column + 1}: {pre} <- {c.incoming}  "
            f"[{c.landing.value}] outs->{outs} "
            f"ss_out={c.same_suit_out_count} "
            f"lim={c.is_foundation_limiting_card} en={c.enables_foundation_this_epoch}"
        )

    s = analysis.row_summary
    lines.append("")
    lines.append("ROW SUMMARY")
    lines.append(
        f"  same_suit={s.n_same_suit_landings} mixed={s.n_mixed_rank_landings} "
        f"non_connect={s.n_non_connecting} empty_land={s.n_empty_landings}"
    )
    lines.append(
        f"  immediate_out={s.n_with_immediate_out} "
        f"same_suit_out={s.n_with_same_suit_out} "
        f"foundation_limiting={s.n_foundation_limiting} "
        f"enables_epoch={s.n_enables_foundation_epoch}"
    )
    lines.append(f"  joint: {s.joint_out_move_status} — {s.joint_out_move_note}")
    if s.conflicts:
        for conf in s.conflicts:
            lines.append(f"  CONFLICT dest col {conf.destination + 1}: {conf.note}")

    lines.append("")
    lines.append("BOUNDED SHAPING PROBE")
    if not analysis.shaping_results:
        lines.append("  (not run)")
    for r in analysis.shaping_results:
        if r.found:
            lines.append(
                f"  FOUND {r.objective.code} cost={r.corrected_mw_cost} "
                f"path={list(r.path_labels)} [{r.status}]"
            )
        else:
            lines.append(
                f"  MISS  {r.objective.code} [{r.status}] "
                f"{r.objective.description}"
            )

    if analysis.pre_post:
        pp = analysis.pre_post
        lines.append("")
        lines.append(
            f"PRE/POST empties {pp.pre_empty_count}->{pp.post_empty_count} "
            f"deal_cost={pp.deal_cost}"
        )
    return "\n".join(lines)
