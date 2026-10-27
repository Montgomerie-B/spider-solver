"""Bridge one verified early fifth-deal tableau onto a later 172 checkpoint.

The search starts at the replayed early candidate, after the named
preparation and the fifth deal. It does not start at the canonical
post-SD5 state, and it does not raise that search's budgets.

After the stock is empty, a candidate may rejoin any later canonical
checkpoint when the foundations and stock agree and the tableau is a
whole-column permutation. The remaining reference actions are remapped
and replayed. An equal or higher corrected cost is not a saving. The
absolute ceiling is 171. Admissible pruning is strict: ``g + h > 171``
is rejected and equality stays eligible. ``incumbent.proof_prune`` is
not used, because that helper rejects equality.

Displacement orders a small set of later checkpoints. It does not prune.
Empty-column count is not a score. Every legal action is kept.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.human_strategy.anchored import Checkpoint, build_checkpoints, target_displacement
from spider.human_strategy.evaluation import admissible_remaining, same_suit_bonds
from spider.metrics import Action, format_action, replay_actions
from spider.packed_state import (
    column_permutation_mapping,
    pack_post_stock_symmetry_state,
    pack_state,
    pack_whole_game_identity,
    remap_tableau_action,
    unpack_state,
)
from spider.pre_sd5_preparation import assess_immediate_deal
from spider.research_actions import (
    all_legal_actions,
    apply_action,
    face_down_count,
    is_deal,
    step_cost,
)
from spider.search_kernel import KernelResult, SearchLimits, run_search


SCHEMA = "spider-stock-boundary-route-bridge-0.133"
CANONICAL_TOTAL = 172
CEILING = 171
CHECKPOINT_PREP = 140
POST_SD5 = 152
FIFTH_DEAL_INDEX = 151
EARLY_PREP: Tuple[Action, ...] = ((1, 4, 1), (2, 0, 2), (8, 1, 1), ("deal",))
EARLY_G = 142
EARLY_H = 24
EARLY_LANDINGS: Tuple[str, ...] = (
    "same_suit",
    "same_suit",
    "non_connecting",
    "non_connecting",
    "non_connecting",
    "same_suit",
    "non_connecting",
    "non_connecting",
    "same_suit",
    "non_connecting",
)
SUFFIX_LEN = 22
MAX_UNIQUE = 20_000
TIME_LIMIT_S = 45.0
RSS_ABORT_MB = 512.0
PROVENANCE = "incumbent-guided prefix + discovered bridge + reused/remapped verified suffix"

# Same-suit continuation and a reveal are the existing action preferences.
# Corrected step cost is first so a zero-cost transfer is cost accounting.
# A move onto an empty column is not ranked above any other action.
_ORDER_TIE = 10**9


class BridgeContractError(RuntimeError):
    """The named early route or the canonical suffix did not replay."""


@dataclass(frozen=True)
class ReferenceStop:
    """One canonical checkpoint that a stock-empty candidate may rejoin."""

    index: int
    g: int
    foundations: int
    suffix: Tuple[Action, ...]
    suffix_cost: int
    physical: bytes
    symmetry: Optional[bytes]
    state: SpiderState = field(compare=False, repr=False)


@dataclass
class ReferenceTable:
    stops: Tuple[ReferenceStop, ...]
    by_physical: Dict[bytes, Tuple[ReferenceStop, ...]]
    by_symmetry: Dict[bytes, Tuple[ReferenceStop, ...]]
    canonical_total: int = CANONICAL_TOTAL


@dataclass
class RemapReplay:
    ok: bool
    reason: str
    failure: str
    mapping: Optional[Tuple[int, ...]]
    actions: Tuple[Action, ...]
    cost: Optional[int]


@dataclass
class EarlyCandidate:
    state: SpiderState
    g: int
    h: int
    f: int
    face_down: int
    bonds: int
    foundations: int
    same_suit_landings: int
    landings: Tuple[str, ...]
    prep_costs: Tuple[int, ...]
    checkpoint_140_g: int
    checkpoint_140_stock: int
    checkpoint_140_empty: int
    fifth_deal_index: int
    post_sd5_index: int
    post_sd5_g: int
    post_sd5_h: int
    suffix_len: int
    suffix_cost: int
    symmetry: bytes
    already_on_reference: bool

    def public(self) -> dict:
        return {
            "g": self.g,
            "h": self.h,
            "f": self.f,
            "face_down": self.face_down,
            "bonds": self.bonds,
            "foundations": self.foundations,
            "same_suit_landings": self.same_suit_landings,
            "landings": list(self.landings),
            "prep_costs": list(self.prep_costs),
            "prep": [format_action(action) for action in EARLY_PREP],
            "checkpoint_140_g": self.checkpoint_140_g,
            "checkpoint_140_stock": self.checkpoint_140_stock,
            "checkpoint_140_empty": self.checkpoint_140_empty,
            "fifth_deal_index": self.fifth_deal_index,
            "post_sd5_index": self.post_sd5_index,
            "post_sd5_g": self.post_sd5_g,
            "post_sd5_h": self.post_sd5_h,
            "suffix_len": self.suffix_len,
            "suffix_cost": self.suffix_cost,
            "already_on_reference": self.already_on_reference,
        }


@dataclass
class BridgeSearch:
    accepted: bool
    kind: str
    stop_reason: str
    searched: bool
    g0: int
    ceiling: int
    g: Optional[int]
    reference_index: Optional[int]
    reference_g: Optional[int]
    projected_cost: Optional[int]
    mapping: Optional[Tuple[int, ...]]
    bridge: Tuple[Action, ...]
    remapped_suffix: Tuple[Action, ...]
    suffix_cost: Optional[int]
    replay_ok: bool
    reference_checkpoint_matches: int
    physical_matches: int
    symmetry_only_matches: int
    rejected_non_improving: int
    improving_attempts: int
    remap_failures: int
    replay_failures: int
    terminal_hits: int
    expanded: int
    unique: int
    generated: int
    duplicate_skips: int
    stale_skips: int
    ceiling_prunes: int
    lower_bound_prunes: int
    proof_prune_identities: int
    proof_prune_unretained: int
    lower_bound_calls: int
    zero_cost_actions: int
    min_f: Optional[int]
    min_h: Optional[int]
    max_h: Optional[int]
    max_foundations: int
    elapsed_s: float
    peak_rss_mb: Optional[float]
    affinity_s: float
    affinity_calls: int
    ordering_target_count: int
    ordering_targets: Tuple[int, ...]
    lane_exp: Tuple[Tuple[str, int], ...]
    expanded_by_g: Tuple[Tuple[int, int], ...]
    node_count: int
    inconclusive: bool
    negative_within_cap: bool

    def to_dict(self) -> dict:
        return {
            "accepted": self.accepted,
            "kind": self.kind,
            "stop_reason": self.stop_reason,
            "searched": self.searched,
            "g0": self.g0,
            "ceiling": self.ceiling,
            "g": self.g,
            "reference_index": self.reference_index,
            "reference_g": self.reference_g,
            "projected_cost": self.projected_cost,
            "mapping": None if self.mapping is None else list(self.mapping),
            "bridge": [format_action(action) for action in self.bridge],
            "remapped_suffix": [format_action(action) for action in self.remapped_suffix],
            "suffix_cost": self.suffix_cost,
            "replay_ok": self.replay_ok,
            "reference_checkpoint_matches": self.reference_checkpoint_matches,
            "physical_matches": self.physical_matches,
            "symmetry_only_matches": self.symmetry_only_matches,
            "rejected_non_improving": self.rejected_non_improving,
            "improving_attempts": self.improving_attempts,
            "remap_failures": self.remap_failures,
            "replay_failures": self.replay_failures,
            "terminal_hits": self.terminal_hits,
            "expanded": self.expanded,
            "unique": self.unique,
            "generated": self.generated,
            "duplicate_skips": self.duplicate_skips,
            "stale_skips": self.stale_skips,
            "ceiling_prunes": self.ceiling_prunes,
            "lower_bound_prunes": self.lower_bound_prunes,
            "proof_prune_identities": self.proof_prune_identities,
            "proof_prune_unretained": self.proof_prune_unretained,
            "lower_bound_calls": self.lower_bound_calls,
            "zero_cost_actions": self.zero_cost_actions,
            "min_f": self.min_f,
            "min_h": self.min_h,
            "max_h": self.max_h,
            "max_foundations": self.max_foundations,
            "elapsed_s": round(self.elapsed_s, 6),
            "peak_rss_mb": self.peak_rss_mb,
            "affinity_s": round(self.affinity_s, 6),
            "affinity_calls": self.affinity_calls,
            "ordering_target_count": self.ordering_target_count,
            "ordering_targets": list(self.ordering_targets),
            "lane_exp": list(map(list, self.lane_exp)),
            "expanded_by_g": list(map(list, self.expanded_by_g)),
            "node_count": self.node_count,
            "inconclusive": self.inconclusive,
            "negative_within_cap": self.negative_within_cap,
            "independent_cold_complete": False,
        }


@dataclass
class _Hit:
    reference_checkpoint_matches: int = 0
    physical_matches: int = 0
    symmetry_only_matches: int = 0
    rejected_non_improving: int = 0
    improving_attempts: int = 0
    remap_failures: int = 0
    replay_failures: int = 0
    accepted: bool = False
    kind: str = ""
    reference_index: Optional[int] = None
    reference_g: Optional[int] = None
    projected: Optional[int] = None
    mapping: Optional[Tuple[int, ...]] = None
    suffix: Tuple[Action, ...] = ()
    suffix_cost: Optional[int] = None
    pack: Optional[bytes] = None
    g: Optional[int] = None


def accept_cost(cost: int, ceiling: int = CEILING) -> bool:
    """A complete game is kept only at or below the absolute ceiling."""

    return int(cost) <= int(ceiling)


def projected_full_cost(
    g_candidate: int,
    g_ref: int,
    canonical_total: int = CANONICAL_TOTAL,
) -> Optional[int]:
    """Full-route cost of rejoining ``g_ref`` at ``g_candidate``.

    Equality and any higher candidate cost return None. They are not savings.
    """

    if int(g_candidate) >= int(g_ref):
        return None
    return int(canonical_total) - (int(g_ref) - int(g_candidate))


def bridge_action_order(state: SpiderState, actions: Sequence[Action]) -> List[Action]:
    """Sort every legal action. None are dropped.

    Lower is earlier: corrected cost, then a reveal, then a same-suit
    continuation. Destination emptiness is not a term.
    """

    def rank(item: Tuple[int, Action]) -> tuple:
        index, action = item
        cost = step_cost(state, action)
        reveal = 1
        same = 1
        if not is_deal(action):
            src, dst, k = action
            source = state.columns[src]
            destination = state.columns[dst]
            run = source.face_up[-k:] if k else []
            top = destination.top()
            if (
                top is not None
                and run
                and top.suit == run[0].suit
                and top.rank == run[0].rank + 1
            ):
                same = 0
            if len(source.face_up) == k and source.face_down:
                reveal = 0
        return (cost, reveal, same, index)

    ordered = [action for _index, action in sorted(enumerate(actions), key=rank)]
    if len(ordered) != len(actions):
        raise RuntimeError("bridge ordering dropped a legal action")
    return ordered


def reference_table(
    stops: Sequence[ReferenceStop],
    *,
    canonical_total: int = CANONICAL_TOTAL,
) -> ReferenceTable:
    by_physical: Dict[bytes, List[ReferenceStop]] = {}
    by_symmetry: Dict[bytes, List[ReferenceStop]] = {}
    ordered = tuple(sorted(stops, key=lambda stop: (stop.index, stop.g)))
    for stop in ordered:
        by_physical.setdefault(stop.physical, []).append(stop)
        if stop.symmetry is not None:
            by_symmetry.setdefault(stop.symmetry, []).append(stop)
    return ReferenceTable(
        stops=ordered,
        by_physical={key: tuple(value) for key, value in by_physical.items()},
        by_symmetry={key: tuple(value) for key, value in by_symmetry.items()},
        canonical_total=int(canonical_total),
    )


def make_reference_stop(
    state: SpiderState,
    *,
    index: int,
    g: int,
    suffix: Sequence[Action],
) -> ReferenceStop:
    """Replay ``suffix`` on a clone and keep the column keys of ``state``."""

    trial = state.clone()
    spent = 0
    actions: List[Action] = []
    for action in suffix:
        if is_deal(action):
            raise BridgeContractError(f"checkpoint {index} suffix still deals")
        spent += int(apply_action(trial, action))
        actions.append(action)
    symmetry = None if state.stock else pack_post_stock_symmetry_state(state)
    return ReferenceStop(
        index=int(index),
        g=int(g),
        foundations=len(state.foundations),
        suffix=tuple(actions),
        suffix_cost=int(spent),
        physical=pack_state(state),
        symmetry=symmetry,
        state=state.clone(),
    )


def build_reference_table(
    checkpoints: Sequence[Checkpoint],
    actions: Sequence[Action],
    *,
    start: int = POST_SD5,
    canonical_total: int = CANONICAL_TOTAL,
) -> ReferenceTable:
    """Every checkpoint from ``start`` through the solved end stays eligible."""

    stops: List[ReferenceStop] = []
    for checkpoint in checkpoints:
        if checkpoint.index < int(start):
            continue
        if checkpoint.index != len(stops) + int(start):
            raise BridgeContractError(
                f"checkpoint index {checkpoint.index} is not contiguous from {start}"
            )
        suffix = tuple(actions[checkpoint.index :])
        stop = make_reference_stop(
            checkpoint.state,
            index=checkpoint.index,
            g=checkpoint.g,
            suffix=suffix,
        )
        if stop.suffix_cost != int(canonical_total) - int(checkpoint.g):
            raise BridgeContractError(
                f"checkpoint {checkpoint.index} suffix costs {stop.suffix_cost}, "
                f"expected {int(canonical_total) - int(checkpoint.g)}"
            )
        trial = checkpoint.state.clone()
        replay_actions(trial, list(stop.suffix))
        if not trial.is_solved() or len(trial.foundations) != 8 or trial.stock:
            raise BridgeContractError(f"checkpoint {checkpoint.index} suffix does not solve")
        stops.append(stop)
    if not stops:
        raise BridgeContractError("no reference checkpoints")
    return reference_table(stops, canonical_total=canonical_total)


def select_ordering_targets(
    stops: Sequence[ReferenceStop],
    *,
    limit: int = 8,
) -> Tuple[ReferenceStop, ...]:
    """First checkpoint of each foundation count, including the solved end.

    This is an ordering set only. Lookup still uses every stop.
    """

    chosen: List[ReferenceStop] = []
    seen = set()
    for stop in stops:
        if stop.foundations in seen:
            continue
        seen.add(stop.foundations)
        chosen.append(stop)
        if len(chosen) >= int(limit):
            break
    return tuple(chosen)


def matching_stops(
    table: ReferenceTable,
    state: SpiderState,
) -> List[Tuple[ReferenceStop, str]]:
    """Physical matches, plus symmetry matches only when the stock is empty.

    ``pack_post_stock_symmetry_state`` raises while stock remains. This
    lookup does not call it in that case.
    """

    found: List[Tuple[ReferenceStop, str]] = []
    seen = set()
    for stop in table.by_physical.get(pack_state(state), ()):
        found.append((stop, "physical"))
        seen.add(stop.index)
    if state.stock:
        return found
    symmetry = pack_post_stock_symmetry_state(state)
    for stop in table.by_symmetry.get(symmetry, ()):
        if stop.index in seen:
            continue
        found.append((stop, "symmetry"))
    return found


def replay_remapped_suffix(
    candidate: SpiderState,
    reference: SpiderState,
    suffix: Sequence[Action],
) -> RemapReplay:
    """Remap ``suffix`` from ``reference`` columns onto ``candidate`` and replay it.

    Stock-bearing states rejoin only when ``pack_state`` agrees. The symmetry
    pack is not consulted while either state still has stock. A permuted
    stock-empty tableau uses ``column_permutation_mapping(reference, candidate)``.
    """

    if any(is_deal(action) for action in suffix):
        return RemapReplay(False, "suffix contains a deal", "remap", None, (), None)
    if candidate.stock or reference.stock:
        if pack_state(candidate) != pack_state(reference):
            return RemapReplay(
                False,
                "stock-bearing states are not a physical match",
                "remap",
                None,
                (),
                None,
            )
        mapping = tuple(range(len(candidate.columns)))
    else:
        if pack_post_stock_symmetry_state(candidate) != pack_post_stock_symmetry_state(reference):
            return RemapReplay(False, "not a post-stock column permutation", "remap", None, (), None)
        if pack_state(candidate) == pack_state(reference):
            mapping = tuple(range(len(candidate.columns)))
        else:
            mapped = column_permutation_mapping(reference, candidate)
            if mapped is None:
                return RemapReplay(False, "column mapping failed", "remap", None, (), None)
            mapping = tuple(int(index) for index in mapped)
    remapped = tuple(remap_tableau_action(action, mapping) for action in suffix)
    trial = candidate.clone()
    try:
        spent = int(replay_actions(trial, list(remapped)))
    except ValueError as exc:
        return RemapReplay(False, f"illegal remapped suffix: {exc}", "replay", mapping, remapped, None)
    if not trial.is_solved() or len(trial.foundations) != 8 or trial.stock:
        return RemapReplay(
            False,
            "remapped suffix did not finish eight foundations",
            "replay",
            mapping,
            remapped,
            spent,
        )
    return RemapReplay(True, "", "", mapping, remapped, spent)


def compose_full_route(
    canonical_actions: Sequence[Action],
    bridge: Sequence[Action],
    remapped_suffix: Sequence[Action],
) -> List[Action]:
    """Canonical prefix, the named preparation, the bridge, then the remapped suffix.

    Only the suffix is in the candidate's column coordinates. The prefix and
    the preparation stay in the original deal's coordinates.
    """

    return (
        list(canonical_actions[:CHECKPOINT_PREP])
        + list(EARLY_PREP)
        + list(bridge)
        + list(remapped_suffix)
    )


def load_verified_bridge_inputs(
    opening: SpiderState,
    actions: Sequence[Action],
) -> Tuple[EarlyCandidate, ReferenceTable, Tuple[ReferenceStop, ...], Tuple[Checkpoint, ...]]:
    """Replay the named early route. Raise if it is not the verified candidate."""

    deal_indexes = [index for index, action in enumerate(actions) if is_deal(action)]
    if len(deal_indexes) < 5 or deal_indexes[4] != FIFTH_DEAL_INDEX:
        raise BridgeContractError(
            f"fifth deal is {deal_indexes[4] if len(deal_indexes) >= 5 else None}, "
            f"expected action {FIFTH_DEAL_INDEX}"
        )
    checkpoints = build_checkpoints(opening, actions)
    if len(checkpoints) != len(actions) + 1:
        raise BridgeContractError("checkpoint count does not match the route")
    prepared = checkpoints[CHECKPOINT_PREP]
    posted = checkpoints[POST_SD5]
    finished = checkpoints[-1]
    if prepared.g != 139 or prepared.stock_cards != 10 or prepared.empty_columns != 2:
        raise BridgeContractError(
            f"checkpoint 140 is g={prepared.g} stock={prepared.stock_cards} "
            f"empty={prepared.empty_columns}"
        )
    if posted.g != 150 or posted.admissible_remaining != 18 or posted.stock_cards != 0:
        raise BridgeContractError(
            f"checkpoint 152 is g={posted.g} h={posted.admissible_remaining} "
            f"stock={posted.stock_cards}"
        )
    if finished.g != CANONICAL_TOTAL or not finished.state.is_solved():
        raise BridgeContractError("canonical route does not finish at corrected cost 172")
    table = build_reference_table(checkpoints, actions)
    if len(actions[POST_SD5:]) != SUFFIX_LEN or table.stops[0].suffix_cost != SUFFIX_LEN:
        raise BridgeContractError("canonical post-SD5 suffix is not the verified 22-cost continuation")
    pre_deal = prepared.state.clone()
    spent = prepared.g
    costs: List[int] = []
    for action in EARLY_PREP[:-1]:
        costs.append(step_cost(pre_deal, action))
        spent += int(apply_action(pre_deal, action))
    assessed = assess_immediate_deal(pre_deal, spent, 0, len(EARLY_PREP) - 1)
    deal_cost = step_cost(pre_deal, ("deal",))
    costs.append(deal_cost)
    early = pre_deal.clone()
    spent += int(apply_action(early, ("deal",)))
    height = int(admissible_remaining(early))
    if costs != [0, 1, 1, 1] or spent != EARLY_G or height != EARLY_H:
        raise BridgeContractError(
            f"early preparation replayed costs {costs} g={spent} h={height}"
        )
    if (
        assessed.same_suit_landings != 4
        or assessed.landings != EARLY_LANDINGS
        or assessed.g_post != EARLY_G
        or assessed.h_post != EARLY_H
        or assessed.f_post != EARLY_G + EARLY_H
    ):
        raise BridgeContractError(
            "early deal landings are not the verified four-landing candidate: "
            f"{assessed.landings}"
        )
    bonds = same_suit_bonds(early)
    hidden = face_down_count(early)
    if bonds != 48 or hidden != 3 or early.stock or len(early.foundations) != 2:
        raise BridgeContractError(
            f"early tableau is bonds={bonds} face_down={hidden} "
            f"stock={len(early.stock)} foundations={len(early.foundations)}"
        )
    symmetry = pack_post_stock_symmetry_state(early)
    candidate = EarlyCandidate(
        state=early,
        g=spent,
        h=height,
        f=spent + height,
        face_down=hidden,
        bonds=bonds,
        foundations=len(early.foundations),
        same_suit_landings=assessed.same_suit_landings,
        landings=tuple(assessed.landings),
        prep_costs=tuple(costs),
        checkpoint_140_g=prepared.g,
        checkpoint_140_stock=prepared.stock_cards,
        checkpoint_140_empty=prepared.empty_columns,
        fifth_deal_index=FIFTH_DEAL_INDEX,
        post_sd5_index=POST_SD5,
        post_sd5_g=posted.g,
        post_sd5_h=posted.admissible_remaining,
        suffix_len=SUFFIX_LEN,
        suffix_cost=table.stops[0].suffix_cost,
        symmetry=symmetry,
        already_on_reference=symmetry in table.by_symmetry,
    )
    return candidate, table, select_ordering_targets(table.stops), checkpoints


def _assess(
    state: SpiderState,
    g: int,
    table: ReferenceTable,
    ceiling: int,
) -> _Hit:
    hit = _Hit(pack=pack_state(state), g=int(g))
    matches = matching_stops(table, state)
    hit.reference_checkpoint_matches = len(matches)
    for stop, kind in matches:
        if kind == "physical":
            hit.physical_matches += 1
        else:
            hit.symmetry_only_matches += 1
    solved = bool(state.is_solved() and len(state.foundations) == 8 and not state.stock)
    if solved and accept_cost(g, ceiling):
        hit.accepted = True
        hit.kind = "solved"
        hit.projected = int(g)
        hit.suffix = ()
        hit.suffix_cost = 0
        return hit
    improving = [(stop, kind) for stop, kind in matches if int(g) < int(stop.g)]
    hit.rejected_non_improving = len(matches) - len(improving)
    improving.sort(key=lambda item: (-int(item[0].g), item[0].index))
    for stop, _kind in improving:
        hit.improving_attempts += 1
        projected = projected_full_cost(g, stop.g, table.canonical_total)
        replayed = replay_remapped_suffix(state, stop.state, stop.suffix)
        if not replayed.ok:
            if replayed.failure == "remap":
                hit.remap_failures += 1
            else:
                hit.replay_failures += 1
            continue
        if replayed.cost != stop.suffix_cost or projected is None or int(g) + int(replayed.cost) != projected:
            hit.replay_failures += 1
            continue
        if not accept_cost(projected, ceiling):
            hit.rejected_non_improving += 1
            continue
        hit.accepted = True
        hit.kind = "reference rejoin"
        hit.reference_index = stop.index
        hit.reference_g = stop.g
        hit.projected = projected
        hit.mapping = replayed.mapping
        hit.suffix = replayed.actions
        hit.suffix_cost = replayed.cost
        return hit
    return hit


def _add(total: _Hit, item: _Hit) -> None:
    total.reference_checkpoint_matches += item.reference_checkpoint_matches
    total.physical_matches += item.physical_matches
    total.symmetry_only_matches += item.symmetry_only_matches
    total.rejected_non_improving += item.rejected_non_improving
    total.improving_attempts += item.improving_attempts
    total.remap_failures += item.remap_failures
    total.replay_failures += item.replay_failures


def search_route_bridge(
    source: SpiderState,
    *,
    g0: int,
    references: ReferenceTable,
    ordering_targets: Optional[Sequence[ReferenceStop]] = None,
    ceiling: int = CEILING,
    max_unique: int = MAX_UNIQUE,
    time_limit_s: float = TIME_LIMIT_S,
    rss_abort_mb: float = RSS_ABORT_MB,
    lower_bound_fn: Optional[Callable[[SpiderState, int], int]] = None,
    actions_fn: Optional[Callable[[SpiderState], List[Action]]] = None,
    progress: bool = False,
) -> BridgeSearch:
    """One bounded bridge from ``source`` at absolute corrected cost ``g0``.

    A stock-empty permutation of a later reference checkpoint is accepted
    only when the remapped suffix replays and the full cost is at or below
    ``ceiling``. An equal reference cost does not stop the search. A cap
    without that rejoin is inconclusive.
    """

    g0 = int(g0)
    ceiling = int(ceiling)
    targets = (
        tuple(ordering_targets)
        if ordering_targets is not None
        else select_ordering_targets(references.stops)
    )
    totals = _Hit()
    max_foundations = len(source.foundations)

    def blank(**overrides) -> BridgeSearch:
        values = dict(
            accepted=False,
            kind="",
            stop_reason="",
            searched=False,
            g0=g0,
            ceiling=ceiling,
            g=None,
            reference_index=None,
            reference_g=None,
            projected_cost=None,
            mapping=None,
            bridge=(),
            remapped_suffix=(),
            suffix_cost=None,
            replay_ok=False,
            reference_checkpoint_matches=totals.reference_checkpoint_matches,
            physical_matches=totals.physical_matches,
            symmetry_only_matches=totals.symmetry_only_matches,
            rejected_non_improving=totals.rejected_non_improving,
            improving_attempts=totals.improving_attempts,
            remap_failures=totals.remap_failures,
            replay_failures=totals.replay_failures,
            terminal_hits=0,
            expanded=0,
            unique=0,
            generated=0,
            duplicate_skips=0,
            stale_skips=0,
            ceiling_prunes=0,
            lower_bound_prunes=0,
            proof_prune_identities=0,
            proof_prune_unretained=0,
            lower_bound_calls=0,
            zero_cost_actions=0,
            min_f=None,
            min_h=None,
            max_h=None,
            max_foundations=max_foundations,
            elapsed_s=0.0,
            peak_rss_mb=None,
            affinity_s=0.0,
            affinity_calls=0,
            ordering_target_count=len(targets),
            ordering_targets=tuple(stop.index for stop in targets),
            lane_exp=(),
            expanded_by_g=(),
            node_count=0,
            inconclusive=False,
            negative_within_cap=False,
        )
        values.update(overrides)
        return BridgeSearch(**values)

    preview = _assess(source, g0, references, ceiling)
    if preview.accepted:
        _add(totals, preview)
        return blank(
            accepted=True,
            kind=preview.kind,
            stop_reason=preview.kind,
            searched=False,
            g=g0,
            reference_index=preview.reference_index,
            reference_g=preview.reference_g,
            projected_cost=preview.projected,
            mapping=preview.mapping,
            remapped_suffix=preview.suffix,
            suffix_cost=preview.suffix_cost,
            replay_ok=True,
            terminal_hits=1,
            unique=1,
            node_count=1,
            max_foundations=max(max_foundations, len(source.foundations)),
        )

    accepted = _Hit()
    accepted_node = [-1]
    affinity_s = [0.0]
    affinity_calls = [0]
    nearest = [10**9]
    seen_foundations = [max_foundations]

    def bound(state: SpiderState, g: int) -> int:
        if lower_bound_fn is None:
            return int(admissible_remaining(state))
        return int(lower_bound_fn(state, g))

    def lane_keys_fn(state: SpiderState, g: int) -> Dict[str, Optional[tuple]]:
        started = time.perf_counter()
        if targets:
            displacement = min(target_displacement(state, stop.state) for stop in targets)
        else:
            displacement = 0
        affinity_s[0] += time.perf_counter() - started
        affinity_calls[0] += 1
        if displacement < nearest[0]:
            nearest[0] = displacement
        # Worse-than-best states stay on the goal lane. They are not deleted.
        cost_key = (int(g), int(displacement)) if displacement <= nearest[0] else None
        return {"goal": (int(displacement), int(g)), "cost": cost_key}

    def on_child(state: SpiderState, g: int, node_i: int) -> None:
        seen_foundations[0] = max(seen_foundations[0], len(state.foundations))
        hit = _assess(state, g, references, ceiling)
        _add(totals, hit)
        if hit.accepted and not accepted.accepted:
            accepted.accepted = True
            accepted.kind = hit.kind
            accepted.reference_index = hit.reference_index
            accepted.reference_g = hit.reference_g
            accepted.projected = hit.projected
            accepted.mapping = hit.mapping
            accepted.suffix = hit.suffix
            accepted.suffix_cost = hit.suffix_cost
            accepted.pack = hit.pack
            accepted.g = int(g)
            accepted_node[0] = int(node_i)

    def is_terminal(state: SpiderState) -> bool:
        return accepted.pack is not None and pack_state(state) == accepted.pack

    def on_progress(result: KernelResult, state: SpiderState, g: int, _node_i: int) -> None:
        if progress and result.unique and result.unique % 5000 == 0:
            print(
                f"PROGRESS unique={result.unique} expanded={result.expanded} "
                f"g={g} f={result.min_f} foundations={len(state.foundations)}",
                flush=True,
            )

    kernel = run_search(
        [{"ordered_digest": pack_state(source).hex(), "g": g0}],
        limits=SearchLimits(
            max_unique=int(max_unique),
            time_limit_s=float(time_limit_s),
            rss_abort_mb=float(rss_abort_mb),
            cost_ceiling=ceiling,
        ),
        identity_fn=pack_whole_game_identity,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=("goal", "cost"),
        lane_keys_fn=lane_keys_fn,
        is_terminal=is_terminal,
        actions_fn=actions_fn or all_legal_actions,
        action_order=bridge_action_order,
        on_child=on_child,
        on_progress=on_progress if progress else None,
        lower_bound_fn=bound,
        stop_on_first_terminal=True,
    )
    reason = str(kernel.stop_reason)
    bridge: Tuple[Action, ...] = ()
    replay_ok = False
    kind = ""
    projected = None
    reference_index = None
    reference_g = None
    mapping = None
    suffix: Tuple[Action, ...] = ()
    suffix_cost = None
    found_g = None
    terminal_hits = 0
    if accepted.accepted and accepted_node[0] >= 0:
        node_i = accepted_node[0]
        bridge = tuple(kernel.reconstruct(node_i))
        trial = source.clone()
        try:
            played = int(replay_actions(trial, list(bridge)))
        except ValueError:
            played = -1
        found_g = int(accepted.g) if accepted.g is not None else None
        replay_ok = bool(
            found_g is not None
            and played == found_g - g0
            and pack_state(trial) == accepted.pack
        )
        if replay_ok:
            kind = accepted.kind
            projected = accepted.projected
            reference_index = accepted.reference_index
            reference_g = accepted.reference_g
            mapping = accepted.mapping
            suffix = accepted.suffix
            suffix_cost = accepted.suffix_cost
            terminal_hits = 1
            if kind == "reference rejoin":
                reason = "reference rejoin"
            elif kind == "solved":
                reason = "solved"
        else:
            totals.replay_failures += 1
            reason = "replay rejected"
            replay_ok = False
    accepted_now = bool(replay_ok and kind)
    inconclusive = bool(not accepted_now and reason in {"time limit", "unique limit", "rss abort", "abort"})
    negative = bool(not accepted_now and reason == "complete")
    return blank(
        accepted=accepted_now,
        kind=kind,
        stop_reason=reason,
        searched=True,
        g=found_g if accepted_now else None,
        reference_index=reference_index,
        reference_g=reference_g,
        projected_cost=projected,
        mapping=mapping,
        bridge=bridge if accepted_now else (),
        remapped_suffix=suffix if accepted_now else (),
        suffix_cost=suffix_cost if accepted_now else None,
        replay_ok=replay_ok,
        terminal_hits=terminal_hits,
        expanded=int(kernel.expanded),
        unique=int(kernel.unique),
        generated=int(kernel.generated),
        duplicate_skips=int(kernel.duplicate_skips),
        stale_skips=int(kernel.stale_skips),
        ceiling_prunes=int(kernel.ceiling_prunes),
        lower_bound_prunes=int(kernel.lower_bound_prunes),
        proof_prune_identities=int(kernel.proof_prune_identities),
        proof_prune_unretained=int(kernel.proof_prune_unretained),
        lower_bound_calls=int(kernel.lower_bound_calls),
        zero_cost_actions=int(kernel.zero_cost_actions),
        min_f=kernel.min_f,
        min_h=kernel.min_h,
        max_h=kernel.max_h,
        max_foundations=seen_foundations[0],
        elapsed_s=float(kernel.elapsed_s),
        peak_rss_mb=kernel.peak_rss_mb,
        affinity_s=affinity_s[0],
        affinity_calls=affinity_calls[0],
        lane_exp=tuple(sorted(kernel.lane_exp.items())),
        expanded_by_g=tuple(sorted(kernel.expanded_by_g.items())),
        node_count=len(kernel.nodes),
        inconclusive=inconclusive,
        negative_within_cap=negative,
    )


