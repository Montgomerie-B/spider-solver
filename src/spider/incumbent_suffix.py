"""Own-campaign suffix witnesses and prefix-improvement search.

The 164, 162, 160 and 158 games are feasible completions. A matching
physical state may reuse the cheapest verified suffix. That cost is an
upper bound, never an admissible lower bound, and a miss proves nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from spider.autonomous_solve_campaign import atomic_write_json, parse_action_text
from spider.global_search_experiment import replay_cost, search_suit_ordered
from spider.human_strategy.evaluation import admissible_remaining
from spider.method_capture import (
    action_path_hash,
    clamp_rss_mb,
    file_hashes,
    probe_host_memory,
    refuse_reference_route,
)
from spider.metrics import Action, export_actions_to_moves_file, format_action, parse_moves_file
from spider.packed_state import pack_state
from spider.research_actions import apply_action, face_down_count, opening_from_deal
from spider.search_kernel import reconstruct_path
from spider.solution_archive import validate_solution

DEAL_ID = "4925153"
SCHEMA = "spider-incumbent-suffix-28"
OWN_ROUTES = (
    ("164", "docs/research/autonomous_solve_campaign/4925153_cold_164.moves"),
    ("162", "docs/research/autonomous_solve_campaign/4925153_cold_162.moves"),
    ("160", "docs/research/autonomous_solve_campaign/4925153_cold_160.moves"),
    ("158", "docs/research/autonomous_solve_campaign/4925153_cold_158.moves"),
)
SAVED_PREFIX_LEDGERS = (
    "docs/research/method_capture_optimisation/status.json",
    "docs/research/search_memory_efficiency/status.json",
)
SOURCE_FILES = (
    "src/spider/incumbent_suffix.py",
    "src/spider/packed_heap.py",
    "src/spider/search_kernel.py",
    "src/spider/global_search_experiment.py",
    "src/spider/search_memory_profile.py",
)


@dataclass(frozen=True)
class SuffixWitness:
    pack: bytes
    source_label: str
    source_path: str
    source_hash16: str
    action_index: int
    prefix_g: int
    suffix_cost: int
    total_g: int
    suffix_actions: tuple

    def as_dict(self) -> dict:
        return {
            "pack": self.pack.hex(),
            "source_label": self.source_label,
            "source_path": self.source_path,
            "source_hash16": self.source_hash16,
            "action_index": int(self.action_index),
            "prefix_g": int(self.prefix_g),
            "suffix_cost": int(self.suffix_cost),
            "total_g": int(self.total_g),
            "suffix_actions": [format_action(action) for action in self.suffix_actions],
        }


def choose_witness(current: Optional[SuffixWitness], candidate: SuffixWitness) -> SuffixWitness:
    """Keep the cheaper remaining corrected cost. Action count is not the key."""

    if current is None or int(candidate.suffix_cost) < int(current.suffix_cost):
        return candidate
    if int(candidate.suffix_cost) == int(current.suffix_cost) and int(candidate.total_g) < int(current.total_g):
        return candidate
    return current


class SuffixTable:
    def __init__(self) -> None:
        self.by_pack: Dict[bytes, SuffixWitness] = {}

    def add(self, candidate: SuffixWitness) -> None:
        self.by_pack[candidate.pack] = choose_witness(self.by_pack.get(candidate.pack), candidate)

    def get(self, pack: bytes) -> Optional[SuffixWitness]:
        return self.by_pack.get(pack)

    def __len__(self) -> int:
        return len(self.by_pack)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_authenticated_route(root: Path, label: str, relative: str) -> dict:
    path = root / relative
    refuse_reference_route(path)
    actions = parse_moves_file(path)
    report = validate_solution(DEAL_ID, actions, expected_deal_id=DEAL_ID)
    if not report.valid:
        raise ValueError(report.failure_reason or f"{label} failed validation")
    digest = action_path_hash(actions)
    return {
        "label": label,
        "path": relative.replace("\\", "/"),
        "actions": actions,
        "g": int(report.mobilityware_moves),
        "explicit_commands": int(report.explicit_commands),
        "tableau_moves": int(report.tableau_moves),
        "stock_deals": int(report.stock_deals),
        "automatic_foundation_removals": int(report.automatic_foundation_removals),
        "path_hash16": digest,
        "foundations": int(report.foundations),
    }


def load_own_routes(root: Optional[Path] = None) -> List[dict]:
    repo = Path(root) if root is not None else _repo_root()
    return [load_authenticated_route(repo, label, relative) for label, relative in OWN_ROUTES]


def shared_prefix_length(routes: Sequence[dict]) -> int:
    sequences = [route["actions"] for route in routes]
    limit = min(len(actions) for actions in sequences)
    count = 0
    for index in range(limit):
        action = sequences[0][index]
        if any(other[index] != action for other in sequences[1:]):
            break
        count += 1
    return count


def build_suffix_table(opening, routes: Sequence[dict]) -> SuffixTable:
    table = SuffixTable()
    for route in routes:
        actions = list(route["actions"])
        _end, total = replay_cost(opening, actions)
        if int(total) != int(route["g"]):
            raise ValueError(f"{route['label']} replay cost {total} != validated {route['g']}")
        state = opening.clone()
        g = 0
        for index, action in enumerate(actions):
            table.add(
                SuffixWitness(
                    pack=pack_state(state),
                    source_label=str(route["label"]),
                    source_path=str(route["path"]),
                    source_hash16=str(route["path_hash16"]),
                    action_index=index,
                    prefix_g=int(g),
                    suffix_cost=int(total) - int(g),
                    total_g=int(total),
                    suffix_actions=tuple(actions[index:]),
                )
            )
            g += int(apply_action(state, action))
        table.add(
            SuffixWitness(
                pack=pack_state(state),
                source_label=str(route["label"]),
                source_path=str(route["path"]),
                source_hash16=str(route["path_hash16"]),
                action_index=len(actions),
                prefix_g=int(g),
                suffix_cost=int(total) - int(g),
                total_g=int(total),
                suffix_actions=tuple(),
            )
        )
    return table


def bound_at(opening, actions: Sequence[Action], index: int) -> dict:
    state, g = replay_cost(opening, list(actions)[: int(index)])
    h = int(admissible_remaining(state))
    return {
        "index": int(index),
        "g": int(g),
        "h": h,
        "f": int(g) + h,
        "foundations": len(state.foundations),
        "face_down": int(face_down_count(state)),
        "stock_cards": len(state.stock),
        "pack": pack_state(state).hex(),
    }


def last_eligible_index(opening, actions: Sequence[Action], ceiling: int = 157) -> Optional[int]:
    """Last prefix whose admissible f is still within the absolute ceiling."""

    chosen = None
    state = opening.clone()
    g = 0
    h = int(admissible_remaining(state))
    if g + h <= int(ceiling):
        chosen = 0
    for index, action in enumerate(actions):
        g += int(apply_action(state, action))
        h = int(admissible_remaining(state))
        if g + h <= int(ceiling):
            chosen = index + 1
    return chosen


def route_prefix_records(opening, routes: Sequence[dict]) -> List[dict]:
    records = []
    for route in routes:
        actions = list(route["actions"])
        state = opening.clone()
        g = 0
        for index in range(len(actions) + 1):
            records.append(
                {
                    "pack": pack_state(state),
                    "g": int(g),
                    "actions": tuple(actions[:index]),
                    "source": f"route:{route['label']}:{index}",
                }
            )
            if index == len(actions):
                break
            g += int(apply_action(state, actions[index]))
    return records


def _branch_lists(document: dict) -> Iterable[dict]:
    for attempt in document.get("attempts") or []:
        for branch in attempt.get("branches") or []:
            yield branch
    for branch in document.get("best_unfinished") or []:
        yield branch
    best = document.get("best_branch")
    if isinstance(best, dict):
        yield best


def saved_branch_records(opening, root: Path) -> List[dict]:
    records = []
    for relative in SAVED_PREFIX_LEDGERS:
        path = root / relative
        if not path.is_file():
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        seen = set()
        for branch in _branch_lists(document):
            if not isinstance(branch, dict) or branch.get("replay_ok") is not True:
                continue
            texts = branch.get("actions") or []
            if not texts:
                continue
            key = tuple(texts)
            if key in seen:
                continue
            seen.add(key)
            try:
                actions = [parse_action_text(text) for text in texts]
                state, g = replay_cost(opening, actions)
            except (ValueError, TypeError):
                records.append({"source": relative, "ok": False})
                continue
            records.append(
                {
                    "pack": pack_state(state),
                    "g": int(g),
                    "actions": tuple(actions),
                    "source": f"branch:{relative}:{branch.get('role')}:{g}",
                    "ok": True,
                }
            )
    return records


def splice_saved_prefixes(table: SuffixTable, records: Sequence[dict], incumbent: int = 158) -> dict:
    """Cheap exact-pack check. This is not a search and not an optimality proof."""

    matches = 0
    best = None
    improving = 0
    for record in records:
        if record.get("ok") is False or "pack" not in record:
            continue
        witness = table.get(record["pack"])
        if witness is None:
            continue
        matches += 1
        total = int(record["g"]) + int(witness.suffix_cost)
        if best is None or total < int(best["total"]):
            best = {
                "total": total,
                "prefix_g": int(record["g"]),
                "suffix_cost": int(witness.suffix_cost),
                "prefix_source": record.get("source"),
                "suffix_source": witness.source_label,
                "suffix_index": int(witness.action_index),
            }
        if total < int(incumbent):
            improving += 1
    return {
        "prefix_records": len(records),
        "exact_matches": matches,
        "best_total": None if best is None else int(best["total"]),
        "improving_combinations": improving,
        "best": best,
        "claim": "saved_path_splice_not_a_search",
        "record_definition": (
            "One record per route state, including the opening and the solved end, "
            "plus one end state for each distinct replay_ok action list in each saved ledger."
        ),
    }


def complete_from_prefix(opening, prefix: Sequence[Action], table: SuffixTable) -> dict:
    """Replay a prefix, append the exact-pack suffix, and verify the full game."""

    state, g = replay_cost(opening, prefix)
    pack = pack_state(state)
    witness = table.get(pack)
    if witness is None:
        return {"ok": False, "reason": "table_miss", "g": int(g)}
    full = list(prefix) + list(witness.suffix_actions)
    report = validate_solution(DEAL_ID, full, expected_deal_id=DEAL_ID)
    projected = int(g) + int(witness.suffix_cost)
    verified = None if not report.valid else int(report.mobilityware_moves)
    ok = bool(report.valid) and verified == projected
    return {
        "ok": ok,
        "reason": None if ok else (report.failure_reason or "verified cost disagreed with the witness"),
        "prefix_g": int(g),
        "suffix_cost": int(witness.suffix_cost),
        "projected": projected,
        "verified_g": verified,
        "actions": full,
        "source_label": witness.source_label,
        "source_hash16": witness.source_hash16,
        "action_index": int(witness.action_index),
        "explicit_commands": None if not report.valid else int(report.explicit_commands),
        "tableau_moves": None if not report.valid else int(report.tableau_moves),
        "stock_deals": None if not report.valid else int(report.stock_deals),
        "foundations": int(report.foundations) if report.foundations is not None else None,
    }


def publish_verified_game(directory: Path, actions: Sequence[Action], g: int, *, header: str) -> dict:
    """Write a new best once. The same path hash does not rewrite the file."""

    directory.mkdir(parents=True, exist_ok=True)
    digest = action_path_hash(actions)
    path = directory / f"4925153_assisted_{int(g)}.moves"
    if path.is_file():
        existing_actions = parse_moves_file(path)
        if action_path_hash(existing_actions) == digest:
            hashes = file_hashes(path)
            return {
                "path": path.as_posix(),
                "g": int(g),
                "path_hash16": digest,
                "rewritten": False,
                "sha256": hashes["raw_sha256"],
            }
        path = directory / f"4925153_assisted_{int(g)}_{len(actions)}.moves"
    temporary = directory / f".{path.name}.{os.getpid()}.tmp"
    export_actions_to_moves_file(list(actions), temporary, header=header)
    try:
        os.replace(temporary, path)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    hashes = file_hashes(path)
    sidecar = {
        "schema": SCHEMA,
        "g": int(g),
        "action_count": len(actions),
        "path_hash16": digest,
        "hashes": hashes,
        "moves": path.name,
        "validated": True,
    }
    atomic_write_json(path.with_suffix(".json"), sidecar)
    return {
        "path": path.as_posix(),
        "g": int(g),
        "path_hash16": digest,
        "rewritten": True,
        "sha256": hashes["raw_sha256"],
        "sidecar": path.with_suffix(".json").as_posix(),
    }


def best_published_g(directory: Path) -> Optional[int]:
    if not directory.is_dir():
        return None
    best = None
    for sidecar in directory.glob("4925153_assisted_*.json"):
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        moves = directory / str(payload.get("moves") or "")
        if not moves.is_file() or payload.get("validated") is not True:
            continue
        g = int(payload["g"])
        best = g if best is None else min(best, g)
    return best


class LiveSuffixChecker:
    """Match admitted physical packs. Do not prune on a miss or a costly suffix."""

    def __init__(
        self,
        table: SuffixTable,
        authenticated_prefix: Sequence[Action],
        incumbent: int,
        solution_dir: Optional[Path] = None,
    ) -> None:
        self.table = table
        self.authenticated_prefix = tuple(authenticated_prefix)
        self.incumbent = int(incumbent)
        self.solution_dir = None if solution_dir is None else Path(solution_dir)
        self.ceiling_box = None
        self.hits = 0
        self.misses = 0
        self.non_improving_hits = 0
        self.candidates = 0
        self.accepted = 0
        self.rejected = 0
        self.best = None
        self.publications = []

    def observe(self, kr, state, g: int, node: int):
        del state
        witness = self.table.get(kr.nodes[int(node)].store)
        if witness is None:
            self.misses += 1
            return None
        self.hits += 1
        projected = int(g) + int(witness.suffix_cost)
        if projected >= self.incumbent:
            self.non_improving_hits += 1
            return None
        self.candidates += 1
        full = list(self.authenticated_prefix) + reconstruct_path(kr.nodes, int(node)) + list(witness.suffix_actions)
        report = validate_solution(DEAL_ID, full, expected_deal_id=DEAL_ID)
        if not report.valid:
            self.rejected += 1
            return None
        verified = int(report.mobilityware_moves)
        if verified >= self.incumbent or verified != projected:
            self.rejected += 1
            return None
        published = None
        if self.solution_dir is not None:
            published = publish_verified_game(
                self.solution_dir,
                full,
                verified,
                header=(
                    f"Suffix-assisted solution for deal {DEAL_ID}. "
                    f"Corrected MW={verified}. Witness {witness.source_label} "
                    f"at action {witness.action_index}."
                ),
            )
        self.accepted += 1
        self.incumbent = verified
        if self.ceiling_box is not None and self.ceiling_box[0] is not None:
            self.ceiling_box[0] = verified - 1
        self.best = {
            "g": verified,
            "actions": full,
            "path_hash16": action_path_hash(full),
            "witness_source": witness.source_label,
            "witness_hash16": witness.source_hash16,
            "witness_index": int(witness.action_index),
            "published": published,
            "explicit_commands": int(report.explicit_commands),
            "tableau_moves": int(report.tableau_moves),
            "stock_deals": int(report.stock_deals),
            "foundations": int(report.foundations),
        }
        self.publications.append({key: value for key, value in self.best.items() if key != "actions"})
        return self.best

    def stats(self) -> dict:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "non_improving_hits": self.non_improving_hits,
            "candidates": self.candidates,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "incumbent": self.incumbent,
            "best_g": None if self.best is None else int(self.best["g"]),
            "publications": list(self.publications),
        }


def source_fingerprint(root: Path) -> dict:
    files = {}
    for relative in SOURCE_FILES:
        path = root / relative
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, encoding="utf-8"
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--short", "--untracked-files=all"],
            cwd=root,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
        dirty = ""
    return {
        "commit": commit,
        "dirty": bool(dirty.strip()),
        "files_sha256": files,
    }


def authenticate_inputs(root: Optional[Path] = None, *, ceiling: int = 157) -> dict:
    repo = Path(root) if root is not None else _repo_root()
    opening = opening_from_deal(repo / "deals" / f"{DEAL_ID}.txt")
    routes = load_own_routes(repo)
    table = build_suffix_table(opening, routes)
    shared = shared_prefix_length(routes)
    reference = next(route for route in routes if route["label"] == "158")
    indexes = [58, 120, 130, 140, 142, 143, shared]
    eligible = last_eligible_index(opening, reference["actions"], ceiling)
    if eligible is not None:
        indexes.append(eligible)
    bounds = {}
    for index in sorted(set(indexes)):
        if 0 <= int(index) <= len(reference["actions"]):
            bounds[str(index)] = bound_at(opening, reference["actions"], int(index))
    records = route_prefix_records(opening, routes)
    branches = saved_branch_records(opening, repo)
    splice = splice_saved_prefixes(table, records + branches, 158)
    improving = []
    if int(splice["improving_combinations"] or 0) > 0 and splice["best"] is not None:
        improving.append(splice["best"])
    return {
        "schema": SCHEMA,
        "deal_id": DEAL_ID,
        "routes": [
            {key: value for key, value in route.items() if key != "actions"}
            for route in routes
        ],
        "shared_prefix_actions": shared,
        "distinct_physical_states": len(table),
        "route_158_hash16": reference["path_hash16"],
        "bounds_on_158": bounds,
        "last_eligible_index": eligible,
        "last_eligible_bound": None if eligible is None else bounds.get(str(eligible)),
        "splice": splice,
        "saved_branch_records": len(branches),
        "verified_improving_splices": improving,
        "source": source_fingerprint(repo),
        "note": (
            "Suffix costs are completion witnesses. They are not admissible bounds. "
            "The splice check does not search and does not prove an unseen prefix is impossible."
        ),
    }


def _compact_branch(record: dict) -> dict:
    actions = record.get("actions") or []
    return {
        "g": record.get("g"),
        "replay_g": record.get("replay_g"),
        "replay_ok": record.get("replay_ok"),
        "foundations": record.get("foundations"),
        "face_down": record.get("face_down"),
        "stock_rows": record.get("stock_rows"),
        "action_count": len(actions),
        "actions": [format_action(action) if not isinstance(action, str) else action for action in actions],
    }


def improvement_label(best_g: Optional[int]) -> str:
    if best_g is not None and int(best_g) < 158:
        return "VERIFIED_IMPROVEMENT"
    return "NO_VERIFIED_IMPROVEMENT"


def load_attempt_ledger(path: Path, *, fingerprint: dict, machine: dict) -> dict:
    """Resume the suffix ledger. An unfinished attempt stays recorded as interrupted."""

    document = {
        "schema": SCHEMA,
        "running": True,
        "deal_id": DEAL_ID,
        "assistance": "incumbent_prefix_suffix_assisted",
        "machine": machine,
        "source": fingerprint,
        "attempts": [],
    }
    if path.is_file():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(previous, dict) and previous.get("schema") == SCHEMA:
            document["attempts"] = list(previous.get("attempts") or [])
            if previous.get("best_verified_g") is not None:
                document["best_verified_g"] = int(previous["best_verified_g"])
            for old in document["attempts"]:
                if isinstance(old, dict) and old.get("status") == "running":
                    old["status"] = "interrupted"
                    old["stop_reason"] = old.get("stop_reason") or "interrupted"
    return document


def run_prefix_attempt(
    *,
    action_index: int,
    time_limit_s: float,
    max_unique: int,
    memory_mb: float = 3000.0,
    checkpoint_s: float = 600.0,
    output_dir: Path,
    root: Optional[Path] = None,
    route_label: str = "158",
    incumbent: int = 158,
    ceiling: int = 157,
    log=None,
) -> dict:
    """Compact prefix-improve search from one authenticated own-route prefix."""

    repo = Path(root) if root is not None else _repo_root()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    opening = opening_from_deal(repo / "deals" / f"{DEAL_ID}.txt")
    routes = load_own_routes(repo)
    route = next(item for item in routes if item["label"] == route_label)
    if int(action_index) < 0 or int(action_index) > len(route["actions"]):
        raise ValueError("prefix index is outside the authenticated route")
    prefix = tuple(route["actions"][: int(action_index)])
    bound = bound_at(opening, route["actions"], int(action_index))
    table = build_suffix_table(opening, routes)
    published = best_published_g(output)
    active_incumbent = int(incumbent) if published is None else min(int(incumbent), int(published))
    host = probe_host_memory()
    applied = clamp_rss_mb(float(memory_mb), int(host["available_bytes"]), workers=1)
    checker = LiveSuffixChecker(table, prefix, active_incumbent, output)
    status_path = output / "status.json"
    started = time.time()
    fingerprint = source_fingerprint(repo)
    document = load_attempt_ledger(
        status_path,
        fingerprint=fingerprint,
        machine={
            "cpus": os.cpu_count(),
            "total_bytes": host.get("total_bytes"),
            "available_bytes": host.get("available_bytes"),
            "requested_rss_mb": float(memory_mb),
            "rss_cap_mb": float(applied),
            "workers": 1,
        },
    )
    attempt = {
        "id": f"p{len(document['attempts']) + 1}",
        "status": "running",
        "route_label": route_label,
        "route_hash16": route["path_hash16"],
        "prefix_index": int(action_index),
        "prefix_g": int(bound["g"]),
        "prefix_h": int(bound["h"]),
        "prefix_f": int(bound["f"]),
        "prefix_pack": bound["pack"],
        "prefix_hash16": action_path_hash(prefix),
        "incumbent": active_incumbent,
        "ceiling": int(ceiling),
        "representation": "compact",
        "time_limit_s": float(time_limit_s),
        "max_unique": int(max_unique),
        "rss_abort_mb": float(applied),
        "distinct_suffix_states": len(table),
        "seed_recorded": 0,
        "seed_wired_into_successor_order": False,
    }
    document["attempts"].append(attempt)
    atomic_write_json(status_path, document)
    last_write = time.perf_counter()

    def progress(kr, state, g, node):
        nonlocal last_write
        del state, g, node
        now = time.perf_counter()
        if now - last_write < float(checkpoint_s):
            return
        last_write = now
        attempt["unique"] = int(kr.unique)
        attempt["expanded"] = int(kr.expanded)
        attempt["lower_bound_prunes"] = int(kr.lower_bound_prunes)
        attempt["suffix"] = checker.stats()
        attempt["status"] = "running"
        document["running"] = True
        atomic_write_json(status_path, document)
        if log is not None:
            log(
                "CHECKPOINT "
                f"unique={kr.unique} expanded={kr.expanded} "
                f"suffix_hits={checker.hits} best={checker.incumbent}"
            )

    if log is not None:
        log(
            "PREFIX "
            f"index={action_index} g={bound['g']} h={bound['h']} f={bound['f']} "
            f"rss_cap_mb={applied:.2f} incumbent={active_incumbent}"
        )
    result = search_suit_ordered(
        opening,
        time_limit_s=float(time_limit_s),
        max_unique=int(max_unique),
        rss_abort_mb=float(applied),
        seed=0,
        mode="prefix-improve",
        incumbent_cost=active_incumbent,
        cost_ceiling=int(ceiling),
        advice_fn=None,
        prefix_actions=prefix,
        representation="compact",
        suffix_checker=checker,
        progress_hook=progress,
    )
    branches = []
    for name, record in result.leaders.items():
        item = _compact_branch(record)
        item["role"] = name
        branches.append(item)
    if result.best_partial is not None:
        item = _compact_branch(result.best_partial)
        item["role"] = "best_partial"
        branches.append(item)
    attempt.update(
        {
            "status": "finished",
            "stop_reason": result.stop_reason,
            "solved": bool(result.solved),
            "replay_ok": bool(result.replay_ok),
            "solution_g": result.solution_g,
            "unique": int(result.unique),
            "expanded": int(result.expanded),
            "generated": int(result.generated),
            "duplicate_skips": int(result.duplicate_skips),
            "stale_skips": int(result.stale_skips),
            "lower_bound_prunes": int(result.lower_bound_prunes),
            "elapsed_s": float(result.elapsed_s),
            "peak_rss_mb": result.peak_rss_mb,
            "max_foundations": int(result.max_foundations),
            "provenance": result.provenance,
            "search_kind": result.search_kind_label,
            "suffix": result.suffix_stats,
            "branches": branches,
            "wall_s": round(time.time() - started, 3),
        }
    )
    if result.solved and result.replay_ok and result.solution_g is not None:
        verified = int(result.solution_g)
        previous = document.get("best_verified_g")
        if previous is None or verified < int(previous):
            document["best_verified_g"] = verified
    document["running"] = False
    document["verified_improvement"] = improvement_label(document.get("best_verified_g"))
    atomic_write_json(status_path, document)
    if log is not None:
        log(
            "ATTEMPT "
            f"stop={result.stop_reason} solved={result.solved} "
            f"unique={result.unique} g={result.solution_g} peak={result.peak_rss_mb}"
        )
    return document
