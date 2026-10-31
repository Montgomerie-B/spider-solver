"""Cold campaign for deal 4925153.

The search is the suit-ordered whole-game kernel. Every engine-legal
successor is generated, including Deal. Lane scores and suit proximity
order nodes only. They are not an admissible bound and they do not drop
a move.

A checkpoint is a sampled reseed. It stores diverse verified prefixes
and a small queue of generated states that this process had not expanded.
It does not store the kernel heap. A later process must not treat a
timed-out, memory-capped, or unique-capped run as an exhausted component.

Launch from the repository root:

    py -3 tools/autonomous_solve_campaign.py --deal deals/4925153.txt --time-limit 1500 --max-unique 1000000 --memory-mb 3000 --cost-ceiling 400 --checkpoint-s 600 --status docs/autonomous_solve_campaign_status.json

Resume a verified cold descendant:

    py -3 tools/autonomous_solve_campaign.py --deal deals/4925153.txt --resume docs/autonomous_solve_campaign_status.json --from best --time-limit 1500 --max-unique 700000 --memory-mb 3000 --cost-ceiling 400 --checkpoint-s 600 --status docs/autonomous_solve_campaign_status.json
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from spider.global_search_experiment import replay_cost, search_suit_ordered
from spider.metrics import Action, export_actions_to_moves_file, format_action
from spider.packed_state import pack_state
from spider.research_actions import face_down_count, is_deal

SCHEMA = "spider-autonomous-solve-campaign-25"
COLD_PROVENANCE = {"cold_opening", "cold_descendant"}
LogFn = Optional[Callable[[str], None]]


def atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON and replace the destination. Readers never see a partial file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def parse_action_text(text: str) -> Action:
    parts = str(text).split()
    if parts == ["deal"]:
        return ("deal",)
    if len(parts) == 4 and parts[0] == "move":
        return (int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3]))
    raise ValueError(f"bad action text: {text!r}")


def assert_cold_document(document: dict) -> None:
    """Refuse anything except this campaign's own cold checkpoint."""

    if not isinstance(document, dict):
        raise ValueError("cold campaign checkpoint must be a JSON object")
    if document.get("schema") != SCHEMA:
        raise ValueError("cold campaign refuses a checkpoint from another schema")
    if document.get("reference_seed") is not False:
        raise ValueError("cold campaign refuses a reference seed")
    if document.get("provenance") not in COLD_PROVENANCE:
        raise ValueError("cold campaign refuses this provenance")
    if document.get("exact_frontier_retained") is not False:
        raise ValueError("cold campaign does not resume an exact kernel frontier")
    if document.get("restart_inherits_exhaustion") is not False:
        raise ValueError("a restart does not inherit an exhaustion claim")


def classify_stop(stop_reason: str) -> str:
    """Name the stop without promoting a resource cap into a proof."""

    if stop_reason == "solved":
        return "solved"
    if stop_reason == "time limit":
        return "timeout"
    if stop_reason == "rss abort":
        return "resource_exhaustion"
    if stop_reason == "unique limit":
        return "unique_omission"
    if stop_reason == "complete":
        return "heap_empty_under_paid_ceiling"
    if stop_reason == "harvested":
        return "harvest_stop"
    if stop_reason == "depth limit":
        return "depth_limit"
    return "incomplete_not_exhausted"


def _better_progress(candidate: dict, current: Optional[dict]) -> bool:
    if current is None:
        return True
    new = (-int(candidate["foundations"]), int(candidate["face_down"]), int(candidate["g"]))
    old = (-int(current["foundations"]), int(current["face_down"]), int(current["g"]))
    return new < old


def _verified_branches(document: dict) -> List[dict]:
    found = []
    for attempt in document.get("attempts") or []:
        if not isinstance(attempt, dict):
            continue
        for branch in attempt.get("branches") or []:
            if isinstance(branch, dict) and branch.get("replay_ok") is True and branch.get("actions"):
                found.append(branch)
    return found


