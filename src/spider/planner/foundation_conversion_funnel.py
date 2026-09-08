"""Observation-only first-foundation conversion funnel.

The funnel deliberately owns no game policy.  It records exact-state,
registry-request, project, campaign, and replay-prefix identities so repeated
widening of one request cannot masquerade as additional conversion progress.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Dict, Hashable, Mapping, Optional, Sequence, Tuple

from spider.metrics import Action
from spider.state_identity import CanonicalStateKey


class FoundationFunnelStage(IntEnum):
    PROJECT_EXISTS = 0
    CANDIDATE_AVAILABLE = 1
    CAMPAIGN_ANALYSED = 2
    ACTIONABLE_PREREQUISITE = 3
    TACTICAL_DEMAND_DERIVED = 4
    ALLOCATOR_GRANT = 5
    REALISER_INVOKED = 6
    REPLAYABLE_PROGRESS_RETURNED = 7
    PROGRESS_RETAINED = 8
    PROJECT_CONTINUATION_SERVICED = 9
    TERMINAL_READY = 10
    REMOVAL_REQUESTED = 11
    FOUNDATION_GENERATED = 12
    FOUNDATION_RETAINED = 13
    FOUNDATION_REPLAY_VERIFIED = 14

    @property
    def label(self) -> str:
        return f"F{int(self)}_{self.name}"


class FoundationFunnelFailure(str, Enum):
    NO_ACTIONABLE_PREREQUISITE = "NO_ACTIONABLE_PREREQUISITE"
    DEMAND_NOT_DERIVED = "DEMAND_NOT_DERIVED"
    TACTICAL_GRANT_DENIED = "TACTICAL_GRANT_DENIED"
    REALISER_NO_RESULT = "REALISER_NO_RESULT"
    REPLAY_INVALID = "REPLAY_INVALID"
    TT_DOMINATED = "TT_DOMINATED"
    SUCCESSOR_DEDUP_DROPPED = "SUCCESSOR_DEDUP_DROPPED"
    PORTFOLIO_DROPPED = "PORTFOLIO_DROPPED"
    RETENTION_DROPPED = "RETENTION_DROPPED"
    CONTINUATION_NOT_SERVICED = "CONTINUATION_NOT_SERVICED"
    PROJECT_EXPIRED = "PROJECT_EXPIRED"
    CAMPAIGN_INVALIDATED = "CAMPAIGN_INVALIDATED"
    TERMINAL_REMOVAL_NOT_REQUESTED = "TERMINAL_REMOVAL_NOT_REQUESTED"
    REMOVAL_NO_RESULT = "REMOVAL_NO_RESULT"


def _digest(value: object) -> str:
    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class FoundationFunnelEvent:
    stage: FoundationFunnelStage
    expansion: int
    project_id: str
    campaign_id: str
    state_digest: str
    request_digest: Optional[str]
    trajectory_digest: str
    action_count: int
    details: Tuple[Tuple[str, Hashable], ...] = ()

    @property
    def identity(self) -> Tuple[object, ...]:
        return (
            self.stage,
            self.project_id,
            self.campaign_id,
            self.state_digest,
            self.request_digest,
            self.trajectory_digest,
            self.details,
        )


@dataclass(frozen=True)
class FoundationFunnelDrop:
    from_stage: FoundationFunnelStage
    to_stage: FoundationFunnelStage
    reason: FoundationFunnelFailure
    expansion: int
    project_id: str
    campaign_id: str
    state_digest: str
    request_digest: Optional[str]
    evidence: str

    @property
    def identity(self) -> Tuple[object, ...]:
        return (
            self.from_stage,
            self.to_stage,
            self.reason,
            self.project_id,
            self.campaign_id,
            self.state_digest,
            self.request_digest,
            self.evidence,
        )


@dataclass
class FoundationConversionFunnel:
    """Deduplicated event ledger with bounded failure classification."""

    events: list[FoundationFunnelEvent] = field(default_factory=list)
    drops: list[FoundationFunnelDrop] = field(default_factory=list)
    _event_keys: set[Tuple[object, ...]] = field(default_factory=set, repr=False)
    _drop_keys: set[Tuple[object, ...]] = field(default_factory=set, repr=False)

    def record(
        self,
        stage: FoundationFunnelStage,
        *,
        expansion: int,
        project_id: str,
        campaign_id: str,
        state_key: CanonicalStateKey,
        actions: Sequence[Action],
        request_key: Optional[object] = None,
        details: Optional[Mapping[str, Hashable]] = None,
    ) -> bool:
        event = FoundationFunnelEvent(
            stage,
            expansion,
            project_id,
            campaign_id,
            _digest(state_key),
            _digest(request_key) if request_key is not None else None,
            _digest(tuple(actions)),
            len(actions),
            tuple(sorted((details or {}).items())),
        )
        if event.identity in self._event_keys:
            return False
        self._event_keys.add(event.identity)
        self.events.append(event)
        return True

    def drop(
        self,
        from_stage: FoundationFunnelStage,
        to_stage: FoundationFunnelStage,
        reason: FoundationFunnelFailure,
        *,
        expansion: int,
        project_id: str,
        campaign_id: str,
        state_key: CanonicalStateKey,
        request_key: Optional[object] = None,
        evidence: str,
    ) -> bool:
        item = FoundationFunnelDrop(
            from_stage,
            to_stage,
            reason,
            expansion,
            project_id,
            campaign_id,
            _digest(state_key),
            _digest(request_key) if request_key is not None else None,
            evidence,
        )
        if item.identity in self._drop_keys:
            return False
        self._drop_keys.add(item.identity)
        self.drops.append(item)
        return True

    def has_stage(self, campaign_id: str, stage: FoundationFunnelStage) -> bool:
        return any(
            item.campaign_id == campaign_id and item.stage == stage
            for item in self.events
        )

    def snapshot(self) -> Dict[str, object]:
        stages: Dict[str, object] = {}
        for stage in FoundationFunnelStage:
            rows = [item for item in self.events if item.stage == stage]
            stages[stage.label] = {
                "entrants": len(rows),
                "first_expansion": min((item.expansion for item in rows), default=None),
                "unique_projects": len({item.project_id for item in rows}),
                "unique_states": len({item.state_digest for item in rows}),
            }
        per_campaign: Dict[str, object] = {}
        for campaign_id in sorted({item.campaign_id for item in self.events}):
            rows = [item for item in self.events if item.campaign_id == campaign_id]
            per_campaign[campaign_id] = {
                stage.label: {
                    "entrants": sum(item.stage == stage for item in rows),
                    "first_expansion": min(
                        (item.expansion for item in rows if item.stage == stage),
                        default=None,
                    ),
                    "unique_projects": len(
                        {item.project_id for item in rows if item.stage == stage}
                    ),
                    "unique_states": len(
                        {item.state_digest for item in rows if item.stage == stage}
                    ),
                }
                for stage in FoundationFunnelStage
            }
        deepest = max((int(item.stage) for item in self.events), default=-1)
        return {
            "deepest_stage": (
                FoundationFunnelStage(deepest).label if deepest >= 0 else None
            ),
            "stages": stages,
            "per_campaign": per_campaign,
            "events": [
                {
                    "stage": item.stage.label,
                    "expansion": item.expansion,
                    "project_id": item.project_id,
                    "campaign_id": item.campaign_id,
                    "state_digest": item.state_digest,
                    "request_digest": item.request_digest,
                    "trajectory_digest": item.trajectory_digest,
                    "action_count": item.action_count,
                    "details": dict(item.details),
                }
                for item in self.events
            ],
            "drops": [
                {
                    "from": item.from_stage.label,
                    "to": item.to_stage.label,
                    "reason": item.reason.value,
                    "expansion": item.expansion,
                    "project_id": item.project_id,
                    "campaign_id": item.campaign_id,
                    "state_digest": item.state_digest,
                    "request_digest": item.request_digest,
                    "evidence": item.evidence,
                }
                for item in self.drops
            ],
        }
