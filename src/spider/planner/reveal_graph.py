"""Generic perfect-information reveal / unlock graph (Sprint 1B).

A human exposes hidden cards partly to learn what they are. The perfect-
information solver already knows every face-down card. Therefore:

    REVEALING A CARD HAS ZERO INFORMATION VALUE.

A reveal is strategically interesting only for known structural consequences
of exposing that card and the cards beneath it.

This module is STRUCTURAL ANALYSIS only. It does not claim exact tactical
move costs for relocating blockers, and it does not implement space lifecycle
or stock-reception optimisation.

HARD STRUCTURAL FACTS and HEURISTIC assessments are kept explicitly separate.
No generic King penalty, reveal-always-good rule, or deal-specific constants.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from spider.cards import Card, rank_str
from spider.engine import SpiderState
from spider.planner.foundation_feasibility import (
    SUITS,
    FoundationAvailability,
    FoundationFeasibilityAnalysis,
    analyze_foundation_feasibility,
    epoch_name,
)

# ---------------------------------------------------------------------------
# Lower-bound contract (for Sprint 1D and proof search)
# ---------------------------------------------------------------------------

REVEAL_LOWER_BOUND_USAGE = """
minimum_reveals_to_expose(T) is an admissible objective-specific lower bound
on the number of hidden-card *flips* that must occur before T is face-up.

SAFE USE:
  - as an objective-specific lower bound for "expose card T";
  - as one argument to max(...) with other *compatible* admissible bounds;
  - never as a free additive term with manoeuvring or foundation-assembly
    bounds: a single paid tableau move can both relocate cards and trigger
    a reveal, so reveal-count and move-count are not automatically additive.

NOT CLAIMED:
  - minimum_reveals_to_expose is NOT the number of MobilityWare moves needed;
  - it is NOT a complete admissible h(s) for full-game search by itself.
