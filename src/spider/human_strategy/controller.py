"""Principal-line controller.

Understand the position, choose one objective, and stay with it while the
plan is still earning its cost. Reassess when the plan finishes, becomes
illegal, or its measured benefit disappears. Dormant alternatives are kept
and tried only after the principal attempt fails, or after a challenger
beats the commitment margin.
"""

from __future__ import annotations

import hashlib
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import Action, format_action, replay_actions_detailed
from spider.packed_state import pack_state
from spider.planner.objective_realizer import RealizationMode, RealizationStatus, realize_objective
from spider.planner.space_lifecycle import empty_count
from spider.research_actions import all_legal_actions, apply_action, face_down_count, rss_mb, step_cost
from spider.search_kernel import SearchLimits, reconstruct_path, run_search
from spider.state_identity import canonical_state_key

from .context import StrategicContext, build_context
from .evaluation import (
    admissible_remaining,
    bury_risk,
    cost_led_action,
    estimate_remaining,
    same_suit_bonds,
)
from .portfolio import Candidate, _score_action, build_candidates, select_candidate
from .foundation_direction import (
    adopt_alternative_foundation,
    choose_without_unjustified_cover,
    close_foundation_campaign,
    covers_productive_run,
    planning_stall_detail,
    propose_foundation_step,
    rank_foundations,
    recover_foundation_step,
    structural_assessment,
)
from .preparation import (
    DealComparison,
    PreparationOption,
    abandonment_reason,
    classify_stall,
    compare_before_deal,
    soft_failure_id,
    strategic_stop_status,
)
from .profiles import Profile
from .strategic_frontier import StrategicFrontier, outcome_rank


@dataclass
class Decision:
    state_id: str
    cumulative_g: int
    stock_rows: int
    foundations: int
    considered: Tuple[str, ...]
    chosen_id: str
    chosen_kind: str
    reason: str
    expected_benefit: float
    projected: float
    structural_risk: float
    evidence: Tuple[str, ...]
    actions: Tuple[str, ...]
    status: str
    actual_cost: int
    actual_notes: Tuple[str, ...]
    principles: Tuple[int, ...]
    dormant_ids: Tuple[str, ...]
    cost_led: str

    def to_dict(self) -> dict:
        return {
            "state_id": self.state_id,
            "cumulative_g": self.cumulative_g,
            "stock_rows": self.stock_rows,
            "foundations": self.foundations,
            "considered": list(self.considered),
            "chosen_id": self.chosen_id,
            "chosen_kind": self.chosen_kind,
            "reason": self.reason,
            "expected_benefit_estimate": self.expected_benefit,
            "projected_estimate": self.projected,
            "structural_risk_estimate": self.structural_risk,
            "evidence": list(self.evidence),
            "actions": list(self.actions),
            "status": self.status,
            "actual_cost": self.actual_cost,
            "actual_notes": list(self.actual_notes),
            "principles": list(self.principles),
            "dormant_ids": list(self.dormant_ids),
            "cost_led_action": self.cost_led,
            "estimates_are_estimates": True,
        }


@dataclass
class SolveResult:
    status: str
    mode: str
    actions: Tuple[Action, ...]
    cumulative_g: int
    suffix_mw: int
    solved: bool
    foundations: int
    stock_rows: int
    elapsed_s: float
    peak_rss_mb: Optional[float]
    unique_states: int
    objectives_attempted: int
    objectives_achieved: int
    objectives_failed: int
    objectives_partial: int
    backtracks: int
    widens: int
    deals: int
    decisions: Tuple[Decision, ...]
    events: Tuple[str, ...]
    provenance: dict
    replay: Optional[dict]
    cache_hits: int
    cache_misses: int
    profile: dict
    stop_reason: str

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "mode": self.mode,
            "actions": [format_action(action) for action in self.actions],
            "cumulative_g": self.cumulative_g,
            "suffix_mw": self.suffix_mw,
            "solved": self.solved,
            "foundations": self.foundations,
            "stock_rows": self.stock_rows,
            "elapsed_s": round(self.elapsed_s, 3),
            "peak_rss_mb": None if self.peak_rss_mb is None else round(self.peak_rss_mb, 2),
            "unique_states": self.unique_states,
            "objectives_attempted": self.objectives_attempted,
            "objectives_achieved": self.objectives_achieved,
            "objectives_failed": self.objectives_failed,
            "objectives_partial": self.objectives_partial,
            "backtracks": self.backtracks,
            "widens": self.widens,
            "deals": self.deals,
            "decisions": [item.to_dict() for item in self.decisions],
            "events": list(self.events),
            "provenance": self.provenance,
            "replay": self.replay,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "profile": self.profile,
            "stop_reason": self.stop_reason,
            "workers_used": 1,
        }


@dataclass
class _Line:
    state: SpiderState
    g: int
    actions: List[Action]
    seen: Dict[object, int]
    active_id: Optional[str] = None
    remaining: Tuple[Action, ...] = ()
    active_kind: str = ""
    active_principles: Tuple[int, ...] = ()
    hold: bool = False

    def snapshot(self) -> "_Line":
        return _Line(
            self.state.clone(),
            self.g,
            list(self.actions),
            dict(self.seen),
            self.active_id,
            tuple(self.remaining),
            self.active_kind,
            self.active_principles,
            self.hold,
        )


@dataclass
class _Dormant:
    line: _Line
    force_id: str


@dataclass
class _Stats:
    attempted: int = 0
    achieved: int = 0
    failed: int = 0
    partial: int = 0
    backtracks: int = 0
    widens: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    peak_rss: Optional[float] = None
    events: List[str] = field(default_factory=list)
    decisions: List[Decision] = field(default_factory=list)


def _identity(state: SpiderState):
    return canonical_state_key(state)


def _state_id(state: SpiderState) -> str:
    return hashlib.sha256(pack_state(state)).hexdigest()


def _profile_dict(profile: Profile) -> dict:
    return {
        "name": profile.name,
        "time_limit_s": profile.time_limit_s,
        "rss_abort_mb": profile.rss_abort_mb,
        "strategic_width": profile.strategic_width,
        "max_width": profile.max_width,
        "tactical_nodes": profile.tactical_nodes,
        "tactical_time_s": profile.tactical_time_s,
        "tactical_max_cost": profile.tactical_max_cost,
        "max_steps": profile.max_steps,
        "commitment_margin": profile.commitment_margin,
        "workers": 1,
        "consult_portfolio": profile.consult_portfolio,
        "frontier_limit": profile.frontier_limit,
        "proposals_per_decision": profile.proposals_per_decision,
        "slice_steps": profile.slice_steps,
        "line_attempt_cap": profile.line_attempt_cap,
    }


def _purpose_met(kind: str, before: SpiderState, after: SpiderState) -> bool:
    if kind == "DEAL_NOW":
        return len(after.stock) < len(before.stock)
    if kind == "FOUNDATION":
        return len(after.foundations) > len(before.foundations) or after.is_solved()
    if kind == "PREPARE":
        return bury_risk(after) < bury_risk(before) or len(after.stock) < len(before.stock)
    if kind == "REVEAL":
        return face_down_count(after) < face_down_count(before)
    if kind == "ZERO_COST":
        return True
    if kind == "SAME_SUIT":
        return same_suit_bonds(after) > same_suit_bonds(before)
    if kind in {"WORKSPACE", "STRETCH"}:
        return empty_count(after) > empty_count(before)
    if kind == "PARK":
        # A bounded exit alone is not progress. The park has to lower the
        # estimate, or it is a shuffle and the objective fails.
        return estimate_remaining(after) + 0.05 < estimate_remaining(before)
    return False


