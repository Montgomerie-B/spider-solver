"""Research adapter: execute a verified short plan without a minimum certificate.

Both modes share one admission and probe procedure. The only difference is
which probed plan they play. An unfinished witness is a legal plan and its
realised cost. It is not a minimum, and UNKNOWN alternatives stay available.

This module does not read a reference route. Callers pass a state. Official
paired episodes stay behind ``confirm_official`` so unit tests cannot launch
them by importing the module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter, process_time
from typing import Callable, Optional, Sequence, Tuple

from spider.dependency_options import (
    build_option,
    obligations_match_state,
    rebuild_obligations,
    select_dependency_portfolio,
)
from spider.engine import SpiderState
from spider.packed_state import pack_state, unpack_state
from spider.practical_witness_manifest import (
    EPISODE_ADDITIONAL_PAID,
    EPISODE_PLANNING_DECISIONS,
    EPISODE_PRIMITIVE_ACTIONS,
    EPISODE_PROBE_IDENTITIES,
    EPISODE_RSS_MB,
    EPISODE_WALL_S,
    PROBE_COST_CEILING,
    PROBE_MAX_UNIQUE,
    PROBE_RSS_ABORT_MB,
    PROBE_SLOTS,
    PROBE_TIME_LIMIT_S,
    REVEAL_GOAL,
    WORKERS,
    FrozenRoot,
    materialize_root,
    mode_order,
    policy_specification,
)
from spider.research_actions import (
    all_legal_actions,
    apply_action,
    face_down_count,
    is_deal,
    rss_mb,
    step_cost,
)
from spider.search_kernel import SearchLimits, run_search
from spider.solution_archive import validate_solution

_VERIFIED = frozenset({"exact", "upper-unfinished"})
RECOMMENDATIONS = {
    "PRACTICAL_SIGNAL_FOUND": (
        "Report a within-deal play preference only, and leave the frozen "
        "exact-comparison gate unchanged."
    ),
    "NO_CLEAR_BENEFIT": (
        "Leave the probe caps, budgets, and selector unchanged."
    ),
    "PROGRESS_AFTER_ESCAPE": (
        "Report the within-deal continuation only. Leave the default cycle "
        "guard, probe caps, and selector unchanged."
    ),
    "ESCAPE_ONLY_NO_CLEAR_GAME_BENEFIT": (
        "Leave the default cycle guard unchanged. The opt-in escape did not "
        "show a clear foundation or hidden-card benefit."
    ),
    "CORRECTNESS_BLOCKER": (
        "Preserve the trace and leave the engine and search kernel unchanged."
    ),
}
_NO_FRESH_DETAIL = (
    "episode-local: no affordable unseen or cheaper successor remains; "
    "not global exhaustion and not an unsolvable position"
)


@dataclass(frozen=True)
class EpisodeBudget:
    """Episode allowance and the per-probe caps it may only tighten."""

    wall_s: float = EPISODE_WALL_S
    additional_paid: int = EPISODE_ADDITIONAL_PAID
    primitive_actions: int = EPISODE_PRIMITIVE_ACTIONS
    planning_decisions: int = EPISODE_PLANNING_DECISIONS
    probe_identities: int = EPISODE_PROBE_IDENTITIES
    rss_mb: float = EPISODE_RSS_MB
    probe_max_unique: int = PROBE_MAX_UNIQUE
    probe_time_s: float = PROBE_TIME_LIMIT_S
    probe_rss_mb: float = PROBE_RSS_ABORT_MB
    probe_cost_ceiling: int = PROBE_COST_CEILING
    probe_slots: int = PROBE_SLOTS
    workers: int = WORKERS


@dataclass(frozen=True)
class ProbeEvidence:
    """One probed candidate. ``not-probed`` is never stored here."""

    option_id: str
    baseline_index: int
    prefix_actions: Tuple
    plan: Tuple
    prefix_cost: int
    continuation: Tuple
    continuation_cost: Optional[int]
    total_cost: Optional[int]
    status: str
    stop_reason: str
    kernel_called: bool
    unique: int
    admissible_bound: bool
    scoped_minimum: bool
    full_game_optimum: bool
    bound_scope: str


@dataclass(frozen=True)
class Selection:
    """An ordering preference. ``optimality_claim`` stays false."""

    mode: str
    option_id: str
    actions: Tuple
    reason: str
    used_witness: bool
    witness_status: Optional[str]
    total_cost: Optional[int]
    admissible_bound: bool
    scoped_minimum: bool
    full_game_optimum: bool
    optimality_claim: bool
    unknown_ids: Tuple[str, ...]


@dataclass(frozen=True)
class Endpoint:
    foundations: int
    hidden: int
    solved: bool
    stock: int


@dataclass
class DecisionDraft:
    legal_ids: Tuple[str, ...] = ()
    ordered_ids: Tuple[str, ...] = ()
    probed: Tuple[ProbeEvidence, ...] = ()
    unprobed_ids: Tuple[str, ...] = ()
    displaced_id: Optional[str] = None
    deal_reserved: bool = False
    obligations_status: str = ""
    baseline_seconds: float = 0.0
    continuation_seconds: float = 0.0
    identities: int = 0
    refusal: Optional[str] = None
    reprobe_suppressed: bool = False
    dead_end: bool = False
    action_by_id: dict = field(default_factory=dict)
    records: list = field(default_factory=list)


def recommendation(verdict: str) -> str:
    try:
        return RECOMMENDATIONS[verdict]
    except KeyError as exc:
        raise ValueError(f"unknown verdict {verdict}") from exc


def independent_cold_complete(
    *,
    opening_root: bool,
    solved: bool,
    verifier_accepted: bool,
) -> bool:
    """Warm roots and short episodes stay false."""

    return bool(opening_root and solved and verifier_accepted)


def reveal_predicate(decision: SpiderState) -> Optional[Callable[[SpiderState], bool]]:
    """Two new face-down reveals anywhere, or the last one if only one remains.

    ``None`` means the reveal phase is already over. That is not a solved game.
    """

    start = face_down_count(decision)
    if start <= 0:
        return None
    drop = 1 if start == 1 else REVEAL_GOAL
    target = start - drop

    def holds(state: SpiderState, _target: int = target) -> bool:
        return face_down_count(state) <= _target

    return holds


def arrive(seen: dict, pack: str, g: int, *, initial: bool = False) -> Optional[str]:
    """Remember the cheapest arrival. An equal or higher g is a cycle stop."""

    if initial or pack not in seen:
        seen[pack] = int(g)
        return None
    if int(g) >= int(seen[pack]):
        return "repeated-state"
    seen[pack] = int(g)
    return None


def tightened_limits(
    budget: EpisodeBudget,
    *,
    remaining_wall: float,
    remaining_ids: int,
    remaining_paid: int,
) -> Optional[SearchLimits]:
    """Shrink a probe to whatever the episode can still afford."""

    if remaining_wall <= 0 or remaining_ids <= 0 or remaining_paid <= 0:
        return None
    return SearchLimits(
        max_unique=min(int(budget.probe_max_unique), int(remaining_ids)),
        time_limit_s=min(float(budget.probe_time_s), float(remaining_wall)),
        rss_abort_mb=min(float(budget.probe_rss_mb), float(budget.rss_mb)),
        cost_ceiling=min(int(budget.probe_cost_ceiling), int(remaining_paid)),
        harvest_slack=None,
        max_depth=None,
        proof_ceiling=None,
    )


def classify(stop_reason: str, hit_depth_limit: bool, found: bool) -> str:
    if hit_depth_limit or stop_reason == "depth limit":
        return "upper-unfinished" if found else "unknown"
    if stop_reason == "complete" and found:
        return "exact"
    if stop_reason == "complete":
        return "exhausted-no-hit"
    if found:
        return "upper-unfinished"
    return "unknown"


def _normalize(action) -> tuple:
    if is_deal(action):
        return ("deal",)
    return (int(action[0]), int(action[1]), int(action[2]))


def action_token(action) -> list:
    normalized = _normalize(action)
    if normalized == ("deal",):
        return ["deal"]
    return [normalized[0], normalized[1], normalized[2]]


def _option_is_deal(option) -> bool:
    return any(is_deal(action) for action in option.actions)


def allocate_probes(ordered: Sequence, slots: int = PROBE_SLOTS):
    """First ``slots`` in baseline order, with Deal reserved in the last slot.

    Unprobed options stay in the returned tail. Omission is not impossibility.
    """

    ordered = tuple(ordered)
    probed = list(ordered[: int(slots)])
    deal = next((option for option in ordered if _option_is_deal(option)), None)
    displaced = None
    reserved = False
    if deal is not None and all(option.option_id != deal.option_id for option in probed):
        reserved = True
        if len(probed) >= int(slots) and int(slots) > 0:
            displaced = probed[-1]
            probed[-1] = deal
        else:
            probed.append(deal)
    probed_ids = {option.option_id for option in probed}
    unprobed = tuple(option for option in ordered if option.option_id not in probed_ids)
    return tuple(probed), unprobed, displaced, reserved


def _unknown_ids(evidences: Sequence[ProbeEvidence]) -> Tuple[str, ...]:
    return tuple(
        evidence.option_id
        for evidence in evidences
        if evidence.status in ("unknown", "exhausted-no-hit") or evidence.total_cost is None
    )


def choose(mode: str, evidences: Sequence[ProbeEvidence]) -> Selection:
    """Pick a plan. Witness mode may use an unfinished verified cost.

    Ties follow baseline order. With no verified plan, both modes play the
    first candidate's original action. Nothing is deleted from ``evidences``.
    """

    if mode not in ("baseline", "witness"):
        raise ValueError(f"unknown mode {mode}")
    ordered = tuple(sorted(evidences, key=lambda item: int(item.baseline_index)))
    if not ordered:
        raise ValueError("choose requires the probed evidence")
    baseline = ordered[0]
    unknown = _unknown_ids(ordered)
    if mode == "baseline" or not any(
        item.status in _VERIFIED and item.total_cost is not None for item in ordered
    ):
        if mode == "baseline" and baseline.status in _VERIFIED and baseline.total_cost is not None:
            chosen = baseline
            reason = "baseline-witness"
            used = True
        else:
            chosen = baseline
            reason = "baseline-prefix" if mode == "baseline" else "baseline-fallback"
            used = False
            return Selection(
                mode=mode,
                option_id=chosen.option_id,
                actions=tuple(chosen.prefix_actions),
                reason=reason,
                used_witness=False,
                witness_status=None,
                total_cost=int(chosen.prefix_cost),
                admissible_bound=False,
                scoped_minimum=False,
                full_game_optimum=False,
                optimality_claim=False,
                unknown_ids=unknown,
            )
    else:
        verified = [
            item
            for item in ordered
            if item.status in _VERIFIED and item.total_cost is not None
        ]
        chosen = min(verified, key=lambda item: (int(item.total_cost), int(item.baseline_index)))
        reason = "lowest-realised-cost"
        used = True
    return Selection(
        mode=mode,
        option_id=chosen.option_id,
        actions=tuple(chosen.plan),
        reason=reason,
        used_witness=used,
        witness_status=chosen.status,
        total_cost=None if chosen.total_cost is None else int(chosen.total_cost),
        admissible_bound=bool(chosen.admissible_bound) and chosen.status == "exact",
        scoped_minimum=bool(chosen.scoped_minimum) and chosen.status == "exact",
        full_game_optimum=False,
        optimality_claim=False,
        unknown_ids=unknown,
    )


def compare_endpoints(baseline: Endpoint, witness: Endpoint) -> str:
    """Progress rule. Stock is ignored. A solved game outranks an incomplete one."""

    if witness.solved and not baseline.solved:
        return "witness"
    if baseline.solved and not witness.solved:
        return "baseline"
    witness_dominates = (
        witness.foundations >= baseline.foundations
        and witness.hidden <= baseline.hidden
        and (
            witness.foundations > baseline.foundations
            or witness.hidden < baseline.hidden
        )
    )
    baseline_dominates = (
        baseline.foundations >= witness.foundations
        and baseline.hidden <= witness.hidden
        and (
            baseline.foundations > witness.foundations
            or baseline.hidden < witness.hidden
        )
    )
    if witness_dominates and not baseline_dominates:
        return "witness"
    if baseline_dominates and not witness_dominates:
        return "baseline"
    if (
        witness.foundations != baseline.foundations
        and witness.hidden != baseline.hidden
    ):
        return "tradeoff"
    return "tie"


def judge_trial(labels: Sequence[str], *, checks_ok: bool) -> str:
    """Predeclared verdict. Caps and tradeoffs are not rewritten into wins."""

    if not checks_ok:
        return "CORRECTNESS_BLOCKER"
    witness_wins = sum(label == "witness" for label in labels)
    baseline_wins = sum(label == "baseline" for label in labels)
    if witness_wins >= 2 and baseline_wins == 0:
        return "PRACTICAL_SIGNAL_FOUND"
    return "NO_CLEAR_BENEFIT"


def escape_label(control: Endpoint, played: Endpoint) -> str:
    """Progress of one opt-in episode against its frozen witness control.

    Stock is ignored. A solved game still outranks an incomplete one.
    """

    label = compare_endpoints(control, played)
    return {
        "witness": "improved",
        "baseline": "regressed",
        "tie": "tie",
        "tradeoff": "tradeoff",
    }[label]


def judge_escape(labels: Sequence[str], *, checks_ok: bool) -> str:
    """Benefit rule for the opt-in arm. Recovery correctness is separate.

    ``labels`` are opening, after-deal-1, after-deal-2, after-deal-3.
    Two warm-root improvements are required, and no pair may regress or
    trade one progress measure off against the other.
    """

    if not checks_ok or len(tuple(labels)) != 4:
        return "CORRECTNESS_BLOCKER"
    if any(label not in ("improved", "regressed", "tie", "tradeoff") for label in labels):
        return "CORRECTNESS_BLOCKER"
    warm_improvements = sum(label == "improved" for label in tuple(labels)[1:])
    blocked = any(label in ("regressed", "tradeoff") for label in labels)
    if warm_improvements >= 2 and not blocked:
        return "PROGRESS_AFTER_ESCAPE"
    return "ESCAPE_ONLY_NO_CLEAR_GAME_BENEFIT"


def observed_trajectory(baseline_samples: Sequence[dict], witness_samples: Sequence[dict], root_hidden: int) -> list:
    """Paid cost at reveal counts both arms actually reached. Not an optimum."""

    def first_paid(samples: Sequence[dict]) -> dict:
        found = {}
        for sample in samples:
            revealed = int(root_hidden) - int(sample["hidden"])
            for count in range(0, revealed + 1):
                found.setdefault(count, int(sample["paid"]))
        return found

    baseline_paid = first_paid(baseline_samples)
    witness_paid = first_paid(witness_samples)
    rows = []
    for count in sorted(set(baseline_paid) & set(witness_paid)):
        rows.append(
            {
                "reveals": count,
                "baseline_paid": baseline_paid[count],
                "witness_paid": witness_paid[count],
                "label": "observed-trajectory-cost",
                "optimal": False,
            }
        )
    return rows


def progress_curve(samples: Sequence[dict]) -> list:
    last = {}
    for sample in samples:
        last[int(sample["paid"])] = {
            "paid": int(sample["paid"]),
            "foundations": int(sample["foundations"]),
            "hidden": int(sample["hidden"]),
            "stock": int(sample["stock"]),
        }
    return [last[paid] for paid in sorted(last)]


def _replay(state: SpiderState, actions: Sequence) -> Tuple[SpiderState, int]:
    current = state.clone()
    total = 0
    for action in actions:
        normalized = _normalize(action)
        if normalized not in all_legal_actions(current):
            raise ValueError(f"illegal step {normalized!r}")
        priced = int(step_cost(current, normalized))
        applied = int(apply_action(current, normalized))
        if applied != priced:
            raise ValueError(f"cost mismatch on {normalized!r}")
        total += priced
    return current, total


def _best_witness(result, prefix_state: SpiderState, predicate: Callable[[SpiderState], bool]):
    best_actions = None
    best_cost = None
    for terminal in result.terminals:
        actions = tuple(result.reconstruct(int(terminal["node"])))
        try:
            reached, cost = _replay(prefix_state, actions)
        except ValueError:
            continue
        if pack_state(reached).hex() != terminal["store"]:
            continue
        if not predicate(reached):
            continue
        if best_cost is None or cost < best_cost:
            best_actions = actions
            best_cost = int(cost)
    return best_actions, best_cost


def _evidence(
    option,
    baseline_index: int,
    *,
    prefix_cost: int,
    continuation: Tuple = (),
    continuation_cost: Optional[int] = None,
    status: str,
    stop_reason: str,
    kernel_called: bool,
    unique: int,
) -> ProbeEvidence:
    plan = tuple(option.actions) + tuple(continuation)
    total = None if continuation_cost is None else int(prefix_cost) + int(continuation_cost)
    exact = status == "exact"
    return ProbeEvidence(
        option_id=option.option_id,
        baseline_index=int(baseline_index),
        prefix_actions=tuple(option.actions),
        plan=plan if exact or status == "upper-unfinished" else tuple(option.actions),
        prefix_cost=int(prefix_cost),
        continuation=tuple(continuation),
        continuation_cost=None if continuation_cost is None else int(continuation_cost),
        total_cost=total if status in _VERIFIED else None,
        status=status,
        stop_reason=stop_reason,
        kernel_called=kernel_called,
        unique=int(unique),
        admissible_bound=exact,
        scoped_minimum=exact,
        full_game_optimum=False,
        bound_scope="reveal-goal" if exact else "none",
    )


def probe_candidate(state, option, predicate, limits: SearchLimits, baseline_index: int):
    """Replay the prefix. Search only when the prefix misses the reveal goal."""

    reached, prefix_cost = _replay(state, option.actions)
    if int(option.cost) != prefix_cost:
        raise ValueError(
            f"{option.option_id} recorded cost {option.cost} != replay {prefix_cost}"
        )
    if predicate(reached):
        evidence = _evidence(
            option,
            baseline_index,
            prefix_cost=prefix_cost,
            continuation=(),
            continuation_cost=0,
            status="exact",
            stop_reason="prefix-terminal",
            kernel_called=False,
            unique=0,
        )
        return evidence, 0.0
    started = perf_counter()
    result = run_search(
        ({"ordered_digest": pack_state(reached).hex(), "g": prefix_cost},),
        limits=limits,
        identity_fn=pack_state,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=("cost",),
        lane_key_fns=(lambda _state, g: (g,),),
        is_terminal=predicate,
        actions_fn=all_legal_actions,
        stop_on_first_terminal=False,
    )
    elapsed = perf_counter() - started
    continuation, continuation_cost = _best_witness(result, reached, predicate)
    found = continuation_cost is not None
    status = classify(result.stop_reason, bool(result.hit_depth_limit), found)
    evidence = _evidence(
        option,
        baseline_index,
        prefix_cost=prefix_cost,
        continuation=tuple(continuation or ()),
        continuation_cost=continuation_cost,
        status=status,
        stop_reason=result.stop_reason,
        kernel_called=True,
        unique=int(result.unique),
    )
    return evidence, elapsed


def admit_options(state: SpiderState):
    """Cost every legal action, including Deal, then ask PR3 for its full order."""

    legal = tuple(_normalize(action) for action in all_legal_actions(state))
    if not legal:
        return (), None, 0.0, "dead-end"
    graph = rebuild_obligations(state)
    if not obligations_match_state(state, graph):
        return legal, None, 0.0, "refused"
    options = tuple(
        build_option(
            state,
            (action,),
            source_g=0,
            structural_name=str(action),
            option_id=str(action),
            obligations=graph,
            provenance="practical-witness-play",
        )
        for action in legal
    )
    started = perf_counter()
    pick = select_dependency_portfolio(options, graph, limit=len(options))
    elapsed = perf_counter() - started
    if pick.obligations_status != "matched" or not pick.chosen:
        return legal, pick, elapsed, "refused"
    return legal, pick, elapsed, "matched"


def collect_decision(
    state: SpiderState,
    budget: EpisodeBudget,
    *,
    remaining_wall: float,
    remaining_ids: int,
    remaining_paid: int,
    reprobe: bool = False,
) -> DecisionDraft:
    """Probe the admitted slate once. Selection happens afterwards."""

    deadline = perf_counter() + float(remaining_wall)
    legal, pick, baseline_seconds, status = admit_options(state)
    legal_ids = tuple(str(action) for action in legal)
    draft = DecisionDraft(
        legal_ids=legal_ids,
        baseline_seconds=baseline_seconds,
        obligations_status=status,
    )
    if status == "dead-end":
        draft.dead_end = True
        return draft
    if status != "matched":
        draft.refusal = "admission retained no matched candidate"
        return draft
    ordered = tuple(pick.chosen)
    draft.ordered_ids = tuple(option.option_id for option in ordered)
    draft.action_by_id = {
        option.option_id: _normalize(option.actions[0]) for option in ordered
    }
    probed_options, unprobed, displaced, reserved = allocate_probes(
        ordered, budget.probe_slots
    )
    draft.unprobed_ids = tuple(option.option_id for option in unprobed)
    draft.displaced_id = None if displaced is None else displaced.option_id
    draft.deal_reserved = bool(reserved)
    index_of = {option.option_id: index for index, option in enumerate(ordered)}
    if reprobe:
        draft.reprobe_suppressed = True
        return draft
    predicate = reveal_predicate(state)
    if predicate is None:
        draft.refusal = "reveal phase is already complete"
        return draft
    evidences = []
    identities = 0
    continuation = 0.0
    ids_left = int(remaining_ids)
    paid_left = int(remaining_paid)
    for option in probed_options:
        limits = tightened_limits(
            budget,
            remaining_wall=deadline - perf_counter(),
            remaining_ids=ids_left,
            remaining_paid=paid_left,
        )
        if limits is None:
            break
        evidence, kernel_elapsed = probe_candidate(
            state,
            option,
            predicate,
            limits,
            index_of[option.option_id],
        )
        evidences.append(evidence)
        identities += int(evidence.unique)
        ids_left -= int(evidence.unique)
        continuation += kernel_elapsed
        draft.records.append(evidence)
    draft.probed = tuple(evidences)
    draft.identities = identities
    draft.continuation_seconds = continuation
    probed_ids = {evidence.option_id for evidence in evidences}
    skipped = [
        option.option_id
        for option in probed_options
        if option.option_id not in probed_ids
    ]
    draft.unprobed_ids = tuple(list(draft.unprobed_ids) + skipped)
    return draft


def _fallback_selection(mode: str, draft: DecisionDraft, reason: str) -> Selection:
    first_id = draft.ordered_ids[0]
    return Selection(
        mode=mode,
        option_id=first_id,
        actions=(draft.action_by_id[first_id],),
        reason=reason,
        used_witness=False,
        witness_status=None,
        total_cost=None,
        admissible_bound=False,
        scoped_minimum=False,
        full_game_optimum=False,
        optimality_claim=False,
        unknown_ids=(),
    )


def _single_original_fallback(selection: Selection) -> bool:
    """A verified witness plan is not a fallback, even when it has one action."""

    return (not selection.used_witness) and len(tuple(selection.actions)) == 1


def _preview_step(state: SpiderState, action) -> Optional[dict]:
    """One legal step on a clone. The caller's state is not modified."""

    normalized = _normalize(action)
    legal = {_normalize(item) for item in all_legal_actions(state)}
    if normalized not in legal:
        return None
    clone = state.clone()
    priced = int(step_cost(clone, normalized))
    applied = int(apply_action(clone, normalized))
    if applied != priced:
        raise ValueError(f"cost mismatch on {normalized!r}")
    return {"action": normalized, "cost": priced, "pack": pack_state(clone).hex()}


