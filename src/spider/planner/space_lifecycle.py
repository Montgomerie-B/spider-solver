"""Generic empty-column lifecycle / recoverability analysis (Sprint 1C).

An empty tableau column is working space, not merely another legal destination.

Lifecycle:
    create -> use -> consume/relocate -> recover/replace -> carry through stock -> reuse

HARD FACTS (exact simulation with existing engine + corrected MobilityWare cost)
are kept separate from HEURISTIC / UNKNOWN assessments.

This module does NOT reimplement move legality or costing. It uses
``SpiderState.enumerate_moves``, ``SpiderState.move`` / ``deal``, and the
corrected ``MW_RULES`` path already implemented in ``engine`` / ``rules``.

No deal-number, column, or leaderboard constants in strategy logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Sequence, Set, Tuple

from spider.cards import Card, rank_str
from spider.engine import SpiderState
from spider.rules import MW_RULES, deal_cost

# Optional integration with prior sprints
from spider.planner.reveal_graph import (
    RevealGraphAnalysis,
    RevealOpportunity,
    analyze_reveal_graph,
)


# ---------------------------------------------------------------------------
# Classifications (HARD)
# ---------------------------------------------------------------------------


class WorkspaceEffectKind(str, Enum):
    """HARD classification of how a move changes empty-column *count* / location."""

    CREATES = "creates"  # empty count increases
    CONSUMES = "consumes"  # empty count decreases
    RELOCATES = "relocates"  # empty count preserved; dest empty, source emptied
    PRESERVES = "preserves"  # empty count unchanged, not a clean relocation
    OTHER = "other"  # unexpected / foundation-dominated edge cases


class ImmediateRecoveryKind(str, Enum):
    """HARD one-move post-deal recovery classification for a pre-deal empty."""

    RECOVERS_SAME_COLUMN = "recovers_same_column"
    MOVES_ELSEWHERE_NO_RECOVERY = "moves_elsewhere_no_same_column_recovery"
    NO_LEGAL_ONE_MOVE = "no_legal_one_move"
    NO_STOCK_REMAINING = "no_stock_remaining"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpaceFact:
    """HARD snapshot of current workspace."""

    empty_columns: Tuple[int, ...]  # 0-based, sorted
    empty_count: int
    fully_open_nonempty: Tuple[int, ...]  # face_down empty, face_up non-empty
    columns_with_face_down: Tuple[int, ...]
    fully_face_up_not_one_move_emptyable: Tuple[int, ...]
    """Fully open columns that cannot currently become empty via one legal move."""


@dataclass(frozen=True)
class SpaceMoveEffect:
    """HARD: exact effect of one legal move, established by simulation."""

    src: int
    dst: int
    k: int
    corrected_mw_cost: int
    empty_before: int
    empty_after: int
    empties_before: Tuple[int, ...]
    empties_after: Tuple[int, ...]
    dest_was_empty: bool
    source_fully_open_before: bool
    source_face_down_before: int
    source_became_empty: bool
    flipped: bool
    foundation_removal: bool
    effect: WorkspaceEffectKind
    notes: Tuple[str, ...]


@dataclass(frozen=True)
class SpaceCreationOpportunity:
    """HARD: legal one-move that increases empty-column count."""

    move: SpaceMoveEffect


@dataclass(frozen=True)
class SpaceConsumptionFact:
    """HARD: legal move into empty that reduces empty count."""

    move: SpaceMoveEffect


@dataclass(frozen=True)
class SpaceRelocationFact:
    """HARD: legal move that preserves empty count by emptying source into empty dest."""

    move: SpaceMoveEffect


@dataclass(frozen=True)
class PostDealColumnRecovery:
    """HARD facts about one pre-deal empty column after the next stock deal."""

    column: int
    incoming_card: Card
    legal_destinations: Tuple[int, ...]  # one-move k=1 destinations after deal
    one_move_options: Tuple[SpaceMoveEffect, ...]  # simulated moves of the top card
    immediate_recovery: ImmediateRecoveryKind
    # Best one-move option that restores this column empty, if any
    recovery_move: Optional[SpaceMoveEffect]
    notes: Tuple[str, ...]


@dataclass(frozen=True)
class SpaceRecoveryForecast:
    """Next-stock space recoverability analysis.

    Per-column one-move recovery is HARD when simulated.
    Simultaneous multi-space recovery is HEURISTIC/UNKNOWN unless proved.
    """

    stock_remaining_before: int
    can_deal: bool
    pre_deal_empties: Tuple[int, ...]
    post_deal_tops_on_pre_empties: Tuple[Tuple[int, Card], ...]
    per_column: Tuple[PostDealColumnRecovery, ...]
    # HEURISTIC / UNKNOWN
    simultaneous_recovery_status: str
    simultaneous_recovery_note: str


@dataclass(frozen=True)
class RevealWorkspaceContext:
    """HARD + labelled heuristic linkage from a reveal opportunity to workspace."""

    column: int
    stop_reveal_order: int
    unavoidable_reveal_count: int
    cards_unlocked: Tuple[Card, ...]
    face_up_blocker_count: int
    face_up_blockers: Tuple[Card, ...]
    empty_count_now: int
    exhausts_face_down: bool
    would_be_fully_open_after_prefix: bool
    # Immediate legal moves that begin excavation (any move of face-up from column)
    immediate_excavation_moves: Tuple[SpaceMoveEffect, ...]
    can_start_with_existing_empty: bool
    # HEURISTIC labels only
    heuristic_workspace_burden: str
    heuristic_recovery_outlook: str
    heuristic_notes: Tuple[str, ...]


@dataclass(frozen=True)
class SpaceLifecycleAnalysis:
    """Full Sprint 1C analysis for a state."""

    workspace: SpaceFact
    all_move_effects: Tuple[SpaceMoveEffect, ...]
    creation_opportunities: Tuple[SpaceCreationOpportunity, ...]
    consumption_moves: Tuple[SpaceConsumptionFact, ...]
    relocation_moves: Tuple[SpaceRelocationFact, ...]
    foundation_space_effects: Tuple[SpaceMoveEffect, ...]
    next_stock_recovery: SpaceRecoveryForecast
    reveal_contexts: Tuple[RevealWorkspaceContext, ...]
    # optional free-move validation samples (HARD)
    zero_cost_full_column_relocations: Tuple[SpaceMoveEffect, ...]
    paid_faceup_to_empty_with_face_down: Tuple[SpaceMoveEffect, ...]


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def empty_columns(state: SpiderState) -> Tuple[int, ...]:
    return tuple(i for i, c in enumerate(state.columns) if c.is_empty())


def empty_count(state: SpiderState) -> int:
    return len(empty_columns(state))


def fully_open_nonempty(state: SpiderState) -> Tuple[int, ...]:
    return tuple(
        i
        for i, c in enumerate(state.columns)
        if (not c.face_down) and c.face_up
    )


def columns_with_face_down(state: SpiderState) -> Tuple[int, ...]:
    return tuple(i for i, c in enumerate(state.columns) if c.face_down)


def _classify_effect(
    *,
    empty_before: int,
    empty_after: int,
    dest_was_empty: bool,
    source_became_empty: bool,
    foundation_removal: bool,
) -> Tuple[WorkspaceEffectKind, Tuple[str, ...]]:
    notes: List[str] = []
    if foundation_removal:
        notes.append("fact: automatic foundation removal occurred (cost 0 extra)")
    delta = empty_after - empty_before
    if delta > 0:
        notes.append(f"fact: empty count {empty_before} -> {empty_after} (created)")
        return WorkspaceEffectKind.CREATES, tuple(notes)
    if delta < 0:
        notes.append(f"fact: empty count {empty_before} -> {empty_after} (consumed)")
        return WorkspaceEffectKind.CONSUMES, tuple(notes)
    # count preserved
    if dest_was_empty and source_became_empty:
        notes.append(
            "fact: empty count preserved; workspace RELOCATED "
            "(dest was empty and source became empty)"
        )
        return WorkspaceEffectKind.RELOCATES, tuple(notes)
    if dest_was_empty and not source_became_empty:
        # Should usually consume; if count preserved, foundation or other effect
        notes.append(
            "fact: empty count preserved despite move into empty without emptying source"
        )
        return WorkspaceEffectKind.OTHER, tuple(notes)
    notes.append("fact: empty count unchanged (preserve)")
    return WorkspaceEffectKind.PRESERVES, tuple(notes)


def simulate_move_effect(
    state: SpiderState, src: int, dst: int, k: int
) -> SpaceMoveEffect:
    """Clone, apply move with corrected MW cost, classify workspace effect."""
    empties_b = empty_columns(state)
    empty_b = len(empties_b)
    src_col = state.columns[src]
    dst_col = state.columns[dst]
    dest_was_empty = dst_col.is_empty()
    source_fully_open = len(src_col.face_down) == 0
    source_fd = len(src_col.face_down)

    st2 = state.clone()
    cost = st2.move(src, dst, k, rules=MW_RULES)
    lm = st2.last_move
    flipped = bool(lm and lm[3])
    foundation_removal = bool(lm and lm[4])
    empties_a = empty_columns(st2)
    empty_a = len(empties_a)
    source_became_empty = st2.columns[src].is_empty()

    effect, notes = _classify_effect(
        empty_before=empty_b,
        empty_after=empty_a,
        dest_was_empty=dest_was_empty,
        source_became_empty=source_became_empty,
        foundation_removal=foundation_removal,
    )
    extra: List[str] = list(notes)
    if dest_was_empty and source_fully_open and k == len(src_col.face_up) and source_fd == 0:
        extra.append(
            f"fact: full open column relocate to empty; corrected MW cost={cost}"
        )
    if dest_was_empty and source_fd > 0 and k == len(src_col.face_up):
        extra.append(
            f"fact: entire face-up moved to empty with face-down remaining; "
            f"NOT free full-column rule; corrected MW cost={cost}"
        )
    if flipped:
        extra.append("fact: hidden card exposed on source")

    return SpaceMoveEffect(
        src=src,
        dst=dst,
        k=k,
        corrected_mw_cost=cost,
        empty_before=empty_b,
        empty_after=empty_a,
        empties_before=empties_b,
        empties_after=empties_a,
        dest_was_empty=dest_was_empty,
        source_fully_open_before=source_fully_open,
        source_face_down_before=source_fd,
        source_became_empty=source_became_empty,
        flipped=flipped,
        foundation_removal=foundation_removal,
        effect=effect,
        notes=tuple(extra),
    )


def analyze_all_move_effects(state: SpiderState) -> Tuple[SpaceMoveEffect, ...]:
    effects: List[SpaceMoveEffect] = []
    for src, dst, k in state.enumerate_moves():
        effects.append(simulate_move_effect(state, src, dst, k))
    return tuple(effects)


def _fully_open_not_one_move_emptyable(
    state: SpiderState, effects: Sequence[SpaceMoveEffect]
) -> Tuple[int, ...]:
    open_cols = set(fully_open_nonempty(state))
    can_empty: Set[int] = set()
    for e in effects:
        if e.source_became_empty and e.src in open_cols:
            can_empty.add(e.src)
    return tuple(sorted(open_cols - can_empty))


# ---------------------------------------------------------------------------
# Next-stock recoverability
# ---------------------------------------------------------------------------


def analyze_next_stock_recovery(state: SpiderState) -> SpaceRecoveryForecast:
    pre_empties = empty_columns(state)
    stock_rem = len(state.stock)
    if stock_rem < 10:
        # No deal possible; per-column rows omitted (no incoming cards).
        return SpaceRecoveryForecast(
            stock_remaining_before=stock_rem,
            can_deal=False,
            pre_deal_empties=pre_empties,
            post_deal_tops_on_pre_empties=(),
            per_column=(),
            simultaneous_recovery_status="not_applicable",
            simultaneous_recovery_note="fact: no stock deal remaining",
        )

    if not state.can_deal():
        return SpaceRecoveryForecast(
            stock_remaining_before=stock_rem,
            can_deal=False,
            pre_deal_empties=pre_empties,
            post_deal_tops_on_pre_empties=(),
            per_column=(),
            simultaneous_recovery_status="blocked_by_empty_column",
            simultaneous_recovery_note=(
                "fact: standard MobilityWare deal is illegal until every empty "
                "tableau column is filled"
            ),
        )

    # If no empties, still report empty structure
    st_post = state.clone()
    deal_c = st_post.deal()
    assert deal_c == deal_cost()

    tops: List[Tuple[int, Card]] = []
    per: List[PostDealColumnRecovery] = []
    for col in pre_empties:
        # Incoming card is the new top on that column after deal
        top = st_post.columns[col].top()
        assert top is not None
        tops.append((col, top))
        # Legal one-card moves from this column
        options: List[SpaceMoveEffect] = []
        dests: List[int] = []
        for src, dst, k in st_post.enumerate_moves():
            if src == col and k == 1:
                dests.append(dst)
                options.append(simulate_move_effect(st_post, src, dst, k))
        recovery_move = None
        kind = ImmediateRecoveryKind.NO_LEGAL_ONE_MOVE
        notes: List[str] = [
            f"fact: incoming card on col {col + 1} = {top}",
            f"fact: deal cost = {deal_c}",
        ]
        for opt in options:
            if opt.source_became_empty and col in opt.empties_after:
                recovery_move = opt
                kind = ImmediateRecoveryKind.RECOVERS_SAME_COLUMN
                notes.append(
                    f"fact: one-move recovery via move {col + 1}->{opt.dst + 1} k=1 "
                    f"cost={opt.corrected_mw_cost}"
                )
                break
        if recovery_move is None and options:
            kind = ImmediateRecoveryKind.MOVES_ELSEWHERE_NO_RECOVERY
            notes.append(
                "fact: legal destinations exist but no simulated one-move restores "
                "this column as empty (unexpected for k=1 from singleton pile)"
            )
            # Actually for k=1 from a column that only has the dealt card,
            # source always becomes empty if face_down empty. After deal, empty
            # col gets one face-up card, no face-down. Moving k=1 always empties it.
            # So RECOVERS_SAME_COLUMN should always hold if any legal dest exists.
            for opt in options:
                if opt.source_became_empty:
                    recovery_move = opt
                    kind = ImmediateRecoveryKind.RECOVERS_SAME_COLUMN
                    notes.append(
                        f"fact: moving the dealt card empties col {col + 1}; "
                        f"cost={opt.corrected_mw_cost}"
                    )
                    break
        if not options:
            notes.append("fact: no legal one-move destination for the incoming card")

        per.append(
            PostDealColumnRecovery(
                column=col,
                incoming_card=top,
                legal_destinations=tuple(sorted(set(dests))),
                one_move_options=tuple(options),
                immediate_recovery=kind,
                recovery_move=recovery_move,
                notes=tuple(notes),
            )
        )

    n_recoverable = sum(
        1
        for p in per
        if p.immediate_recovery == ImmediateRecoveryKind.RECOVERS_SAME_COLUMN
    )
    if len(pre_empties) <= 1:
        sim_status = "exact_trivial"
        sim_note = (
            "fact: at most one pre-deal empty; simultaneous multi-space N/A"
        )
    else:
        sim_status = "unknown_without_joint_search"
        sim_note = (
            f"heuristic/unknown: {n_recoverable}/{len(pre_empties)} columns are "
            f"individually one-move recoverable; simultaneous joint recovery is "
            f"NOT claimed as a hard fact (destinations may conflict)"
        )

    return SpaceRecoveryForecast(
        stock_remaining_before=stock_rem,
        can_deal=True,
        pre_deal_empties=pre_empties,
        post_deal_tops_on_pre_empties=tuple(tops),
        per_column=tuple(per),
        simultaneous_recovery_status=sim_status,
        simultaneous_recovery_note=sim_note,
    )


# ---------------------------------------------------------------------------
# Reveal linkage
# ---------------------------------------------------------------------------


def _reveal_workspace_contexts(
    state: SpiderState,
    effects: Sequence[SpaceMoveEffect],
    reveal: Optional[RevealGraphAnalysis],
) -> Tuple[RevealWorkspaceContext, ...]:
    if reveal is None:
        return ()
    empty_n = empty_count(state)
    # Index moves by source for excavation starts
    by_src: Dict[int, List[SpaceMoveEffect]] = {}
    for e in effects:
        by_src.setdefault(e.src, []).append(e)

    out: List[RevealWorkspaceContext] = []
    # One context per opportunity prefix (can be many); keep best per column stop
    for opp in reveal.opportunities:
        p = opp.prefix
        chain = reveal.chain_for_column(p.column)
        if chain is None:
            continue
        blockers = chain.face_up_cards
        moves = tuple(by_src.get(p.column, ()))
        can_start_empty = any(m.dest_was_empty for m in moves)
        exhausts = p.exhausts_face_down
        fully_open_after = exhausts  # after N reveals, no face-down left

        # Heuristic burden / recovery (labels only)
        if can_start_empty and any(
            m.effect == WorkspaceEffectKind.RELOCATES for m in moves
        ):
            burden = "can_relocate_workspace"
            recovery = "direct_relocation_possible"
            hnotes = (
                "heuristic: full open material can relocate into empty at corrected cost",
            )
        elif can_start_empty and any(
            m.effect == WorkspaceEffectKind.CONSUMES for m in moves if m.dest_was_empty
        ):
            burden = "may_consume_one_empty_for_immediate_progress"
            recovery = "unknown_without_multi_move_search"
            hnotes = (
                "heuristic: immediate legal progress into an empty consumes workspace "
                "unless the source is emptied (relocation)",
            )
        elif moves:
            burden = "progress_without_empty_possible"
            recovery = "not_required_for_immediate_legal_start"
            hnotes = (
                "heuristic: immediate excavation moves exist onto non-empty destinations",
            )
        elif empty_n == 0:
            burden = "no_empty_and_no_immediate_legal_start"
            recovery = "unknown"
            hnotes = (
                "heuristic: no empty column and no legal excavation start from face-up",
            )
        else:
            burden = "no_immediate_legal_excavation_move"
            recovery = "unknown"
            hnotes = (
                "heuristic: face-up blockers have no legal move yet",
            )

        if fully_open_after:
            hnotes = hnotes + (
                "fact: completing this reveal prefix exhausts face-down "
                "(fully open; emptiness still requires relocating remaining face-up)",
            )

        out.append(
            RevealWorkspaceContext(
                column=p.column,
                stop_reveal_order=p.stop_reveal_order,
                unavoidable_reveal_count=p.unavoidable_reveal_count,
                cards_unlocked=p.cards_unlocked,
                face_up_blocker_count=len(blockers),
                face_up_blockers=blockers,
                empty_count_now=empty_n,
                exhausts_face_down=exhausts,
                would_be_fully_open_after_prefix=fully_open_after,
                immediate_excavation_moves=moves,
                can_start_with_existing_empty=can_start_empty,
                heuristic_workspace_burden=burden,
                heuristic_recovery_outlook=recovery,
                heuristic_notes=hnotes,
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# Public analysis API
# ---------------------------------------------------------------------------


def analyze_space_lifecycle(
    state: SpiderState,
    *,
    reveal_analysis: Optional[RevealGraphAnalysis] = None,
    cards: Optional[Sequence[Card]] = None,
    include_reveal_link: bool = True,
) -> SpaceLifecycleAnalysis:
    """Full workspace lifecycle analysis for ``state``."""
    effects = analyze_all_move_effects(state)
    creations = tuple(
        SpaceCreationOpportunity(move=e)
        for e in effects
        if e.effect == WorkspaceEffectKind.CREATES
    )
    consumptions = tuple(
        SpaceConsumptionFact(move=e)
        for e in effects
        if e.effect == WorkspaceEffectKind.CONSUMES
    )
    relocations = tuple(
        SpaceRelocationFact(move=e)
        for e in effects
        if e.effect == WorkspaceEffectKind.RELOCATES
    )
    foundation_fx = tuple(e for e in effects if e.foundation_removal)

    zero_cost_reloc = tuple(
        e
        for e in effects
        if e.effect == WorkspaceEffectKind.RELOCATES
        and e.corrected_mw_cost == 0
        and e.dest_was_empty
        and e.source_fully_open_before
    )
    paid_fu_to_empty = tuple(
        e
        for e in effects
        if e.dest_was_empty
        and e.source_face_down_before > 0
        and e.k > 0
        and e.corrected_mw_cost >= 1
    )

    workspace = SpaceFact(
        empty_columns=empty_columns(state),
        empty_count=empty_count(state),
        fully_open_nonempty=fully_open_nonempty(state),
        columns_with_face_down=columns_with_face_down(state),
        fully_face_up_not_one_move_emptyable=_fully_open_not_one_move_emptyable(
            state, effects
        ),
    )

    recovery = analyze_next_stock_recovery(state)

    reveal = reveal_analysis
    if include_reveal_link and reveal is None and cards is not None:
        reveal = analyze_reveal_graph(state, cards=cards)
    elif include_reveal_link and reveal is None:
        # State-only reveal graph (no foundation table)
        reveal = analyze_reveal_graph(state)

    contexts = (
        _reveal_workspace_contexts(state, effects, reveal)
        if include_reveal_link
        else ()
    )

    return SpaceLifecycleAnalysis(
        workspace=workspace,
        all_move_effects=effects,
        creation_opportunities=creations,
        consumption_moves=consumptions,
        relocation_moves=relocations,
        foundation_space_effects=foundation_fx,
        next_stock_recovery=recovery,
        reveal_contexts=contexts,
        zero_cost_full_column_relocations=zero_cost_reloc,
        paid_faceup_to_empty_with_face_down=paid_fu_to_empty,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def format_space_report(
    analysis: SpaceLifecycleAnalysis,
    *,
    title: str = "Space lifecycle",
    max_moves: int = 12,
) -> str:
    w = analysis.workspace
    lines = [
        title,
        "=" * len(title),
        "CURRENT WORKSPACE (HARD)",
        f"  empty_count = {w.empty_count}",
        f"  empty_columns = {[c + 1 for c in w.empty_columns]}",
        f"  fully_open_nonempty = {[c + 1 for c in w.fully_open_nonempty]}",
        f"  with_face_down = {[c + 1 for c in w.columns_with_face_down]}",
        f"  fully_open_not_one_move_emptyable = "
        f"{[c + 1 for c in w.fully_face_up_not_one_move_emptyable]}",
        "",
        f"DIRECT CREATION OPPORTUNITIES ({len(analysis.creation_opportunities)})",
    ]
    for i, opp in enumerate(analysis.creation_opportunities[:max_moves]):
        m = opp.move
        lines.append(
            f"  + empty: move {m.src + 1}->{m.dst + 1} k={m.k} "
            f"cost={m.corrected_mw_cost} "
            f"empties {m.empty_before}->{m.empty_after} "
            f"flip={m.flipped} found={m.foundation_removal}"
        )
    if not analysis.creation_opportunities:
        lines.append("  (none)")

    lines.append("")
    lines.append(f"SPACE-CONSUMING MOVES ({len(analysis.consumption_moves)})")
    for m in [c.move for c in analysis.consumption_moves[:max_moves]]:
        lines.append(
            f"  consume: move {m.src + 1}->{m.dst + 1} k={m.k} "
            f"cost={m.corrected_mw_cost} empties {m.empty_before}->{m.empty_after}"
        )
    if not analysis.consumption_moves:
        lines.append("  (none)")

    lines.append("")
    lines.append(f"SPACE-RELOCATING MOVES ({len(analysis.relocation_moves)})")
    for m in [r.move for r in analysis.relocation_moves[:max_moves]]:
        lines.append(
            f"  relocate: move {m.src + 1}->{m.dst + 1} k={m.k} "
            f"cost={m.corrected_mw_cost} "
            f"empties {list(c + 1 for c in m.empties_before)} -> "
            f"{list(c + 1 for c in m.empties_after)}"
        )
    if not analysis.relocation_moves:
        lines.append("  (none)")

    lines.append("")
    lines.append("NEXT-STOCK SPACE RECOVERY")
    rec = analysis.next_stock_recovery
    lines.append(
        f"  can_deal={rec.can_deal} stock_remaining={rec.stock_remaining_before}"
    )
    lines.append(f"  pre_deal_empties={[c + 1 for c in rec.pre_deal_empties]}")
    for p in rec.per_column:
        dests = [d + 1 for d in p.legal_destinations]
        lines.append(
            f"  col {p.column + 1}: incoming={p.incoming_card} "
            f"dests={dests} recovery={p.immediate_recovery.value}"
        )
    lines.append(f"  simultaneous: {rec.simultaneous_recovery_status}")
    lines.append(f"  {rec.simultaneous_recovery_note}")

    lines.append("")
    lines.append("REVEAL CHAINS WITH WORKSPACE CONTEXT (sample)")
    # Prefer deepest prefix per column
    by_col: Dict[int, RevealWorkspaceContext] = {}
    for ctx in analysis.reveal_contexts:
        prev = by_col.get(ctx.column)
        if prev is None or ctx.unavoidable_reveal_count > prev.unavoidable_reveal_count:
            by_col[ctx.column] = ctx
    for col in sorted(by_col):
        ctx = by_col[col]
        seq = " -> ".join(str(c) for c in ctx.cards_unlocked)
        lines.append(
            f"  col {col + 1}: prefix {ctx.unavoidable_reveal_count} "
            f"[{seq}] exhausts_fd={ctx.exhausts_face_down} "
            f"burden={ctx.heuristic_workspace_burden} "
            f"recovery={ctx.heuristic_recovery_outlook}"
        )

    lines.append("")
    lines.append(
        f"ZERO-COST full-open->empty relocations: "
        f"{len(analysis.zero_cost_full_column_relocations)}"
    )
    lines.append(
        f"PAID entire-face-up->empty with face-down under: "
        f"{len(analysis.paid_faceup_to_empty_with_face_down)}"
    )
    return "\n".join(lines)
