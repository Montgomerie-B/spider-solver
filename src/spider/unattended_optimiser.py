"""Unattended suffix-assisted campaign for deal 4925153.

One worker selects jobs from the verified best route. A finished frontier is
an exhaustion claim only for that prefix, physical state, cost, rules and
ceiling. A stop, a crash, or a cap is not. An unlimited run keeps going until
every prefix inside the ceiling has that finished frontier.
"""

from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Optional

from spider.app_paths import local_app_root
from spider.autonomous_solve_campaign import atomic_write_json, read_text_shared
from spider.incumbent_suffix import (
    HISTORICAL_LABELS,
    _adopted_label,
    authenticate_moves_path,
    bound_at,
    run_prefix_attempt,
    select_campaign_route,
)
from spider.method_capture import action_path_hash
from spider.packaged_runtime import load_optimiser_routes, resource_report, runtime_identity

SCHEMA = "spider-play-lab-unattended-1"
DEAL_ID = "4925153"
RULES = "MW_RULES"
SEED_G = 140
SEED_HASH = "34a94de8e6edfa4b"
INITIAL_CEILING = 139
PRIORITY_INDEXES = (100, 90)
RECOVERY_TEXT = (
    "Interrupted before a clean finish. The exact search frontier was not retained. "
    "A later attempt starts again from the saved authenticated prefix. "
    "This is not an exhaustion claim."
)
CAP_STOPS = frozenset({
    "time limit",
    "unique limit",
    "rss abort",
    "depth limit",
    "harvested",
    "solved",
    "frontier key limit",
})
# Identities the disk frontier may retain. The RSS cap still bounds RAM.
DISK_IDENTITY_CAP = 2_000_000_000
EXHAUSTED_ROUTE_TEXT = (
    "The best route is exhausted under the current ceiling. "
    "No cheaper game remains inside that boundary."
)
HELD_ROUTE_TEXT = (
    "The best route is not optimised. Unfinished prefixes remain inside the ceiling. "
    "Their stored frontiers do not fit in the memory safety cap. "
    "Waiting, then continuing one of them."
)
RETAINED_FRONTIER_TEXT = (
    "The search frontier is stored on disk. A later attempt continues from that frontier. "
    "This is not an exhaustion claim."
)


def default_optimiser_dir() -> Path:
    return local_app_root() / "PlayLab" / "Optimiser" / DEAL_ID


def publish_verified_moves(path: Path, directory: Path) -> str:
    """Copy one replayed assisted game into the Load dialog folder.

    The campaign directory stays outside that folder. Identical bytes are
    left alone. Different bytes are left alone. A folder that cannot be
    written does not fail the campaign.
    """

    try:
        source = Path(path)
        name = source.name
        if not name.startswith("4925153_assisted_") or not name.endswith(".moves"):
            return "skipped"
        if not source.is_file():
            return "skipped"
        destination_dir = Path(directory)
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / name
        if destination.exists() and source.resolve() == destination.resolve():
            return "identical"
        payload = source.read_bytes()
        if destination.is_file():
            if destination.read_bytes() == payload:
                return "identical"
            return "different"
        destination.write_bytes(payload)
        return "written"
    except OSError:
        return "skipped"


def assert_campaign_dir(path: Path) -> Path:
    resolved = Path(path).resolve()
    parts = {part.lower() for part in resolved.parts}
    if "solutions" in parts:
        raise ValueError("the optimiser does not write the solutions directory")
    if "pre120_optimisation" in parts or "incumbent_suffix_optimisation" in parts:
        raise ValueError("the optimiser does not write the research campaign directories")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def read_json(path: Path, default: Optional[dict] = None) -> dict:
    if not path.is_file():
        return {} if default is None else dict(default)
    try:
        payload = json.loads(read_text_shared(path))
    except (OSError, json.JSONDecodeError):
        return {} if default is None else dict(default)
    return payload if isinstance(payload, dict) else {}


def normalise_settings(settings: dict) -> dict:
    unlimited = bool(settings.get("unlimited"))
    requested = float(settings.get("requested_rss_mb") or 3000)
    unique = settings.get("max_unique")
    if requested <= 0:
        raise ValueError("duration, attempt time and memory must be positive")
    if unlimited:
        return {
            "unlimited": True,
            "campaign_duration_s": 0.0,
            "attempt_time_limit_s": 0.0,
            "requested_rss_mb": requested,
            "max_unique": None if unique in (None, "") else int(unique),
            "workers": 1,
        }
    duration = float(settings.get("campaign_duration_s") or 20 * 60)
    attempt = float(settings.get("attempt_time_limit_s") or 180)
    if duration <= 0 or attempt <= 0:
        raise ValueError("duration, attempt time and memory must be positive")
    return {
        "unlimited": False,
        "campaign_duration_s": duration,
        "attempt_time_limit_s": attempt,
        "requested_rss_mb": requested,
        "max_unique": None if unique is None else int(unique),
        "workers": 1,
    }


def configuration(settings: dict, resources: dict) -> dict:
    return {
        "representation": "compact",
        "advice": "off",
        "lanes": "seven-suit-ordered",
        "seed": 0,
        "seed_wired": False,
        "workers": 1,
        "time_limit_s": round(float(settings["attempt_time_limit_s"]), 3),
        "requested_rss_mb": round(float(resources["requested_rss_mb"]), 2),
        "effective_rss_mb": round(float(resources["effective_rss_mb"]), 2),
        "requested_max_unique": int(resources["requested_max_unique"]),
        "max_unique": int(resources["effective_max_unique"]),
        "checkpoint_s": 2.0,
        "frontier_generation": 0,
    }


def configuration_key(cfg: dict) -> tuple:
    return (
        round(float(cfg["time_limit_s"]), 3),
        int(cfg["max_unique"]),
        round(float(cfg["effective_rss_mb"]), 2),
        str(cfg["representation"]),
        str(cfg["advice"]),
        int(cfg["workers"]),
        int(cfg["seed"]),
        int(cfg.get("frontier_generation") or 0),
    )