def choose_branch(document: dict, which: str) -> dict:
    assert_cold_document(document)
    which = which or "best"
    if which == "untried":
        latest = None
        for attempt in document.get("attempts") or []:
            if isinstance(attempt, dict):
                latest = attempt
        pool = []
        for branch in (latest or {}).get("branches") or []:
            if branch.get("role") == "untried" and branch.get("expanded") is False and branch.get("replay_ok") is True:
                pool.append(branch)
        if not pool:
            raise ValueError("no verified unexpanded sample is stored; this is not a full frontier")
        pool.sort(key=lambda branch: (-int(branch["foundations"]), int(branch["face_down"]), int(branch["g"])))
        return pool[0]
    if which == "best" and isinstance(document.get("best_branch"), dict):
        branch = document["best_branch"]
        if branch.get("replay_ok") is True and branch.get("actions"):
            return branch
    pool = _verified_branches(document)
    if which == "foundations":
        pool = [branch for branch in pool if int(branch.get("foundations") or 0) > 0] or pool
    if not pool:
        raise ValueError("no verified cold branch is stored")
    pool.sort(key=lambda branch: (-int(branch["foundations"]), int(branch["face_down"]), int(branch["g"])))
    return pool[0]


def verified_prefix(opening, document: dict, which: str = "best") -> List[Action]:
    """Replay the selected branch from the opening. Mismatch refuses the resume."""

    branch = choose_branch(document, which)
    actions = [parse_action_text(text) for text in branch.get("actions") or []]
    if not actions:
        raise ValueError("refusing an empty resume prefix")
    try:
        end, cost = replay_cost(opening, actions)
    except Exception as exc:
        raise ValueError(f"resume prefix is illegal: {exc}") from exc
    pack = pack_state(end).hex()
    if int(cost) != int(branch["g"]) or pack != branch.get("pack"):
        raise ValueError("branch replay does not match the saved cost and state")
    return actions


def campaign_category(document: dict) -> str:
    for attempt in document.get("attempts") or []:
        if not isinstance(attempt, dict) or attempt.get("reference_seed") is not False:
            continue
        if attempt.get("solved") and attempt.get("replay_ok") and attempt.get("validated"):
            return "INDEPENDENT_COMPLETE_FOUND"
    return "NO_NEW_COMPLETE_GAME_YET"


def _fresh_document(machine: Optional[dict]) -> dict:
    return {
        "schema": SCHEMA,
        "deal_id": "4925153",
        "provenance": "cold_opening",
        "reference_seed": False,
        "exact_frontier_retained": False,
        "restart_inherits_exhaustion": False,
        "ceiling_is_proof": False,
        "inherits_production_ceiling": False,
        "category": "NO_NEW_COMPLETE_GAME_YET",
        "resume_kind": "sampled_reseed",
        "machine": machine or {},
        "attempts": [],
        "best_branch": None,
        "notes": (
            "Elite prefixes and a small unexpanded sample can reseed a later search. "
            "They are not the kernel heap. Timeout, memory, and unique-cap stops "
            "do not close the position. A paid ceiling is not an impossibility proof."
        ),
    }


