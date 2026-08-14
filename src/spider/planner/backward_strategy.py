"""Backward / meet-in-the-middle strategic dependency analysis.

Diagnostic only. Not a search layer and not wired into plan_search.

Perfect information is used to ask, for a *current* state:

- which buried cards are worth excavating, and by when
- which columns are worthwhile excavation / latent-workspace projects
- what a usable space would enable, and whether it is cheap to regain
- how the exact next stock row should change those answers

HARD facts (locations, deals, one-move effects) are labelled separately
from HEURISTIC urgency / rank. Physical duplicate cards are interchangeable.
No deal-id, column-id, or canonical-route constants belong here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from spider.cards import Card, rank_str
from spider.engine import SpiderState
from spider.planner.foundation_feasibility import (
    FoundationFeasibilityAnalysis,
    analyze_foundation_feasibility,
    current_stock_epoch,
)
from spider.planner.objective_realizer import RealizationStatus
from spider.planner.reveal_graph import (
    FoundationRelevanceFact,
    _foundation_relevance_for_card,
    _foundations_removed_by_suit,
    _same_suit_fragments_visible,
    build_reveal_chain,
)
from spider.planner.space_lifecycle import (
    analyze_next_stock_recovery,
    empty_columns,
    empty_count,
)
from spider.planner.stock_reception import (
    LandingKind,
    analyze_stock_reception,
    next_stock_row,
)
from spider.planner.workspace_obstruction import (
    open_column_facts,
    profile_state,
    workspace_potential,
)
from spider.planner.workspace_tactics import WorkspaceBackend, realize_workspace
from spider.rules import MW_RULES


class LocationKind(str, Enum):
    FACE_UP_TOP = "face_up_top"
    FACE_UP_BURIED = "face_up_buried"
    FACE_DOWN = "face_down"
    STOCK = "stock"
    FOUNDATION = "foundation"


class Urgency(str, Enum):
    USEFUL_NOW = "useful_now"
    USEFUL_BEFORE_NEXT_DEAL = "useful_before_next_deal"
    USEFUL_LATER = "useful_later"
    CURRENTLY_LOW_VALUE = "currently_low_value"


class PrereqStatus(str, Enum):
    EXPOSED = "exposed"
    BURIED = "buried"
    FUTURE_STOCK = "future_stock"
    NONE = "none"


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CardLocation:
    """HARD: one physical copy of a rank/suit."""

    card: Card
    kind: LocationKind
    column: Optional[int]
    depth: int
    stock_epoch: Optional[int]
    note: str = ""


def locate_all_cards(state: SpiderState) -> Tuple[CardLocation, ...]:
    """Locate every physical card still in play or remaining stock."""
    epoch_now = current_stock_epoch(state, 5)
    out: List[CardLocation] = []
    for i, col in enumerate(state.columns):
        nfd = len(col.face_down)
        for d, card in enumerate(col.face_down):
            # reveal_order 0 = next flip = last face_down
            reveal_order = nfd - 1 - d
            out.append(
                CardLocation(
                    card,
                    LocationKind.FACE_DOWN,
                    i,
                    reveal_order,
                    None,
                    f"col {i + 1} buried depth {reveal_order}",
                )
            )
        for u, card in enumerate(col.face_up):
            kind = (
                LocationKind.FACE_UP_TOP
                if u == len(col.face_up) - 1
                else LocationKind.FACE_UP_BURIED
            )
            buried_under_top = len(col.face_up) - 1 - u
            out.append(
                CardLocation(
                    card,
                    kind,
                    i,
                    buried_under_top,
                    None,
                    f"col {i + 1} face-up from top {buried_under_top}",
                )
            )
    stock = state.stock
    n = len(stock)
    for i, card in enumerate(stock):
        from_top = n - 1 - i
        deal_offset = from_top // 10  # 0 = next deal
        ep = epoch_now + 1 + deal_offset
        out.append(
            CardLocation(
                card,
                LocationKind.STOCK,
                from_top % 10,
                deal_offset,
                ep,
                f"stock deal epoch {ep} col {from_top % 10 + 1}",
            )
        )
    for seq in state.foundations:
        for card in seq:
            out.append(
                CardLocation(
                    card, LocationKind.FOUNDATION, None, 0, None, "foundation"
                )
            )
    return tuple(out)


def copies_of(
    locs: Sequence[CardLocation], suit: str, rank: int
) -> Tuple[CardLocation, ...]:
    return tuple(x for x in locs if x.card.suit == suit and x.card.rank == rank)


def copies_of_rank(locs: Sequence[CardLocation], rank: int) -> Tuple[CardLocation, ...]:
    return tuple(x for x in locs if x.card.rank == rank)


# ---------------------------------------------------------------------------
# Buried-card backward facts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BuriedCardFact:
    card: Card
    column: int
    reveal_order: int
    min_reveals: int
    foundation: Optional[FoundationRelevanceFact]
    ss_join: Tuple[str, ...]
    dest_prereqs: Tuple[CardLocation, ...]
    prereq_status: PrereqStatus
    earliest_useful_epoch: int
    urgency: Urgency
    value_score: float
    notes: Tuple[str, ...]


def _best_prereq_status(dests: Sequence[CardLocation]) -> PrereqStatus:
    if any(d.kind == LocationKind.FACE_UP_TOP for d in dests):
        return PrereqStatus.EXPOSED
    if any(d.kind in (LocationKind.FACE_UP_BURIED, LocationKind.FACE_DOWN) for d in dests):
        return PrereqStatus.BURIED
    if any(d.kind == LocationKind.STOCK for d in dests):
        return PrereqStatus.FUTURE_STOCK
    return PrereqStatus.NONE


def _earliest_dest_epoch(dests: Sequence[CardLocation], epoch_now: int) -> int:
    best = None
    for d in dests:
        if d.kind in (
            LocationKind.FACE_UP_TOP,
            LocationKind.FACE_UP_BURIED,
            LocationKind.FACE_DOWN,
        ):
            return epoch_now
        if d.kind == LocationKind.STOCK and d.stock_epoch is not None:
            if best is None or d.stock_epoch < best:
                best = d.stock_epoch
    return best if best is not None else epoch_now + 9


def analyze_buried_cards(
    state: SpiderState,
    *,
    cards: Optional[Sequence[Card]] = None,
    foundation: Optional[FoundationFeasibilityAnalysis] = None,
    locs: Optional[Sequence[CardLocation]] = None,
) -> Tuple[BuriedCardFact, ...]:
    """Heuristic value of each hidden card. Not every card should be exposed."""
    epoch = current_stock_epoch(state, 5)
    fa = foundation
    if fa is None and cards is not None:
        fa = analyze_foundation_feasibility(cards, state)
    availability = fa.static_availability if fa is not None else ()
    removed = _foundations_removed_by_suit(state)
    fragments = _same_suit_fragments_visible(state)
    locs = tuple(locs) if locs is not None else locate_all_cards(state)
    next_row = next_stock_row(state)
    next_incoming = tuple(next_row) if next_row is not None else ()

    facts: List[BuriedCardFact] = []
    for i in range(10):
        chain = build_reveal_chain(i, state)
        if chain is None:
            continue
        for hid in chain.hidden_cards:
            card = hid.card
            rel = None
            if availability:
                rel = _foundation_relevance_for_card(
                    card,
                    current_epoch=epoch,
                    availability=availability,
                    foundations_removed_by_suit=removed,
                )
            ss: List[str] = []
            for col_idx, top_r, bot_r in fragments.get(card.suit, []):
                if bot_r - 1 == card.rank:
                    ss.append(
                        f"extends {rank_str(top_r)}-{rank_str(bot_r)}{card.suit} "
                        f"on col {col_idx + 1}"
                    )
                if top_r + 1 == card.rank:
                    ss.append(
                        f"receives {rank_str(top_r)}{card.suit} on col {col_idx + 1}"
                    )
            # Destination for placing this card: any rank+1 (mixed legal).
            dests: Tuple[CardLocation, ...] = ()
            if card.rank < 13:
                dests = copies_of_rank(locs, card.rank + 1)
            # Same-suit dests preferred as structural notes
            ss_dests = tuple(d for d in dests if d.card.suit == card.suit)
            status = _best_prereq_status(dests)
            useful_ep = _earliest_dest_epoch(dests, epoch)
            if rel is not None and rel.earliest_any_candidate_epoch is not None:
                useful_ep = min(useful_ep, max(epoch, rel.earliest_any_candidate_epoch))

            incoming_role = False
            if next_incoming:
                inc_here = next_incoming[i]
                # Incoming on *this* column is a dest for the buried card, or
                # the buried card is the same-suit receiver for that incoming.
                if inc_here.rank == card.rank + 1:
                    incoming_role = True
                if inc_here.suit == card.suit and inc_here.rank + 1 == card.rank:
                    incoming_role = True
                # A same-suit destination copy arrives somewhere in the next row.
                if any(
                    inc_c.suit == card.suit and inc_c.rank == card.rank + 1
                    for inc_c in next_incoming
                ):
                    incoming_role = True

            notes: List[str] = []
            score = 0.0
            if ss:
                score += 28.0
                notes.extend(ss)
            if ss_dests and any(d.kind == LocationKind.FACE_UP_TOP for d in ss_dests):
                score += 16.0
                notes.append("same-suit dest currently a top")
            elif any(d.kind == LocationKind.FACE_UP_TOP for d in dests):
                score += 8.0
                notes.append("mixed dest currently a top")
            if rel is not None and rel.remaining_rank_demand > 0:
                if rel.theoretically_available_this_epoch:
                    score += 10.0
                    notes.append("foundation rank demanded this epoch")
                elif rel.first_available_next_epoch_or_later:
                    score += 3.0
                    notes.append("foundation rank demanded later")
            if incoming_role:
                score += 14.0
                notes.append("interacts with next stock row")
            if hid.reveal_order == 0:
                score += 4.0
            else:
                score -= 2.0 * hid.reveal_order
            if card.rank == 13 and not ss:
                score -= 4.0
                notes.append("king: needs empty to park, not a dest")

            # Urgency is not "expose everything".
            if ss or (
                hid.reveal_order <= 1
                and any(d.kind == LocationKind.FACE_UP_TOP for d in dests)
            ):
                urgency = Urgency.USEFUL_NOW
            elif incoming_role or (
                next_incoming is not None
                and status == PrereqStatus.FUTURE_STOCK
                and useful_ep == epoch + 1
            ):
                urgency = Urgency.USEFUL_BEFORE_NEXT_DEAL
            elif score <= 2.0:
                urgency = Urgency.CURRENTLY_LOW_VALUE
            else:
                urgency = Urgency.USEFUL_LATER

            # Next-deal dest only: bump before_next_deal even if later-looking.
            if status == PrereqStatus.FUTURE_STOCK and useful_ep == epoch + 1:
                if urgency == Urgency.USEFUL_LATER:
                    urgency = Urgency.USEFUL_BEFORE_NEXT_DEAL

            facts.append(
                BuriedCardFact(
                    card=card,
                    column=i,
                    reveal_order=hid.reveal_order,
                    min_reveals=hid.minimum_reveals_to_expose,
                    foundation=rel,
                    ss_join=tuple(ss),
                    dest_prereqs=dests,
                    prereq_status=status,
                    earliest_useful_epoch=useful_ep,
                    urgency=urgency,
                    value_score=score,
                    notes=tuple(notes),
                )
            )
    return tuple(sorted(facts, key=lambda f: (-f.value_score, f.min_reveals, f.column)))


# ---------------------------------------------------------------------------
# Column excavation projects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExcavationProject:
    column: int
    face_down: int
    face_up: int
    shortage: str
    dests_nonempty: Tuple[int, ...]
    approx_advance_cost: int
    approx_open_cost: int
    important: Tuple[str, ...]
    unlock_value: float
    latent_workspace: bool
    can_start_now: bool
    rank_score: float
    reasons: Tuple[str, ...]


def analyze_excavation_projects(
    state: SpiderState,
    buried: Sequence[BuriedCardFact],
) -> Tuple[ExcavationProject, ...]:
    """Rank columns as projects. Not raw face-down reduction."""
    profs = profile_state(state)
    by_col: Dict[int, List[BuriedCardFact]] = {i: [] for i in range(10)}
    for b in buried:
        by_col[b.column].append(b)
    projects: List[ExcavationProject] = []
    for p in profs:
        col = state.columns[p.column]
        if col.is_empty() or not col.face_down:
            # Fully open: still a latent-workspace project if non-king.
            if col.face_up and not col.face_down:
                nk = col.face_up[0].rank < 13
                reasons = []
                if nk:
                    reasons.append("already fully-open non-king (latent workspace)")
                else:
                    reasons.append("already fully-open king (needs empty to park)")
                projects.append(
                    ExcavationProject(
                        column=p.column,
                        face_down=0,
                        face_up=p.face_up,
                        shortage=p.shortage,
                        dests_nonempty=p.dests_nonempty,
                        approx_advance_cost=0,
                        approx_open_cost=0,
                        important=(),
                        unlock_value=12.0 if nk else 2.0,
                        latent_workspace=nk,
                        can_start_now=bool(p.dests),
                        rank_score=(18.0 if nk else 2.0) + (6.0 if p.one_move_creates else 0.0),
                        reasons=tuple(reasons),
                    )
                )
            continue
        cards = by_col[p.column]
        unlock = sum(max(0.0, c.value_score) for c in cards)
        now_n = sum(1 for c in cards if c.urgency == Urgency.USEFUL_NOW)
        soon_n = sum(1 for c in cards if c.urgency == Urgency.USEFUL_BEFORE_NEXT_DEAL)
        important = tuple(
            f"{c.card} d{c.reveal_order} {c.urgency.value} {c.value_score:.0f}"
            for c in sorted(cards, key=lambda x: -x.value_score)[:4]
        )
        # Advance = peel the current face-up run. Open = that plus remaining fd.
        advance = 1 if p.dests_nonempty else (2 if p.dests else 4)
        if p.shortage.startswith("king"):
            advance += 2
        if p.shortage == "no_visible_rank_plus_1_top":
            advance += 2
        open_cost = advance + max(0, p.face_down - 1)
        latent = True  # completing any non-empty fd column yields a fully-open pile
        # King-base after open is weaker latent workspace.
        deepest = col.face_down[0] if col.face_down else None
        if deepest is not None and deepest.rank == 13:
            latent = False
        reasons = [
            f"fd={p.face_down} unlock={unlock:.0f} now={now_n} soon={soon_n}",
            f"shortage={p.shortage} destNE={list(d + 1 for d in p.dests_nonempty)}",
        ]
        if latent:
            reasons.append("completion yields fully-open (likely non-king) workspace")
        can_start = bool(p.dests) or bool(p.moving_reveals and p.dests)
        # Rank: unlock per unit difficulty, not fd.
        rank = unlock / (1.0 + open_cost)
        rank += 8.0 * now_n + 4.0 * soon_n
        if can_start:
            rank += 3.0
        if latent and p.face_down <= 2:
            rank += 5.0
        projects.append(
            ExcavationProject(
                column=p.column,
                face_down=p.face_down,
                face_up=p.face_up,
                shortage=p.shortage,
                dests_nonempty=p.dests_nonempty,
                approx_advance_cost=advance,
                approx_open_cost=open_cost,
                important=important,
                unlock_value=unlock,
                latent_workspace=latent,
                can_start_now=bool(p.dests),
                rank_score=rank,
                reasons=tuple(reasons),
            )
        )
    return tuple(sorted(projects, key=lambda x: (-x.rank_score, x.approx_open_cost, x.column)))


# ---------------------------------------------------------------------------
# Space liquidity
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpaceUse:
    kind: str
    column: int
    approx_cost: int
    benefit: str
    value: float


@dataclass(frozen=True)
class SpaceLiquidity:
    spaces_now: int
    empty_columns: Tuple[int, ...]
    fully_open: int
    fully_open_nonking: int
    min_column_fd: int
    one_move_creates: int
    cheapest_create: Optional[int]
    create_status: str
    regain_if_consumed: Optional[int]
    recoverability: str
    consume_is_plausible: bool
    uses: Tuple[SpaceUse, ...]
    notes: Tuple[str, ...]


def _cheap_workspace_cost(state: SpiderState) -> Tuple[Optional[int], str]:
    n_open, n_nk, _min_fd = open_column_facts(state)
    profs = profile_state(state)
    if any(p.one_move_creates for p in profs):
        return 1, "fact: one-move create exists"
    if empty_count(state) > 0:
        return 0, "fact: space already exists"
    # Tight probe — diagnostic, not a search layer.
    res = realize_workspace(
        state,
        backend=WorkspaceBackend.IMPROVED,
        max_cost=6,
        max_nodes=400,
        time_limit_s=0.35,
    )
    if res.status == RealizationStatus.FOUND:
        return int(res.corrected_mw_cost or 0), f"improved probe nodes={res.nodes_expanded}"
    if res.status == RealizationStatus.ALREADY_SATISFIED:
        return 0, "already satisfied"
    return None, f"probe {res.status.value}"


def _option_uses(
    state: SpiderState, buried: Sequence[BuriedCardFact]
) -> Tuple[SpaceUse, ...]:
    """If one usable empty existed, what would we spend it on?"""
    uses: List[SpaceUse] = []
    by_col = {i: [] for i in range(10)}
    for b in buried:
        by_col[b.column].append(b)
    for i, col in enumerate(state.columns):
        if col.is_empty() or not col.face_up:
            continue
        k = 0
        for t in range(1, len(col.face_up) + 1):
            if state.is_desc_run(col.face_up[-t:]):
                k = t
            else:
                break
        if k <= 0:
            continue
        head = col.face_up[-k]
        whole = k == len(col.face_up)
        cost = 0 if (whole and not col.face_down) else 1
        cards = by_col[i]
        top_b = max(cards, key=lambda c: c.value_score) if cards else None
        if whole and col.face_down and top_b is not None:
            uses.append(
                SpaceUse(
                    "reveal_buried",
                    i,
                    cost,
                    f"dump col {i + 1} run onto empty, expose {top_b.card} "
                    f"({top_b.urgency.value}, {top_b.value_score:.0f})",
                    top_b.value_score + 6.0,
                )
            )
        elif whole and not col.face_down and head.rank < 13:
            uses.append(
                SpaceUse(
                    "relocate_open",
                    i,
                    0,
                    f"migrate fully-open col {i + 1} (latent workspace move)",
                    8.0,
                )
            )
        elif head.rank == 13:
            uses.append(
                SpaceUse(
                    "park_king",
                    i,
                    cost,
                    f"park King{head.suit} from col {i + 1}",
                    5.0 + (top_b.value_score if top_b and whole else 0.0),
                )
            )
        if any(c.urgency == Urgency.USEFUL_NOW for c in cards) and whole:
            uses.append(
                SpaceUse(
                    "continue_excavation",
                    i,
                    cost,
                    f"continue col {i + 1} project onto empty",
                    10.0 + sum(c.value_score for c in cards if c.urgency == Urgency.USEFUL_NOW),
                )
            )
    # Same-suit spine / receiver uses: empty as a holding bay.
    for i, col in enumerate(state.columns):
        if not col.face_up:
            continue
        run = 1
        up = col.face_up
        for j in range(len(up) - 2, -1, -1):
            if up[j].suit == up[j + 1].suit and up[j].rank - 1 == up[j + 1].rank:
                run += 1
            else:
                break
        if run >= 4:
            uses.append(
                SpaceUse(
                    "consolidate_spine",
                    i,
                    1,
                    f"hold/rebuild {run}-card same-suit spine on col {i + 1}",
                    9.0 + run,
                )
            )
    uses.sort(key=lambda u: -u.value)
    # Dedup (kind, column)
    seen = set()
    uniq: List[SpaceUse] = []
    for u in uses:
        key = (u.kind, u.column)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(u)
    return tuple(uniq[:8])


def analyze_space_liquidity(
    state: SpiderState,
    buried: Sequence[BuriedCardFact],
) -> SpaceLiquidity:
    n_open, n_nk, min_fd = open_column_facts(state)
    wp = workspace_potential(state)
    empties = empty_columns(state)
    spaces = len(empties)
    create, create_st = _cheap_workspace_cost(state)
    uses = _option_uses(state, buried)
    notes: List[str] = []
    regain: Optional[int] = None
    recov = "unknown"
    consume_ok = False
    if spaces == 0:
        recov = "no_space_to_consume"
        notes.append("no current empty; liquidity is the create-cost above")
        if n_nk >= 2:
            notes.append("several open non-kings: a created space is likely recoverable")
            recov = "likely_recoverable_once_created"
        elif n_nk == 0:
            recov = "poor_until_open_columns_exist"
    else:
        # Consume hypothetically: first legal consume of a non-full-open pile
        # or a park that reduces empty count, then re-probe create.
        st2 = state.clone()
        consumed = False
        for src, dst, k in st2.enumerate_moves():
            if not st2.columns[dst].is_empty():
                continue
            src_col = st2.columns[src]
            # Prefer a consume (source not fully emptied) so empty count drops.
            will_empty_src = k == len(src_col.face_up) and not src_col.face_down
            if will_empty_src:
                continue
            st2.move(src, dst, k, rules=MW_RULES)
            consumed = True
            break
        if consumed:
            regain, rst = _cheap_workspace_cost(st2)
            notes.append(f"after one consume: recreate {regain} ({rst})")
            if regain is not None and regain <= 2:
                recov = "cheap_regain"
                consume_ok = True
            elif regain is not None and regain <= 4:
                recov = "moderate_regain"
                consume_ok = True
            else:
                recov = "expensive_or_unknown_regain"
        else:
            recov = "only_relocates_available"
            notes.append("every empty-dest move relocates; count would not drop")
        top = uses[0] if uses else None
        if top is not None and top.value >= 16.0:
            consume_ok = True
            notes.append(f"high-value use {top.kind} col {top.column + 1} val={top.value:.0f}")
    return SpaceLiquidity(
        spaces_now=spaces,
        empty_columns=empties,
        fully_open=n_open,
        fully_open_nonking=n_nk,
        min_column_fd=min_fd,
        one_move_creates=int(wp["one_move_creates"]),
        cheapest_create=create,
        create_status=create_st,
        regain_if_consumed=regain,
        recoverability=recov,
        consume_is_plausible=consume_ok,
        uses=uses,
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# Known-stock backward pass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReceiverWish:
    column: int
    incoming: Card
    landing_now: str
    desired_top: str
    reason: str
    importance: float


@dataclass(frozen=True)
class StockBackwardPass:
    can_deal: bool
    epoch_before: int
    incoming: Tuple[Tuple[int, str], ...]
    landings: Tuple[str, ...]
    receiver_wishes: Tuple[ReceiverWish, ...]
    cards_wanted_before: Tuple[str, ...]
    carry_empty_assessment: str
    fill_then_recreate_assessment: str
    recommendation: str
    post_deal_empty: int
    post_deal_ws_cost: Optional[int]
    post_deal_open_nk: int
    projects_unlocked: Tuple[str, ...]
    notes: Tuple[str, ...]


def analyze_stock_backward(
    state: SpiderState,
    *,
    cards: Optional[Sequence[Card]] = None,
    buried: Optional[Sequence[BuriedCardFact]] = None,
) -> StockBackwardPass:
    """Simulate the exact next row and reason *backwards*.

    Explicitly allows: space>0 → fill it → DEAL → cheaply recreate after.
    More pre-deal empties is not assumed better.
    """
    row = next_stock_row(state)
    epoch = current_stock_epoch(state, 5)
    if row is None:
        return StockBackwardPass(
            False,
            epoch,
            (),
            (),
            (),
            (),
            "no_deal",
            "no_deal",
            "no_deal",
            empty_count(state),
            None,
            open_column_facts(state)[1],
            (),
            ("no stock remaining",),
        )
    rec = analyze_stock_reception(
        state, cards=cards, run_shaping_probe=False
    )
    buried = buried if buried is not None else analyze_buried_cards(state, cards=cards)
    wishes: List[ReceiverWish] = []
    wanted: List[str] = []
    unlocked: List[str] = []
    notes: List[str] = []
    for cf in rec.columns:
        inc = cf.incoming
        landing = cf.landing.value
        # Same-suit receiver: want pre-deal top = incoming.rank+1 same suit.
        if inc.rank < 13:
            need = inc.rank + 1
            desired = f"{rank_str(need)}{inc.suit}"
        else:
            need = None
            desired = "empty (King)"
        imp = 4.0
        reason = f"incoming {inc} currently {landing}"
        if cf.landing == LandingKind.SAME_SUIT_CONNECT:
            imp = 2.0
            reason = "already same-suit connect"
        elif cf.landing == LandingKind.MIXED_RANK_CONNECT:
            imp = 8.0
            reason = "rank connects mixed; same-suit top would be better"
        elif cf.landing == LandingKind.EMPTY_LANDING:
            imp = 6.0
            reason = "lands on empty: occupies workspace unless it walks off"
        elif cf.landing == LandingKind.NON_CONNECTING:
            imp = 10.0
            reason = "non-connecting: a prepared receiver would unlock this card"
        if cf.is_foundation_limiting_card or cf.enables_foundation_this_epoch:
            imp += 6.0
            reason += "; foundation-relevant"
        wishes.append(
            ReceiverWish(cf.column, inc, landing, desired, reason, imp)
        )
        if cf.landing in (LandingKind.NON_CONNECTING, LandingKind.MIXED_RANK_CONNECT):
            wanted.append(
                f"{desired} exposed as col {cf.column + 1} top before deal "
                f"(for incoming {inc})"
            )
        # Incoming as dest for a currently buried card.
        for b in buried:
            if b.card.rank + 1 == inc.rank and (
                b.urgency in (Urgency.USEFUL_NOW, Urgency.USEFUL_BEFORE_NEXT_DEAL)
                or b.ss_join
            ):
                unlocked.append(
                    f"incoming {inc} on col {cf.column + 1} dests buried "
                    f"{b.card} (col {b.column + 1})"
                )
            if inc.rank + 1 == b.card.rank and b.card.suit == inc.suit:
                unlocked.append(
                    f"incoming {inc} can extend toward buried {b.card}"
                )

    st_post = state.clone()
    st_post.deal()
    post_e = empty_count(st_post)
    post_ws, post_st = _cheap_workspace_cost(st_post)
    post_nk = open_column_facts(st_post)[1]
    notes.append(f"post-deal empty={post_e} ws={post_ws} ({post_st}) open_nk={post_nk}")

    spaces = empty_count(state)
    # Carry vs fill.
    carry = "n/a_no_empty"
    fill = "n/a_no_empty"
    rec_txt = "deal_with_zero_empty"
    if spaces > 0:
        empty_landings = [
            cf
            for cf in rec.columns
            if cf.landing == LandingKind.EMPTY_LANDING
        ]
        recover = rec.next_stock_recovery if False else analyze_next_stock_recovery(state)
        one_move_rec = [
            p
            for p in recover.per_column
            if p.immediate_recovery.value == "recovers_same_column"
        ]
        # Simulate fill then deal: consume without relocating if possible.
        st_fill = state.clone()
        filled = False
        for src, dst, k in st_fill.enumerate_moves():
            if not st_fill.columns[dst].is_empty():
                continue
            src_col = st_fill.columns[src]
            if k == len(src_col.face_up) and not src_col.face_down:
                continue
            st_fill.move(src, dst, k, rules=MW_RULES)
            filled = True
            break
        fill_post_ws: Optional[int] = None
        fill_post_e = None
        if filled:
            st_fill.deal()
            fill_post_e = empty_count(st_fill)
            fill_post_ws, fst = _cheap_workspace_cost(st_fill)
            notes.append(
                f"fill-then-deal: post empty={fill_post_e} ws={fill_post_ws} ({fst})"
            )
        if empty_landings and not one_move_rec:
            carry = (
                "poor: incoming occupies empty and no one-move same-column recovery"
            )
        elif empty_landings and one_move_rec:
            carry = "possible: incoming on empty has a one-move walk-off"
        else:
            carry = "empty would not receive this row (unexpected)"
        if filled and fill_post_ws is not None and fill_post_ws <= 2:
            fill = f"attractive: post-deal recreate cost {fill_post_ws}"
        elif filled and fill_post_ws is None:
            fill = "fill possible but post-deal recreate not found in probe"
        elif not filled:
            fill = "no consuming fill found (only relocations)"
        else:
            fill = f"fill possible; post-deal recreate {fill_post_ws}"
        # Recommendation: fill if incoming would sit on empty without recovery
        # and recreate after is cheap; else carry only if recovery is HARD-true.
        if fill.startswith("attractive") and (
            empty_landings and not one_move_rec
        ):
            rec_txt = "fill_then_deal_then_recreate"
        elif one_move_rec:
            rec_txt = "carry_empty_if_needed_recovery_exists"
        elif fill.startswith("attractive"):
            rec_txt = "fill_then_deal_then_recreate"
        else:
            rec_txt = "ambiguous_space_policy"
    else:
        # empty=0: carrying is unavailable. Ask whether *creating* a space
        # just to carry it through the deal is worth it.
        n_ss = rec.row_summary.n_same_suit_landings
        n_nc = rec.row_summary.n_non_connecting
        notes.append(
            f"pre-deal empty=0; row ss={n_ss} mixed={rec.row_summary.n_mixed_rank_landings} "
            f"non={n_nc}"
        )
        if post_ws is not None and post_ws <= 2:
            rec_txt = "deal_now_workspace_recreates_cheaply_after"
            fill = "creating-then-filling is unnecessary if post-deal recreate is already cheap"
            carry = "creating-then-carrying not justified: post-deal already cheap"
        else:
            rec_txt = "shape_receivers_then_deal_do_not_fetishize_empty"
            carry = "creating an empty just to carry it through this deal is not supported"
            fill = "if a space appears, prefer fill-before-deal when incoming would occupy it"

    wishes.sort(key=lambda w: -w.importance)
    return StockBackwardPass(
        True,
        epoch,
        tuple((cf.column, str(cf.incoming)) for cf in rec.columns),
        tuple(cf.landing.value for cf in rec.columns),
        tuple(wishes),
        tuple(wanted[:8]),
        carry,
        fill,
        rec_txt,
        post_e,
        post_ws,
        post_nk,
        tuple(unlocked[:8]),
        tuple(notes),
    )


# ---------------------------------------------------------------------------
# Meet-in-the-middle rank
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RankedProject:
    column: int
    combined: float
    forward: float
    backward: float
    stock: float
    space: float
    label: str
    reasons: Tuple[str, ...]


def rank_projects_meet_in_middle(
    state: SpiderState,
    projects: Sequence[ExcavationProject],
    buried: Sequence[BuriedCardFact],
    stock: StockBackwardPass,
    liquidity: SpaceLiquidity,
) -> Tuple[RankedProject, ...]:
    """Combine tactical feasibility (forward) with downstream need (backward).

    Cheap shallow reveals with no downstream role should lose to slightly
    harder projects that unlock dests, stock receivers, or latent workspace.
    """
    wanted_cols = set()
    for w in stock.receiver_wishes:
        if w.importance >= 8.0:
            wanted_cols.add(w.column)
    soon_cols = {
        b.column
        for b in buried
        if b.urgency in (Urgency.USEFUL_NOW, Urgency.USEFUL_BEFORE_NEXT_DEAL)
    }
    ranked: List[RankedProject] = []
    for p in projects:
        # Forward: can we start, and how expensive is progress.
        if p.face_down == 0:
            fwd = 0.9 if p.can_start_now else 0.4
        elif p.can_start_now:
            fwd = 1.0 / (1.0 + 0.25 * p.approx_advance_cost)
        else:
            fwd = 0.25 / (1.0 + 0.2 * p.approx_open_cost)
        bwd = min(40.0, p.unlock_value) / 40.0
        if p.latent_workspace and p.face_down <= 3:
            bwd += 0.15
        stk = 0.0
        if p.column in wanted_cols:
            stk += 0.6
        if p.column in soon_cols:
            stk += 0.3
        # Space: a project that *creates* recoverable workspace scores up when
        # liquidity is poor; a project that only needs space scores down then.
        if liquidity.spaces_now == 0:
            if p.latent_workspace and p.face_down <= 2:
                spc = 0.5
            elif p.can_start_now:
                spc = 0.25
            else:
                spc = 0.05
        else:
            spc = 0.35 if p.can_start_now else 0.2
        combined = (0.55 * bwd + 0.20 * stk + 0.10 * spc) * (0.35 + 0.65 * fwd)
        # Pure fd-reduction with no unlock stays small.
        if p.unlock_value < 4.0 and p.face_down > 0:
            combined *= 0.55
        label = (
            f"col {p.column + 1} fd={p.face_down} unlock={p.unlock_value:.0f} "
            f"open~{p.approx_open_cost}"
        )
        reasons = p.reasons + (
            f"fwd={fwd:.2f} bwd={bwd:.2f} stock={stk:.2f} space={spc:.2f}",
        )
        ranked.append(
            RankedProject(
                p.column, combined, fwd, bwd, stk, spc, label, reasons
            )
        )
    return tuple(sorted(ranked, key=lambda r: (-r.combined, r.column)))


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------


@dataclass
class BackwardAnalysis:
    epoch: int
    buried: Tuple[BuriedCardFact, ...]
    projects: Tuple[ExcavationProject, ...]
    liquidity: SpaceLiquidity
    stock: StockBackwardPass
    ranked: Tuple[RankedProject, ...]
    top_uses: Tuple[SpaceUse, ...]


def analyze_backward(
    state: SpiderState,
    *,
    cards: Optional[Sequence[Card]] = None,
) -> BackwardAnalysis:
    epoch = current_stock_epoch(state, 5)
    locs = locate_all_cards(state)
    fa = None
    if cards is not None:
        fa = analyze_foundation_feasibility(cards, state)
    buried = analyze_buried_cards(state, cards=cards, foundation=fa, locs=locs)
    projects = analyze_excavation_projects(state, buried)
    liquidity = analyze_space_liquidity(state, buried)
    stock = analyze_stock_backward(state, cards=cards, buried=buried)
    ranked = rank_projects_meet_in_middle(
        state, projects, buried, stock, liquidity
    )
    return BackwardAnalysis(
        epoch=epoch,
        buried=buried,
        projects=projects,
        liquidity=liquidity,
        stock=stock,
        ranked=ranked,
        top_uses=liquidity.uses,
    )