def work_key(identity: dict) -> tuple:
    ancestry = identity["ancestry"]
    return (
        str(identity["physical_pack"]),
        int(identity["accumulated_g"]),
        str(ancestry["prefix_hash16"]),
        str(identity["rules"]),
        int(identity["ceiling"]),
        configuration_key(identity["configuration"]),
    )


def classify_stop(stop_reason: Optional[str], *, terminated: bool, requested_stop: bool) -> dict:
    if terminated or requested_stop:
        state = "stopped" if requested_stop else "interrupted"
        return {
            "state": state,
            "exhausted": False,
            "stop_reason": state,
            "recovery": RECOVERY_TEXT,
        }
    reason = str(stop_reason or "failed")
    if reason == "complete":
        return {"state": "complete", "exhausted": True, "stop_reason": reason, "recovery": None}
    if reason in CAP_STOPS or reason == "failed":
        return {"state": reason, "exhausted": False, "stop_reason": reason, "recovery": None}
    return {"state": "failed", "exhausted": False, "stop_reason": reason, "recovery": None}


UNKNOWN_CEILING_NOTE = (
    "The final live ceiling was not recorded. "
    "This evidence does not establish exhaustion at the launch ceiling."
)


def exhaustion_scope(job: dict) -> str:
    identity = job["identity"]
    ancestry = identity["ancestry"]
    launch = int(identity["ceiling"])
    final = job.get("effective_ceiling")
    final_text = "unrecorded" if final is None else str(int(final))
    return (
        f"exact authenticated prefix {ancestry['prefix_hash16']} "
        f"after action {ancestry['prefix_index']} of route {ancestry['route_hash16']}, "
        f"physical pack {identity['physical_pack']}, "
        f"accumulated g={identity['accumulated_g']}, "
        f"deal {DEAL_ID}, rules {identity['rules']}, "
        f"launch ceiling {launch}, final live ceiling {final_text}, "
        f"compact suffix-assisted configuration"
    )


def qualify_saved_exhaustion(job: dict) -> None:
    """Mark an older exhaustion record whose live ceiling was not stored.

    The launch ceiling, the exhausted flag, and the original scope text stay.
    Coverage does not treat that record as exhaustion through the launch ceiling.
    """

    if not job.get("exhausted"):
        return
    if job.get("effective_ceiling") is not None:
        job["exhaustion_ceiling_known"] = True
        return
    job["exhaustion_ceiling_known"] = False
    if not job.get("exhaustion_ceiling_note"):
        job["exhaustion_ceiling_note"] = UNKNOWN_CEILING_NOTE


def attempt_budget(control: dict, planned_s: float, *, now: Optional[float] = None) -> dict:
    """Cap a new attempt at the campaign time still remaining.

    A non-positive plan is an unlimited attempt. It is not a deadline.
    """

    planned = float(planned_s)
    if planned <= 0:
        return {
            "planned_time_limit_s": 0.0,
            "applied_time_limit_s": 0.0,
            "deadline_limited": False,
            "unlimited": True,
        }
    moment = time.time() if now is None else float(now)
    settings = control.get("settings") or {}
    duration = float(settings.get("campaign_duration_s") or 0)
    started = control.get("run_started_at")
    if not started or duration <= 0:
        applied = planned
    else:
        remaining = float(duration) - (moment - float(started))
        applied = min(planned, remaining)
    if applied < 0:
        applied = 0.0
    return {
        "planned_time_limit_s": round(planned, 3),
        "applied_time_limit_s": round(applied, 3),
        "deadline_limited": planned - applied > 0.05,
        "unlimited": False,
    }


def coerce_run_start(control: dict, now: float) -> float:
    """Keep an existing campaign clock. A fresh Resume starts one."""

    started = control.get("run_started_at")
    if started:
        return float(started)
    return float(now)


def _terminal(job: dict) -> bool:
    return str(job.get("state") or "queued") != "queued"


def covered_by_exhaustion(identity: dict, jobs: list) -> bool:
    for job in jobs:
        if not job.get("exhausted"):
            continue
        if job.get("exhaustion_ceiling_known") is False or job.get("effective_ceiling") is None:
            continue
        previous = job["identity"]
        if previous["physical_pack"] != identity["physical_pack"]:
            continue
        if int(previous["accumulated_g"]) != int(identity["accumulated_g"]):
            continue
        if previous["ancestry"]["prefix_hash16"] != identity["ancestry"]["prefix_hash16"]:
            continue
        if previous["rules"] != identity["rules"]:
            continue
        # The live ceiling at completion, not the ceiling used to launch the job.
        if int(identity["ceiling"]) <= int(job["effective_ceiling"]):
            return True
    return False


def identical_terminal(identity: dict, jobs: list) -> bool:
    key = work_key(identity)
    for job in jobs:
        if not _terminal(job):
            continue
        # A campaign deadline did not finish the planned attempt.
        if str(job.get("stop_reason") or "") == "deadline":
            continue
        if work_key(job["identity"]) == key:
            return True
    return False


def prefix_was_interrupted(prefix_hash: str, jobs: list) -> bool:
    for job in jobs:
        if job.get("state") not in {"interrupted", "stopped"}:
            continue
        if job["identity"]["ancestry"]["prefix_hash16"] == prefix_hash:
            return True
    return False


def eligible_indexes(actions) -> list:
    """Prefix lengths the widener searches. The empty opening is not a root."""

    priority_rank = {index: pos for pos, index in enumerate(PRIORITY_INDEXES)}
    ordered = [index for index in PRIORITY_INDEXES if 0 < index < len(actions)]
    ordered.extend(index for index in range(1, len(actions)) if index not in priority_rank)
    return ordered