def _execute(state: SpiderState, candidate: Candidate, profile: Profile, time_left: float):
    """Return status, cost, resulting state, note, remaining actions, applied actions."""

    if candidate.objective is not None and not candidate.actions:
        limit = min(profile.tactical_time_s, max(0.05, time_left))
        found = realize_objective(
            state,
            candidate.objective,
            mode=RealizationMode.FAST_BOUNDED,
            max_cost=profile.tactical_max_cost,
            max_nodes=profile.tactical_nodes,
            time_limit_s=limit,
            beam=32,
        )
        if found.status == RealizationStatus.FOUND and found.target_verified and found.actions:
            trial = state.clone()
            cost = 0
            for action in found.actions:
                cost += apply_action(trial, action)
            if candidate.objective.is_satisfied(trial):
                return ("achieved", cost, trial, "objective predicate holds after replay", (), tuple(found.actions))
        return (
            "failed",
            0,
            state,
            f"objective not achieved within the tactical budget ({found.status.value})",
            (),
            (),
        )
    if not candidate.actions:
        return ("failed", 0, state, "candidate has no actions and no objective", (), ())

    action = candidate.actions[0]
    if action == ("deal",):
        legal = state.can_deal()
    else:
        legal = state.can_move(*action)
    if not legal:
        return ("blocked", 0, state, "action is not legal in this state", (), ())
    trial = state.clone()
    cost = apply_action(trial, action)
    remaining = tuple(candidate.actions[1:])
    if candidate.hold:
        # A blocker relocation is not itself a reveal. The plan already
        # replayed, so a legal step stays committed until the plan ends.
        if trial.is_solved() or not remaining:
            return ("achieved", cost, trial, "committed plan finished", (), (action,))
        return ("partial", cost, trial, "committed plan step", remaining, (action,))
    met = trial.is_solved() or _purpose_met(candidate.kind, state, trial)
    if met and not remaining:
        return ("achieved", cost, trial, "legal action met the objective", (), (action,))
    if met and remaining:
        return (
            "partial",
            cost,
            trial,
            "step met its immediate purpose; the objective remains open",
            remaining,
            (action,),
        )
    if candidate.kind in {"TACTICAL", "ACCESS", "ALIGN"}:
        return ("partial", cost, trial, "legal step; not counted as a completed objective", remaining, (action,))
    return ("failed", 0, state, "action was legal but did not meet the objective", (), ())


def _retarget(line: _Line, ctx: StrategicContext) -> Optional[Candidate]:
    if not line.remaining or not line.active_id:
        return None
    action = line.remaining[0]
    if action == ("deal",):
        if not line.state.can_deal():
            return None
    elif not line.state.can_move(*action):
        return None
    scored = _score_action(line.state, line.g, action, ctx)
    scored.candidate_id = line.active_id
    scored.actions = tuple(line.remaining)
    scored.kind = line.active_kind or scored.kind
    scored.hold = line.hold
    if line.active_principles:
        scored.principles = line.active_principles
    return scored


def _insert(ranked: List[Candidate], extra: Candidate) -> List[Candidate]:
    rest = [item for item in ranked if item.candidate_id != extra.candidate_id]
    rest.append(extra)
    rest.sort(key=lambda item: item.rank_key())
    return rest


def _decision(ctx, considered, choice: Candidate, reason: str, dormant_ids, execution) -> Decision:
    status, cost, _state, note, _remaining, applied = execution
    led = cost_led_action(ctx.state)
    return Decision(
        state_id=_state_id(ctx.state),
        cumulative_g=ctx.cumulative_g,
        stock_rows=ctx.stock_rows,
        foundations=ctx.foundations,
        considered=tuple(item.candidate_id for item in considered),
        chosen_id=choice.candidate_id,
        chosen_kind=choice.kind,
        reason=reason,
        expected_benefit=choice.expected_benefit,
        projected=choice.projected,
        structural_risk=choice.structural_risk,
        evidence=choice.evidence,
        actions=tuple(format_action(action) for action in applied),
        status=status,
        actual_cost=cost if status in {"achieved", "partial"} else 0,
        actual_notes=(note,),
        principles=choice.principles,
        dormant_ids=tuple(dormant_ids),
        cost_led="" if led is None else format_action(led),
    )


def _validate(root: SpiderState, actions: Sequence[Action], end: SpiderState, claimed: bool) -> dict:
    if not actions and not claimed:
        return {"ok": True, "mobilityware_moves": 0, "solved": end.is_solved(), "checked": False}
    trial = root.clone()
    try:
        detail = replay_actions_detailed(trial, list(actions))
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "checked": True}
    solved_ok = trial.is_solved() == end.is_solved()
    claim_ok = (trial.is_solved() and len(trial.foundations) == 8 and not trial.stock) if claimed else True
    return {
        "ok": solved_ok and claim_ok,
        "checked": True,
        "mobilityware_moves": detail["mobilityware_moves"],
        "foundations": len(trial.foundations),
        "stock_remaining": len(trial.stock),
        "solved": trial.is_solved(),
        "explicit_commands": detail["explicit_commands"],
    }


def _remember(stats: _Stats) -> None:
    current = rss_mb()
    if current is None:
        return
    if stats.peak_rss is None or current > stats.peak_rss:
        stats.peak_rss = current


def _backtrack(line: _Line, dormant: List[_Dormant], failed: Dict[object, set], stats: _Stats):
    while dormant:
        item = dormant.pop()
        ident = _identity(item.line.state)
        if item.force_id in failed.get(ident, ()):
            continue
        stats.backtracks += 1
        stats.events.append(f"backtrack: try dormant {item.force_id}")
        return item.line, item.force_id
    return None


def _cycle(line: _Line, new_state: SpiderState, added: int) -> bool:
    key = _identity(new_state)
    if key == _identity(line.state):
        return False
    previous = line.seen.get(key)
    return previous is not None and line.g + added >= previous


def _clear_commitment(line: _Line) -> None:
    line.hold = False
    line.active_id = None
    line.remaining = ()
    line.active_kind = ""
    line.active_principles = ()


def _candidate_from_prep(option: PreparationOption, g: int) -> Candidate:
    return Candidate(
        candidate_id=option.objective_id,
        kind="PREPARE",
        purpose="Finish this preparation before dealing the next stock row.",
        principles=(2, 8, 9, 23, 24, 25, 26),
        actions=option.actions,
        objective=option.objective,
        immediate_cost=option.cost,
        cost_is_exact=True,
        expected_benefit=float(option.net),
        structural_risk=0.0,
        horizon="preparation then deal",
        feasibility="replayed",
        evidence=option.evidence,
        admissible_lb=0,
        projected=float(g + option.cost),
        solves=False,
        hold=True,
    )


def _finish_held(
    line: _Line,
    ctx: StrategicContext,
    choice: Candidate,
    profile: Profile,
    deadline: float,
    best_g: Dict[object, int],
    stats: _Stats,
) -> Tuple[bool, int]:
    """Play one step of a committed plan.

    The first value is true when the loop should start the next iteration.
    The second value is the change in the committed-step count.
    """

    execution = _execute(line.state, choice, profile, deadline - time.perf_counter())
    if execution[0] in {"achieved", "partial"} and _cycle(line, execution[2], execution[1]):
        execution = ("failed", 0, line.state, "repeat state at no better corrected cost", (), ())
    stats.attempted += 1
    stats.decisions.append(_decision(ctx, [choice], choice, "continued: committed plan", (), execution))
    if execution[0] in {"achieved", "partial"}:
        _apply(line, best_g, execution)
        if execution[0] == "achieved" or not execution[4]:
            stats.achieved += 1
            _clear_commitment(line)
            stats.events.append("replan: objective completed")
        else:
            stats.partial += 1
            line.hold = True
            line.active_id = choice.candidate_id
            line.remaining = execution[4]
            line.active_kind = choice.kind
            line.active_principles = choice.principles
        if len(line.state.foundations) > ctx.foundations:
            stats.events.append("replan: foundation removed")
        return True, 1
    stats.failed += 1
    stats.events.append("abandoned: committed plan step did not stay legal")
    _clear_commitment(line)
    return False, 0


def _foundation_goal(goal: str) -> bool:
    return goal in {"first-foundation", "foundations"}


def _annotate_stall(goal: str, state: SpiderState, lock: dict, stop_reason: str) -> str:
    if goal != "foundations":
        return stop_reason
    return f"{stop_reason}; {planning_stall_detail(state, lock)}"