class _Observer:
    def __init__(self, opening, prefix, attempt, document, path, checkpoint_s, log):
        self.opening = opening
        self.prefix = list(prefix)
        self.attempt = attempt
        self.document = document
        self.path = path
        self.checkpoint_s = float(checkpoint_s)
        self.log = log
        self.started = time.perf_counter()
        self.last_write = self.started
        self.expanded = set()
        self.leaders = {}
        self.leader_rank = {}
        self.queue = []
        self.milestone_nodes = {}
        self.deals = 0
        self.tableau = 0
        self.zero_steps = 0
        self.max_foundations = 0
        self.last_kr = None
        self.writes = 0
        self._flushing = False

    def on_expand(self, state, g, node) -> None:
        node = int(node)
        self.expanded.add(node)
        try:
            self.queue.remove(node)
        except ValueError:
            pass

    def on_progress(self, kr, state, g, node) -> None:
        self.last_kr = kr
        node = int(node)
        record = kr.nodes[node]
        action = record.action
        if action is not None:
            if is_deal(action):
                self.deals += 1
            else:
                self.tableau += 1
            parent = record.parent
            if parent >= 0 and kr.nodes[parent].g == record.g:
                self.zero_steps += 1
        foundations = len(state.foundations)
        rows = len(state.stock) // 10
        hidden = face_down_count(state)
        if foundations > self.max_foundations:
            self.max_foundations = foundations
            self.milestone_nodes[foundations] = node
        key = (foundations, rows)
        rank = (hidden, int(g))
        previous = self.leader_rank.get(key)
        if previous is None or rank < previous:
            self.leader_rank[key] = rank
            self.leaders[key] = node
            if len(self.leaders) > 12:
                worst = max(
                    self.leaders,
                    key=lambda item: (-item[0], self.leader_rank[item][0], self.leader_rank[item][1]),
                )
                self.leaders.pop(worst, None)
                self.leader_rank.pop(worst, None)
        if node not in self.expanded:
            self.queue.append(node)
            if len(self.queue) > 8:
                self.queue.pop(0)
        if self._flushing or self.checkpoint_s <= 0:
            return
        if time.perf_counter() - self.last_write >= self.checkpoint_s:
            self.flush(running=True)
            self.last_write = time.perf_counter()

    def _materialise(self, node: int, role: str) -> Optional[dict]:
        kernel = self.last_kr
        if kernel is None or node < 0 or node >= len(kernel.nodes):
            return None
        suffix = kernel.reconstruct(node)
        full = list(self.prefix) + list(suffix)
        stored = kernel.nodes[node].store.hex()
        g = int(kernel.nodes[node].g)
        built = {
            "id": f"{role}-{node}",
            "role": role,
            "node": int(node),
            "g": g,
            "pack": stored,
            "actions": [format_action(action) for action in full],
            "action_count": len(full),
            "expanded": node in self.expanded,
            "replay_ok": False,
        }
        if not full and role != "leader":
            return None
        try:
            end, cost = replay_cost(self.opening, full)
        except Exception as exc:
            built["replay_error"] = str(exc)
            return built
        built["replay_g"] = int(cost)
        built["foundations"] = len(end.foundations)
        built["face_down"] = face_down_count(end)
        built["stock_rows"] = len(end.stock) // 10
        built["replay_ok"] = int(cost) == g and pack_state(end).hex() == stored
        return built

    def _branches(self) -> List[dict]:
        branches = []
        seen = set()
        for key in sorted(self.leaders):
            node = int(self.leaders[key])
            if node in seen:
                continue
            seen.add(node)
            built = self._materialise(node, "leader")
            if built is not None:
                branches.append(built)
        for foundations in sorted(self.milestone_nodes):
            node = int(self.milestone_nodes[foundations])
            if node in seen:
                continue
            seen.add(node)
            built = self._materialise(node, "milestone")
            if built is not None:
                branches.append(built)
        for node in list(self.queue):
            node = int(node)
            if node in self.expanded or node in seen:
                continue
            seen.add(node)
            built = self._materialise(node, "untried")
            if built is not None:
                branches.append(built)
        return branches

    def flush(self, running: bool, result=None) -> None:
        if self._flushing:
            return
        self._flushing = True
        try:
            kernel = self.last_kr
            branches = self._branches() if kernel is not None else []
            self.attempt["branches"] = branches
            self.attempt["status"] = "running" if running else "finished"
            self.attempt["elapsed_s"] = round(time.perf_counter() - self.started, 3)
            self.attempt["max_foundations"] = int(self.max_foundations)
            self.attempt["deal_admissions"] = int(self.deals)
            self.attempt["tableau_admissions"] = int(self.tableau)
            self.attempt["zero_cost_admissions"] = int(self.zero_steps)
            self.attempt["deal_policy"] = "all_legal_actions"
            self.attempt["legal_actions_dropped"] = 0
            if kernel is not None:
                self.attempt["unique"] = int(kernel.unique)
                self.attempt["expanded"] = int(kernel.expanded)
                self.attempt["generated"] = int(kernel.generated)
                self.attempt["duplicate_skips"] = int(kernel.duplicate_skips)
                self.attempt["stale_skips"] = int(kernel.stale_skips)
                self.attempt["zero_cost_actions"] = int(kernel.zero_cost_actions)
                self.attempt["ceiling_prunes"] = int(kernel.ceiling_prunes)
                self.attempt["lower_bound_prunes"] = int(kernel.lower_bound_prunes)
                self.attempt["proof_prune_identities"] = int(kernel.proof_prune_identities)
                self.attempt["min_live_g"] = kernel.min_live_g
                self.attempt["closed_g"] = kernel.closed_g
                self.attempt["lane_remaining"] = dict(kernel.lane_remaining)
            if result is not None:
                self.attempt["stop_reason"] = result.stop_reason
                self.attempt["stop_class"] = classify_stop(result.stop_reason)
                self.attempt["solved"] = bool(result.solved)
                self.attempt["replay_ok"] = bool(result.replay_ok)
                self.attempt["solution_g"] = result.solution_g
                self.attempt["replay_g"] = result.replay_g
                self.attempt["search_provenance"] = result.provenance
                self.attempt["peak_rss_mb"] = result.peak_rss_mb
                self.attempt["stock_deals_in_nodes"] = int(result.stock_deals)
                self.attempt["heuristic_exclusions"] = int(result.heuristic_exclusions)
                self.attempt["ceiling_kind"] = result.ceiling_kind
            elif running:
                self.attempt["stop_reason"] = ""
                self.attempt["stop_class"] = "still_running"
            verified = [branch for branch in branches if branch.get("replay_ok") and branch.get("actions")]
            leaders = [branch for branch in verified if branch.get("role") == "leader"]
            best = None
            for branch in leaders or verified:
                if _better_progress(branch, best):
                    best = branch
            if best is not None and _better_progress(best, self.document.get("best_branch")):
                self.document["best_branch"] = best
            untried = [branch for branch in verified if branch.get("role") == "untried" and branch.get("expanded") is False]
            self.attempt["untried_sample"] = len(untried)
            self.document["category"] = campaign_category(self.document)
            self.document["exact_frontier_retained"] = False
            self.document["restart_inherits_exhaustion"] = False
            atomic_write_json(self.path, self.document)
            self.writes += 1
            if self.log is not None:
                self.log(
                    "CHECKPOINT "
                    f"status={self.attempt['status']} "
                    f"unique={self.attempt.get('unique', 0)} "
                    f"foundations={self.max_foundations} "
                    f"deals={self.deals} "
                    f"zero_cost={self.zero_steps} "
                    f"branches={len(verified)}"
                )
        finally:
            self._flushing = False