def _prefix_identity(route, index, bound, prefix_hash, ceiling, cfg) -> dict:
    return {
        "physical_pack": bound["pack"],
        "accumulated_g": int(bound["g"]),
        "ancestry": {
            "route_label": str(route["label"]),
            "route_hash16": str(route["path_hash16"]),
            "prefix_index": index,
            "prefix_hash16": prefix_hash,
        },
        "rules": RULES,
        "ceiling": int(ceiling),
        "configuration": dict(cfg),
    }


def _same_prefix(job: dict, identity: dict) -> bool:
    previous = job.get("identity") or {}
    ancestry = previous.get("ancestry") or {}
    wanted = identity["ancestry"]
    if previous.get("physical_pack") != identity["physical_pack"]:
        return False
    if int(previous.get("accumulated_g") or -1) != int(identity["accumulated_g"]):
        return False
    if ancestry.get("prefix_hash16") != wanted["prefix_hash16"]:
        return False
    return previous.get("rules") == identity["rules"]


def _generation(job: dict) -> int:
    cfg = (job.get("identity") or {}).get("configuration") or {}
    return int(cfg.get("frontier_generation") or 0)


def _latest_at_ceiling(jobs: list, identity: dict, ceiling: int) -> Optional[dict]:
    matched = [
        job for job in jobs
        if _terminal(job)
        and _same_prefix(job, identity)
        and int((job.get("identity") or {}).get("ceiling") or -1) == int(ceiling)
    ]
    if not matched:
        return None
    return max(matched, key=lambda job: (_generation(job), float(job.get("finished_at") or 0)))


def _proven_ceiling(jobs: list, identity: dict) -> Optional[int]:
    best = None
    for job in jobs:
        if not job.get("exhausted"):
            continue
        if job.get("exhaustion_ceiling_known") is False or job.get("effective_ceiling") is None:
            continue
        if not _same_prefix(job, identity):
            continue
        value = int(job["effective_ceiling"])
        best = value if best is None else max(best, value)
    return best


def _prefix_is_open(jobs: list, identity: dict) -> bool:
    return any(not _terminal(job) and _same_prefix(job, identity) for job in jobs)


def route_boundary_exhausted(route: dict, opening, ceiling: int, jobs: list) -> bool:
    """True when every in-ceiling prefix has a finished frontier at that ceiling."""

    actions = list(route["actions"])
    for index in eligible_indexes(actions):
        bound = bound_at(opening, actions, index)
        if int(bound["f"]) > int(ceiling):
            continue
        identity = _prefix_identity(
            route,
            index,
            bound,
            action_path_hash(tuple(actions[:index])),
            ceiling,
            {"frontier_generation": 0},
        )
        if not covered_by_exhaustion(identity, jobs):
            return False
    return True


def _slice_job(route, index, bound, prefix_hash, target, cfg, priority_rank, jobs) -> Optional[dict]:
    identity = _prefix_identity(route, index, bound, prefix_hash, target, cfg)
    if any(work_key(item["identity"]) == work_key(identity) for item in jobs):
        return None
    recovery = RETAINED_FRONTIER_TEXT if cfg.get("resume_frontier") else None
    if recovery is None and prefix_was_interrupted(prefix_hash, jobs):
        recovery = RECOVERY_TEXT
    return {
        "id": "",
        "state": "queued",
        "index": index,
        "route_label": str(route["label"]),
        "route_hash16": str(route["path_hash16"]),
        "bound": {"g": int(bound["g"]), "h": int(bound["h"]), "f": int(bound["f"])},
        "identity": identity,
        "exhausted": False,
        "exhaustion_scope": None,
        "stop_reason": None,
        "recovery": recovery,
        "priority": index in priority_rank,
        "frontier_retained": False,
        "frontier_stuck": False,
        "frontier_path": None,
    }


def _continuation(latest: dict, *, target: int, route, index, bound, prefix_hash, cfg_base, priority_rank, jobs):
    """One fresh spill, or a resume, or nothing when this ceiling is stuck."""

    if latest is None:
        cfg = dict(cfg_base)
        cfg["frontier_generation"] = 0
        cfg.pop("resume_frontier", None)
        return _slice_job(route, index, bound, prefix_hash, target, cfg, priority_rank, jobs)
    if latest.get("exhausted"):
        return None
    if latest.get("frontier_retained") and not latest.get("frontier_stuck") and latest.get("frontier_path"):
        cfg = dict(cfg_base)
        cfg["frontier_generation"] = _generation(latest) + 1
        cfg["resume_frontier"] = str(latest["frontier_path"])
        return _slice_job(route, index, bound, prefix_hash, target, cfg, priority_rank, jobs)
    if (
        not latest.get("frontier_retained")
        and not latest.get("frontier_stuck")
        and _generation(latest) == 0
    ):
        cfg = dict(cfg_base)
        cfg["frontier_generation"] = 1
        cfg.pop("resume_frontier", None)
        return _slice_job(route, index, bound, prefix_hash, target, cfg, priority_rank, jobs)
    return None


def _unlimited_slice(route, index, bound, prefix_hash, ceiling, cfg_base, jobs, priority_rank):
    full = _prefix_identity(route, index, bound, prefix_hash, ceiling, cfg_base)
    latest = _latest_at_ceiling(jobs, full, ceiling)
    chosen = _continuation(
        latest,
        target=int(ceiling),
        route=route,
        index=index,
        bound=bound,
        prefix_hash=prefix_hash,
        cfg_base=cfg_base,
        priority_rank=priority_rank,
        jobs=jobs,
    )
    if chosen is not None:
        return chosen
    if latest is None:
        return None
    proven = _proven_ceiling(jobs, full)
    target = int(bound["f"]) if proven is None else int(proven) + 1
    if target >= int(ceiling):
        return None
    band = _latest_at_ceiling(jobs, full, target)
    return _continuation(
        band,
        target=target,
        route=route,
        index=index,
        bound=bound,
        prefix_hash=prefix_hash,
        cfg_base=cfg_base,
        priority_rank=priority_rank,
        jobs=jobs,
    )