"""


# ---------------------------------------------------------------------------
# Data model — HARD FACTS
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RevealCardFact:
    """HARD FACT: one physical face-down card and its exposure dependency.

    Face-down stacks are ordered for excavation as:
        face_down[-1] (next flip) → … → face_down[0] (deepest).
    """

    card: Card
    column: int  # 0-based
    face_down_index: int  # index in column.face_down (0 = deepest)
    reveal_order: int  # 0 = next card to flip; larger = deeper
    face_down_above: int  # hidden cards that must flip before this one
    face_up_above: int  # current face-up cards sitting on the hidden section
    minimum_reveals_to_expose: int  # face_down_above + 1 (includes this card)
    predecessor_order: Optional[int]  # reveal_order of card immediately above, or None


@dataclass(frozen=True)
class FoundationRelevanceFact:
    """HARD / conservative demand tags for a physical rank/suit copy.

    Physical cards are never hard-bound to foundation copy #1 vs #2. We only
    report suit/rank demand against Sprint 1A availability tables.
    """

    suit: str
    rank: int
    # Foundation candidates of this suit not yet completed, with earliest epoch
    candidate_labels: Tuple[str, ...]  # e.g. ("C#1", "C#2")
    earliest_any_candidate_epoch: Optional[int]
    theoretically_available_this_epoch: bool
    first_available_next_epoch_or_later: bool
    # True if at least one incomplete candidate of this suit has earliest_epoch
    # strictly greater than the current epoch (removal still blocked for some).
    any_candidate_blocked_until_later: bool
    # Copy-count demand remaining: how many physical copies of this rank/suit
    # are still required across incomplete foundation copies (conservative).
    remaining_rank_demand: int
    notes: Tuple[str, ...]


@dataclass(frozen=True)
class StructuralTag:
    """HARD or clearly labelled structural observation (not a value judgement)."""

    code: str
    detail: str
    is_hard_fact: bool = True


@dataclass(frozen=True)
class RevealPrefix:
    """HARD FACT: excavating a column to a chosen stopping depth.

    ``stop_reveal_order`` is inclusive: the deepest card exposed by this
    prefix has ``reveal_order == stop_reveal_order``.
    """

    column: int
    stop_reveal_order: int  # 0 .. n_hidden-1
    unavoidable_reveal_count: int  # == stop_reveal_order + 1
    cards_unlocked: Tuple[Card, ...]  # in reveal order
    exhausts_face_down: bool
    new_hidden_frontier: Optional[Card]  # next still-hidden card, if any
    suit_rank_composition: Tuple[Tuple[str, int], ...]  # (suit, rank) counts summary
    structural_tags: Tuple[StructuralTag, ...]
    foundation_relevance: Tuple[FoundationRelevanceFact, ...]


@dataclass(frozen=True)
class RevealChain:
    """HARD FACT: complete known hidden sequence in one column."""

    column: int
    face_up_top: Optional[Card]
    face_up_count: int
    face_up_cards: Tuple[Card, ...]
    hidden_cards: Tuple[RevealCardFact, ...]  # reveal order: frontier first
    n_hidden: int

    def card_at_order(self, reveal_order: int) -> RevealCardFact:
        for c in self.hidden_cards:
            if c.reveal_order == reveal_order:
                return c
        raise KeyError(reveal_order)

    def minimum_reveals_to_expose(self, reveal_order: int) -> int:
        """Admissible flip-count lower bound to expose the card at order."""
        return self.card_at_order(reveal_order).minimum_reveals_to_expose

    def prefixes(self) -> Tuple[RevealPrefix, ...]:
        """All stopping depths 0 .. n_hidden-1 (built externally for tags)."""
        raise NotImplementedError("use build_column_prefixes(...)")


# ---------------------------------------------------------------------------
# Data model — HEURISTIC assessments
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RevealOpportunity:
    """One excavation direction + stopping depth with heuristic assessment.

    Hard structural fields mirror the prefix. Heuristic fields are diagnostic
    only and must never be used for proof pruning.
    """

    prefix: RevealPrefix
    # HEURISTIC
    heuristic_interest: float  # simple 0..100 diagnostic
    heuristic_label: str  # low / medium / high
    heuristic_reasons: Tuple[str, ...]


@dataclass(frozen=True)
class RevealGraphAnalysis:
    """Full Sprint 1B analysis for a state."""

    current_epoch: int
    current_epoch_name: str
    chains: Tuple[RevealChain, ...]
    opportunities: Tuple[RevealOpportunity, ...]  # ranked by heuristic_interest
    foundation_analysis: Optional[FoundationFeasibilityAnalysis]
    lower_bound_usage_note: str = REVEAL_LOWER_BOUND_USAGE

    def chain_for_column(self, column: int) -> Optional[RevealChain]:
        for ch in self.chains:
            if ch.column == column:
                return ch
        return None

    def top_opportunities(self, n: int = 5) -> Tuple[RevealOpportunity, ...]:
        return self.opportunities[:n]


# ---------------------------------------------------------------------------
# Construction helpers
# ---------------------------------------------------------------------------


def _face_down_reveal_order(face_down: Sequence[Card]) -> List[Tuple[int, Card]]:
    """Return (face_down_index, card) in excavation order (next flip first)."""
    n = len(face_down)
    return [(n - 1 - order, face_down[n - 1 - order]) for order in range(n)]


def build_reveal_chain(column: int, state: SpiderState) -> Optional[RevealChain]:
    """Build HARD FACT chain for one column, or None if no face-down cards."""
    col = state.columns[column]
    if not col.face_down:
        return None
    face_up = tuple(col.face_up)
    facts: List[RevealCardFact] = []
    ordered = _face_down_reveal_order(col.face_down)
    for reveal_order, (fd_idx, card) in enumerate(ordered):
        facts.append(
            RevealCardFact(
                card=card,
                column=column,
                face_down_index=fd_idx,
                reveal_order=reveal_order,
                face_down_above=reveal_order,
                face_up_above=len(face_up),
                minimum_reveals_to_expose=reveal_order + 1,
                predecessor_order=(reveal_order - 1) if reveal_order > 0 else None,
            )
        )
    return RevealChain(
        column=column,
        face_up_top=face_up[-1] if face_up else None,
        face_up_count=len(face_up),
        face_up_cards=face_up,
        hidden_cards=tuple(facts),
        n_hidden=len(facts),
    )


def minimum_reveals_to_expose(chain: RevealChain, reveal_order: int) -> int:
    """Flip-count lower bound for exposing the hidden card at ``reveal_order``."""
    return chain.minimum_reveals_to_expose(reveal_order)


def _same_suit_fragments_visible(state: SpiderState) -> Dict[str, List[Tuple[int, int, int]]]:
    """suit -> list of (column, top_rank, bottom_rank) for face-up same-suit runs."""
    out: Dict[str, List[Tuple[int, int, int]]] = {s: [] for s in SUITS}
    for col_idx, col in enumerate(state.columns):
        up = col.face_up
        i = 0
        while i < len(up):
            s = up[i].suit
            j = i
            while (
                j + 1 < len(up)
                and up[j + 1].suit == s
                and up[j].rank - 1 == up[j + 1].rank
            ):
                j += 1
            out[s].append((col_idx, up[i].rank, up[j].rank))
            i = j + 1
    return out


def _foundation_relevance_for_card(
    card: Card,
    *,
    current_epoch: int,
    availability: Sequence[FoundationAvailability],
    foundations_removed_by_suit: Dict[str, int],
) -> FoundationRelevanceFact:
    suit = card.suit
    rank = card.rank
    labels: List[str] = []
    earliest_any: Optional[int] = None
    remaining_demand = 0
    notes: List[str] = []
    any_blocked_later = False
    theo_now = False
    next_or_later = False

    for a in availability:
        if a.suit != suit:
            continue
        # Skip completed copies (conservative: foundations_removed >= copy_index)
        if foundations_removed_by_suit.get(suit, 0) >= a.copy_index:
            continue
        label = f"{suit.upper()}#{a.copy_index}"
        labels.append(label)
        # Each incomplete foundation copy demands one of this rank
        remaining_demand += 1
        ep = a.earliest_epoch
        if ep is not None:
            if earliest_any is None or ep < earliest_any:
                earliest_any = ep
            if current_epoch >= ep:
                theo_now = True
            else:
                any_blocked_later = True
                next_or_later = True
        else:
            notes.append(f"{label} never theoretically available")

    if remaining_demand == 0:
        notes.append("no incomplete foundation candidate of this suit")
    else:
        notes.append(
            f"physical {rank_str(rank)}{suit} is one interchangeable copy; "
            f"remaining incomplete candidates for suit: {', '.join(labels) or 'none'}"
        )
        if theo_now:
            notes.append("contributes to a foundation theoretically available this epoch")
        if next_or_later and earliest_any is not None and earliest_any > current_epoch:
            notes.append(
                f"at least one candidate of this suit first available at "
                f"{epoch_name(earliest_any)}"
            )
        if any_blocked_later and not theo_now:
            notes.append("suit worth building; removal still blocked for all its candidates")

    return FoundationRelevanceFact(
        suit=suit,
        rank=rank,
        candidate_labels=tuple(labels),
        earliest_any_candidate_epoch=earliest_any,
        theoretically_available_this_epoch=theo_now,
        first_available_next_epoch_or_later=next_or_later,
        any_candidate_blocked_until_later=any_blocked_later,
        remaining_rank_demand=remaining_demand,
        notes=tuple(notes),
    )


def _foundations_removed_by_suit(state: SpiderState) -> Dict[str, int]:
    counts = {s: 0 for s in SUITS}
    for seq in state.foundations:
        if len(seq) == 13 and all(c.suit == seq[0].suit for c in seq):
            counts[seq[0].suit] = counts.get(seq[0].suit, 0) + 1
    return counts


def _structural_tags_for_prefix(
    cards: Sequence[Card],
    *,
    exhausts: bool,
    state: SpiderState,
    fragments: Dict[str, List[Tuple[int, int, int]]],
    relevance: Sequence[FoundationRelevanceFact],
) -> Tuple[StructuralTag, ...]:
    tags: List[StructuralTag] = []
    if exhausts:
        tags.append(
            StructuralTag(
                "exhausts_face_down",
                "excavation exhausts all face-down cards in this column",
                True,
            )
        )
        tags.append(
            StructuralTag(
                "full_face_up_column",
                "column would be fully face-up (emptiness still requires relocating cards — not claimed cheap)",
                True,
            )
        )

    for c in cards:
        if c.rank == 13:
            tags.append(
                StructuralTag(
                    "contains_king",
                    f"hidden sequence contains King of {c.suit} (neutral structural fact, not a penalty)",
                    True,
                )
            )

    # Extension / connection potential (deterministic structural observation)
    for c in cards:
        for col_idx, top_r, bot_r in fragments.get(c.suit, []):
            # Card could sit on a pile whose exposed bottom is c.rank+1 same suit
            # or extend downward from a fragment ending at c.rank-1 — structural only
            if bot_r - 1 == c.rank:
                tags.append(
                    StructuralTag(
                        "extends_same_suit_fragment",
                        f"{c} could extend face-up {rank_str(top_r)}-{rank_str(bot_r)}"
                        f"{c.suit} fragment (col {col_idx + 1})",
                        True,
                    )
                )
            if top_r + 1 == c.rank:
                tags.append(
                    StructuralTag(
                        "receives_same_suit_fragment",
                        f"{c} could receive face-up fragment headed by "
                        f"{rank_str(top_r)}{c.suit} (col {col_idx + 1})",
                        True,
                    )
                )

    if any(r.theoretically_available_this_epoch for r in relevance):
        tags.append(
            StructuralTag(
                "foundation_available_epoch",
                "sequence contains cards for foundations theoretically available this epoch",
                True,
            )
        )
    if any(
        r.any_candidate_blocked_until_later and not r.theoretically_available_this_epoch
        for r in relevance
    ):
        tags.append(
            StructuralTag(
                "foundation_later_epoch",
                "sequence contains cards whose suit cannot yet be removed",
                True,
            )
        )
    if any(r.remaining_rank_demand > 0 for r in relevance):
        tags.append(
            StructuralTag(
                "foundation_rank_demand",
                "sequence contains ranks still demanded by incomplete foundation candidates",
                True,
            )
        )

    # Deduplicate by (code, detail)
    seen = set()
    uniq: List[StructuralTag] = []
    for t in tags:
        key = (t.code, t.detail)
        if key not in seen:
            seen.add(key)
            uniq.append(t)
    return tuple(uniq)


def build_column_prefixes(
    chain: RevealChain,
    state: SpiderState,
    *,
    current_epoch: int,
    availability: Sequence[FoundationAvailability],
    foundations_removed: Dict[str, int],
) -> Tuple[RevealPrefix, ...]:
    fragments = _same_suit_fragments_visible(state)
    prefixes: List[RevealPrefix] = []
    for stop in range(chain.n_hidden):
        unlocked = tuple(chain.hidden_cards[i].card for i in range(stop + 1))
        exhausts = stop == chain.n_hidden - 1
        new_front = (
            None
            if exhausts
            else chain.hidden_cards[stop + 1].card
        )
        # composition: sorted unique then counts
        comp_map: Dict[Tuple[str, int], int] = {}
        for c in unlocked:
            comp_map[(c.suit, c.rank)] = comp_map.get((c.suit, c.rank), 0) + 1
        composition = tuple(sorted(comp_map.items()))

        relevance = tuple(
            _foundation_relevance_for_card(
                c,
                current_epoch=current_epoch,
                availability=availability,
                foundations_removed_by_suit=foundations_removed,
            )
            for c in unlocked
        )
        tags = _structural_tags_for_prefix(
            unlocked,
            exhausts=exhausts,
            state=state,
            fragments=fragments,
            relevance=relevance,
        )
        prefixes.append(
            RevealPrefix(
                column=chain.column,
                stop_reveal_order=stop,
                unavoidable_reveal_count=stop + 1,
                cards_unlocked=unlocked,
                exhausts_face_down=exhausts,
                new_hidden_frontier=new_front,
                suit_rank_composition=composition,
                structural_tags=tags,
                foundation_relevance=relevance,
            )
        )
    return tuple(prefixes)


def _heuristic_opportunity(prefix: RevealPrefix) -> RevealOpportunity:
    """Simple transparent diagnostic score — not for proof pruning."""
    reasons: List[str] = []
    score = 0.0

    n = prefix.unavoidable_reveal_count
    # Density of useful tags per reveal
    hard_tags = [t for t in prefix.structural_tags if t.is_hard_fact]
    useful_codes = {
        "extends_same_suit_fragment",
        "receives_same_suit_fragment",
        "foundation_available_epoch",
        "foundation_rank_demand",
        "exhausts_face_down",
    }
    useful = [t for t in hard_tags if t.code in useful_codes]
    score += min(40.0, 12.0 * len(useful))
    if useful:
        reasons.append(
            f"heuristic: {len(useful)} strategically relevant structural tag(s) "
            f"in {n} reveal(s)"
        )

    # Foundation relevance density
    fr_hits = sum(
        1
        for r in prefix.foundation_relevance
        if r.remaining_rank_demand > 0
        and (r.theoretically_available_this_epoch or r.any_candidate_blocked_until_later)
    )
    score += min(25.0, fr_hits * 8.0)
    if fr_hits:
        reasons.append(
            f"heuristic: {fr_hits}/{len(prefix.cards_unlocked)} unlocked card(s) "
            f"have foundation rank demand"
        )

    # Reward reaching useful cards without too many empty reveals
    if n > 0 and fr_hits + len(useful) > 0:
        density = (fr_hits + len(useful)) / n
        score += min(20.0, density * 15.0)
        if density >= 1.0 and n >= 2:
            reasons.append(
                "heuristic: high downstream density — several relevant cards "
                "share one dependency chain"
            )

    if prefix.exhausts_face_down:
        score += 8.0
        reasons.append("heuristic: fully excavating hidden section (space analysis deferred)")

    # King is NOT penalised — optional neutral mention only
    kings = [c for c in prefix.cards_unlocked if c.rank == 13]
    if kings:
        reasons.append(
            f"heuristic: sequence includes {len(kings)} King(s) — treated neutrally "
            f"(no generic penalty)"
        )

    # Mild preference for shorter paths when scores otherwise equal is NOT applied
    # as a King-like rule; only slight cost for very long empty excavations
    if n >= 4 and fr_hits == 0 and not useful:
        score = max(0.0, score - 10.0)
        reasons.append("heuristic: long excavation with little recognised structural interest")

    score = max(0.0, min(100.0, score))
    if score >= 55:
        label = "high"
    elif score >= 30:
        label = "medium"
    else:
        label = "low"

    if not reasons:
        reasons.append("heuristic: little recognised structural interest at this depth")

    return RevealOpportunity(
        prefix=prefix,
        heuristic_interest=round(score, 1),
        heuristic_label=label,
        heuristic_reasons=tuple(reasons),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_reveal_graph(
    state: SpiderState,
    *,
    cards: Optional[Sequence[Card]] = None,
    foundation_analysis: Optional[FoundationFeasibilityAnalysis] = None,
) -> RevealGraphAnalysis:
    """Build the perfect-information reveal/unlock graph for ``state``.

    Parameters
    ----------
    state:
        Current play state (hidden cards must be known in the engine state).
    cards:
        Optional full 104-card deal for foundation analysis if not supplied.
    foundation_analysis:
        Optional precomputed Sprint 1A analysis; computed from ``cards`` if
        needed and available.
    """
    fa = foundation_analysis
    if fa is None and cards is not None:
        fa = analyze_foundation_feasibility(cards, state)

    if fa is not None:
        current_epoch = fa.current_epoch
        current_epoch_name = fa.current_epoch_name
        availability = fa.static_availability
    else:
        # Minimal fallback: epoch from stock length assuming 5 deals max
        stock_deals_total = 5
        remaining = len(state.stock) // 10
        current_epoch = max(0, stock_deals_total - remaining)
        current_epoch_name = epoch_name(current_epoch)
        availability = ()

    foundations_removed = _foundations_removed_by_suit(state)

    chains: List[RevealChain] = []
    opportunities: List[RevealOpportunity] = []

    for col_idx in range(len(state.columns)):
        chain = build_reveal_chain(col_idx, state)
        if chain is None:
            continue
        chains.append(chain)
        prefixes = build_column_prefixes(
            chain,
            state,
            current_epoch=current_epoch,
            availability=availability,
            foundations_removed=foundations_removed,
        )
        for p in prefixes:
            opportunities.append(_heuristic_opportunity(p))

    opportunities.sort(
        key=lambda o: (
            -o.heuristic_interest,
            o.prefix.unavoidable_reveal_count,
            o.prefix.column,
            o.prefix.stop_reveal_order,
        )
    )

    return RevealGraphAnalysis(
        current_epoch=current_epoch,
        current_epoch_name=current_epoch_name,
        chains=tuple(chains),
        opportunities=tuple(opportunities),
        foundation_analysis=fa,
        lower_bound_usage_note=REVEAL_LOWER_BOUND_USAGE,
    )


# ---------------------------------------------------------------------------
# Human-readable reporting
# ---------------------------------------------------------------------------


def format_chain(chain: RevealChain) -> str:
    lines = [
        f"Column {chain.column + 1}  "
        f"(face-up={chain.face_up_count}"
        f"{', top=' + str(chain.face_up_top) if chain.face_up_top else ''}; "
        f"hidden={chain.n_hidden})"
    ]
    if chain.face_up_cards:
        fu = " ".join(str(c) for c in chain.face_up_cards)
        lines.append(f"  face-up stack: {fu}")
    seq = " -> ".join(str(h.card) for h in chain.hidden_cards)
    lines.append(f"  reveal order (frontier first): {seq}")
    for h in chain.hidden_cards:
        pred = (
            f"after order {h.predecessor_order}"
            if h.predecessor_order is not None
            else "frontier (next flip)"
        )
        lines.append(
            f"    [{h.reveal_order}] {h.card}: "
            f"min_reveals={h.minimum_reveals_to_expose}, "
            f"fd_above={h.face_down_above}, fu_above={h.face_up_above}, {pred}"
        )
    return "\n".join(lines)


def format_opportunity(opp: RevealOpportunity, *, verbose: bool = True) -> str:
    p = opp.prefix
    seq = " -> ".join(str(c) for c in p.cards_unlocked)
    lines = [
        f"Column {p.column + 1}, pursue {p.unavoidable_reveal_count} reveal(s) "
        f"[{opp.heuristic_label} interest={opp.heuristic_interest}]"
    ]
    lines.append("  HARD:")
    lines.append(f"    known sequence = {seq}")
    lines.append(f"    unavoidable reveal count = {p.unavoidable_reveal_count}")
    lines.append(f"    exhausts hidden cards = {p.exhausts_face_down}")
    if p.new_hidden_frontier is not None:
        lines.append(f"    new hidden frontier = {p.new_hidden_frontier}")
    if verbose:
        if p.structural_tags:
            lines.append("  STRUCTURAL TAGS:")
            for t in p.structural_tags:
                kind = "fact" if t.is_hard_fact else "tag"
                lines.append(f"    [{kind}/{t.code}] {t.detail}")
        if p.foundation_relevance:
            lines.append("  FOUNDATION RELEVANCE (no fixed copy assignment):")
            for r in p.foundation_relevance:
                lines.append(
                    f"    {rank_str(r.rank)}{r.suit}: demand={r.remaining_rank_demand}, "
                    f"candidates={list(r.candidate_labels)}, "
                    f"theo_now={r.theoretically_available_this_epoch}"
                )
        lines.append("  HEURISTIC:")
        for reason in opp.heuristic_reasons:
            lines.append(f"    {reason}")
    return "\n".join(lines)


def format_reveal_report(
    analysis: RevealGraphAnalysis,
    *,
    title: str = "Reveal / unlock graph",
    top_n: int = 8,
) -> str:
    parts = [
        title,
        "=" * len(title),
        f"Current epoch: {analysis.current_epoch_name} ({analysis.current_epoch})",
        f"Columns with hidden cards: {len(analysis.chains)}",
        "",
        "REVEAL CHAINS BY COLUMN",
        "-" * 40,
    ]
    for ch in sorted(analysis.chains, key=lambda c: c.column):
        parts.append(format_chain(ch))
        parts.append("")
    parts.append("TOP CURRENT REVEAL OPPORTUNITIES")
    parts.append("-" * 40)
    for opp in analysis.top_opportunities(top_n):
        parts.append(format_opportunity(opp))
        parts.append("")
    parts.append("LOWER-BOUND NOTE")
    parts.append("-" * 40)
    parts.append(analysis.lower_bound_usage_note.strip())
    return "\n".join(parts)