def _record_foundation_proposal(proposal, stats, foundation_trace) -> None:
    for event in proposal.events:
        stats.events.append(event)
    if proposal.public:
        foundation_trace.append(
            {"reason": proposal.reason, "timeout": proposal.timeout, **proposal.public}
        )


def _recovery_candidate(line, deal_cards, deadline, foundation_cache, foundation_lock, failed, ident, stats):
    candidate, events = recover_foundation_step(
        line.state,
        deal_cards,
        line.g,
        foundation_cache,
        foundation_lock,
        tuple(failed.get(ident, ())),
        deadline - time.perf_counter(),
    )
    for event in events:
        stats.events.append(event)
    if candidate is None:
        return None
    return candidate, "selected: bounded recovery toward a buried foundation card"


def _proposal_blocked(failed, ident, lock) -> tuple:
    """Candidate ids the proposer must skip.

    ``fork_block`` belongs to one saved line. An empty block leaves the
    failure set unchanged, which is the single-line controller.
    """

    blocked = tuple(failed.get(ident, ()))
    extra = tuple((lock or {}).get("fork_block") or ())
    if not extra:
        return blocked
    present = set(blocked)
    return blocked + tuple(item for item in extra if item not in present)


def _frontier_on(profile: Profile, goal: str) -> bool:
    return goal in {"first-foundation", "foundations"} and int(profile.frontier_limit) > 1


def _retain_line(frontier, stats, line, lock, *, force_id, reason, label) -> None:
    if frontier is None or frontier.limit <= 1:
        return
    snapshot = line.snapshot()
    _accepted, event = frontier.consider(
        state=snapshot.state,
        g=snapshot.g,
        actions=tuple(snapshot.actions),
        lock=lock,
        force_id=force_id,
        reason=reason,
        label=label or "",
        payload=snapshot,
    )
    if event:
        stats.events.append(event)


def _queue_sibling_campaigns(frontier, stats, line, lock) -> None:
    """Keep campaigns the in-place switch will not take on this iteration."""

    if frontier is None or frontier.limit <= 1:
        return
    tried = set(lock.get("tried_labels") or [])
    current = lock.get("label")
    pending = [
        label
        for label in list(lock.get("alternatives") or [])
        if label and label != current and label not in tried
    ]
    for label in pending[1:frontier.proposals]:
        copied = deepcopy(lock)
        copied["hold_label"] = label
        copied["yield_to_alternative"] = False
        _retain_line(
            frontier,
            stats,
            line,
            copied,
            force_id=None,
            reason=f"campaign {label} held beside {current or 'the lock'}",
            label=label,
        )


def _adopt_keeping_siblings(frontier, stats, line, lock):
    _queue_sibling_campaigns(frontier, stats, line, lock)
    return adopt_alternative_foundation(lock)


def _resume_foundation_campaign(
    line,
    goal,
    deal_cards,
    profile,
    deadline,
    foundation_cache,
    foundation_lock,
    failed,
    ident,
    stats,
    foundation_trace,
    frontier=None,
):
    """Propose a foundation step after the one-ply list has nothing to play.

    An announced alternative is proposed here even when every portfolio
    candidate is already blocked. Two resumes per state, then one recovery.
    """

    if goal != "foundations" or line.hold:
        return None
    if deadline - time.perf_counter() < 0.05:
        return None
    counts = foundation_lock.setdefault("resume_counts", {})
    state_key = canonical_state_key(line.state)
    if counts.get(state_key, 0) >= 2:
        return _recovery_candidate(
            line, deal_cards, deadline, foundation_cache, foundation_lock, failed, ident, stats
        )
    counts[state_key] = counts.get(state_key, 0) + 1

    def _propose():
        proposal = propose_foundation_step(
            line.state,
            deal_cards,
            profile,
            deadline - time.perf_counter(),
            line.g,
            cache=foundation_cache,
            lock=foundation_lock,
            blocked=_proposal_blocked(failed, ident, foundation_lock),
        )
        _record_foundation_proposal(proposal, stats, foundation_trace)
        return proposal

    proposal = _propose()
    if proposal.candidate is not None:
        return proposal.candidate, proposal.reason
    if foundation_lock.get("yield_to_alternative"):
        foundation_lock["yield_to_alternative"] = False
        switched = _adopt_keeping_siblings(frontier, stats, line, foundation_lock)
        if switched:
            stats.events.append(f"foundation: {switched}")
            follow = _propose()
            if follow.candidate is not None:
                return follow.candidate, follow.reason
    return _recovery_candidate(
        line, deal_cards, deadline, foundation_cache, foundation_lock, failed, ident, stats
    )


