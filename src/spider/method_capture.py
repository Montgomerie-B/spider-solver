"""Method-v1 campaign commands for deal 4925153.

Cold feasibility, fresh-opening scalar improvement, route repair, and
sampled continuation are separate records. The search implementation
remains ``search_suit_ordered``. This module does not copy the kernel.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from spider.autonomous_solve_campaign import (
    atomic_write_json,
    classify_stop,
    parse_action_text,
)
from spider.global_search_experiment import replay_cost, search_suit_ordered
from spider.human_strategy.anchored import (
    AdaptiveRegion,
    _examine_region,
    build_checkpoints,
)
from spider.metrics import Action, export_actions_to_moves_file, format_action
from spider.packed_state import pack_state
from spider.research_actions import apply_action, face_down_count, is_deal, step_cost

SCHEMA = "spider-method-capture-26"
RECIPE_SCHEMA = "spider-whole-game-method-v1"
AGGREGATE_CAP_MB = 8 * 1024.0
MODES = ("cold", "opening-improve", "repair", "continue")
DEAL_ID = "4925153"
RULES_ID = "MW_RULES"
RECIPE_RELATIVE = "docs/research/method_capture_optimisation/method_v1.json"
SOURCE_FILES = (
    "src/spider/method_capture.py",
    "src/spider/global_search_experiment.py",
    "src/spider/search_kernel.py",
    "src/spider/research_actions.py",
    "tools/autonomous_solve_campaign.py",
    RECIPE_RELATIVE,
)
LogFn = Optional[Callable[[str], None]]


def load_recipe(path: Path) -> dict:
    """Load the frozen recipe and refuse a document that changes the method."""

    recipe = json.loads(Path(path).read_text(encoding="utf-8"))
    if recipe.get("schema") != RECIPE_SCHEMA or int(recipe.get("version") or 0) != 1:
        raise ValueError("method recipe schema or version is not v1")
    if recipe.get("advice") is not False:
        raise ValueError("method v1 keeps advice off")
    if recipe.get("seed_wired_into_successor_order") is not False:
        raise ValueError("method v1 does not wire seed into successor order")
    if recipe.get("actions_fn") != "all_legal_actions":
        raise ValueError("method v1 generates every legal action")
    if recipe.get("kernel_copied") is not False:
        raise ValueError("method v1 keeps search_suit_ordered as the reference")
    if recipe.get("mode") != "cold":
        raise ValueError("the frozen recipe is the cold opening method")
    for key in ("time_limit_s", "max_unique", "requested_rss_mb", "paid_cost_ceiling", "lane_names"):
        if key not in recipe:
            raise ValueError(f"method recipe is missing {key}")
    return recipe


def cold_search_kwargs(
    recipe: dict,
    *,
    rss_abort_mb: float,
    time_limit_s: Optional[float] = None,
    max_unique: Optional[int] = None,
    cost_ceiling: Optional[int] = None,
) -> dict:
    """Arguments for one fresh cold call. No incumbent and no route prefix."""

    if recipe.get("advice") is not False:
        raise ValueError("method v1 keeps advice off")
    return {
        "time_limit_s": float(recipe["time_limit_s"] if time_limit_s is None else time_limit_s),
        "max_unique": int(recipe["max_unique"] if max_unique is None else max_unique),
        "rss_abort_mb": float(rss_abort_mb),
        "seed": int(recipe.get("seed_recorded") or 0),
        "mode": "cold",
        "cost_ceiling": int(recipe["paid_cost_ceiling"] if cost_ceiling is None else cost_ceiling),
        "advice_fn": None,
        "prefix_actions": (),
    }


def opening_improve_kwargs(
    incumbent_cost: int,
    cost_ceiling: Optional[int],
    *,
    time_limit_s: float,
    max_unique: int,
    rss_abort_mb: float,
    seed: int = 0,
) -> dict:
    """Fresh-opening search under a scalar incumbent. Equality stays eligible."""

    ceiling = int(incumbent_cost) - 1
    if cost_ceiling is not None:
        ceiling = min(ceiling, int(cost_ceiling))
    if ceiling < 0:
        raise ValueError("improvement ceiling must be non-negative")
    return {
        "time_limit_s": float(time_limit_s),
        "max_unique": int(max_unique),
        "rss_abort_mb": float(rss_abort_mb),
        "seed": int(seed),
        "mode": "optimise",
        "incumbent_cost": int(incumbent_cost),
        "cost_ceiling": int(ceiling),
        "advice_fn": None,
        "prefix_actions": (),
    }


def parse_meminfo(text: str) -> tuple:
    """Return ``(total_bytes, available_bytes)`` from ``/proc/meminfo`` text."""

    values = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        parts = raw.split()
        if not parts:
            continue
        number = int(parts[0])
        unit = parts[1].lower() if len(parts) > 1 else "b"
        scale = {"b": 1, "kb": 1024, "mb": 1024 * 1024, "gb": 1024 * 1024 * 1024}.get(unit)
        if scale is None:
            continue
        values[key] = number * scale
    if "MemTotal" not in values or "MemAvailable" not in values:
        raise ValueError("meminfo is missing MemTotal or MemAvailable")
    return int(values["MemTotal"]), int(values["MemAvailable"])


def probe_host_memory() -> dict:
    """Read total and available RAM on Windows or Linux."""

    if sys.platform == "win32":
        total, avail = _windows_memory()
        return {
            "probe": "GlobalMemoryStatusEx",
            "total_bytes": int(total),
            "available_bytes": int(avail),
        }
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        total, avail = parse_meminfo(meminfo.read_text(encoding="utf-8"))
        return {"probe": "proc_meminfo", "total_bytes": total, "available_bytes": avail}
    return {"probe": "unavailable", "total_bytes": 0, "available_bytes": 0}


def clamp_rss_mb(requested_mb: float, available_bytes: int, *, workers: int = 1) -> float:
    """Aggregate cap for every worker: requested, 8 GiB, and 40 percent of available RAM."""

    if int(workers) < 1:
        raise ValueError("worker count must be positive")
    limits = [float(requested_mb), AGGREGATE_CAP_MB]
    if int(available_bytes) > 0:
        limits.append((int(available_bytes) / (1024.0 * 1024.0)) * 0.40)
    return float(min(limits))


def plan_overlapping_windows(
    action_count: int,
    deal_indexes: Sequence[int],
    *,
    span: int,
    stride: int,
    limit: int,
) -> List[dict]:
    """Wider repair windows. Stride shorter than the span makes them overlap."""

    if int(stride) >= int(span):
        raise ValueError("overlapping repair requires stride shorter than span")
    if int(span) < 2 or int(limit) < 1:
        raise ValueError("repair span and window count must cover a real segment")
    windows = []
    start = 0
    deals = [int(item) for item in deal_indexes]
    while start < int(action_count) and len(windows) < int(limit):
        end = min(int(action_count), start + int(span))
        if end - start < 2:
            break
        crosses = [deal for deal in deals if start < deal <= end]
        windows.append(
            {
                "start": int(start),
                "end": int(end),
                "span": int(end - start),
                "crosses_stock_deals": crosses,
            }
        )
        if end >= int(action_count):
            break
        start += int(stride)
    return windows


def route_profile(opening, actions: Sequence[Action]) -> dict:
    """Cost, stock deals, and repeated-state gaps along one replayed route."""

    state = opening.clone()
    seen = {}
    repeats = []
    deals = []
    epochs = {}
    zero_cost = 0
    g = 0
    for index, action in enumerate(actions, start=1):
        cost = int(step_cost(state, action))
        if cost == 0:
            zero_cost += 1
        apply_action(state, action)
        g += cost
        rows = len(state.stock) // 10
        epoch = epochs.setdefault(
            rows,
            {"stock_rows": rows, "first_action": index, "first_g": g, "last_g": g},
        )
        epoch["last_g"] = g
        epoch["last_action"] = index
        token = pack_state(state).hex()
        previous = seen.get(token)
        if previous is not None and g > previous["g"]:
            repeats.append(
                {
                    "first_action": previous["action"],
                    "again_action": index,
                    "gap": index - previous["action"],
                    "g_increase": g - previous["g"],
                }
            )
        else:
            seen[token] = {"action": index, "g": g}
        if is_deal(action):
            deals.append({"action": index, "g": g, "stock_rows_after": rows})
    repeats.sort(key=lambda item: (-int(item["g_increase"]), -int(item["gap"])))
    return {
        "action_count": len(actions),
        "cost": int(g),
        "deal_count": len(deals),
        "deals": deals,
        "zero_cost_actions": int(zero_cost),
        "stock_epochs": [epochs[key] for key in sorted(epochs, reverse=True)],
        "repeated_state_count": len(repeats),
        "largest_repeated_gaps": repeats[:8],
    }


def refuse_reference_route(path: Path) -> None:
    """Refuse a published route before its bytes are used as search guidance."""

    candidate = Path(path)
    if "solutions" in candidate.parts:
        raise ValueError("method capture does not read the solutions directory")
    stem = candidate.stem.lower()
    if "canonical" in stem or stem.endswith("_185") or "v0_74" in stem:
        raise ValueError("method capture refuses a published reference route")


def file_hashes(path: Path) -> dict:
    raw = Path(path).read_bytes()
    lf = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    crlf = lf.replace(b"\n", b"\r\n")
    newline = "crlf" if b"\r\n" in raw else "lf"
    return {
        "bytes": len(raw),
        "newline": newline,
        "raw_sha256": hashlib.sha256(raw).hexdigest().upper(),
        "lf_sha256": hashlib.sha256(lf).hexdigest().upper(),
        "crlf_sha256": hashlib.sha256(crlf).hexdigest().upper(),
    }


def action_path_hash(actions: Sequence[Action]) -> str:
    payload = repr([(action if action != ("deal",) else ("deal",)) for action in actions])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def authenticate_route(opening, path: Path) -> dict:
    """Replay one campaign route and return its cost. Actions are not included."""

    from spider.metrics import parse_moves_file
    from spider.solution_archive import validate_solution

    route = Path(path)
    refuse_reference_route(route)
    actions = parse_moves_file(route)
    report = validate_solution(
        "4925153",
        actions,
        expected_deal_id="4925153",
    )
    if not report.valid:
        raise ValueError(report.failure_reason or "route failed validation")
    digest = action_path_hash(actions)
    del actions
    return {
        "path": route.as_posix(),
        "g": int(report.mobilityware_moves),
        "action_count": int(report.explicit_commands),
        "valid": True,
        "foundations": int(report.foundations),
        "path_hash16": digest,
        "hashes": file_hashes(route),
        "actions_loaded_into_search": False,
    }


def assert_method_document(document: dict) -> None:
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise ValueError("method continuation refuses a checkpoint from another schema")
    if document.get("reference_seed") is not False:
        raise ValueError("method continuation refuses a reference seed")
    if document.get("exact_frontier_retained") is not False:
        raise ValueError("method continuation does not resume an exact kernel frontier")
    if document.get("restart_inherits_exhaustion") is not False:
        raise ValueError("a restart does not inherit an exhaustion claim")


def _terminal(branch: dict) -> bool:
    return branch.get("terminal") is True


def _prefix_hash16(actions: Sequence[Action]) -> str:
    return action_path_hash(actions)


def _actions_from_branch(branch: dict) -> List[Action]:
    return [parse_action_text(text) for text in branch.get("actions") or []]


def _component_exhausted(attempt: dict) -> bool:
    """A reusable exhaustion is a heap that emptied, not a resource cap."""

    if attempt.get("search_kind") != "sampled_reseed":
        return False
    if attempt.get("stop_reason") != "complete" or attempt.get("solved"):
        return False
    stop_class = attempt.get("stop_class")
    return stop_class in {None, "", "heap_empty_under_paid_ceiling"}


def _exhaustion_from_saved_root(attempt: dict, deal_id: str) -> Optional[dict]:
    """Identify a historical exhausted root from its saved node, not its length."""

    if not _component_exhausted(attempt):
        return None
    prefix_len = attempt.get("prefix_len")
    ceiling = attempt.get("cost_ceiling")
    if not prefix_len or ceiling is None:
        return None
    for branch in attempt.get("branches") or []:
        if not isinstance(branch, dict) or branch.get("replay_ok") is not True:
            continue
        if _terminal(branch) or not branch.get("pack"):
            continue
        if int(branch.get("node") if branch.get("node") is not None else -1) != 0:
            continue
        if int(branch.get("action_count") or 0) != int(prefix_len):
            continue
        actions = _actions_from_branch(branch)
        return {
            "pack": branch.get("pack"),
            "prefix_hash16": _prefix_hash16(actions) if actions else None,
            "root_g": int(branch.get("g") or 0),
            "prefix_len": int(prefix_len),
            "deal_id": str(deal_id),
            "rules": RULES_ID,
            "cost_ceiling": int(ceiling),
            "component_exhausted": True,
            "derived_from": "saved_root_branch",
            "attempt_id": attempt.get("id"),
            "root_ancestry": attempt.get("root_ancestry") or "verified_unfinished_prefix",
            "search_scope": {
                "cost_ceiling": int(ceiling),
                "max_unique": attempt.get("max_unique"),
                "time_limit_s": attempt.get("time_limit_s"),
                "rss_abort_mb": attempt.get("rss_abort_mb"),
                "stop_reason": attempt.get("stop_reason"),
                "stop_class": attempt.get("stop_class") or "heap_empty_under_paid_ceiling",
            },
        }
    return None


def _exhaustion_records(document: dict) -> List[dict]:
    """Exact roots whose paid component emptied. Length is not a record."""

    deal_id = str(document.get("deal_id") or DEAL_ID)
    records = []
    for attempt in document.get("attempts") or []:
        if not isinstance(attempt, dict) or not _component_exhausted(attempt):
            continue
        stored = attempt.get("exhausted_root")
        if isinstance(stored, dict) and stored.get("pack") and stored.get("component_exhausted") is not False:
            record = dict(stored)
            record.setdefault("deal_id", deal_id)
            record.setdefault("rules", RULES_ID)
            record["component_exhausted"] = True
            records.append(record)
            continue
        derived = _exhaustion_from_saved_root(attempt, deal_id)
        if derived is not None:
            records.append(derived)
    return records


def _exhaustion_covers(record: dict, branch: dict, *, requested_ceiling: Optional[int], deal_id: str) -> bool:
    """Reuse one emptied component only inside the ceiling that emptied it."""

    if record.get("component_exhausted") is False:
        return False
    if requested_ceiling is None:
        return False
    if str(record.get("deal_id") or deal_id) != str(deal_id):
        return False
    if str(record.get("rules") or RULES_ID) != RULES_ID:
        return False
    pack = record.get("pack")
    if not pack or pack != branch.get("pack"):
        return False
    if int(record.get("root_g") if record.get("root_g") is not None else -1) != int(branch.get("g") or -2):
        return False
    ceiling = record.get("cost_ceiling")
    if ceiling is None or int(requested_ceiling) > int(ceiling):
        return False
    recorded_hash = record.get("prefix_hash16")
    branch_hash = branch.get("prefix_hash16")
    if recorded_hash and branch_hash and recorded_hash != branch_hash:
        return False
    return True


def choose_continuation(
    document: dict,
    which: str = "unfinished",
    max_g: Optional[int] = None,
    min_slack: int = 0,
) -> dict:
    """Pick unfinished or untried work. A solved terminal is not a seed.

    ``max_g`` skips a prefix that already costs more than the paid ceiling.
    A heap that emptied excludes only that root's pack, root g, deal, and
    rules, and only when the requested ceiling is within the exhausted scope.
    Two prefixes of the same action count stay distinct.
    """

    assert_method_document(document)
    which = which or "unfinished"
    if which in {"best", "complete"}:
        raise ValueError("a solved terminal is not a continuation seed")
    deal_id = str(document.get("deal_id") or DEAL_ID)
    exhausted = _exhaustion_records(document)
    pool = []
    for attempt in document.get("attempts") or []:
        if not isinstance(attempt, dict):
            continue
        for branch in attempt.get("branches") or []:
            if not isinstance(branch, dict) or branch.get("replay_ok") is not True:
                continue
            if _terminal(branch) or not branch.get("actions"):
                continue
            if max_g is not None and int(branch.get("g") or 0) > int(max_g) - int(min_slack):
                continue
            if any(
                _exhaustion_covers(record, branch, requested_ceiling=max_g, deal_id=deal_id)
                for record in exhausted
            ):
                continue
            if which == "untried":
                if branch.get("role") == "untried" and branch.get("expanded") is False:
                    pool.append(branch)
            elif branch.get("role") in {"leader", "milestone", "untried"}:
                pool.append(branch)
    if not pool:
        raise ValueError("no verified unfinished branch is stored; refusing to restart a solved terminal")
    pool.sort(key=lambda branch: (-int(branch["foundations"]), int(branch["face_down"]), int(branch["g"])))
    return pool[0]


def continuation_prefix(
    opening,
    document: dict,
    which: str = "unfinished",
    max_g: Optional[int] = None,
    min_slack: int = 0,
) -> List[Action]:
    branch = choose_continuation(document, which, max_g=max_g, min_slack=min_slack)
    actions = [parse_action_text(text) for text in branch.get("actions") or []]
    if not actions:
        raise ValueError("refusing an empty continuation prefix")
    try:
        end, cost = replay_cost(opening, actions)
    except Exception as exc:
        raise ValueError(f"continuation prefix is illegal: {exc}") from exc
    if int(cost) != int(branch["g"]) or pack_state(end).hex() != branch.get("pack"):
        raise ValueError("branch replay does not match the saved cost and state")
    if end.is_solved():
        raise ValueError("a solved terminal is not a continuation seed")
    return actions


def _better_progress(candidate: dict, current: Optional[dict]) -> bool:
    if current is None:
        return True
    new = (-int(candidate["foundations"]), int(candidate["face_down"]), int(candidate["g"]))
    old = (-int(current["foundations"]), int(current["face_down"]), int(current["g"]))
    return new < old


def _git_text(repo: Path, args: Sequence[str]) -> Optional[str]:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=str(repo),
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return None


def _source_identity_snapshot(repo: Path, recipe: dict) -> dict:
    """Commit, dirty flag, and LF hashes for the files that define this run."""

    commit = _git_text(repo, ["rev-parse", "HEAD"])
    porcelain = _git_text(repo, ["status", "--porcelain"])
    if commit is None or porcelain is None:
        dirty: object = "unknown"
        relevant_dirty: List[str] = []
        commit_text = "unknown"
    else:
        commit_text = commit.strip() or "unknown"
        dirty_lines = [line for line in porcelain.splitlines() if line.strip()]
        dirty = bool(dirty_lines)
        relevant_dirty = []
        known = set(SOURCE_FILES)
        for line in dirty_lines:
            path_text = line[3:].strip().replace("\\", "/") if len(line) > 3 else ""
            if path_text in known:
                relevant_dirty.append(path_text)
    hashes = {}
    for relative in SOURCE_FILES:
        path = repo / relative
        if path.is_file():
            hashes[relative] = file_hashes(path)["lf_sha256"]
    recipe_path = repo / RECIPE_RELATIVE
    recipe_hash = hashes.get(RECIPE_RELATIVE)
    if recipe_hash is None and recipe_path.is_file():
        recipe_hash = file_hashes(recipe_path)["lf_sha256"]
    return {
        "commit": commit_text,
        "dirty": dirty,
        "relevant_dirty": relevant_dirty,
        "relevant_lf_sha256": hashes,
        "recipe": {
            "schema": recipe.get("schema"),
            "version": recipe.get("version"),
            "frozen_at_commit": recipe.get("frozen_at_commit"),
            "path": RECIPE_RELATIVE,
            "lf_sha256": recipe_hash,
        },
    }


def _freeze_attempt_source(identity: dict, configuration: dict) -> dict:
    """Copy the identity known at attempt creation. Later loads must not replace it."""

    return {
        "commit": identity.get("commit") or "unknown",
        "dirty": identity.get("dirty", "unknown"),
        "relevant_dirty": list(identity.get("relevant_dirty") or []),
        "relevant_lf_sha256": dict(identity.get("relevant_lf_sha256") or {}),
        "recipe": dict(identity.get("recipe") or {}),
        "configuration": dict(configuration),
    }


def _historical_source_snapshot(attempt: dict) -> dict:
    """Unknown provenance for a ledger row that never stored its own snapshot."""

    snapshot = {
        "commit": "unknown",
        "dirty": "unknown",
        "historical": True,
        "note": (
            "No per-attempt source snapshot was recorded. "
            "A retrospective commit is not assigned."
        ),
    }
    stored_prefix = int(attempt.get("prefix_len") or 0) > 0
    fresh_opening = (
        attempt.get("search_kind") == "sampled_reseed"
        and attempt.get("kernel_provenance_string") == "partial_legal_search"
        and stored_prefix
    )
    if fresh_opening:
        snapshot["errata"] = (
            "Stored prefix_len was not the executed search. "
            "The run was a fresh opening. "
            "Kernel provenance remains partial_legal_search. "
            "Raw telemetry is unchanged."
        )
    return snapshot


def _attach_historical_source_errata(document: dict) -> None:
    """Fill missing snapshots in memory. An existing snapshot is left as stored."""

    for attempt in document.get("attempts") or []:
        if not isinstance(attempt, dict) or isinstance(attempt.get("source_snapshot"), dict):
            continue
        attempt["source_snapshot"] = _historical_source_snapshot(attempt)


def _fresh_document(machine: Optional[dict], source: dict) -> dict:
    return {
        "schema": SCHEMA,
        "deal_id": "4925153",
        "method_version": 1,
        "source": source,
        "machine": machine or {},
        "reference_seed": False,
        "exact_frontier_retained": False,
        "restart_inherits_exhaustion": False,
        "ceiling_is_proof": False,
        "resume_kind": "sampled_reseed",
        "method_captured": "METHOD_CAPTURED",
        "cold_reproduction": "NOT_RUN",
        "verified_improvement": "NOT_RUN",
        "best_verified_g": None,
        "best_complete": None,
        "best_unfinished": [],
        "untried_work": [],
        "best_branch": None,
        "attempts": [],
        "notes": (
            "best_complete is a validated finished game. best_branch and best_unfinished "
            "are unfinished. untried_work is a sampled ring, not the kernel heap. "
            "A continuation refuses a solved terminal. Timeout, RSS, unique cap, and "
            "sampled reseed are not proofs."
        ),
    }


def _load_document(path: Path, machine: Optional[dict], source: dict) -> dict:
    if not path.is_file():
        return _fresh_document(machine, source)
    document = json.loads(path.read_text(encoding="utf-8"))
    assert_method_document(document)
    if machine:
        document["machine"] = machine
    # The shared source field is the last writer already stored. Attempt
    # provenance lives on each attempt and is not replaced from HEAD.
    _attach_historical_source_errata(document)
    return document


class _Observer:
    def __init__(
        self,
        opening,
        prefix,
        attempt,
        document,
        path,
        checkpoint_s,
        log,
        *,
        solution_dir: Optional[Path] = None,
        kind: str = "",
        header: str = "",
        incumbent: Optional[int] = None,
    ):
        self.opening = opening
        self.prefix = list(prefix)
        self.attempt = attempt
        self.document = document
        self.path = path
        self.checkpoint_s = float(checkpoint_s)
        self.log = log
        self.solution_dir = None if solution_dir is None else Path(solution_dir)
        self.kind = kind
        self.header = header
        self.incumbent = incumbent
        self.started = time.perf_counter()
        self.last_write = 0.0
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
        self._flushing = False
        self.best_terminal_g = None

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
        solved_now = bool(state.is_solved()) and (
            self.best_terminal_g is None or int(g) < int(self.best_terminal_g)
        )
        if solved_now:
            self.best_terminal_g = int(g)
        due = self.checkpoint_s > 0 and time.perf_counter() - self.last_write >= self.checkpoint_s
        if solved_now or due:
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
            "terminal": False,
        }
        if not full:
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
        built["terminal"] = bool(end.is_solved())
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
                self.attempt["min_live_g"] = kernel.min_live_g
                self.attempt["closed_g"] = kernel.closed_g
                self.attempt["lane_pops"] = dict(kernel.lane_pops)
                self.attempt["lane_remaining"] = dict(kernel.lane_remaining)
            if result is not None:
                self.attempt["stop_reason"] = result.stop_reason
                self.attempt["stop_class"] = classify_stop(result.stop_reason)
                self.attempt["solved"] = bool(result.solved)
                self.attempt["replay_ok"] = bool(result.replay_ok)
                self.attempt["solution_g"] = result.solution_g
                self.attempt["replay_g"] = result.replay_g
                self.attempt["kernel_provenance_string"] = result.provenance
                self.attempt["peak_rss_mb"] = result.peak_rss_mb
                self.attempt["ceiling_kind"] = result.ceiling_kind
                self.attempt["lane_pops"] = dict(result.lane_pops)
            elif running:
                self.attempt["stop_reason"] = ""
                self.attempt["stop_class"] = "still_running"
            _publish_terminals(
                self.document,
                branches,
                solution_dir=self.solution_dir,
                kind=self.kind or str(self.attempt.get("search_kind") or ""),
                header=self.header,
                incumbent=self.incumbent,
                attempt=self.attempt,
            )
            _publish_samples(self.document, branches)
            self.document["running"] = bool(running)
            atomic_write_json(self.path, self.document)
            if self.log is not None:
                self.log(
                    "CHECKPOINT "
                    f"status={self.attempt['status']} "
                    f"unique={self.attempt.get('unique', 0)} "
                    f"expanded={self.attempt.get('expanded', 0)} "
                    f"foundations={self.max_foundations} "
                    f"best_complete={self.document.get('best_verified_g')} "
                    f"unfinished={len(self.document.get('best_unfinished') or [])} "
                    f"untried={len(self.document.get('untried_work') or [])}"
                )
        finally:
            self._flushing = False


def _compact(branch: dict) -> dict:
    return {
        "id": branch.get("id"),
        "role": branch.get("role"),
        "g": branch.get("g"),
        "foundations": branch.get("foundations"),
        "face_down": branch.get("face_down"),
        "stock_rows": branch.get("stock_rows"),
        "action_count": branch.get("action_count"),
        "expanded": branch.get("expanded"),
        "terminal": branch.get("terminal"),
        "replay_ok": branch.get("replay_ok"),
    }


def _publish_samples(document: dict, branches: Sequence[dict]) -> None:
    del branches
    verified = []
    for attempt in document.get("attempts") or []:
        if not isinstance(attempt, dict):
            continue
        for branch in attempt.get("branches") or []:
            if branch.get("replay_ok") and branch.get("actions"):
                verified.append(branch)
    unfinished = [branch for branch in verified if not _terminal(branch)]
    leaders = [branch for branch in unfinished if branch.get("role") == "leader"] or unfinished
    best = None
    for branch in leaders:
        if _better_progress(branch, best):
            best = branch
    if best is not None and _better_progress(best, document.get("best_branch")):
        document["best_branch"] = best
    ranked = sorted(
        unfinished,
        key=lambda branch: (-int(branch["foundations"]), int(branch["face_down"]), int(branch["g"])),
    )
    document["best_unfinished"] = [_compact(branch) for branch in ranked[:5]]
    untried = [
        branch
        for branch in unfinished
        if branch.get("role") == "untried" and branch.get("expanded") is False
    ]
    document["untried_work"] = [_compact(branch) for branch in untried]
    document["exact_frontier_retained"] = False
    document["restart_inherits_exhaustion"] = False
    document["resume_kind"] = "sampled_reseed"


def _note_outcome(document: dict, *, kind: str, solved: bool, solution_g: Optional[int], incumbent: Optional[int]) -> None:
    if kind == "cold_feasibility":
        document["cold_reproduction"] = (
            "COLD_REPRODUCTION_COMPLETE" if solved else "COLD_REPRODUCTION_INCOMPLETE"
        )
    if solved and solution_g is not None and incumbent is not None and int(solution_g) < int(incumbent):
        document["verified_improvement"] = "VERIFIED_IMPROVEMENT"
    elif kind in {"fresh_opening_scalar", "route_guided_repair"}:
        if document.get("verified_improvement") != "VERIFIED_IMPROVEMENT":
            document["verified_improvement"] = "NO_VERIFIED_IMPROVEMENT"
    if solved and solution_g is not None:
        current = document.get("best_verified_g")
        if current is None or int(solution_g) < int(current):
            document["best_verified_g"] = int(solution_g)


def _write_candidate(actions: Sequence[Action], g: int, directory: Path, *, kind: str, header: str) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"4925153_{kind}_{int(g)}.moves"
    temporary = directory / f".{path.name}.{os.getpid()}.tmp"
    export_actions_to_moves_file(list(actions), temporary, header=header)
    try:
        hashes = file_hashes(temporary)
        if path.exists() and file_hashes(path)["raw_sha256"] == hashes["raw_sha256"]:
            temporary.unlink()
        else:
            if path.exists():
                path = directory / f"4925153_{kind}_{int(g)}_{len(actions)}.moves"
            os.replace(temporary, path)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    sidecar = {
        "g": int(g),
        "action_count": len(actions),
        "path_hash16": action_path_hash(actions),
        "search_kind": kind,
        "hashes": hashes,
        "moves": path.name,
    }
    atomic_write_json(path.with_suffix(".json"), sidecar)
    return {
        "path": path.as_posix(),
        "sha256": hashes["raw_sha256"],
        "lf_sha256": hashes["lf_sha256"],
        "crlf_sha256": hashes["crlf_sha256"],
        "newline": hashes["newline"],
        "g": int(g),
        "action_count": len(actions),
        "path_hash16": sidecar["path_hash16"],
        "sidecar": path.with_suffix(".json").as_posix(),
    }


def _promote_verified_complete(
    document: dict,
    actions: Sequence[Action],
    g: int,
    *,
    solution_dir: Optional[Path],
    kind: str,
    header: str,
    incumbent: Optional[int],
    attempt: Optional[dict] = None,
) -> bool:
    """Validate a finished game and publish it when it is a new best.

    The same cost and path hash is a no-op. A higher cost does not replace
    ``best_complete``. Returns True only when the stored best moves downward.
    """

    from spider.solution_archive import validate_solution

    played = list(actions)
    digest = action_path_hash(played)
    current = document.get("best_complete") if isinstance(document.get("best_complete"), dict) else None
    if (
        current is not None
        and current.get("validated") is True
        and current.get("path_hash16") == digest
        and int(current.get("g") or -1) == int(g)
    ):
        # The checkpoint already verified this path. Copy that result onto the
        # attempt and do not write the candidate again.
        if attempt is not None:
            attempt["validated"] = True
            attempt["validation_g"] = int(current["g"])
            attempt["validation_failure"] = ""
            attempt["contract_failure"] = False
            attempt["action_count"] = int(current.get("action_count") or len(played))
            attempt["path_hash16"] = digest
            if current.get("candidate") is not None:
                attempt["candidate"] = current["candidate"]
        return False
    report = validate_solution(
        DEAL_ID,
        played,
        claimed_mobilityware_moves=int(g),
        expected_deal_id=DEAL_ID,
    )
    if attempt is not None:
        attempt["validated"] = bool(report.valid)
        attempt["validation_g"] = report.mobilityware_moves
        attempt["validation_failure"] = report.failure_reason or ""
        attempt["action_count"] = len(played)
        attempt["path_hash16"] = digest
    if not report.valid or int(report.mobilityware_moves or -1) != int(g):
        if attempt is not None:
            attempt["solved"] = False
            attempt["contract_failure"] = True
        return False
    if attempt is not None:
        attempt["contract_failure"] = False
    _note_outcome(document, kind=kind, solved=True, solution_g=int(g), incumbent=incumbent)
    if current is not None and int(g) >= int(current["g"]):
        return False
    candidate = None
    if solution_dir is not None:
        candidate = _write_candidate(played, int(g), Path(solution_dir), kind=kind, header=header)
        if attempt is not None:
            attempt["candidate"] = candidate
    document["best_complete"] = {
        "g": int(g),
        "action_count": len(played),
        "path_hash16": digest,
        "search_kind": kind,
        "validated": True,
        "candidate": candidate,
    }
    return True


def _publish_terminals(
    document: dict,
    branches: Sequence[dict],
    *,
    solution_dir: Optional[Path],
    kind: str,
    header: str,
    incumbent: Optional[int],
    attempt: Optional[dict] = None,
) -> bool:
    """Publish replayable terminals in cost order. The cheapest new best wins."""

    terminals = [
        branch
        for branch in branches
        if isinstance(branch, dict) and branch.get("terminal") is True and branch.get("replay_ok") is True and branch.get("actions")
    ]
    terminals.sort(key=lambda branch: int(branch.get("g") or 0))
    changed = False
    for branch in terminals:
        actions = _actions_from_branch(branch)
        if not actions:
            continue
        if _promote_verified_complete(
            document,
            actions,
            int(branch.get("g") or 0),
            solution_dir=solution_dir,
            kind=kind,
            header=header or "Verified terminal published when it was found.",
            incumbent=incumbent,
            attempt=attempt,
        ):
            changed = True
    return changed


def _promote_saved_terminals(
    document: dict,
    *,
    solution_dir: Optional[Path],
    incumbent: Optional[int],
) -> bool:
    """Publish a terminal already stored on an attempt before another search starts."""

    changed = False
    for attempt in document.get("attempts") or []:
        if not isinstance(attempt, dict):
            continue
        kind = str(attempt.get("search_kind") or "saved_terminal")
        if _publish_terminals(
            document,
            attempt.get("branches") or [],
            solution_dir=solution_dir,
            kind=kind,
            header="Saved terminal published before the search resumed.",
            incumbent=incumbent,
            attempt=None,
        ):
            changed = True
    return changed


def _accept_complete(opening, result, attempt, document, solution_dir: Optional[Path], *, kind: str, header: str, incumbent: Optional[int]) -> None:
    del opening
    _promote_verified_complete(
        document,
        list(result.actions),
        int(result.solution_g),
        solution_dir=solution_dir,
        kind=kind,
        header=header,
        incumbent=incumbent,
        attempt=attempt,
    )


def run_method_attempt(
    opening,
    *,
    mode: str,
    status_path: Path,
    recipe: dict,
    time_limit_s: float,
    max_unique: int,
    rss_abort_mb: float,
    cost_ceiling: Optional[int],
    checkpoint_s: float,
    machine: Optional[dict],
    solution_dir: Optional[Path],
    incumbent_cost: Optional[int] = None,
    route_path: Optional[Path] = None,
    resume_from: str = "unfinished",
    repair_span: int = 48,
    repair_stride: int = 16,
    repair_windows: int = 6,
    window_s: float = 120.0,
    medium_s: float = 240.0,
    historical_best_g: Optional[int] = None,
    min_slack: int = 0,
    authentication: Optional[dict] = None,
    log: LogFn = None,
    repo_root: Optional[Path] = None,
    representation: str = "reference",
) -> dict:
    """Run one labelled method-v1 attempt and atomically update its ledger."""

    if mode not in MODES:
        raise ValueError(f"unknown method mode {mode!r}")
    if mode == "opening-improve" and route_path is not None:
        raise ValueError("fresh-opening improvement does not read a route")
    if mode == "cold" and (incumbent_cost is not None or route_path is not None):
        raise ValueError("cold feasibility does not take an incumbent or a route")
    if mode == "repair" and route_path is None:
        raise ValueError("route repair requires the campaign route")
    repo = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
    identity = _source_identity_snapshot(repo, recipe)
    status_path = Path(status_path)
    document = _load_document(status_path, machine, {"commit": identity["commit"]})
    _publish_samples(document, [])
    recovery_incumbent = incumbent_cost if incumbent_cost is not None else historical_best_g
    if _promote_saved_terminals(document, solution_dir=solution_dir, incumbent=recovery_incumbent):
        atomic_write_json(status_path, document)
    if mode == "repair":
        if representation != "reference":
            raise ValueError("route repair keeps the reference representation")
        return _run_repair(
            opening,
            document,
            status_path,
            route_path=Path(route_path),
            time_limit_s=float(time_limit_s),
            max_unique=int(max_unique),
            rss_abort_mb=float(rss_abort_mb),
            repair_span=int(repair_span),
            repair_stride=int(repair_stride),
            repair_windows=int(repair_windows),
            window_s=float(window_s),
            medium_s=float(medium_s),
            solution_dir=solution_dir,
            source_identity=identity,
            log=log,
        )
    prefix: Sequence[Action] = ()
    if mode == "continue":
        prefix = continuation_prefix(
            opening,
            document,
            resume_from,
            max_g=cost_ceiling,
            min_slack=int(min_slack),
        )
        kwargs = cold_search_kwargs(
            recipe,
            rss_abort_mb=rss_abort_mb,
            time_limit_s=time_limit_s,
            max_unique=max_unique,
            cost_ceiling=cost_ceiling,
        )
        kind = "sampled_reseed"
        ancestry = "verified_unfinished_prefix"
        incumbent_source = "none"
        guidance = "none"
        header = "Sampled reseed from a verified unfinished prefix. The kernel heap was not restored."
        compare = None
    elif mode == "opening-improve":
        if incumbent_cost is None:
            raise ValueError("fresh-opening improvement requires a scalar incumbent")
        kwargs = opening_improve_kwargs(
            int(incumbent_cost),
            cost_ceiling,
            time_limit_s=time_limit_s,
            max_unique=max_unique,
            rss_abort_mb=rss_abort_mb,
            seed=int(recipe.get("seed_recorded") or 0),
        )
        kind = "fresh_opening_scalar"
        ancestry = "fresh_opening"
        incumbent_source = "scalar_verified_cost"
        guidance = "none"
        header = (
            f"Fresh-opening search. Scalar incumbent {int(incumbent_cost)}. "
            f"Paid ceiling {kwargs['cost_ceiling']}. No route actions were read."
        )
        compare = int(incumbent_cost)
    else:
        kwargs = cold_search_kwargs(
            recipe,
            rss_abort_mb=rss_abort_mb,
            time_limit_s=time_limit_s,
            max_unique=max_unique,
            cost_ceiling=int(recipe["paid_cost_ceiling"] if cost_ceiling is None else cost_ceiling),
        )
        kind = "cold_feasibility"
        ancestry = "fresh_opening"
        incumbent_source = "none"
        guidance = "none"
        header = "Fresh cold reproduction of method v1. No stored route was read."
        compare = None if historical_best_g is None else int(historical_best_g)
    attempt = {
        "id": f"a{len(document['attempts']) + 1}",
        "status": "running",
        "search_kind": kind,
        "root_ancestry": ancestry,
        "incumbent_source": incumbent_source,
        "action_guidance": guidance,
        "published_route_read": False,
        "incumbent_passed_to_search": kind == "fresh_opening_scalar",
        "reference_seed": False,
        "prefix_len": len(prefix),
        "resume_from": None if mode != "continue" else resume_from,
        "cost_ceiling": kwargs["cost_ceiling"],
        "time_limit_s": kwargs["time_limit_s"],
        "max_unique": kwargs["max_unique"],
        "rss_abort_mb": kwargs["rss_abort_mb"],
        "checkpoint_s": float(checkpoint_s),
        "seed_recorded": kwargs["seed"],
        "seed_wired_into_successor_order": False,
        "exact_frontier_retained": False,
        "restart_inherits_exhaustion": False,
        "ceiling_is_proof": False,
        "solved": False,
        "replay_ok": False,
        "validated": False,
        "branches": [],
        "authentication": authentication,
        "source_snapshot": _freeze_attempt_source(
            identity,
            {
                "mode": mode,
                "search_kind": kind,
                "cost_ceiling": kwargs["cost_ceiling"],
                "time_limit_s": kwargs["time_limit_s"],
                "max_unique": kwargs["max_unique"],
                "rss_abort_mb": kwargs["rss_abort_mb"],
                "checkpoint_s": float(checkpoint_s),
                "seed_recorded": kwargs["seed"],
                "resume_from": None if mode != "continue" else resume_from,
                "min_slack": int(min_slack),
                "prefix_len": len(prefix),
                "historical_best_g": historical_best_g,
                "incumbent_cost": incumbent_cost,
                "representation": representation,
            },
        ),
    }
    attempt["representation"] = representation
    if representation != "reference":
        kwargs["representation"] = representation
    document["attempts"].append(attempt)
    if mode == "continue":
        kwargs["prefix_actions"] = tuple(prefix)
    elif kwargs.get("prefix_actions"):
        raise ValueError("only a sampled continuation may replay a prefix")
    observer = _Observer(
        opening,
        prefix,
        attempt,
        document,
        status_path,
        checkpoint_s,
        log,
        solution_dir=solution_dir,
        kind=kind,
        header=header,
        incumbent=compare,
    )
    observer.flush(running=True)
    observer.last_write = time.perf_counter()
    result = search_suit_ordered(opening, progress_hook=observer.on_progress, expand_hook=observer.on_expand, **kwargs)
    if mode == "continue" and result.stop_reason == "complete" and not result.solved and prefix:
        end, root_g = replay_cost(opening, prefix)
        attempt["exhausted_root"] = {
            "pack": pack_state(end).hex(),
            "prefix_hash16": action_path_hash(tuple(prefix)),
            "root_g": int(root_g),
            "prefix_len": len(prefix),
            "deal_id": DEAL_ID,
            "rules": RULES_ID,
            "cost_ceiling": int(kwargs["cost_ceiling"]),
            "component_exhausted": True,
            "root_ancestry": ancestry,
            "search_scope": {
                "cost_ceiling": int(kwargs["cost_ceiling"]),
                "max_unique": int(kwargs["max_unique"]),
                "time_limit_s": float(kwargs["time_limit_s"]),
                "rss_abort_mb": float(kwargs["rss_abort_mb"]),
                "search_mode": kwargs["mode"],
                "stop_reason": result.stop_reason,
                "stop_class": classify_stop(result.stop_reason),
            },
        }
    observer.flush(running=False, result=result)
    if result.solved and result.replay_ok:
        _accept_complete(
            opening,
            result,
            attempt,
            document,
            solution_dir,
            kind=kind,
            header=header,
            incumbent=compare,
        )
        observer.flush(running=False, result=result)
    else:
        _note_outcome(document, kind=kind, solved=False, solution_g=None, incumbent=compare)
        atomic_write_json(status_path, document)
    if log is not None:
        log(
            "ATTEMPT "
            f"id={attempt['id']} kind={kind} stop={attempt.get('stop_reason')} "
            f"solved={attempt.get('solved')} cold={document.get('cold_reproduction')} "
            f"improvement={document.get('verified_improvement')}"
        )
    return document


def _run_repair(
    opening,
    document: dict,
    status_path: Path,
    *,
    route_path: Path,
    time_limit_s: float,
    max_unique: int,
    rss_abort_mb: float,
    repair_span: int,
    repair_stride: int,
    repair_windows: int,
    window_s: float,
    medium_s: float,
    solution_dir: Optional[Path],
    source_identity: dict,
    log: LogFn,
) -> dict:
    from spider.metrics import parse_moves_file
    from spider.solution_archive import validate_solution

    refuse_reference_route(route_path)
    actions = list(parse_moves_file(route_path))
    report = validate_solution("4925153", actions, expected_deal_id="4925153")
    if not report.valid:
        raise ValueError(report.failure_reason or "repair route failed validation")
    incumbent_g = int(report.mobilityware_moves)
    started = time.perf_counter()
    profile = route_profile(opening, actions)
    deal_indexes = [int(item["action"]) for item in profile["deals"]]
    windows = plan_overlapping_windows(
        len(actions),
        deal_indexes,
        span=repair_span,
        stride=repair_stride,
        limit=repair_windows,
    )
    attempt = {
        "id": f"a{len(document['attempts']) + 1}",
        "status": "running",
        "search_kind": "route_guided_repair",
        "root_ancestry": "campaign_route_prefix",
        "incumbent_source": "campaign_complete_route",
        "action_guidance": "campaign_route",
        "published_route_read": False,
        "incumbent_passed_to_search": True,
        "reference_seed": False,
        "route": route_path.name,
        "incumbent_g": incumbent_g,
        "route_profile": profile,
        "planned_windows": windows,
        "window_results": [],
        "cost_ceiling": incumbent_g - 1,
        "time_limit_s": float(time_limit_s),
        "max_unique": int(max_unique),
        "rss_abort_mb": float(rss_abort_mb),
        "exact_frontier_retained": False,
        "restart_inherits_exhaustion": False,
        "ceiling_is_proof": False,
        "solved": False,
        "improved": False,
        "validated": False,
        "source_snapshot": _freeze_attempt_source(
            source_identity,
            {
                "mode": "repair",
                "search_kind": "route_guided_repair",
                "cost_ceiling": incumbent_g - 1,
                "time_limit_s": float(time_limit_s),
                "max_unique": int(max_unique),
                "rss_abort_mb": float(rss_abort_mb),
                "repair_span": int(repair_span),
                "repair_stride": int(repair_stride),
                "repair_windows": int(repair_windows),
                "window_s": float(window_s),
                "medium_s": float(medium_s),
                "route": route_path.name,
                "incumbent_g": incumbent_g,
            },
        ),
    }
    document["attempts"].append(attempt)
    atomic_write_json(status_path, document)
    deadline = time.perf_counter() + float(time_limit_s)
    current_actions = list(actions)
    current_cost = incumbent_g
    improved = False
    for window in windows:
        if time.perf_counter() >= deadline:
            attempt["stop_reason"] = "time limit"
            attempt["stop_class"] = "timeout"
            break
        checkpoints = build_checkpoints(opening, current_actions)
        end = int(window["end"])
        start = int(window["start"])
        if end >= len(checkpoints) or start >= end:
            continue
        region = AdaptiveRegion(
            start=start,
            targets=tuple(range(start + 1, end + 1)),
            kind="overlapping_repair",
            budget_class="medium" if window["crosses_stock_deals"] else "short",
            reason="overlapping window; deal-crossing windows use the longer allowance",
        )
        record = _examine_region(
            opening,
            current_actions,
            checkpoints,
            region,
            current_cost=current_cost,
            time_left=deadline - time.perf_counter(),
            window_time_s=float(window_s),
            medium_time_s=float(medium_s),
            max_unique=int(max_unique),
            rss_abort_mb=float(rss_abort_mb),
            memo={},
        )
        replacement = record.pop("actions", None)
        prefix_cost = int(checkpoints[start].g)
        matched_end = record.get("matched_end")
        suffix_cost = None if matched_end is None else int(current_cost) - int(checkpoints[int(matched_end)].g)
        record["prefix_cost"] = prefix_cost
        record["suffix_cost"] = suffix_cost
        record["replacement_cost"] = record.get("replacement_cost")
        if record.get("status") == "IMPROVED" and replacement is not None and suffix_cost is not None:
            recomputed = prefix_cost + int(record["replacement_cost"]) + int(suffix_cost)
            record["recomputed_total"] = recomputed
            checked = validate_solution(
                "4925153",
                list(replacement),
                claimed_mobilityware_moves=recomputed,
                expected_deal_id="4925153",
            )
            record["validated"] = bool(checked.valid)
            record["validation_g"] = checked.mobilityware_moves
            if (
                checked.valid
                and int(checked.mobilityware_moves) == recomputed
                and int(checked.mobilityware_moves) < current_cost
            ):
                current_actions = list(replacement)
                current_cost = int(checked.mobilityware_moves)
                improved = True
                attempt["solved"] = True
                attempt["validated"] = True
                attempt["solution_g"] = current_cost
                attempt["path_hash16"] = action_path_hash(current_actions)
                header = (
                    f"Route-guided repair of {route_path.name}. "
                    f"Prefix {prefix_cost}, replacement {record['replacement_cost']}, "
                    f"suffix {suffix_cost}, recomputed total {recomputed}."
                )
                _promote_verified_complete(
                    document,
                    current_actions,
                    current_cost,
                    solution_dir=solution_dir,
                    kind="route_guided_repair",
                    header=header,
                    incumbent=incumbent_g,
                    attempt=attempt,
                )
                record["accepted"] = True
                attempt["window_results"].append(record)
                atomic_write_json(status_path, document)
                if log is not None:
                    log(f"REPAIR improved g={current_cost} window={start}:{end}")
                continue
            record["accepted"] = False
            record["status"] = "REJECTED"
        attempt["window_results"].append(record)
        atomic_write_json(status_path, document)
        if log is not None:
            log(
                "REPAIR "
                f"window={start}:{end} status={record.get('status')} "
                f"deals={window['crosses_stock_deals']}"
            )
    if "stop_reason" not in attempt:
        attempt["stop_reason"] = "IMPROVED" if improved else "NO_IMPROVEMENT"
        attempt["stop_class"] = "improved" if improved else "no_improvement"
    attempt["status"] = "finished"
    attempt["improved"] = improved
    attempt["elapsed_s"] = round(time.perf_counter() - started, 3)
    if not improved:
        _note_outcome(
            document,
            kind="route_guided_repair",
            solved=False,
            solution_g=None,
            incumbent=incumbent_g,
        )
    document["running"] = False
    atomic_write_json(status_path, document)
    if log is not None:
        log(f"REPAIR status={attempt['stop_reason']} improved={improved} g={attempt.get('solution_g')}")
    return document


def _windows_memory() -> tuple:
    if sys.platform != "win32":
        return 0, 0
    try:
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return 0, 0
        return int(status.ullTotalPhys), int(status.ullAvailPhys)
    except (OSError, AttributeError, ValueError):
        return 0, 0
