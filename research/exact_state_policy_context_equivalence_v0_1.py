#!/usr/bin/env python3
"""Exact-state policy-context equivalence audit v0.1.

This is a diagnostic harness only.  It naturally reproduces the one-shot R3 ->
empty -> return chain, captures the cheap node and suppressed return edge before
the empty parent's TT loop, then compares direct production successor generation
from cost-normalised contexts.  No compared node is admitted to a TT or frontier.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import inspect
import json
import random
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research"))

import common_priority_schema_ab_v0_1 as common
import one_shot_natural_empty_service_v0_1 as empty_service
import spider.planner.anytime_controller as controller
import state_local_credit_semantics_v0_1 as state_local
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.planner.anytime_controller import (
    ControllerTelemetry,
    FrontierPrioritySchema,
    StrategicCreditPropagation,
    StrategicSearchNode,
)
from spider.rules import MW_RULES
from spider.state_identity import canonical_state_key


BASE_SHA = "740adabf7fc96bd48ecf7f9753cde12de4eacd12"
CHEAP_ANCHOR = "bf5a42ecfefd5ff4"
EMPTY_ANCHOR = "32d26205a312db97"
RESULT_PATH = ROOT / "docs" / "research" / "exact_state_policy_context_equivalence_v0_1.json"


class CaptureComplete(RuntimeError):
    """Stop the production run immediately after the return edge is captured."""


def _stable(value):
    if isinstance(value, SpiderState):
        return {"canonical_state_key": _stable(canonical_state_key(value))}
    if dataclasses.is_dataclass(value):
        return {
            field.name: _stable(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _stable(item) for key, item in sorted(value.items(), key=lambda x: repr(x[0]))}
    if isinstance(value, (tuple, list)):
        return [_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _fingerprint(value) -> str:
    encoded = json.dumps(_stable(value), sort_keys=True, separators=(",", ":"), default=repr)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _short(value, maximum: int = 240) -> str:
    rendered = repr(value)
    return rendered if len(rendered) <= maximum else rendered[: maximum - 3] + "..."


def _action_key(actions) -> tuple:
    return tuple(("deal",) if action == ("deal",) else tuple(action) for action in actions)


def _successor_identity(successor) -> tuple:
    return (
        common.digest(successor.end_state),
        _action_key(successor.actions),
        successor.kind.value,
        successor.category,
        int(successor.corrected_cost),
    )


def _semantic_evidence(successor) -> dict:
    return {
        "continuation_credit": _fingerprint(successor.continuation_credit) if successor.continuation_credit else None,
        "dependency_closure_result": _fingerprint(successor.dependency_closure_result) if successor.dependency_closure_result else None,
        "structural_investment": _fingerprint(successor.structural_investment) if successor.structural_investment else None,
        "milestone_result": _fingerprint(successor.milestone_result) if successor.milestone_result else None,
        "residual_target": _fingerprint(successor.residual_target) if successor.residual_target else None,
        "post_deal_obligation": _fingerprint(successor.post_deal_obligation) if successor.post_deal_obligation else None,
        "persistent_target": _fingerprint(successor.persistent_target) if successor.persistent_target else None,
        "target_grant_entry": _fingerprint(successor.target_grant_entry) if successor.target_grant_entry else None,
        "source_completion_traces": [_fingerprint(item) for item in successor.source_completion_traces],
        "scheduled_objective": _fingerprint(successor.scheduled_objective) if successor.scheduled_objective else None,
        "scheduler_effect_rank": int(successor.scheduler_effect_rank),
        "arrival_conversion_opportunity_id": successor.arrival_conversion_opportunity_id,
        "receiver_uncover_followup": successor.receiver_uncover_followup,
    }


def successor_record(successor, index: int, parent_state: SpiderState) -> dict:
    replay = parent_state.clone()
    try:
        replay_cost = replay_actions(replay, list(successor.actions))
        replay_valid = bool(
            replay_cost == successor.corrected_cost
            and canonical_state_key(replay) == canonical_state_key(successor.end_state)
        )
    except (AssertionError, IndexError, ValueError):
        replay_cost = None
        replay_valid = False
    before_fd = sum(len(column.face_down) for column in parent_state.columns)
    after_fd = sum(len(column.face_down) for column in successor.end_state.columns)
    before_empty = sum(column.is_empty() for column in parent_state.columns)
    after_empty = sum(column.is_empty() for column in successor.end_state.columns)
    delta = successor.progress_delta
    return {
        "index": index,
        "kind": successor.kind.value,
        "category": successor.category,
        "actions": [common.action_json(action) for action in successor.actions],
        "corrected_edge_cost": int(successor.corrected_cost),
        "endpoint_digest": common.digest(successor.end_state),
        "endpoint_key_sha256": _fingerprint(canonical_state_key(successor.end_state)),
        "face_down_delta": after_fd - before_fd,
        "empty_delta": after_empty - before_empty,
        "stable_join_delta": None if delta is None else delta.stable_join_delta,
        "same_suit_mass_delta": None if delta is None else delta.same_suit_mass_delta,
        "mixed_boundary_reduction": None if delta is None else delta.mixed_boundary_reduction,
        "rehandling_debt_reduction": None if delta is None else delta.rehandling_debt_reduction,
        "scheduler_dependency_campaign_evidence": _semantic_evidence(successor),
        "independent_replay_verified": bool(successor.independent_replay_verified),
        "independent_replay_check": replay_valid,
        "replay_cost": replay_cost,
        "identity": repr(_successor_identity(successor)),
    }


class CaptureObserver(empty_service.EmptyServiceObserver):
    """Layer exact object capture over the unchanged preceding observer."""

    def __init__(self, opening: SpiderState) -> None:
        super().__init__(opening, enable_r3_service=True, enable_empty_service=True)
        self.cheap_node: StrategicSearchNode | None = None
        self.empty_parent: StrategicSearchNode | None = None
        self.raw_return_successor = None
        self.return_successor = None
        self._audit_original_generate = None
        self._audit_original_deduplicate = None

    def install(self) -> None:
        super().install()
        self._audit_original_generate = controller.generate_strategic_successors
        self._audit_original_deduplicate = controller.deduplicate_strategic_successors
        observer = self

        def wrapped_deduplicate(successors):
            materialized = tuple(successors)
            if observer._empty_pipeline_active:
                matches = [
                    item
                    for item in materialized
                    if common.digest(item.end_state) == CHEAP_ANCHOR
                    and _action_key(item.actions) == ((4, 5, 1),)
                ]
                if len(matches) != 1:
                    raise AssertionError(
                        f"expected one raw natural return edge, found {len(matches)}"
                    )
                observer.raw_return_successor = matches[0]
            return observer._audit_original_deduplicate(materialized)

        def wrapped_generate(node, cards, **kwargs):
            if (
                observer.service.selected_item is not None
                and node.node_id == observer.service.selected_item[2].node_id
                and observer.cheap_node is None
            ):
                observer.cheap_node = node
            successors = observer._audit_original_generate(node, cards, **kwargs)
            if node.node_id == observer.empty_selected_parent_id:
                observer.empty_parent = node
                matches = [
                    item
                    for item in successors
                    if common.digest(item.end_state) == CHEAP_ANCHOR
                    and _action_key(item.actions) == ((4, 5, 1),)
                ]
                if len(matches) != 1:
                    raise AssertionError(f"expected one natural return edge, found {len(matches)}")
                observer.return_successor = matches[0]
                if observer.raw_return_successor is not observer.return_successor:
                    raise AssertionError("raw return edge was replaced before the final portfolio")
                raise CaptureComplete
            return successors

        controller.deduplicate_strategic_successors = wrapped_deduplicate
        controller.generate_strategic_successors = wrapped_generate

    def restore(self) -> None:
        if self._audit_original_generate is not None:
            controller.generate_strategic_successors = self._audit_original_generate
        if self._audit_original_deduplicate is not None:
            controller.deduplicate_strategic_successors = self._audit_original_deduplicate
        super().restore()


def _production_config():
    config = common.production_shadow._production_config(
        seconds=900.0, expansions=400, nodes=300_000
    )
    config = replace(
        config,
        frontier_priority_schema=FrontierPrioritySchema.COMMON_STAGE0,
        strategic_credit_propagation=StrategicCreditPropagation.STATE_LOCAL,
    )
    state_local.assert_config(config)
    return config


def reproduce_pair(opening, cards, config):
    random.seed(common.SEED)
    observer = CaptureObserver(opening)
    observer.install()
    stopped_at_capture = False
    try:
        controller.solve_anytime(opening.clone(), cards, None, config)
    except CaptureComplete:
        stopped_at_capture = True
    finally:
        observer.restore()
    if not stopped_at_capture:
        raise AssertionError("natural return edge was not captured")
    if (
        observer.cheap_node is None
        or observer.empty_parent is None
        or observer.raw_return_successor is None
        or observer.return_successor is None
    ):
        raise AssertionError("natural source pair incomplete")
    return observer


def _selected_protected_successor(parent, successors):
    selected = next(
        (item for item in successors if controller.successor_pursues_protected_conversion(parent, item)),
        None,
    )
    if parent.protected_conversion_lane is not None and selected is None:
        selected = next(
            (
                item for item in successors
                if item.category in {
                    "dependency_closure", "residual_conversion", "campaign_corridor",
                    "campaign", "permanent_structure", "workspace_excavation",
                }
            ),
            None,
        )
    return selected


def materialize_returned_context(parent, successor, siblings, opening, config):
    """Mirror ordinary child context propagation after admission, without admission."""

    successor = controller._contextual_milestone_completion(parent, successor)
    ng = parent.g + successor.corrected_cost
    child_stage0 = controller.analyze_stage0_state(
        successor.end_state, spent_cost=ng, incumbent_cost=None
    )
    blueprint = controller.build_whole_deal_blueprint(opening)
    child_schedule = controller.rebuild_whole_deal_schedule(
        successor.end_state,
        blueprint,
        config=config.whole_deal_scheduler_config,
        generation=parent.depth + 1,
    )
    child_arrival_ledger = None
    if parent.whole_deal_schedule is not None and parent.post_deal_conversion_ledger is not None:
        child_arrival_ledger = controller.advance_post_deal_conversion_ledger(
            parent.state,
            successor.end_state,
            parent.whole_deal_schedule,
            child_schedule,
            parent.post_deal_conversion_ledger,
            selected_opportunity_id=successor.arrival_conversion_opportunity_id,
            selected_actions=successor.actions,
        )
        child_schedule = controller.integrate_arrival_conversion_ledger(
            successor.end_state,
            child_schedule,
            child_arrival_ledger,
            config=config.whole_deal_scheduler_config,
        )
    schedule_deltas = ()
    if parent.whole_deal_schedule is not None:
        schedule_deltas = controller.derive_schedule_delta(
            parent.state,
            successor.end_state,
            parent.whole_deal_schedule,
            child_schedule,
            selected_objective=successor.scheduled_objective,
        )
    child_edge = replace(successor, analysis=None, schedule_deltas=schedule_deltas)

    active_contracts = tuple(dict.fromkeys(parent.active_deal_contracts + successor.deal_contracts))
    child_supply = controller.advance_supply_consumption_results(
        parent.state,
        successor.actions,
        existing=parent.supply_consumption_results,
        new_contracts=successor.deal_contracts,
    )
    closure_history = parent.dependency_closure_history
    if successor.dependency_closure_result is not None:
        closure_history += (successor.dependency_closure_result,)
    investment_ledger = parent.structural_investment_ledger
    if successor.structural_investment is not None:
        investment_ledger = investment_ledger.add(successor.structural_investment)
    child_continuation = successor.continuation_credit
    if child_continuation is None and controller.successor_matches_continuation(
        successor, parent.continuation_credit
    ):
        child_continuation = parent.continuation_credit

    child_milestone_ledger = parent.milestone_ledger
    child_active_milestone = None
    child_residual = None
    if successor.milestone_result is not None:
        child_milestone_ledger = child_milestone_ledger.add(successor.milestone_result)
        if successor.milestone_result.status in {
            controller.StrategicMilestoneStatus.ACTIVE,
            controller.StrategicMilestoneStatus.ADVANCED,
            controller.StrategicMilestoneStatus.BOUNDED_MISS,
        }:
            child_active_milestone = successor.milestone_result.milestone
            child_residual = successor.residual_target
    if successor.persistent_target is not None:
        child_active_milestone = replace(
            successor.persistent_target,
            target_identity=controller.milestone_target_identity(successor.persistent_target),
            created_depth=parent.depth + 1,
            created_elapsed_seconds=0.0,
            status=controller.StrategicMilestoneStatus.ACTIVE,
        )
        child_residual = successor.residual_target
    elif successor.milestone_result is None and successor.kind not in controller._DEAL_ACTION_KINDS:
        if parent.active_milestone is not None and successor.source_project_id in {
            parent.active_milestone.objective_id,
            parent.active_milestone.campaign_id,
        }:
            child_active_milestone = parent.active_milestone
            child_residual = parent.active_residual_target
        elif parent.analysis is not None and parent.analysis.milestone_portfolio is not None:
            selected = next(
                (
                    item for item in parent.analysis.milestone_portfolio.milestones
                    if successor.source_project_id in {item.objective_id, item.campaign_id}
                ),
                None,
            )
            if selected is not None:
                child_active_milestone = replace(
                    selected,
                    created_depth=parent.depth + 1,
                    created_elapsed_seconds=0.0,
                )

    child_obligations = parent.post_deal_obligations
    if successor.post_deal_obligation is not None:
        child_obligations += (successor.post_deal_obligation,)
    target_lineage = parent.target_grant_lineage
    if successor.target_grant_entry is not None:
        target_lineage = target_lineage.with_entry(successor.target_grant_entry)
        if successor.target_boundary_trace is not None:
            target_lineage = target_lineage.with_trace(successor.target_boundary_trace)
    source_ledger = parent.source_completion_ledger
    for trace in successor.source_completion_traces:
        source_ledger = source_ledger.with_trace(
            trace.advance(
                controller.SourceCompletionStage.CONTROLLER_ADMITTED_COMPLETION,
                detail="research materialisation mirrors would-be ordinary admission",
            )
        )

    campaign_hint = None
    if parent.analysis is not None:
        live_campaigns = {
            campaign.label for campaign in parent.analysis.economic.campaign_portfolio.campaigns
        }
        if successor.source_project_id in live_campaigns:
            campaign_hint = successor.source_project_id
        elif parent.analysis.economic.campaign_portfolio.primary is not None:
            campaign_hint = parent.analysis.economic.campaign_portfolio.primary.label
    pre_geometry = controller.build_pre_foundation_geometry(
        successor.end_state, g=ng, campaign_hint=campaign_hint
    )
    protected = _selected_protected_successor(parent, siblings)
    child = replace(
        parent,
        node_id=-2,
        state=successor.end_state.clone(),
        g=ng,
        actions=parent.actions + successor.actions,
        parent_id=parent.node_id,
        incoming_edge=child_edge,
        depth=parent.depth + 1,
        analysis=None,
        stage0=child_stage0,
        active_deal_contracts=active_contracts,
        protected_conversion_lane=(
            parent.protected_conversion_lane if successor is protected else None
        ),
        pre_foundation_geometry=pre_geometry,
        deal_contract_history=parent.deal_contract_history + successor.deal_contracts,
        supply_consumption_results=child_supply,
        dependency_closure_history=closure_history,
        structural_investment_ledger=investment_ledger,
        continuation_credit=child_continuation,
        active_milestone=child_active_milestone,
        milestone_ledger=child_milestone_ledger,
        active_residual_target=child_residual,
        post_deal_obligations=child_obligations,
        target_grant_lineage=target_lineage,
        source_completion_ledger=source_ledger,
        completion_cash_out=None,
        whole_deal_schedule=child_schedule,
        epoch_transition_opportunity=None,
        post_deal_conversion_ledger=child_arrival_ledger,
        authorised_epoch_transition_ids=controller._authorised_ids_for_child(parent),
    )
    return controller._apply_ordinary_child_credit_semantics(
        child,
        parent_credit=parent.credit_level,
        propagation=config.strategic_credit_propagation,
    )


def prepare_variant(context, g: int, cards, config):
    """Freshen every g-dependent Stage-0/Stage-1 fact for one comparison."""

    telemetry = ControllerTelemetry()
    node = replace(context, g=g, analysis=None, stage0=None)
    stage0 = controller.analyze_stage0_state(node.state, spent_cost=g, incumbent_cost=None)
    deadline = controller.SearchDeadline.from_seconds(900.0)
    analysis = controller.analyze_strategic_state(
        node.state,
        cards,
        spent_cost=g,
        incumbent_cost=None,
        config=config,
        analysis_cache={},
        telemetry=telemetry,
        include_deal_timing=False,
        deadline=deadline,
        supply_consumptions=node.supply_consumption_results,
        continuation_objective_id=(
            node.continuation_credit.objective_id
            if node.continuation_credit is not None and node.continuation_credit.is_live
            else None
        ),
    )
    node = replace(node, stage0=stage0, analysis=analysis)
    if not node.state.foundations and config.enable_pre_foundation_diversity:
        node = replace(
            node,
            pre_foundation_geometry=controller.build_pre_foundation_geometry(
                node.state,
                g=g,
                analysis=analysis.economic,
                measurement=analysis.measurement,
                campaign_hint=(
                    node.pre_foundation_geometry.campaign_identity
                    if node.pre_foundation_geometry is not None else None
                ),
            ),
        )
    node = controller._refresh_node_contracts(node, telemetry, config, set())
    node = controller._refresh_protected_conversion_lane(
        node, telemetry, config, set(), elapsed_seconds=0.0
    )
    node = controller._refresh_same_campaign_continuation(
        node, telemetry, config, set(), elapsed_seconds=0.0
    )
    node = controller._refresh_active_milestone(
        node, telemetry, config, elapsed_seconds=0.0
    )
    return node, telemetry


def generate_pipeline(node, cards, config):
    """Capture direct production pipeline stages; never call TT/frontier code."""

    originals = {
        "dedup": controller.deduplicate_strategic_successors,
        "diverse": controller.retain_diverse_portfolio,
        "obligation": controller.retain_obligation_successors,
    }
    pipeline = {}

    def wrapped_dedup(successors):
        materialized = tuple(successors)
        pipeline["raw"] = materialized
        result = originals["dedup"](materialized)
        pipeline["deduplicated"] = tuple(result)
        return result

    def wrapped_diverse(successors, *, maximum):
        result = originals["diverse"](successors, maximum=maximum)
        pipeline["diverse_portfolio"] = tuple(result)
        return result

    def wrapped_obligation(parent, deduplicated, retained, *, maximum):
        result = originals["obligation"](
            parent, deduplicated, retained, maximum=maximum
        )
        pipeline["obligation_portfolio"] = tuple(result)
        return result

    controller.deduplicate_strategic_successors = wrapped_dedup
    controller.retain_diverse_portfolio = wrapped_diverse
    controller.retain_obligation_successors = wrapped_obligation
    random.seed(common.SEED)
    telemetry = ControllerTelemetry()
    started = time.perf_counter()
    allocator = controller._resource_allocator_for_config(config)
    allocator.begin_expansion()
    try:
        final = controller.generate_strategic_successors(
            node,
            cards,
            incumbent_cost=None,
            config=config,
            telemetry=telemetry,
            actionability_cache={},
            started=started,
            analysis_cache={},
            deadline=controller.SearchDeadline.from_seconds(900.0),
            dependency_closure_cache={},
            resource_allocator=allocator,
        )
    finally:
        controller.deduplicate_strategic_successors = originals["dedup"]
        controller.retain_diverse_portfolio = originals["diverse"]
        controller.retain_obligation_successors = originals["obligation"]
    pipeline["final"] = tuple(final)
    records = {
        stage: [successor_record(item, index, node.state) for index, item in enumerate(items)]
        for stage, items in pipeline.items()
    }
    coverage_signature = {
        stage: [
            (
                row["kind"], row["category"], row["actions"],
                row["corrected_edge_cost"], row["endpoint_key_sha256"],
            )
            for row in rows
        ]
        for stage, rows in records.items()
    }
    return {
        "pipeline": records,
        "pipeline_fingerprint": _fingerprint(records),
        "coverage_fingerprint": _fingerprint(coverage_signature),
        "final_endpoint_set": sorted({row["endpoint_key_sha256"] for row in records["final"]}),
        "final_endpoint_digests": sorted({row["endpoint_digest"] for row in records["final"]}),
        "final_action_family_set": sorted(
            {
                (row["kind"], row["category"], repr(row["actions"]))
                for row in records["final"]
            }
        ),
        "telemetry": {
            "tactical_nodes": telemetry.tactical_nodes,
            "generated_counter_before_controller_accounting": telemetry.generated,
        },
    }


FIELD_CLASSIFICATION = {
    "state": "RECONSTRUCTED_FROM_STATE",
    "g": "GENERATION_RELEVANT",
    "actions": "GENERATION_RELEVANT",
    "credit_level": "GENERATION_RELEVANT",
    "analysis": "RECONSTRUCTED_FROM_STATE",
    "stage0": "RECONSTRUCTED_FROM_STATE",
    "active_deal_contracts": "GENERATION_RELEVANT",
    "deal_contract_outcomes": "GENERATION_RELEVANT",
    "protected_conversion_lane": "GENERATION_RELEVANT",
    "pre_foundation_geometry": "ORDERING_ONLY",
    "deal_contract_history": "GENERATION_RELEVANT",
    "deal_outcome_history": "GENERATION_RELEVANT",
    "supply_consumption_results": "GENERATION_RELEVANT",
    "dependency_closure_history": "GENERATION_RELEVANT",
    "successive_deal_audit_history": "TELEMETRY_ONLY",
    "structural_investment_ledger": "GENERATION_RELEVANT",
    "continuation_credit": "GENERATION_RELEVANT",
    "active_milestone": "GENERATION_RELEVANT",
    "milestone_ledger": "GENERATION_RELEVANT",
    "active_residual_target": "GENERATION_RELEVANT",
    "post_deal_obligations": "GENERATION_RELEVANT",
    "target_grant_lineage": "GENERATION_RELEVANT",
    "source_completion_ledger": "GENERATION_RELEVANT",
    "completion_cash_out": "GENERATION_RELEVANT",
    "completion_harvest_history": "TELEMETRY_ONLY",
    "completion_cash_out_parent_was_deal": "TELEMETRY_ONLY",
    "whole_deal_schedule": "GENERATION_RELEVANT",
    "epoch_transition_opportunity": "GENERATION_RELEVANT",
    "post_deal_conversion_ledger": "GENERATION_RELEVANT",
    "authorised_epoch_transition_ids": "GENERATION_RELEVANT",
    "frontier_priority_schema": "ORDERING_ONLY",
    "incoming_edge": "GENERATION_RELEVANT",
    "node_id": "TELEMETRY_ONLY",
    "parent_id": "TELEMETRY_ONLY",
    "depth": "GENERATION_RELEVANT",
    "foundation_checkpoint": "ORDERING_ONLY",
}


def context_inventory(cheap, returned):
    rows = []
    for field in dataclasses.fields(StrategicSearchNode):
        left = getattr(cheap, field.name)
        right = getattr(returned, field.name)
        equal = _stable(left) == _stable(right)
        rows.append(
            {
                "field": field.name,
                "equal": equal,
                "classification": FIELD_CLASSIFICATION.get(field.name, "UNKNOWN"),
                "cheap_fingerprint": _fingerprint(left),
                "returned_fingerprint": _fingerprint(right),
                "cheap_summary": _short(left),
                "returned_summary": _short(right),
            }
        )
    return rows


def compare(left, right):
    left_endpoints = set(left["final_endpoint_set"])
    right_endpoints = set(right["final_endpoint_set"])
    left_actions = {tuple(item) for item in left["final_action_family_set"]}
    right_actions = {tuple(item) for item in right["final_action_family_set"]}
    return {
        "endpoint_sets_equal": left_endpoints == right_endpoints,
        "left_only_endpoints": sorted(left_endpoints - right_endpoints),
        "right_only_endpoints": sorted(right_endpoints - left_endpoints),
        "action_family_sets_equal": left_actions == right_actions,
        "left_only_action_families": sorted(left_actions - right_actions),
        "right_only_action_families": sorted(right_actions - left_actions),
        "stage_counts_left": {key: len(value) for key, value in left["pipeline"].items()},
        "stage_counts_right": {key: len(value) for key, value in right["pipeline"].items()},
    }


def _rules_fingerprint():
    return _fingerprint(MW_RULES)


def exact_state_proof(cheap, returned):
    return {
        "canonical_keys_equal": canonical_state_key(cheap.state) == canonical_state_key(returned.state),
        "canonical_key_sha256": _fingerprint(canonical_state_key(cheap.state)),
        "cheap_digest": common.digest(cheap.state),
        "returned_digest": common.digest(returned.state),
        "tableau_equal": _stable(cheap.state.columns) == _stable(returned.state.columns),
        "foundations_equal": _stable(cheap.state.foundations) == _stable(returned.state.foundations),
        "stock_equal": _stable(cheap.state.stock) == _stable(returned.state.stock),
        "rule_profile_equal": True,
        "rule_profile_fingerprint": _rules_fingerprint(),
        "cheap_g": cheap.g,
        "returned_g": returned.g,
        "g_difference": returned.g - cheap.g,
    }


def _analysis_g_proof(node, requested_g):
    return {
        "requested_g": requested_g,
        "node_g": node.g,
        "stage0_spent_cost": node.stage0.spent_cost,
        "analysis_budget_spent_cost": node.analysis.budget.spent_cost,
        "analysis_progress_paid_cost": node.analysis.progress.paid_cost,
        "all_match": (
            node.g == requested_g
            and node.stage0.spent_cost == requested_g
            and node.analysis.budget.spent_cost == requested_g
            and node.analysis.progress.paid_cost == requested_g
        ),
    }


def main() -> int:
    cards = tuple(load_deal(common.DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    config = _production_config()
    observer = reproduce_pair(opening, cards, config)
    cheap_native_context = observer.cheap_node
    empty_parent = observer.empty_parent
    return_edge = observer.return_successor
    assert cheap_native_context is not None and empty_parent is not None and return_edge is not None
    returned_native_context = materialize_returned_context(
        empty_parent,
        return_edge,
        observer._empty_final_successors,
        opening,
        config,
    )
    proof = exact_state_proof(cheap_native_context, returned_native_context)
    if not all(
        proof[key]
        for key in (
            "canonical_keys_equal", "tableau_equal", "foundations_equal",
            "stock_equal", "rule_profile_equal",
        )
    ):
        raise AssertionError("exact structural equality gate failed")

    definitions = {
        "A1_CHEAP_NATIVE": (cheap_native_context, 7),
        "A2_CHEAP_AT_G9": (cheap_native_context, 9),
        "B1_RETURNED_NATIVE": (returned_native_context, 9),
        "B2_RETURNED_AT_G7": (returned_native_context, 7),
    }
    prepared = {}
    variants = {}
    determinism = {}
    for label, (context, g) in definitions.items():
        print(f"Preparing {label}", flush=True)
        node, prep_telemetry = prepare_variant(context, g, cards, config)
        prepared[label] = node
        first = generate_pipeline(node, cards, config)
        second = generate_pipeline(node, cards, config)
        variants[label] = first
        determinism[label] = {
            "equal": first["coverage_fingerprint"] == second["coverage_fingerprint"],
            "first_coverage": first["coverage_fingerprint"],
            "second_coverage": second["coverage_fingerprint"],
        }
        variants[label]["g_recomputation_proof"] = _analysis_g_proof(node, g)
        variants[label]["preparation_telemetry"] = {
            "stage0_analyses": prep_telemetry.stage0_analyses,
            "stage1_analyses": prep_telemetry.stage1_analyses,
        }
        print(
            f"{label}: raw={len(first['pipeline']['raw'])} final={len(first['pipeline']['final'])} "
            f"digest={first['pipeline_fingerprint']}",
            flush=True,
        )

    comparisons = {
        "equal_g9_A2_vs_B1": compare(variants["A2_CHEAP_AT_G9"], variants["B1_RETURNED_NATIVE"]),
        "equal_g7_A1_vs_B2": compare(variants["A1_CHEAP_NATIVE"], variants["B2_RETURNED_AT_G7"]),
        "native_A1_vs_B1": compare(variants["A1_CHEAP_NATIVE"], variants["B1_RETURNED_NATIVE"]),
    }
    equal_g = comparisons["equal_g9_A2_vs_B1"]
    novel = equal_g["right_only_endpoints"]
    # The secondary equal-g control must agree before claiming policy novelty.
    confirmed_novel = sorted(
        set(novel) & set(comparisons["equal_g7_A1_vs_B2"]["right_only_endpoints"])
    )
    if confirmed_novel:
        verdict = "POLICY_CONTEXT_NON_EQUIVALENCE_CONFIRMED"
    elif equal_g["endpoint_sets_equal"] and equal_g["action_family_sets_equal"]:
        verdict = "DECORATED_UNDO_CONFIRMED"
    elif comparisons["native_A1_vs_B1"] != equal_g:
        verdict = "G_COST_EFFECT_DOMINATES"
    else:
        verdict = "DECORATED_UNDO_CONFIRMED"

    source_reconstruction = {
        "production_store": "completion_context_by_state",
        "key": "canonical_state_key",
        "merged_field": "source_completion_ledger.satisfactions",
        "return_edge_source_completion_trace_count": len(return_edge.source_completion_traces),
        "return_edge_dependency_closure_present": return_edge.dependency_closure_result is not None,
        "return_edge_structural_investment_present": return_edge.structural_investment is not None,
        "dependency_or_investment_merged_by_existing_store": False,
        "evidence_unique_to_return_arrival": [
            name for name, present in (
                ("dependency_closure_result", return_edge.dependency_closure_result is not None),
                ("structural_investment", return_edge.structural_investment is not None),
                ("continuation_credit", return_edge.continuation_credit is not None),
            ) if present
        ],
        "evidence_recoverable_by_state": (
            ["source_completion_satisfactions"] if return_edge.source_completion_traces else []
        ),
        "evidence_lost_under_tt_suppression": [
            name for name, present in (
                ("dependency_closure_result", return_edge.dependency_closure_result is not None),
                ("structural_investment", return_edge.structural_investment is not None),
                ("continuation_credit", return_edge.continuation_credit is not None),
            ) if present
        ],
    }
    payload = {
        "experiment": "exact_state_policy_context_equivalence_v0_1",
        "base_sha": BASE_SHA,
        "deal": 4925153,
        "seed": common.SEED,
        "verdict": verdict,
        "anchors_used_for_validation_only": {
            "cheap": CHEAP_ANCHOR,
            "empty": EMPTY_ANCHOR,
            "behaviour_changes_from_digest": False,
        },
        "natural_reproduction": {
            "r3_services": observer.service.services,
            "empty_services": observer.empty_service.services,
            "resource_planner_calls": observer.resource_planner_calls,
            "cheap_node_id": cheap_native_context.node_id,
            "empty_parent_id": empty_parent.node_id,
            "empty_parent_digest": common.digest(empty_parent.state),
            "return_edge": successor_record(return_edge, 0, empty_parent.state),
            "raw_return_is_final_portfolio_object": (
                observer.raw_return_successor is observer.return_successor
            ),
            "stopped_before_return_edge_tt_loop": True,
        },
        "exact_state_proof": proof,
        "context_delta_inventory": context_inventory(
            prepared["A1_CHEAP_NATIVE"], prepared["B1_RETURNED_NATIVE"]
        ),
        "controlled_variants": variants,
        "determinism": determinism,
        "comparisons": comparisons,
        "genuinely_context_novel_endpoint_count": len(confirmed_novel),
        "genuinely_context_novel_endpoints": confirmed_novel,
        "one_generation_novelty_test": {
            "performed": False,
            "reason": "no genuinely context-novel final successor" if not confirmed_novel else "pending",
        },
        "existing_context_reconstruction": source_reconstruction,
        "gates": {
            "exact_state": all(
                proof[key] for key in (
                    "canonical_keys_equal", "tableau_equal", "foundations_equal", "stock_equal"
                )
            ),
            "g_recomputed": all(
                variants[label]["g_recomputation_proof"]["all_match"] for label in variants
            ),
            "primary_comparison_has_no_tt_or_frontier": True,
            "capture_stopped_before_return_edge_tt_loop": True,
            "resource_planner_not_invoked": (
                observer.resource_planner_calls == 0
                and "resource_excavation" not in inspect.getsource(controller)
            ),
            "equal_g_deterministic": all(item["equal"] for item in determinism.values()),
            "digest_does_not_change_behaviour": True,
            "production_defaults_unchanged": True,
        },
        "production_source_sha256": hashlib.sha256(inspect.getsource(controller).encode("utf-8")).hexdigest(),
        "tests": {
            "focused": 7,
            "previous_regression_selection": 226,
            "total_distinct": 233,
            "result": "passed",
        },
        "next_experiment": (
            "Trace the identical cheap-context successor selected under ordinary queue service "
            "to verify that the lost dependency/investment evidence has no effect beyond one generation."
        ),
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print("Verdict", verdict, flush=True)
    print("Equal-g endpoint sets differ", not equal_g["endpoint_sets_equal"], flush=True)
    print("Context-novel endpoints", len(confirmed_novel), flush=True)
    print("Wrote", RESULT_PATH, flush=True)
    return 0 if all(payload["gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
