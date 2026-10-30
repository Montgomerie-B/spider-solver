"""Dependency-aware tactical options.

Research-only proposals. An option is a replay of existing primitives.
It is not a substitute move, not a proof, and not a second search.

``dependency_penalty`` is a portfolio sort key. It is not added to
``h_target`` and it is not an argument of ``kernel_lower_bound``.
The Human Strategy Controller does not import this module.

``source_g`` is the caller's declared base. Admission checks the incremental
identity ``target_g == source_g + cost``. That identity is not an opening
cost. Absolute ``g`` stays ``unestablished`` unless a separate source-cost
claim replays from a trusted ``g=0`` root. It is not a rank key and not a
proof term.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.human_strategy.evaluation import (
    admissible_remaining,
    mixed_boundaries,
    same_suit_bonds,
)
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.planner.stock_reception import next_stock_row
from spider.purposeful_macro import WorkspaceAudit, audit_workspace
from spider.research_actions import (
    all_legal_actions,
    apply_action,
    empty_column_indices,
    face_down_count,
    is_deal,
    step_cost,
    stock_rows,
    tableau_actions,
)

SUITS = ("s", "h", "d", "c")
_TACTICAL = ("JOIN", "REVEAL")


class OptionContractError(RuntimeError):
    """An option action is illegal, or its replay cost disagrees with ``step_cost``."""


@dataclass(frozen=True)
class StatePredicate:
    """Measurable state fact. No canonical move index. No deal id."""

    kind: str
    subject: tuple


@dataclass(frozen=True)
class EffectDelta:
    foundations: int
    face_down: int
    bonds: int
    mixed_joins: int
    empty_count: int
    top_run_by_suit: tuple
    stock_rows: int
    exposed_cards: int


@dataclass(frozen=True)
class TacticalOption:
    option_id: str
    structural_name: str
    source_pack: str
    source_symmetry: Optional[str]
    source_g: int
    actions: tuple
    cost: int
    target_pack: str
    target_g: int
    preconditions: tuple
    postconditions: tuple
    effects: EffectDelta
    workspace: WorkspaceAudit
    broken_dependencies: tuple
    outstanding_obligations: tuple
    enables: tuple
    blocks: tuple
    h_target: int
    f_target: int
    target_bonds: int
    finishability_proof: bool
    dependency_penalty: int
    replay_ok: bool
    provenance: str
    independent_cold_complete: bool
    source_g_provenance: str = "unestablished"
    unresolved_dependencies: tuple = ()


@dataclass(frozen=True)
class ObligationNode:
    obligation_id: str
    kind: str
    satisfied: bool
    requires_all: tuple
    requires_any: tuple
    landing: Optional[tuple]


@dataclass(frozen=True)
class AncestorClaim:
    """Replay-verified checkpoint that reaches an option source.

    The ancestor is ``checkpoint_pack``. It is not the option's own pack
    and it is not inferred from the stock length. ``continuation`` is the
    legal action list from that checkpoint to ``source_pack``. An empty
    continuation is valid only when the source already is that checkpoint.
    """

    checkpoint_pack: str
    continuation: tuple
    source_pack: str
    label: str = ""


@dataclass(frozen=True)
class SourceCostClaim:
    """Opt-in corrected-cost replay from a trusted ``g=0`` opening.

    ``continuation`` is the legal action list from ``opening_pack`` to
    ``source_pack``. An empty continuation is valid only when ``source_g``
    is 0 and the source already is that opening. This is not an ancestor
    claim. A verified checkpoint proves checkpoint-to-source reachability,
    not the corrected cost from the opening.
    """

    opening_pack: str
    continuation: tuple
    source_pack: str
    source_g: int


@dataclass(frozen=True)
class PortfolioPick:
    chosen: tuple
    diverse_ancestor_available: bool
    omitted_not_proved_impossible: bool
    breakers_not_proof_pruned: tuple
    ancestor_status: str = "not_established"
    verified_checkpoint_packs: tuple = ()
    rejected_ancestor_claims: int = 0
    obligations_status: str = "matched"
    receive_protection: str = "not_present"
    protected_ids: tuple = ()
    unsupported_receive_ids: tuple = ()
    source_signatures: tuple = ()
    outcome_signatures: tuple = ()
    source_g_provenance: str = "unestablished"
    absolute_g_used_for_proof: bool = False
    rejected_source_cost_claims: int = 0


@dataclass(frozen=True)
class BoundGapRecord:
    """Illustration of bound informativeness. Not written, and not a prune."""

    label: str
    g: int
    h: int
    f: int
    true_remaining: Optional[int]
    gap: Optional[int]
    gap_versus: str
    proof_dead_under_171: bool
    screen_f_le_170: bool
    identity_note: str


@dataclass(frozen=True)
class _Interval:
    column: int
    suit: str
    low: int
    high: int
    start: int
    end: int


@dataclass(frozen=True)
class _OpenNode:
    obligation_id: str
    kind: str
    column: int
    suit: str
    low: int
    high: int
    landing_count: int
    actionable: bool
    requires_all: tuple
    requires_any: tuple
    landing: Optional[tuple]
    face_down_at_build: int


def _top_run_length(state: SpiderState, suit: str) -> int:
    best = 0
    for column in state.columns:
        up = column.face_up
        if not up or up[-1].suit != suit:
            continue
        length = 1
        index = len(up) - 1
        while (
            index > 0
            and up[index - 1].suit == suit
            and up[index - 1].rank == up[index].rank + 1
        ):
            length += 1
            index -= 1
        if length > best:
            best = length
    return best


def _visible_intervals(state: SpiderState) -> Tuple[_Interval, ...]:
    """Same-suit descending face-up components, bottom to top.

    ``low`` is the top card of the component and ``high`` is the bottom
    card, matching ``physical_units``. The card that contacts a receiver
    is ``high``.
    """

    found = []
    for column_index, column in enumerate(state.columns):
        up = column.face_up
        index = 0
        while index < len(up):
            end = index + 1
            while (
                end < len(up)
                and up[end].suit == up[index].suit
                and up[end - 1].rank == up[end].rank + 1
            ):
                end += 1
            high = int(up[index].rank)
            low = int(up[end - 1].rank)
            if low > high:
                low, high = high, low
            found.append(
                _Interval(
                    column=column_index,
                    suit=up[index].suit,
                    low=low,
                    high=high,
                    start=index,
                    end=end - 1,
                )
            )
            index = end
    return tuple(found)


def _join_id(interval: _Interval, used: set) -> str:
    base = f"join:{interval.suit}:{interval.high}:col{interval.column}"
    if base not in used:
        used.add(base)
        return base
    suffix = 2
    while f"{base}:{suffix}" in used:
        suffix += 1
    ident = f"{base}:{suffix}"
    used.add(ident)
    return ident


def _landing_column(landing: tuple) -> int:
    if landing[0] == "empty":
        return int(landing[1])
    return int(landing[0])


def _receiver_landings(
    state: SpiderState,
    *,
    column: int,
    contacting_rank: int,
    suit: Optional[str],
    allow_empty: bool,
) -> Tuple[tuple, ...]:
    """Current tops that can legally receive the contacting card.

    An empty column is a reveal landing. It is not a join landing.
    A landing that is not the current top is not attached.
    """

    landings = []
    for index, dest in enumerate(state.columns):
        if index == column:
            continue
        if dest.is_empty():
            if allow_empty:
                landings.append(("empty", index))
            continue
        top = dest.top()
        if top is None or int(top.rank) != int(contacting_rank) + 1:
            continue
        if suit is not None and top.suit != suit:
            continue
        landings.append((index, top.suit, int(top.rank)))
    return tuple(landings)


def _movable_k(state: SpiderState, interval: _Interval) -> Optional[int]:
    """Length of the interval when it is the column's top suffix.

    A covered interval is not a legal block. ``k`` is None in that case.
    """

    face_up = state.columns[interval.column].face_up
    if not face_up or interval.end != len(face_up) - 1:
        return None
    return interval.end - interval.start + 1


def _is_actionable(
    column: int,
    block_k: Optional[int],
    landings: Sequence[tuple],
    actions: set,
) -> bool:
    if block_k is None or not landings:
        return False
    for landing in landings:
        destination = _landing_column(landing)
        if (column, destination, block_k) in actions:
            return True
    return False


def _node_from_parts(
    *,
    obligation_id: str,
    kind: str,
    column: int,
    suit: str,
    low: int,
    high: int,
    landings: Sequence[tuple],
    actionable: bool,
    requires_all: Sequence[str],
    face_down_at_build: int,
) -> _OpenNode:
    landing_tuple = tuple(landings)
    return _OpenNode(
        obligation_id=obligation_id,
        kind=kind,
        column=column,
        suit=suit,
        low=low,
        high=high,
        landing_count=len(landing_tuple),
        actionable=actionable,
        requires_all=tuple(requires_all),
        requires_any=(landing_tuple,) if landing_tuple else (),
        landing=landing_tuple[0] if len(landing_tuple) == 1 else None,
        face_down_at_build=face_down_at_build,
    )


def _as_public(node: _OpenNode) -> ObligationNode:
    return ObligationNode(
        obligation_id=node.obligation_id,
        kind=node.kind,
        satisfied=False,
        requires_all=node.requires_all,
        requires_any=node.requires_any,
        landing=node.landing,
    )


def _analyze(state: SpiderState) -> Tuple[_OpenNode, ...]:
    """Full obligation graph for this state. Nothing is carried over."""

    intervals = _visible_intervals(state)
    by_column = {}
    for interval in intervals:
        by_column.setdefault(interval.column, []).append(interval)
    actions = {tuple(action) for action in tableau_actions(state)}
    used_ids: set = set()
    join_ids = {}
    for interval in intervals:
        join_ids[id(interval)] = _join_id(interval, used_ids)

    nodes = []
    for column_index, column in enumerate(state.columns):
        column_intervals = by_column.get(column_index, [])
        if column.face_down and column_intervals:
            subject = column_intervals[0]
            above = [
                join_ids[id(other)]
                for other in column_intervals
                if other.start > subject.end
            ]
            landings = _receiver_landings(
                state,
                column=column_index,
                contacting_rank=subject.high,
                suit=None,
                allow_empty=True,
            )
            block_k = _movable_k(state, subject)
            nodes.append(
                _node_from_parts(
                    obligation_id=f"reveal:col{column_index}:depth0",
                    kind="REVEAL",
                    column=column_index,
                    suit=subject.suit,
                    low=subject.low,
                    high=subject.high,
                    landings=landings,
                    actionable=_is_actionable(
                        column_index, block_k, landings, actions
                    ),
                    requires_all=(*above, join_ids[id(subject)]),
                    face_down_at_build=len(column.face_down),
                )
            )
        for interval in column_intervals:
            above = [
                join_ids[id(other)]
                for other in column_intervals
                if other.start > interval.end
            ]
            landings = _receiver_landings(
                state,
                column=column_index,
                contacting_rank=interval.high,
                suit=interval.suit,
                allow_empty=False,
            )
            block_k = _movable_k(state, interval)
            nodes.append(
                _node_from_parts(
                    obligation_id=join_ids[id(interval)],
                    kind="JOIN",
                    column=column_index,
                    suit=interval.suit,
                    low=interval.low,
                    high=interval.high,
                    landings=landings,
                    actionable=_is_actionable(
                        column_index, block_k, landings, actions
                    ),
                    requires_all=tuple(above),
                    face_down_at_build=0,
                )
            )

    if stock_rows(state) > 0:
        incoming = next_stock_row(state)
        epoch = stock_rows(state)
        if incoming is not None:
            for column_index, card in enumerate(incoming):
                column = state.columns[column_index]
                landings = []
                if column.is_empty():
                    landings.append(("empty", column_index))
                else:
                    top = column.top()
                    if top is not None and int(top.rank) == int(card.rank) + 1:
                        landings.append((column_index, top.suit, int(top.rank)))
                nodes.append(
                    _node_from_parts(
                        obligation_id=(
                            f"receive:e{epoch}:col{column_index}:"
                            f"{card.suit}:{int(card.rank)}"
                        ),
                        kind="RECEIVE",
                        column=column_index,
                        suit=card.suit,
                        low=int(card.rank),
                        high=int(card.rank),
                        landings=tuple(landings),
                        actionable=False,
                        requires_all=(),
                        face_down_at_build=0,
                    )
                )
    return tuple(nodes)


def rebuild_obligations(state: SpiderState) -> Tuple[ObligationNode, ...]:
    """Regenerate every open obligation from ``state``.

    The result is a new tuple. A reveal or a deal is honoured by calling
    this again, not by patching the previous tuple.
    """

    return tuple(_as_public(node) for node in _analyze(state))


def _reveal_done(node: _OpenNode, final: SpiderState) -> bool:
    if node.kind != "REVEAL":
        return False
    return len(final.columns[node.column].face_down) < node.face_down_at_build


class _Track:
    """Face-up index span of one source JOIN, followed along a replay."""

    __slots__ = ("column", "start", "end", "cards", "status")

    def __init__(self, column: int, start: int, end: int, cards: tuple, status: str):
        self.column = column
        self.start = start
        self.end = end
        self.cards = cards
        self.status = status


def _span_cards(state: SpiderState, column: int, start: int, end: int) -> tuple:
    face_up = state.columns[column].face_up
    return tuple((int(card.rank), card.suit) for card in face_up[start:end + 1])


def _lose_all(tracks: dict) -> None:
    for track in tracks.values():
        track.status = "unresolved"


def _join_nodes(nodes: Sequence[_OpenNode]) -> Tuple[_OpenNode, ...]:
    return tuple(node for node in nodes if node.kind == "JOIN")


def _initial_tracks(state: SpiderState) -> dict:
    """Pair each JOIN with the interval that produced it. No suit search."""

    intervals = _visible_intervals(state)
    joins = _join_nodes(_analyze(state))
    tracks = {}
    matched = len(intervals) == len(joins)
    if matched:
        for interval, node in zip(intervals, joins):
            if (
                interval.column != node.column
                or interval.suit != node.suit
                or interval.low != node.low
                or interval.high != node.high
            ):
                matched = False
                break
    if not matched:
        for node in joins:
            tracks[node.obligation_id] = _Track(0, 0, -1, (), "unresolved")
        return tracks
    for interval, node in zip(intervals, joins):
        tracks[node.obligation_id] = _Track(
            column=interval.column,
            start=interval.start,
            end=interval.end,
            cards=_span_cards(state, interval.column, interval.start, interval.end),
            status="intact",
        )
    return tracks


def _drop_removed_top(tracks: dict, column: int, length_before: int) -> None:
    """The engine removed one same-suit top sequence. Survivors stay put."""

    if length_before < 13:
        for track in tracks.values():
            if track.status == "intact" and track.column == column:
                track.status = "unresolved"
        return
    cut = length_before - 13
    for track in tracks.values():
        if track.status != "intact" or track.column != column:
            continue
        if track.end < cut:
            continue
        track.status = "unresolved"


def _drop_inconsistent(tracks: dict, state: SpiderState) -> None:
    for track in tracks.values():
        if track.status != "intact":
            continue
        face_up = state.columns[track.column].face_up
        if track.start < 0 or track.end < track.start or track.end >= len(face_up):
            track.status = "unresolved"
            continue
        if _span_cards(state, track.column, track.start, track.end) != track.cards:
            track.status = "unresolved"


def _follow_move(tracks: dict, pre_len: Sequence[int], action: tuple, state: SpiderState) -> None:
    src, dst, count = action
    moved = state.last_move
    if (
        not isinstance(moved, tuple)
        or len(moved) < 5
        or int(moved[0]) != int(src)
        or int(moved[1]) != int(dst)
        or int(moved[2]) != int(count)
    ):
        _lose_all(tracks)
        return
    cut = int(pre_len[src]) - int(count)
    for track in tracks.values():
        if track.status != "intact" or track.column != src:
            continue
        if track.end < cut:
            continue
        if track.start >= cut:
            shift = track.start - cut
            track.column = int(dst)
            track.start = int(pre_len[dst]) + shift
            track.end = int(pre_len[dst]) + (track.end - cut)
            continue
        track.status = "unresolved"
    if moved[4]:
        _drop_removed_top(tracks, int(dst), int(pre_len[dst]) + int(count))


def _follow_deal(
    tracks: dict,
    pre_len: Sequence[int],
    pre_down: Sequence[int],
    state: SpiderState,
) -> None:
    for column in range(len(state.columns)):
        before = int(pre_len[column])
        after = len(state.columns[column].face_up)
        if after == before + 1:
            continue
        removed_len = before + 1 - 13
        flipped = removed_len == 0 and after == 1 and int(pre_down[column]) > 0
        emptied = removed_len == 0 and after == 0 and int(pre_down[column]) == 0
        if removed_len >= 0 and (after == removed_len or flipped or emptied):
            _drop_removed_top(tracks, column, before + 1)
            continue
        for track in tracks.values():
            if track.status == "intact" and track.column == column:
                track.status = "unresolved"


def _follow_joins(source: SpiderState, actions: Sequence) -> Tuple[SpiderState, dict]:
    """Replay ``actions`` and move each intact JOIN span with the cards.

    A split, a foundation removal, or a span whose cards no longer sit at
    the path index is ``unresolved``. Suit and rank are not used to find
    another copy.
    """

    state = source.clone()
    tracks = _initial_tracks(state)
    for action in actions:
        normalized = ("deal",) if is_deal(action) else tuple(int(part) for part in action)
        pre_len = [len(column.face_up) for column in state.columns]
        pre_down = [len(column.face_down) for column in state.columns]
        try:
            legal = all_legal_actions(state) if is_deal(normalized) else tableau_actions(state)
            if normalized not in legal:
                _lose_all(tracks)
                break
            apply_action(state, normalized)
        except (ValueError, TypeError, OptionContractError):
            _lose_all(tracks)
            break
        if is_deal(normalized):
            _follow_deal(tracks, pre_len, pre_down, state)
        else:
            _follow_move(tracks, pre_len, normalized, state)
        _drop_inconsistent(tracks, state)
    return state, tracks


def _joins_by_span(state: SpiderState, nodes: Sequence[_OpenNode]) -> dict:
    intervals = _visible_intervals(state)
    joins = _join_nodes(nodes)
    if len(intervals) != len(joins):
        return {}
    paired = {}
    for interval, node in zip(intervals, joins):
        if (
            interval.column != node.column
            or interval.suit != node.suit
            or interval.low != node.low
            or interval.high != node.high
        ):
            return {}
        paired[(interval.column, interval.start, interval.end)] = node
    return paired


def _outstanding_ids(nodes: Sequence[_OpenNode]) -> Tuple[str, ...]:
    return tuple(sorted(node.obligation_id for node in nodes if node.kind in _TACTICAL))


def _dependency_report(source: SpiderState, final: SpiderState, actions: Sequence):
    """Proven breaks, new enables, and unresolved source ids.

    An intact component that changed column is not a break while its
    replayed span still has a legal receiver. A missing column id is not
    evidence. A split, a merge into a longer span, a foundation removal,
    or an unfollowed span is unresolved: no break and no enablement.
    """

    replayed, tracks = _follow_joins(source, actions)
    source_nodes = _analyze(source)
    final_nodes = _analyze(final)
    outstanding = _outstanding_ids(final_nodes)
    if pack_state(replayed).hex() != pack_state(final).hex():
        unresolved = _outstanding_ids(source_nodes)
        return (), (), outstanding, 0, unresolved
    spans = _joins_by_span(final, final_nodes)
    broken = []
    enabled = []
    unresolved = []
    lost_receivers = 0
    for node in source_nodes:
        if node.kind not in _TACTICAL:
            continue
        if node.kind == "REVEAL":
            if _reveal_done(node, final):
                continue
            final_node = next(
                (item for item in final_nodes if item.obligation_id == node.obligation_id),
                None,
            )
            if final_node is None:
                unresolved.append(node.obligation_id)
                continue
            if node.landing_count > 0 and final_node.landing_count == 0:
                broken.append(node.obligation_id)
                lost_receivers += 1
                continue
            if (not node.actionable) and final_node.actionable:
                enabled.append(node.obligation_id)
            continue
        track = tracks.get(node.obligation_id)
        if track is None or track.status != "intact":
            unresolved.append(node.obligation_id)
            continue
        physical = spans.get((track.column, track.start, track.end))
        if physical is None:
            unresolved.append(node.obligation_id)
            continue
        if node.landing_count > 0 and physical.landing_count == 0:
            broken.append(node.obligation_id)
            lost_receivers += 1
            continue
        if (
            node.obligation_id == physical.obligation_id
            and (not node.actionable)
            and physical.actionable
        ):
            enabled.append(node.obligation_id)
    broken_ids = tuple(sorted(broken))
    return (
        broken_ids,
        tuple(sorted(enabled)),
        outstanding,
        lost_receivers,
        tuple(sorted(unresolved)),
    )


def _ranking_penalty(
    broken: Sequence[str],
    lost_receivers: int,
    before: SpiderState,
    after: SpiderState,
) -> int:
    empties_spent = max(
        0,
        len(empty_column_indices(before)) - len(empty_column_indices(after)),
    )
    return len(broken) + empties_spent + lost_receivers


def _effects(before: SpiderState, after: SpiderState, exposed: int) -> EffectDelta:
    return EffectDelta(
        foundations=len(after.foundations) - len(before.foundations),
        face_down=face_down_count(after) - face_down_count(before),
        bonds=same_suit_bonds(after) - same_suit_bonds(before),
        mixed_joins=mixed_boundaries(after) - mixed_boundaries(before),
        empty_count=(
            len(empty_column_indices(after)) - len(empty_column_indices(before))
        ),
        top_run_by_suit=tuple(
            (suit, _top_run_length(before, suit), _top_run_length(after, suit))
            for suit in SUITS
        ),
        stock_rows=stock_rows(after) - stock_rows(before),
        exposed_cards=exposed,
    )


def _predicates_for_action(state: SpiderState, action) -> Tuple[StatePredicate, ...]:
    if is_deal(action):
        return (
            StatePredicate(
                "deal",
                ("stock", len(state.stock), "epoch", stock_rows(state)),
            ),
        )
    src, dst, count = action
    outer = state.columns[src].face_up[-count]
    facts = [
        StatePredicate(
            "moved_block",
            ("column", int(src), "suit", outer.suit, "rank", int(outer.rank)),
        )
    ]
    top = state.columns[dst].top()
    if top is None:
        facts.append(StatePredicate("landing_empty", ("column", int(dst))))
    else:
        facts.append(
            StatePredicate(
                "destination_top",
                ("column", int(dst), "suit", top.suit, "rank", int(top.rank)),
            )
        )
    return tuple(facts)


def _final_predicates(final: SpiderState, action) -> Tuple[StatePredicate, ...]:
    if is_deal(action):
        return (
            StatePredicate(
                "deal",
                ("stock", len(final.stock), "epoch", stock_rows(final)),
            ),
        )
    _src, dst, count = action
    # The contacting card is the deepest card of the moved block. On the
    # final state of a one-action option it still sits on the destination.
    top = final.columns[dst].top()
    if top is None or count > len(final.columns[dst].face_up):
        return ()
    outer = final.columns[dst].face_up[-count]
    facts = [
        StatePredicate(
            "moved_block",
            ("column", int(dst), "suit", outer.suit, "rank", int(outer.rank)),
        )
    ]
    if final.columns[dst].is_empty():
        facts.append(StatePredicate("landing_empty", ("column", int(dst))))
    else:
        facts.append(
            StatePredicate(
                "destination_top",
                ("column", int(dst), "suit", top.suit, "rank", int(top.rank)),
            )
        )
    return tuple(facts)


def _symmetry_hex(state: SpiderState) -> Optional[str]:
    if state.stock:
        return None
    return pack_whole_game_identity(state).hex()


def _replay(source: SpiderState, actions: Sequence) -> Tuple[SpiderState, int, int, tuple]:
    """Clone, require each primitive, and sum the engine cost.

    Raises ``OptionContractError`` when an action is absent from the legal
    generator or when ``apply_action`` disagrees with ``step_cost``.
    """

    state = source.clone()
    total = 0
    exposed = 0
    preconditions = []
    for action in actions:
        legal = all_legal_actions(state) if is_deal(action) else tableau_actions(state)
        if action not in legal and tuple(action) not in legal:
            raise OptionContractError(f"action is not legal: {action!r}")
        normalized = ("deal",) if is_deal(action) else tuple(action)
        preconditions.extend(_predicates_for_action(state, normalized))
        before_face_down = face_down_count(state)
        expected = int(step_cost(state, normalized))
        played = int(apply_action(state, normalized))
        if played != expected:
            raise OptionContractError(
                f"replay cost {played} disagrees with step_cost {expected}"
            )
        total += played
        after_face_down = face_down_count(state)
        if after_face_down < before_face_down:
            exposed += before_face_down - after_face_down
    return state, total, exposed, tuple(preconditions)


def _replay_ok(source: SpiderState, actions: Sequence, target_pack: str, cost: int) -> bool:
    state = source.clone()
    total = 0
    for action in actions:
        normalized = ("deal",) if is_deal(action) else tuple(action)
        total += int(apply_action(state, normalized))
    return pack_state(state).hex() == target_pack and total == cost


def build_option(
    source: SpiderState,
    actions: Sequence,
    *,
    source_g: int,
    structural_name: str,
    obligations: Sequence[ObligationNode],
    provenance: str = "synthetic-fixture",
    option_id: Optional[str] = None,
) -> TacticalOption:
    """Replay ``actions`` and derive cost, predicates, and dependency fields.

    ``obligations`` is the caller's graph. Enables, blocks, and the penalty
    are rebuilt from the source and the replayed target, so a stale caller
    graph cannot invent an enablement edge.
    """

    if obligations is not None:
        tuple(obligations)
    normalized = tuple(("deal",) if is_deal(action) else tuple(int(part) for part in action) for action in actions)
    final, cost, exposed, preconditions = _replay(source, normalized)
    source_g = int(source_g)
    target_g = source_g + cost
    # Admissible remainder only. The dependency penalty is not added here.
    h_target = int(admissible_remaining(final))
    f_target = target_g + h_target
    broken, enabled, outstanding, lost_receivers, unresolved = _dependency_report(
        source, final, normalized
    )
    if any(is_deal(action) for action in normalized):
        workspace = WorkspaceAudit(
            empty_at_start=len(empty_column_indices(source)),
            empty_at_end=len(empty_column_indices(final)),
            max_empty=max(
                len(empty_column_indices(source)),
                len(empty_column_indices(final)),
            ),
            two_spaces_available=(
                len(empty_column_indices(source)) >= 2
                or len(empty_column_indices(final)) >= 2
            ),
            temporary_spaces=0,
            zero_cost_transfers=(),
            spaces_spent_at=(),
            spaces_recovered_at=(),
            relocated_holding_two=(),
        )
    else:
        workspace = audit_workspace(source, normalized)
    penalty = _ranking_penalty(broken, lost_receivers, source, final)
    postconditions = []
    for action in normalized:
        postconditions.extend(_final_predicates(final, action))
    for obligation_id in enabled:
        postconditions.append(StatePredicate("actionable", (obligation_id,)))
    target_pack = pack_state(final).hex()
    return TacticalOption(
        option_id=structural_name if option_id is None else option_id,
        structural_name=structural_name,
        source_pack=pack_state(source).hex(),
        source_symmetry=_symmetry_hex(source),
        source_g=source_g,
        actions=normalized,
        cost=cost,
        target_pack=target_pack,
        target_g=target_g,
        preconditions=preconditions,
        postconditions=tuple(postconditions),
        effects=_effects(source, final, exposed),
        workspace=workspace,
        broken_dependencies=broken,
        outstanding_obligations=outstanding,
        enables=enabled,
        blocks=broken,
        h_target=h_target,
        f_target=f_target,
        target_bonds=int(same_suit_bonds(final)),
        finishability_proof=False,
        dependency_penalty=penalty,
        replay_ok=_replay_ok(source, normalized, target_pack, cost),
        provenance=provenance,
        independent_cold_complete=False,
        source_g_provenance="unestablished",
        unresolved_dependencies=unresolved,
    )


def dependency_penalty_of(
    before: SpiderState,
    after: SpiderState,
    option: TacticalOption,
) -> int:
    """Ranking sum: broken ids, unrecovered empties, and lost receivers.

    The result is not an admissible bound.
    """

    broken, _enabled, _outstanding, lost_receivers, _unresolved = _dependency_report(
        before, after, option.actions
    )
    return _ranking_penalty(broken, lost_receivers, before, after)


def diversity_signature(state: SpiderState) -> tuple:
    """Structural signature. No coefficient is fitted on a published deal."""

    epoch = len(state.stock) // 10
    depth_histogram = tuple(sorted(len(column.face_down) for column in state.columns))
    foundation_suits = tuple(
        sorted(seq[0].suit for seq in state.foundations if seq)
    )
    two_spaces = sum(column.is_empty() for column in state.columns) >= 2
    buried = []
    accessible = []
    for suit in SUITS:
        buried_n = sum(
            1
            for column in state.columns
            for card in column.face_down
            if card.suit == suit
        )
        visible = 0
        for column in state.columns:
            up = column.face_up
            index = 0
            while index < len(up):
                end = index + 1
                while (
                    end < len(up)
                    and up[end].suit == up[index].suit
                    and up[end - 1].rank == up[end].rank + 1
                ):
                    end += 1
                if up[index].suit == suit:
                    visible += 1
                index = end
        buried.append(buried_n)
        accessible.append(visible)
    return (
        epoch,
        depth_histogram,
        foundation_suits,
        two_spaces,
        tuple(buried),
        tuple(accessible),
    )


def _signature_distance(left: tuple, right: tuple) -> int:
    distance = 0 if left[0] == right[0] else 1
    distance += sum(abs(a - b) for a, b in zip(left[1], right[1]))
    distance += len(set(left[2]) ^ set(right[2]))
    if left[3] != right[3]:
        distance += 1
    distance += sum(abs(a - b) for a, b in zip(left[4], right[4]))
    distance += sum(abs(a - b) for a, b in zip(left[5], right[5]))
    return distance


def outcome_signature(option: TacticalOption) -> tuple:
    """Diversity signature of the replayed target, not of the source.

    Reported beside the source signature. It is not a portfolio weight and
    it is not a proof term.
    """

    return diversity_signature(unpack_state(bytes.fromhex(option.target_pack)))


def _obligation_key(nodes: Sequence[ObligationNode]) -> tuple:
    """Full graph identity. Obligation id strings alone are not enough."""

    return tuple(
        sorted(
            (
                node.obligation_id,
                node.kind,
                bool(node.satisfied),
                tuple(node.requires_all),
                tuple(tuple(group) for group in node.requires_any),
                node.landing,
            )
            for node in nodes
        )
    )


def obligations_match_state(
    state: SpiderState,
    obligations: Sequence[ObligationNode],
) -> bool:
    """True when ``obligations`` is the graph rebuilt from this physical state."""

    return _obligation_key(rebuild_obligations(state)) == _obligation_key(obligations)


def _receiver_group_size(node: ObligationNode) -> int:
    if not node.requires_any:
        return 0
    return len(node.requires_any[0])


def _critical_ids(obligations: Sequence[ObligationNode]) -> Tuple[str, ...]:
    """Size-1 JOIN and REVEAL receivers. RECEIVE is not protected."""

    return tuple(
        node.obligation_id
        for node in obligations
        if node.kind in _TACTICAL
        and not node.satisfied
        and _receiver_group_size(node) == 1
    )


def _unsupported_receive_ids(obligations: Sequence[ObligationNode]) -> Tuple[str, ...]:
    return tuple(
        sorted(
            node.obligation_id
            for node in obligations
            if node.kind == "RECEIVE"
            and not node.satisfied
            and _receiver_group_size(node) == 1
        )
    )


def _option_replays(option: TacticalOption) -> bool:
    """Recompute selector fields from the replayed source and target.

    The incremental identity ``target_g == source_g + cost`` is checked.
    ``source_g`` itself is not an opening cost. A stored provenance other
    than ``unestablished`` is rejected: an option cannot certify its own
    absolute ``g``. The dependency penalty is checked and is not added to
    ``h`` or ``f``.
    """

    if not option.replay_ok or option.finishability_proof:
        return False
    if option.source_g_provenance != "unestablished":
        return False
    try:
        origin = unpack_state(bytes.fromhex(option.source_pack))
    except (TypeError, ValueError):
        return False
    state = origin.clone()
    total = 0
    for action in option.actions:
        legal = all_legal_actions(state) if is_deal(action) else tableau_actions(state)
        if action not in legal:
            return False
        total += int(apply_action(state, action))
    if pack_state(state).hex() != option.target_pack:
        return False
    if int(option.cost) != total:
        return False
    if int(option.target_g) != int(option.source_g) + total:
        return False
    height = int(admissible_remaining(state))
    if int(option.h_target) != height:
        return False
    if int(option.f_target) != int(option.target_g) + height:
        return False
    if int(option.target_bonds) != int(same_suit_bonds(state)):
        return False
    broken, enabled, outstanding, lost_receivers, unresolved = _dependency_report(
        origin, state, option.actions
    )
    if tuple(option.broken_dependencies) != broken:
        return False
    if tuple(option.blocks) != broken:
        return False
    if tuple(option.enables) != enabled:
        return False
    if tuple(option.outstanding_obligations) != outstanding:
        return False
    if tuple(option.unresolved_dependencies) != unresolved:
        return False
    if int(option.dependency_penalty) != _ranking_penalty(broken, lost_receivers, origin, state):
        return False
    return True


def _normalize_action(action) -> tuple:
    if is_deal(action):
        return ("deal",)
    return tuple(int(part) for part in action)


def verify_ancestor_claim(claim: AncestorClaim) -> bool:
    """Replay ``continuation`` from the checkpoint. Packs must match.

    Stock length is not consulted. A different source pack reached from the
    same checkpoint is the same ancestor. The summed corrected cost is not
    read. A verified claim is checkpoint-relative until a source-cost claim
    ties that checkpoint to a ``g=0`` opening.
    """

    try:
        state = unpack_state(bytes.fromhex(claim.checkpoint_pack))
    except (TypeError, ValueError):
        return False
    for action in claim.continuation:
        normalized = _normalize_action(action)
        legal = all_legal_actions(state) if is_deal(normalized) else tableau_actions(state)
        if normalized not in legal:
            return False
        apply_action(state, normalized)
    return pack_state(state).hex() == claim.source_pack


def verify_source_cost_claim(claim: SourceCostClaim) -> bool:
    """Replay ``continuation`` from a trusted ``g=0`` opening.

    The summed corrected cost must equal ``source_g``, and the resulting
    pack must be ``source_pack``. An empty continuation therefore requires
    ``source_g == 0``. A failed claim does not reject a relatively
    consistent option.
    """

    try:
        state = unpack_state(bytes.fromhex(claim.opening_pack))
    except (TypeError, ValueError):
        return False
    total = 0
    for action in claim.continuation:
        normalized = _normalize_action(action)
        legal = all_legal_actions(state) if is_deal(normalized) else tableau_actions(state)
        if normalized not in legal:
            return False
        total += int(apply_action(state, normalized))
    if pack_state(state).hex() != claim.source_pack:
        return False
    return int(claim.source_g) == total


def _bound_source_costs(
    claims: Sequence[SourceCostClaim],
    survivors: Sequence[TacticalOption],
) -> Tuple[set, int]:
    """Return ``(pack, source_g)`` pairs a claim actually supports."""

    supported = set()
    rejected = 0
    admitted = {
        (option.source_pack, int(option.source_g))
        for option in survivors
    }
    for claim in claims:
        if not verify_source_cost_claim(claim):
            rejected += 1
            continue
        key = (claim.source_pack, int(claim.source_g))
        if key in admitted:
            supported.add(key)
        else:
            rejected += 1
    return supported, rejected


def _rank_key(option: TacticalOption) -> tuple:
    return (
        option.cost,
        option.dependency_penalty,
        -option.target_bonds,
        option.source_pack,
        option.option_id,
    )


def _signature_of(option: TacticalOption) -> tuple:
    return diversity_signature(unpack_state(bytes.fromhex(option.source_pack)))


def _pick_farthest(pool: Sequence[TacticalOption], chosen: Sequence[TacticalOption]) -> TacticalOption:
    signatures = {id(option): _signature_of(option) for option in pool}
    chosen_signatures = [_signature_of(option) for option in chosen]

    def sort_key(option: TacticalOption):
        if not chosen_signatures:
            distance = 0
        else:
            own = signatures[id(option)]
            distance = min(
                _signature_distance(own, other) for other in chosen_signatures
            )
        return (-distance, _rank_key(option))

    return min(pool, key=sort_key)


def _sources_match_obligations(
    options: Sequence[TacticalOption],
    obligations: Sequence[ObligationNode],
) -> bool:
    packs = {option.source_pack for option in options}
    for pack in packs:
        state = unpack_state(bytes.fromhex(pack))
        if not obligations_match_state(state, obligations):
            return False
    return True


def _verified_checkpoints(
    claims: Sequence[AncestorClaim],
    survivors: Sequence[TacticalOption],
) -> Tuple[tuple, int]:
    source_packs = {option.source_pack for option in survivors}
    verified = []
    rejected = 0
    for claim in claims:
        if claim.source_pack not in source_packs:
            rejected += 1
            continue
        if verify_ancestor_claim(claim):
            verified.append(claim.checkpoint_pack)
        else:
            rejected += 1
    return tuple(sorted(set(verified))), rejected


def select_dependency_portfolio(
    options: Sequence[TacticalOption],
    obligations: Sequence[ObligationNode],
    *,
    limit: int = 8,
    ancestor_claims: Optional[Sequence[AncestorClaim]] = None,
    source_cost_claims: Optional[Sequence[SourceCostClaim]] = None,
) -> PortfolioPick:
    """Reserve a unique JOIN or REVEAL receiver, then fill by source signature.

    The cap is not a proof that an omitted option cannot finish. A breaker
    stays available to the generator. Nothing here edits ``tableau_actions``.

    Critical priority is applied only when ``obligations`` rebuilds to the
    same graph as every admitted source. A graph from another physical state
    is refused. RECEIVE nodes are reported and are not protected.

    ``diverse_ancestor_available`` is true only when admitted options carry
    two or more replay-verified checkpoint packs. Distinct source packs and
    ``len(stock) % 10 == 0`` are not ancestors. Outcome signatures are
    reported and do not change the rank order.

    ``source_g`` is not a rank key. ``absolute_g_used_for_proof`` stays
    false. ``source_g_provenance`` is ``opening_verified`` only when every
    admitted option has a source-cost claim whose corrected cost matches
    ``source_g``. Verified ancestor packs alone are ``checkpoint_relative``.
    """

    survivors = [option for option in options if _option_replays(option)]
    obligations_ok = bool(survivors) and _sources_match_obligations(survivors, obligations)
    receive_nodes = [node for node in obligations if node.kind == "RECEIVE"]
    unsupported_receive = _unsupported_receive_ids(obligations) if obligations_ok else ()
    if obligations_ok:
        critical = _critical_ids(obligations)
        obligations_status = "matched"
    else:
        critical = ()
        obligations_status = "refused" if survivors else "not_applied"
    breakers = []
    preservers = []
    neutrals = []
    if critical:
        critical_set = set(critical)
        for option in survivors:
            blocked = set(option.broken_dependencies) | set(option.blocks)
            if critical_set & blocked:
                breakers.append(option)
            elif critical_set & set(option.enables):
                preservers.append(option)
            else:
                neutrals.append(option)
    if critical and preservers:
        tiers = (preservers, neutrals, breakers)
    else:
        tiers = (survivors,)
        if not critical:
            breakers = []
    chosen = []
    limit = int(limit)
    for tier in tiers:
        pool = [option for option in tier if option not in chosen]
        while pool and len(chosen) < limit:
            pick = _pick_farthest(pool, chosen)
            chosen.append(pick)
            pool = [option for option in pool if option is not pick]
        if len(chosen) >= limit:
            break
    omitted = len(chosen) < len(survivors)
    verified_packs, rejected_claims = _verified_checkpoints(
        () if ancestor_claims is None else tuple(ancestor_claims),
        survivors,
    )
    if len(verified_packs) >= 2:
        ancestor_status = "diverse_verified"
    elif len(verified_packs) == 1:
        ancestor_status = "one_verified"
    else:
        ancestor_status = "not_established"
    supported_costs, rejected_costs = _bound_source_costs(
        () if source_cost_claims is None else tuple(source_cost_claims),
        survivors,
    )
    opening_verified = bool(survivors) and all(
        (option.source_pack, int(option.source_g)) in supported_costs
        for option in survivors
    )
    if opening_verified:
        source_g_provenance = "opening_verified"
    elif verified_packs:
        source_g_provenance = "checkpoint_relative"
    else:
        source_g_provenance = "unestablished"
    return PortfolioPick(
        chosen=tuple(chosen),
        diverse_ancestor_available=len(verified_packs) >= 2,
        omitted_not_proved_impossible=omitted,
        breakers_not_proof_pruned=tuple(option.option_id for option in breakers),
        ancestor_status=ancestor_status,
        verified_checkpoint_packs=verified_packs,
        rejected_ancestor_claims=rejected_claims,
        obligations_status=obligations_status,
        receive_protection="unsupported" if receive_nodes else "not_present",
        protected_ids=critical,
        unsupported_receive_ids=unsupported_receive,
        source_signatures=tuple(_signature_of(option) for option in chosen),
        outcome_signatures=tuple(outcome_signature(option) for option in chosen),
        source_g_provenance=source_g_provenance,
        absolute_g_used_for_proof=False,
        rejected_source_cost_claims=rejected_costs,
    )


def prefer_option_actions(state: SpiderState, actions: Sequence, option: TacticalOption) -> list:
    """Return a permutation that leads with the next still-legal option action.

    An option action that is not already in ``actions`` is not appended.
    If none of the option's actions is present, the generated order is kept.
    """

    generated = [tuple(action) if not is_deal(action) else ("deal",) for action in actions]
    present = set(generated)
    preferred = None
    for action in option.actions:
        normalized = ("deal",) if is_deal(action) else tuple(action)
        if normalized not in present:
            continue
        if is_deal(normalized):
            if not state.can_deal():
                continue
        else:
            src, dst, count = normalized
            if not state.can_move(src, dst, count):
                continue
        preferred = normalized
        break
    if preferred is None:
        return generated
    rest = [action for action in generated if action != preferred]
    return [preferred, *rest]


def kernel_lower_bound(state: SpiderState, g: int) -> int:
    """Return ``admissible_remaining``. ``g`` is accepted and not read.

    ``dependency_penalty`` is not an argument and is not added to the result.
    """

    del g
    return int(admissible_remaining(state))