def solve(
    state: SpiderState,
    profile: Profile,
    *,
    mode: str = "cold",
    incumbent_actions: Optional[Sequence[Action]] = None,
    incumbent_mw: Optional[int] = None,
    opening_g: int = 0,
    provenance_note: str = "",
    goal: str = "play",
    deal_cards: Optional[Sequence] = None,
    target_foundations: Optional[int] = None,
) -> SolveResult:
    """Search from ``state``. The caller's state is not mutated."""

    if mode not in {"cold", "optimise", "diagnose"}:
        raise ValueError(f"unknown mode {mode!r}")
    if goal not in {"play", "first-foundation", "foundations"}:
        raise ValueError(f"unknown goal {goal!r}")
    if goal == "first-foundation" and not deal_cards:
        raise ValueError("first-foundation goal requires the full deal")
    if goal == "foundations" and not deal_cards:
        raise ValueError("foundations goal requires the full deal")
    if goal == "first-foundation":
        foundation_target = 1
    elif goal == "foundations":
        foundation_target = 8 if target_foundations is None else int(target_foundations)
        if not 1 <= foundation_target <= 8:
            raise ValueError("target-foundations must be from 1 to 8")
    else:
        foundation_target = None
    if mode == "cold" and incumbent_actions:
        raise ValueError("cold mode does not accept an incumbent sequence")
    if mode == "optimise" and incumbent_mw is None:
        raise ValueError("optimise mode requires an incumbent corrected-MW ceiling")

    started = time.perf_counter()
    deadline = started + float(profile.time_limit_s)
    root = state.clone()
    root_key = _identity(root)
    line = _Line(root, int(opening_g), [], {root_key: int(opening_g)})
    dormant: List[_Dormant] = []
    failed: Dict[object, set] = {}
    best_g: Dict[object, int] = {root_key: int(opening_g)}
    cache: Dict[tuple, List[Candidate]] = {}
    width = int(profile.strategic_width)
    stats = _Stats()
    force_id: Optional[str] = None
    status = "STEP_LIMIT"
    stop_reason = "strategic step budget ended"
    commits = 0
    slice_origin_commits = 0
    slice_origin_attempts = 0
    played_edges = set()
    comparisons: Dict[object, Optional[DealComparison]] = {}
    saved_by_state: Dict[object, Tuple[PreparationOption, ...]] = {}
    revisited: set = set()
    released_soft: set = set()
    boost_ident = None
    foundation_cache: dict = {}
    foundation_lock: dict = {}
    foundation_trace: List[dict] = []
    start_foundations = len(root.foundations)
    last_foundation_g = int(opening_g)
    multiline = _frontier_on(profile, goal)
    frontier = StrategicFrontier(
        limit=profile.frontier_limit if multiline else 1,
        proposals=profile.proposals_per_decision,
    )
    branch_log: List[dict] = []
    best_branch: Optional[dict] = None
    success_status = {"SOLVED_VALID", "FOUNDATION_REACHED", "FOUNDATION_TARGET_REACHED"}

    def _remember_branch(status_now: str, reason_now: str, compete: bool = True) -> None:
        nonlocal best_branch
        if not multiline:
            return
        snap = line.snapshot()
        solved_now = status_now == "SOLVED_VALID" or snap.state.is_solved()
        rank = outcome_rank(snap.state, snap.g, solved=solved_now)
        record = {
            "status": status_now,
            "stop_reason": reason_now,
            "g": snap.g,
            "actions": tuple(snap.actions),
            "foundations": len(snap.state.foundations),
            "face_down": face_down_count(snap.state),
            "bonds": same_suit_bonds(snap.state),
            "adjusted_bonds": same_suit_bonds(snap.state) + 12 * len(snap.state.foundations),
            "stock": len(snap.state.stock),
            "label": foundation_lock.get("label"),
            "rank": rank,
            "payload": snap,
            "lock": deepcopy(foundation_lock),
        }
        branch_log.append(record)
        if compete and (best_branch is None or rank < best_branch["rank"]):
            best_branch = record

    def _install_node(node) -> None:
        nonlocal line, force_id, width, slice_origin_commits, slice_origin_attempts
        payload = node.payload
        if payload is not None and hasattr(payload, "snapshot"):
            line = payload.snapshot()
        else:
            ident_now = _identity(node.state)
            line = _Line(node.state.clone(), int(node.g), list(node.actions), {ident_now: int(node.g)})
        foundation_lock.clear()
        foundation_lock.update(deepcopy(node.lock))
        force_id = node.force_id
        if force_id:
            failed.get(_identity(line.state), set()).discard(force_id)
        dormant.clear()
        width = int(profile.strategic_width)
        stats.backtracks += 1
        stats.events.append(
            f"frontier: restore {node.reason} at g={node.g} label={node.label or 'none'}"
        )
        pinned = foundation_lock.pop("pinned_actions", None)
        if pinned and not line.remaining:
            line.remaining = tuple(pinned)
            line.hold = True
            line.active_id = "pinned:" + format_action(pinned[0])
            line.active_kind = "ACCESS"
            line.active_principles = (11, 12)
        slice_origin_commits = commits
        slice_origin_attempts = stats.attempted

    def _seed_divergences() -> None:
        """Queue unplayed legal moves when labels would otherwise repeat one history."""

        if not multiline or frontier.queue:
            return
        ident_now = _identity(line.state)
        legal = [action for action in all_legal_actions(line.state) if action != ("deal",)]
        last = line.actions[-1] if line.actions else None
        queued = 0
        for action in legal:
            if queued >= frontier.proposals:
                break
            if (ident_now, action) in played_edges:
                continue
            if covers_productive_run(line.state, action):
                continue
            if (
                last
                and last != ("deal",)
                and action[0] == last[1]
                and action[1] == last[0]
                and action[2] == last[2]
            ):
                continue
            copied = deepcopy(foundation_lock)
            copied["pinned_actions"] = [action]
            _retain_line(
                frontier,
                stats,
                line,
                copied,
                force_id=f"pinned:{format_action(action)}",
                reason=f"unplayed {format_action(action)}",
                label=foundation_lock.get("label") or "",
            )
            queued += 1

    def _handoff(reason: str, *, requeue: bool, remember: bool) -> bool:
        """Move to another queued line. A slice requeues the paused line after the pop."""

        if not multiline or time.perf_counter() >= deadline - 0.05:
            return False
        held = None
        label_now = foundation_lock.get("label") or ""
        if requeue:
            frontier.release(line.state, label_now, None)
            before = len(frontier.queue)
            _retain_line(
                frontier,
                stats,
                line,
                deepcopy(foundation_lock),
                force_id=None,
                reason=reason,
                label=label_now,
            )
            if len(frontier.queue) > before:
                held = frontier.queue.pop()
        if not frontier.queue:
            if held is not None:
                frontier.queue.append(held)
            return False
        if remember:
            _remember_branch("OPEN", reason, compete=False)
        node = frontier.pop_next()
        if held is not None:
            frontier.queue.append(held)
        if node is None:
            return False
        _install_node(node)
        return True

    def _continue_from_frontier(status_now: str, reason_now: str, remember: bool = True) -> bool:
        nonlocal status, stop_reason
        if not multiline:
            return False
        if status_now in success_status or status_now in {"TIME_LIMIT", "MEMORY_LIMIT", "STEP_LIMIT"}:
            return False
        if time.perf_counter() >= deadline - 0.05:
            return False
        if status_now == "PLANNING_STALL":
            _seed_divergences()
        if remember:
            _remember_branch(status_now, reason_now)
        node = frontier.pop_next()
        if node is None:
            return False
        _install_node(node)
        status = "STEP_LIMIT"
        stop_reason = "strategic step budget ended"
        return True

    while True:
        _remember(stats)
        if time.perf_counter() >= deadline:
            status, stop_reason = "TIME_LIMIT", "time budget ended before a solved terminal"
            break
        if stats.peak_rss is not None and stats.peak_rss > profile.rss_abort_mb:
            status, stop_reason = "MEMORY_LIMIT", "peak RSS exceeded the abort ceiling"
            break
        if commits >= profile.max_steps:
            status = "STEP_LIMIT"
            stop_reason = "strategic step budget ended"
            if multiline and frontier.queue:
                stop_reason += f"; still queued {len(frontier.queue)}"
            break
        new_attempts = stats.attempted - slice_origin_attempts
        new_commits = commits - slice_origin_commits
        if (
            multiline
            and profile.line_attempt_cap > 0
            and new_attempts >= profile.line_attempt_cap
            and frontier.queue
            and time.perf_counter() < deadline - 0.05
        ):
            stats.events.append("frontier: line attempt budget yielded to a queued line")
            if _handoff("line attempt budget yielded", requeue=False, remember=True):
                continue
        if (
            multiline
            and profile.slice_steps > 0
            and new_commits >= profile.slice_steps
            and frontier.queue
            and time.perf_counter() < deadline - 0.05
        ):
            stats.events.append("frontier: execution slice yielded to a queued line")
            if _handoff("execution slice yielded", requeue=True, remember=True):
                continue
        if stats.attempted > profile.max_steps * 4:
            if multiline and frontier.queue and time.perf_counter() < deadline - 0.05:
                stats.events.append("frontier: attempt ceiling yielded to a queued line")
                if _handoff("attempt ceiling yielded", requeue=False, remember=True):
                    continue
            status = "STEP_LIMIT"
            stop_reason = "strategic step budget ended"
            if multiline and frontier.queue:
                stop_reason += f"; still queued {len(frontier.queue)}"
            break
        if line.state.is_solved():
            status, stop_reason = "SOLVED_VALID", "terminal state reached"
            break

        if multiline:
            frontier.remember_visit(line.state, line.g, line.actions, foundation_lock)
            frontier.mark_expanded(line.state, foundation_lock.get("label") or "", None)

        ident = _identity(line.state)
        if ident in best_g and line.g > best_g[ident]:
            stats.events.append("transposition: discarded a more expensive ancestry")
            jumped = _backtrack(line, dormant, failed, stats)
            if jumped is None:
                status, stop_reason = "EXHAUSTED", "every retained line was more expensive than a known ancestry"
                if _continue_from_frontier(status, stop_reason):
                    continue
                break
            line, force_id = jumped
            continue
        bound = admissible_remaining(line.state)
        if incumbent_mw is not None and line.g + bound >= int(incumbent_mw):
            stats.events.append(
                f"incumbent bound: g {line.g} plus admissible {bound} cannot beat {incumbent_mw}"
            )
            jumped = _backtrack(line, dormant, failed, stats)
            if jumped is None:
                status, stop_reason = "EXHAUSTED", "incumbent bound pruned the remaining lines"
                if _continue_from_frontier(status, stop_reason):
                    continue
                break
            line, force_id = jumped
            continue

        if _foundation_goal(goal) and line.remaining[:1] == (("deal",),):
            stats.events.append("foundation: a bundled deal is reconsidered against the campaign")
            _clear_commitment(line)

        if line.hold and line.remaining:
            pending_action = line.remaining[0]
            if multiline and (ident, pending_action) in played_edges:
                frontier.same_moves += 1
                stats.events.append(
                    f"frontier: same move {format_action(pending_action)} already played from this state; "
                    "campaign labels are not a new history"
                )
                _clear_commitment(line)
            else:
                reason_abandon = abandonment_reason(line.state, line.remaining)
                if reason_abandon is not None:
                    stats.events.append(reason_abandon)
                    _clear_commitment(line)
                else:
                    held_ctx = build_context(line.state, line.g)
                    continuation = _retarget(line, held_ctx)
                    if continuation is None:
                        stats.events.append("abandoned: committed plan is no longer legal")
                        _clear_commitment(line)
                    else:
                        continuation.hold = True
                        advanced, delta = _finish_held(
                            line, held_ctx, continuation, profile, deadline, best_g, stats
                        )
                        commits += delta
                        if advanced and multiline:
                            played_edges.add((ident, pending_action))
                        if advanced:
                            continue

        ctx = build_context(line.state, line.g)
        blocked = tuple(sorted(failed.get(ident, ())))
        cache_key = (ident, line.g, blocked, width, profile.consult_portfolio)
        if cache_key in cache:
            stats.cache_hits += 1
            ranked = list(cache[cache_key])
        else:
            stats.cache_misses += 1
            ranked = build_candidates(ctx, profile, blocked_ids=blocked)
            cache[cache_key] = list(ranked)
        if line.remaining and line.active_id:
            continuation = _retarget(line, ctx)
            if continuation is not None:
                ranked = _insert(ranked, continuation)
        if not ranked:
            legal_now = all_legal_actions(line.state)
            blocked_ids = failed.setdefault(ident, set())
            if legal_now and ident not in released_soft:
                soft = {item for item in blocked_ids if soft_failure_id(item)}
                if soft:
                    blocked_ids.difference_update(soft)
                    released_soft.add(ident)
                    boost_ident = ident
                    stats.events.append(
                        "retry: a missed realisation is not proof the objective is impossible"
                    )
                    continue
            if legal_now:
                resumed = None
                if goal == "foundations":
                    resumed = _resume_foundation_campaign(
                        line,
                        goal,
                        deal_cards,
                        profile,
                        deadline,
                        foundation_cache,
                        foundation_lock,
                        failed,
                        ident,
                        stats,
                        foundation_trace,
                        frontier,
                    )
                if resumed is not None:
                    candidate, resume_reason = resumed
                    ranked = [candidate]
                    foundation_lock["forced_foundation_id"] = candidate.candidate_id
                    foundation_lock["forced_foundation_reason"] = resume_reason
                else:
                    stall_kind = classify_stall(
                        legal_count=len(legal_now),
                        generated_count=len(blocked_ids) + len(ranked),
                        visible_count=0,
                        suppressed=len(blocked_ids),
                    )
                    stats.events.append(
                        f"planning failure: {len(legal_now)} legal moves remain after objectives were blocked"
                    )
                    if _foundation_goal(goal):
                        status, stop_reason = strategic_stop_status(
                            goal=goal,
                            legal_count=len(legal_now),
                            proved_no_legal_continuation=False,
                        )
                        stop_reason = _annotate_stall(
                            goal,
                            line.state,
                            foundation_lock,
                            f"{stop_reason}; {stall_kind}",
                        )
                    else:
                        status = "EXHAUSTED"
                        stop_reason = f"planning failure: {len(legal_now)} legal moves remain; {stall_kind}"
                    if _continue_from_frontier(status, stop_reason):
                        continue
                    break
            stats.events.append("no legal objective remained")
            jumped = _backtrack(line, dormant, failed, stats)
            if jumped is None:
                status, stop_reason = "EXHAUSTED", "no legal continuation under the current restrictions"
                if multiline and frontier.queue:
                    stop_reason += f"; still queued {len(frontier.queue)}"
                    if _continue_from_frontier(status, stop_reason):
                        continue
                break
            line, force_id = jumped
            continue

        considered = list(ranked[:width])
        if force_id:
            for item in ranked:
                if item.candidate_id == force_id and item not in considered:
                    considered.append(item)
                    break
        active_open = bool(line.remaining and line.active_id)
        active_projected = None
        if active_open:
            for item in ranked:
                if item.candidate_id == line.active_id:
                    active_projected = item.projected
                    if all(existing.candidate_id != item.candidate_id for existing in considered):
                        considered.append(item)
                    break
        considered.sort(key=lambda item: item.rank_key())
        choice, reason = select_candidate(
            considered,
            active_id=line.active_id,
            active_projected=active_projected,
            active_open=active_open,
            margin=profile.commitment_margin,
            force_id=force_id,
        )
        force_id = None
        foundation_locked = False
        forced_foundation = foundation_lock.pop("forced_foundation_id", None)
        if forced_foundation:
            match = next(
                (item for item in considered if item.candidate_id == forced_foundation),
                None,
            )
            if match is not None:
                choice = match
                reason = foundation_lock.pop("forced_foundation_reason", reason)
                foundation_locked = True
        if not foundation_locked and _foundation_goal(goal) and not line.hold:
            proposal = propose_foundation_step(
                line.state,
                deal_cards,
                profile,
                deadline - time.perf_counter(),
                line.g,
                cache=foundation_cache,
                lock=foundation_lock,
                blocked=_proposal_blocked(failed, ident, foundation_lock),
            )
            for event in proposal.events:
                stats.events.append(event)
            if proposal.public:
                foundation_trace.append(
                    {"reason": proposal.reason, "timeout": proposal.timeout, **proposal.public}
                )
            if proposal.candidate is not None:
                choice = proposal.candidate
                reason = proposal.reason
                foundation_locked = True
                if all(item.candidate_id != choice.candidate_id for item in considered):
                    considered.append(choice)
                alternate = foundation_lock.pop("pending_alternate_bottleneck", None)
                if multiline and alternate:
                    copied = deepcopy(foundation_lock)
                    copied["pinned_actions"] = list(alternate)
                    _retain_line(
                        frontier,
                        stats,
                        line,
                        copied,
                        force_id="bottleneck-alt",
                        reason="alternate foundation bottleneck",
                        label=foundation_lock.get("label") or "",
                    )
            elif (
                proposal.candidate is None
                and proposal.block_deal
                and goal == "foundations"
                and foundation_lock.get("yield_to_alternative")
            ):
                # The locked campaign has named why it cannot move. Play the
                # announced alternative instead of an unrelated portfolio action.
                foundation_lock["yield_to_alternative"] = False
                switched = _adopt_keeping_siblings(frontier, stats, line, foundation_lock)
                if switched:
                    stats.events.append(f"foundation: {switched}")
                    continue
                recovered = _recovery_candidate(
                    line,
                    deal_cards,
                    deadline,
                    foundation_cache,
                    foundation_lock,
                    failed,
                    ident,
                    stats,
                )
                if recovered is not None:
                    choice, reason = recovered
                    foundation_locked = True
                    if all(item.candidate_id != choice.candidate_id for item in considered):
                        considered.append(choice)
                else:
                    legal_left = [
                        action for action in all_legal_actions(line.state) if action != ("deal",)
                    ]
                    status, stop_reason = strategic_stop_status(
                        goal=goal,
                        legal_count=len(legal_left),
                        proved_no_legal_continuation=not legal_left,
                    )
                    stop_reason = _annotate_stall(
                        goal,
                        line.state,
                        foundation_lock,
                        f"{stop_reason}; no campaign offered an executable step",
                    )
                    if _continue_from_frontier(status, stop_reason):
                        continue
                    break
            elif proposal.block_deal and _choice_deals(choice):
                useful = _moves_that_meet_their_purpose(line.state, line.g, ctx, ranked)
                if useful:
                    choice = useful[0]
                    reason = "selected: foundation prerequisites are still open, so the deal waits"
                    foundation_locked = True
                    if all(item.candidate_id != choice.candidate_id for item in considered):
                        considered.append(choice)
                else:
                    # No purpose-met tableau move. Dealing would cover the
                    # open prerequisite, so keep the row and try another line.
                    stats.events.append(
                        "foundation: deal refused while a prerequisite remains open"
                    )
                    failed.setdefault(ident, set()).add(choice.candidate_id)
                    jumped = _backtrack(line, dormant, failed, stats)
                    if jumped is None:
                        if goal == "foundations":
                            switched = _adopt_keeping_siblings(
                                frontier, stats, line, foundation_lock
                            )
                            if switched:
                                stats.events.append(f"foundation: {switched}")
                                continue
                        legal_left = [
                            action for action in all_legal_actions(line.state) if action != ("deal",)
                        ]
                        status, stop_reason = strategic_stop_status(
                            goal=goal,
                            legal_count=len(legal_left),
                            proved_no_legal_continuation=not legal_left,
                        )
                        if legal_left:
                            stop_reason = (
                                f"{stop_reason}; foundation prerequisites remain open "
                                "and no purpose-met substitute was legal"
                            )
                        stop_reason = _annotate_stall(
                            goal, line.state, foundation_lock, stop_reason
                        )
                        if _continue_from_frontier(status, stop_reason):
                            continue
                        break
                    line, force_id = jumped
                    continue
        if (
            not foundation_locked
            and not line.hold
            and choice.kind in {"DEAL_NOW", "STRETCH"}
            and line.state.can_deal()
        ):
            if ident not in comparisons:
                comparisons[ident] = compare_before_deal(
                    line.state,
                    ranked,
                    profile,
                    deadline - time.perf_counter(),
                )
                compared = comparisons[ident]
                if compared is not None:
                    prep_text = "none" if compared.prep_net is None else f"{compared.prep_net:.2f}"
                    stats.events.append(
                        f"compare: {compared.choice} deal_net={compared.deal_net:.2f} prep_net={prep_text}"
                    )
            comparison = comparisons.get(ident)
            if comparison is not None and comparison.saved:
                saved_by_state[ident] = comparison.saved
            blocked_now = failed.get(ident, ())
            if (
                comparison is not None
                and comparison.choice == "prepare"
                and comparison.option is not None
                and comparison.option.objective_id not in blocked_now
            ):
                if all(item.candidate_id != choice.candidate_id for item in considered):
                    considered.append(choice)
                for item in ranked:
                    if item.kind == "DEAL_NOW" and all(
                        existing.candidate_id != item.candidate_id for existing in considered
                    ):
                        considered.append(item)
                        break
                choice = _candidate_from_prep(comparison.option, line.g)
                reason = "selected: measured preparation beats dealing now"
            elif comparison is not None and choice.kind == "DEAL_NOW" and comparison.evidence:
                choice.evidence = tuple(choice.evidence) + tuple(comparison.evidence)
        if _foundation_goal(goal):
            guarded, guard_note = choose_without_unjustified_cover(line.state, choice, considered)
            if guard_note:
                stats.events.append(guard_note)
                choice = guarded
                reason = "selected: preserve a productive run; the covering move is not a justified park"
        dormant_ids = [item.candidate_id for item in considered if item.candidate_id != choice.candidate_id]
        # Store the worst sibling first so the next backtrack pops the best one.
        # Popping insertion order would resume the weakest avenue and thrash.
        siblings = [item for item in considered if item.candidate_id != choice.candidate_id]
        for item in reversed(siblings):
            if len(dormant) >= 16:
                dormant.pop(0)
            dormant.append(_Dormant(line.snapshot(), item.candidate_id))

        exec_profile = profile
        if boost_ident == ident:
            exec_profile = profile.with_overrides(
                tactical_max_cost=max(profile.tactical_max_cost, 6),
                tactical_nodes=max(profile.tactical_nodes, 1500),
                tactical_time_s=min(2.0, max(profile.tactical_time_s, 1.0)),
            )
            boost_ident = None
        if multiline and choice.actions and not line.hold and (ident, choice.actions[0]) in played_edges:
            frontier.same_moves += 1
            stats.events.append(
                f"frontier: same move {format_action(choice.actions[0])} already played from this state; "
                "campaign labels are not a new history"
            )
            failed.setdefault(ident, set()).add(choice.candidate_id)
            jumped = _backtrack(line, dormant, failed, stats)
            if jumped is not None:
                line, force_id = jumped
                continue
            already_logged = any(tuple(record["actions"]) == tuple(line.actions) for record in branch_log)
            if _handoff("same move suppressed", requeue=False, remember=not already_logged):
                continue
            _seed_divergences()
            if _continue_from_frontier(
                "PLANNING_STALL",
                "same move already played and no different line remained",
                remember=False,
            ):
                continue
            status = "PLANNING_STALL"
            stop_reason = "same move already played and no different line remained"
            stop_reason = _annotate_stall(goal, line.state, foundation_lock, stop_reason)
            break
        if multiline and choice.actions[:1] == (("deal",),):
            label_now = foundation_lock.get("label") or ""
            deal_id = f"DEAL:{label_now}" if label_now else ""
            kept = 0
            for item in considered:
                if kept >= frontier.proposals:
                    break
                if item.candidate_id == choice.candidate_id or item.actions[:1] == (("deal",),):
                    continue
                copied = deepcopy(foundation_lock)
                if deal_id:
                    current_block = tuple(copied.get("fork_block") or ())
                    if deal_id not in current_block:
                        copied["fork_block"] = current_block + (deal_id,)
                _retain_line(
                    frontier,
                    stats,
                    line,
                    copied,
                    force_id=item.candidate_id,
                    reason=f"{item.candidate_id} retained instead of the deal",
                    label=label_now,
                )
                kept += 1
        deal_snapshot = line.snapshot() if choice.actions[:1] == (("deal",),) else None
        execution = _execute(line.state, choice, exec_profile, deadline - time.perf_counter())
        if execution[0] in {"achieved", "partial"} and _cycle(line, execution[2], execution[1]):
            execution = ("failed", 0, line.state, "repeat state at no better corrected cost", (), ())
        stats.attempted += 1
        stats.decisions.append(_decision(ctx, considered, choice, reason, dormant_ids, execution))

        if execution[0] in {"achieved", "partial"}:
            if multiline and execution[5]:
                for action in execution[5]:
                    played_edges.add((ident, action))
            _apply(line, best_g, execution)
            # A committed step stays committed. Sibling alternatives from
            # before this step are not allowed to erase it.
            dormant[:] = [item for item in dormant if len(item.line.actions) >= len(line.actions)]
            commits += 1
            if execution[0] == "achieved" or not execution[4]:
                stats.achieved += 1
                _clear_commitment(line)
            else:
                stats.partial += 1
                line.hold = bool(choice.hold)
                line.active_id = choice.candidate_id
                line.remaining = execution[4]
                line.active_kind = choice.kind
                line.active_principles = choice.principles
            if len(line.state.foundations) > ctx.foundations:
                stats.events.append("replan: foundation removed")
            elif len(line.state.stock) < len(ctx.state.stock):
                stats.events.append("replan: stock dealt")
            elif execution[0] == "achieved":
                stats.events.append("replan: objective completed")
            if _foundation_goal(goal) and foundation_locked and execution[0] in {"achieved", "partial"}:
                foundation_lock["cost_invested"] = foundation_lock.get("cost_invested", 0) + int(execution[1])
            removed_now = _foundation_goal(goal) and len(line.state.foundations) > ctx.foundations
            if removed_now:
                sequence = line.state.foundations[-1]
                removed_label = foundation_lock.get("label") or foundation_lock.get("epoch_label")
                campaign_cost = int(line.g) - int(last_foundation_g)
                assessment = structural_assessment(line.state)
                assessment["foundation_aware_bonds"] = assessment["bonds"] + 12 * assessment["foundations"]
                assessment["legal_moves"] = len(all_legal_actions(line.state))
                assessment["foundation_suits"] = [item[0].suit for item in line.state.foundations if item]
                foundation_trace.append(
                    {
                        "reason": "foundation completed",
                        "label": removed_label,
                        "removed_suit": sequence[0].suit if sequence else "",
                        "cards": [str(card) for card in sequence],
                        "exact_cost": campaign_cost,
                        "step_cost": int(execution[1]),
                        "cumulative_g": line.g,
                        "foundations": len(line.state.foundations),
                        "face_down": assessment["face_down"],
                        "stock_cards": assessment["stock_cards"],
                        "bonds": assessment["bonds"],
                        "foundation_aware_bonds": assessment["foundation_aware_bonds"],
                        "admissible_remaining": assessment["admissible_remaining"],
                        "heuristic_remaining": assessment["heuristic_remaining"],
                        "legal_moves": assessment["legal_moves"],
                        "empty_columns": assessment["empty_columns"],
                        "foundation_suits": list(assessment["foundation_suits"]),
                        "assessment": assessment,
                    }
                )
                close_foundation_campaign(
                    foundation_lock,
                    reason=f"{removed_label} removed at corrected cost {campaign_cost}",
                    exact_cost=campaign_cost,
                    cumulative_g=line.g,
                    label=removed_label,
                )
                last_foundation_g = int(line.g)
                try:
                    follow_views = rank_foundations(line.state, deal_cards, cache=foundation_cache)
                except (ValueError, KeyError):
                    follow_views = ()
                if follow_views:
                    nxt = follow_views[0]
                    stats.events.append(
                        f"replan: foundation campaign after removal; next {nxt.label} "
                        f"epoch {nxt.target_epoch} cost {nxt.estimated_cost:.1f}"
                    )
                    foundation_trace.append(
                        {
                            "reason": "after removal",
                            "label": nxt.label,
                            "target_epoch": nxt.target_epoch,
                            "estimated_cost": nxt.estimated_cost,
                            "theoretically_available": nxt.theoretically_available,
                            "reasons": list(nxt.reasons[:4]),
                        }
                    )
                else:
                    stats.events.append("replan: foundation campaign after removal")
            if line.state.is_solved():
                status, stop_reason = "SOLVED_VALID", "terminal state reached"
                break
            if removed_now:
                gained = len(line.state.foundations) - start_foundations
                if goal == "first-foundation" or gained >= int(foundation_target or 1):
                    if goal == "first-foundation":
                        status = "FOUNDATION_REACHED"
                        stop_reason = (
                            "first foundation completed; this is a partial research trajectory, "
                            "not a finished game"
                        )
                    else:
                        status = "FOUNDATION_TARGET_REACHED"
                        stop_reason = (
                            f"foundation target {foundation_target} reached at corrected g {line.g}; "
                            "this is a partial research trajectory, not a finished game"
                        )
                    break
                stats.events.append(
                    "replan: closed completed campaign; the next foundation gets a new horizon"
                )
                if multiline and follow_views:
                    primary = follow_views[0].label
                    names = [item.label for item in follow_views]
                    for view in list(follow_views)[1:1 + frontier.proposals]:
                        copied = deepcopy(foundation_lock)
                        copied["hold_label"] = view.label
                        copied["label"] = view.label
                        copied["alternatives"] = list(names)
                        copied["yield_to_alternative"] = False
                        _retain_line(
                            frontier,
                            stats,
                            line,
                            copied,
                            force_id=None,
                            reason=f"after removal try {view.label} instead of {primary}",
                            label=view.label,
                        )
                continue
            if (
                deal_snapshot is not None
                and execution[5] == (("deal",),)
                and _revisit_unproductive_deal(
                    line,
                    deal_snapshot,
                    ident,
                    saved_by_state.get(ident, ()),
                    revisited,
                    dormant,
                    stats,
                )
            ):
                commits -= 1
                continue
            continue

        stats.failed += 1
        failed.setdefault(ident, set()).add(choice.candidate_id)
        _clear_commitment(line)
        jumped = _backtrack(line, dormant, failed, stats)
        if jumped is not None:
            line, force_id = jumped
            continue
        if width < profile.max_width:
            width += 1
            stats.widens += 1
            stats.events.append(f"widen: strategic width is now {width}")
            continue
        if _foundation_goal(goal):
            if goal == "foundations":
                switched = _adopt_keeping_siblings(frontier, stats, line, foundation_lock)
                if switched:
                    stats.events.append(f"foundation: {switched}")
                    continue
            legal_left = [action for action in all_legal_actions(line.state) if action != ("deal",)]
            status, stop_reason = strategic_stop_status(
                goal=goal,
                legal_count=len(legal_left),
                proved_no_legal_continuation=not legal_left,
            )
            stop_reason = _annotate_stall(goal, line.state, foundation_lock, stop_reason)
        else:
            status, stop_reason = "EXHAUSTED", "principal objective failed and no dormant alternative remained"
        if _continue_from_frontier(status, stop_reason):
            continue
        break

    if multiline:
        already = (
            branch_log
            and branch_log[-1]["g"] == line.g
            and branch_log[-1]["actions"] == tuple(line.actions)
        )
        if not already:
            _remember_branch(status, stop_reason)
        current_rank = outcome_rank(
            line.state,
            line.g,
            solved=status == "SOLVED_VALID" or line.state.is_solved(),
        )
        if (
            status not in success_status
            and best_branch is not None
            and best_branch["rank"] < current_rank
        ):
            chosen = best_branch
            line = chosen["payload"]
            foundation_lock.clear()
            foundation_lock.update(deepcopy(chosen["lock"]))
            status = chosen["status"]
            stop_reason = chosen["stop_reason"]
            stats.events.append(
                f"frontier: report g={chosen['g']} foundations={chosen['foundations']} "
                f"face-down={chosen['face_down']} over a later line"
            )
        if status == "PLANNING_STALL":
            stop_reason = (
                f"{stop_reason}; alternative lines explored {frontier.explored}; "
                f"retained {frontier.generated}; still queued {len(frontier.queue)}; "
                f"transpositions {frontier.transpositions}"
            )
        stats.events.append(
            f"frontier: generated {frontier.generated} explored {frontier.explored} "
            f"transpositions {frontier.transpositions} same-moves {frontier.same_moves} "
            f"still queued {len(frontier.queue)}"
        )

    kernel_info = None
    portfolio_stopped = stop_reason in {
        "no legal continuation under the current restrictions",
        "principal objective failed and no dormant alternative remained",
    } or stop_reason.startswith("planning failure:")
    if (
        goal == "play"
        and status == "EXHAUSTED"
        and portfolio_stopped
        and not line.state.is_solved()
        and all_legal_actions(line.state)
    ):
        kernel_info = _kernel_fallback(line, profile, deadline, incumbent_mw)
        if kernel_info is not None:
            stats.events.append(kernel_info["event"])
            if kernel_info["solved"]:
                status = "SOLVED_VALID"
                stop_reason = "constructive fallback reached a terminal after the strategic portfolio stopped"
            elif kernel_info["stop_reason"] == "time limit":
                status = "TIME_LIMIT"
                stop_reason = "strategic portfolio stopped; constructive fallback then hit the time budget"
            elif kernel_info["stop_reason"] == "rss abort":
                status = "MEMORY_LIMIT"
                stop_reason = "strategic portfolio stopped; constructive fallback hit the memory ceiling"
            else:
                stop_reason = (
                    "strategic portfolio stopped; constructive fallback then stopped: "
                    + str(kernel_info["stop_reason"])
                )

    replay = _validate(root, line.actions, line.state, status == "SOLVED_VALID")
    if status == "SOLVED_VALID" and not (replay and replay.get("ok")):
        status = "INVALID"
        stop_reason = "claimed terminal failed independent replay"
    same_as_incumbent = bool(incumbent_actions) and list(incumbent_actions) == list(line.actions)
    discovery = status == "SOLVED_VALID" and mode in {"cold", "optimise"} and not same_as_incumbent
    provenance = {
        "mode": mode,
        "goal": goal,
        "note": provenance_note,
        "incumbent_mw": incumbent_mw,
        "prefix_injected": False,
        "assisted_suffix": False,
        "new_discovery": discovery,
        "reproduced_incumbent": bool(status == "SOLVED_VALID" and same_as_incumbent),
        "kernel_fallback": kernel_info,
        "partial_trajectory": status in {"FOUNDATION_REACHED", "FOUNDATION_TARGET_REACHED"},
        "target_foundations": foundation_target,
        "completed_campaigns": list(foundation_lock.get("completed") or []),
        "foundation": foundation_trace[-12:],
        "frontier": _frontier_provenance(root, frontier, branch_log, multiline, profile, started, status),
    }
    _remember(stats)
    return SolveResult(
        status=status,
        mode=mode,
        actions=tuple(line.actions),
        cumulative_g=line.g,
        suffix_mw=line.g - int(opening_g),
        solved=bool(line.state.is_solved() and status == "SOLVED_VALID"),
        foundations=len(line.state.foundations),
        stock_rows=len(line.state.stock) // 10,
        elapsed_s=time.perf_counter() - started,
        peak_rss_mb=stats.peak_rss,
        unique_states=len(best_g),
        objectives_attempted=stats.attempted,
        objectives_achieved=stats.achieved,
        objectives_failed=stats.failed,
        objectives_partial=stats.partial,
        backtracks=stats.backtracks,
        widens=stats.widens,
        deals=sum(1 for action in line.actions if action == ("deal",)),
        decisions=tuple(stats.decisions),
        events=tuple(stats.events),
        provenance=provenance,
        replay=replay,
        cache_hits=stats.cache_hits,
        cache_misses=stats.cache_misses,
        profile=_profile_dict(profile),
        stop_reason=stop_reason,
    )


