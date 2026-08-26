#!/usr/bin/env python3
"""Bounded prospective diagnostic for the anytime whole-game controller v0.1.

The regression anchors execute in isolated subprocesses and return primitive
summaries only.  The prospective controller therefore receives neither the
canonical action sequence nor the legal cost-23 route.  Canonical route
inspection happens only after every prospective result is frozen.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import Action, parse_moves_file
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    AnytimeSearchResult,
    IncumbentRecord,
    StrategicCreditLevel,
    solve_anytime,
)
from spider.planner.deal_timing import DealTimingConfig
from spider.solution_archive import (
    SolutionArchiveResult,
    path_hash,
    record_solution_if_better,
    validate_solution,
)


AUTHORITATIVE_BASE = "6bea3776e5fd05007c46e5e6c509f67842732905"
DEAL_ID = "4925153"
DEAL_PATH = ROOT / "deals" / f"{DEAL_ID}.txt"
CANONICAL_PATH = ROOT / "solutions" / f"{DEAL_ID}_canonical.moves"
DEFAULT_REPORT = ROOT / "artifacts" / "anytime_controller_v0_1_report.md"


@dataclass(frozen=True)
class RegressionAnchors:
    canonical: Dict[str, Any]
    legal_cost23: Dict[str, Any]
    passed: bool


@dataclass(frozen=True)
class UnseenSmokeResult:
    seed: int
    status: str
    elapsed_seconds: float
    expansions: int
    tactical_nodes: int
    best_g: int
    best_stock_epoch: int
    best_foundations: int
    lowest_face_down: int
    unrestricted_deal: bool
    legal_progression: bool
    stop_reason: str


@dataclass(frozen=True)
class FrozenProspectiveExperiment:
    production_smoke: AnytimeSearchResult
    production_attempt: AnytimeSearchResult
    research_attempt: AnytimeSearchResult
    unseen_smokes: Tuple[UnseenSmokeResult, ...]
    prospective_frozen: bool = True
    canonical_actions_loaded: bool = False


@dataclass(frozen=True)
class CanonicalComparison:
    corrected_cost: int
    path_hash: str
    final_state_hash: str
    deals_at_explicit_commands: Tuple[int, ...]
    foundations_at_explicit_commands: Tuple[Tuple[int, int], ...]
    first_machine_divergence: Optional[int]
    loaded_after_prospective_freeze: bool


def _isolated_json(code: str) -> Dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise AssertionError("isolated regression emitted no summary")
    return json.loads(lines[-1])


def run_rule_surprise_preflight() -> RegressionAnchors:
    """Replay both mandated anchors without returning either action route."""
    canonical = _isolated_json(
        "import json; from pathlib import Path; "
        "from spider.solution_archive import validate_solution; "
        f"v=validate_solution('{DEAL_ID}', Path(r'{CANONICAL_PATH}')); "
        "print(json.dumps({'valid':v.valid,'solved':v.solved,"
        "'cost':v.mobilityware_moves,'explicit':v.explicit_commands,"
        "'tableau':v.tableau_moves,'deals':v.stock_deals,"
        "'foundations':v.foundations,'stock':v.stock_remaining,"
        "'path_hash':v.path_hash,'state_hash':v.state_hash}))"
    )
    legal = _isolated_json(
        "import json; "
        "from spider.planner.diagnostics.economic_project_analysis_report "
        "import reconstruct_cost23_checkpoint; "
        "c=reconstruct_cost23_checkpoint(); "
        "print(json.dumps({'valid':c.independently_verified,"
        "'cost':c.arm.total_cost,'explicit':c.action_count,"
        "'deals':c.deal_count,'foundations':len(c.state.foundations),"
        "'foundation_suits':c.foundation_suits,'stock':len(c.state.stock),"
        "'face_down':c.face_down_count}))"
    )
    expected_canonical = {
        "valid": True,
        "solved": True,
        "cost": 172,
        "explicit": 174,
        "tableau": 169,
        "deals": 5,
        "foundations": 8,
        "stock": 0,
        "path_hash": "77d169da2538ba8c",
        "state_hash": "4e9861540eac570cb",
    }
    expected_legal = {
        "valid": True,
        "cost": 23,
        "explicit": 23,
        "deals": 2,
        "foundations": 1,
        "foundation_suits": ["s"],
        "stock": 30,
        "face_down": 32,
    }
    passed = canonical == expected_canonical and legal == expected_legal
    if not passed:
        raise AssertionError(
            f"rule-surprise regression changed: canonical={canonical}, legal={legal}"
        )
    return RegressionAnchors(canonical, legal, True)


def _timing_config() -> DealTimingConfig:
    return DealTimingConfig(
        max_preparation_projects=1,
        max_preparation_cost=4,
        hard_preparation_cost_cap=8,
        max_h1_candidates=1,
        max_h2_candidates=0,
        tactical_max_cost=2,
        tactical_max_nodes=400,
        tactical_time_limit_s=0.15,
        downstream_max_cost=3,
        downstream_max_nodes=400,
        downstream_time_limit_s=0.15,
    )


def benchmark_config(seconds: float, *, expansions: int, tactical_nodes: int) -> AnytimeControllerConfig:
    return AnytimeControllerConfig(
        wall_clock_limit_s=seconds,
        max_strategic_expansions=expansions,
        max_tactical_nodes=tactical_nodes,
        max_frontier_size=500,
        max_credit_level=StrategicCreditLevel.RAW_LEGAL_FALLBACK,
        max_successors_per_expansion=4,
        max_trace_entries=96,
        max_timeline_entries=96,
        campaign_source_combination_limit=4,
        max_direct_projects_per_tier=1,
        max_bounded_projects_per_expansion=1,
        tactical_nodes_per_project=600,
        tactical_time_limit_s_per_project=0.2,
        campaign_branches_clean=0,
        campaign_branches_positive=1,
        campaign_branches_speculative=1,
        campaign_max_added_cost=12,
        campaign_max_nodes=1_500,
        campaign_time_limit_s=0.5,
        campaign_beam_width=64,
        deal_preparation_arms=1,
        deal_pair_arms=0,
        deal_timing_config=_timing_config(),
    )


def _standard_cards() -> list[Card]:
    return [Card(suit, rank) for suit in "cdhs" for rank in range(1, 14) for _ in range(2)]


def _run_unseen(seed: int, seconds: float) -> UnseenSmokeResult:
    cards = _standard_cards()
    random.Random(seed).shuffle(cards)
    state = SpiderState.from_cards(cards)
    config = replace(
        benchmark_config(seconds, expansions=3, tactical_nodes=2_000),
        max_successors_per_expansion=2,
        max_frontier_size=20,
        enable_campaign_edges=False,
        enable_removal_edges=False,
        max_trace_entries=8,
        max_timeline_entries=8,
    )
    result = solve_anytime(state, cards, incumbent=None, config=config)
    return UnseenSmokeResult(
        seed=seed,
        status=result.status.value,
        elapsed_seconds=result.elapsed_seconds,
        expansions=result.strategic_expansions,
        tactical_nodes=result.tactical_nodes,
        best_g=result.best_node.g,
        best_stock_epoch=result.telemetry.best_stock_epoch,
        best_foundations=result.telemetry.best_foundations,
        lowest_face_down=result.telemetry.lowest_face_down,
        unrestricted_deal=result.preflight.profile.can_deal_into_empty,
        legal_progression=bool(
            result.preflight.passed
            and result.best_node.analysis.state_hash
            and result.status.value != "PREFLIGHT_FAILED"
        ),
        stop_reason=result.stop_reason,
    )


def run_prospective_controller_experiment(
    *,
    smoke_seconds: float = 60.0,
    production_seconds: float = 300.0,
    research_seconds: float = 300.0,
    unseen_seconds: float = 10.0,
) -> FrozenProspectiveExperiment:
    """Run from the true deal without importing any stored route actions."""
    cards = tuple(load_deal(DEAL_PATH))
    initial = SpiderState.from_cards(list(cards))
    smoke = solve_anytime(
        initial,
        cards,
        incumbent=None,
        config=benchmark_config(smoke_seconds, expansions=40, tactical_nodes=20_000),
    )
    production = solve_anytime(
        initial,
        cards,
        incumbent=None,
        config=benchmark_config(production_seconds, expansions=160, tactical_nodes=80_000),
    )
    research = solve_anytime(
        initial,
        cards,
        incumbent=172,
        config=benchmark_config(research_seconds, expansions=160, tactical_nodes=80_000),
    )
    unseen = (
        _run_unseen(104729, unseen_seconds),
        _run_unseen(130363, unseen_seconds),
    )
    return FrozenProspectiveExperiment(smoke, production, research, unseen)


def inspect_canonical_after_freeze(
    experiment: FrozenProspectiveExperiment,
) -> CanonicalComparison:
    if not experiment.prospective_frozen or experiment.canonical_actions_loaded:
        raise AssertionError("canonical comparison requires a clean prospective freeze")
    actions = tuple(parse_moves_file(CANONICAL_PATH))
    validation = validate_solution(DEAL_ID, actions)
    if not validation.valid or validation.mobilityware_moves != 172:
        raise AssertionError("canonical comparison replay regressed")
    cards = load_deal(DEAL_PATH)
    state = SpiderState.from_cards(cards)
    deals = []
    foundations = []
    previous_foundations = 0
    for command, action in enumerate(actions, start=1):
        if action == ("deal",):
            state.deal()
            deals.append(command)
        else:
            state.move(*action)
        if len(state.foundations) > previous_foundations:
            foundations.append((command, len(state.foundations)))
            previous_foundations = len(state.foundations)
    machine = experiment.production_attempt.first_solution
    divergence = None
    if machine is not None:
        for index, (left, right) in enumerate(zip(machine.actions, actions), start=1):
            if left != right:
                divergence = index
                break
        if divergence is None and len(machine.actions) != len(actions):
            divergence = min(len(machine.actions), len(actions)) + 1
    return CanonicalComparison(
        corrected_cost=int(validation.mobilityware_moves),
        path_hash=validation.path_hash,
        final_state_hash=validation.state_hash,
        deals_at_explicit_commands=tuple(deals),
        foundations_at_explicit_commands=tuple(foundations),
        first_machine_divergence=divergence,
        loaded_after_prospective_freeze=True,
    )


def _best_machine_candidate(experiment: FrozenProspectiveExperiment) -> Optional[IncumbentRecord]:
    candidates = [
        result.incumbent
        for result in (experiment.production_attempt, experiment.research_attempt)
        if result.incumbent is not None and result.incumbent.source == "machine"
    ]
    return min(candidates, key=lambda item: item.corrected_cost) if candidates else None


def archive_improvement_if_required(
    experiment: FrozenProspectiveExperiment,
) -> Optional[SolutionArchiveResult]:
    candidate = _best_machine_candidate(experiment)
    if candidate is None or candidate.corrected_cost > 171:
        return None
    return record_solution_if_better(
        DEAL_ID,
        candidate.actions,
        source="anytime_whole_game_controller_v0_1",
        experiment_id="anytime-controller-v0.1",
        claimed_mobilityware_moves=candidate.corrected_cost,
    )


def _run_line(result: AnytimeSearchResult) -> str:
    m = result.best_node.analysis.measurement
    return (
        f"status={result.status.value}; elapsed={result.elapsed_seconds:.2f}s; "
        f"stop={result.stop_reason}; "
        f"expansions={result.strategic_expansions}; tactical_nodes={result.tactical_nodes}; "
        f"frontier={result.frontier_remaining}; max_credit={result.maximum_credit_reached}; "
        f"best_g={result.best_node.g}; best_epoch={result.telemetry.best_stock_epoch}; "
        f"best_foundations={result.telemetry.best_foundations}; lowest_face_down={result.telemetry.lowest_face_down}; "
        f"best_state={result.best_node.analysis.state_hash}; current=(fd={m.face_down_count}, stock={m.stock_count}, foundations={m.foundation_count})"
    )


def _format_timeline(values: Iterable[Any]) -> str:
    frozen = tuple(values)
    return "none recorded" if not frozen else "; ".join(str(value) for value in frozen)


def _verdict(experiment: FrozenProspectiveExperiment) -> Tuple[str, str]:
    candidate = _best_machine_candidate(experiment)
    if candidate is not None and candidate.corrected_cost <= 171:
        return "EXCEPTIONAL", "verified machine solution improves the replayed 172 incumbent"
    if candidate is not None:
        return "STRONG PASS", "a complete independently replayed machine solution was found"
    result = experiment.production_attempt
    t = result.telemetry
    if t.best_stock_epoch == 5 and t.best_foundations >= 2:
        return "PASS", "all stock epochs and multiple foundations were reached without route seeding"
    if t.best_foundations > 1 or t.lowest_face_down < 32:
        return "PARTIAL", "the controller advanced beyond the legal cost-23 checkpoint but did not solve"
    return "FAIL", (
        "stock advanced, but the controller did not materially exceed the legal "
        "cost-23 checkpoint's one foundation and 32 face-down cards"
    )


def render_report(
    anchors: RegressionAnchors,
    experiment: FrozenProspectiveExperiment,
    canonical: CanonicalComparison,
    archive: Optional[SolutionArchiveResult],
    *,
    smoke_seconds: float,
    production_seconds: float,
    research_seconds: float,
    unseen_seconds: float,
) -> str:
    smoke = experiment.production_smoke
    production = experiment.production_attempt
    research = experiment.research_attempt
    profile = production.preflight.profile
    candidate = _best_machine_candidate(experiment)
    verdict, reason = _verdict(experiment)
    pt = production.telemetry
    rt = research.telemetry
    lines = ["# Anytime Whole-Game Controller v0.1 — prospective report", ""]

    def section(number: int, title: str, body: Sequence[str]) -> None:
        lines.extend((f"## {number}. {title}", "", *body, ""))

    section(1, "Authoritative base", [f"`{AUTHORITATIVE_BASE}`"])
    section(2, "Active MobilityWare rule-profile freeze", [f"`{asdict(profile)}`", f"Preflight passed: **{production.preflight.passed}**."])
    section(3, "Unrestricted Deal = ON", [f"Confirmed: **{profile.can_deal_into_empty}**. Empty tableau columns do not make a deal illegal."])
    section(4, "Rule-surprise preflight", [f"Both isolated regression anchors passed: **{anchors.passed}**. No additional rule inconsistency was discovered."])
    section(5, "Canonical 172 regression replay", [f"`{anchors.canonical}`"])
    section(6, "Legal cost-23 regression replay", [f"`{anchors.legal_cost23}`"])
    section(7, "Controller config", [f"Smoke: {smoke_seconds}s/40 expansions/20,000 tactical nodes.", f"Production: {production_seconds}s/160 expansions/80,000 tactical nodes.", f"Research: {research_seconds}s/160 expansions/80,000 tactical nodes; supplied incumbent score only = 172.", "All runs: frontier 500, at most 4 strategic successors per expansion, exact state TT, credits 0..4."])
    section(8, "Strategic credit policy", ["Credit 0 starts with structurally dominant/actionable work and Deal alternatives; levels 1–3 widen economic/campaign/rework coverage; level 4 admits corrected raw legal tableau moves. Widening controls coverage, never proof authority."])
    section(9, "Production-like benchmark run", ["Smoke — " + _run_line(smoke), "Five-minute attempt — " + _run_line(production)])
    section(10, "First solution if found", ["None." if production.first_solution is None else f"cost={production.first_solution.corrected_cost}; time={production.first_solution.installed_after_seconds:.2f}s; expansions={production.first_solution.installed_after_expansions}; path={production.first_solution.path_hash}"])
    section(11, "Solution verification", ["No complete production candidate existed to verify." if production.first_solution is None else f"Independent replay={production.first_solution.independently_replay_verified}; endpoint match={production.first_solution.search_endpoint_matches_replay}; stock={production.first_solution.stock_remaining}; foundations={production.first_solution.foundations}; final={production.first_solution.final_state_hash}"])
    section(12, "Incumbent progression", [str(production.incumbent_progression or "none")])
    section(13, "Research-mode benchmark run", [_run_line(research)])
    section(14, "Any <=171 candidate", ["None." if candidate is None or candidate.corrected_cost > 171 else f"cost={candidate.corrected_cost}; path={candidate.path_hash}; final={candidate.final_state_hash}"])
    section(15, "Verification/archive result", ["Not applicable; no <=171 machine candidate." if archive is None else f"candidate_valid={archive.candidate_valid}; strict_improvement={archive.is_strict_improvement}; external_written={archive.external_archive_written}; read-back/current-best={archive.current_best_updated}; path={archive.path_hash}; failure={archive.failure_reason or 'none'}"])
    section(16, "Stock/deal timing timeline", ["Production: " + _format_timeline(pt.deal_timeline), "Research: " + _format_timeline(rt.deal_timeline)])
    section(17, "Foundation timeline", ["Production: " + _format_timeline(pt.foundation_timeline), "Research: " + _format_timeline(rt.foundation_timeline)])
    section(18, "Rework/debt timeline", ["Production: " + _format_timeline(pt.rework_timeline), "Research: " + _format_timeline(rt.rework_timeline)])
    section(19, "Strategic frontier/branch telemetry summary", [f"Production generated={pt.generated}, retained={pt.retained}, kinds={pt.successor_kinds}, deal successors={pt.deal_successors_generated}, prepared deals={pt.deal_preparations_retained}, reanalyses={pt.reanalyses}.", f"Bounded trace entries={len(pt.decision_trace)}; suppressions={pt.suppression_reasons}."])
    section(20, "Credit-level usage", [f"Production={pt.credit_expansions}; research={rt.credit_expansions}."])
    section(21, "TT statistics", [f"Production new={pt.tt_new}, improved={pt.tt_improved}, suppressed={pt.tt_suppressed}, exact-loop={pt.exact_loop_suppressed}.", f"Research new={rt.tt_new}, improved={rt.tt_improved}, suppressed={rt.tt_suppressed}, exact-loop={rt.exact_loop_suppressed}."])
    section(22, "Proof-bound statistics", [f"Production proof-pruned={pt.proof_pruned}, heuristic frontier trims={pt.heuristic_pruned}; research proof-pruned={rt.proof_pruned}, heuristic frontier trims={rt.heuristic_pruned}. Only remaining deals plus the proved reveal lower bound entered proof pruning."])
    section(23, "Major stalls/dead ends", [f"Production stop={production.stop_reason}; inaccessible retries suppressed={pt.inaccessible_retry_suppressed}; cache hits/misses={pt.actionability_cache_hits}/{pt.actionability_cache_misses}; solution replay failures={pt.solution_replay_failures}.", "The bounded report distinguishes a resource-limited tactical miss from global impossibility."])
    section(24, "Unseen-deal smoke results", [*(str(asdict(value)) for value in experiment.unseen_smokes), f"Per-deal requested limit={unseen_seconds}s; completion was not required."])
    section(25, "Prospective verdict", [f"**{verdict}** — {reason}.", "The prospective runs were frozen before canonical future actions were loaded."])
    section(26, "Canonical route comparison (post-freeze only)", [f"Loaded after prospective freeze={canonical.loaded_after_prospective_freeze}; score={canonical.corrected_cost}; path={canonical.path_hash}; final={canonical.final_state_hash}.", f"Canonical deal commands={canonical.deals_at_explicit_commands}; foundation milestones={canonical.foundations_at_explicit_commands}.", "No complete machine route was available for action-by-action comparison." if candidate is None else f"First machine/canonical action divergence={canonical.first_machine_divergence}."])
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-seconds", type=float, default=60.0)
    parser.add_argument("--production-seconds", type=float, default=300.0)
    parser.add_argument("--research-seconds", type=float, default=300.0)
    parser.add_argument("--unseen-seconds", type=float, default=10.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    anchors = run_rule_surprise_preflight()
    experiment = run_prospective_controller_experiment(
        smoke_seconds=args.smoke_seconds,
        production_seconds=args.production_seconds,
        research_seconds=args.research_seconds,
        unseen_seconds=args.unseen_seconds,
    )
    archive = archive_improvement_if_required(experiment)
    canonical = inspect_canonical_after_freeze(experiment)
    report = render_report(
        anchors,
        experiment,
        canonical,
        archive,
        smoke_seconds=args.smoke_seconds,
        production_seconds=args.production_seconds,
        research_seconds=args.research_seconds,
        unseen_seconds=args.unseen_seconds,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nReport written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
