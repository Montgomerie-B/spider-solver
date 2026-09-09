"""Exact-state project-intent coalescing.

When a replayable StrategicProject progress successor is suppressed by exact
TT dominance or same-expansion child deduplication, the game state is already
represented.  This module classifies whether the *purpose* of that successor
should be attached to the surviving canonical registry request.

It never:
- alters transposition-table dominance;
- creates another canonical state;
- copies decorative path history;
- grants proof authority;
- forces service or changes numeric priority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Hashable, Optional, Tuple

from spider.engine import SpiderState
from spider.planner.foundation_conversion_funnel import (
    FoundationConversionFunnel,
    FoundationFunnelStage,
)
from spider.planner.state_service_registry import (
    ServiceRequestKey,
    StateServiceRegistry,
)
from spider.planner.strategic_project import StrategicProjectRegistry
from spider.planner.structural_investment import SameCampaignContinuationCredit
from spider.state_identity import CanonicalStateKey


class ProjectIntentLossClass(str, Enum):
    STATE_ALREADY_HAS_PROJECT_INTENT = "STATE_ALREADY_HAS_PROJECT_INTENT"
    TRANSFERABLE_PROJECT_INTENT_LOST = "TRANSFERABLE_PROJECT_INTENT_LOST"
    NONTRANSFERABLE_CONTEXT_ONLY_PROGRESS = "NONTRANSFERABLE_CONTEXT_ONLY_PROGRESS"
    TRUE_RETENTION_LOSS = "TRUE_RETENTION_LOSS"
    OTHER = "OTHER"


class ProjectIntentSuppressionKind(str, Enum):
    TT_DOMINATED = "TT_DOMINATED"
    SAME_EXPANSION_DEDUP = "SAME_EXPANSION_DEDUP"
    PORTFOLIO = "PORTFOLIO"
    RETENTION = "RETENTION"


@dataclass(frozen=True)
class ProjectIntentAuditRecord:
    classification: ProjectIntentLossClass
    suppression: ProjectIntentSuppressionKind
    campaign_id: str
    project_id: str
    transferred: bool
    request_present: bool
    already_candidate: bool
    campaign_supported: Optional[bool]
    evidence: str


@dataclass
class ProjectIntentCoalescingTelemetry:
    records: list[ProjectIntentAuditRecord] = field(default_factory=list)
    class_counts: Dict[str, int] = field(default_factory=dict)
    tt_dominated: int = 0
    same_expansion_dedup: int = 0
    portfolio_or_retention: int = 0
    transfers_tt: int = 0
    transfers_dedup: int = 0
    recovered_candidates: int = 0
    idempotent_hits: int = 0

    def observe(self, record: ProjectIntentAuditRecord) -> None:
        self.records.append(record)
        name = record.classification.value
        self.class_counts[name] = self.class_counts.get(name, 0) + 1
        if record.suppression is ProjectIntentSuppressionKind.TT_DOMINATED:
            self.tt_dominated += 1
            if record.transferred:
                self.transfers_tt += 1
        elif record.suppression is ProjectIntentSuppressionKind.SAME_EXPANSION_DEDUP:
            self.same_expansion_dedup += 1
            if record.transferred:
                self.transfers_dedup += 1
        else:
            self.portfolio_or_retention += 1
        if record.transferred:
            self.recovered_candidates += 1
        if record.classification is ProjectIntentLossClass.STATE_ALREADY_HAS_PROJECT_INTENT:
            self.idempotent_hits += 1

    def snapshot(self) -> dict:
        return {
            "class_counts": dict(self.class_counts),
            "tt_dominated": self.tt_dominated,
            "same_expansion_dedup": self.same_expansion_dedup,
            "portfolio_or_retention": self.portfolio_or_retention,
            "transfers_tt": self.transfers_tt,
            "transfers_dedup": self.transfers_dedup,
            "recovered_candidates": self.recovered_candidates,
            "idempotent_hits": self.idempotent_hits,
            "records": [
                {
                    "classification": item.classification.value,
                    "suppression": item.suppression.value,
                    "campaign_id": item.campaign_id,
                    "project_id": item.project_id,
                    "transferred": item.transferred,
                    "request_present": item.request_present,
                    "already_candidate": item.already_candidate,
                    "campaign_supported": item.campaign_supported,
                    "evidence": item.evidence,
                }
                for item in self.records
            ],
        }


def parse_campaign_id(campaign_id: str) -> Optional[Tuple[str, int]]:
    if not campaign_id or "#" not in campaign_id:
        return None
    suit, _, index = campaign_id.partition("#")
    if suit.lower() not in "cdhs":
        return None
    try:
        copy_index = int(index)
    except ValueError:
        return None
    return suit.lower(), copy_index


def foundations_removed(state: SpiderState, suit: str) -> int:
    return sum(
        1
        for seq in state.foundations
        if len(seq) == 13 and seq and all(card.suit == suit for card in seq)
    )


def campaign_supported_on_state(state: SpiderState, campaign_id: str) -> bool:
    """Fresh, provenance-free check: the named campaign is still next outstanding."""

    parsed = parse_campaign_id(campaign_id)
    if parsed is None:
        return False
    suit, copy_index = parsed
    next_copy = foundations_removed(state, suit) + 1
    return copy_index == next_copy and 1 <= copy_index <= 2


def _request_already_represents_project(
    projects: StrategicProjectRegistry,
    request_key: ServiceRequestKey,
    *,
    project_id: str,
    campaign_id: str,
) -> bool:
    for project in projects.projects_for_request(request_key):
        if project.project_id == project_id or project.target.campaign_id == campaign_id:
            return True
    return False


def _credit_for_campaign(
    projects: StrategicProjectRegistry,
    campaign_id: str,
    fallback: Optional[SameCampaignContinuationCredit],
) -> Optional[SameCampaignContinuationCredit]:
    if fallback is not None and fallback.objective_id == campaign_id and fallback.is_live:
        return fallback
    for project in projects.projects:
        if project.target.campaign_id != campaign_id:
            continue
        for candidate in project.candidates.values():
            if candidate.continuation.is_live:
                return candidate.continuation
    return None


def consider_suppressed_project_progress(
    *,
    registry: StateServiceRegistry,
    projects: StrategicProjectRegistry,
    campaign_id: str,
    project_id: str,
    child_key: CanonicalStateKey,
    credit: Optional[SameCampaignContinuationCredit],
    expansion: int,
    suppression: ProjectIntentSuppressionKind,
    transfer: bool,
    request_key: Optional[ServiceRequestKey] = None,
    priority_information: Tuple[Hashable, ...] = (),
    funnel: Optional[FoundationConversionFunnel] = None,
    telemetry: Optional[ProjectIntentCoalescingTelemetry] = None,
) -> ProjectIntentAuditRecord:
    """Classify a suppressed campaign-progress arrival and optionally transfer purpose."""

    arrival = registry.arrival(child_key)
    if arrival is None:
        record = ProjectIntentAuditRecord(
            ProjectIntentLossClass.TRUE_RETENTION_LOSS,
            suppression,
            campaign_id,
            project_id,
            False,
            False,
            False,
            None,
            "no registry arrival remains for the suppressed canonical child",
        )
        if telemetry is not None:
            telemetry.observe(record)
        return record

    witness_state = getattr(arrival.witness, "state", None)
    supported: Optional[bool]
    if isinstance(witness_state, SpiderState):
        supported = campaign_supported_on_state(witness_state, campaign_id)
    else:
        supported = None

    resolved_key = request_key
    if resolved_key is None:
        for key in arrival.request_keys:
            resolved_key = key
            break

    already = False
    if resolved_key is not None:
        already = _request_already_represents_project(
            projects,
            resolved_key,
            project_id=project_id,
            campaign_id=campaign_id,
        )
    if not already:
        for key in arrival.request_keys:
            if _request_already_represents_project(
                projects, key, project_id=project_id, campaign_id=campaign_id
            ):
                already = True
                resolved_key = key
                break

    if already:
        record = ProjectIntentAuditRecord(
            ProjectIntentLossClass.STATE_ALREADY_HAS_PROJECT_INTENT,
            suppression,
            campaign_id,
            project_id,
            False,
            resolved_key is not None,
            True,
            supported,
            "surviving canonical request already represents this StrategicProject",
        )
        if telemetry is not None:
            telemetry.observe(record)
        return record

    if supported is False:
        record = ProjectIntentAuditRecord(
            ProjectIntentLossClass.NONTRANSFERABLE_CONTEXT_ONLY_PROGRESS,
            suppression,
            campaign_id,
            project_id,
            False,
            resolved_key is not None,
            False,
            False,
            "fresh canonical analysis does not still have this campaign as next outstanding",
        )
        if telemetry is not None:
            telemetry.observe(record)
        return record

    if resolved_key is None:
        record = ProjectIntentAuditRecord(
            ProjectIntentLossClass.TRUE_RETENTION_LOSS,
            suppression,
            campaign_id,
            project_id,
            False,
            False,
            False,
            supported,
            "canonical arrival exists but has no service request to attach purpose to",
        )
        if telemetry is not None:
            telemetry.observe(record)
        return record

    live_credit = _credit_for_campaign(projects, campaign_id, credit)
    if live_credit is None:
        record = ProjectIntentAuditRecord(
            ProjectIntentLossClass.OTHER,
            suppression,
            campaign_id,
            project_id,
            False,
            True,
            False,
            supported,
            "no live same-campaign continuation credit exists to transfer as purpose",
        )
        if telemetry is not None:
            telemetry.observe(record)
        return record

    record = ProjectIntentAuditRecord(
        ProjectIntentLossClass.TRANSFERABLE_PROJECT_INTENT_LOST,
        suppression,
        campaign_id,
        project_id,
        False,
        True,
        False,
        True if supported is None else supported,
        "canonical survivor supports the campaign but is not a project candidate",
    )
    if not transfer:
        if telemetry is not None:
            telemetry.observe(record)
        return record

    before = len(projects.project(project_id).candidates) if projects.project(project_id) else 0
    attached = projects.attach_continuation(
        live_credit,
        resolved_key,
        priority_information=tuple(priority_information),
        arrival_version=arrival.version,
        expansion=expansion,
    )
    after = len(attached.candidates)
    transferred = after >= before
    record = ProjectIntentAuditRecord(
        ProjectIntentLossClass.TRANSFERABLE_PROJECT_INTENT_LOST,
        suppression,
        campaign_id,
        attached.project_id,
        True,
        True,
        False,
        True if supported is None else supported,
        "attached existing StrategicProject purpose to surviving canonical request",
    )
    if funnel is not None:
        funnel.record(
            FoundationFunnelStage.CANDIDATE_AVAILABLE,
            expansion=expansion,
            project_id=attached.project_id,
            campaign_id=attached.target.campaign_id,
            state_key=child_key,
            actions=(),
            request_key=resolved_key,
            details={
                "coalesced_onto_canonical": True,
                "suppression": suppression.value,
                "arrival_version": arrival.version,
            },
        )
    if telemetry is not None:
        telemetry.observe(record)
    return record