def _frontier_provenance(root, frontier, branch_log, multiline, profile, started, status) -> dict:
    """Serializable frontier report. Every stored line is replay-checked."""

    reported = []
    for record in branch_log:
        trial = root.clone()
        replay_ok = True
        try:
            for action in record["actions"]:
                apply_action(trial, action)
            replay_ok = _identity(trial) == _identity(record["payload"].state)
        except ValueError:
            replay_ok = False
        reported.append(
            {
                "status": record["status"],
                "stop_reason": record["stop_reason"],
                "g": record["g"],
                "foundations": record["foundations"],
                "face_down": record["face_down"],
                "bonds": record["bonds"],
                "adjusted_bonds": record["adjusted_bonds"],
                "stock": record["stock"],
                "label": record["label"],
                "actions": [format_action(action) for action in record["actions"]],
                "replay_ok": replay_ok,
            }
        )
    elapsed = time.perf_counter() - started
    return {
        "enabled": bool(multiline),
        "limit": int(profile.frontier_limit),
        "proposals_per_decision": int(profile.proposals_per_decision),
        "generated": frontier.generated,
        "explored": frontier.explored,
        "transpositions": frontier.transpositions,
        "merges": frontier.merges,
        "dropped_full": frontier.dropped_full,
        "replaced": frontier.replaced,
        "same_moves": frontier.same_moves,
        "unique_histories": len({tuple(item["actions"]) for item in reported}),
        "still_queued": len(frontier.queue),
        "pending": frontier.pending(),
        "branches": reported,
        "budget": {
            "time_limit_s": profile.time_limit_s,
            "elapsed_s": round(elapsed, 3),
            "remaining_s": round(max(0.0, float(profile.time_limit_s) - elapsed), 3),
            "stop": status,
        },
        "dominance": (
            "Identical physical states keep the cheapest corrected ancestry. "
            "A more expensive visit adds its campaign label to that ancestry "
            "instead of replacing it. Equal cost with a different label or "
            "forced candidate stays as its own line. Replaying the same action "
            "from that state under another label is one physical history. "
            "Heuristics order the queue. A full queue leaves a line unexpanded "
            "and does not mark it exhausted. Admissible cost does not prune "
            "inside the frontier. Restoring a line spends new actions only; "
            "the ancestry length is not a per-line step limit."
        ),
    }