def _step_fits(budget: EpisodeBudget, paid: int, primitives: int, cost: int) -> bool:
    if int(primitives) >= int(budget.primitive_actions):
        return False
    if int(paid) >= int(budget.additional_paid):
        return False
    if int(paid) + int(cost) > int(budget.additional_paid):
        return False
    return True


def _uncertainty(option_id: str, probed_status: dict, unprobed_ids: Sequence[str]) -> str:
    if option_id in set(unprobed_ids) or option_id not in probed_status:
        return "unprobed-legal-fallback"
    status = probed_status[option_id]
    if status in ("unknown", "exhausted-no-hit", None):
        return "unknown-legal-fallback"
    return f"probed-{status}-legal-fallback"


def _binding_cap(budget: EpisodeBudget, *, paid: int, primitives: int, started: float) -> Optional[str]:
    if perf_counter() - started >= float(budget.wall_s):
        return "time"
    if int(primitives) >= int(budget.primitive_actions):
        return "primitive-actions"
    if int(paid) >= int(budget.additional_paid):
        return "paid-moves"
    if _over_rss(budget):
        return "rss"
    return None


def consider_cycle_escape(
    state: SpiderState,
    selection: Selection,
    ordered: Sequence[Tuple[str, tuple]],
    seen: dict,
    budget: EpisodeBudget,
    *,
    paid: int,
    primitives: int,
    started: float,
    probed_status: dict,
    unprobed_ids: Sequence[str],
    remaining_ids: int,
    decisions_used: int,
) -> dict:
    """Try the next legal fallback when the chosen single action repeats.

    Previews use a clone and do not write ``seen``, do not call the kernel,
    and do not count as probe identities. The scan follows ``ordered``, which
    is the admitted PR3 order, including actions that were not probed.
    """

    preview_started = perf_counter()

    def elapsed() -> float:
        return perf_counter() - preview_started

    def finish(replacement, halt, detail, log, count) -> dict:
        seconds = elapsed()
        log["preview_count"] = int(count)
        log["preview_seconds"] = seconds
        log["remaining"] = {
            "wall_s": max(0.0, float(budget.wall_s) - (perf_counter() - started)),
            "paid": int(budget.additional_paid) - int(paid),
            "primitives": int(budget.primitive_actions) - int(primitives),
            "decisions": int(budget.planning_decisions) - int(decisions_used),
            "probe_identities": int(remaining_ids),
        }
        log["preview_identities"] = 0
        return {
            "replacement": replacement,
            "halt": halt,
            "detail": detail,
            "preview_count": int(count),
            "preview_seconds": seconds,
            "log": log,
        }

    if not _single_original_fallback(selection):
        return finish(
            None,
            None,
            "",
            {"triggered": False, "reason": "not-a-single-original-action-fallback"},
            0,
        )
    cap = _binding_cap(budget, paid=paid, primitives=primitives, started=started)
    if cap is not None:
        return finish(
            None,
            cap,
            "",
            {"triggered": False, "reason": "episode-cap", "cap": cap},
            0,
        )
    original = _normalize(selection.actions[0])
    preview = _preview_step(state, original)
    if preview is None:
        return finish(
            None,
            "correctness-blocker",
            f"selected fallback is illegal: {original!r}",
            {"triggered": False, "reason": "illegal-fallback"},
            1,
        )
    arrival = int(paid) + int(preview["cost"])
    earlier = seen.get(preview["pack"])
    repeats = earlier is not None and arrival >= int(earlier)
    if not repeats:
        return finish(
            None,
            None,
            "",
            {
                "triggered": False,
                "reason": "original-fallback-is-not-a-repeat",
                "original_option_id": selection.option_id,
                "original_action": action_token(original),
                "destination": preview["pack"],
                "arrival_g": arrival,
                "earlier_g": None if earlier is None else int(earlier),
            },
            1,
        )
    if not _step_fits(budget, paid, primitives, preview["cost"]):
        return finish(
            None,
            None,
            "",
            {
                "triggered": False,
                "reason": "original-fallback-does-not-fit",
                "original_option_id": selection.option_id,
                "original_action": action_token(original),
                "destination": preview["pack"],
                "arrival_g": arrival,
                "earlier_g": int(earlier),
            },
            1,
        )

    deal_available = any(is_deal(action) for _option_id, action in ordered)
    checked = []
    count = 1
    selected_row = None
    halt = None
    for option_id, action in ordered:
        if perf_counter() - started >= float(budget.wall_s):
            halt = "time"
            break
        if _over_rss(budget):
            halt = "rss"
            break
        normalized = _normalize(action)
        if normalized == original and option_id == selection.option_id:
            row_preview = preview
        else:
            count += 1
            row_preview = _preview_step(state, normalized)
        if row_preview is None:
            checked.append(
                {
                    "option_id": option_id,
                    "action": action_token(normalized),
                    "legal": False,
                    "affordable": False,
                    "fresh": False,
                    "disposition": "illegal",
                }
            )
            continue
        row_g = int(paid) + int(row_preview["cost"])
        row_earlier = seen.get(row_preview["pack"])
        fresh = row_earlier is None or row_g < int(row_earlier)
        affordable = _step_fits(budget, paid, primitives, row_preview["cost"])
        if not affordable:
            disposition = "unaffordable"
        elif row_earlier is None:
            disposition = "unseen"
        elif row_g < int(row_earlier):
            disposition = "cheaper"
        else:
            disposition = "repeat"
        row = {
            "option_id": option_id,
            "action": action_token(row_preview["action"]),
            "legal": True,
            "cost": int(row_preview["cost"]),
            "affordable": bool(affordable),
            "fresh": bool(fresh),
            "destination": row_preview["pack"],
            "arrival_g": row_g,
            "earlier_g": None if row_earlier is None else int(row_earlier),
            "disposition": disposition,
        }
        if fresh and affordable and halt is None:
            row["disposition"] = "selected"
            checked.append(row)
            selected_row = row
            break
        checked.append(row)

    log = {
        "triggered": True,
        "trigger_pack": pack_state(state).hex(),
        "trigger_paid": int(paid),
        "original_option_id": selection.option_id,
        "original_action": action_token(original),
        "repeated_destination": preview["pack"],
        "earlier_g": int(earlier),
        "arrival_g": arrival,
        "checked": checked,
        "deal_available": bool(deal_available),
        "source_pack": pack_state(state).hex(),
        "proved_strategy": False,
        "admissible_bound": False,
        "used_witness": False,
        "optimality_claim": False,
    }
    if halt is not None:
        log["selected_option_id"] = None
        return finish(None, halt, "", log, count)
    if selected_row is None:
        log["selected_option_id"] = None
        return finish(None, "no-fresh-successor", _NO_FRESH_DETAIL, log, count)

    uncertainty = _uncertainty(selected_row["option_id"], probed_status, unprobed_ids)
    unknown = tuple(selection.unknown_ids)
    if uncertainty.startswith("unprobed") or uncertainty.startswith("unknown"):
        if selected_row["option_id"] not in unknown:
            unknown = unknown + (selected_row["option_id"],)
    chosen_action = next(
        action for option_id, action in ordered if option_id == selected_row["option_id"]
    )
    replacement = Selection(
        mode=selection.mode,
        option_id=selected_row["option_id"],
        actions=(_normalize(chosen_action),),
        reason="cycle-escape",
        used_witness=False,
        witness_status=None,
        total_cost=int(selected_row["cost"]),
        admissible_bound=False,
        scoped_minimum=False,
        full_game_optimum=False,
        optimality_claim=False,
        unknown_ids=unknown,
    )
    log.update(
        {
            "selected_option_id": selected_row["option_id"],
            "selected_action": selected_row["action"],
            "destination_pack": selected_row["destination"],
            "uncertainty": uncertainty,
            "selected_cost": int(selected_row["cost"]),
        }
    )
    return finish(replacement, None, "", log, count)