def _load_document(path: Path, machine: Optional[dict]) -> dict:
    if not path.is_file():
        return _fresh_document(machine)
    document = json.loads(path.read_text(encoding="utf-8"))
    assert_cold_document(document)
    if machine:
        document["machine"] = machine
    return document


def run_campaign_attempt(
    opening,
    *,
    status_path: Path,
    time_limit_s: float,
    max_unique: int,
    rss_abort_mb: float,
    cost_ceiling: int,
    checkpoint_s: float = 600.0,
    resume: Optional[dict] = None,
    resume_from: str = "best",
    machine: Optional[dict] = None,
    solution_dir: Optional[Path] = None,
    log: LogFn = None,
) -> dict:
    """Run one bounded cold attempt and persist verified branches.

    ``cost_ceiling`` is a paid-move cap for this attempt. It is not the
    production incumbent and it is not passed to a proof bound. Cold mode
    does not accept an incumbent cost.
    """

    if int(cost_ceiling) < 0:
        raise ValueError("cost ceiling must be non-negative")
    status_path = Path(status_path)
    document = _load_document(status_path, machine)
    prefix: Sequence[Action] = ()
    if resume is not None:
        prefix = verified_prefix(opening, resume, resume_from)
        document["provenance"] = "cold_descendant"
    elif document.get("attempts"):
        document["provenance"] = document.get("provenance") or "cold_opening"
    attempt = {
        "id": f"a{len(document['attempts']) + 1}",
        "status": "running",
        "reference_seed": False,
        "campaign_provenance": "cold_descendant" if prefix else "cold_opening",
        "resume_from": None if not prefix else resume_from,
        "prefix_len": len(prefix),
        "cost_ceiling": int(cost_ceiling),
        "time_limit_s": float(time_limit_s),
        "max_unique": int(max_unique),
        "rss_abort_mb": float(rss_abort_mb),
        "checkpoint_s": float(checkpoint_s),
        "exact_frontier_retained": False,
        "restart_inherits_exhaustion": False,
        "ceiling_is_proof": False,
        "solved": False,
        "replay_ok": False,
        "validated": False,
        "branches": [],
    }
    document["attempts"].append(attempt)
    observer = _Observer(opening, prefix, attempt, document, status_path, checkpoint_s, log)
    observer.flush(running=True)
    result = search_suit_ordered(
        opening,
        time_limit_s=float(time_limit_s),
        max_unique=int(max_unique),
        rss_abort_mb=float(rss_abort_mb),
        mode="cold",
        cost_ceiling=int(cost_ceiling),
        prefix_actions=prefix,
        progress_hook=observer.on_progress,
        expand_hook=observer.on_expand,
    )
    observer.flush(running=False, result=result)
    if result.solved and result.replay_ok:
        _validate_complete(opening, result, attempt, document, solution_dir)
        observer.flush(running=False, result=result)
    if log is not None:
        log(
            "ATTEMPT "
            f"id={attempt['id']} "
            f"stop={attempt.get('stop_reason')} "
            f"class={attempt.get('stop_class')} "
            f"solved={attempt.get('solved')} "
            f"validated={attempt.get('validated')} "
            f"category={document['category']}"
        )
    return document


