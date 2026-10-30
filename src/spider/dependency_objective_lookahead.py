"""Bounded local-objective lookahead over admitted dependency options.

Research only. This recommends one admitted prefix. It does not prune the
legal move set, does not certify a finished game, and does not change
``dependency_options`` or the search kernel.

The objective is a caller predicate. Fixture cards and columns stay in the
panel. Continuation search is the existing ``run_search`` on ordered
``pack_state`` identity, scored only by corrected move cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Callable, Optional, Sequence, Tuple

from spider.dependency_objective_panel import COMPARISON_BUDGET, build_state, reveal_predicate
from spider.dependency_options import (
    build_option,
    obligations_match_state,
    rebuild_obligations,
    select_dependency_portfolio,
)
from spider.engine import SpiderState
from spider.packed_state import pack_state, unpack_state
from spider.research_actions import apply_action, step_cost, tableau_actions
from spider.search_kernel import SearchLimits, run_search

_CAP_STOPS = frozenset({"time limit", "unique limit", "rss abort"})
_UNRESOLVED = frozenset({"upper-unfinished", "unknown"})


@dataclass(frozen=True)
class CandidateEvidence:
    """One admitted prefix and its scoped objective certificate."""

    option_id: str
    actions: Tuple
    prefix_cost: int
    continuation: Tuple
    continuation_cost: Optional[int]
    total_cost: Optional[int]
    status: str
    stop_reason: str
    kernel_called: bool
    unique: int
    expanded: int
    generated: int
    elapsed_s: float
    first_g: Optional[int]
    zero_cost_actions: int
    declared_source_g: int
    baseline_index: int


@dataclass(frozen=True)
class ObjectiveComparison:
    """A recommendation. ``pruned`` stays empty. Legal actions stay available."""

    status: str
    choice_id: Optional[str]
    baseline_id: Optional[str]
    reason: str
    legal_actions: Tuple
    pruned: Tuple
    candidates: Tuple[CandidateEvidence, ...]
    rejected_option_ids: Tuple[str, ...]
    obligations_status: str
    source_pack: str
    baseline_seconds: float
    kernel_seconds: float
    overhead_seconds: float
    absolute_g_used_for_proof: bool


def _limits(limits: Optional[SearchLimits]) -> SearchLimits:
    if limits is not None:
        return limits
    budget = COMPARISON_BUDGET
    return SearchLimits(
        max_unique=int(budget["max_unique"]),
        time_limit_s=float(budget["time_limit_s"]),
        rss_abort_mb=float(budget["rss_abort_mb"]),
        cost_ceiling=budget["cost_ceiling"],
        harvest_slack=None,
        max_depth=budget["max_depth"],
        proof_ceiling=None,
    )


def _play(state: SpiderState, actions: Sequence) -> Tuple[SpiderState, int]:
    """Replay ``actions``. Raise when a step is not a legal tableau move."""

    current = state.clone()
    total = 0
    for action in actions:
        normalized = tuple(int(part) for part in action)
        if normalized not in tableau_actions(current):
            raise ValueError(f"illegal continuation step: {normalized!r}")
        total += int(step_cost(current, normalized))
        apply_action(current, normalized)
    return current, total


def _generated_options(state: SpiderState, obligations) -> Tuple:
    options = []
    for action in tableau_actions(state):
        normalized = tuple(int(part) for part in action)
        options.append(
            build_option(
                state,
                (normalized,),
                source_g=0,
                structural_name=str(normalized),
                option_id=str(normalized),
                obligations=obligations,
            )
        )
    return tuple(options)


def _empty_result(
    *,
    status: str,
    reason: str,
    legal: Tuple,
    source_pack: str,
    obligations_status: str,
    baseline_seconds: float = 0.0,
    rejected: Tuple[str, ...] = (),
) -> ObjectiveComparison:
    return ObjectiveComparison(
        status=status,
        choice_id=None,
        baseline_id=None,
        reason=reason,
        legal_actions=legal,
        pruned=(),
        candidates=(),
        rejected_option_ids=rejected,
        obligations_status=obligations_status,
        source_pack=source_pack,
        baseline_seconds=baseline_seconds,
        kernel_seconds=0.0,
        overhead_seconds=0.0,
        absolute_g_used_for_proof=False,
    )


def _classify(stop_reason: str, hit_depth_limit: bool, found: bool) -> str:
    if hit_depth_limit or stop_reason == "depth limit":
        return "upper-unfinished" if found else "unknown"
    if stop_reason == "complete" and found:
        return "exact"
    if stop_reason == "complete":
        return "exhausted-no-hit"
    if stop_reason in _CAP_STOPS or stop_reason == "":
        return "upper-unfinished" if found else "unknown"
    return "upper-unfinished" if found else "unknown"


def _best_witness(result, prefix_state: SpiderState, predicate: Callable[[SpiderState], bool]):
    """Replay every kernel terminal. Keep the cheapest valid objective witness."""

    best_actions = None
    best_cost = None
    for terminal in result.terminals:
        actions = tuple(result.reconstruct(int(terminal["node"])))
        try:
            reached, cost = _play(prefix_state, actions)
        except ValueError:
            continue
        if pack_state(reached).hex() != terminal["store"]:
            continue
        if not predicate(reached):
            continue
        if best_cost is None or cost < best_cost:
            best_actions = actions
            best_cost = cost
    return best_actions, best_cost


def _evaluate_candidate(state, option, predicate, limits, baseline_index: int):
    prefix_state, prefix_cost = _play(state, option.actions)
    declared = int(option.source_g)
    if predicate(prefix_state):
        return (
            CandidateEvidence(
                option_id=option.option_id,
                actions=tuple(option.actions),
                prefix_cost=prefix_cost,
                continuation=(),
                continuation_cost=0,
                total_cost=prefix_cost,
                status="exact",
                stop_reason="prefix-terminal",
                kernel_called=False,
                unique=0,
                expanded=0,
                generated=0,
                elapsed_s=0.0,
                first_g=None,
                zero_cost_actions=0,
                declared_source_g=declared,
                baseline_index=baseline_index,
            ),
            0.0,
        )
    root_pack = pack_state(prefix_state)
    started = perf_counter()
    result = run_search(
        ({"ordered_digest": root_pack.hex(), "g": prefix_cost},),
        limits=limits,
        identity_fn=pack_state,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=("cost",),
        lane_key_fns=(lambda _state, g: (g,),),
        is_terminal=predicate,
        actions_fn=tableau_actions,
        stop_on_first_terminal=False,
    )
    elapsed = perf_counter() - started
    continuation, continuation_cost = _best_witness(result, prefix_state, predicate)
    found = continuation_cost is not None
    status = _classify(result.stop_reason, bool(result.hit_depth_limit), found)
    total = None if continuation_cost is None else prefix_cost + int(continuation_cost)
    evidence = CandidateEvidence(
        option_id=option.option_id,
        actions=tuple(option.actions),
        prefix_cost=prefix_cost,
        continuation=tuple(continuation or ()),
        continuation_cost=None if continuation_cost is None else int(continuation_cost),
        total_cost=total,
        status=status,
        stop_reason=result.stop_reason,
        kernel_called=True,
        unique=int(result.unique),
        expanded=int(result.expanded),
        generated=int(result.generated),
        elapsed_s=float(result.elapsed_s),
        first_g=None if result.first_g is None else int(result.first_g),
        zero_cost_actions=int(result.zero_cost_actions),
        declared_source_g=declared,
        baseline_index=baseline_index,
    )
    return evidence, elapsed


def _choose(candidates: Sequence[CandidateEvidence], baseline_id: Optional[str]):
    if any(candidate.status in _UNRESOLVED for candidate in candidates):
        return "inconclusive", baseline_id, "an admitted candidate has no exact scoped cost"
    exact = [candidate for candidate in candidates if candidate.status == "exact" and candidate.total_cost is not None]
    if not exact:
        return "no-exact-in-scope", baseline_id, "every admitted candidate exhausted the scoped objective without a hit"
    winner = min(exact, key=lambda candidate: (int(candidate.total_cost), candidate.baseline_index))
    return "ranked", winner.option_id, "lowest exact scoped cost, baseline order on ties"


def compare_local_objective(
    state: SpiderState,
    predicate: Callable[[SpiderState], bool],
    *,
    obligations=None,
    options=None,
    limits: Optional[SearchLimits] = None,
) -> ObjectiveComparison:
    """Compare admitted prefixes by verified cost to ``predicate``.

    Local cost starts at 0 on ``state``. A stored ``source_g`` is ignored
    for the objective total and is not an opening proof. Nothing is pruned.
    """

    wall = perf_counter()
    legal = tuple(tableau_actions(state))
    source_pack = pack_state(state).hex()
    if predicate(state):
        return _empty_result(
            status="already-satisfied",
            reason="the source already meets the objective",
            legal=legal,
            source_pack=source_pack,
            obligations_status="not_applied",
        )
    graph = rebuild_obligations(state) if obligations is None else tuple(obligations)
    if not obligations_match_state(state, graph):
        return _empty_result(
            status="refused",
            reason="obligations do not match the source",
            legal=legal,
            source_pack=source_pack,
            obligations_status="refused",
        )
    supplied = _generated_options(state, graph) if options is None else tuple(options)
    if any(option.source_pack != source_pack for option in supplied):
        return _empty_result(
            status="refused",
            reason="an option was built from a different source",
            legal=legal,
            source_pack=source_pack,
            obligations_status="refused",
            rejected=tuple(option.option_id for option in supplied if option.source_pack != source_pack),
        )
    search_limits = _limits(limits)
    baseline_started = perf_counter()
    pick = select_dependency_portfolio(supplied, graph, limit=len(supplied))
    baseline_seconds = perf_counter() - baseline_started
    if pick.obligations_status != "matched" or not pick.chosen:
        rejected = tuple(option.option_id for option in supplied if option not in pick.chosen)
        return _empty_result(
            status="refused",
            reason="admission retained no matched candidate",
            legal=legal,
            source_pack=source_pack,
            obligations_status=pick.obligations_status,
            baseline_seconds=baseline_seconds,
            rejected=rejected,
        )
    evidences = []
    kernel_accounted = 0.0
    for index, option in enumerate(pick.chosen):
        evidence, kernel_elapsed = _evaluate_candidate(
            state, option, predicate, search_limits, index
        )
        evidences.append(evidence)
        kernel_accounted += kernel_elapsed
    status, choice, reason = _choose(tuple(evidences), pick.chosen[0].option_id)
    chosen_ids = {option.option_id for option in pick.chosen}
    rejected = tuple(option.option_id for option in supplied if option.option_id not in chosen_ids)
    return ObjectiveComparison(
        status=status,
        choice_id=choice,
        baseline_id=pick.chosen[0].option_id,
        reason=reason,
        legal_actions=legal,
        pruned=(),
        candidates=tuple(evidences),
        rejected_option_ids=rejected,
        obligations_status=pick.obligations_status,
        source_pack=source_pack,
        baseline_seconds=baseline_seconds,
        kernel_seconds=kernel_accounted,
        overhead_seconds=max(0.0, perf_counter() - wall - baseline_seconds - kernel_accounted),
        absolute_g_used_for_proof=False,
    )


def compare_panel_board(board, *, limits: Optional[SearchLimits] = None) -> ObjectiveComparison:
    """Evaluate one frozen panel board. Callers choose development or reserved."""

    state = build_state(board)
    return compare_local_objective(
        state,
        reveal_predicate(state, board.target_column),
        limits=limits,
    )