def _assign_ids(jobs: list, chosen: list) -> list:
    next_number = 1 + max(
        [int(str(job["id"])[1:]) for job in jobs if str(job.get("id", "")).startswith("j")] or [0]
    )
    for job in chosen:
        job["id"] = f"j{next_number}"
        next_number += 1
    return chosen


def plan_unlimited_jobs(route: dict, opening, *, ceiling: int, settings: dict, resources: dict, jobs: list) -> tuple[list, list]:
    """Keep a slice queued until every in-ceiling prefix is exhausted.

    The full ceiling is first. A stored frontier is resumed. A cap with no
    stored frontier is tried once more with a disk frontier. After that the
    prefix climbs one cost at a time from its admissible f.
    """

    cfg_base = configuration(settings, resources)
    cfg_base["max_unique"] = DISK_IDENTITY_CAP
    notes = []
    created = []
    extras = []
    actions = list(route["actions"])
    priority_rank = {index: pos for pos, index in enumerate(PRIORITY_INDEXES)}
    for index in eligible_indexes(actions):
        bound = bound_at(opening, actions, index)
        prefix_hash = action_path_hash(tuple(actions[:index]))
        if int(bound["f"]) > int(ceiling):
            notes.append(
                f"Skipped action {index}: admissible f={bound['f']} is above ceiling {ceiling}."
            )
            continue
        identity = _prefix_identity(route, index, bound, prefix_hash, ceiling, cfg_base)
        already = jobs + created + extras
        if covered_by_exhaustion(identity, already):
            notes.append(f"Skipped action {index}: already exhausted at this ceiling or a higher one.")
            continue
        if _prefix_is_open(already, identity):
            continue
        job = _unlimited_slice(
            route, index, bound, prefix_hash, ceiling, cfg_base, already, priority_rank,
        )
        if job is None:
            notes.append(
                f"Action {index} is held. Its frontier is stored and does not fit "
                "in the memory safety cap. It stays unfinished."
            )
            continue
        if index in priority_rank:
            created.append(job)
        else:
            extras.append(job)
    created.sort(key=lambda item: priority_rank[int(item["index"])])
    extras.sort(key=lambda item: (-int(item["bound"]["f"]), -int(item["index"])))
    return _assign_ids(jobs, created + extras), notes


def plan_jobs(route: dict, opening, *, ceiling: int, settings: dict, resources: dict, jobs: list) -> tuple[list, list]:
    """Queue prefixes of the best route that stay inside its cost.

    Actions 100 and 90 stay first. Every other prefix of this route follows,
    tightest admissible f first, so the analysis widens down from the ceiling.
    A prefix is not rejected for being at action 120 or later. The ceiling and
    an exhausted pack are the boundary. Unlimited runs use plan_unlimited_jobs.
    """

    if settings.get("unlimited"):
        return plan_unlimited_jobs(
            route, opening, ceiling=ceiling, settings=settings, resources=resources, jobs=jobs,
        )
    cfg = configuration(settings, resources)
    notes = []
    created = []
    extras = []
    actions = list(route["actions"])
    priority_rank = {index: pos for pos, index in enumerate(PRIORITY_INDEXES)}
    ordered = eligible_indexes(actions)
    for index in ordered:
        if index > len(actions):
            notes.append(f"Skipped action {index}: past the end of route {route['label']}.")
            continue
        bound = bound_at(opening, actions, index)
        prefix = tuple(actions[:index])
        identity = {
            "physical_pack": bound["pack"],
            "accumulated_g": int(bound["g"]),
            "ancestry": {
                "route_label": str(route["label"]),
                "route_hash16": str(route["path_hash16"]),
                "prefix_index": index,
                "prefix_hash16": action_path_hash(prefix),
            },
            "rules": RULES,
            "ceiling": int(ceiling),
            "configuration": dict(cfg),
        }
        if int(bound["f"]) > int(ceiling):
            notes.append(
                f"Skipped action {index}: admissible f={bound['f']} is above ceiling {ceiling}."
            )
            continue
        already = jobs + created + extras
        if covered_by_exhaustion(identity, already):
            notes.append(f"Skipped action {index}: already exhausted at this ceiling or a higher one.")
            continue
        if identical_terminal(identity, already):
            notes.append(f"Skipped action {index}: an identical capped or finished job is already recorded.")
            continue
        if any(work_key(item["identity"]) == work_key(identity) for item in already):
            continue
        recovery = None
        if prefix_was_interrupted(identity["ancestry"]["prefix_hash16"], jobs):
            recovery = RECOVERY_TEXT
        job = {
            "id": "",
            "state": "queued",
            "index": index,
            "route_label": str(route["label"]),
            "route_hash16": str(route["path_hash16"]),
            "bound": {"g": int(bound["g"]), "h": int(bound["h"]), "f": int(bound["f"])},
            "identity": identity,
            "exhausted": False,
            "exhaustion_scope": None,
            "stop_reason": None,
            "recovery": recovery,
            "priority": index in priority_rank,
        }
        if index in priority_rank:
            created.append(job)
        else:
            extras.append(job)
    created.sort(key=lambda item: priority_rank[int(item["index"])])
    extras.sort(key=lambda item: (-int(item["bound"]["f"]), -int(item["index"])))
    chosen = created + extras
    next_number = 1 + max(
        [int(str(job["id"])[1:]) for job in jobs if str(job.get("id", "")).startswith("j")] or [0]
    )
    for job in chosen:
        job["id"] = f"j{next_number}"
        next_number += 1
    return chosen, notes


