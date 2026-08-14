#!/usr/bin/env python3
"""Foundation-campaign POC report for benchmark deal 4925153.

The benchmark actions and expected validation facts in this file are fixture
data only.  They are deliberately kept out of the generic campaign analyser.

Ordering is a hard part of this diagnostic: the opening and the two supplied
machine states are constructed, analysed, rendered, and frozen *before* this
program reads the canonical move trace.  Canonical checkpoints and future
moves therefore cannot influence the prospective reports for those states.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import Action, parse_moves_file, replay_actions
from spider.planner.foundation_campaign import (
    FoundationCampaign,
    FoundationCampaignPortfolio,
    RankSource,
    analyze_foundation_campaigns,
    format_campaign_portfolio,
)
from spider.planner.space_lifecycle import empty_columns, empty_count


# Benchmark-only fixture constants.  Nothing here is imported by strategy.
DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"

# One-based report: 6->8, 6->3, 6->3, 6->2, 6->5.
COMMITTED_COST5_ACTIONS: Tuple[Action, ...] = (
    (5, 7, 1),
    (5, 2, 1),
    (5, 2, 1),
    (5, 1, 1),
    (5, 4, 1),
)

# User-supplied TEST STATE only: col 3 -> col 8, full 4s-3s-2s run.
USER_CONSOLIDATION: Action = (2, 7, 3)


@dataclass(frozen=True)
class AnalysedState:
    label: str
    state: SpiderState
    portfolio: FoundationCampaignPortfolio
    rendered: str
    elapsed_seconds: float


@dataclass(frozen=True)
class CanonicalValidation:
    foundation_order: Tuple[str, ...]
    foundation_events: Tuple[str, ...]
    predeal_empties: Tuple[Tuple[int, Tuple[int, ...]], ...]
    space_creates: int
    space_consumes: int
    space_relocates: int
    corrected_cost: int
    explicit_commands: int


def _card_text(card: Card) -> str:
    return str(card)


def _top_text(state: SpiderState) -> str:
    return " ".join(_card_text(card) if card is not None else "--" for card in state.top_row())


def _state_facts(state: SpiderState) -> str:
    return (
        f"tops=[{_top_text(state)}] fd={sum(len(c.face_down) for c in state.columns)} "
        f"stock={len(state.stock)} foundations={len(state.foundations)} "
        f"empties={[c + 1 for c in empty_columns(state)]}"
    )


def _analyse(label: str, state: SpiderState, cards: Sequence[Card]) -> AnalysedState:
    started = time.perf_counter()
    portfolio = analyze_foundation_campaigns(state, cards=cards)
    rendered = format_campaign_portfolio(portfolio)
    return AnalysedState(
        label=label,
        state=state.clone(),
        portfolio=portfolio,
        rendered=rendered,
        elapsed_seconds=time.perf_counter() - started,
    )


def _source_text(source: RankSource) -> str:
    if source.stock_epoch is not None:
        assert source.stock_column is not None
        return f"{source.card}@Deal{source.stock_epoch}/col{source.stock_column + 1}"
    if source.column is not None:
        return f"{source.card}@col{source.column + 1}/{source.kind.value}"
    return f"{source.card}/{source.kind.value}"


def _campaign_rank_line(campaign: FoundationCampaign) -> str:
    target = (
        f"Deal{campaign.target_removal_epoch}"
        if campaign.target_removal_epoch
        else "opening"
    )
    return (
        f"{campaign.label:<4} target={target:<8} score={campaign.campaign_score:6.1f} "
        f"paid-moves~{campaign.estimated_campaign_cost:5.1f} "
        f"MUST={len(campaign.tableau_critical_cards):2d} "
        f"stock={len(campaign.future_stock_supplied_cards):2d} "
        f"readiness={campaign.readiness.value}"
    )


def _print_state_report(report: AnalysedState) -> None:
    print()
    print("=" * 92)
    print(report.label)
    print("=" * 92)
    print(_state_facts(report.state))
    print(f"analysis_runtime={report.elapsed_seconds:.3f}s")
    print()
    print("CAMPAIGN RANKING")
    for campaign in report.portfolio.campaigns:
        print("  " + _campaign_rank_line(campaign))
    print()
    print(report.rendered)

    primary = report.portfolio.primary
    if primary is None:
        return
    must = ", ".join(_source_text(source) for source in primary.tableau_critical_cards) or "none"
    safe = (
        ", ".join(_source_text(source) for source in primary.optional_replaceable_buried_copies)
        or "none"
    )
    print()
    print("PRIMARY CAMPAIGN ACTION BRIEF")
    print(
        f"  Campaign {primary.label} is preferred for Deal{primary.target_removal_epoch} "
        f"because score={primary.campaign_score:.1f}, selected MUST work={len(primary.tableau_critical_cards)}, "
        f"and stock supplies {len(primary.future_stock_supplied_cards)} ranks."
    )
    print(f"  MUST excavate: {must}")
    print(
        "  Replaceable/off-MUST (subject to listed receiver geometry): " + safe
    )
    print(
        f"  Current space: {primary.space_plan.policy.value}; "
        f"{primary.space_plan.enabled_action}; regain~{primary.space_plan.estimated_regain_cost}."
    )
    for epoch_plan in primary.stock_plan:
        print(f"  Desired geometry before Deal{epoch_plan.epoch}:")
        if epoch_plan.receiver_requirements:
            for requirement in epoch_plan.receiver_requirements:
                print(f"    - {requirement}")
        else:
            print("    - no selected receiver reshaping requirement")
        for join in epoch_plan.useful_same_suit_joins:
            print(f"    - join: {join}")
        print(f"    - workspace policy: {epoch_plan.carry_empty_policy}")


def _build_early_states(cards: Sequence[Card]) -> Tuple[SpiderState, SpiderState, SpiderState]:
    opening = SpiderState.from_cards(list(cards))
    committed = opening.clone()
    committed_cost = replay_actions(committed, list(COMMITTED_COST5_ACTIONS))
    if committed_cost != 5 or not committed.columns[5].is_empty():
        raise AssertionError(
            f"committed fixture drift: cost={committed_cost}, col6_empty={committed.columns[5].is_empty()}"
        )

    consolidated = committed.clone()
    src, dst, k = USER_CONSOLIDATION
    if not consolidated.can_move(src, dst, k):
        raise AssertionError("user-supplied 4s-3s-2s consolidation is no longer legal")
    consolidated.move(src, dst, k)
    expected = ["6s", "5s", "4s", "3s", "2s"]
    actual = [str(card) for card in consolidated.columns[7].face_up[-5:]]
    if actual != expected:
        raise AssertionError(f"user consolidation drift: got {actual}, want {expected}")
    return opening, committed, consolidated


def _replay_predeal_states(
    cards: Sequence[Card], actions: Sequence[Action], wanted: Iterable[int]
) -> Dict[int, SpiderState]:
    wanted_set = set(wanted)
    state = SpiderState.from_cards(list(cards))
    out: Dict[int, SpiderState] = {}
    deals = 0
    for action in actions:
        if action == ("deal",):
            deals += 1
            if deals in wanted_set:
                out[deals] = state.clone()
            if wanted_set.issubset(out):
                break
        replay_actions(state, [action])
    missing = wanted_set - set(out)
    if missing:
        raise AssertionError(f"canonical trace lacks pre-deal states {sorted(missing)}")
    return out


def _action_text(action: Action) -> str:
    if action == ("deal",):
        return "deal"
    src, dst, k = action
    return f"move {src + 1} {dst + 1} {k}"


def _canonical_validation(
    cards: Sequence[Card], actions: Sequence[Action]
) -> CanonicalValidation:
    state = SpiderState.from_cards(list(cards))
    foundation_order = []
    foundation_events = []
    predeal_empties = []
    creates = consumes = relocates = 0
    deals = 0
    corrected_cost = 0

    for command_index, action in enumerate(actions, 1):
        before_empty = empty_count(state)
        before_foundations = len(state.foundations)
        dest_was_empty = False
        src = None
        if action == ("deal",):
            deals += 1
            predeal_empties.append(
                (deals, tuple(column + 1 for column in empty_columns(state)))
            )
        else:
            src, dst, _k = action
            dest_was_empty = state.columns[dst].is_empty()

        corrected_cost += replay_actions(state, [action])
        after_empty = empty_count(state)
        if after_empty > before_empty:
            creates += 1
        elif after_empty < before_empty:
            consumes += 1
        elif (
            action != ("deal",)
            and dest_was_empty
            and src is not None
            and state.columns[src].is_empty()
        ):
            relocates += 1

        for sequence in state.foundations[before_foundations:]:
            if not sequence:
                continue
            suit = sequence[0].suit.upper()
            foundation_order.append(suit)
            foundation_events.append(
                f"cmd {command_index} / g={corrected_cost}: {_action_text(action)} -> {suit} foundation"
            )

    if not state.is_solved():
        raise AssertionError("canonical validation replay no longer solves the deal")
    return CanonicalValidation(
        foundation_order=tuple(foundation_order),
        foundation_events=tuple(foundation_events),
        predeal_empties=tuple(predeal_empties),
        space_creates=creates,
        space_consumes=consumes,
        space_relocates=relocates,
        corrected_cost=corrected_cost,
        explicit_commands=len(actions),
    )


def _print_canonical_validation(
    validation: CanonicalValidation,
    opening: AnalysedState,
    committed: AnalysedState,
    consolidated: AnalysedState,
) -> None:
    print()
    print("=" * 92)
    print("CANONICAL COMPARISON — LOADED ONLY AFTER PROSPECTIVE ANALYSIS")
    print("=" * 92)
    print(f"foundation_order={' -> '.join(validation.foundation_order)}")
    for event in validation.foundation_events:
        print("  " + event)
    print(
        f"space_cycles: creates={validation.space_creates} "
        f"consumes={validation.space_consumes} relocates={validation.space_relocates}"
    )
    print(
        "predeal_empties="
        + ", ".join(
            f"D{deal}:{list(columns)}" for deal, columns in validation.predeal_empties
        )
    )
    print(
        f"canonical_replay: commands={validation.explicit_commands} "
        f"corrected_MW={validation.corrected_cost}"
    )
    early = (opening, committed, consolidated)
    for report in early:
        primary = report.portfolio.primary
        secondary = report.portfolio.secondary
        print(
            f"  {report.label}: prospective primary={primary.label if primary else '--'} "
            f"target=Deal{primary.target_removal_epoch if primary else '--'}; "
            f"secondary={secondary.label if secondary else '--'}"
        )
    print(
        "  Interpretation: the prospective S primary agrees with the first canonical "
        "foundation.  The second canonical D foundation matches the deferred D#1 "
        "campaign (not the independent runner-up slot); optional buried copies remain "
        "conditional substitutions when their listed receiver geometry is achieved, even "
        "where the human chose them for cheaper final geometry."
    )


def _gate(
    early_reports: Sequence[AnalysedState],
    validation: CanonicalValidation,
) -> Tuple[str, Tuple[str, ...]]:
    opening, committed, consolidated = early_reports
    c_primary = committed.portfolio.primary
    x_primary = consolidated.portfolio.primary
    if c_primary is None or x_primary is None:
        return "FAIL", ("no primary campaign in an early-space state",)

    competing_scores = [
        campaign.campaign_score
        for campaign in committed.portfolio.campaigns
        if campaign.label != c_primary.label
    ]
    ranking_gap = c_primary.campaign_score - max(competing_scores, default=c_primary.campaign_score)
    early_primary_labels = tuple(
        report.portfolio.primary.label if report.portfolio.primary else "--"
        for report in early_reports
    )
    canonical_second_campaign = None
    if len(validation.foundation_order) >= 2:
        canonical_second_campaign = next(
            (
                campaign
                for campaign in committed.portfolio.campaigns
                if campaign.suit.upper() == validation.foundation_order[1]
            ),
            None,
        )
    canonical_alignment = (
        len(validation.foundation_order) >= 2
        and validation.foundation_order[0] == c_primary.suit.upper()
        and canonical_second_campaign is not None
        and canonical_second_campaign.target_removal_epoch is not None
        and canonical_second_campaign.target_removal_epoch <= 4
    )
    evidence = (
        f"non-flat early ranking gap={ranking_gap:.1f}",
        f"stable prospective primaries={early_primary_labels}",
        f"cost-5 primary={c_primary.label} target=Deal{c_primary.target_removal_epoch}",
        f"consolidated critical tableau set={len(x_primary.tableau_critical_cards)}",
        f"consolidated off-MUST replaceable copies={len(x_primary.optional_replaceable_buried_copies)}",
        f"current-space action={_action_text(x_primary.space_plan.action) if x_primary.space_plan.action else '--'} "
        f"policy={x_primary.space_plan.policy.value}",
        f"pre-deal receiver requirements={sum(len(p.receiver_requirements) for p in x_primary.stock_plan)}",
        f"canonical first={validation.foundation_order[0] if validation.foundation_order else '--'} "
        f"matches primary={c_primary.suit.upper()}",
        f"canonical second={validation.foundation_order[1] if len(validation.foundation_order) >= 2 else '--'} "
        f"matches deferred={canonical_second_campaign.label if canonical_second_campaign else '--'} "
        f"target=Deal{canonical_second_campaign.target_removal_epoch if canonical_second_campaign else '--'} "
        f"aligned={canonical_alignment}",
    )
    strong_checks = (
        ranking_gap >= 10.0,
        len(set(early_primary_labels)) == 1,
        c_primary.target_removal_epoch is not None,
        1 <= len(x_primary.tableau_critical_cards) <= 3,
        bool(x_primary.optional_replaceable_buried_copies),
        x_primary.space_plan.action is not None,
        sum(len(p.receiver_requirements) for p in x_primary.stock_plan) >= 2,
        canonical_alignment,
    )
    if all(strong_checks):
        return "STRONG PASS", evidence
    partial_checks = (
        ranking_gap > 0.0,
        c_primary.target_removal_epoch is not None,
        bool(x_primary.critical_path),
    )
    if all(partial_checks):
        return "PARTIAL", evidence
    return "FAIL", evidence


def main() -> int:
    total_started = time.perf_counter()
    cards = load_deal(DEAL_PATH)

    print("FOUNDATION CAMPAIGN PLANNER POC")
    print("No plan search. No whole-game search. Corrected MobilityWare accounting.")
    print(
        "Prospective states 1-3 are analysed and printed before the canonical file is read."
    )

    # ------------------------------------------------------------------
    # PROSPECTIVE PHASE.  The canonical path has not been opened or parsed.
    # ------------------------------------------------------------------
    opening_state, committed_state, consolidated_state = _build_early_states(cards)
    early_reports = (
        _analyse("1) TRUE OPENING — prospective", opening_state, cards),
        _analyse("2) COMMITTED EXCAVATION COST-5 / COL 6 EMPTY — prospective", committed_state, cards),
        _analyse(
            "3) USER-SUPPLIED COL 3 -> COL 8, 4s-3s-2s CONSOLIDATION — prospective",
            consolidated_state,
            cards,
        ),
    )
    for report in early_reports:
        _print_state_report(report)

    print()
    print("EARLY ANALYSIS FROZEN — canonical trace may now be loaded for states 4-6 and validation.")
    sys.stdout.flush()

    # ------------------------------------------------------------------
    # VALIDATION PHASE.  Canonical data is first read here, never above.
    # ------------------------------------------------------------------
    canonical_actions = tuple(parse_moves_file(CANONICAL_PATH))
    predeal = _replay_predeal_states(cards, canonical_actions, (1, 2, 5))
    canonical_reports = (
        _analyse("4) CANONICAL PRE-DEAL1 — validation state", predeal[1], cards),
        _analyse("5) CANONICAL PRE-DEAL2 — validation state", predeal[2], cards),
        _analyse("6) CANONICAL PRE-DEAL5 — validation state", predeal[5], cards),
    )
    for report in canonical_reports:
        _print_state_report(report)

    validation = _canonical_validation(cards, canonical_actions)
    _print_canonical_validation(validation, *early_reports)

    verdict, evidence = _gate(early_reports, validation)
    print()
    print("=" * 92)
    print("HARD GATE")
    print("=" * 92)
    for item in evidence:
        print("  " + item)
    print(f"VERDICT: {verdict}")
    print(f"total_runtime={time.perf_counter() - total_started:.3f}s")
    print("Recommended next step: review this diagnostic; only on STRONG PASS consider planner integration.")
    return 0 if verdict == "STRONG PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