def _snapshot(state: SpiderState, paid: int) -> dict:
    return {
        "paid": int(paid),
        "foundations": len(state.foundations),
        "hidden": face_down_count(state),
        "stock": len(state.stock),
    }


def _over_rss(budget: EpisodeBudget) -> bool:
    measured = rss_mb()
    return measured is not None and float(measured) > float(budget.rss_mb)


def execute_plan(
    state: SpiderState,
    actions: Sequence,
    budget: EpisodeBudget,
    seen: dict,
    *,
    paid: int,
    primitives: int,
    started: float,
    expected_cost: Optional[int],
    predicate,
    require_predicate: bool,
):
    """Verify the whole plan, then play only the steps the budget still allows."""

    try:
        reached, total = _replay(state, actions)
    except ValueError as exc:
        return state, paid, primitives, [], "correctness-blocker", f"illegal plan: {exc}"
    if expected_cost is not None and int(total) != int(expected_cost):
        return (
            state,
            paid,
            primitives,
            [],
            "correctness-blocker",
            f"plan cost {total} != recorded {expected_cost}",
        )
    if require_predicate and (predicate is None or not predicate(reached)):
        return state, paid, primitives, [], "correctness-blocker", "plan misses the reveal goal"
    current = state
    played = []
    for action in actions:
        if perf_counter() - started >= budget.wall_s:
            return current, paid, primitives, played, "time", ""
        if primitives >= budget.primitive_actions:
            return current, paid, primitives, played, "primitive-actions", ""
        if paid >= budget.additional_paid:
            return current, paid, primitives, played, "paid-moves", ""
        if _over_rss(budget):
            return current, paid, primitives, played, "rss", ""
        normalized = _normalize(action)
        step_paid = int(step_cost(current, normalized))
        if paid + step_paid > budget.additional_paid:
            return current, paid, primitives, played, "paid-moves", ""
        trial, _applied = _replay(current, (normalized,))
        new_paid = paid + step_paid
        flag = arrive(seen, pack_state(trial).hex(), new_paid)
        if flag:
            return current, paid, primitives, played, flag, ""
        current = trial
        paid = new_paid
        primitives += 1
        played.append(
            {
                "action": action_token(normalized),
                "cost": step_paid,
                "paid": paid,
                "pack": pack_state(current).hex(),
                "foundations": len(current.foundations),
                "hidden": face_down_count(current),
                "stock": len(current.stock),
            }
        )
    return current, paid, primitives, played, None, ""


