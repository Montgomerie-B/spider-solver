"""Ordering-only lifecycle tracking for campaign assets supplied by a Deal.

Campaign supply is an obligation attached to a named dependency, not to a
coordinate forever.  The tracker starts from the exact incoming row, follows
the delivered physical copy through later tableau actions, and accepts an
interchangeable copy only when the substitute is actually used for the same
rank dependency.  None of these records participate in exact state identity,
transposition dominance, or admissible proof pruning.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.metrics import Action
from spider.planner.foundation_campaign import FoundationCampaign, RankSource
from spider.rules import MW_RULES
from spider.state_identity import CanonicalStateKey, canonical_state_key


class SupplyConsumptionStage(str, Enum):
    PROMISED = "PROMISED"
    DELIVERED = "DELIVERED"
    AVAILABLE = "AVAILABLE"
    CONSUMED = "CONSUMED"
    INTEGRATED = "INTEGRATED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class CampaignSupplyObligation:
    obligation_id: str
    campaign_id: str
    card: Card
    deal_row: int
    destination_column: int
    promised_source_key: str
    dependency_key: str
    dependency_interval: Tuple[int, int]
    expected_receiver_rank: Optional[int]
    receiver_supply: bool = False
    interchangeable_copy_allowed: bool = True
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class CampaignSupplyEvidence:
    obligation_id: str
    stage: SupplyConsumptionStage
    delivered_source_key: Optional[str]
    active_source_key: Optional[str]
    current_column: Optional[int]
    current_face_up_index: Optional[int]
    substituted_source_key: Optional[str]
    consumption_action_index: Optional[int]
    consumed_as: Optional[str]
    direct_campaign_advance: bool
    reason: str
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class CampaignSupplyConsumption:
    obligation_id: str
    action_index: int
    action: Action
    source_key: str
    substituted: bool
    direct_campaign_advance: bool
    consequence: str
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class SupplyConsumptionResult:
    contract_id: str
    campaign_id: Optional[str]
    obligations: Tuple[CampaignSupplyObligation, ...]
    evidence: Tuple[CampaignSupplyEvidence, ...]
    consumptions: Tuple[CampaignSupplyConsumption, ...]
    evaluated_state_key: CanonicalStateKey
    foundations_before: int
    foundations_after: int
    reason: str
    proof_pruning_allowed: bool = False

    @property
    def highest_stage(self) -> SupplyConsumptionStage:
        ranks = {
            SupplyConsumptionStage.PROMISED: 0,
            SupplyConsumptionStage.DELIVERED: 1,
            SupplyConsumptionStage.AVAILABLE: 2,
            SupplyConsumptionStage.CONSUMED: 3,
            SupplyConsumptionStage.INTEGRATED: 4,
            SupplyConsumptionStage.INVALIDATED: -1,
            SupplyConsumptionStage.EXPIRED: -1,
        }
        if not self.evidence:
            return SupplyConsumptionStage.PROMISED
        return max((item.stage for item in self.evidence), key=ranks.__getitem__)

    @property
    def delivered_count(self) -> int:
        return sum(
            item.stage
            in (
                SupplyConsumptionStage.DELIVERED,
                SupplyConsumptionStage.AVAILABLE,
                SupplyConsumptionStage.CONSUMED,
                SupplyConsumptionStage.INTEGRATED,
            )
            for item in self.evidence
        )

    @property
    def consumed_count(self) -> int:
        return sum(
            item.stage
            in (SupplyConsumptionStage.CONSUMED, SupplyConsumptionStage.INTEGRATED)
            for item in self.evidence
        )

    @property
    def fully_consumed(self) -> bool:
        return bool(self.obligations) and self.consumed_count == len(self.obligations)

    @property
    def integrated_count(self) -> int:
        return sum(item.stage == SupplyConsumptionStage.INTEGRATED for item in self.evidence)


def _obligation_id(campaign_id: str, source_key: str, card: Card) -> str:
    payload = f"{campaign_id}|{source_key}|{card.suit}|{card.rank}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _next_epoch(state: SpiderState) -> int:
    return 5 - len(state.stock) // 10 + 1


def _selected_next_row_sources(
    campaign: FoundationCampaign,
    *,
    epoch: int,
) -> Tuple[RankSource, ...]:
    return tuple(
        need.chosen
        for need in campaign.rank_needs
        if need.chosen is not None
        and need.chosen.stock_epoch == epoch
        and need.chosen.stock_column is not None
    )


def derive_campaign_supply_obligations(
    state_before: SpiderState,
    exact_row: Sequence[Card],
    campaign: Optional[FoundationCampaign],
    *,
    campaign_id: Optional[str],
) -> Tuple[CampaignSupplyObligation, ...]:
    """Bind a named dependency to exact next-row provenance.

    If the fresh campaign exposes selected next-row sources, those exact
    source keys are used.  A conservative suit/rank fallback is retained for
    contract producers that know the campaign label but not its full object.
    """
    if campaign_id is None or not exact_row:
        return ()
    epoch = _next_epoch(state_before)
    selected = _selected_next_row_sources(campaign, epoch=epoch) if campaign else ()
    selected_by_column = {
        int(source.stock_column): source
        for source in selected
        if source.stock_column is not None
    }
    suit = campaign.suit if campaign is not None else campaign_id.split("#", 1)[0].lower()
    out = []
    for column, card in enumerate(exact_row):
        source = selected_by_column.get(column)
        if source is None:
            if card.suit != suit:
                continue
            source_key = f"stock:{epoch}:{column}"
        else:
            if source.card != card:
                continue
            source_key = source.source_key
        receiver_rank = card.rank + 1 if card.rank < 13 else None
        out.append(
            CampaignSupplyObligation(
                obligation_id=_obligation_id(campaign_id, source_key, card),
                campaign_id=campaign_id,
                card=card,
                deal_row=epoch,
                destination_column=column,
                promised_source_key=source_key,
                dependency_key=f"rank:{card.rank}:{suit}",
                dependency_interval=(card.rank, card.rank),
                expected_receiver_rank=receiver_rank,
            )
        )
    return tuple(out)


def promised_supply_result(
    contract_id: str,
    campaign_id: Optional[str],
    obligations: Sequence[CampaignSupplyObligation],
    state: SpiderState,
) -> SupplyConsumptionResult:
    evidence = tuple(
        CampaignSupplyEvidence(
            obligation_id=item.obligation_id,
            stage=SupplyConsumptionStage.PROMISED,
            delivered_source_key=None,
            active_source_key=None,
            current_column=None,
            current_face_up_index=None,
            substituted_source_key=None,
            consumption_action_index=None,
            consumed_as=None,
            direct_campaign_advance=False,
            reason="exact campaign asset promised by the purpose-bearing Deal",
        )
        for item in obligations
    )
    return SupplyConsumptionResult(
        contract_id=contract_id,
        campaign_id=campaign_id,
        obligations=tuple(obligations),
        evidence=evidence,
        consumptions=(),
        evaluated_state_key=canonical_state_key(state),
        foundations_before=len(state.foundations),
        foundations_after=len(state.foundations),
        reason="supply assets promised but not yet delivered",
    )


def _is_available(state: SpiderState, column: Optional[int], index: Optional[int]) -> bool:
    if column is None or index is None or not 0 <= column < len(state.columns):
        return False
    up = state.columns[column].face_up
    if not 0 <= index < len(up):
        return False
    if index == len(up) - 1:
        return True
    return SpiderState.is_movable_run(up[index:])


def _find_matching_face_up(
    state: SpiderState,
    card: Card,
    *,
    preferred_column: Optional[int] = None,
) -> Optional[Tuple[int, int]]:
    ordered = list(range(len(state.columns)))
    if preferred_column is not None and preferred_column in ordered:
        ordered.remove(preferred_column)
        ordered.insert(0, preferred_column)
    candidates = []
    for column in ordered:
        for index, current in enumerate(state.columns[column].face_up):
            if current == card:
                candidates.append((not _is_available(state, column, index), column, -index, index))
    if not candidates:
        return None
    _blocked, column, _reverse_index, index = min(candidates)
    return column, index


def _set_delivery(
    result: SupplyConsumptionResult,
    state: SpiderState,
) -> SupplyConsumptionResult:
    evidence = []
    for obligation, current in zip(result.obligations, result.evidence):
        column = obligation.destination_column
        up = state.columns[column].face_up if 0 <= column < len(state.columns) else []
        index = len(up) - 1 if up and up[-1] == obligation.card else None
        if index is None:
            found = _find_matching_face_up(state, obligation.card, preferred_column=column)
            if found is None:
                evidence.append(current)
                continue
            column, index = found
        available = _is_available(state, column, index)
        evidence.append(
            replace(
                current,
                stage=(
                    SupplyConsumptionStage.AVAILABLE
                    if available
                    else SupplyConsumptionStage.DELIVERED
                ),
                delivered_source_key=obligation.promised_source_key,
                active_source_key=obligation.promised_source_key,
                current_column=column,
                current_face_up_index=index,
                reason=(
                    "exact supplied asset is actionable for its named dependency"
                    if available
                    else "exact supplied asset arrived but is not currently actionable"
                ),
            )
        )
    return replace(
        result,
        evidence=tuple(evidence),
        evaluated_state_key=canonical_state_key(state),
        foundations_after=len(state.foundations),
        reason="exact incoming assets observed; delivery alone is not consumption",
    )


def _matching_obligation(
    obligations: Sequence[CampaignSupplyObligation],
    card: Card,
) -> Iterable[Tuple[int, CampaignSupplyObligation]]:
    for index, obligation in enumerate(obligations):
        if obligation.card == card and obligation.interchangeable_copy_allowed:
            yield index, obligation


def advance_supply_consumption_results(
    start_state: SpiderState,
    actions: Sequence[Action],
    *,
    existing: Sequence[SupplyConsumptionResult] = (),
    new_contracts: Sequence[object] = (),
) -> Tuple[SupplyConsumptionResult, ...]:
    """Replay one strategic edge while carrying campaign supply provenance."""
    results = list(existing)
    probe = start_state.clone()
    foundations_before_edge = len(probe.foundations)
    contracts_by_parent = {}
    for contract in new_contracts:
        obligations = tuple(getattr(contract, "supply_obligations", ()))
        if not obligations:
            continue
        contracts_by_parent.setdefault(getattr(contract, "parent_state_key"), []).append(contract)

    for action_index, action in enumerate(actions):
        if action == ("deal",):
            parent = canonical_state_key(probe)
            probe.deal(MW_RULES)
            for contract in contracts_by_parent.get(parent, ()):
                result = promised_supply_result(
                    getattr(contract, "contract_id"),
                    getattr(contract, "campaign_id", None),
                    getattr(contract, "supply_obligations", ()),
                    probe,
                )
                results.append(_set_delivery(result, probe))
            # Existing unconsumed cards remain physically in their columns but
            # may cease to be available after another row covers them.
            refreshed = []
            for result in results:
                ev = []
                for item in result.evidence:
                    if item.stage in (
                        SupplyConsumptionStage.CONSUMED,
                        SupplyConsumptionStage.INTEGRATED,
                        SupplyConsumptionStage.INVALIDATED,
                        SupplyConsumptionStage.EXPIRED,
                    ):
                        ev.append(item)
                        continue
                    stage = (
                        SupplyConsumptionStage.AVAILABLE
                        if _is_available(probe, item.current_column, item.current_face_up_index)
                        else SupplyConsumptionStage.DELIVERED
                    )
                    ev.append(replace(item, stage=stage))
                refreshed.append(replace(result, evidence=tuple(ev)))
            results = refreshed
            continue

        src, dst, count = action
        if not probe.can_move(src, dst, count):
            raise ValueError(f"illegal supply-provenance action {action}")
        src_up = list(probe.columns[src].face_up)
        dst_up = list(probe.columns[dst].face_up)
        moved_start = len(src_up) - count
        moved = src_up[moved_start:]
        dest_top = dst_up[-1] if dst_up else None
        updated_results = []
        for result in results:
            evidence = list(result.evidence)
            events = list(result.consumptions)
            for ev_index, (obligation, current) in enumerate(zip(result.obligations, evidence)):
                if current.stage in (
                    SupplyConsumptionStage.INTEGRATED,
                    SupplyConsumptionStage.INVALIDATED,
                    SupplyConsumptionStage.EXPIRED,
                ):
                    continue
                tracked_moved = bool(
                    current.current_column == src
                    and current.current_face_up_index is not None
                    and moved_start <= current.current_face_up_index < len(src_up)
                )
                receiver_used = bool(
                    current.current_column == dst
                    and current.current_face_up_index == len(dst_up) - 1
                    and dest_top == obligation.card
                    and moved
                    and moved[0].suit == obligation.card.suit
                    and obligation.expected_receiver_rank == obligation.card.rank
                )
                substitution_offset = next(
                    (
                        offset
                        for offset, card in enumerate(moved)
                        if card == obligation.card and not tracked_moved
                    ),
                    None,
                )
                substituted = substitution_offset is not None
                if not tracked_moved and not substituted and not receiver_used:
                    # Keep exact coordinates aligned when unrelated cards move
                    # below or above the tracked copy.
                    if current.current_column == src and current.current_face_up_index is not None:
                        if current.current_face_up_index >= moved_start:
                            continue
                    evidence[ev_index] = current
                    continue

                moved_offset = (
                    current.current_face_up_index - moved_start
                    if tracked_moved and current.current_face_up_index is not None
                    else substitution_offset
                )
                same_suit_join = bool(
                    dest_top is not None
                    and moved
                    and dest_top.suit == obligation.card.suit
                    and dest_top.rank - 1 == moved[0].rank
                )
                direct = receiver_used or same_suit_join
                source_key = (
                    current.active_source_key
                    or obligation.promised_source_key
                )
                substitute_key = None
                if substituted:
                    substitute_key = f"tableau:{src}:up:{moved_start + int(substitution_offset)}@a{action_index}"
                    source_key = substitute_key
                consequence = (
                    "supplied receiver was actually used by the named same-suit source"
                    if receiver_used
                    else (
                        "supplied source joined the named same-suit campaign interval"
                        if same_suit_join
                        else "supplied source moved without demonstrated campaign integration"
                    )
                )
                stage = (
                    SupplyConsumptionStage.INTEGRATED
                    if direct
                    else SupplyConsumptionStage.CONSUMED
                )
                evidence[ev_index] = replace(
                    current,
                    stage=stage,
                    active_source_key=source_key,
                    current_column=(dst if moved_offset is not None else current.current_column),
                    current_face_up_index=(
                        len(dst_up) + int(moved_offset)
                        if moved_offset is not None
                        else current.current_face_up_index
                    ),
                    substituted_source_key=substitute_key,
                    consumption_action_index=action_index,
                    consumed_as=("receiver" if receiver_used else "source"),
                    direct_campaign_advance=direct,
                    reason=consequence,
                )
                events.append(
                    CampaignSupplyConsumption(
                        obligation.obligation_id,
                        action_index,
                        action,
                        source_key,
                        substituted,
                        direct,
                        consequence,
                    )
                )
            updated_results.append(
                replace(result, evidence=tuple(evidence), consumptions=tuple(events))
            )
        probe.move(src, dst, count, rules=MW_RULES)
        # Automatic foundation removal consumes/integrates any tracked card
        # that has disappeared from the expected destination segment.
        removed = len(probe.foundations) > foundations_before_edge
        normalized = []
        for result in updated_results:
            evidence = []
            for obligation, current in zip(result.obligations, result.evidence):
                if current.stage in (
                    SupplyConsumptionStage.CONSUMED,
                    SupplyConsumptionStage.INTEGRATED,
                ) and current.current_column is not None:
                    location_valid = bool(
                        current.current_face_up_index is not None
                        and 0 <= current.current_face_up_index < len(probe.columns[current.current_column].face_up)
                        and probe.columns[current.current_column].face_up[current.current_face_up_index]
                        == obligation.card
                    )
                    if not location_valid and removed:
                        current = replace(
                            current,
                            stage=SupplyConsumptionStage.INTEGRATED,
                            current_column=None,
                            current_face_up_index=None,
                            direct_campaign_advance=True,
                            reason="supplied asset participated in automatic foundation removal",
                        )
                elif current.stage in (
                    SupplyConsumptionStage.DELIVERED,
                    SupplyConsumptionStage.AVAILABLE,
                ):
                    current = replace(
                        current,
                        stage=(
                            SupplyConsumptionStage.AVAILABLE
                            if _is_available(probe, current.current_column, current.current_face_up_index)
                            else SupplyConsumptionStage.DELIVERED
                        ),
                    )
                evidence.append(current)
            normalized.append(
                replace(
                    result,
                    evidence=tuple(evidence),
                    evaluated_state_key=canonical_state_key(probe),
                    foundations_after=len(probe.foundations),
                    reason="supply provenance advanced through replayed tableau actions",
                )
            )
        results = normalized
        foundations_before_edge = len(probe.foundations)

    final = []
    for result in results:
        evidence = []
        for current in result.evidence:
            if current.stage in (
                SupplyConsumptionStage.DELIVERED,
                SupplyConsumptionStage.AVAILABLE,
            ):
                current = replace(
                    current,
                    stage=(
                        SupplyConsumptionStage.AVAILABLE
                        if _is_available(probe, current.current_column, current.current_face_up_index)
                        else SupplyConsumptionStage.DELIVERED
                    ),
                )
            evidence.append(current)
        final.append(
            replace(
                result,
                evidence=tuple(evidence),
                evaluated_state_key=canonical_state_key(probe),
                foundations_after=len(probe.foundations),
            )
        )
    return tuple(final)


def invalidate_supply_result(
    result: SupplyConsumptionResult,
    state: SpiderState,
    *,
    reason: str,
) -> SupplyConsumptionResult:
    return replace(
        result,
        evidence=tuple(
            replace(item, stage=SupplyConsumptionStage.INVALIDATED, reason=reason)
            if item.stage not in (SupplyConsumptionStage.CONSUMED, SupplyConsumptionStage.INTEGRATED)
            else item
            for item in result.evidence
        ),
        evaluated_state_key=canonical_state_key(state),
        reason=reason,
    )


def supply_result_for_contract(
    results: Sequence[SupplyConsumptionResult], contract_id: str
) -> Optional[SupplyConsumptionResult]:
    return next((item for item in reversed(results) if item.contract_id == contract_id), None)
