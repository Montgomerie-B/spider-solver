"""Generic foundation-removal feasibility analysis (Sprint 1A).

Separates HARD FACTS (stock/card availability, theoretical impossibility)
from HEURISTIC ASSESSMENTS (build attractiveness, blocker burden, removal
attractiveness).

No deal number, column index, canonical move number or suit order is
hard-coded into strategy logic. Benchmark fixture paths belong only in
diagnostics and tests, never in generic ranking rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from spider.cards import Card, rank_str
from spider.deal import stock_deal_rounds
from spider.engine import SpiderState

# ---------------------------------------------------------------------------
# Constants (rules of Spider, not deal-specific strategy)
# ---------------------------------------------------------------------------

SUITS: Tuple[str, ...] = ("c", "d", "h", "s")
SUIT_NAMES = {"c": "Clubs", "d": "Diamonds", "h": "Hearts", "s": "Spades"}
FOUNDATION_RANKS: Tuple[int, ...] = tuple(range(13, 0, -1))  # K .. A
FOUNDATION_COPIES: Tuple[int, ...] = (1, 2)
TABLEAU_DEAL_CARDS = 54  # standard Spider opening layout size

EPOCH_NAMES: Dict[int, str] = {
    0: "opening",
    1: "after deal 1",
    2: "after deal 2",
    3: "after deal 3",
    4: "after deal 4",
    5: "after deal 5",
}


def epoch_name(epoch: int) -> str:
    if epoch in EPOCH_NAMES:
        return EPOCH_NAMES[epoch]
    if epoch < 0:
        return "before opening"
    return f"after deal {epoch}"


# ---------------------------------------------------------------------------
# Data model — hard facts vs heuristics are explicit
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FoundationAvailability:
    """HARD FACT: earliest stock epoch at which a complete K→A foundation
    of this suit/copy can exist in theory (all required physical cards have
    entered play). Independent of exposure, accessibility or assembly cost.
    """

    suit: str
    copy_index: int  # 1 or 2
    earliest_epoch: Optional[int]  # None if never possible with this deal
    earliest_epoch_name: str
    limiting_ranks: Tuple[int, ...]
    """Ranks that only reached the required copy-count at the earliest epoch
    (i.e. would have blocked any earlier epoch). Empty if earliest is opening
    or never.
    """
    cumulative_counts_by_epoch: Tuple[Tuple[int, ...], ...]
    """For each epoch e, a 13-tuple of counts for ranks 1..13 of this suit
    that have entered play by that epoch (index 0 = Ace).
    """

    def rank_count_at(self, epoch: int, rank: int) -> int:
        if epoch < 0 or epoch >= len(self.cumulative_counts_by_epoch):
            return 0
        if rank < 1 or rank > 13:
            return 0
        return self.cumulative_counts_by_epoch[epoch][rank - 1]


@dataclass(frozen=True)
class BuriedCardFact:
    """HARD FACT: a required suit card still face-down in the tableau."""

    rank: int
    column: int  # 0-based column index
    depth: int  # face-up cards + deeper face-down cards above it
    obstructors_face_up: int


@dataclass(frozen=True)
class SuitFragmentFact:
    """HARD FACT: a same-suit descending run fragment currently face-up."""

    column: int
    top_rank: int  # highest rank in the fragment (nearer K)
    bottom_rank: int  # lowest rank (nearer A / exposed end if at pile top)
    length: int
    at_pile_top: bool


@dataclass
class FoundationCandidate:
    """One foundation objective (suit × copy) evaluated at a current state.

    Fields under ``facts_*`` / without ``heuristic_`` prefix are deterministic
    observations. Fields named ``heuristic_*`` are diagnostic scores only.
    """

    suit: str
    copy_index: int

    # ---- HARD FACTS ----
    current_epoch: int
    earliest_epoch: Optional[int]
    theoretically_available: bool
    already_completed: bool
    foundations_of_suit_removed: int

    cards_in_play_total: int
    face_up_count: int
    face_down_count: int
    stock_remaining_count: int
    foundation_count: int  # cards of this suit already on foundations

    face_up_by_rank: Dict[int, int]
    face_down_by_rank: Dict[int, int]
    stock_by_rank: Dict[int, int]
    foundation_by_rank: Dict[int, int]

    ranks_with_enough_in_play: Tuple[int, ...]
    ranks_short_in_play: Tuple[int, ...]
    ranks_face_up: Tuple[int, ...]
    ranks_only_buried: Tuple[int, ...]
    ranks_only_in_stock: Tuple[int, ...]

    same_suit_fragments: Tuple[SuitFragmentFact, ...]
    longest_same_suit_fragment: int
    buried_cards: Tuple[BuriedCardFact, ...]
    total_burial_depth: int
    empty_columns: int

    facts_reasons: Tuple[str, ...]

    # ---- HEURISTIC ASSESSMENTS (not proof) ----
    heuristic_build_readiness: float
    heuristic_removal_readiness: float
    heuristic_space_pressure: float
    heuristic_reasons: Tuple[str, ...]

    @property
    def label(self) -> str:
        return f"{self.suit.upper()}#{self.copy_index}"


@dataclass
class FoundationFrontier:
    """Ranked guidance list of foundation objectives (not a proof order)."""

    current_epoch: int
    current_epoch_name: str
    empty_columns: int
    candidates: Tuple[FoundationCandidate, ...]
    """Ordered primarily by removal readiness, then build readiness.
    Already-completed foundations are listed last.
    """

    def active(self) -> Tuple[FoundationCandidate, ...]:
        return tuple(c for c in self.candidates if not c.already_completed)


@dataclass
class FoundationFeasibilityAnalysis:
    """Complete Sprint 1A analysis for a deal and optional current state."""

    stock_deals_total: int
    current_epoch: int
    current_epoch_name: str
    static_availability: Tuple[FoundationAvailability, ...]
    frontier: FoundationFrontier

    def availability_for(self, suit: str, copy_index: int) -> FoundationAvailability:
        suit = suit.lower()
        for a in self.static_availability:
            if a.suit == suit and a.copy_index == copy_index:
                return a
        raise KeyError(f"no availability for {suit}#{copy_index}")


# ---------------------------------------------------------------------------
# Static stock-epoch availability (HARD FACTS)
# ---------------------------------------------------------------------------


def _empty_rank_counts() -> List[int]:
    return [0] * 13


def _add_card_counts(counts_by_suit: Dict[str, List[int]], card: Card) -> None:
    counts_by_suit[card.suit][card.rank - 1] += 1


def cumulative_suit_rank_counts_by_epoch(
    cards: Sequence[Card],
) -> Tuple[int, Dict[str, Tuple[Tuple[int, ...], ...]]]:
    """Return (stock_deals_total, suit -> epoch -> rank counts 1..13).

    Epoch 0 = opening tableau only. Epoch k = after stock deal k.
    """
    if len(cards) != 104:
        raise ValueError(f"expected 104 cards, got {len(cards)}")
    tableau = list(cards[:TABLEAU_DEAL_CARDS])
    stock = list(cards[TABLEAU_DEAL_CARDS:])
    if len(stock) % 10:
        raise ValueError(f"stock length must be multiple of 10, got {len(stock)}")
    deals_total = len(stock) // 10
    rounds = stock_deal_rounds(stock)  # index 0 = first deal

    # Running counts
    running: Dict[str, List[int]] = {s: _empty_rank_counts() for s in SUITS}
    for c in tableau:
        _add_card_counts(running, c)

    by_suit: Dict[str, List[Tuple[int, ...]]] = {s: [] for s in SUITS}
    for s in SUITS:
        by_suit[s].append(tuple(running[s]))

    for deal_round in rounds:
        for c in deal_round:
            _add_card_counts(running, c)
        for s in SUITS:
            by_suit[s].append(tuple(running[s]))

    frozen = {s: tuple(by_suit[s]) for s in SUITS}
    return deals_total, frozen


def _earliest_epoch_for_copy(
    counts_by_epoch: Sequence[Sequence[int]],
    copy_index: int,
) -> Tuple[Optional[int], Tuple[int, ...]]:
    """First epoch where every rank has count >= copy_index.

    Returns (epoch_or_None, limiting_ranks).
    """
    need = copy_index
    for epoch, counts in enumerate(counts_by_epoch):
        short = [r + 1 for r, n in enumerate(counts) if n < need]
        if not short:
            # Limiting ranks: those that were short at the previous epoch
            if epoch == 0:
                limiting: Tuple[int, ...] = ()
            else:
                prev = counts_by_epoch[epoch - 1]
                limiting = tuple(
                    r + 1 for r, n in enumerate(prev) if n < need
                )
            return epoch, limiting
    return None, tuple(range(1, 14))


def compute_static_availability(
    cards: Sequence[Card],
) -> Tuple[int, Tuple[FoundationAvailability, ...]]:
    """Static foundation availability table for a full 104-card deal."""
    deals_total, by_suit = cumulative_suit_rank_counts_by_epoch(cards)
    out: List[FoundationAvailability] = []
    for suit in SUITS:
        counts = by_suit[suit]
        for copy_index in FOUNDATION_COPIES:
            epoch, limiting = _earliest_epoch_for_copy(counts, copy_index)
            out.append(
                FoundationAvailability(
                    suit=suit,
                    copy_index=copy_index,
                    earliest_epoch=epoch,
                    earliest_epoch_name=(
                        epoch_name(epoch) if epoch is not None else "never"
                    ),
                    limiting_ranks=limiting,
                    cumulative_counts_by_epoch=counts,
                )
            )
    return deals_total, tuple(out)


# ---------------------------------------------------------------------------
# Dynamic state observations (HARD FACTS)
# ---------------------------------------------------------------------------


def current_stock_epoch(state: SpiderState, stock_deals_total: int) -> int:
    """How many stock deals have already been applied (0..stock_deals_total)."""
    remaining = len(state.stock) // 10
    done = stock_deals_total - remaining
    if done < 0:
        done = 0
    if done > stock_deals_total:
        done = stock_deals_total
    return done


def _count_by_rank(cards: Iterable[Card], suit: str) -> Dict[int, int]:
    out = {r: 0 for r in range(1, 14)}
    for c in cards:
        if c.suit == suit:
            out[c.rank] += 1
    return out


def _locate_suit_cards(
    state: SpiderState, suit: str
) -> Tuple[
    Dict[int, int],
    Dict[int, int],
    Dict[int, int],
    Dict[int, int],
    List[BuriedCardFact],
    List[SuitFragmentFact],
]:
    face_up: Dict[int, int] = {r: 0 for r in range(1, 14)}
    face_down: Dict[int, int] = {r: 0 for r in range(1, 14)}
    stock: Dict[int, int] = {r: 0 for r in range(1, 14)}
    foundation: Dict[int, int] = {r: 0 for r in range(1, 14)}
    buried: List[BuriedCardFact] = []
    fragments: List[SuitFragmentFact] = []

    for col_idx, col in enumerate(state.columns):
        for c in col.face_up:
            if c.suit == suit:
                face_up[c.rank] += 1
        for fd_idx, c in enumerate(col.face_down):
            if c.suit == suit:
                face_down[c.rank] += 1
                # depth: all face-up + face-down cards above this one
                above_fd = len(col.face_down) - 1 - fd_idx
                depth = len(col.face_up) + above_fd
                buried.append(
                    BuriedCardFact(
                        rank=c.rank,
                        column=col_idx,
                        depth=depth,
                        obstructors_face_up=len(col.face_up),
                    )
                )
        # Same-suit descending fragments within face-up
        up = col.face_up
        if not up:
            continue
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
            length = j - i + 1
            top_rank = up[i].rank
            bottom_rank = up[j].rank
            at_top = j == len(up) - 1
            fragments.append(
                SuitFragmentFact(
                    column=col_idx,
                    top_rank=top_rank,
                    bottom_rank=bottom_rank,
                    length=length,
                    at_pile_top=at_top,
                )
            )
            i = j + 1

    for c in state.stock:
        if c.suit == suit:
            stock[c.rank] += 1

    for seq in state.foundations:
        for c in seq:
            if c.suit == suit:
                foundation[c.rank] += 1

    return face_up, face_down, stock, foundation, buried, fragments


def _foundations_of_suit(state: SpiderState, suit: str) -> int:
    n = 0
    for seq in state.foundations:
        if seq and seq[0].suit == suit and len(seq) == 13:
            n += 1
        elif seq and all(c.suit == suit for c in seq) and len(seq) == 13:
            n += 1
    return n


# ---------------------------------------------------------------------------
# Heuristic readiness (explicitly non-proof)
# ---------------------------------------------------------------------------


def _heuristic_scores(
    *,
    theoretically_available: bool,
    already_completed: bool,
    face_up_count: int,
    face_down_count: int,
    stock_remaining_count: int,
    longest_fragment: int,
    total_burial_depth: int,
    empty_columns: int,
    ranks_face_up: Sequence[int],
    ranks_only_buried: Sequence[int],
    ranks_only_in_stock: Sequence[int],
    ranks_short_in_play: Sequence[int],
) -> Tuple[float, float, float, Tuple[str, ...]]:
    """Simple transparent diagnostic scores in roughly [0, 100]."""
    reasons: List[str] = []

    if already_completed:
        return 0.0, 0.0, 0.0, ("already completed",)

    # Build readiness: value of consolidating material even if removal is impossible
    build = 0.0
    build += min(40.0, longest_fragment * 6.0)
    build += min(25.0, face_up_count * 2.0)
    build += min(15.0, len(ranks_face_up) * 1.2)
    build -= min(20.0, total_burial_depth * 0.8)
    build -= min(15.0, len(ranks_only_in_stock) * 2.0)
    if face_up_count >= 5:
        reasons.append(f"heuristic: solid face-up mass ({face_up_count})")
    if longest_fragment >= 4:
        reasons.append(f"heuristic: long same-suit fragment ({longest_fragment})")
    if ranks_only_in_stock:
        reasons.append(
            f"heuristic: {len(ranks_only_in_stock)} rank(s) still only in future stock"
        )
    build = max(0.0, min(100.0, build))

    # Removal readiness: only meaningful when theoretically available
    removal = 0.0
    space_pressure = max(0.0, 3.0 - float(empty_columns)) * 10.0
    if not theoretically_available:
        removal = 0.0
        reasons.append("heuristic: removal blocked — not theoretically available yet")
    else:
        removal += 20.0  # base for being theoretically possible
        removal += min(35.0, longest_fragment * 5.0)
        removal += min(20.0, len(ranks_face_up) * 1.5)
        removal -= min(30.0, total_burial_depth * 1.0)
        removal -= min(20.0, len(ranks_only_buried) * 2.5)
        removal -= space_pressure * 0.5
        if face_down_count == 0 and stock_remaining_count == 0 and not ranks_short_in_play:
            removal += 15.0
            reasons.append("heuristic: all required cards are face-up in tableau")
        if total_burial_depth >= 6:
            reasons.append(
                f"heuristic: high burial burden (depth sum {total_burial_depth})"
            )
        if empty_columns == 0:
            reasons.append("heuristic: no empty columns — assembly likely constrained")
        removal = max(0.0, min(100.0, removal))

    return build, removal, space_pressure, tuple(reasons)


# ---------------------------------------------------------------------------
# Public analysis API
# ---------------------------------------------------------------------------


def analyze_foundation_feasibility(
    cards: Sequence[Card],
    state: Optional[SpiderState] = None,
) -> FoundationFeasibilityAnalysis:
    """Full static + dynamic foundation feasibility analysis.

    Parameters
    ----------
    cards:
        Complete 104-card deal in MobilityWare file order (tableau then stock).
    state:
        Current play state. If omitted, uses the initial state from ``cards``.
    """
    deals_total, static = compute_static_availability(cards)
    if state is None:
        state = SpiderState.from_cards(list(cards))
    epoch = current_stock_epoch(state, deals_total)

    static_by_key = {(a.suit, a.copy_index): a for a in static}
    empties = sum(1 for c in state.columns if c.is_empty())
    candidates: List[FoundationCandidate] = []

    for suit in SUITS:
        face_up, face_down, stock, foundation, buried, fragments = _locate_suit_cards(
            state, suit
        )
        foundations_removed = _foundations_of_suit(state, suit)
        longest = max((f.length for f in fragments), default=0)
        burial_depth = sum(b.depth for b in buried)

        for copy_index in FOUNDATION_COPIES:
            avail = static_by_key[(suit, copy_index)]
            earliest = avail.earliest_epoch
            theoretically = earliest is not None and epoch >= earliest
            already = foundations_removed >= copy_index

            # Rank inventory relative to needing `copy_index` copies in play
            need = copy_index
            in_play_by_rank = {
                r: face_up[r] + face_down[r] + foundation[r]
                for r in range(1, 14)
            }
            # "In play" excludes remaining stock
            # Inventory including remaining stock (current physical multiset).
            ranks_enough = tuple(
                r for r in range(1, 14) if in_play_by_rank[r] + stock[r] >= need
            )
            # Correct theoretical ranks short at *current* epoch from static table
            if earliest is None:
                ranks_short = FOUNDATION_RANKS
            else:
                counts_now = avail.cumulative_counts_by_epoch[
                    min(epoch, len(avail.cumulative_counts_by_epoch) - 1)
                ]
                ranks_short = tuple(
                    r for r in range(1, 14) if counts_now[r - 1] < need
                )
                ranks_enough = tuple(
                    r for r in range(1, 14) if counts_now[r - 1] >= need
                )

            ranks_face_up = tuple(r for r in range(1, 14) if face_up[r] > 0)
            ranks_only_buried = tuple(
                r
                for r in range(1, 14)
                if face_down[r] > 0 and face_up[r] == 0 and foundation[r] == 0
            )
            ranks_only_stock = tuple(
                r
                for r in range(1, 14)
                if stock[r] > 0
                and face_up[r] == 0
                and face_down[r] == 0
                and foundation[r] == 0
            )

            facts_reasons: List[str] = []
            if already:
                facts_reasons.append(
                    f"fact: foundation {suit.upper()}#{copy_index} already removed"
                )
            elif theoretically:
                facts_reasons.append(
                    f"fact: theoretically available since {epoch_name(earliest)}"
                )
            else:
                if earliest is None:
                    facts_reasons.append(
                        "fact: never theoretically available with this deal"
                    )
                else:
                    facts_reasons.append(
                        f"fact: not available until {epoch_name(earliest)} "
                        f"(now {epoch_name(epoch)})"
                    )
                if avail.limiting_ranks:
                    lim = ", ".join(rank_str(r) for r in avail.limiting_ranks)
                    facts_reasons.append(f"fact: limiting ranks for earliest epoch: {lim}")
            if ranks_short:
                facts_reasons.append(
                    "fact: ranks short of copy-count in play+entered: "
                    + ", ".join(rank_str(r) for r in ranks_short)
                )
            facts_reasons.append(
                f"fact: face-up={sum(face_up.values())} "
                f"face-down={sum(face_down.values())} "
                f"stock={sum(stock.values())} "
                f"foundation={sum(foundation.values())}"
            )
            if fragments:
                facts_reasons.append(
                    f"fact: longest same-suit fragment length {longest}"
                )
            if buried:
                facts_reasons.append(
                    f"fact: {len(buried)} buried card(s), total depth {burial_depth}"
                )
            facts_reasons.append(f"fact: empty columns = {empties}")

            build, removal, space_p, h_reasons = _heuristic_scores(
                theoretically_available=theoretically and not already,
                already_completed=already,
                face_up_count=sum(face_up.values()),
                face_down_count=sum(face_down.values()),
                stock_remaining_count=sum(stock.values()),
                longest_fragment=longest,
                total_burial_depth=burial_depth,
                empty_columns=empties,
                ranks_face_up=ranks_face_up,
                ranks_only_buried=ranks_only_buried,
                ranks_only_in_stock=ranks_only_stock,
                ranks_short_in_play=ranks_short,
            )

            candidates.append(
                FoundationCandidate(
                    suit=suit,
                    copy_index=copy_index,
                    current_epoch=epoch,
                    earliest_epoch=earliest,
                    theoretically_available=bool(theoretically and not already),
                    already_completed=already,
                    foundations_of_suit_removed=foundations_removed,
                    cards_in_play_total=(
                        sum(face_up.values())
                        + sum(face_down.values())
                        + sum(foundation.values())
                    ),
                    face_up_count=sum(face_up.values()),
                    face_down_count=sum(face_down.values()),
                    stock_remaining_count=sum(stock.values()),
                    foundation_count=sum(foundation.values()),
                    face_up_by_rank=dict(face_up),
                    face_down_by_rank=dict(face_down),
                    stock_by_rank=dict(stock),
                    foundation_by_rank=dict(foundation),
                    ranks_with_enough_in_play=ranks_enough,
                    ranks_short_in_play=ranks_short,
                    ranks_face_up=ranks_face_up,
                    ranks_only_buried=ranks_only_buried,
                    ranks_only_in_stock=ranks_only_stock,
                    same_suit_fragments=tuple(fragments),
                    longest_same_suit_fragment=longest,
                    buried_cards=tuple(buried),
                    total_burial_depth=burial_depth,
                    empty_columns=empties,
                    facts_reasons=tuple(facts_reasons),
                    heuristic_build_readiness=round(build, 1),
                    heuristic_removal_readiness=round(removal, 1),
                    heuristic_space_pressure=round(space_p, 1),
                    heuristic_reasons=h_reasons,
                )
            )

    # Frontier ranking: completed last; then removal readiness; then build
    def sort_key(c: FoundationCandidate) -> Tuple:
        return (
            1 if c.already_completed else 0,
            -c.heuristic_removal_readiness,
            -c.heuristic_build_readiness,
            c.earliest_epoch if c.earliest_epoch is not None else 99,
            c.suit,
            c.copy_index,
        )

    ranked = tuple(sorted(candidates, key=sort_key))
    frontier = FoundationFrontier(
        current_epoch=epoch,
        current_epoch_name=epoch_name(epoch),
        empty_columns=empties,
        candidates=ranked,
    )
    return FoundationFeasibilityAnalysis(
        stock_deals_total=deals_total,
        current_epoch=epoch,
        current_epoch_name=epoch_name(epoch),
        static_availability=static,
        frontier=frontier,
    )


# ---------------------------------------------------------------------------
# Human-readable reporting
# ---------------------------------------------------------------------------


def format_availability_table(analysis: FoundationFeasibilityAnalysis) -> str:
    lines = [
        "FOUNDATION AVAILABILITY BY STOCK EPOCH",
        f"{'Suit':<6} {'Copy':<5} {'Earliest theoretical epoch':<28} Limiting ranks/cards",
        "-" * 88,
    ]
    for a in analysis.static_availability:
        lim = (
            ", ".join(f"{rank_str(r)}{a.suit}" for r in a.limiting_ranks)
            if a.limiting_ranks
            else "—"
        )
        lines.append(
            f"{a.suit.upper():<6} {a.copy_index:<5} {a.earliest_epoch_name:<28} {lim}"
        )
    return "\n".join(lines)


def format_frontier_table(analysis: FoundationFeasibilityAnalysis) -> str:
    lines = [
        f"CURRENT REMOVAL FRONTIER (epoch: {analysis.current_epoch_name})",
        f"{'Candidate':<10} {'Theoretical?':<13} {'Build':>7} {'Removal':>8}  Main reasons",
        "-" * 100,
    ]
    for c in analysis.frontier.candidates:
        if c.already_completed:
            theo = "done"
        else:
            theo = "yes" if c.theoretically_available else "no"
        reasons = list(c.facts_reasons[:2]) + list(c.heuristic_reasons[:2])
        reason_txt = "; ".join(reasons)
        if len(reason_txt) > 70:
            reason_txt = reason_txt[:67] + "..."
        lines.append(
            f"{c.label:<10} {theo:<13} {c.heuristic_build_readiness:>7.1f} "
            f"{c.heuristic_removal_readiness:>8.1f}  {reason_txt}"
        )
    return "\n".join(lines)


def format_analysis_report(
    analysis: FoundationFeasibilityAnalysis,
    *,
    title: str = "Foundation feasibility",
) -> str:
    parts = [
        title,
        "=" * len(title),
        f"Stock deals total: {analysis.stock_deals_total}",
        f"Current epoch: {analysis.current_epoch_name} ({analysis.current_epoch})",
        "",
        format_availability_table(analysis),
        "",
        format_frontier_table(analysis),
        "",
        "NOTE: Build/Removal readiness columns are HEURISTIC diagnostics only.",
        "Theoretical availability is a HARD FACT from stock/card inventory.",
    ]
    return "\n".join(parts)


def earliest_any_foundation_epoch(
    analysis: FoundationFeasibilityAnalysis,
) -> Optional[int]:
    """Earliest epoch at which *any* foundation copy is theoretically possible."""
    epochs = [
        a.earliest_epoch
        for a in analysis.static_availability
        if a.copy_index == 1 and a.earliest_epoch is not None
    ]
    return min(epochs) if epochs else None
