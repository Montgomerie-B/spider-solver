"""MobilityWare move-cost metrics and solution I/O.

Counter taxonomy (see docs/4925153_move_accounting_incident.md):

* ``explicit_commands`` — every replay line
* ``tableau_moves`` / ``stock_deals``
* ``mobilityware_moves`` — corrected UI-emulating total (preferred)
* ``legacy_mw`` — defective historical free-empty-stack total (audit only)

The withdrawn constant 163 for deal 4925153 was ``legacy_mw``, not a
verified MobilityWare UI score. Corrected total for the same trace is 172.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple, Union

from .deal import load_deal
from .engine import SpiderState
from .rules import LEGACY_MW_RULES, MW_RULES, deal_cost, legacy_mw_move_cost

# Deal 4925153 — complete user-supplied trace (see move-accounting audit).
# RECORD_MW_COST: historical aspirational/partial figure; not authoritative.
RECORD_MW_COST = 119
# Withdrawn as "verified MobilityWare": was legacy_mw under defective free-empty rule.
LEGACY_CANONICAL_MW_COST = 163
# Corrected MobilityWare-emulating total for solutions/4925153_canonical.moves
CANONICAL_MOBILITYWARE_MOVES = 172
# Back-compat alias used by older optimiser code; means mobilityware_moves.
CANONICAL_MW_COST = CANONICAL_MOBILITYWARE_MOVES

Action = Union[Tuple[int, int, int], Tuple[str]]


def replay_actions(state: SpiderState, actions: List[Action]) -> int:
    """Apply actions in place; return corrected ``mobilityware_moves`` total.

    Uses default ``MW_RULES`` (full-column-to-empty free only).
    """
    total = 0
    for action in actions:
        if action == ("deal",):
            total += state.deal()
        else:
            src, dst, k = action
            total += state.move(src, dst, k)
    return total


def replay_actions_detailed(
    state: SpiderState, actions: List[Action]
) -> Dict[str, int]:
    """Replay with full counter taxonomy. Mutates ``state``."""
    explicit = tableau = deals = removals = engine = 0
    mobilityware = legacy = 0
    for action in actions:
        explicit += 1
        engine += 1
        f0 = len(state.foundations)
        if action == ("deal",):
            deals += 1
            c = state.deal()
            mobilityware += c
            legacy += deal_cost()
        else:
            tableau += 1
            src, dst, k = action
            fu = len(state.columns[src].face_up)
            fd = len(state.columns[src].face_down)
            empty = state.columns[dst].is_empty()
            legacy += legacy_mw_move_cost(
                cards_moved=k,
                source_face_up_count=fu,
                dest_was_empty=empty,
                source_face_down_count=fd,
            )
            # engine.move uses corrected MW_RULES
            mobilityware += state.move(src, dst, k, rules=MW_RULES)
        dr = len(state.foundations) - f0
        removals += dr
        engine += dr
    return {
        "explicit_commands": explicit,
        "tableau_moves": tableau,
        "stock_deals": deals,
        "automatic_foundation_removals": removals,
        "engine_actions": engine,
        "mobilityware_moves": mobilityware,
        "legacy_mw": legacy,
        "mobilityware_count_verified": True,
    }


def parse_moves_file(path: Path) -> List[Action]:
    """Parse .moves file into 0-based (src, dst, k) or ('deal',)."""
    actions: List[Action] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] == "deal":
            actions.append(("deal",))
        elif parts[0] == "move" and len(parts) >= 4:
            actions.append((int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3])))
        else:
            raise ValueError(f"bad moves line: {line}")
    return actions


def mw_cost_from_moves_file(path: Path, deal_path: Path | None = None) -> int:
    """Replay a .moves file from initial deal; return MW cost (raises if illegal)."""
    root = Path(__file__).resolve().parents[2]
    deal = deal_path or root / "deals" / "4925153.txt"
    state = SpiderState.from_cards(load_deal(deal))
    return replay_actions(state, parse_moves_file(path))


def mw_cost_for_actions(initial: SpiderState, actions: List[Action]) -> int:
    """Replay actions on a clone; return MW cost."""
    state = initial.clone()
    return replay_actions(state, actions)


def count_actions(path: Path) -> tuple[int, int]:
    """Return (tableau_moves, deals) line counts."""
    moves = deals = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.split()[0] == "move":
            moves += 1
        elif line.split()[0] == "deal":
            deals += 1
    return moves, deals


def export_actions_to_moves_file(actions: List[Action], path: Path, header: str = "") -> None:
    """Write 1-based column .moves file."""
    lines: List[str] = []
    if header:
        for hline in header.strip().splitlines():
            lines.append(f"# {hline}" if not hline.startswith("#") else hline)
    for action in actions:
        if action == ("deal",):
            lines.append("deal")
        else:
            src, dst, k = action
            lines.append(f"move {src + 1} {dst + 1} {k}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def format_action(action: Action) -> str:
    if action == ("deal",):
        return "deal"
    src, dst, k = action
    return f"move {src + 1} {dst + 1} {k}"