class OptimiserCampaign:
    def __init__(
        self,
        directory: Path,
        root: Optional[Path] = None,
        dialog_directory: Optional[Path] = None,
    ):
        from spider.app_paths import repo_root

        self.directory = assert_campaign_dir(directory)
        self.root = Path(root) if root is not None else repo_root()
        self.dialog_directory = (
            Path(dialog_directory) if dialog_directory is not None else self.root / "solutions"
        )
        self.campaign_path = self.directory / "campaign.json"
        self.state_path = self.directory / "state.json"
        self.campaign = self._fresh()
        self.routes: list = []
        self.opening = None

    def _fresh(self) -> dict:
        return {
            "schema": SCHEMA,
            "deal_id": DEAL_ID,
            "rules": RULES,
            "phase": "idle",
            "incumbent_g": SEED_G,
            "ceiling": INITIAL_CEILING,
            "seed": None,
            "source": None,
            "resources": None,
            "settings": None,
            "jobs": [],
            "activity": [],
            "best": None,
            "run_started_at": None,
            "skips": [],
        }

    def load(self) -> dict:
        payload = read_json(self.campaign_path)
        if payload.get("schema") == SCHEMA:
            self.campaign = payload
            self.campaign.setdefault("jobs", [])
            self.campaign.setdefault("activity", [])
            self.campaign.setdefault("skips", [])
            for job in self.campaign["jobs"]:
                if isinstance(job, dict):
                    qualify_saved_exhaustion(job)
        return self.campaign

    def save(self) -> None:
        atomic_write_json(self.campaign_path, self.campaign)

    def log(self, line: str, *, persist: bool = True) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.campaign["activity"] = (list(self.campaign.get("activity") or []) + [f"{stamp}  {line}"])[-200:]
        if persist:
            self.save()
        try:
            self.write_state()
        except OSError as exc:
            # A locked snapshot is stale for one checkpoint. The search continues.
            self.campaign["activity"] = (
                list(self.campaign.get("activity") or [])
                + [f"{stamp}  Snapshot skipped: {type(exc).__name__}: {exc}"]
            )[-200:]

    def write_state(self, **extra) -> None:
        current = next((job for job in self.campaign.get("jobs") or [] if job.get("state") == "running"), None)
        resources = self.campaign.get("resources") or {}
        attempt = {}
        elapsed = None
        if current is not None:
            attempt = _latest_attempt(self.directory / "jobs" / str(current["id"]) / "search")
            if current.get("started_at"):
                elapsed = round(time.time() - float(current["started_at"]), 3)
        payload = {
            "schema": SCHEMA,
            "phase": self.campaign.get("phase"),
            "deal_id": DEAL_ID,
            "incumbent_g": self.campaign.get("incumbent_g"),
            "ceiling": self.campaign.get("ceiling"),
            "best": self.campaign.get("best"),
            "resources": resources,
            "current_job": None if current is None else {
                "id": current.get("id"),
                "index": current.get("index"),
                "route_label": current.get("route_label"),
                "bound": current.get("bound"),
                "state": current.get("state"),
            },
            "jobs": [
                {
                    "id": job.get("id"),
                    "state": job.get("state"),
                    "index": job.get("index"),
                    "exhausted": bool(job.get("exhausted")),
                    "stop_reason": job.get("stop_reason"),
                    "recovery": job.get("recovery"),
                    "bound": job.get("bound"),
                }
                for job in self.campaign.get("jobs") or []
                if isinstance(job, dict)
            ],
            "activity": list(self.campaign.get("activity") or [])[-40:],
            "queue_remaining": sum(1 for job in self.campaign.get("jobs") or [] if job.get("state") == "queued"),
            "unique": attempt.get("unique"),
            "expanded": attempt.get("expanded"),
            "peak_rss_mb": attempt.get("peak_rss_mb"),
            "elapsed_s": elapsed,
        }
        payload.update(extra)
        atomic_write_json(self.state_path, payload)

    def recover_running(self, *, requested_stop: bool) -> int:
        changed = 0
        for job in self.campaign.get("jobs") or []:
            if job.get("state") != "running":
                continue
            outcome = classify_stop(None, terminated=True, requested_stop=requested_stop)
            job["state"] = outcome["state"]
            job["exhausted"] = False
            job["stop_reason"] = outcome["stop_reason"]
            job["recovery"] = outcome["recovery"]
            job["exhaustion_scope"] = None
            spill = self.directory / "jobs" / str(job.get("id")) / "search" / "frontier.sqlite"
            from spider.search_spill import FrontierSpill

            stored = FrontierSpill.peek(spill)
            if stored and stored.get("resumable"):
                job["frontier_retained"] = True
                job["frontier_stuck"] = False
                job["frontier_path"] = str(spill)
                job["recovery"] = RETAINED_FRONTIER_TEXT
            changed += 1
        if changed:
            self.campaign["phase"] = "stopped" if requested_stop else "interrupted"
            self.log(
                f"Recorded {changed} unfinished job(s) as "
                f"{'stopped' if requested_stop else 'interrupted'}. {RECOVERY_TEXT}"
            )
        return changed

    def authenticate(self) -> None:
        routes, payload = load_optimiser_routes(self.root)
        self.routes = routes
        self.opening = payload["opening"]
        seed = payload["seed"]
        if seed["path_hash16"] != SEED_HASH or int(seed["g"]) != SEED_G:
            raise ValueError("authenticated seed is not the accepted 140 game")
        self.campaign["seed"] = {
            "label": seed["label"],
            "g": int(seed["g"]),
            "path_hash16": seed["path_hash16"],
            "path": str(self.root / payload["manifest"]["seed"]["relative"]),
        }
        self.campaign["source"] = runtime_identity(self.root)
        if self.campaign.get("best") is None:
            self.campaign["best"] = {
                "g": SEED_G,
                "path": self.campaign["seed"]["path"],
                "path_hash16": SEED_HASH,
                "verified": True,
                "source": "seed",
            }
            self.campaign["incumbent_g"] = SEED_G
            self.campaign["ceiling"] = INITIAL_CEILING
        self.adopt_files()
        self.log(
            f"Authenticated {seed['label']} route {seed['path_hash16']}. "
            f"Incumbent {self.campaign['incumbent_g']}, ceiling {self.campaign['ceiling']}."
        )

    def adopt_files(self) -> list:
        """Replay saved games and put every verified route back into the search sources.

        A route whose cost equals the persisted incumbent is still a source.
        Intermediate improvements are sources too. The best claim is then
        reconciled with the files that actually replayed.
        """

        restored = []
        if self.opening is None:
            self._reconcile_best(restored)
            return []
        for path in self._published_files():
            try:
                route = authenticate_moves_path(self.opening, path, label="published", root=self.root)
            except (OSError, ValueError) as exc:
                self.log(f"Rejected {path.name}: {exc}")
                continue
            self._ensure_route(route, path)
            restored.append((route, path))
        self._reconcile_best(restored)
        return [route for route, _path in restored]

    def _publish_dialog_copy(self, route: dict, path: Path) -> None:
        status = publish_verified_moves(path, self.dialog_directory)
        if status == "written":
            self.log(f"Copied verified {route['g']} into the load dialog as {path.name}.")
        elif status == "different":
            self.log(f"Left the load-dialog copy of {path.name} unchanged. Its bytes differ.")

    def _ensure_route(self, route: dict, path: Path) -> bool:
        digest = str(route["path_hash16"])
        self._publish_dialog_copy(route, path)
        if any(item["path_hash16"] == digest for item in self.routes):
            return False
        stored = dict(route)
        stored["label"] = _adopted_label(self.routes, int(route["g"]), digest)
        stored["adopted"] = True
        self.routes.append(stored)
        destination = self.directory / "verified" / path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if path.resolve() != destination.resolve() and not destination.is_file():
            destination.write_bytes(path.read_bytes())
        self.log(
            f"Restored verified {stored['g']} ({digest}) into the search and suffix sources."
        )
        return True

    def _reconcile_best(self, restored: list) -> None:
        by_hash = {str(route["path_hash16"]): path for route, path in restored}
        playable = [
            route for route in self.routes
            if route.get("label") not in HISTORICAL_LABELS and route.get("actions") is not None
        ]
        supported = {str(route["path_hash16"]) for route in playable}
        persisted = dict(self.campaign.get("best") or {})
        claimed = str(persisted.get("path_hash16") or "")
        if claimed and claimed not in supported:
            self.log(f"Withdrew persisted best {claimed}: no replayed file supports it.")
        if not playable:
            self.campaign["best"] = {
                "g": persisted.get("g"),
                "path": persisted.get("path"),
                "path_hash16": claimed or None,
                "verified": False,
                "source": "withdrawn",
            }
            if claimed:
                self.log("No replayed route supports a verified best.")
            return
        best_route = min(playable, key=lambda route: (int(route["g"]), str(route["label"])))
        path = by_hash.get(str(best_route["path_hash16"]))
        if path is None:
            raw = best_route.get("path")
            if raw:
                candidate = Path(str(raw))
                if not candidate.is_file():
                    rooted = self.root / str(raw)
                    candidate = rooted if rooted.is_file() else candidate
                path = candidate
        previous = int(self.campaign.get("incumbent_g") or best_route["g"])
        self.campaign["incumbent_g"] = int(best_route["g"])
        self.campaign["ceiling"] = int(best_route["g"]) - 1
        self.campaign["best"] = {
            "g": int(best_route["g"]),
            "path": "" if path is None else str(path),
            "path_hash16": best_route["path_hash16"],
            "verified": True,
            "source": "replay",
        }
        if int(best_route["g"]) < previous:
            self.log(
                f"Adopted verified {best_route['g']} ({best_route['path_hash16']}) "
                f"after a full opening replay. Ceiling is now {self.campaign['ceiling']}."
            )
        elif int(best_route["g"]) != previous:
            self.campaign["jobs"] = [
                job for job in self.campaign.get("jobs") or [] if job.get("state") != "queued"
            ]
            self.log(
                f"Verified best is {best_route['g']} ({best_route['path_hash16']}). "
                "Queued jobs were dropped because the persisted incumbent was not replayed."
            )

    def _published_files(self) -> list[Path]:
        found = []
        verified = self.directory / "verified"
        if verified.is_dir():
            found.extend(sorted(verified.glob("4925153_assisted_*.moves")))
        jobs = self.directory / "jobs"
        if jobs.is_dir():
            found.extend(sorted(jobs.glob("*/search/4925153_assisted_*.moves")))
        return found

    def apply_settings(self, settings: dict) -> None:
        chosen = normalise_settings(settings)
        signature = (
            chosen["campaign_duration_s"],
            chosen["attempt_time_limit_s"],
            chosen["requested_rss_mb"],
            chosen["max_unique"],
        )
        if signature == getattr(self, "_settings_signature", None) and self.campaign.get("resources"):
            return
        fit = bool(chosen.get("unlimited") and chosen.get("max_unique") is None)
        resources = resource_report(chosen["requested_rss_mb"], chosen["max_unique"], fit_to_rss=fit)
        chosen["max_unique"] = int(resources["effective_max_unique"])
        self._settings_signature = signature
        self.campaign["settings"] = chosen
        self.campaign["resources"] = resources
        self.log(
            "Resources: "
            f"requested {resources['requested_rss_mb']:.2f} MB, "
            f"effective {resources['effective_rss_mb']:.2f} MB, "
            f"one worker, unique cap {resources['effective_max_unique']}. "
            f"{resources['retained_state_note']}",
            persist=False,
        )

    def ensure_queue(self) -> None:
        route = select_campaign_route(self.routes, "best")
        if route["label"] in HISTORICAL_LABELS:
            raise ValueError("historical games are suffix sources, not search roots")
        new_jobs, notes = plan_jobs(
            route,
            self.opening,
            ceiling=int(self.campaign["ceiling"]),
            settings=self.campaign["settings"],
            resources=self.campaign["resources"],
            jobs=list(self.campaign["jobs"]),
        )
        known = set(self.campaign.get("skips") or [])
        for note in notes:
            if note not in known:
                self.campaign["skips"].append(note)
                self.log(note, persist=False)
        if new_jobs:
            self.campaign["jobs"].extend(new_jobs)
            described = ", ".join(
                f"{job['index']} (f={job['bound']['f']})" for job in new_jobs[:6]
            )
            more = "" if len(new_jobs) <= 6 else f" and {len(new_jobs) - 6} later prefixes"
            self.log(
                f"Queued {described}{more} along route {route['label']} "
                f"under ceiling {self.campaign['ceiling']}."
            )
        else:
            self.save()

    def next_queued(self) -> Optional[dict]:
        queued = [job for job in self.campaign["jobs"] if job.get("state") == "queued"]
        if not queued:
            return None
        if (self.campaign.get("settings") or {}).get("unlimited"):
            for job in queued:
                cfg = (job.get("identity") or {}).get("configuration") or {}
                if cfg.get("resume_frontier"):
                    return job
        return queued[0]

    def boundary_exhausted(self) -> bool:
        route = select_campaign_route(self.routes, "best")
        return route_boundary_exhausted(
            route,
            self.opening,
            int(self.campaign["ceiling"]),
            list(self.campaign.get("jobs") or []),
        )

    def release_one_hold(self) -> bool:
        """Let one stored frontier try again after the memory cap blocked it."""

        for job in reversed(list(self.campaign.get("jobs") or [])):
            if not job.get("frontier_stuck"):
                continue
            job["frontier_stuck"] = False
            self.log(
                f"Retrying the stored frontier of {job.get('id')} on action {job.get('index')}."
            )
            return True
        return False

    def run_expired(self, control: dict) -> bool:
        started = control.get("run_started_at")
        duration = float((control.get("settings") or {}).get("campaign_duration_s") or 0)
        if not started or duration <= 0:
            return False
        return (time.time() - float(started)) >= duration

    def execute(self, job: dict) -> dict:
        search_dir = self.directory / "jobs" / job["id"] / "search"
        search_dir.mkdir(parents=True, exist_ok=True)
        cfg = job["identity"]["configuration"]
        budget = attempt_budget(read_control(self.directory), cfg["time_limit_s"])
        job["planned_time_limit_s"] = budget["planned_time_limit_s"]
        job["applied_time_limit_s"] = budget["applied_time_limit_s"]
        job["deadline_limited"] = bool(budget["deadline_limited"])
        self.campaign["phase"] = "running"
        job["state"] = "running"
        job["started_at"] = time.time()
        self.log(
            f"Started {job['id']} on action {job['index']} of route {job['route_label']}. "
            f"g={job['bound']['g']} h={job['bound']['h']} f={job['bound']['f']}. "
            f"Requested RSS {cfg['requested_rss_mb']:.2f} MB, "
            f"effective {cfg['effective_rss_mb']:.2f} MB. "
            f"Planned attempt {budget['planned_time_limit_s']:.2f}s, "
            f"applied {budget['applied_time_limit_s']:.2f}s."
        )
        if budget.get("unlimited"):
            self.log(
                "No time limit. This prefix stays inside the best-route ceiling "
                "until its frontier finishes. If memory fills, the frontier is stored "
                "on disk and the same prefix continues. The deal is optimised only when "
                "every prefix inside the ceiling has a finished frontier."
            )
        elif float(budget["applied_time_limit_s"]) <= 0:
            self.log("Campaign allowance is exhausted. This attempt was not started.")
            return {"attempts": [{"stop_reason": "time limit"}]}

        def progress(line: str) -> None:
            self.log(line, persist=False)

        unlimited = bool((self.campaign.get("settings") or {}).get("unlimited"))
        unique_cap = int(cfg["max_unique"])
        spill_dir = None
        if unlimited:
            unique_cap = max(unique_cap, DISK_IDENTITY_CAP)
            resume = cfg.get("resume_frontier")
            spill_dir = str(resume or (search_dir / "frontier.sqlite"))
        return run_prefix_attempt(
            action_index=int(job["index"]),
            time_limit_s=float(budget["applied_time_limit_s"]),
            max_unique=unique_cap,
            memory_mb=float(cfg["requested_rss_mb"]),
            checkpoint_s=float(cfg["checkpoint_s"]),
            output_dir=search_dir,
            root=self.root,
            route_label=str(job["route_label"]),
            incumbent=int(self.campaign["incumbent_g"]),
            ceiling=int(job["identity"]["ceiling"]),
            routes=self.routes,
            verify_published=True,
            improvement_below=SEED_G,
            log=progress,
            spill_dir=spill_dir,
        )

    def finish(self, job: dict, document: Optional[dict], error: Optional[BaseException]) -> None:
        search_dir = self.directory / "jobs" / job["id"] / "search"
        if error is not None:
            outcome = classify_stop("failed", terminated=False, requested_stop=False)
            job["error"] = f"{type(error).__name__}: {error}"
            self.log(f"{job['id']} failed: {job['error']}")
        else:
            attempt = (document or {}).get("attempts", [{}])[-1]
            if job.get("deadline_limited") and str(attempt.get("stop_reason") or "") == "time limit":
                outcome = {
                    "state": "interrupted",
                    "exhausted": False,
                    "stop_reason": "deadline",
                    "recovery": RECOVERY_TEXT,
                }
            else:
                outcome = classify_stop(attempt.get("stop_reason"), terminated=False, requested_stop=False)
            job["unique"] = attempt.get("unique")
            job["elapsed_s"] = attempt.get("elapsed_s")
            job["peak_rss_mb"] = attempt.get("peak_rss_mb")
            job["wall_s"] = attempt.get("wall_s")
            applied = attempt.get("rss_abort_mb")
            if applied is not None:
                # Keep the planned configuration key stable. The runner's clamp
                # can move by a fraction of a megabyte between probes.
                job["applied_rss_mb"] = float(applied)
            self.log(
                f"Finished {job['id']} stop={outcome['stop_reason']} "
                f"unique={job.get('unique')} peak={job.get('peak_rss_mb')}."
                + ("" if outcome["exhausted"] else " Not an exhaustion claim.")
            )
        job["state"] = outcome["state"]
        job["exhausted"] = bool(outcome["exhausted"])
        job["stop_reason"] = outcome["stop_reason"]
        job["recovery"] = outcome["recovery"]
        job["finished_at"] = time.time()
        attempt_row = {}
        if document:
            rows = document.get("attempts") or []
            if rows and isinstance(rows[-1], dict):
                attempt_row = rows[-1]
        job["frontier_path"] = attempt_row.get("frontier_path")
        job["frontier_retained"] = bool(attempt_row.get("frontier_retained"))
        job["resume_from_unique"] = attempt_row.get("resume_from_unique")
        if job["frontier_retained"] and not job["exhausted"]:
            job["recovery"] = RETAINED_FRONTIER_TEXT
            started_unique = job.get("resume_from_unique")
            job["frontier_stuck"] = (
                started_unique is not None
                and int(job.get("unique") or 0) <= int(started_unique)
            )
        else:
            job["frontier_stuck"] = False
        if job["exhausted"]:
            suffix = ((document or {}).get("attempts") or [{}])[-1].get("suffix") or {}
            job["launch_ceiling"] = int(job["identity"]["ceiling"])
            if suffix.get("ceiling") is None:
                job["exhausted"] = False
                job["effective_ceiling"] = None
                job["exhaustion_ceiling_known"] = False
                job["exhaustion_scope"] = None
                job["exhaustion_ceiling_note"] = UNKNOWN_CEILING_NOTE
                self.log(UNKNOWN_CEILING_NOTE)
            else:
                job["effective_ceiling"] = int(suffix["ceiling"])
                job["exhaustion_ceiling_known"] = True
                job["exhaustion_scope"] = exhaustion_scope(job)
                self.log(f"Exhaustion scope: {job['exhaustion_scope']}")
        else:
            job["exhaustion_scope"] = None
        before = int(self.campaign["incumbent_g"])
        self.adopt_files()
        if int(self.campaign["incumbent_g"]) != before:
            self.campaign["jobs"] = [item for item in self.campaign["jobs"] if item.get("state") != "queued"]
            self.log(
                f"Incumbent is now {self.campaign['incumbent_g']}. "
                "Queued jobs were dropped and will be chosen again under the new ceiling."
            )
        self.save()
        self.write_state()
        del search_dir