def _selection_payload(selection: Selection) -> dict:
    return {
        "mode": selection.mode,
        "option_id": selection.option_id,
        "actions": [action_token(action) for action in selection.actions],
        "reason": selection.reason,
        "used_witness": bool(selection.used_witness),
        "witness_status": selection.witness_status,
        "total_cost": selection.total_cost,
        "admissible_bound": bool(selection.admissible_bound),
        "scoped_minimum": bool(selection.scoped_minimum),
        "full_game_optimum": bool(selection.full_game_optimum),
        "optimality_claim": bool(selection.optimality_claim),
        "unknown_ids": list(selection.unknown_ids),
    }


def _decision_payload(index, pack, draft: DecisionDraft, selection: Selection, recovery) -> dict:
    record = {
        "index": index,
        "source_pack": pack,
        "legal_ids": list(draft.legal_ids),
        "ordered_ids": list(draft.ordered_ids),
        "probed_ids": [item.option_id for item in draft.probed],
        "unprobed_ids": list(draft.unprobed_ids),
        "displaced_id": draft.displaced_id,
        "deal_reserved": draft.deal_reserved,
        "reprobe_suppressed": draft.reprobe_suppressed,
        "obligations_status": draft.obligations_status,
        "identities": draft.identities,
        "candidates": [
            {
                "option_id": item.option_id,
                "baseline_index": item.baseline_index,
                "status": item.status,
                "stop_reason": item.stop_reason,
                "total_cost": item.total_cost,
                "unique": item.unique,
                "kernel_called": item.kernel_called,
                "admissible_bound": item.admissible_bound,
                "scoped_minimum": item.scoped_minimum,
                "full_game_optimum": item.full_game_optimum,
                "bound_scope": item.bound_scope,
            }
            for item in draft.probed
        ],
        "selection": _selection_payload(selection),
    }
    if recovery is not None:
        record["recovery"] = recovery
    return record