def _choice_deals(choice) -> bool:
    return choice.kind == "DEAL_NOW" or choice.actions[:1] == (("deal",),)


def _moves_that_meet_their_purpose(state, g, ctx, ranked):
    """Tableau moves whose declared purpose holds on the resulting state.

    A blocked deal must not be replaced by a move the executor will reject.
    That rejection loop spends the step budget without changing the position.
    """

    useful = []
    seen = set()
    pool = [item for item in ranked if item.actions[:1] not in ((), (("deal",),))]
    scored = {item.actions[0] for item in pool if item.actions}
    for action in all_legal_actions(state):
        if action == ("deal",) or action in scored:
            continue
        pool.append(_score_action(state, g, action, ctx))
    for item in pool:
        action = item.actions[0]
        if action in seen or action == ("deal",):
            continue
        seen.add(action)
        trial = state.clone()
        try:
            apply_action(trial, action)
        except ValueError:
            continue
        if item.hold or _purpose_met(item.kind, state, trial):
            useful.append(item)
    useful.sort(key=lambda item: item.rank_key())
    return useful


def _constructive_lane(state: SpiderState, g: int) -> tuple:
    """Prefer access, construction, and foundations before raw cheapness."""

    return (face_down_count(state), -same_suit_bonds(state), -len(state.foundations), int(g))


