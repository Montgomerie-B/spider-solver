"""Inventory-valid reconstructions of the six new PR4 motifs.

``DECK_LABEL`` is ``constructed_inventory_valid``.
``OPENING_REACHABILITY`` is ``unestablished``. These positions are
known-motif replication controls. They are not opening replays, deal
samples, autonomous solves, or whole-game evidence.

Construction rule ``spine-plus-inert-top-and-foundation-sink``:

1. Start from two copies of every suit and rank.
2. Place the motif spine as face-up cards, bottom to top. The spine is
   the abstract mechanism only. The abstract buried fillers are not copied.
3. Fill columns that are still empty with inert tops. Scan ranks from
   king down to ace. Skip a rank that is adjacent to a current top, or
   adjacent to the contact card of a current movable run, or adjacent to
   an inert rank already chosen. Among suits that still have two copies,
   in order spades, hearts, diamonds, clubs, place one card on each
   still-empty column.
4. Extract completed foundations in suit order spades, hearts, diamonds,
   clubs. A foundation is king through ace of one suit. Repeat while any
   suit still has every rank.
5. Sort the remainder by rank, then by that suit order. Give one
   face-down card to each column that is not free, the target column
   first.
6. Place every remaining card as face-up body under the lowest-index
   column that is neither the target nor free, and only when the card
   does not form a same-suit descending bond with the current bottom.
7. Leave the stock empty.

The target receives no body: the reveal predicate fires when that
column's face-up cards leave. Workspace columns 2 and 4 are free, so
each keeps its single mechanism card and no face-down card. A later
whole-column move onto an empty column can then cost 0.

Face-down limits are the post-flip maxima from ``SpiderState.from_cards``:
at most 5 in columns 0-3, at most 4 in columns 4-9, and at most 44 in
total. They are maxima, not exact fills, and they do not cap the total
column length. Length caps of 5 and 4 would hold 44 tableau cards.
``104 - 44 = 60`` is not a multiple of 13, so an empty stock and
complete foundations could not both exist under that reading.

Inert tops may repeat a rank that is already showing. A repeated nine
adds no root action while the club eight is covered. After that eight
is exposed, each nine is another rank receiver. Body cards sit under
one column and stay outside the initial movable run. Both effects are
physical differences from the abstract panel.

This module does not search.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Sequence, Tuple

from spider.cards import Card
from spider.dependency_objective_panel import COMPARISON_BUDGET
from spider.dependency_options import (
    build_option,
    rebuild_obligations,
    select_dependency_portfolio,
)
from spider.engine import Column, SpiderState
from spider.research_actions import tableau_actions

DECK_LABEL = "constructed_inventory_valid"
OPENING_REACHABILITY = "unestablished"
CONSTRUCTION_RULE = "spine-plus-inert-top-and-foundation-sink"
SUITS = "shdc"
FACE_DOWN_CAP: Tuple[int, ...] = (5, 5, 5, 5, 4, 4, 4, 4, 4, 4)
FACE_DOWN_TOTAL_CAP = 44

# The validation uses the frozen panel budget. It does not define another one.
assert COMPARISON_BUDGET["max_unique"] == 20
assert COMPARISON_BUDGET["cost_ceiling"] == 4
assert COMPARISON_BUDGET["workers"] == 1


@dataclass(frozen=True)
class ReplayCase:
    """A scripted mechanism path. This is not a search result."""

    actions: Tuple[Tuple[int, int, int], ...]
    costs: Tuple[int, ...]
    revealed_at_end: bool


@dataclass(frozen=True)
class InventorySource:
    """One frozen full-inventory source."""

    source_id: str
    target_column: int
    free_columns: Tuple[int, ...]
    mechanism: Tuple[str, ...]
    face_down: Tuple[str, ...]
    face_up: Tuple[str, ...]
    foundations: Tuple[str, ...]
    foundation_suits: Tuple[str, ...]
    inert_tops: Tuple[Tuple[int, str], ...]
    body_counts: Tuple[int, ...]
    legal_actions: Tuple[Tuple[int, int, int], ...]
    baseline_id: str


@dataclass(frozen=True)
class _Spec:
    source_id: str
    target_column: int
    free_columns: Tuple[int, ...]
    mechanism: Tuple[str, ...]
    legal_actions: Tuple[Tuple[int, int, int], ...]
    baseline_id: str
    replays: Tuple[ReplayCase, ...]


def _spec(
    source_id: str,
    target_column: int,
    free_columns: Tuple[int, ...],
    mechanism: Tuple[str, ...],
    legal_actions: Tuple[Tuple[int, int, int], ...],
    baseline_id: str,
    replays: Tuple[ReplayCase, ...],
) -> _Spec:
    if len(mechanism) != 10:
        raise ValueError(f"{source_id} needs 10 mechanism columns")
    return _Spec(
        source_id,
        target_column,
        free_columns,
        mechanism,
        legal_actions,
        baseline_id,
        replays,
    )


_SPECS: Tuple[_Spec, ...] = (
    _spec(
        "blocker-chain",
        0,
        (),
        ("7c", "8c 9d", "10h", "2h", "3h", "", "", "", "", ""),
        ((1, 2, 1), (3, 4, 1)),
        "(3, 4, 1)",
        (
            ReplayCase(((3, 4, 1), (1, 2, 1), (0, 1, 1)), (1, 1, 1), True),
            ReplayCase(((1, 2, 1), (0, 1, 1)), (1, 1), True),
        ),
    ),
    _spec(
        "immediate-join",
        5,
        (),
        ("4s 3s", "5s", "", "", "", "8c", "9c", "", "", ""),
        ((0, 1, 2), (5, 6, 1)),
        "(0, 1, 2)",
        (
            ReplayCase(((0, 1, 2), (5, 6, 1)), (1, 1), True),
            ReplayCase(((5, 6, 1),), (1,), True),
        ),
    ),
    _spec(
        "symmetric-tie",
        0,
        (),
        ("8c 3h", "9c", "4d", "", "4s", "", "", "", "", ""),
        ((0, 2, 1), (0, 4, 1)),
        "(0, 2, 1)",
        (
            ReplayCase(((0, 2, 1), (0, 1, 1)), (1, 1), True),
            ReplayCase(((0, 4, 1), (0, 1, 1)), (1, 1), True),
        ),
    ),
    _spec(
        "distractor-reveal",
        0,
        (),
        ("8c 3h", "9c", "4d", "9c", "", "qs", "ks", "", "", ""),
        ((0, 2, 1), (5, 6, 1)),
        "(5, 6, 1)",
        (
            ReplayCase(((5, 6, 1), (0, 2, 1), (0, 1, 1)), (1, 1, 1), True),
            ReplayCase(((0, 2, 1), (0, 1, 1)), (1, 1), True),
            ReplayCase(((5, 6, 1),), (1,), False),
        ),
    ),
    _spec(
        "three-deep-uncover",
        0,
        (),
        ("8c 4d 3h", "9c", "4s", "5h", "qd", "kd", "", "", "", ""),
        ((0, 2, 1), (2, 3, 1), (4, 5, 1)),
        "(4, 5, 1)",
        (
            ReplayCase(((4, 5, 1), (0, 2, 1), (0, 3, 1), (0, 1, 1)), (1, 1, 1, 1), True),
            ReplayCase(((0, 2, 1), (0, 3, 1), (0, 1, 1)), (1, 1, 1), True),
            ReplayCase(((2, 3, 1),), (1,), False),
        ),
    ),
    _spec(
        "zero-cost-workspace",
        0,
        (2, 4),
        ("8c 3h", "9c", "10d", "jh", "kd", "6s", "7s", "", "", ""),
        ((1, 2, 1), (2, 3, 1), (5, 6, 1)),
        "(5, 6, 1)",
        (
            ReplayCase(((2, 3, 1), (4, 2, 1)), (1, 0), False),
            ReplayCase(((5, 6, 1),), (1,), False),
            ReplayCase(((1, 2, 1),), (1,), False),
        ),
    ),
)

MECHANISM_REPLAYS: Dict[str, Tuple[ReplayCase, ...]] = {
    spec.source_id: spec.replays for spec in _SPECS
}


def _deck() -> list:
    return [Card(suit, rank) for suit in SUITS for rank in range(1, 14) for _ in range(2)]


def _count(pool: Sequence[Card], suit: str, rank: int) -> int:
    return sum(1 for card in pool if card.suit == suit and card.rank == rank)


def _take(pool: list, suit: str, rank: int) -> Card:
    for index, card in enumerate(pool):
        if card.suit == suit and card.rank == rank:
            return pool.pop(index)
    raise RuntimeError(f"missing {rank}{suit}")


def _parse_cards(text: str) -> list:
    return [Card.parse(token) for token in text.split() if token]


def _render(cards: Sequence[Card]) -> str:
    return " ".join(str(card) for card in cards)


def _forbidden(columns: Sequence[Sequence[Card]]) -> set:
    banned = set()
    for cards in columns:
        if not cards:
            continue
        top = cards[-1].rank
        banned.update((top - 1, top + 1))
        for length in range(1, len(cards) + 1):
            run = list(cards[-length:])
            if SpiderState.is_movable_run(run):
                banned.add(run[0].rank + 1)
    return {rank for rank in banned if 1 <= rank <= 13}


def _place_inert(columns: list, pool: list) -> Tuple[Tuple[int, str], ...]:
    chosen: list = []
    placed: list = []
    while any(not cards for cards in columns):
        placed_rank = False
        for rank in range(13, 0, -1):
            if rank in _forbidden(columns):
                continue
            if any(abs(rank - previous) == 1 for previous in chosen):
                continue
            suits = [suit for suit in SUITS if _count(pool, suit, rank) >= 2]
            if not suits:
                continue
            used = False
            for index, cards in enumerate(columns):
                if cards or not suits:
                    continue
                card = _take(pool, suits.pop(0), rank)
                columns[index] = [card]
                placed.append((index, str(card)))
                used = True
                if not suits:
                    break
            if used:
                chosen.append(rank)
                placed_rank = True
                break
        if not placed_rank:
            raise RuntimeError("inert-top placement could not fill every column")
    return tuple(placed)


def _extract_foundations(pool: list) -> list:
    found = []
    progressed = True
    while progressed:
        progressed = False
        for suit in SUITS:
            if all(_count(pool, suit, rank) >= 1 for rank in range(1, 14)):
                found.append([_take(pool, suit, rank) for rank in range(13, 0, -1)])
                progressed = True
                break
    return found


def _bonds(lower: Card, upper: Card) -> bool:
    return lower.suit == upper.suit and lower.rank == upper.rank + 1


def _place_body(columns: list, pool: list, protected: set) -> None:
    pool.sort(key=lambda card: (card.rank, SUITS.index(card.suit), str(card)))
    pending = list(pool)
    stalled = 0
    while pending:
        card = pending.pop(0)
        placed = False
        for index in range(10):
            if index in protected or not columns[index]:
                continue
            if not _bonds(card, columns[index][0]):
                columns[index].insert(0, card)
                placed = True
                stalled = 0
                break
        if not placed:
            pending.append(card)
            stalled += 1
            if stalled > len(pending):
                raise RuntimeError(f"body card {card} could not be placed")


def _same_suit_descending(cards: Sequence[Card]) -> bool:
    if not cards:
        return False
    suit = cards[0].suit
    for index in range(len(cards) - 1):
        left = cards[index]
        right = cards[index + 1]
        if left.suit != suit or right.suit != suit or left.rank - 1 != right.rank:
            return False
    return True


def inventory_shape_failures(state: SpiderState) -> Tuple[str, ...]:
    """Return static inventory and shape failures.

    This helper counts cards and reads sequences. It does not judge moves.
    """

    failures = []
    if len(state.columns) != 10:
        failures.append(f"column-count:{len(state.columns)}")
    cards = []
    hidden = []
    for index, column in enumerate(state.columns):
        cards.extend(column.face_down)
        cards.extend(column.face_up)
        hidden.append(len(column.face_down))
        if column.face_down and not column.face_up:
            failures.append(f"face-down-without-top:{index}")
        cap = FACE_DOWN_CAP[index] if index < len(FACE_DOWN_CAP) else 0
        if len(column.face_down) > cap:
            failures.append(f"hidden-cap:{index}")
        if len(column.face_up) >= 13 and _same_suit_descending(column.face_up[-13:]):
            if column.face_up[-13].rank == 13:
                failures.append(f"latent-sequence:{index}")
    cards.extend(state.stock)
    if len(state.stock) != 0:
        failures.append(f"stock:{len(state.stock)}")
    if sum(hidden) > FACE_DOWN_TOTAL_CAP:
        failures.append(f"hidden-total:{sum(hidden)}")
    for sequence in state.foundations:
        cards.extend(sequence)
        complete = (
            len(sequence) == 13
            and sequence[0].rank == 13
            and sequence[-1].rank == 1
            and _same_suit_descending(sequence)
        )
        if not complete:
            failures.append("foundation-shape")
    if len(cards) != 104:
        failures.append(f"card-count:{len(cards)}")
    counts: Dict[Tuple[str, int], int] = {}
    for card in cards:
        key = (card.suit, card.rank)
        counts[key] = counts.get(key, 0) + 1
    expected = {(suit, rank): 2 for suit in SUITS for rank in range(1, 14)}
    if counts != expected:
        failures.append("two-copy")
    return tuple(failures)


def build_state(source: InventorySource) -> SpiderState:
    """Return a fresh state for one frozen source."""

    columns = [
        Column(_parse_cards(down), _parse_cards(up))
        for down, up in zip(source.face_down, source.face_up)
    ]
    foundations = [_parse_cards(sequence) for sequence in source.foundations]
    return SpiderState(columns, [], foundations)


def _build(spec: _Spec) -> InventorySource:
    pool = _deck()
    columns: list = [[] for _ in range(10)]
    for index, text in enumerate(spec.mechanism):
        columns[index] = _parse_cards(text)
        for card in columns[index]:
            _take(pool, card.suit, card.rank)
    inert_tops = _place_inert(columns, pool)
    foundations = _extract_foundations(pool)
    free = set(spec.free_columns)
    order = [spec.target_column] + [
        index for index in range(10) if index != spec.target_column and index not in free
    ]
    pool.sort(key=lambda card: (card.rank, SUITS.index(card.suit)))
    face_down: list = [[] for _ in range(10)]
    for index in order:
        if not pool:
            raise RuntimeError(f"{spec.source_id} ran out of face-down cards")
        face_down[index].append(pool.pop(0))
    protected = free | {spec.target_column}
    _place_body(columns, pool, protected)
    source = InventorySource(
        source_id=spec.source_id,
        target_column=spec.target_column,
        free_columns=spec.free_columns,
        mechanism=spec.mechanism,
        face_down=tuple(_render(cards) for cards in face_down),
        face_up=tuple(_render(cards) for cards in columns),
        foundations=tuple(_render(sequence) for sequence in foundations),
        foundation_suits=tuple(sequence[0].suit for sequence in foundations),
        inert_tops=inert_tops,
        body_counts=tuple(
            len(columns[index]) - (len(_parse_cards(spec.mechanism[index])) or 1)
            for index in range(10)
        ),
        legal_actions=(),
        baseline_id="",
    )
    state = build_state(source)
    failures = inventory_shape_failures(state)
    if failures:
        raise RuntimeError(f"{spec.source_id} shape failures: {failures}")
    if len(state.columns[spec.target_column].face_down) != 1:
        raise RuntimeError(f"{spec.source_id} target has no face-down card")
    if source.face_up[spec.target_column] != spec.mechanism[spec.target_column]:
        raise RuntimeError(f"{spec.source_id} target face-up differs from the mechanism")
    legal = tuple(tableau_actions(state))
    engine_legal = tuple(state.enumerate_legal_actions())
    if ("deal",) in engine_legal or state.can_deal():
        raise RuntimeError(f"{spec.source_id} has a legal deal")
    if set(engine_legal) != set(legal) or legal != spec.legal_actions:
        raise RuntimeError(f"{spec.source_id} legal set {legal} != {spec.legal_actions}")
    if len(legal) > 8:
        raise RuntimeError(f"{spec.source_id} has {len(legal)} candidates")
    obligations = rebuild_obligations(state)
    options = tuple(
        build_option(
            state,
            (action,),
            source_g=0,
            structural_name=str(action),
            option_id=str(action),
            obligations=obligations,
        )
        for action in legal
    )
    pick = select_dependency_portfolio(options, obligations, limit=len(options))
    if pick.obligations_status != "matched" or not pick.chosen:
        raise RuntimeError(f"{spec.source_id} selector did not match")
    if pick.chosen[0].option_id != spec.baseline_id:
        raise RuntimeError(
            f"{spec.source_id} baseline {pick.chosen[0].option_id} != {spec.baseline_id}"
        )
    return InventorySource(
        source_id=source.source_id,
        target_column=source.target_column,
        free_columns=source.free_columns,
        mechanism=source.mechanism,
        face_down=source.face_down,
        face_up=source.face_up,
        foundations=source.foundations,
        foundation_suits=source.foundation_suits,
        inert_tops=source.inert_tops,
        body_counts=source.body_counts,
        legal_actions=legal,
        baseline_id=pick.chosen[0].option_id,
    )


INVENTORY_SOURCES: Tuple[InventorySource, ...] = tuple(_build(spec) for spec in _SPECS)


def inventory_sources() -> Tuple[InventorySource, ...]:
    return INVENTORY_SOURCES


def source_by_id(source_id: str) -> InventorySource:
    for source in INVENTORY_SOURCES:
        if source.source_id == source_id:
            return source
    raise KeyError(source_id)