def run_episode(
    state: SpiderState,
    mode: str,
    budget: Optional[EpisodeBudget] = None,
    *,
    source_pack: Optional[str] = None,
    cycle_escape: bool = False,
) -> dict:
    """Play one limited episode from ``state``. The caller's state is unchanged.

    ``cycle_escape`` defaults off. The default still stops before playing a
    repeating fallback. The opt-in arm may replace that one action.
    """

    budget = EpisodeBudget() if budget is None else budget
    if int(budget.workers) != 1:
        raise ValueError("the episode budget is one worker")
    current = state.clone()
    started = perf_counter()
    cpu_started = process_time()
    actual_pack = pack_state(current).hex()
    samples = [_snapshot(current, 0)]
    payload = {
        "mode": mode,
        "source_pack": actual_pack,
        "stop_reason": "",
        "detail": "",
        "checks_ok": True,
        "paid": 0,
        "primitives": 0,
        "decisions": 0,
        "probe_identities": 0,
        "foundations": len(current.foundations),
        "hidden": face_down_count(current),
        "stock": len(current.stock),
        "solved": False,
        "reveal_phase_complete": False,
        "independent_cold_complete": False,
        "goals_completed": 0,
        "optimality_claim": False,
        "absolute_g_used_for_proof": False,
        "workers": 1,
        "actions": [],
        "decision_records": [],
        "samples": samples,
        "cycle_escape": bool(cycle_escape),
        "preview_count": 0,
        "preview_seconds": 0.0,
        "baseline_seconds": 0.0,
        "continuation_seconds": 0.0,
        "overhead_seconds": 0.0,
        "wall_s": 0.0,
        "cpu_s": 0.0,
    }
    if source_pack is not None and actual_pack != source_pack:
        payload["stop_reason"] = "correctness-blocker"
        payload["detail"] = "source pack mismatch"
        payload["checks_ok"] = False
        payload["wall_s"] = perf_counter() - started
        payload["cpu_s"] = process_time() - cpu_started
        return payload

    seen = {}
    arrive(seen, actual_pack, 0, initial=True)
    planned = set()
    paid = 0
    primitives = 0
    decisions = 0
    identities = 0
    baseline_seconds = 0.0
    continuation_seconds = 0.0
    goals = 0
    stop = ""
    detail = ""

    while True:
        if perf_counter() - started >= budget.wall_s:
            stop = "time"
            break
        if _over_rss(budget):
            stop = "rss"
            break
        if current.is_solved():
            stop = "solved"
            break
        if face_down_count(current) == 0:
            stop = "reveal_phase_complete"
            break
        if decisions >= budget.planning_decisions:
            stop = "decisions"
            break
        if paid >= budget.additional_paid:
            stop = "paid-moves"
            break
        if primitives >= budget.primitive_actions:
            stop = "primitive-actions"
            break
        if identities >= budget.probe_identities:
            stop = "probe-identities"
            break
        pack = pack_state(current).hex()
        remaining_wall = budget.wall_s - (perf_counter() - started)
        try:
            draft = collect_decision(
                current,
                budget,
                remaining_wall=remaining_wall,
                remaining_ids=budget.probe_identities - identities,
                remaining_paid=budget.additional_paid - paid,
                reprobe=pack in planned,
            )
        except ValueError as exc:
            stop = "correctness-blocker"
            detail = str(exc)
            payload["checks_ok"] = False
            break
        decisions += 1
        baseline_seconds += draft.baseline_seconds
        continuation_seconds += draft.continuation_seconds
        identities += draft.identities
        if draft.dead_end:
            stop = "dead-end"
            break
        if draft.refusal and not draft.reprobe_suppressed:
            stop = "refusal"
            detail = draft.refusal
            break
        if not draft.ordered_ids or not draft.action_by_id:
            stop = "refusal"
            detail = "no admitted action"
            break
        if draft.reprobe_suppressed:
            selection = _fallback_selection(mode, draft, "reprobe-suppressed")
        elif not draft.probed:
            selection = _fallback_selection(
                mode,
                draft,
                "baseline-prefix" if mode == "baseline" else "baseline-fallback",
            )
        else:
            selection = choose(mode, draft.probed)
        planned.add(pack)
        recovery = None
        played_selection = selection
        if cycle_escape:
            try:
                outcome = consider_cycle_escape(
                    current,
                    selection,
                    tuple(
                        (option_id, draft.action_by_id[option_id])
                        for option_id in draft.ordered_ids
                    ),
                    seen,
                    budget,
                    paid=paid,
                    primitives=primitives,
                    started=started,
                    probed_status={item.option_id: item.status for item in draft.probed},
                    unprobed_ids=draft.unprobed_ids,
                    remaining_ids=budget.probe_identities - identities,
                    decisions_used=decisions,
                )
            except ValueError as exc:
                stop = "correctness-blocker"
                detail = str(exc)
                payload["checks_ok"] = False
                payload["decision_records"].append(
                    _decision_payload(decisions - 1, pack, draft, selection, None)
                )
                break
            payload["preview_count"] += int(outcome["preview_count"])
            payload["preview_seconds"] += float(outcome["preview_seconds"])
            recovery = outcome["log"]
            if outcome["halt"] is not None and outcome["replacement"] is None:
                stop = outcome["halt"]
                detail = outcome["detail"]
                if outcome["halt"] == "correctness-blocker":
                    payload["checks_ok"] = False
                payload["decision_records"].append(
                    _decision_payload(decisions - 1, pack, draft, selection, recovery)
                )
                break
            if outcome["replacement"] is not None:
                played_selection = outcome["replacement"]
        predicate = reveal_predicate(current)
        require_predicate = bool(played_selection.used_witness)
        expected = played_selection.total_cost if require_predicate else None
        if expected is None and played_selection.actions:
            try:
                _checked, expected = _replay(current, played_selection.actions)
            except ValueError as exc:
                stop = "correctness-blocker"
                detail = str(exc)
                payload["checks_ok"] = False
                payload["decision_records"].append(
                    _decision_payload(decisions - 1, pack, draft, selection, recovery)
                )
                break
        hidden_before = face_down_count(current)
        current, paid, primitives, played, exec_stop, exec_detail = execute_plan(
            current,
            played_selection.actions,
            budget,
            seen,
            paid=paid,
            primitives=primitives,
            started=started,
            expected_cost=expected,
            predicate=predicate,
            require_predicate=require_predicate,
        )
        payload["actions"].extend(played)
        for step in played:
            samples.append(
                {
                    "paid": step["paid"],
                    "foundations": step["foundations"],
                    "hidden": step["hidden"],
                    "stock": step["stock"],
                }
            )
        if played and face_down_count(current) <= hidden_before - (
            1 if hidden_before == 1 else REVEAL_GOAL
        ):
            goals += 1
        if (
            recovery is not None
            and recovery.get("triggered")
            and recovery.get("selected_option_id")
            and exec_stop == "repeated-state"
            and played_selection.option_id == recovery.get("selected_option_id")
        ):
            exec_stop = "correctness-blocker"
            exec_detail = "execution cycle guard rejected the previewed alternative"
            payload["checks_ok"] = False
        payload["decision_records"].append(
            _decision_payload(decisions - 1, pack, draft, selection, recovery)
        )
        if exec_stop:
            stop = exec_stop
            detail = exec_detail
            if exec_stop == "correctness-blocker":
                payload["checks_ok"] = False
            break

    wall = perf_counter() - started
    payload.update(
        {
            "stop_reason": stop or "decisions",
            "detail": detail,
            "paid": paid,
            "primitives": primitives,
            "decisions": decisions,
            "probe_identities": identities,
            "foundations": len(current.foundations),
            "hidden": face_down_count(current),
            "stock": len(current.stock),
            "solved": bool(current.is_solved()),
            "reveal_phase_complete": (stop == "reveal_phase_complete"),
            "independent_cold_complete": False,
            "goals_completed": goals,
            "final_pack": pack_state(current).hex(),
            "baseline_seconds": baseline_seconds,
            "continuation_seconds": continuation_seconds,
            "overhead_seconds": max(0.0, wall - baseline_seconds - continuation_seconds),
            "wall_s": wall,
            "cpu_s": process_time() - cpu_started,
            "progress": progress_curve(samples),
        }
    )
    return payload