def _revisit_unproductive_deal(
    line: _Line,
    snapshot: _Line,
    key: object,
    saved: Tuple[PreparationOption, ...],
    revisited: set,
    dormant: List[_Dormant],
    stats: _Stats,
) -> bool:
    """Undo a deal that exposed nothing and try a saved preparation instead."""

    if key in revisited:
        return False
    useful = [item for item in saved if item.fd_gain >= 1 or item.found_gain >= 1]
    if not useful:
        return False
    before = snapshot.state
    if face_down_count(before) > face_down_count(line.state):
        return False
    if same_suit_bonds(line.state) > same_suit_bonds(before):
        return False
    if len(line.state.foundations) > len(before.foundations):
        return False
    useful.sort(key=lambda item: item.net, reverse=True)
    chosen = useful[0]
    revisited.add(key)
    line.state = snapshot.state
    line.g = snapshot.g
    line.actions = list(snapshot.actions)
    line.seen = dict(snapshot.seen)
    line.hold = True
    line.remaining = chosen.actions
    line.active_id = chosen.objective_id
    line.active_kind = "PREPARE"
    line.active_principles = (2, 8, 23, 24, 25)
    dormant.clear()
    if stats.achieved > 0:
        stats.achieved -= 1
    elif stats.partial > 0:
        stats.partial -= 1
    stats.backtracks += 1
    stats.events.append("revisit: dealing did not expose or build; trying the saved preparation")
    return True