def _latest_attempt(search_dir: Path) -> dict:
    payload = read_json(search_dir / "status.json")
    attempts = payload.get("attempts") or []
    if not attempts or not isinstance(attempts[-1], dict):
        return {}
    return attempts[-1]


def read_control(directory: Path) -> dict:
    return read_json(Path(directory) / "control.json")


def recover_campaign(directory: Path, *, requested_stop: bool) -> dict:
    campaign = OptimiserCampaign(directory)
    campaign.load()
    campaign.recover_running(requested_stop=requested_stop)
    campaign.write_state()
    return campaign.campaign


def supervise(directory: Path) -> int:
    campaign = OptimiserCampaign(directory)
    campaign.load()
    try:
        campaign.recover_running(requested_stop=False)
        campaign.campaign["phase"] = "planning"
        campaign.write_state()
        campaign.authenticate()
        while True:
            control = read_control(campaign.directory)
            command = str(control.get("command") or "stop")
            if command == "stop":
                campaign.campaign["phase"] = "stopped"
                campaign.log("Stop requested. No further job will start.")
                return 0
            if command == "run" and not control.get("run_started_at"):
                control["run_started_at"] = time.time()
                atomic_write_json(campaign.directory / "control.json", control)
                campaign.log("Started the campaign clock.")
            if command == "pause":
                if campaign.campaign.get("phase") != "paused":
                    campaign.campaign["phase"] = "paused"
                    campaign.log("Paused after the current attempt. No new job has started.")
                else:
                    campaign.write_state()
                time.sleep(0.4)
                continue
            if campaign.run_expired(control):
                campaign.campaign["phase"] = "finished"
                campaign.log("Campaign duration elapsed. No further job started.")
                return 0
            settings = control.get("settings") or {}
            campaign.apply_settings(settings)
            campaign.ensure_queue()
            job = campaign.next_queued()
            if job is None:
                unlimited = bool((campaign.campaign.get("settings") or {}).get("unlimited"))
                if unlimited and not campaign.boundary_exhausted():
                    campaign.campaign["phase"] = "running"
                    activity = campaign.campaign.get("activity") or []
                    if not activity or not str(activity[-1]).endswith(HELD_ROUTE_TEXT):
                        campaign.log(HELD_ROUTE_TEXT)
                    else:
                        campaign.write_state()
                    time.sleep(30)
                    campaign.release_one_hold()
                    continue
                campaign.campaign["phase"] = "finished"
                if unlimited:
                    campaign.log(EXHAUSTED_ROUTE_TEXT)
                else:
                    campaign.log("No distinct useful job remains. Identical capped work was not repeated.")
                return 0
            try:
                document = campaign.execute(job)
            except Exception as exc:
                campaign.finish(job, None, exc)
                continue
            campaign.finish(job, document, None)
    except Exception:
        campaign.campaign["phase"] = "failed"
        try:
            campaign.log("Supervisor failed.\n" + traceback.format_exc())
        except OSError:
            return 1
        return 1


def best_moves_path(directory: Path) -> Optional[Path]:
    payload = read_json(assert_campaign_dir(directory) / "campaign.json")
    best = payload.get("best") or {}
    path = best.get("path")
    if not path:
        return None
    candidate = Path(path)
    return candidate if candidate.is_file() else None


def open_verified_route(session, moves_path: Path) -> str:
    """Add a replay route through the existing session. History and campaigns stay."""

    if session.deal_id != DEAL_ID:
        raise ValueError("The optimiser opens verified lines for deal 4925153 only.")
    return session.load_solution(Path(moves_path))
