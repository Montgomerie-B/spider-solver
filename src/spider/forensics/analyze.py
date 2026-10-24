"""Load, validate, analyse, and compare canonical Spider solutions."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional, Sequence

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions_detailed

from .attribution import (
    backward_attributions,
    build_findings,
    counterfactual_seeds,
    divergence,
    phase_gaps,
)
from .episodes import build_parks, build_workspace, park_summary, workspace_summary
from .trajectory import ForensicIntegrityError, replay_trajectory

SCHEMA_VERSION = "spider-solution-forensics-0.105"

SCHEMA_NOTES = {
    "version": SCHEMA_VERSION,
    "state_hash": "sha256 of spider.packed_state.pack_state. Ordered columns. Not Zobrist.",
    "post_stock_symmetry_hash": (
        "sha256 of pack_post_stock_symmetry_state when stock is empty, else null. "
        "Research identity only. Never applied while stock remains."
    ),
    "physical_card": (
        "Index into the original deal file order, plus a label such as 7S#A. "
        "The suffix distinguishes duplicate rank/suit cards. Stock-deal placement "
        "is recorded and is not counted as a handle."
    ),
    "experimental_debt_score": (
        "3*suit_boundaries + 2*rank_discontinuities + buried_face_up + "
        "2*component_layers + immobile_exposed. Face-down is in the indicator "
        "vector and is excluded from the score. Not a remaining-cost estimate."
    ),
    "park_confidence": "HIGH, MEDIUM, or LOW. LOW is retained as ambiguous evidence.",
    "exclusive_cost_class": (
        "Priority partition of each action's corrected MW cost so class costs sum "
        "to the route total. Tags are multi-label and are not a partition."
    ),
    "counterfactual_seed": "One legal ply of immediate metrics. Not a search and not a solved branch. A poor immediate rank on a reveal is not a verdict.",
    "segment_gap": (
        "Signed corrected-MW differences by stock-boundary segment sum to the finished gap. "
        "When some segments are negative, a larger positive segment is an offset. It is not a percentage of the gap."
    ),
    "solved_terminal": (
        "A shared exact state that is solved is recorded separately from strategic reconvergence. "
        "It is the empty completed tableau."
    ),
    "undo": "Canonical analysis does not read Play Lab sessions and does not call undo.",
}


class ForensicError(Exception):
    """Validation failed. Comparison must not continue on this input."""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.details = details or {}


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_solution_file(
    deal_path: Path,
    moves_path: Path,
    *,
    expected_mw: Optional[int] = None,
    require_solved: bool = True,
) -> dict:
    """Replay from the deal file. Caller metrics are not trusted."""

    deal_path = Path(deal_path)
    moves_path = Path(moves_path)
    if not deal_path.is_file():
        raise ForensicError(f"deal file not found: {deal_path}")
    if not moves_path.is_file():
        raise ForensicError(f"solution file not found: {moves_path}")
    try:
        actions = parse_moves_file(moves_path)
    except ValueError as exc:
        raise ForensicError(f"could not parse {moves_path}: {exc}") from exc
    try:
        cards = list(load_deal(deal_path))
        state = SpiderState.from_cards(cards)
        counters = replay_actions_detailed(state, actions)
    except Exception as exc:
        raise ForensicError(f"replay failed for {moves_path}: {exc}") from exc
    result = {
        "deal_path": str(deal_path),
        "moves_path": str(moves_path),
        "deal_sha256": _file_sha256(deal_path),
        "moves_sha256": _file_sha256(moves_path),
        "solved": bool(state.is_solved()),
        "foundations": len(state.foundations),
        "stock_remaining": len(state.stock),
        "tableau_empty": all(column.is_empty() for column in state.columns),
        "mobilityware_moves": int(counters["mobilityware_moves"]),
        "legacy_mw": int(counters["legacy_mw"]),
        "explicit_commands": int(counters["explicit_commands"]),
        "tableau_moves": int(counters["tableau_moves"]),
        "stock_deals": int(counters["stock_deals"]),
        "automatic_foundation_removals": int(counters["automatic_foundation_removals"]),
        "actions": len(actions),
    }
    if require_solved and not result["solved"]:
        raise ForensicError(
            f"{moves_path} is not a complete solution: solved={result['solved']} "
            f"foundations={result['foundations']} stock_remaining={result['stock_remaining']}",
            result,
        )
    if require_solved and (result["foundations"] != 8 or result["stock_remaining"] != 0):
        raise ForensicError(
            f"{moves_path} failed completion checks: foundations={result['foundations']} "
            f"stock_remaining={result['stock_remaining']}",
            result,
        )
    if expected_mw is not None and result["mobilityware_moves"] != int(expected_mw):
        raise ForensicError(
            f"{moves_path} corrected MW is {result['mobilityware_moves']}, expected {expected_mw}. "
            "Forensic comparison stopped.",
            result,
        )
    return result


def analyze_solution(
    deal_path: Path,
    moves_path: Path,
    *,
    label: str,
    expected_mw: Optional[int] = None,
    focus_column: Optional[int] = None,
    require_solved: bool = True,
    actions: Optional[Sequence] = None,
    opening_cards: Optional[Sequence] = None,
    opening_state: Optional[SpiderState] = None,
) -> dict:
    """Validate, unless a fixture passes cards and actions directly, then instrument."""

    deal_path = Path(deal_path) if deal_path is not None else None
    validation = None
    if actions is None:
        validation = validate_solution_file(
            deal_path,
            moves_path,
            expected_mw=expected_mw,
            require_solved=require_solved,
        )
        cards = list(load_deal(deal_path))
        opening = SpiderState.from_cards(cards)
        parsed = parse_moves_file(Path(moves_path))
    else:
        if opening_cards is None or opening_state is None:
            raise ForensicError("fixture analysis requires opening_cards and opening_state")
        cards = list(opening_cards)
        opening = opening_state
        parsed = list(actions)
    try:
        trajectory = replay_trajectory(
            opening,
            cards,
            parsed,
            label=label,
            focus_column=focus_column,
            require_solved=require_solved,
        )
    except ForensicIntegrityError as exc:
        raise ForensicError(str(exc)) from exc
    parks = build_parks(trajectory)
    workspace = build_workspace(trajectory)
    trajectory["parks"] = parks
    trajectory["park_summary"] = park_summary(parks)
    trajectory["workspace_episodes"] = workspace
    trajectory["workspace_summary"] = workspace_summary(workspace)
    trajectory["backward_attributions"] = backward_attributions(trajectory, parks)
    trajectory["validation"] = validation
    trajectory["actions"] = [
        ["deal"] if action == ("deal",) else [int(action[0]), int(action[1]), int(action[2])]
        for action in parsed
    ]
    return trajectory


def compare_solutions(
    deal_path: Path,
    moves_a: Path,
    moves_b: Path,
    *,
    label_a: str,
    label_b: str,
    expected_a: Optional[int] = None,
    expected_b: Optional[int] = None,
    focus_column: Optional[int] = None,
    role_a: str = "reference",
    role_b: str = "machine",
    seed_limit: int = 8,
    require_solved: bool = True,
) -> dict:
    """Validate both routes before either forensic comparison is built."""

    validation_a = validate_solution_file(
        deal_path, moves_a, expected_mw=expected_a, require_solved=require_solved
    )
    validation_b = validate_solution_file(
        deal_path, moves_b, expected_mw=expected_b, require_solved=require_solved
    )
    route_a = analyze_solution(
        deal_path,
        moves_a,
        label=label_a,
        expected_mw=expected_a,
        focus_column=focus_column,
        require_solved=require_solved,
    )
    route_b = analyze_solution(
        deal_path,
        moves_b,
        label=label_b,
        expected_mw=expected_b,
        focus_column=focus_column,
        require_solved=require_solved,
    )
    seeds = counterfactual_seeds(
        deal_path,
        [_restore(action) for action in route_b["actions"]],
        route_b,
        route_b["backward_attributions"],
        focus_column=focus_column,
        limit=seed_limit,
    )
    route_b.pop("_seed_reasons", None)
    route_a.pop("_seed_reasons", None)
    findings = build_findings(
        route_a,
        route_b,
        label_a=label_a,
        label_b=label_b,
        role_a=role_a,
        role_b=role_b,
        focus_column=focus_column,
        attributions_b=route_b["backward_attributions"],
        seeds_b=seeds,
    )
    return {
        "schema": SCHEMA_VERSION,
        "schema_notes": SCHEMA_NOTES,
        "metadata": {
            "deal_path": str(deal_path),
            "focus_column": focus_column,
            "role_a": role_a,
            "role_b": role_b,
            "label_a": label_a,
            "label_b": label_b,
            "seed_limit": seed_limit,
        },
        "validation": {"a": validation_a, "b": validation_b},
        "trajectories": {"a": route_a, "b": route_b},
        "comparison": {
            "phase_gaps": phase_gaps(route_a, route_b),
            "divergence": divergence(route_a, route_b),
            "counterfactual_seeds": seeds,
        },
        "findings": findings,
    }


def _restore(action):
    if action == ["deal"]:
        return ("deal",)
    return (int(action[0]), int(action[1]), int(action[2]))