def _kernel_fallback(
    line: _Line,
    profile: Profile,
    deadline: float,
    incumbent_mw: Optional[int],
) -> Optional[dict]:
    """Spend leftover budget on constructive progress, not the cheapest deals.

    The strategic portfolio has already stopped. This does not restart a
    campaign and it does not read a known solution. A terminal is accepted
    only when the caller replays the combined action list. The lane key is
    ordering only. Admissible bounds remain the only pruning rule.
    """

    remaining = deadline - time.perf_counter()
    if remaining < 1.0:
        return None
    started = time.perf_counter()
    found = run_search(
        [{"g": line.g, "ordered_digest": pack_state(line.state).hex()}],
        limits=SearchLimits(
            max_unique=400_000,
            time_limit_s=remaining,
            rss_abort_mb=float(profile.rss_abort_mb),
            max_depth=None,
            cost_ceiling=None if incumbent_mw is None else int(incumbent_mw) - 1,
        ),
        identity_fn=pack_state,
        store_fn=pack_state,
        lane_names=("constructive",),
        lane_key_fns=(_constructive_lane,),
        lower_bound_fn=lambda state, g: admissible_remaining(state),
        stop_on_first_terminal=True,
    )
    solved = bool(found.terminals)
    if solved:
        path = reconstruct_path(found.nodes, int(found.terminals[0]["node"]))
        trial = line.state.clone()
        for action in path:
            apply_action(trial, action)
            line.actions.append(action)
        line.g = int(found.terminals[0]["g"])
        line.state = trial
    event = (
        f"fallback: constructive kernel stop={found.stop_reason} unique={found.unique} "
        f"expanded={found.expanded} solved={solved}"
    )
    return {
        "used": True,
        "stop_reason": found.stop_reason,
        "unique": found.unique,
        "expanded": found.expanded,
        "elapsed_s": round(time.perf_counter() - started, 3),
        "solved": solved,
        "event": event,
    }


def _apply(line: _Line, best_g: Dict[object, int], execution) -> None:
    _status, cost, new_state, _note, _remaining, applied = execution
    line.actions.extend(applied)
    line.g += int(cost)
    line.state = new_state
    key = _identity(new_state)
    line.seen[key] = line.g
    previous = best_g.get(key)
    if previous is None or line.g < previous:
        best_g[key] = line.g
