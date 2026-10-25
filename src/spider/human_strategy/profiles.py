"""Resource profiles for the integrated human-strategy controller.

The extended profile is never selected unless the caller names it.
Workers stay at one. The Optiplex has 16 GB of RAM; the abort ceilings
are intentionally well below that.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Profile:
    name: str
    time_limit_s: float
    rss_abort_mb: float
    strategic_width: int
    max_width: int
    tactical_nodes: int
    tactical_time_s: float
    tactical_max_cost: int
    max_steps: int
    commitment_margin: float = 0.75
    workers: int = 1
    consult_portfolio: bool = True
    frontier_limit: int = 1
    proposals_per_decision: int = 2
    slice_steps: int = 0
    line_attempt_cap: int = 0

    def with_overrides(self, **kwargs) -> "Profile":
        data = {key: value for key, value in kwargs.items() if value is not None}
        updated = replace(self, **data)
        if updated.workers != 1:
            updated = replace(updated, workers=1)
        if updated.strategic_width < 1:
            updated = replace(updated, strategic_width=1)
        if updated.max_width < updated.strategic_width:
            updated = replace(updated, max_width=updated.strategic_width)
        if updated.frontier_limit < 1:
            updated = replace(updated, frontier_limit=1)
        if updated.frontier_limit > 16:
            updated = replace(updated, frontier_limit=16)
        if updated.proposals_per_decision < 1:
            updated = replace(updated, proposals_per_decision=1)
        if updated.proposals_per_decision > 4:
            updated = replace(updated, proposals_per_decision=4)
        if updated.slice_steps < 0:
            updated = replace(updated, slice_steps=0)
        if updated.line_attempt_cap < 0:
            updated = replace(updated, line_attempt_cap=0)
        return updated


PROFILES = {
    "smoke": Profile(
        name="smoke",
        time_limit_s=20.0,
        rss_abort_mb=1024.0,
        strategic_width=2,
        max_width=3,
        tactical_nodes=400,
        tactical_time_s=0.35,
        tactical_max_cost=3,
        max_steps=8,
        consult_portfolio=True,
        frontier_limit=1,
        proposals_per_decision=2,
    ),
    "pilot": Profile(
        name="pilot",
        time_limit_s=600.0,
        rss_abort_mb=3072.0,
        strategic_width=3,
        max_width=4,
        tactical_nodes=4000,
        tactical_time_s=1.5,
        tactical_max_cost=6,
        max_steps=80,
        consult_portfolio=True,
        frontier_limit=8,
        proposals_per_decision=3,
        slice_steps=24,
        line_attempt_cap=48,
    ),
    "extended": Profile(
        name="extended",
        time_limit_s=3600.0,
        rss_abort_mb=4096.0,
        strategic_width=4,
        max_width=6,
        tactical_nodes=20000,
        tactical_time_s=4.0,
        tactical_max_cost=8,
        max_steps=400,
        consult_portfolio=True,
        frontier_limit=12,
        proposals_per_decision=4,
        slice_steps=40,
        line_attempt_cap=80,
    ),
}


def resolve_profile(name: str) -> Profile:
    key = (name or "smoke").strip().lower()
    if key not in PROFILES:
        known = ", ".join(sorted(PROFILES))
        raise ValueError(f"unknown profile {name!r}; expected one of {known}")
    return PROFILES[key]