def _validate_complete(opening, result, attempt, document, solution_dir: Optional[Path]) -> None:
    from spider.solution_archive import validate_solution

    actions = list(result.actions)
    report = validate_solution(
        "4925153",
        actions,
        claimed_mobilityware_moves=result.solution_g,
        expected_deal_id="4925153",
    )
    attempt["validated"] = bool(report.valid)
    attempt["validation_g"] = report.mobilityware_moves
    attempt["validation_failure"] = report.failure_reason or ""
    attempt["action_count"] = len(actions)
    if not report.valid or int(report.mobilityware_moves or -1) != int(result.solution_g):
        attempt["solved"] = False
        attempt["contract_failure"] = True
        document["category"] = "NO_NEW_COMPLETE_GAME_YET"
        return
    attempt["contract_failure"] = False
    if solution_dir is not None:
        attempt["candidate"] = _write_candidate(actions, int(result.solution_g), Path(solution_dir))
    document["category"] = "INDEPENDENT_COMPLETE_FOUND"
    document["solution_g"] = int(result.solution_g)
    document["action_count"] = len(actions)


def _refuse_reference_route(path: Path) -> None:
    if "solutions" in Path(path).parts:
        raise ValueError("campaign optimisation does not read the solutions directory")
    stem = Path(path).stem.lower()
    if "canonical" in stem or stem.endswith("_185") or "v0_74" in stem:
        raise ValueError("campaign optimisation refuses a published reference route")


