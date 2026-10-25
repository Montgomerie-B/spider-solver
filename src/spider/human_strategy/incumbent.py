"""Verified complete routes and the safe incumbent prune.

A numeric ceiling may prune. Only an independently replayed route that
finishes all eight foundations may be reported as the best verified
complete solution. A partial trajectory never becomes that route.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from spider.engine import SpiderState
from spider.metrics import Action, replay_actions


class IncumbentRejected(ValueError):
    """The supplied route is illegal, partial, or costed incorrectly."""


@dataclass(frozen=True)
class VerifiedRoute:
    actions: tuple
    cost: int
    foundations: int
    solved: bool
    source: str
    source_id: str


def verify_complete_solution(
    opening: SpiderState,
    actions: Sequence[Action],
    *,
    expected_cost: Optional[int] = None,
    source: str = "imported",
    source_id: str = "",
) -> VerifiedRoute:
    """Replay ``actions`` on a clone. Reject anything that is not a solved game.

    The caller's state is not mutated. ``expected_cost``, when given, must
    equal the corrected MobilityWare cost of the replay.
    """

    trial = opening.clone()
    try:
        cost = int(replay_actions(trial, list(actions)))
    except ValueError as exc:
        raise IncumbentRejected(f"illegal incumbent: {exc}") from exc
    solved = bool(trial.is_solved() and len(trial.foundations) == 8 and not trial.stock)
    if not solved:
        raise IncumbentRejected(
            f"partial trajectory is not an incumbent: "
            f"foundations={len(trial.foundations)} solved={trial.is_solved()} cost={cost}"
        )
    if expected_cost is not None and int(expected_cost) != cost:
        raise IncumbentRejected(f"incorrect cost: replay {cost} != expected {int(expected_cost)}")
    return VerifiedRoute(
        actions=tuple(actions),
        cost=cost,
        foundations=len(trial.foundations),
        solved=True,
        source=source,
        source_id=source_id,
    )


def proof_prune(g: int, h_lb: int, incumbent_cost: Optional[int]) -> bool:
    """True when ``g + h_lb`` cannot strictly beat a verified ceiling.

    ``h_lb`` must already be an admissible remainder for this state. Callers
    pass 0 when they have no applicable admissible bound. Heuristic remainders
    are not passed here.
    """

    if incumbent_cost is None:
        return False
    return int(g) + int(h_lb) >= int(incumbent_cost)


def excavation_cost_cap(requested: int, ceiling: Optional[int]) -> int:
    """Cap a tactical cost by a global slack ceiling.

    ``ceiling`` is the additional corrected cost still allowed, already
    reduced by the exact cost so far. ``None`` leaves the request unchanged.
    """

    requested = int(requested)
    if ceiling is None:
        return requested
    return min(requested, max(0, int(ceiling)))