def audit_replay(root: FrozenRoot, executed: Sequence, expected_pack: str, expected_paid: int) -> Tuple[bool, str]:
    """Replay the stored prefix and the played actions from the opening."""

    try:
        state = materialize_root(root)
    except Exception as exc:
        return False, f"prefix replay failed: {exc}"
    paid = 0
    try:
        for action in executed:
            normalized = _normalize(action if not isinstance(action, list) else (
                ("deal",) if action == ["deal"] else tuple(action)
            ))
            if normalized not in all_legal_actions(state):
                return False, f"illegal audited action {normalized!r}"
            paid += int(step_cost(state, normalized))
            apply_action(state, normalized)
    except Exception as exc:
        return False, f"audit replay failed: {exc}"
    if pack_state(state).hex() != expected_pack:
        return False, "audited final pack mismatch"
    if paid != int(expected_paid):
        return False, f"audited cost {paid} != recorded {expected_paid}"
    return True, ""


def _endpoint(episode: dict) -> Endpoint:
    return Endpoint(
        foundations=int(episode["foundations"]),
        hidden=int(episode["hidden"]),
        solved=bool(episode["solved"]),
        stock=int(episode["stock"]),
    )


def run_paired_trial(
    manifest,
    *,
    confirm_official: bool = False,
    budget: Optional[EpisodeBudget] = None,
    freeze_sha: str = "",
    implementation_sha: str = "",
) -> dict:
    """Run each nonduplicate root once per mode. Tests must leave the flag false."""

    if not confirm_official:
        raise RuntimeError(
            "official paired episodes require confirm_official=True and must not run inside unit tests"
        )
    budget = EpisodeBudget() if budget is None else budget
    episodes = []
    pairs = []
    checks_ok = True
    for index, root in enumerate(manifest.roots):
        if not root.counts_as_evidence:
            pairs.append(
                {
                    "root_id": root.root_id,
                    "label": "duplicate-excluded",
                    "duplicate_of": root.duplicate_of,
                }
            )
            continue
        by_mode = {}
        for mode in mode_order(index):
            try:
                source = materialize_root(root)
                if pack_state(source).hex() != root.pack_hex:
                    raise RuntimeError("materialised pack drifted")
                episode = run_episode(
                    source,
                    mode,
                    budget,
                    source_pack=root.pack_hex,
                )
            except Exception as exc:
                episode = {
                    "mode": mode,
                    "root_id": root.root_id,
                    "stop_reason": "correctness-blocker",
                    "detail": str(exc),
                    "checks_ok": False,
                    "solved": False,
                    "foundations": 0,
                    "hidden": 0,
                    "stock": 0,
                    "paid": 0,
                    "actions": [],
                    "samples": [],
                    "final_pack": "",
                    "independent_cold_complete": False,
                }
            episode["root_id"] = root.root_id
            episode["deal_ordinal"] = root.deal_ordinal
            episode["imported_prefix"] = [action_token(action) for action in root.prefix_actions]
            episode["imported_cost"] = root.corrected_cost
            episode["imported_prefix_recorded"] = root.imported_prefix
            episode["run_order"] = mode_order(index)
            ok, reason = (False, episode.get("detail", ""))
            if episode.get("checks_ok", False) and episode.get("final_pack"):
                ok, reason = audit_replay(
                    root,
                    [step["action"] for step in episode.get("actions", [])],
                    episode["final_pack"],
                    int(episode.get("paid", 0)),
                )
                if not ok:
                    episode["checks_ok"] = False
                    episode["detail"] = reason
                    episode["stop_reason"] = "correctness-blocker"
            if episode.get("solved") and not root.imported_prefix:
                verified = validate_solution(
                    "4925153",
                    [
                        ("deal",) if step["action"] == ["deal"] else tuple(step["action"])
                        for step in episode.get("actions", [])
                    ],
                )
                accepted = bool(
                    verified.valid and verified.solved and verified.foundations == 8 and verified.stock_remaining == 0
                )
            else:
                accepted = False
            episode["independent_cold_complete"] = independent_cold_complete(
                opening_root=not root.imported_prefix,
                solved=bool(episode.get("solved")),
                verifier_accepted=accepted,
            )
            if not episode.get("checks_ok", False):
                checks_ok = False
            by_mode[mode] = episode
            episodes.append(episode)
            if not episode.get("checks_ok", False):
                break
        if "baseline" in by_mode and "witness" in by_mode:
            if by_mode["baseline"].get("checks_ok") and by_mode["witness"].get("checks_ok"):
                label = compare_endpoints(_endpoint(by_mode["baseline"]), _endpoint(by_mode["witness"]))
            else:
                label = "correctness-blocker"
                checks_ok = False
            pairs.append(
                {
                    "root_id": root.root_id,
                    "label": label,
                    "baseline": by_mode["baseline"],
                    "witness": by_mode["witness"],
                    "trajectory": observed_trajectory(
                        by_mode["baseline"].get("samples", []),
                        by_mode["witness"].get("samples", []),
                        root.hidden,
                    ),
                }
            )
        elif not checks_ok:
            pairs.append({"root_id": root.root_id, "label": "correctness-blocker"})
            break
    labels = [
        pair["label"]
        for pair in pairs
        if pair["label"] not in ("duplicate-excluded", "correctness-blocker")
    ]
    verdict = judge_trial(labels, checks_ok=checks_ok)
    return {
        "freeze_sha": freeze_sha,
        "implementation_sha": implementation_sha,
        "specification": policy_specification(),
        "deal_sha256": manifest.deal_sha256,
        "canonical_sha256": manifest.canonical_sha256,
        "episodes": episodes,
        "pairs": [
            {
                "root_id": pair["root_id"],
                "label": pair["label"],
                "trajectory": pair.get("trajectory", []),
            }
            for pair in pairs
        ],
        "pair_records": pairs,
        "checks_ok": checks_ok,
        "verdict": verdict,
        "recommendation": recommendation(verdict),
        "independent_cold_complete": False,
    }