def optimise_campaign_incumbent(
    opening,
    *,
    incumbent_path: Path,
    status_path: Path,
    time_limit_s: float,
    rss_abort_mb: float,
    max_unique: int = 40000,
    window_s: float = 25.0,
    medium_s: float = 45.0,
    max_windows: int = 32,
    adaptive: bool = True,
    solution_dir: Optional[Path] = None,
    log: LogFn = None,
) -> dict:
    """Try to beat one cold-campaign solution. The published routes are refused.

    This is an incumbent search, not a cold discovery. A cheaper verified
    route stays in the research directory and does not enter the production
    registry.
    """

    from spider.human_strategy.anchored import optimise_anchored
    from spider.metrics import parse_moves_file
    from spider.solution_archive import validate_solution

    incumbent_path = Path(incumbent_path)
    _refuse_reference_route(incumbent_path)
    actions = parse_moves_file(incumbent_path)
    report = validate_solution(
        "4925153",
        actions,
        expected_deal_id="4925153",
    )
    if not report.valid:
        raise ValueError(report.failure_reason or "incumbent failed validation")
    incumbent_g = int(report.mobilityware_moves)
    if log is not None:
        log(f"OPTIMISE incumbent_g={incumbent_g} actions={len(actions)} ceiling={incumbent_g - 1}")
    result = optimise_anchored(
        opening,
        actions,
        mode="anchored",
        source="cold_campaign",
        source_id=incumbent_path.name,
        time_limit_s=float(time_limit_s),
        window_time_s=float(window_s),
        medium_time_s=float(medium_s),
        max_windows=int(max_windows),
        max_unique=int(max_unique),
        rss_abort_mb=float(rss_abort_mb),
        max_improvements=6,
        expected_cost=incumbent_g,
        adaptive=bool(adaptive),
        horizon=24,
        max_regions=8,
    )
    improved_actions = list(result.actions)
    improved = validate_solution(
        "4925153",
        improved_actions,
        claimed_mobilityware_moves=int(result.cumulative_g),
        expected_deal_id="4925153",
    )
    better = bool(improved.valid) and int(improved.mobilityware_moves) < incumbent_g
    document = _load_document(Path(status_path), None)
    attempt = {
        "id": f"a{len(document['attempts']) + 1}",
        "status": "finished",
        "kind": "anchored_optimise",
        "reference_seed": False,
        "campaign_provenance": "cold_descendant_optimise",
        "incumbent_g": incumbent_g,
        "incumbent_file": incumbent_path.name,
        "cost_ceiling": incumbent_g - 1,
        "ceiling_is_proof": False,
        "exact_frontier_retained": False,
        "restart_inherits_exhaustion": False,
        "solved": bool(improved.valid),
        "validated": bool(improved.valid),
        "improved": better,
        "solution_g": int(improved.mobilityware_moves) if improved.valid else None,
        "action_count": len(improved_actions),
        "replay_g": improved.mobilityware_moves,
        "stop_reason": result.status,
        "stop_class": "improved" if better else "no_improvement",
        "elapsed_s": result.elapsed_s,
        "peak_rss_mb": result.peak_rss_mb,
        "search_provenance": "anchored_optimise_of_cold_route",
        "optimality": "unestablished",
        "windows": (result.provenance or {}).get("windows_examined"),
        "improvements": (result.provenance or {}).get("improvements"),
        "expansions": (result.provenance or {}).get("search_expansions"),
    }
    if better and solution_dir is not None:
        attempt["candidate"] = _write_candidate(
            improved_actions,
            int(improved.mobilityware_moves),
            Path(solution_dir),
        )
        document["solution_g"] = int(improved.mobilityware_moves)
        document["action_count"] = len(improved_actions)
    document["attempts"].append(attempt)
    document["optimise"] = {
        "incumbent_g": incumbent_g,
        "best_g": attempt["solution_g"],
        "improved": better,
        "status": result.status,
    }
    atomic_write_json(Path(status_path), document)
    if log is not None:
        log(
            "OPTIMISE "
            f"status={result.status} improved={better} "
            f"g={attempt['solution_g']} windows={attempt['windows']}"
        )
    return document


def _write_candidate(actions: Sequence[Action], g: int, directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"4925153_cold_{g}.moves"
    if path.exists():
        path = directory / f"4925153_cold_{g}_{len(actions)}.moves"
    header = (
        f"Cold campaign solution for deal 4925153. Corrected MW={g}. "
        f"Actions={len(actions)}. Found without reading a stored route."
    )
    export_actions_to_moves_file(list(actions), path, header=header)
    digest = __import__("hashlib").sha256(path.read_bytes()).hexdigest().upper()
    return {
        "path": str(path.as_posix()),
        "sha256": digest,
        "g": int(g),
        "action_count": len(actions),
    }
