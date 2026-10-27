"""Stock-empty completion search from one packed checkpoint.

The root is an exact physical state. ``pack_whole_game_identity`` is the
search identity and ``pack_state`` is the stored tableau, so a reconstructed
path uses real column indices. After the stock is empty that identity is the
existing column-permutation quotient. While stock remains it is ordered
``pack_state``.

Ordering is not a bound. The proof bound is ``admissible_remaining``.
A state is pruned only when ``g + h`` is strictly above the absolute ceiling.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from spider.engine import SpiderState
from spider.human_strategy.evaluation import admissible_remaining
from spider.metrics import Action, format_action, replay_actions
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import all_legal_actions, step_cost
from spider.search_kernel import KernelResult, SearchLimits, run_search


def completion_lane_key(state: SpiderState, g: int) -> tuple:
    """Cheap prefix of the existing stock-empty completion key.

    The full ``completion_key`` also ranks blockers, boundaries, and the
    legal-move count. Those terms enumerate the tableau and are not required
    for ``f = g + h`` order. ``h`` is ``admissible_remaining``. A missing
    stock-empty key is not invented: this tuple is defined for every state
    the proof bound can score.
    """

    h = int(admissible_remaining(state))
    return (int(g) + h, h, -len(state.foundations), int(g))


def cost_lane_key(_state: SpiderState, g: int) -> tuple:
    """Existing uniform-cost order."""

    return (int(g),)


_ORDERINGS: Dict[str, Callable[[SpiderState, int], tuple]] = {
    "completion": completion_lane_key,
    "cost": cost_lane_key,
}


@dataclass
class CompletionSearch:
    ordering: str
    ceiling: int
    g0: int
    stop_reason: str
    solved: bool
    solution_g: Optional[int]
    suffix: Tuple[Action, ...]
    suffix_cost: Optional[int]
    replay_ok: bool
    negative_proof: bool
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
    symmetry_collapses: int
    elapsed_s: float
    peak_rss_mb: Optional[float]
    min_g: Optional[int]
    max_g: Optional[int]
    min_h: Optional[int]
    max_h: Optional[int]
    min_f: Optional[int]
    expanded_by_g: Tuple[Tuple[int, int], ...]
    generated_by_g: Tuple[Tuple[int, int], ...]
    prunes_by_f: Tuple[Tuple[int, int], ...]
    prunes_by_g: Tuple[Tuple[int, int], ...]
    kept_by_h: Tuple[Tuple[int, int], ...]
    expanded_by_foundations: Tuple[Tuple[int, int], ...]
    lane_exp: Tuple[Tuple[str, int], ...]
    max_foundations_expanded: int
    terminals: int


def search_post_sd5(
    source: SpiderState,
    *,
    g0: int,
    ceiling: int,
    ordering: str = "completion",
    max_unique: int = 80_000,
    time_limit_s: float = 90.0,
    rss_abort_mb: float = 512.0,
    progress: bool = False,
) -> CompletionSearch:
    """Search from ``source`` at absolute cost ``g0`` for eight foundations.

    ``ceiling`` is an absolute corrected-cost ceiling. The first legal
    solution at or below it stops the run. That solution's cost is verified
    by replaying the stored actions on a clone of ``source``. Stopping at the
    first solution does not prove the cost is minimum. An empty frontier
    with no solution is a negative proof inside this ceiling, this identity,
    and this admissible bound. A unique, time, or memory stop is not.

    A child with ``g + h`` above the ceiling is rejected before it takes a
    unique slot. A later cheaper arrival to that identity is checked again.
    Equality with the ceiling stays eligible.
    """

    if ordering not in _ORDERINGS:
        raise ValueError(f"unknown completion ordering: {ordering}")
    key_fn = _ORDERINGS[ordering]
    g0 = int(g0)
    ceiling = int(ceiling)
    prunes_by_g: Counter = Counter()
    kept_by_h: Counter = Counter()
    expanded_by_foundations: Counter = Counter()
    first_physical: Dict[bytes, bytes] = {}
    collapses = [0]

    def identity(state: SpiderState) -> bytes:
        ident = pack_whole_game_identity(state)
        physical = pack_state(state)
        seen = first_physical.get(ident)
        if seen is None:
            first_physical[ident] = physical
        elif seen != physical:
            collapses[0] += 1
        return ident

    def bound(state: SpiderState, g: int) -> int:
        h = int(admissible_remaining(state))
        if int(g) + h > ceiling:
            prunes_by_g[int(g)] += 1
        else:
            kept_by_h[h] += 1
        return h

    def actions_of(state: SpiderState) -> List[Action]:
        expanded_by_foundations[len(state.foundations)] += 1
        return all_legal_actions(state)

    def on_progress(result: KernelResult, state: SpiderState, g: int, _node_i: int) -> None:
        if progress and result.unique and result.unique % 5000 == 0:
            print(
                f"PROGRESS unique={result.unique} expanded={result.expanded} "
                f"g={g} foundations={len(state.foundations)}",
                flush=True,
            )

    kernel: KernelResult = run_search(
        [
            {
                "ordered_digest": pack_state(source).hex(),
                "g": g0,
            }
        ],
        limits=SearchLimits(
            max_unique=int(max_unique),
            time_limit_s=float(time_limit_s),
            rss_abort_mb=float(rss_abort_mb),
            cost_ceiling=ceiling,
        ),
        identity_fn=identity,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=(ordering,),
        lane_key_fns=(key_fn,),
        is_terminal=lambda state: bool(state.is_solved()),
        actions_fn=actions_of,
        action_order=lambda state, actions: sorted(
            actions,
            key=lambda action: (step_cost(state, action), str(action)),
        ),
        lower_bound_fn=bound,
        stop_on_first_terminal=True,
        on_progress=on_progress if progress else None,
    )
    suffix: Tuple[Action, ...] = ()
    solution_g: Optional[int] = None
    suffix_cost: Optional[int] = None
    replay_ok = False
    if kernel.terminals:
        best = min(kernel.terminals, key=lambda item: int(item["g"]))
        solution_g = int(best["g"])
        suffix = tuple(kernel.reconstruct(int(best["node"])))
        trial = source.clone()
        try:
            played = int(replay_actions(trial, list(suffix)))
        except ValueError:
            played = -1
        replay_ok = bool(
            played == solution_g - g0
            and trial.is_solved()
            and len(trial.foundations) == 8
            and not trial.stock
            and solution_g <= ceiling
        )
        if replay_ok:
            suffix_cost = played
    solved = bool(replay_ok)
    negative_proof = bool(kernel.stop_reason == "complete" and not kernel.terminals)
    return CompletionSearch(
        ordering=ordering,
        ceiling=ceiling,
        g0=g0,
        stop_reason=str(kernel.stop_reason),
        solved=solved,
        solution_g=solution_g if solved else None,
        suffix=suffix if solved else (),
        suffix_cost=suffix_cost,
        replay_ok=replay_ok,
        negative_proof=negative_proof,
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
        symmetry_collapses=int(collapses[0]),
        elapsed_s=float(kernel.elapsed_s),
        peak_rss_mb=kernel.peak_rss_mb,
        min_g=kernel.min_g,
        max_g=kernel.max_g,
        min_h=kernel.min_h,
        max_h=kernel.max_h,
        min_f=kernel.min_f,
        expanded_by_g=tuple(sorted(kernel.expanded_by_g.items())),
        generated_by_g=tuple(sorted(kernel.generated_by_g.items())),
        prunes_by_f=tuple(sorted(kernel.prunes_by_F.items())),
        prunes_by_g=tuple(sorted(prunes_by_g.items())),
        kept_by_h=tuple(sorted(kept_by_h.items())),
        expanded_by_foundations=tuple(sorted(expanded_by_foundations.items())),
        lane_exp=tuple(sorted(kernel.lane_exp.items())),
        max_foundations_expanded=max(expanded_by_foundations, default=0),
        terminals=len(kernel.terminals),
    )


def public_search(row: CompletionSearch) -> dict:
    """JSON-ready counters. The suffix is included only when replay succeeded."""

    return {
        "ordering": row.ordering,
        "ceiling": row.ceiling,
        "g0": row.g0,
        "stop_reason": row.stop_reason,
        "solved": row.solved,
        "solution_g": row.solution_g,
        "suffix_cost": row.suffix_cost,
        "suffix": [format_action(action) for action in row.suffix],
        "replay_ok": row.replay_ok,
        "negative_proof": row.negative_proof,
        "expanded": row.expanded,
        "unique": row.unique,
        "generated": row.generated,
        "duplicate_skips": row.duplicate_skips,
        "stale_skips": row.stale_skips,
        "ceiling_prunes": row.ceiling_prunes,
        "lower_bound_prunes": row.lower_bound_prunes,
        "proof_prune_identities": row.proof_prune_identities,
        "proof_prune_unretained": row.proof_prune_unretained,
        "lower_bound_calls": row.lower_bound_calls,
        "zero_cost_actions": row.zero_cost_actions,
        "symmetry_collapses": row.symmetry_collapses,
        "elapsed_s": round(row.elapsed_s, 3),
        "peak_rss_mb": row.peak_rss_mb,
        "min_g": row.min_g,
        "max_g": row.max_g,
        "min_h": row.min_h,
        "max_h": row.max_h,
        "min_f": row.min_f,
        "expanded_by_g": row.expanded_by_g,
        "generated_by_g": row.generated_by_g,
        "prunes_by_f": row.prunes_by_f,
        "prunes_by_g": row.prunes_by_g,
        "kept_by_h": row.kept_by_h,
        "expanded_by_foundations": row.expanded_by_foundations,
        "lane_exp": row.lane_exp,
        "max_foundations_expanded": row.max_foundations_expanded,
        "terminals": row.terminals,
    }
