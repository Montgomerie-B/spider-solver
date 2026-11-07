"""Unattended suffix-assisted campaign for deal 4925153.

One worker selects bounded jobs from the accepted 140-move route. A finished
frontier is an exhaustion claim only for that prefix, physical state, cost,
rules and ceiling. A stop, a crash, or a cap is not.
"""

from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Optional

from spider.app_paths import local_app_root
from spider.autonomous_solve_campaign import atomic_write_json
from spider.incumbent_suffix import (
    HISTORICAL_LABELS,
    _adopted_label,
    authenticate_moves_path,
    bound_at,
    require_pre120_index,
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
EXTRA_INDEXES = (119, 116, 110, 80, 58)
RECOVERY_TEXT = (
    "Interrupted before a clean finish. The exact search frontier was not retained. "
    "A later attempt starts again from the saved authenticated prefix. "
    "This is not an exhaustion claim."
)
CAP_STOPS = frozenset({"time limit", "unique limit", "rss abort", "depth limit", "harvested", "solved"})


def default_optimiser_dir() -> Path:
    return local_app_root() / "PlayLab" / "Optimiser" / DEAL_ID


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
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {} if default is None else dict(default)
    return payload if isinstance(payload, dict) else {}


def normalise_settings(settings: dict) -> dict:
    duration = float(settings.get("campaign_duration_s") or 20 * 60)
    attempt = float(settings.get("attempt_time_limit_s") or 180)
    requested = float(settings.get("requested_rss_mb") or 3000)
    unique = settings.get("max_unique")
    if duration <= 0 or attempt <= 0 or requested <= 0:
        raise ValueError("duration, attempt time and memory must be positive")
    return {
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


def exhaustion_scope(job: dict) -> str:
    identity = job["identity"]
    ancestry = identity["ancestry"]
    return (
        f"exact authenticated prefix {ancestry['prefix_hash16']} "
        f"after action {ancestry['prefix_index']} of route {ancestry['route_hash16']}, "
        f"physical pack {identity['physical_pack']}, "
        f"accumulated g={identity['accumulated_g']}, "
        f"deal {DEAL_ID}, rules {identity['rules']}, "
        f"absolute ceiling {identity['ceiling']}, "
        f"compact suffix-assisted configuration"
    )


def _terminal(job: dict) -> bool:
    return str(job.get("state") or "queued") != "queued"


def covered_by_exhaustion(identity: dict, jobs: list) -> bool:
    for job in jobs:
        if not job.get("exhausted"):
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
        if int(identity["ceiling"]) <= int(previous["ceiling"]):
            return True
    return False


def identical_terminal(identity: dict, jobs: list) -> bool:
    key = work_key(identity)
    for job in jobs:
        if not _terminal(job):
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


def plan_jobs(route: dict, opening, *, ceiling: int, settings: dict, resources: dict, jobs: list) -> tuple[list, list]:
    """Queue eligible roots. Actions 100 and 90 are first when they are still useful."""

    cfg = configuration(settings, resources)
    notes = []
    created = []
    extras = []
    ordered = list(PRIORITY_INDEXES) + [index for index in EXTRA_INDEXES if index not in PRIORITY_INDEXES]
    actions = list(route["actions"])
    for index in ordered:
        try:
            checked = require_pre120_index(index)
        except ValueError as exc:
            notes.append(f"Skipped action {index}: {exc}")
            continue
        if checked > len(actions):
            notes.append(f"Skipped action {index}: past the end of route {route['label']}.")
            continue
        bound = bound_at(opening, actions, checked)
        prefix = tuple(actions[:checked])
        identity = {
            "physical_pack": bound["pack"],
            "accumulated_g": int(bound["g"]),
            "ancestry": {
                "route_label": str(route["label"]),
                "route_hash16": str(route["path_hash16"]),
                "prefix_index": checked,
                "prefix_hash16": action_path_hash(prefix),
            },
            "rules": RULES,
            "ceiling": int(ceiling),
            "configuration": dict(cfg),
        }
        if int(bound["f"]) > int(ceiling):
            notes.append(
                f"Skipped action {checked}: admissible f={bound['f']} is above ceiling {ceiling}."
            )
            continue
        already = jobs + created + extras
        if covered_by_exhaustion(identity, already):
            notes.append(f"Skipped action {checked}: already exhausted at this ceiling or a higher one.")
            continue
        if identical_terminal(identity, already):
            notes.append(f"Skipped action {checked}: an identical capped or finished job is already recorded.")
            continue
        if any(work_key(item["identity"]) == work_key(identity) for item in already):
            continue
        recovery = None
        if prefix_was_interrupted(identity["ancestry"]["prefix_hash16"], jobs):
            recovery = RECOVERY_TEXT
        job = {
            "id": "",
            "state": "queued",
            "index": checked,
            "route_label": str(route["label"]),
            "route_hash16": str(route["path_hash16"]),
            "bound": {"g": int(bound["g"]), "h": int(bound["h"]), "f": int(bound["f"])},
            "identity": identity,
            "exhausted": False,
            "exhaustion_scope": None,
            "stop_reason": None,
            "recovery": recovery,
            "priority": index in PRIORITY_INDEXES,
        }
        if index in PRIORITY_INDEXES:
            created.append(job)
        else:
            extras.append(job)
    extras.sort(key=lambda item: (int(item["bound"]["f"]), -int(item["index"])))
    chosen = created + extras
    next_number = 1 + max(
        [int(str(job["id"])[1:]) for job in jobs if str(job.get("id", "")).startswith("j")] or [0]
    )
    for job in chosen:
        job["id"] = f"j{next_number}"
        next_number += 1
    return chosen, notes


class OptimiserCampaign:
    def __init__(self, directory: Path, root: Optional[Path] = None):
        from spider.app_paths import repo_root

        self.directory = assert_campaign_dir(directory)
        self.root = Path(root) if root is not None else repo_root()
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
        return self.campaign

    def save(self) -> None:
        atomic_write_json(self.campaign_path, self.campaign)

    def log(self, line: str, *, persist: bool = True) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.campaign["activity"] = (list(self.campaign.get("activity") or []) + [f"{stamp}  {line}"])[-200:]
        if persist:
            self.save()
        self.write_state()

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
                "id": current["id"],
                "index": current["index"],
                "route_label": current["route_label"],
                "bound": current.get("bound"),
                "state": current["state"],
            },
            "jobs": [
                {
                    "id": job["id"],
                    "state": job["state"],
                    "index": job["index"],
                    "exhausted": bool(job.get("exhausted")),
                    "stop_reason": job.get("stop_reason"),
                    "recovery": job.get("recovery"),
                    "bound": job.get("bound"),
                }
                for job in self.campaign.get("jobs") or []
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
        """Replay every published game under this campaign and keep a strictly cheaper one."""

        adopted = []
        for path in self._published_files():
            try:
                route = authenticate_moves_path(self.opening, path, label="published", root=self.root)
            except (OSError, ValueError) as exc:
                self.log(f"Rejected {path.name}: {exc}")
                continue
            if int(route["g"]) >= int(self.campaign["incumbent_g"]):
                continue
            if any(item["path_hash16"] == route["path_hash16"] for item in self.routes):
                self._remember_best(route, path)
                continue
            route["label"] = _adopted_label(self.routes, int(route["g"]), route["path_hash16"])
            route["adopted"] = True
            self.routes.append(route)
            destination = self.directory / "verified" / path.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.is_file():
                destination.write_bytes(path.read_bytes())
            self._remember_best(route, destination)
            adopted.append(route)
            self.log(
                f"Adopted verified {route['g']} ({route['path_hash16']}) after a full opening replay. "
                f"Ceiling is now {self.campaign['ceiling']}."
            )
        return adopted

    def _remember_best(self, route: dict, path: Path) -> None:
        self.campaign["incumbent_g"] = int(route["g"])
        self.campaign["ceiling"] = int(route["g"]) - 1
        self.campaign["best"] = {
            "g": int(route["g"]),
            "path": str(path),
            "path_hash16": route["path_hash16"],
            "verified": True,
            "source": "replay",
        }

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
        resources = resource_report(chosen["requested_rss_mb"], chosen["max_unique"])
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
                f"{job['index']} (f={job['bound']['f']})" for job in new_jobs
            )
            self.log(f"Queued {described}.")
        else:
            self.save()

    def next_queued(self) -> Optional[dict]:
        for job in self.campaign["jobs"]:
            if job.get("state") == "queued":
                return job
        return None

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
        self.campaign["phase"] = "running"
        job["state"] = "running"
        job["started_at"] = time.time()
        self.log(
            f"Started {job['id']} on action {job['index']} of route {job['route_label']}. "
            f"g={job['bound']['g']} h={job['bound']['h']} f={job['bound']['f']}. "
            f"Requested RSS {cfg['requested_rss_mb']:.2f} MB, "
            f"effective {cfg['effective_rss_mb']:.2f} MB."
        )

        def progress(line: str) -> None:
            self.log(line, persist=False)

        return run_prefix_attempt(
            action_index=int(job["index"]),
            time_limit_s=float(cfg["time_limit_s"]),
            max_unique=int(cfg["max_unique"]),
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
        )

    def finish(self, job: dict, document: Optional[dict], error: Optional[BaseException]) -> None:
        search_dir = self.directory / "jobs" / job["id"] / "search"
        if error is not None:
            outcome = classify_stop("failed", terminated=False, requested_stop=False)
            job["error"] = f"{type(error).__name__}: {error}"
            self.log(f"{job['id']} failed: {job['error']}")
        else:
            attempt = (document or {}).get("attempts", [{}])[-1]
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
        job["exhaustion_scope"] = exhaustion_scope(job) if job["exhausted"] else None
        job["finished_at"] = time.time()
        if job["exhausted"]:
            self.log(f"Exhaustion scope: {job['exhaustion_scope']}")
        before = int(self.campaign["incumbent_g"])
        self.adopt_files()
        if int(self.campaign["incumbent_g"]) < before:
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
                campaign.campaign["phase"] = "finished"
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
        campaign.log("Supervisor failed.\n" + traceback.format_exc())
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
