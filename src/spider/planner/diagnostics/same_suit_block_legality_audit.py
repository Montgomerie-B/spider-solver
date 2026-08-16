#!/usr/bin/env python3
"""Reproduce the same-suit block-legality audit for deal 4925153."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import Action, format_action, replay_actions
from spider.move_lifecycle import (
    MoveLifecycleAssessment,
    PlacementClass,
    assess_tableau_move,
)
from spider.planner.diagnostics.experiment_4925153_opt011_cmd43_51_corridor import (
    build_corridor_endpoints,
)
from spider.planner.diagnostics.opt012_compact_search import search_quotient
from spider.planner.diagnostics.opt012_free_quotient import (
    free_closure,
    free_slot_analysis,
)
from spider.planner.foundation_campaign import analyze_foundation_campaigns
from spider.planner.foundation_campaign_realizer import realize_campaign_to_next_epoch
from spider.planner.foundation_campaign_removal import locate_campaign_bands
from spider.solution_archive import ValidationResult, validate_solution


ROOT = Path(__file__).resolve().parents[4]
DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"

# Published diagnostic route, captured before correcting engine legality. It is
# audit evidence only and is never consumed by generic strategy.
PUBLISHED_MACHINE_ROUTE: Tuple[Action, ...] = (
    (5, 7, 1),
    (5, 2, 1),
    (5, 2, 1),
    (5, 1, 1),
    (5, 4, 1),
    (2, 7, 3),
    (6, 8, 1),
    (6, 5, 1),
    (9, 8, 1),
    (5, 9, 1),
    ("deal",),
    (6, 0, 2),
    (6, 7, 1),
    (7, 6, 2),
    (2, 9, 1),
    (0, 2, 3),
    (8, 2, 1),
    (2, 3, 5),
    ("deal",),
    (7, 9, 1),
    (7, 3, 5),
    (1, 3, 1),
    (3, 0, 12),
    (8, 3, 1),
    (6, 0, 1),
    (8, 9, 3),
    (6, 8, 2),
    (6, 1, 1),
    (3, 6, 2),
    (3, 1, 1),
    (3, 1, 1),
    (9, 6, 5),
    (9, 8, 2),
    (1, 9, 4),
    (9, 1, 6),
    (9, 1, 1),
    (0, 9, 2),
    (7, 0, 1),
    (5, 7, 1),
    (5, 6, 1),
    (7, 5, 2),
    (7, 1, 1),
    (9, 7, 1),
    (9, 0, 2),
    (9, 0, 1),
    (6, 9, 6),
    (0, 9, 5),
    (9, 6, 11),
    (1, 9, 10),
)

MACHINE_PREFIXES = (
    ("A committed opening", 5),
    ("B opening plus consolidation", 6),
    ("C through Deal 1", 11),
    ("D S-foundation route", 23),
    ("E residual route", 47),
    ("F source-project partial", 49),
)


@dataclass(frozen=True)
class PrefixAudit:
    label: str
    commands: int
    valid: bool
    corrected_cost: int
    first_illegal_command: Optional[int]
    first_illegal_action: Optional[Action]
    cards_moved: Tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class QueenAudit:
    label: str
    legal: bool
    immediate_added_cost: int
    projected_lifecycle_cost: float
    empty_columns: Tuple[int, ...]
    spade_bands: Tuple[str, ...]
    placement_records: Tuple[str, ...]
    same_suit_joins_created: Tuple[str, ...]
    same_suit_joins_broken: Tuple[str, ...]
    mixed_suit_boundaries_created: Tuple[str, ...]
    mixed_suit_boundaries_removed: Tuple[str, ...]
    park_exit_routes: Tuple[str, ...]
    estimated_rehandling_cost: float
    override_reasons: Tuple[str, ...]
    s1_target_epoch: Optional[int]
    s1_readiness: str
    s1_must: Tuple[str, ...]
    receiver_requirements: Tuple[str, ...]
    realizer_status: str
    realizer_added_cost: Optional[int]
    realizer_nodes: int
    realizer_replay_verified: bool
    realizer_actions: Tuple[Action, ...]

    @property
    def added_cost(self) -> int:
        """Backward-compatible name; this is immediate cost only."""
        return self.immediate_added_cost


def audit_prefix(
    cards: Sequence[Card], label: str, commands: int
) -> PrefixAudit:
    state = SpiderState.from_cards(list(cards))
    cost = 0
    for command, action in enumerate(PUBLISHED_MACHINE_ROUTE[:commands], 1):
        moved: Tuple[str, ...] = ()
        if action != ("deal",):
            src, _dst, k = action
            moved = tuple(str(card) for card in state.columns[src].face_up[-k:])
        try:
            cost += replay_actions(state, [action])
        except ValueError as exc:
            if len(moved) > 1 and not state.is_same_suit(
                state.columns[action[0]].face_up[-action[2]:]  # type: ignore[index]
            ):
                reason = "descending multi-card block contains a suit break"
            else:
                reason = str(exc)
            return PrefixAudit(
                label,
                commands,
                False,
                cost,
                command,
                action,
                moved,
                reason,
            )
    return PrefixAudit(label, commands, True, cost, None, None, (), "legal")


def audit_machine_prefixes(cards: Sequence[Card]) -> Tuple[PrefixAudit, ...]:
    return tuple(
        audit_prefix(cards, label, commands)
        for label, commands in MACHINE_PREFIXES
    )


def _spade_structure(state: SpiderState) -> Tuple[str, ...]:
    return tuple(band.label for band in locate_campaign_bands(state, "s"))


def audit_queen_variant(
    cards: Sequence[Card], label: str, actions: Sequence[Action]
) -> QueenAudit:
    state = SpiderState.from_cards(list(cards))
    replay_actions(state, list(PUBLISHED_MACHINE_ROUTE[:3]))
    legal = True
    added = 0
    placements: list[MoveLifecycleAssessment] = []
    for action in actions:
        if action == ("deal",):
            raise ValueError("Queen diagnostic accepts tableau moves only")
        src, dst, k = action
        moved = state.columns[src].face_up[-k]
        dest = state.columns[dst].top()
        exit_route = None
        exit_bounded = None
        if dest is not None and dest.suit != moved.suit:
            if str(moved) == "Qs":
                exit_route = (
                    "move the Qs campaign band onto the exact incoming Deal-2 "
                    "Ks on c1"
                )
                exit_bounded = True
            elif str(moved) == "Qc":
                exit_route = (
                    "after Qs exits Kc for the incoming Deal-2 Ks, move Qc "
                    "onto the exposed Kc"
                )
                exit_bounded = True
        try:
            assessment = assess_tableau_move(
                state,
                action,
                future_exit_route=exit_route,
                exit_route_bounded=exit_bounded,
            )
            placements.append(assessment)
            added += replay_actions(state, [action])
        except ValueError:
            legal = False
            break
    portfolio = analyze_foundation_campaigns(state, cards=cards)
    campaign = portfolio.campaign_for("s", 1)
    epoch1 = next(plan for plan in campaign.stock_plan if plan.epoch == 1)
    realized = realize_campaign_to_next_epoch(
        state,
        campaign,
        cards,
        max_added_cost=6,
        max_nodes=50_000,
        time_limit_s=20,
    )
    debt = sum(item.estimated_rehandling_cost for item in placements)
    realized_cost = float(realized.corrected_added_cost or 0)
    records = tuple(
        f"{format_action(item.action)}={item.placement_class.value} "
        f"immediate={item.immediate_cost} debt~{item.estimated_rehandling_cost:g}"
        for item in placements
    )
    return QueenAudit(
        label,
        legal,
        added,
        float(added) + realized_cost + debt,
        tuple(
            index + 1
            for index, column in enumerate(state.columns)
            if column.is_empty()
        ),
        _spade_structure(state),
        records,
        tuple(
            event
            for item in placements
            for event in item.same_suit_joins_created
        ),
        tuple(
            event
            for item in placements
            for event in item.same_suit_joins_broken
        ),
        tuple(
            event
            for item in placements
            for event in item.mixed_suit_boundaries_created
        ),
        tuple(
            event
            for item in placements
            for event in item.mixed_suit_boundaries_removed
        ),
        tuple(
            f"{item.placement_class.value}: {item.future_exit_route}"
            for item in placements
            if item.placement_class
            in (PlacementClass.MIXED_SUIT_PARK, PlacementClass.WORKSPACE_PARK)
        ),
        debt,
        tuple(
            item.compensating_benefit.override_reason
            for item in placements
            if item.compensating_benefit is not None
            and item.can_override_permanent_join
        ),
        campaign.target_removal_epoch,
        campaign.readiness.value,
        tuple(str(source.card) for source in campaign.tableau_critical_cards),
        epoch1.receiver_requirements,
        realized.status.value,
        realized.corrected_added_cost,
        realized.nodes_expanded,
        realized.independent_replay_verified,
        realized.actions,
    )


def audit_queen_variants(cards: Sequence[Card]) -> Tuple[QueenAudit, QueenAudit]:
    consolidate = (2, 7, 3)
    return (
        audit_queen_variant(
            cards,
            "A Qc->Kd; Qs->Kc",
            ((5, 1, 1), (5, 4, 1), consolidate),
        ),
        audit_queen_variant(
            cards,
            "B Qc->Kc; Qs->Kd",
            ((5, 4, 1), (5, 1, 1), consolidate),
        ),
    )


def print_canonical(result: ValidationResult) -> None:
    print("CANONICAL HUMAN ROUTE")
    print(
        f"valid={result.valid} solved={result.solved} "
        f"cost={result.mobilityware_moves} commands={result.explicit_commands} "
        f"tableau={result.tableau_moves} deals={result.stock_deals} "
        f"foundations={result.foundations} stock={result.stock_remaining} "
        f"path_hash={result.path_hash} state_hash={result.state_hash}"
    )


def main() -> int:
    started = time.perf_counter()
    cards = tuple(load_deal(DEAL))
    canonical = validate_solution("4925153", CANONICAL)
    print_canonical(canonical)

    print()
    print("PUBLISHED MACHINE PREFIXES")
    for result in audit_machine_prefixes(cards):
        failure = (
            "none"
            if result.valid
            else (
                f"command={result.first_illegal_command} "
                f"action={format_action(result.first_illegal_action)} "
                f"cards={result.cards_moved} reason={result.reason}"
            )
        )
        print(
            f"{result.label}: valid={result.valid} "
            f"cost_to_stop={result.corrected_cost} failure={failure}"
        )

    print()
    print("QUEEN-PLACEMENT A/B")
    for result in audit_queen_variants(cards):
        print(
            f"{result.label}: legal={result.legal} "
            f"immediate_added={result.immediate_added_cost} "
            f"projected_lifecycle={result.projected_lifecycle_cost:g} "
            f"rehandling_debt~{result.estimated_rehandling_cost:g} "
            f"empties={result.empty_columns} spade_bands={result.spade_bands}"
        )
        print(f"  placements={result.placement_records}")
        print(
            f"  joins+={result.same_suit_joins_created} "
            f"joins-={result.same_suit_joins_broken} "
            f"mixed+={result.mixed_suit_boundaries_created} "
            f"mixed-={result.mixed_suit_boundaries_removed}"
        )
        print(f"  park exits={result.park_exit_routes}")
        print(f"  permanent-join overrides={result.override_reasons or ('none',)}")
        print(
            f"  S1 target=D{result.s1_target_epoch} "
            f"readiness={result.s1_readiness} MUST={result.s1_must}"
        )
        print(f"  Deal1 receivers={result.receiver_requirements}")
        print(
            f"  realizer={result.realizer_status} "
            f"added={result.realizer_added_cost} nodes={result.realizer_nodes} "
            f"replay={result.realizer_replay_verified} "
            f"actions={tuple(format_action(a) for a in result.realizer_actions)}"
        )

    print()
    print("CORRECTED FREE-QUOTIENT AUDIT")
    start = build_corridor_endpoints()["start_state"]
    analysis = free_slot_analysis(start)
    print(
        f"start_free_slots={analysis['n_slots']} "
        f"free_piles={analysis['n_piles']} empties={analysis['n_empty']} "
        f"free_closure={len(free_closure(start))}"
    )
    for mode in ("algebraic", "bruteforce"):
        result = search_quotient(ceiling=7, expand_mode=mode)
        print(
            f"{mode}: termination={result.termination} status={result.status} "
            f"components={result.tt_entries} raw={result.generated_raw} "
            f"runtime={result.runtime_seconds:.3f}s "
            f"improvements={result.improvements}"
        )

    print(f"total_runtime={time.perf_counter() - started:.3f}s")
    return 0 if canonical.valid and canonical.solved else 1


if __name__ == "__main__":
    raise SystemExit(main())