def _escape_proof_ok(episode: dict) -> bool:
    """An escape choice is a legal fallback. It must not become a proof."""

    if episode.get("optimality_claim") or episode.get("absolute_g_used_for_proof"):
        return False
    for decision in episode.get("decision_records") or []:
        selection = decision.get("selection") or {}
        if selection.get("optimality_claim") or selection.get("full_game_optimum"):
            return False
        if selection.get("admissible_bound") and selection.get("witness_status") != "exact":
            return False
        recovery = decision.get("recovery") or {}
        if not recovery.get("triggered") or not recovery.get("selected_option_id"):
            continue
        if recovery.get("proved_strategy") or recovery.get("admissible_bound"):
            return False
        if recovery.get("used_witness") or recovery.get("optimality_claim"):
            return False
        uncertainty = str(recovery.get("uncertainty") or "")
        if not uncertainty.endswith("legal-fallback"):
            return False
    return True


def run_cycle_escape_trial(
    manifest,
    *,
    confirm_official: bool = False,
    budget: Optional[EpisodeBudget] = None,
    specification_sha: str = "",
    implementation_sha: str = "",
) -> dict:
    """Run the opt-in witness arm once per root. Tests must leave the flag false."""

    if not confirm_official:
        raise RuntimeError(
            "official cycle-escape episodes require confirm_official=True "
            "and must not run inside unit tests"
        )
    budget = EpisodeBudget() if budget is None else budget
    episodes = []
    checks_ok = True
    for root in manifest.roots:
        if not root.counts_as_evidence:
            continue
        try:
            source = materialize_root(root)
            if pack_state(source).hex() != root.pack_hex:
                raise RuntimeError("materialised pack drifted")
            episode = run_episode(
                source,
                "witness",
                budget,
                source_pack=root.pack_hex,
                cycle_escape=True,
            )
        except Exception as exc:
            episode = {
                "mode": "witness",
                "root_id": root.root_id,
                "stop_reason": "correctness-blocker",
                "detail": str(exc),
                "checks_ok": False,
                "solved": False,
                "foundations": 0,
                "hidden": 0,
                "stock": 0,
                "paid": 0,
                "actions": [],
                "samples": [],
                "decision_records": [],
                "final_pack": "",
                "independent_cold_complete": False,
                "cycle_escape": True,
                "preview_count": 0,
                "preview_seconds": 0.0,
                "optimality_claim": False,
            }
        episode["root_id"] = root.root_id
        episode["deal_ordinal"] = root.deal_ordinal
        episode["imported_prefix"] = [action_token(action) for action in root.prefix_actions]
        episode["imported_cost"] = root.corrected_cost
        episode["imported_prefix_recorded"] = root.imported_prefix
        played = [step["action"] for step in episode.get("actions", [])]
        ok = bool(episode.get("checks_ok", False) and episode.get("final_pack"))
        reason = episode.get("detail", "")
        if ok:
            ok, reason = audit_replay(root, played, episode["final_pack"], int(episode.get("paid", 0)))
            if not ok:
                episode["checks_ok"] = False
                episode["detail"] = reason
                episode["stop_reason"] = "correctness-blocker"
        if not _escape_proof_ok(episode):
            ok = False
            episode["checks_ok"] = False
            episode["stop_reason"] = "correctness-blocker"
            episode["detail"] = "escape result carried a proof or certainty flag"
        composed = [
            action if not isinstance(action, list) else (
                ("deal",) if action == ["deal"] else tuple(action)
            )
            for action in list(root.prefix_actions) + played
        ]
        accepted = False
        if episode.get("solved"):
            verified = validate_solution("4925153", composed)
            accepted = bool(
                verified.valid
                and verified.solved
                and verified.foundations == 8
                and verified.stock_remaining == 0
            )
            if not accepted:
                ok = False
                episode["checks_ok"] = False
                episode["stop_reason"] = "correctness-blocker"
                episode["detail"] = "solved episode failed the eight-foundation verifier"
        episode["independent_cold_complete"] = independent_cold_complete(
            opening_root=not root.imported_prefix,
            solved=bool(episode.get("solved")),
            verifier_accepted=accepted,
        )
        if not ok:
            checks_ok = False
        episodes.append(episode)
        if not ok:
            break
    opening_complete = any(
        episode.get("root_id") == "opening" and episode.get("independent_cold_complete")
        for episode in episodes
    )
    return {
        "specification_sha": specification_sha,
        "implementation_sha": implementation_sha,
        "specification": policy_specification(),
        "deal_sha256": manifest.deal_sha256,
        "canonical_sha256": manifest.canonical_sha256,
        "mode": "witness",
        "cycle_escape": True,
        "episodes": episodes,
        "checks_ok": checks_ok,
        "independent_cold_complete": bool(opening_complete),
    }
