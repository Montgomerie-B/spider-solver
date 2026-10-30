"""Dependency-aware tactical options.

Research-only proposals. An option is a replay of existing primitives.
It is not a substitute move, not a proof, and not a second search.

``dependency_penalty`` is a portfolio sort key. It is not added to
``h_target`` and it is not an argument of ``kernel_lower_bound``.
The Human Strategy Controller does not import this module.
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


@dataclass(frozen=True)
class ObligationNode:
    obligation_id: str
    kind: str
    satisfied: bool
    requires_all: tuple
    requires_any: tuple
    landing: Optional[tuple]


@dataclass(frozen=True)
class PortfolioPick:
    chosen: tuple
    diverse_ancestor_available: bool
    omitted_not_proved_impossible: bool
    breakers_not_proof_pruned: tuple


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


def _merged(node: _OpenNode, final_nodes: Sequence[_OpenNode]) -> bool:
    """True when this join's rank span now sits inside a longer component."""

    if node.kind != "JOIN":
        return False
    still_here = any(
        other.kind == "JOIN"
        and other.column == node.column
        and other.suit == node.suit
        and other.low == node.low
        and other.high == node.high
        for other in final_nodes
    )
    if still_here:
        return False
    span = node.high - node.low
    return any(
        other.kind == "JOIN"
        and other.suit == node.suit
        and other.low <= node.low
        and other.high >= node.high
        and (other.high - other.low) > span
        for other in final_nodes
    )


def _reveal_done(node: _OpenNode, final: SpiderState) -> bool:
    if node.kind != "REVEAL":
        return False
    return len(final.columns[node.column].face_down) < node.face_down_at_build


def _dependency_report(source: SpiderState, final: SpiderState):
    source_nodes = _analyze(source)
    final_nodes = _analyze(final)
    final_by_id = {node.obligation_id: node for node in final_nodes}
    broken = []
    enabled = []
    lost_receivers = 0
    for node in source_nodes:
        if node.kind not in _TACTICAL:
            continue
        if _merged(node, final_nodes) or _reveal_done(node, final):
            continue
        final_node = final_by_id.get(node.obligation_id)
        final_landings = 0 if final_node is None else final_node.landing_count
        final_actionable = False if final_node is None else final_node.actionable
        lost = node.landing_count > 0 and final_landings == 0
        if lost:
            broken.append(node.obligation_id)
            lost_receivers += 1
            continue
        if (not node.actionable) and final_actionable:
            enabled.append(node.obligation_id)
    broken_ids = tuple(sorted(broken))
    outstanding = tuple(
        sorted(
            node.obligation_id
            for node in final_nodes
            if node.kind in _TACTICAL
        )
    )
    return broken_ids, tuple(sorted(enabled)), outstanding, lost_receivers


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
    broken, enabled, outstanding, lost_receivers = _dependency_report(source, final)
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
    empties_spent = max(0, workspace.empty_at_start - workspace.empty_at_end)
    penalty = len(broken) + empties_spent + lost_receivers
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
    )


def dependency_penalty_of(
    before: SpiderState,
    after: SpiderState,
    option: TacticalOption,
) -> int:
    """Ranking sum: broken ids, unrecovered empties, and lost receivers.

    The result is not an admissible bound.
    """

    broken, _enabled, _outstanding, lost_receivers = _dependency_report(before, after)
    workspace = option.workspace
    empties_spent = max(0, workspace.empty_at_start - workspace.empty_at_end)
    return len(broken) + empties_spent + lost_receivers


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


def _receiver_group_size(node: ObligationNode) -> int:
    if not node.requires_any:
        return 0
    return len(node.requires_any[0])


def _critical_ids(obligations: Sequence[ObligationNode]) -> Tuple[str, ...]:
    return tuple(
        node.obligation_id
        for node in obligations
        if not node.satisfied and _receiver_group_size(node) == 1
    )


def _option_replays(option: TacticalOption) -> bool:
    if not option.replay_ok or option.finishability_proof:
        return False
    state = unpack_state(bytes.fromhex(option.source_pack))
    for action in option.actions:
        legal = all_legal_actions(state) if is_deal(action) else tableau_actions(state)
        if action not in legal:
            return False
        apply_action(state, action)
    return pack_state(state).hex() == option.target_pack


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


def _on_stock_boundary(option: TacticalOption) -> bool:
    state = unpack_state(bytes.fromhex(option.source_pack))
    return len(state.stock) % 10 == 0


def select_dependency_portfolio(
    options: Sequence[TacticalOption],
    obligations: Sequence[ObligationNode],
    *,
    limit: int = 8,
) -> PortfolioPick:
    """Reserve a unique receiver, then fill by signature distance.

    The cap is not a proof that an omitted option cannot finish. A breaker
    stays available to the generator. Nothing here edits ``tableau_actions``.
    """

    survivors = [option for option in options if _option_replays(option)]
    critical = _critical_ids(obligations)
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
    boundary_packs = {
        option.source_pack for option in survivors if _on_stock_boundary(option)
    }
    return PortfolioPick(
        chosen=tuple(chosen),
        diverse_ancestor_available=len(boundary_packs) >= 2,
        omitted_not_proved_impossible=omitted,
        breakers_not_proof_pruned=tuple(option.option_id for option in breakers),
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
