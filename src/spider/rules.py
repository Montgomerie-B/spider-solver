"""MobilityWare Spider Solitaire (4-suit) scoring rules.

Move accounting (forensic audit 4925153, 2026):

* ``explicit_commands`` — every player/replay line (tableau + deal).
* ``mobilityware_moves`` — UI-emulating count (preferred for optimisation).
* ``legacy_mw`` — historical counter that treated *all* entire-face-up→empty
  moves as free (produced false 163 for the 174-command canonical trace).

Corrected MobilityWare rule (reproduces user-observed 172 on deal 4925153):

* Every stock deal costs 1.
* This project's benchmark uses MobilityWare's **Unrestricted Deal** setting,
  so stock may be dealt while one or more tableau columns are empty.
* Every tableau move costs 1, **except** relocating an **entire column**
  (no face-down cards remain under the moved run) onto an empty column,
  which costs 0.

Automatic foundation removals never adjust the move counter.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MobilityWareRules:
    # The benchmark/user profile has MobilityWare's optional Unrestricted Deal
    # setting enabled.  A restricted profile can still set this to False.
    can_deal_into_empty: bool = True
    # Corrected: free only when the move empties the source column.
    zero_cost_move_to_empty: bool = True
    zero_cost_requires_emptying_column: bool = True
    # Historical (defective) behaviour for comparison / legacy_mw only.
    legacy_zero_cost_ignores_face_down: bool = False


MW_RULES = MobilityWareRules()

# Explicit legacy rules object for reproducing the withdrawn 163 total.
LEGACY_MW_RULES = MobilityWareRules(
    zero_cost_move_to_empty=True,
    zero_cost_requires_emptying_column=False,
    legacy_zero_cost_ignores_face_down=True,
)


def mw_move_cost(
    *,
    cards_moved: int,
    source_face_up_count: int,
    dest_was_empty: bool,
    source_face_down_count: int = 0,
    rules: MobilityWareRules = MW_RULES,
) -> int:
    """Return MobilityWare move cost for a tableau move.

    Default ``MW_RULES`` implements the corrected counting convention.
    Pass ``LEGACY_MW_RULES`` to reproduce the defective free-empty-stack
    behaviour that reported 163 for the 174-command canonical trace.
    """
    if (
        rules.zero_cost_move_to_empty
        and dest_was_empty
        and cards_moved == source_face_up_count
        and cards_moved > 0
    ):
        if rules.zero_cost_requires_emptying_column:
            # Free only if no face-down cards remain (full-column relocate).
            if source_face_down_count == 0:
                return 0
            return 1
        # Legacy defective path: free regardless of face-down under the run.
        return 0
    return 1


def mobilityware_move_cost(
    *,
    cards_moved: int,
    source_face_up_count: int,
    dest_was_empty: bool,
    source_face_down_count: int = 0,
) -> int:
    """Authoritative MobilityWare UI-emulating tableau cost (corrected)."""
    return mw_move_cost(
        cards_moved=cards_moved,
        source_face_up_count=source_face_up_count,
        dest_was_empty=dest_was_empty,
        source_face_down_count=source_face_down_count,
        rules=MW_RULES,
    )


def legacy_mw_move_cost(
    *,
    cards_moved: int,
    source_face_up_count: int,
    dest_was_empty: bool,
    source_face_down_count: int = 0,
) -> int:
    """Defective historical cost (for audit comparison only)."""
    return mw_move_cost(
        cards_moved=cards_moved,
        source_face_up_count=source_face_up_count,
        dest_was_empty=dest_was_empty,
        source_face_down_count=source_face_down_count,
        rules=LEGACY_MW_RULES,
    )


def deal_cost() -> int:
    """Stock deal always increments MobilityWare count by 1."""
    return 1
